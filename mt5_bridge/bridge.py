from flask import Flask, jsonify, request
import MetaTrader5 as mt5
import math
import os
import socket
import threading

app = Flask(__name__)
LOCK = threading.Lock()
MAGIC = 630063


def ensure_mt5():
    if mt5.terminal_info() is not None and mt5.account_info() is not None:
        return True
    return bool(mt5.initialize())


def account_type_name(info):
    if info is None:
        return "UNKNOWN"
    if info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
        return "DEMO"
    if info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
        return "REAL"
    if info.trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
        return "CONTEST"
    return "UNKNOWN"


def resolve_symbol(raw):
    base = (raw or "").upper().replace("/", "").replace("_", "").replace("-", "")
    if not base:
        return None
    if mt5.symbol_info(base) is not None:
        mt5.symbol_select(base, True)
        return base
    all_symbols = mt5.symbols_get() or []
    # Prefer exact normalized name, then common broker suffixes/prefixes.
    for s in all_symbols:
        normalized = s.name.upper().replace("/", "").replace("_", "").replace("-", "").replace(".", "")
        if normalized == base:
            mt5.symbol_select(s.name, True)
            return s.name
    for s in all_symbols:
        n = s.name.upper().replace("/", "").replace("_", "").replace("-", "").replace(".", "")
        if n.startswith(base) or n.endswith(base):
            mt5.symbol_select(s.name, True)
            return s.name
    return None


def positions_payload():
    positions = mt5.positions_get() or []
    return len(positions), sum(float(p.profit) for p in positions)


@app.get('/health')
def health():
    with LOCK:
        ok = ensure_mt5()
        info = mt5.account_info() if ok else None
        count, floating = positions_payload() if info else (0, 0.0)
        return jsonify({
            "ok": bool(ok),
            "mt5_connected": info is not None,
            "account_type": account_type_name(info),
            "login": int(info.login) if info else None,
            "server": info.server if info else None,
            "balance": float(info.balance) if info else None,
            "equity": float(info.equity) if info else None,
            "currency": info.currency if info else "USD",
            "positions": count,
            "floating_pl": floating,
            "bridge_version": "6.3"
        })


@app.get('/quote')
def quote():
    raw = request.args.get('symbol', '')
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        symbol = resolve_symbol(raw)
        if not symbol:
            return jsonify(ok=False, message=f"Symbol not found: {raw}"), 404
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return jsonify(ok=False, message=f"No tick for {symbol}"), 503
        return jsonify(ok=True, symbol=symbol, bid=float(tick.bid), ask=float(tick.ask), time=int(tick.time))


def floor_volume(value, step, minimum, maximum):
    if step <= 0:
        step = minimum
    value = math.floor(value / step + 1e-12) * step
    value = min(value, maximum)
    decimals = max(0, len(str(step).split('.')[-1]) if '.' in str(step) else 0)
    return round(value, decimals)


def risk_volume(symbol, order_type, price, sl, risk_pct, equity):
    info = mt5.symbol_info(symbol)
    if not info or sl <= 0 or price <= 0 or price == sl:
        return None, "Invalid SL/price"
    risk_money = equity * (risk_pct / 100.0)
    pnl_one_lot = mt5.order_calc_profit(order_type, symbol, 1.0, price, sl)
    if pnl_one_lot is None or pnl_one_lot == 0:
        return None, "order_calc_profit failed"
    loss_one_lot = abs(float(pnl_one_lot))
    raw = risk_money / loss_one_lot
    vol = floor_volume(raw, info.volume_step, info.volume_min, info.volume_max)
    if vol < info.volume_min:
        return None, f"Calculated lot {raw:.4f} is below broker minimum {info.volume_min}"
    return vol, None


@app.post('/signal')
def signal():
    data = request.get_json(silent=True) or {}
    with LOCK:
        if not ensure_mt5():
            return jsonify(accepted=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        if account is None:
            return jsonify(accepted=False, message="No MT5 account"), 503
        if account_type_name(account) != "DEMO":
            return jsonify(accepted=False, message="V6.3 bridge blocks trading on non-DEMO accounts"), 403

        side = str(data.get('signal', '')).upper()
        if side not in ('BUY', 'SELL'):
            return jsonify(accepted=False, message="WAIT/no trade")

        symbol = resolve_symbol(data.get('symbol'))
        if not symbol:
            return jsonify(accepted=False, message="MT5 symbol not found"), 404

        max_positions = int(data.get('max_positions', 1))
        positions = mt5.positions_get() or []
        if len(positions) >= max_positions:
            return jsonify(accepted=False, message=f"Max positions reached: {len(positions)}/{max_positions}")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return jsonify(accepted=False, message="No current MT5 quote"), 503

        order_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if side == 'BUY' else tick.bid)
        api_entry = float(data.get('api_entry') or 0)
        max_drift = float(data.get('max_price_drift_pct') or 0.05)
        if api_entry > 0:
            drift = abs(price - api_entry) / api_entry * 100.0
            if drift > max_drift:
                return jsonify(accepted=False, message=f"Price drift {drift:.4f}% > {max_drift:.4f}%")

        sl = float(data.get('sl') or 0)
        tp = float(data.get('tp1') or 0)
        risk_pct = float(data.get('risk_pct') or 0.5)
        volume, err = risk_volume(symbol, order_type, price, sl, risk_pct, float(account.equity))
        if err:
            return jsonify(accepted=False, message=err)

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": MAGIC,
            "comment": "FXM1 V6.3 DEMO",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result is None:
            return jsonify(accepted=False, message=f"order_send returned None: {mt5.last_error()}"), 500
        ok = result.retcode == mt5.TRADE_RETCODE_DONE
        return jsonify(
            accepted=ok,
            message=("DEMO order opened" if ok else f"MT5 retcode {result.retcode}: {result.comment}"),
            ticket=int(result.order) if result.order else None,
            deal=int(result.deal) if result.deal else None,
            symbol=symbol,
            volume=volume,
            execution_price=price,
            retcode=int(result.retcode)
        )


@app.post('/close-all')
def close_all():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        if account_type_name(account) != "DEMO":
            return jsonify(ok=False, message="V6.3 bridge blocks CLOSE ALL on non-DEMO accounts"), 403
        positions = mt5.positions_get() or []
        results = []
        for p in positions:
            tick = mt5.symbol_info_tick(p.symbol)
            if tick is None:
                results.append({"ticket": int(p.ticket), "ok": False, "message": "no tick"})
                continue
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
            price = float(tick.bid if is_buy else tick.ask)
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": int(p.ticket),
                "symbol": p.symbol,
                "volume": float(p.volume),
                "type": close_type,
                "price": price,
                "deviation": 30,
                "magic": MAGIC,
                "comment": "FXM1 V6.3 CLOSE ALL",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            r = mt5.order_send(req)
            ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
            results.append({
                "ticket": int(p.ticket),
                "ok": ok,
                "retcode": int(r.retcode) if r else None,
                "message": r.comment if r else str(mt5.last_error())
            })
        success = all(x['ok'] for x in results) if results else True
        return jsonify(ok=success, message=f"Closed {sum(1 for x in results if x['ok'])}/{len(results)} positions", results=results)


if __name__ == '__main__':
    if not mt5.initialize():
        print('WARNING: MT5 is not connected yet:', mt5.last_error())
        print('Open MetaTrader 5 on Windows and log in to your DEMO account, then retry /health.')
    host = '0.0.0.0'
    port = int(os.environ.get('FXM1_PORT', '8000'))
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = 'YOUR_PC_IP'
    print(f'FX M1 MT5 Bridge V6.3: http://{ip}:{port}')
    app.run(host=host, port=port, debug=False, threaded=True)
