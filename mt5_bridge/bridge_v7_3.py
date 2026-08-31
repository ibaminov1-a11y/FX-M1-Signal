from flask import Flask, jsonify, request
import MetaTrader5 as mt5
import math
import os
import socket
import threading
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
LOCK = threading.RLock()

BRIDGE_VERSION = "7.4.5"
MAGIC = 720072

# Safety default: real-account execution remains OFF until explicitly enabled
ALLOW_REAL = os.environ.get("FXM1_ALLOW_REAL", "0").strip().lower() in ("1", "true", "yes", "on")


def ensure_mt5():
    try:
        if mt5.terminal_info() is not None and mt5.account_info() is not None:
            return True
    except Exception:
        pass
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


def trading_allowed(info):
    if info is None:
        return False, "No MT5 account"
    kind = account_type_name(info)
    if kind == "DEMO":
        return True, ""
    if kind == "REAL" and ALLOW_REAL:
        return True, ""
    if kind == "REAL":
        return False, f"REAL trading is disabled on Bridge V{BRIDGE_VERSION}. Set FXM1_ALLOW_REAL=1 only after DEMO validation."
    return False, f"Trading blocked for account type {kind}"


def normalize_symbol_name(value):
    return (value or "").upper().replace("/", "").replace("_", "").replace("-", "").replace(".", "")


def resolve_symbol(raw):
    base = normalize_symbol_name(raw)
    if not base:
        return None

    direct = mt5.symbol_info(base)
    if direct is not None:
        mt5.symbol_select(base, True)
        return base

    all_symbols = mt5.symbols_get() or []
    exact = []
    fuzzy = []
    for s in all_symbols:
        n = normalize_symbol_name(s.name)
        if n == base:
            exact.append(s.name)
        elif n.startswith(base) or n.endswith(base):
            fuzzy.append(s.name)

    for name in exact + fuzzy:
        if mt5.symbol_select(name, True):
            return name
    return None


def safe_float(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def clamp(v, lo, hi):
    return max(lo, min(float(v), hi))


def scalp_money_limits(equity, cfg=None):
    """Money caps for SCALP. Scale down on small accounts, never above requested hard ceilings."""
    cfg = cfg or {}
    eq = max(0.0, float(equity or 0.0))
    risk_cap = max(0.10, safe_float(cfg.get('scalp_risk_usd_cap'), 2.0))
    hard_cap = max(risk_cap, safe_float(cfg.get('scalp_hard_loss_usd_cap'), 5.0))
    protect_cap = max(0.10, safe_float(cfg.get('scalp_profit_protect_usd_cap'), 1.5))
    trail_cap = max(protect_cap, safe_float(cfg.get('scalp_trail_start_usd_cap'), 2.5))
    tp_cap = max(protect_cap, safe_float(cfg.get('scalp_take_profit_usd_cap'), 3.0))
    basket_cap_req = max(risk_cap, safe_float(cfg.get('scalp_basket_risk_usd_cap'), 16.0))

    # V7.4.5: true micro-scalp cash sizing. A large DEMO balance must NOT create a large lot.
    # Small future accounts scale down automatically.
    planned = min(risk_cap, max(0.50, eq * 0.002))
    hard_loss = min(hard_cap, max(1.00, eq * 0.005))
    protect = min(protect_cap, max(0.35, eq * 0.0015))
    trail_start = min(trail_cap, max(0.60, eq * 0.0025))
    take_profit = min(tp_cap, max(0.75, eq * 0.003))
    basket_risk = min(basket_cap_req, max(planned * 8.0, planned))
    return {
        'planned_risk_usd': round(planned, 2),
        'hard_loss_usd': round(hard_loss, 2),
        'protect_usd': round(protect, 2),
        'trail_start_usd': round(trail_start, 2),
        'take_profit_usd': round(take_profit, 2),
        'basket_risk_usd': round(basket_risk, 2),
    }


def floor_volume(value, step, minimum, maximum):
    step = step if step and step > 0 else minimum
    if not step or step <= 0:
        return None
    value = math.floor(value / step + 1e-12) * step
    value = max(minimum, min(value, maximum))
    decimals = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]) if "." in f"{step:.10f}".rstrip("0") else 0)
    return round(value, decimals)


def symbol_payload(symbol):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None:
        return None
    return {
        "symbol": symbol,
        "description": getattr(info, "description", ""),
        "digits": int(info.digits),
        "point": float(info.point),
        "trade_tick_size": float(getattr(info, "trade_tick_size", 0.0) or 0.0),
        "trade_tick_value": float(getattr(info, "trade_tick_value", 0.0) or 0.0),
        "contract_size": float(getattr(info, "trade_contract_size", 0.0) or 0.0),
        "volume_min": float(info.volume_min),
        "volume_max": float(info.volume_max),
        "volume_step": float(info.volume_step),
        "trade_stops_level": int(getattr(info, "trade_stops_level", 0) or 0),
        "spread_points": int(getattr(info, "spread", 0) or 0),
        "bid": float(tick.bid) if tick else None,
        "ask": float(tick.ask) if tick else None,
        "tick_time": int(tick.time) if tick else None,
    }


def position_payload(p):
    tick = mt5.symbol_info_tick(p.symbol)
    current_price = None
    if tick:
        current_price = float(tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask)
    return {
        "ticket": int(p.ticket),
        "identifier": int(getattr(p, "identifier", p.ticket)),
        "symbol": p.symbol,
        "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
        "volume": float(p.volume),
        "open_price": float(p.price_open),
        "current_price": current_price,
        "sl": float(p.sl),
        "tp": float(p.tp),
        "profit": float(p.profit),
        "swap": float(getattr(p, "swap", 0.0)),
        "magic": int(p.magic),
        "comment": p.comment,
        "time": int(p.time),
        "time_msc": int(getattr(p, "time_msc", 0) or 0),
    }


def positions_payload():
    positions = mt5.positions_get() or []
    payload = [position_payload(p) for p in positions]
    return payload


def calc_risk_volume(symbol, order_type, price, sl, risk_pct, equity):
    info = mt5.symbol_info(symbol)
    if info is None:
        return None, None, "Symbol info unavailable"
    if sl <= 0 or price <= 0 or price == sl:
        return None, None, "Invalid SL/price"

    risk_money = equity * (risk_pct / 100.0)
    if risk_money <= 0:
        return None, None, "Risk money is zero"

    pnl_one_lot = mt5.order_calc_profit(order_type, symbol, 1.0, price, sl)
    if pnl_one_lot is None or pnl_one_lot == 0:
        return None, None, f"order_calc_profit failed: {mt5.last_error()}"

    one_lot_loss = abs(float(pnl_one_lot))
    raw_volume = risk_money / one_lot_loss

    if raw_volume < float(info.volume_min) - 1e-12:
        return None, {
            "risk_money": risk_money,
            "raw_volume": raw_volume,
            "broker_min": float(info.volume_min)
        }, f"Calculated lot {raw_volume:.4f} is below broker minimum {info.volume_min}"

    vol = floor_volume(raw_volume, float(info.volume_step), float(info.volume_min), float(info.volume_max))
    if vol is None:
        return None, None, "Cannot normalize lot"

    calc_loss = mt5.order_calc_profit(order_type, symbol, vol, price, sl)
    actual_risk = abs(float(calc_loss)) if calc_loss is not None else None

    return vol, {
        "risk_pct": risk_pct,
        "risk_money_target": risk_money,
        "risk_money_actual": actual_risk,
        "raw_volume": raw_volume,
        "volume": vol,
        "sl_distance": abs(price - sl)
    }, None


def margin_payload(order_type, symbol, volume, price, account):
    margin = mt5.order_calc_margin(order_type, symbol, volume, price)
    if margin is None:
        return {
            "required_margin": None,
            "free_margin_before": float(account.margin_free),
            "free_margin_after": None,
            "margin_level_before": float(account.margin_level),
        }
    margin = float(margin)
    return {
        "required_margin": margin,
        "free_margin_before": float(account.margin_free),
        "free_margin_after": float(account.margin_free) - margin,
        "margin_level_before": float(account.margin_level),
    }


def filling_mode_candidates(symbol):
    """Return safe ORDER_FILLING candidates. SYMBOL filling_mode is a bit-mask,
    while ORDER_FILLING_* uses different enum values, so they must not be compared directly.
    """
    info = mt5.symbol_info(symbol)
    out = []
    flags = int(getattr(info, "filling_mode", 0) or 0) if info is not None else 0
    # SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2. RETURN may be allowed depending on execution mode.
    if flags & 2:
        out.append(mt5.ORDER_FILLING_IOC)
    if flags & 1:
        out.append(mt5.ORDER_FILLING_FOK)
    out.append(mt5.ORDER_FILLING_RETURN)
    out.extend([mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK])
    unique = []
    for x in out:
        if x not in unique:
            unique.append(x)
    return unique


def filling_mode_for(symbol):
    return filling_mode_candidates(symbol)[0]


def normalize_order_stops(symbol, side, tick, sl, tp):
    info = mt5.symbol_info(symbol)
    if info is None:
        return sl, tp
    point = float(info.point or 0.00001)
    digits = int(info.digits)
    # Extra safety buffer above broker stops level because Bid/Ask can move between check and send.
    min_stop = max(point * (int(getattr(info, "trade_stops_level", 0) or 0) + 5), point * 8)
    bid, ask = float(tick.bid), float(tick.ask)
    if side == "BUY":
        if sl > 0: sl = min(sl, bid - min_stop)
        if tp > 0: tp = max(tp, ask + min_stop)
    else:
        if sl > 0: sl = max(sl, ask + min_stop)
        if tp > 0: tp = min(tp, bid - min_stop)
    return (round(sl, digits) if sl > 0 else 0.0,
            round(tp, digits) if tp > 0 else 0.0)


def send_deal_with_fill_fallback(req):
    """Try broker-supported filling policies and keep diagnostics for the APK/Bridge log."""
    attempts = []
    last = None
    for fill in filling_mode_candidates(req["symbol"]):
        trial = dict(req)
        trial["type_filling"] = fill
        check = mt5.order_check(trial)
        check_code = int(check.retcode) if check is not None else None
        check_comment = check.comment if check is not None else str(mt5.last_error())
        result = mt5.order_send(trial)
        last = result
        attempts.append({
            "filling": int(fill),
            "check_retcode": check_code,
            "check_comment": check_comment,
            "retcode": int(result.retcode) if result is not None else None,
            "comment": result.comment if result is not None else str(mt5.last_error()),
        })
        if result is not None and result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
            return result, attempts
        # 10030 = invalid/unsupported filling. Try the next policy.
        if result is not None and int(result.retcode) != 10030:
            break
    return last, attempts


def close_position_internal(p, volume=None, comment=None):
    if comment is None:
        comment = f"FXM1 V{BRIDGE_VERSION} CLOSE"
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return False, {"message": "No current tick"}

    is_buy = p.type == mt5.POSITION_TYPE_BUY
    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    price = float(tick.bid if is_buy else tick.ask)
    info = mt5.symbol_info(p.symbol)
    vol = float(p.volume if volume is None else volume)

    if info is not None:
        vol = floor_volume(vol, float(info.volume_step), float(info.volume_min), float(info.volume_max))
        if vol is None or vol <= 0:
            return False, {"message": "Invalid close volume"}
        vol = min(vol, float(p.volume))

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": int(p.ticket),
        "symbol": p.symbol,
        "volume": vol,
        "type": close_type,
        "price": price,
        "deviation": 30,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode_for(p.symbol),
    }
    r = mt5.order_send(req)
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    return ok, {
        "ticket": int(p.ticket),
        "volume": vol,
        "execution_price": price,
        "retcode": int(r.retcode) if r else None,
        "message": r.comment if r else str(mt5.last_error()),
        "deal": int(r.deal) if r and r.deal else None,
    }


@app.errorhandler(404)
def not_found(_):
    return jsonify(ok=False, error="ENDPOINT_NOT_FOUND", message="Endpoint not found", bridge_version=BRIDGE_VERSION), 404


@app.errorhandler(Exception)
def unhandled(e):
    return jsonify(ok=False, error="BRIDGE_ERROR", message=str(e), bridge_version=BRIDGE_VERSION), 500


@app.get("/health")
def health():
    with LOCK:
        ok = ensure_mt5()
        info = mt5.account_info() if ok else None
        positions = positions_payload() if info else []
        floating = sum(x["profit"] for x in positions)
        return jsonify({
            "ok": bool(ok),
            "service": "FX M1 MT5 Bridge",
            "bridge_version": BRIDGE_VERSION,
            "api_version": 7,
            "build_tag": "AUDITED_FULL_740",
            "mt5_connected": info is not None,
            "account_type": account_type_name(info),
            "real_trading_enabled": bool(ALLOW_REAL),
            "login": int(info.login) if info else None,
            "server": info.server if info else None,
            "balance": float(info.balance) if info else None,
            "equity": float(info.equity) if info else None,
            "profit": float(info.profit) if info else None,
            "currency": info.currency if info else "USD",
            "leverage": int(info.leverage) if info else None,
            "margin": float(info.margin) if info else None,
            "free_margin": float(info.margin_free) if info else None,
            "margin_level": float(info.margin_level) if info else None,
            "positions": len(positions),
            "floating_pl": floating,
            "capabilities": [
                "quote", "symbols", "positions", "position_management",
                "risk_sizing", "margin_check", "history", "stats", "close_all"
            ]
        })


@app.get("/account")
def account():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        info = mt5.account_info()
        if info is None:
            return jsonify(ok=False, message="No MT5 account"), 503
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, account={
            "type": account_type_name(info),
            "login": int(info.login),
            "server": info.server,
            "currency": info.currency,
            "balance": float(info.balance),
            "equity": float(info.equity),
            "profit": float(info.profit),
            "leverage": int(info.leverage),
            "margin": float(info.margin),
            "free_margin": float(info.margin_free),
            "margin_level": float(info.margin_level),
        })


@app.get("/quote")
def quote():
    raw = request.args.get("symbol", "")
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        symbol = resolve_symbol(raw)
        if not symbol:
            return jsonify(ok=False, error="SYMBOL_NOT_FOUND", message=f"Symbol not found: {raw}"), 404
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick is None or info is None:
            return jsonify(ok=False, message=f"No quote for {symbol}"), 503
        spread_price = float(tick.ask - tick.bid)
        spread_points = spread_price / float(info.point) if info.point else None
        return jsonify(
            ok=True,
            bridge_version=BRIDGE_VERSION,
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            mid=(float(tick.bid) + float(tick.ask)) / 2.0,
            spread=spread_price,
            spread_points=spread_points,
            time=int(tick.time),
            digits=int(info.digits),
            point=float(info.point)
        )


@app.get("/symbols")
def symbols():
    query = (request.args.get("q") or "").strip().upper()
    limit = min(max(int(request.args.get("limit", "300")), 1), 2000)
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        out = []
        for s in (mt5.symbols_get() or []):
            if query and query not in s.name.upper() and query not in (s.description or "").upper():
                continue
            out.append({
                "symbol": s.name,
                "description": s.description,
                "visible": bool(s.visible),
                "selected": bool(s.select),
                "digits": int(s.digits),
                "volume_min": float(s.volume_min),
                "volume_max": float(s.volume_max),
                "volume_step": float(s.volume_step),
            })
            if len(out) >= limit:
                break
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, count=len(out), symbols=out)


@app.get("/symbol-info")
def symbol_info():
    raw = request.args.get("symbol", "")
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        symbol = resolve_symbol(raw)
        if not symbol:
            return jsonify(ok=False, error="SYMBOL_NOT_FOUND", message=f"Symbol not found: {raw}"), 404
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, data=symbol_payload(symbol))


@app.get("/positions")
def positions():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        data = positions_payload()
        return jsonify(
            ok=True,
            bridge_version=BRIDGE_VERSION,
            count=len(data),
            floating_pl=sum(x["profit"] for x in data),
            positions=data
        )


@app.get("/position/<int:ticket>")
def position(ticket):
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        arr = mt5.positions_get(ticket=ticket)
        if not arr:
            return jsonify(ok=False, error="POSITION_NOT_FOUND", message=f"Position {ticket} not found"), 404
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, position=position_payload(arr[0]))


@app.post("/position/<int:ticket>/close")
def close_position(ticket):
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403
        arr = mt5.positions_get(ticket=ticket)
        if not arr:
            return jsonify(ok=False, error="POSITION_NOT_FOUND", message=f"Position {ticket} not found"), 404
        ok, result = close_position_internal(arr[0])
        return jsonify(ok=ok, bridge_version=BRIDGE_VERSION, **result), (200 if ok else 500)


@app.post("/position/<int:ticket>/partial-close")
def partial_close(ticket):
    data = request.get_json(silent=True) or {}
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403
        arr = mt5.positions_get(ticket=ticket)
        if not arr:
            return jsonify(ok=False, error="POSITION_NOT_FOUND", message=f"Position {ticket} not found"), 404
        p = arr[0]
        percent = safe_float(data.get("percent"), 50.0)
        volume = safe_float(data.get("volume"), 0.0)
        if volume <= 0:
            volume = float(p.volume) * max(0.01, min(percent, 99.0)) / 100.0
        ok, result = close_position_internal(p, volume=volume, comment=f"FXM1 V{BRIDGE_VERSION} PARTIAL")
        return jsonify(ok=ok, bridge_version=BRIDGE_VERSION, **result), (200 if ok else 500)


@app.post("/position/<int:ticket>/modify")
def modify_position(ticket):
    data = request.get_json(silent=True) or {}
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403
        arr = mt5.positions_get(ticket=ticket)
        if not arr:
            return jsonify(ok=False, error="POSITION_NOT_FOUND", message=f"Position {ticket} not found"), 404
        p = arr[0]
        sl = safe_float(data.get("sl"), float(p.sl))
        tp = safe_float(data.get("tp"), float(p.tp))
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": p.symbol,
            "sl": sl,
            "tp": tp,
            "magic": MAGIC,
            "comment": f"FXM1 V{BRIDGE_VERSION} MODIFY",
        }
        r = mt5.order_send(req)
        ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
        return jsonify(
            ok=ok,
            bridge_version=BRIDGE_VERSION,
            ticket=ticket,
            sl=sl,
            tp=tp,
            retcode=int(r.retcode) if r else None,
            message=r.comment if r else str(mt5.last_error())
        ), (200 if ok else 500)


@app.post("/position/<int:ticket>/breakeven")
def breakeven(ticket):
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403
        arr = mt5.positions_get(ticket=ticket)
        if not arr:
            return jsonify(ok=False, error="POSITION_NOT_FOUND", message=f"Position {ticket} not found"), 404
        p = arr[0]
        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": int(ticket),
            "symbol": p.symbol,
            "sl": float(p.price_open),
            "tp": float(p.tp),
            "magic": MAGIC,
            "comment": f"FXM1 V{BRIDGE_VERSION} BE",
        }
        r = mt5.order_send(req)
        ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
        return jsonify(ok=ok, ticket=ticket, sl=float(p.price_open),
                       retcode=int(r.retcode) if r else None,
                       message=r.comment if r else str(mt5.last_error())), (200 if ok else 500)


@app.post("/risk-preview")
def risk_preview():
    data = request.get_json(silent=True) or {}
    raw_symbol = data.get("symbol", "")
    side = str(data.get("side") or data.get("signal") or "").upper()
    risk_pct = safe_float(data.get("risk_pct"), 0.5)
    sl = safe_float(data.get("sl"), 0)
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        symbol = resolve_symbol(raw_symbol)
        if not symbol:
            return jsonify(ok=False, error="SYMBOL_NOT_FOUND", message=f"Symbol not found: {raw_symbol}"), 404
        if side not in ("BUY", "SELL"):
            return jsonify(ok=False, message="side must be BUY or SELL"), 400
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return jsonify(ok=False, message="No current MT5 quote"), 503
        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if side == "BUY" else tick.bid)
        volume, risk, err = calc_risk_volume(symbol, order_type, price, sl, risk_pct, float(account.equity))
        if err:
            return jsonify(ok=False, message=err, risk=risk), 400
        margin = margin_payload(order_type, symbol, volume, price, account)
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, symbol=symbol, side=side,
                       execution_price=price, volume=volume, risk=risk, margin=margin,
                       leverage=int(account.leverage), equity=float(account.equity))



def position_risk_money(p):
    """Estimated cash downside to SL. A stop already beyond breakeven has zero downside risk."""
    try:
        if not p.sl or p.sl <= 0:
            return None
        open_price = float(p.price_open)
        stop_price = float(p.sl)
        if p.type == mt5.POSITION_TYPE_BUY and stop_price >= open_price:
            return 0.0
        if p.type == mt5.POSITION_TYPE_SELL and stop_price <= open_price:
            return 0.0
        order_type = mt5.ORDER_TYPE_BUY if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_SELL
        pnl = mt5.order_calc_profit(order_type, p.symbol, float(p.volume), open_price, stop_price)
        return abs(min(0.0, float(pnl))) if pnl is not None else None
    except Exception:
        return None


def basket_snapshot(positions, symbol, side, equity):
    expected_type = mt5.POSITION_TYPE_BUY if side == "BUY" else mt5.POSITION_TYPE_SELL
    basket = [p for p in positions if p.symbol == symbol and p.type == expected_type and int(getattr(p, "magic", 0)) == MAGIC]
    total_volume = sum(float(p.volume) for p in basket)
    avg_entry = (sum(float(p.price_open) * float(p.volume) for p in basket) / total_volume) if total_volume > 0 else None
    risks = [position_risk_money(p) for p in basket]
    known_risk = sum(x for x in risks if x is not None)
    risk_pct = (known_risk / equity * 100.0) if equity and equity > 0 else 0.0
    latest_time = max((int(getattr(p, "time", 0) or 0) for p in basket), default=0)
    return basket, total_volume, avg_entry, known_risk, risk_pct, latest_time

@app.post("/signal")
def signal():
    data = request.get_json(silent=True) or {}
    raw_symbol = data.get("symbol", "")
    side = str(data.get("signal") or data.get("side") or "").upper()
    if str(data.get("signal_mode") or "").upper() == "SCALP":
        update_scalp_supervisor_cfg(data)

    with LOCK:
        if not ensure_mt5():
            return jsonify(accepted=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503

        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(accepted=False, message=reason, bridge_version=BRIDGE_VERSION), 403

        if side not in ("BUY", "SELL"):
            return jsonify(accepted=False, message="Signal must be BUY or SELL"), 400

        max_positions = max(1, min(int(data.get("max_positions") or 1), 10))
        current_positions = mt5.positions_get() or []

        symbol = resolve_symbol(raw_symbol)
        if not symbol:
            return jsonify(accepted=False, error="SYMBOL_NOT_FOUND", message=f"Symbol not found: {raw_symbol}"), 404

        basket_mode = bool(data.get("basket_mode", False)) and str(data.get("signal_mode") or "").upper() == "SCALP"
        same_symbol = [p for p in current_positions if p.symbol == symbol]

        if not basket_mode:
            if len(current_positions) >= max_positions:
                return jsonify(accepted=False, message=f"Max positions reached: {len(current_positions)}/{max_positions}"), 409
            if same_symbol and not bool(data.get("allow_same_symbol_multiple", False)):
                return jsonify(accepted=False, message=f"Position for {symbol} already exists"), 409
        else:
            basket, basket_volume, basket_avg, basket_risk_money, basket_risk_pct_used, latest_time = basket_snapshot(
                current_positions, symbol, side, float(account.equity))
            opposite_type = mt5.POSITION_TYPE_SELL if side == "BUY" else mt5.POSITION_TYPE_BUY
            opposite = [p for p in current_positions if p.symbol == symbol and p.type == opposite_type and int(getattr(p, "magic", 0)) == MAGIC]
            if opposite:
                return jsonify(accepted=False, message=f"SCALP basket opposite position exists for {symbol}; close/reverse first"), 409
            if len(basket) >= max_positions:
                return jsonify(accepted=False, message=f"SCALP basket full: {len(basket)}/{max_positions}", basket_count=len(basket)), 409

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return jsonify(accepted=False, message="No current MT5 quote"), 503

        order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if side == "BUY" else tick.bid)

        if basket_mode:
            # V7.4.5: independent micro-scalp slots. Each fresh M1 micro trigger may open another
            # small same-direction slot until max_positions / cash-risk cap is reached.
            # We no longer require the previous slot to be in profit before allowing the next one.
            cooldown = max(1, int(data.get("basket_add_cooldown_sec") or 2))
            if latest_time and int(datetime.now().timestamp()) - latest_time < cooldown:
                return jsonify(accepted=False, message=f"SCALP slot cooldown: {cooldown}s", basket_count=len(basket)), 409

        api_entry = safe_float(data.get("api_entry") or data.get("entry"), 0)
        max_drift = safe_float(data.get("max_price_drift_pct"), 0.05)
        drift_pct = None
        if api_entry > 0:
            drift_pct = abs(price - api_entry) / api_entry * 100.0
            if drift_pct > max_drift:
                return jsonify(accepted=False, message=f"Price drift {drift_pct:.4f}% > {max_drift:.4f}%",
                               mt5_price=price, api_entry=api_entry, drift_pct=drift_pct), 409

        sl = safe_float(data.get("sl"), 0)
        tp = safe_float(data.get("tp1") or data.get("tp"), 0)
        risk_pct = safe_float(data.get("risk_pct"), 0.5)
        scalp_limits = None
        if basket_mode and bool(data.get("scalp_money_manager", True)):
            scalp_limits = scalp_money_limits(float(account.equity), data)
            remaining_money = scalp_limits['basket_risk_usd'] - float(basket_risk_money)
            if remaining_money <= 0.01:
                return jsonify(accepted=False, message=f"SCALP basket money-risk cap reached: ${basket_risk_money:.2f}/${scalp_limits['basket_risk_usd']:.2f}",
                               basket_count=len(basket), basket_risk_usd=basket_risk_money, scalp_money=scalp_limits), 409
            tranche_money = min(scalp_limits['planned_risk_usd'], remaining_money)
            risk_pct = (tranche_money / max(float(account.equity), 1e-9)) * 100.0
        elif basket_mode:
            basket_risk_cap = max(0.05, safe_float(data.get("basket_risk_pct"), 0.5))
            if basket_risk_pct_used >= basket_risk_cap - 1e-9:
                return jsonify(accepted=False, message=f"SCALP basket risk cap reached: {basket_risk_pct_used:.3f}%/{basket_risk_cap:.3f}%",
                               basket_count=len(basket), basket_risk_pct=basket_risk_pct_used), 409
            risk_pct = min(risk_pct, max(0.01, basket_risk_cap - basket_risk_pct_used))

        # CURRENT: Android analysis prices can differ slightly from the broker feed.
        # Preserve the intended SL/TP distance, but anchor execution protection to MT5 Bid/Ask.
        # This prevents invalid stops and wrong-side stops when API Entry != MT5 price.
        info = mt5.symbol_info(symbol)
        point = float(info.point) if info and info.point else 0.00001
        min_stop = max(point * (int(getattr(info, "trade_stops_level", 0) or 0) + 2), point * 5)
        if api_entry > 0 and sl > 0:
            sl_distance = max(abs(api_entry - sl), min_stop)
            if side == "BUY":
                sl = price - sl_distance
            else:
                sl = price + sl_distance
        if api_entry > 0 and tp > 0:
            tp_distance = max(abs(tp - api_entry), min_stop)
            if side == "BUY":
                tp = price + tp_distance
            else:
                tp = price - tp_distance

        volume, risk, err = calc_risk_volume(symbol, order_type, price, sl, risk_pct, float(account.equity))
        if err:
            return jsonify(accepted=False, message=err, risk=risk, scalp_money=scalp_limits), 400
        if scalp_limits is not None:
            actual = safe_float((risk or {}).get('risk_money_actual'), 0.0)
            if actual > scalp_limits['hard_loss_usd'] + 0.01:
                return jsonify(accepted=False, message=f"SCALP lot rejected: SL risk ${actual:.2f} > hard cap ${scalp_limits['hard_loss_usd']:.2f}",
                               risk=risk, scalp_money=scalp_limits), 409

        margin = margin_payload(order_type, symbol, volume, price, account)
        req_margin = margin.get("required_margin")
        if req_margin is not None and req_margin > float(account.margin_free):
            return jsonify(accepted=False, message="Insufficient free margin", margin=margin), 409

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": int(data.get("deviation") or 20),
            "magic": MAGIC,
            "comment": f"FXM1 V{BRIDGE_VERSION} {str(data.get('signal_mode') or 'AUTO')[:10]}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode_for(symbol),
        }

        # CURRENT: enforce broker-valid stop side/distance on the live MT5 quote.
        sl, tp = normalize_order_stops(symbol, side, tick, sl, tp)
        req["sl"] = sl
        req["tp"] = tp

        result, attempts = send_deal_with_fill_fallback(req)
        if result is None:
            return jsonify(accepted=False, ok=False, bridge_version=BRIDGE_VERSION,
                           message=f"order_send returned None: {mt5.last_error()}", attempts=attempts), 500

        ok = result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL)
        return jsonify(
            accepted=ok,
            ok=ok,
            bridge_version=BRIDGE_VERSION,
            message=("Order opened" if ok else f"MT5 retcode {result.retcode}: {result.comment}"),
            ticket=int(result.order) if result.order else None,
            deal=int(result.deal) if result.deal else None,
            symbol=symbol,
            side=side,
            volume=volume,
            execution_price=price,
            api_entry=api_entry if api_entry > 0 else None,
            drift_pct=drift_pct,
            sl=sl,
            tp=tp,
            risk=risk,
            margin=margin,
            retcode=int(result.retcode),
            mt5_comment=result.comment,
            attempts=attempts,
            basket_mode=basket_mode,
            basket_count=(len(basket) + 1 if basket_mode and ok else len(basket) if basket_mode else None),
            basket_risk_pct_before=(basket_risk_pct_used if basket_mode else None),
            scalp_money=scalp_limits
        ), (200 if ok else 500)


@app.post("/close-all")
def close_all():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403

        positions = mt5.positions_get() or []
        results = []
        for p in positions:
            ok, result = close_position_internal(p)
            result["ok"] = ok
            results.append(result)

        success = all(x["ok"] for x in results) if results else True
        return jsonify(
            ok=success,
            bridge_version=BRIDGE_VERSION,
            message=f"Closed {sum(1 for x in results if x['ok'])}/{len(results)} positions",
            results=results
        ), (200 if success else 500)


def history_deals(days=30):
    now = datetime.now()
    start = now - timedelta(days=max(1, min(days, 3650)))
    deals = mt5.history_deals_get(start, now) or []
    return deals


@app.get("/journal")
def journal():
    days = int(request.args.get("days", "30"))
    limit = min(max(int(request.args.get("limit", "200")), 1), 2000)
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503

        deals = history_deals(days)
        rows = []
        for d in reversed(deals[-limit:]):
            rows.append({
                "ticket": int(d.ticket),
                "order": int(d.order),
                "position_id": int(d.position_id),
                "time": int(d.time),
                "symbol": d.symbol,
                "type": int(d.type),
                "entry": int(d.entry),
                "volume": float(d.volume),
                "price": float(d.price),
                "profit": float(d.profit),
                "commission": float(d.commission),
                "swap": float(d.swap),
                "fee": float(getattr(d, "fee", 0.0) or 0.0),
                "magic": int(d.magic),
                "comment": d.comment,
            })
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, count=len(rows), deals=rows)


@app.get("/stats")
def stats():
    days = int(request.args.get("days", "30"))
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503

        deals = history_deals(days)
        # Count only closing/out deals for trade-result stats
        closing = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY)]
        pnl = [float(d.profit) + float(d.commission) + float(d.swap) + float(getattr(d, "fee", 0.0) or 0.0) for d in closing]
        wins = [x for x in pnl if x > 0]
        losses = [x for x in pnl if x < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (None if gross_profit == 0 else 999.0)

        consecutive_losses = 0
        max_consecutive_losses = 0
        for x in pnl:
            if x < 0:
                consecutive_losses += 1
                max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
            else:
                consecutive_losses = 0

        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, period_days=days, stats={
            "closed_trades": len(pnl),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": (len(wins) / len(pnl) * 100.0) if pnl else 0.0,
            "net_pl": sum(pnl),
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "avg_trade": (sum(pnl) / len(pnl)) if pnl else 0.0,
            "avg_win": (sum(wins) / len(wins)) if wins else 0.0,
            "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
            "max_consecutive_losses": max_consecutive_losses,
        })


@app.get("/position-manager")
def position_manager():
    # Read-only snapshot; active BE/trailing logic should be orchestrated by app/server loop.
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        data = positions_payload()
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, status="READY",
                       message="Position manager endpoints available",
                       positions=data,
                       controls={
                           "close": True, "partial_close": True, "modify_sltp": True,
                           "breakeven": True, "trailing_server_loop": False
                       })


# ---- V7.3 compatibility endpoints for Android client ----
_INITIAL_R = {}
_PARTIAL_DONE = set()

# V7.4.5 Bridge-side SCALP supervisor. It runs independently of Android's 5-second analysis loop.
_SCALP_SUPERVISOR_CFG = {
    'scalp_risk_usd_cap': 2.0,
    'scalp_hard_loss_usd_cap': 5.0,
    'scalp_profit_protect_usd_cap': 1.5,
    'scalp_trail_start_usd_cap': 2.5,
    'scalp_take_profit_usd_cap': 3.0,
    'scalp_basket_risk_usd_cap': 16.0,
    'scalp_basket_hard_loss_usd_cap': 10.0,
    'scalp_basket_take_profit_usd_cap': 8.0,
    'scalp_max_hold_sec': 90,
}
_SCALP_SUPERVISOR_STOP = threading.Event()

def update_scalp_supervisor_cfg(cfg):
    if not isinstance(cfg, dict):
        return
    for key in list(_SCALP_SUPERVISOR_CFG.keys()):
        if key in cfg:
            _SCALP_SUPERVISOR_CFG[key] = safe_float(cfg.get(key), _SCALP_SUPERVISOR_CFG[key])

def is_scalp_position(p):
    if int(getattr(p, 'magic', 0) or 0) != MAGIC:
        return False
    c = str(getattr(p, 'comment', '') or '').upper()
    return 'SCALP' in c

def scalp_supervisor_once():
    if not ensure_mt5():
        return
    account = mt5.account_info()
    if account is None:
        return
    positions = [p for p in (mt5.positions_get() or []) if is_scalp_position(p)]
    if not positions:
        return
    cfg = dict(_SCALP_SUPERVISOR_CFG)
    limits = scalp_money_limits(float(account.equity), cfg)
    basket_hard = max(limits['hard_loss_usd'], safe_float(cfg.get('scalp_basket_hard_loss_usd_cap'), 10.0))
    basket_tp = max(limits['take_profit_usd'], safe_float(cfg.get('scalp_basket_take_profit_usd_cap'), 8.0))
    basket_pnl = sum(float(p.profit) + float(getattr(p, 'swap', 0.0) or 0.0) for p in positions)

    # Basket circuit breaker first: prevents several independent slots from accumulating a large loss.
    if basket_pnl <= -basket_hard or basket_pnl >= basket_tp:
        reason = 'BASKET_HARD_LOSS' if basket_pnl <= -basket_hard else 'BASKET_TAKE_PROFIT'
        for p in list(positions):
            close_position_internal(p, comment=f'FXM1 V{BRIDGE_VERSION} SCALP {reason}')
        return

    for p in list(positions):
        tick = mt5.symbol_info_tick(p.symbol)
        if tick is None:
            continue
        pnl_usd = float(p.profit) + float(getattr(p, 'swap', 0.0) or 0.0)
        age_sec = max(0, int(datetime.now().timestamp()) - int(getattr(p, 'time', 0) or 0))
        if pnl_usd <= -limits['hard_loss_usd']:
            close_position_internal(p, comment=f'FXM1 V{BRIDGE_VERSION} SCALP HARD_LOSS')
            continue
        if pnl_usd >= limits['take_profit_usd']:
            close_position_internal(p, comment=f'FXM1 V{BRIDGE_VERSION} SCALP TAKE_PROFIT')
            continue
        if age_sec >= max(30, int(safe_float(cfg.get('scalp_max_hold_sec'), 90))) and pnl_usd > 0:
            close_position_internal(p, comment=f'FXM1 V{BRIDGE_VERSION} SCALP TIME_PROFIT')
            continue

        # Profit-lock is broker-side SL, so protection survives even if the phone sleeps.
        if pnl_usd >= limits['protect_usd']:
            is_buy = p.type == mt5.POSITION_TYPE_BUY
            current = float(tick.bid if is_buy else tick.ask)
            move = current - float(p.price_open)
            fraction = 0.75 if pnl_usd >= limits['trail_start_usd'] else 0.35
            candidate = float(p.price_open) + move * fraction
            side_name = 'BUY' if is_buy else 'SELL'
            candidate, _ = normalize_order_stops(p.symbol, side_name, tick, candidate, 0.0)
            old_sl = float(p.sl)
            improve = (is_buy and candidate > max(old_sl, float(p.price_open))) or \
                      ((not is_buy) and candidate < float(p.price_open) and (old_sl <= 0 or candidate < old_sl))
            if improve and candidate > 0:
                req = {'action': mt5.TRADE_ACTION_SLTP, 'position': int(p.ticket), 'symbol': p.symbol,
                       'sl': candidate, 'tp': float(p.tp), 'magic': MAGIC,
                       'comment': f'FXM1 V{BRIDGE_VERSION} SCALP LOCK'}
                mt5.order_send(req)

def scalp_supervisor_loop():
    while not _SCALP_SUPERVISOR_STOP.is_set():
        try:
            with LOCK:
                scalp_supervisor_once()
        except Exception as e:
            print('SCALP supervisor error:', e)
        _SCALP_SUPERVISOR_STOP.wait(0.25)


@app.get('/trade-log')
def trade_log_alias():
    days = int(request.args.get('days', '30'))
    limit = min(max(int(request.args.get('limit', '200')), 1), 2000)
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        deals = history_deals(days)
        events = []
        for d in reversed(deals[-limit:]):
            events.append({
                'ts': int(d.time), 'event': 'DEAL', 'ticket': int(d.ticket),
                'position_id': int(d.position_id), 'symbol': d.symbol,
                'volume': float(d.volume), 'price': float(d.price),
                'profit': float(d.profit), 'commission': float(d.commission),
                'swap': float(d.swap), 'comment': d.comment
            })
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, events=events)

@app.post('/position-action')
def position_action_alias():
    data = request.get_json(silent=True) or {}
    ticket = int(data.get('ticket') or 0)
    action = str(data.get('action') or '').lower()
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403
        arr = mt5.positions_get(ticket=ticket)
        if not arr:
            return jsonify(ok=False, message=f'Position {ticket} not found'), 404
        p = arr[0]
        if action == 'close':
            ok, result = close_position_internal(p)
            return jsonify(ok=ok, message=result.get('message','close'), **result), (200 if ok else 500)
        if action == 'partial':
            pct = max(1.0, min(float(data.get('pct') or 50.0), 99.0))
            ok, result = close_position_internal(p, volume=float(p.volume)*pct/100.0, comment=f'FXM1 V{BRIDGE_VERSION} PARTIAL')
            return jsonify(ok=ok, message=result.get('message','partial'), **result), (200 if ok else 500)
        if action == 'breakeven':
            req = {'action': mt5.TRADE_ACTION_SLTP, 'position': int(ticket), 'symbol': p.symbol,
                   'sl': float(p.price_open), 'tp': float(p.tp), 'magic': MAGIC, 'comment':f'FXM1 V{BRIDGE_VERSION} BE'}
            r = mt5.order_send(req)
            ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
            return jsonify(ok=ok, message=(r.comment if r else str(mt5.last_error())), ticket=ticket), (200 if ok else 500)
        return jsonify(ok=False, message=f'Unknown action: {action}'), 400

@app.post('/manage-positions')
def manage_positions_alias():
    cfg = request.get_json(silent=True) or {}
    if bool(cfg.get('scalp_mode', False)):
        update_scalp_supervisor_cfg(cfg)
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        allowed, reason = trading_allowed(account)
        if not allowed:
            return jsonify(ok=False, message=reason), 403
        positions = mt5.positions_get() or []
        actions = []
        for p in positions:
            tick = mt5.symbol_info_tick(p.symbol)
            info = mt5.symbol_info(p.symbol)
            if not tick or not info: continue
            current = float(tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask)
            direction = 1.0 if p.type == mt5.POSITION_TYPE_BUY else -1.0
            ticket = int(p.ticket)
            if ticket not in _INITIAL_R:
                dist = abs(float(p.price_open) - float(p.sl)) if float(p.sl) > 0 else 0.0
                if dist <= 0:
                    dist = max(float(info.point) * max(10, int(getattr(info,'trade_stops_level',0) or 0)), abs(current-float(p.price_open)))
                _INITIAL_R[ticket] = max(dist, float(info.point))
            rdist = _INITIAL_R[ticket]
            r_now = direction * (current - float(p.price_open)) / rdist

            # V7.4.5 SCALP Money Manager. Manage by cash P/L, not normal intraday R thresholds.
            if bool(cfg.get('scalp_mode', False)) and int(getattr(p, 'magic', 0)) == MAGIC:
                limits = scalp_money_limits(float(account.equity), cfg)
                age_sec = max(0, int(datetime.now().timestamp()) - int(getattr(p, 'time', 0) or 0))
                pnl_usd = float(p.profit) + float(getattr(p, 'swap', 0.0) or 0.0)
                max_hold_sec = max(30, int(cfg.get('scalp_max_hold_sec', 120)))

                # Absolute emergency loss and fast take-profit.
                close_reason = None
                if pnl_usd <= -limits['hard_loss_usd']:
                    close_reason = 'HARD_LOSS'
                elif pnl_usd >= limits['take_profit_usd']:
                    close_reason = 'TAKE_PROFIT'
                elif age_sec >= max_hold_sec and pnl_usd > 0:
                    close_reason = 'TIME_PROFIT'

                if close_reason:
                    ok, res = close_position_internal(p, comment=f'FXM1 V{BRIDGE_VERSION} SCALP {close_reason}')
                    actions.append({'ticket':ticket,'action':'SCALP_'+close_reason,'ok':ok,'pnl_usd':pnl_usd,
                                    'age_sec':age_sec,'limits':limits,'message':res.get('message','')})
                    if ok:
                        _INITIAL_R.pop(ticket, None); _PARTIAL_DONE.discard(ticket)
                        continue

                # Protect a small scalp profit early. Once the move is stronger, lock most of it.
                if pnl_usd >= limits['protect_usd']:
                    lock_fraction = 0.65 if pnl_usd >= limits['trail_start_usd'] else 0.25
                    move = current - float(p.price_open)
                    candidate = float(p.price_open) + move * lock_fraction
                    side_name = 'BUY' if direction > 0 else 'SELL'
                    candidate, _ = normalize_order_stops(p.symbol, side_name, tick, candidate, 0.0)
                    old_sl = float(p.sl)
                    improve = (direction > 0 and candidate > max(old_sl, float(p.price_open))) or \
                              (direction < 0 and candidate < (old_sl if old_sl > 0 else float('inf')) and candidate < float(p.price_open))
                    if improve and candidate > 0:
                        req={'action':mt5.TRADE_ACTION_SLTP,'position':ticket,'symbol':p.symbol,'sl':candidate,'tp':float(p.tp),
                             'magic':MAGIC,'comment':f'FXM1 V{BRIDGE_VERSION} SCALP LOCK'}
                        rr=mt5.order_send(req)
                        actions.append({'ticket':ticket,'action':'SCALP_LOCK','ok':bool(rr and rr.retcode==mt5.TRADE_RETCODE_DONE),
                                        'pnl_usd':pnl_usd,'sl':candidate,'lock_fraction':lock_fraction,'limits':limits})
                # Do not fall through into the normal R-based manager for SCALP.
                continue

            new_sl = float(p.sl)
            do_modify = False
            if bool(cfg.get('break_even_enabled', True)) and r_now >= float(cfg.get('break_even_at_r',1.0)):
                be = float(p.price_open)
                if (direction > 0 and (new_sl == 0 or new_sl < be)) or (direction < 0 and (new_sl == 0 or new_sl > be)):
                    new_sl = be; do_modify = True
            if bool(cfg.get('trailing_enabled', True)) and r_now >= float(cfg.get('trailing_start_r',1.5)):
                trail = float(cfg.get('trailing_distance_r',0.8)) * rdist
                candidate = current - trail if direction > 0 else current + trail
                if (direction > 0 and candidate > new_sl) or (direction < 0 and (new_sl == 0 or candidate < new_sl)):
                    new_sl = candidate; do_modify = True
            if do_modify:
                req={'action':mt5.TRADE_ACTION_SLTP,'position':ticket,'symbol':p.symbol,'sl':new_sl,'tp':float(p.tp),'magic':MAGIC,'comment':f'FXM1 V{BRIDGE_VERSION} MANAGER'}
                r=mt5.order_send(req)
                actions.append({'ticket':ticket,'action':'SL','ok':bool(r and r.retcode==mt5.TRADE_RETCODE_DONE),'r':r_now,'sl':new_sl})
            if bool(cfg.get('partial_close_enabled', True)) and ticket not in _PARTIAL_DONE and r_now >= float(cfg.get('partial_close_at_r',1.5)):
                pct=max(1.0,min(float(cfg.get('partial_close_pct',50.0)),99.0))
                ok,res=close_position_internal(p,volume=float(p.volume)*pct/100.0,comment=f'FXM1 V{BRIDGE_VERSION} AUTO PARTIAL')
                if ok: _PARTIAL_DONE.add(ticket)
                actions.append({'ticket':ticket,'action':'PARTIAL','ok':ok,'r':r_now,'pct':pct})
        live={int(x.ticket) for x in (mt5.positions_get() or [])}
        for t in list(_INITIAL_R):
            if t not in live: _INITIAL_R.pop(t,None); _PARTIAL_DONE.discard(t)
        return jsonify(ok=True, bridge_version=BRIDGE_VERSION, managed=len(positions), actions=actions, message='ACTIVE')

@app.get('/risk-state')
def risk_state_alias():
    daily_limit=float(request.args.get('daily_loss_limit_pct','3'))
    dd_limit=float(request.args.get('max_drawdown_pct','5'))
    streak_limit=int(request.args.get('max_consecutive_losses','3'))
    with LOCK:
        if not ensure_mt5(): return jsonify(ok=False, allowed=False, message='MT5 offline'),503
        ai=mt5.account_info()
        st_resp = stats()
        # Flask response may be tuple; derive directly for stable values
        now=datetime.now(); start=now-timedelta(days=30)
        deals=mt5.history_deals_get(start,now) or []
        closing=[d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT,mt5.DEAL_ENTRY_OUT_BY)]
        pnl=[float(d.profit)+float(d.commission)+float(d.swap)+float(getattr(d,'fee',0.0) or 0.0) for d in closing]
        streak=0
        for x in reversed(pnl):
            if x<0: streak+=1
            else: break
        day_start=datetime(now.year,now.month,now.day)
        day_deals=mt5.history_deals_get(day_start,now) or []
        day_pl=sum(float(d.profit)+float(d.commission)+float(d.swap)+float(getattr(d,'fee',0.0) or 0.0) for d in day_deals if d.entry in (mt5.DEAL_ENTRY_OUT,mt5.DEAL_ENTRY_OUT_BY))
        bal=max(float(ai.balance),1e-9)
        day_loss_pct=max(0.0,-day_pl/bal*100.0)
        dd_pct=max(0.0,(float(ai.balance)-float(ai.equity))/bal*100.0)
        blocks=[]
        if day_loss_pct>=daily_limit: blocks.append('DAILY_LOSS')
        if dd_pct>=dd_limit: blocks.append('DRAWDOWN')
        if streak>=streak_limit: blocks.append('LOSS_STREAK')
        return jsonify(ok=True, allowed=not blocks, blocks=blocks, daily_pl=day_pl, daily_loss_pct=day_loss_pct, drawdown_pct=dd_pct, consecutive_losses=streak)


if __name__ == "__main__":
    if not mt5.initialize():
        print("WARNING: MT5 is not connected yet:", mt5.last_error())
        print("Open MetaTrader 5 on Windows and log in, then retry /health.")

    host = "0.0.0.0"
    port = int(os.environ.get("FXM1_PORT", "8000"))
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "YOUR_PC_IP"

    print(f"FX M1 MT5 Bridge V{BRIDGE_VERSION}: http://{ip}:{port}")
    print("REAL trading:", "ENABLED" if ALLOW_REAL else "DISABLED (safe default)")
    threading.Thread(target=scalp_supervisor_loop, name="FXM1-ScalpSupervisor", daemon=True).start()
    print("SCALP supervisor: ACTIVE · 250 ms cash-stop loop")
    app.run(host=host, port=port, debug=False, threaded=True)
