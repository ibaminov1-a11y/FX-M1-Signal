from flask import Flask, jsonify, request
import MetaTrader5 as mt5
import math
import os
import socket
import threading
import json
import time
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
LOCK = threading.RLock()
MAGIC = 710071
BRIDGE_VERSION = "7.1"
STARTED_AT = time.time()
STATE_FILE = os.environ.get("FXM1_STATE_FILE", os.path.join(os.path.dirname(__file__), "fxm1_bridge_state.json"))
LOG_FILE = os.environ.get("FXM1_LOG_FILE", os.path.join(os.path.dirname(__file__), "fxm1_trade_log.jsonl"))


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def append_log(event, **payload):
    row = {"ts": int(time.time()), "event": event, **payload}
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


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


def demo_guard():
    if not ensure_mt5():
        return None, (jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503)
    info = mt5.account_info()
    if info is None:
        return None, (jsonify(ok=False, message="No MT5 account"), 503)
    if account_type_name(info) != "DEMO":
        return None, (jsonify(ok=False, message="V7.1 bridge blocks trading on non-DEMO accounts"), 403)
    return info, None


def norm_symbol(raw):
    return (raw or "").upper().replace("/", "").replace("_", "").replace("-", "").replace(".", "")


def resolve_symbol(raw):
    base = norm_symbol(raw)
    if not base:
        return None
    exact = (raw or "").upper().strip()
    if exact and mt5.symbol_info(exact) is not None:
        mt5.symbol_select(exact, True)
        return exact
    if mt5.symbol_info(base) is not None:
        mt5.symbol_select(base, True)
        return base
    all_symbols = mt5.symbols_get() or []
    for s in all_symbols:
        if norm_symbol(s.name) == base:
            mt5.symbol_select(s.name, True)
            return s.name
    for s in all_symbols:
        n = norm_symbol(s.name)
        if n.startswith(base) or n.endswith(base):
            mt5.symbol_select(s.name, True)
            return s.name
    return None


def point_pip(info):
    if not info:
        return 0.0001
    # 5/3 digit FX quotes: one pip = 10 points; otherwise 1 point.
    return float(info.point) * (10.0 if int(info.digits) in (3, 5) else 1.0)


def spread_pips(symbol, tick=None):
    info = mt5.symbol_info(symbol)
    tick = tick or mt5.symbol_info_tick(symbol)
    if not info or not tick:
        return None
    pip = point_pip(info)
    if pip <= 0:
        return None
    return abs(float(tick.ask) - float(tick.bid)) / pip


def position_payload(p):
    tick = mt5.symbol_info_tick(p.symbol)
    current = float(tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask) if tick else float(p.price_current)
    return {
        "ticket": int(p.ticket),
        "symbol": p.symbol,
        "side": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
        "volume": float(p.volume),
        "price_open": float(p.price_open),
        "price_current": current,
        "sl": float(p.sl),
        "tp": float(p.tp),
        "profit": float(p.profit),
        "time": int(p.time),
        "age_sec": max(0, int(time.time()) - int(p.time)),
        "magic": int(p.magic),
        "comment": str(p.comment or ""),
    }


def positions_payload():
    positions = mt5.positions_get() or []
    return [position_payload(p) for p in positions]


def today_bounds_utc():
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return start, now


def history_stats(days=30):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=max(1, min(int(days), 365)))
    deals = mt5.history_deals_get(start, now) or []
    closes = []
    for d in deals:
        if int(getattr(d, "magic", 0)) != MAGIC:
            continue
        entry = int(getattr(d, "entry", -1))
        if entry not in (getattr(mt5, "DEAL_ENTRY_OUT", 1), getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)):
            continue
        profit = float(getattr(d, "profit", 0.0)) + float(getattr(d, "swap", 0.0)) + float(getattr(d, "commission", 0.0)) + float(getattr(d, "fee", 0.0))
        closes.append({"time": int(d.time), "profit": profit, "symbol": d.symbol, "deal": int(d.ticket)})
    wins = [x for x in closes if x["profit"] > 0]
    losses = [x for x in closes if x["profit"] < 0]
    gross_profit = sum(x["profit"] for x in wins)
    gross_loss = abs(sum(x["profit"] for x in losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    avg = sum(x["profit"] for x in closes) / len(closes) if closes else 0.0
    streak_losses = 0
    for x in sorted(closes, key=lambda z: z["time"], reverse=True):
        if x["profit"] < 0:
            streak_losses += 1
        else:
            break
    today_start, _ = today_bounds_utc()
    daily = sum(x["profit"] for x in closes if datetime.fromtimestamp(x["time"], tz=timezone.utc) >= today_start)
    return {
        "trades": len(closes),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(closes) * 100.0) if closes else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "avg_trade": avg,
        "daily_realized_pl": daily,
        "consecutive_losses": streak_losses,
        "recent": sorted(closes, key=lambda z: z["time"], reverse=True)[:30],
    }


def risk_state(account, daily_loss_limit_pct=3.0, max_drawdown_pct=5.0, max_consecutive_losses=3):
    stats = history_stats(30)
    balance = float(account.balance)
    equity = float(account.equity)
    drawdown_pct = ((balance - equity) / balance * 100.0) if balance > 0 and equity < balance else 0.0
    daily_loss_pct = (-stats["daily_realized_pl"] / max(balance, 1e-9) * 100.0) if stats["daily_realized_pl"] < 0 else 0.0
    blocks = []
    if daily_loss_pct >= float(daily_loss_limit_pct):
        blocks.append(f"daily loss {daily_loss_pct:.2f}% >= {float(daily_loss_limit_pct):.2f}%")
    if drawdown_pct >= float(max_drawdown_pct):
        blocks.append(f"drawdown {drawdown_pct:.2f}% >= {float(max_drawdown_pct):.2f}%")
    if int(stats["consecutive_losses"]) >= int(max_consecutive_losses):
        blocks.append(f"loss streak {stats['consecutive_losses']} >= {int(max_consecutive_losses)}")
    return {
        "allowed": not blocks,
        "blocks": blocks,
        "daily_loss_pct": daily_loss_pct,
        "drawdown_pct": drawdown_pct,
        "consecutive_losses": int(stats["consecutive_losses"]),
        "stats": stats,
    }


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
    raw = risk_money / abs(float(pnl_one_lot))
    vol = floor_volume(raw, info.volume_step, info.volume_min, info.volume_max)
    if vol < info.volume_min:
        return None, f"Calculated lot {raw:.4f} is below broker minimum {info.volume_min}"
    return vol, None


def send_close_position(p, volume=None, comment="FXM1 V7.1 CLOSE"):
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return False, "no tick", None
    is_buy = p.type == mt5.POSITION_TYPE_BUY
    close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    price = float(tick.bid if is_buy else tick.ask)
    info = mt5.symbol_info(p.symbol)
    vol = float(p.volume if volume is None else volume)
    if info:
        vol = floor_volume(vol, info.volume_step, info.volume_min, info.volume_max)
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
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    r = mt5.order_send(req)
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    return ok, (r.comment if r else str(mt5.last_error())), r


def modify_sl_tp(p, sl=None, tp=None):
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": int(p.ticket),
        "symbol": p.symbol,
        "sl": float(p.sl if sl is None else sl),
        "tp": float(p.tp if tp is None else tp),
        "magic": MAGIC,
    }
    r = mt5.order_send(req)
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    return ok, (r.comment if r else str(mt5.last_error())), r


def position_r_multiple(p, meta=None):
    meta = meta or {}
    initial_sl = float(meta.get("initial_sl") or p.sl or 0)
    open_price = float(meta.get("open_price") or p.price_open)
    risk = abs(open_price - initial_sl)
    if risk <= 0:
        return 0.0
    tick = mt5.symbol_info_tick(p.symbol)
    current = float(tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask) if tick else float(p.price_current)
    reward = (current - open_price) if p.type == mt5.POSITION_TYPE_BUY else (open_price - current)
    return reward / risk


def manage_positions_impl(cfg):
    account, err = demo_guard()
    if err:
        return None, err
    state = load_state()
    pstate = state.setdefault("positions", {})
    positions = mt5.positions_get() or []
    results = []
    be_enabled = bool(cfg.get("break_even_enabled", True))
    be_r = float(cfg.get("break_even_at_r", 1.0))
    trailing_enabled = bool(cfg.get("trailing_enabled", True))
    trailing_start_r = float(cfg.get("trailing_start_r", 1.5))
    trailing_distance_r = float(cfg.get("trailing_distance_r", 0.8))
    partial_enabled = bool(cfg.get("partial_close_enabled", True))
    partial_at_r = float(cfg.get("partial_close_at_r", 1.5))
    partial_pct = max(10.0, min(float(cfg.get("partial_close_pct", 50.0)), 90.0))

    live_tickets = set()
    for p in positions:
        ticket = str(int(p.ticket))
        live_tickets.add(ticket)
        meta = pstate.setdefault(ticket, {
            "open_price": float(p.price_open),
            "initial_sl": float(p.sl),
            "initial_volume": float(p.volume),
            "be_done": False,
            "partial_done": False,
        })
        r_mult = position_r_multiple(p, meta)
        acts = []
        # Break-even: move SL to entry if profitable enough and not already beyond entry.
        if be_enabled and r_mult >= be_r and not meta.get("be_done"):
            new_sl = float(p.price_open)
            valid = (p.type == mt5.POSITION_TYPE_BUY and (p.sl == 0 or p.sl < new_sl)) or (p.type == mt5.POSITION_TYPE_SELL and (p.sl == 0 or p.sl > new_sl))
            if valid:
                ok, msg, _ = modify_sl_tp(p, sl=new_sl)
                acts.append({"action": "break_even", "ok": ok, "message": msg})
                if ok:
                    meta["be_done"] = True
                    append_log("break_even", ticket=int(p.ticket), symbol=p.symbol, r=r_mult, sl=new_sl)

        # Partial close once.
        if partial_enabled and r_mult >= partial_at_r and not meta.get("partial_done"):
            info = mt5.symbol_info(p.symbol)
            close_vol = float(p.volume) * partial_pct / 100.0
            if info:
                close_vol = floor_volume(close_vol, info.volume_step, info.volume_min, info.volume_max)
            if info and close_vol >= info.volume_min and close_vol < float(p.volume):
                ok, msg, _ = send_close_position(p, close_vol, "FXM1 V7.1 PARTIAL")
                acts.append({"action": "partial_close", "ok": ok, "message": msg, "volume": close_vol})
                if ok:
                    meta["partial_done"] = True
                    append_log("partial_close", ticket=int(p.ticket), symbol=p.symbol, r=r_mult, volume=close_vol)

        # Trailing stop after configured R. Trail by initial risk * distance.
        if trailing_enabled and r_mult >= trailing_start_r:
            initial_sl = float(meta.get("initial_sl") or 0)
            initial_risk = abs(float(p.price_open) - initial_sl)
            tick = mt5.symbol_info_tick(p.symbol)
            if initial_risk > 0 and tick:
                current = float(tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask)
                new_sl = current - initial_risk * trailing_distance_r if p.type == mt5.POSITION_TYPE_BUY else current + initial_risk * trailing_distance_r
                improve = (p.type == mt5.POSITION_TYPE_BUY and new_sl > float(p.sl or 0) and new_sl < current) or (p.type == mt5.POSITION_TYPE_SELL and (p.sl == 0 or new_sl < float(p.sl)) and new_sl > current)
                if improve:
                    ok, msg, _ = modify_sl_tp(p, sl=new_sl)
                    acts.append({"action": "trailing", "ok": ok, "message": msg, "sl": new_sl})
                    if ok:
                        append_log("trailing", ticket=int(p.ticket), symbol=p.symbol, r=r_mult, sl=new_sl)
        results.append({"ticket": int(p.ticket), "symbol": p.symbol, "r": r_mult, "actions": acts})

    for key in list(pstate.keys()):
        if key not in live_tickets:
            pstate.pop(key, None)
    save_state(state)
    return {"ok": True, "results": results}, None


@app.get('/health')
def health():
    with LOCK:
        ok = ensure_mt5()
        info = mt5.account_info() if ok else None
        positions = positions_payload() if info else []
        return jsonify({
            "ok": bool(ok),
            "mt5_connected": info is not None,
            "account_type": account_type_name(info),
            "login": int(info.login) if info else None,
            "server": info.server if info else None,
            "balance": float(info.balance) if info else None,
            "equity": float(info.equity) if info else None,
            "currency": info.currency if info else "USD",
            "positions": len(positions),
            "floating_pl": sum(float(x["profit"]) for x in positions),
            "bridge_version": BRIDGE_VERSION,
            "uptime_sec": int(time.time() - STARTED_AT),
            "heartbeat": int(time.time()),
        })


@app.get('/symbols')
def symbols():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        items = []
        for s in mt5.symbols_get() or []:
            if not getattr(s, "visible", False) and not getattr(s, "select", False):
                continue
            items.append({
                "symbol": s.name,
                "description": getattr(s, "description", ""),
                "digits": int(s.digits),
                "point": float(s.point),
                "trade_mode": int(s.trade_mode),
                "visible": bool(s.visible),
            })
        return jsonify(ok=True, count=len(items), symbols=items)


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
        return jsonify(ok=True, symbol=symbol, bid=float(tick.bid), ask=float(tick.ask), time=int(tick.time), spread_pips=spread_pips(symbol, tick))


@app.get('/positions')
def positions():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        items = positions_payload()
        return jsonify(ok=True, positions=items, count=len(items), floating_pl=sum(float(x["profit"]) for x in items))


@app.get('/stats')
def stats():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        days = request.args.get('days', '30')
        try:
            days = int(days)
        except Exception:
            days = 30
        return jsonify(ok=True, **history_stats(days))


@app.get('/risk-state')
def risk_state_endpoint():
    with LOCK:
        if not ensure_mt5():
            return jsonify(ok=False, message=f"MT5 initialize failed: {mt5.last_error()}"), 503
        account = mt5.account_info()
        if account is None:
            return jsonify(ok=False, message="No MT5 account"), 503
        def f(name, default):
            try: return float(request.args.get(name, default))
            except Exception: return float(default)
        def i(name, default):
            try: return int(request.args.get(name, default))
            except Exception: return int(default)
        rs = risk_state(account, f('daily_loss_limit_pct', 3.0), f('max_drawdown_pct', 5.0), i('max_consecutive_losses', 3))
        return jsonify(ok=True, **rs)


@app.post('/signal')
def signal():
    data = request.get_json(silent=True) or {}
    with LOCK:
        account, err = demo_guard()
        if err:
            return err

        side = str(data.get('signal', '')).upper()
        if side not in ('BUY', 'SELL'):
            append_log("signal_skipped", reason="WAIT", payload=data)
            return jsonify(accepted=False, message="WAIT/no trade")

        execution_mode = str(data.get('execution_mode', 'FULL_AUTO')).upper()
        manual_approved = bool(data.get('manual_approved', False))
        if execution_mode == 'SIGNALS_ONLY':
            append_log("signal_skipped", reason="SIGNALS_ONLY", payload=data)
            return jsonify(accepted=False, message="SIGNALS_ONLY: execution disabled")
        if execution_mode == 'SEMI_AUTO' and not manual_approved:
            append_log("signal_pending", reason="SEMI_AUTO approval required", payload=data)
            return jsonify(accepted=False, pending_approval=True, message="SEMI_AUTO: manual approval required")

        now = int(time.time())
        blackout_until = int(data.get('news_blackout_until_epoch') or 0)
        if blackout_until > now:
            append_log("signal_skipped", reason="NEWS_BLACKOUT", until=blackout_until, payload=data)
            return jsonify(accepted=False, message=f"News blackout active until {blackout_until}")

        quality = int(data.get('quality') or 0)
        confirm_below = int(data.get('confirm_below_quality') or 0)
        if bool(data.get('confirm_risky_entries', False)) and confirm_below > 0 and quality < confirm_below and not manual_approved:
            append_log("signal_pending", reason="LOW_QUALITY_APPROVAL", quality=quality, payload=data)
            return jsonify(accepted=False, pending_approval=True, message=f"Quality {quality}/100 requires manual approval")

        rs = risk_state(
            account,
            float(data.get('daily_loss_limit_pct') or 3.0),
            float(data.get('max_drawdown_pct') or 5.0),
            int(data.get('max_consecutive_losses') or 3),
        )
        if not rs['allowed']:
            append_log("signal_skipped", reason="RISK_MANAGER", blocks=rs['blocks'], payload=data)
            return jsonify(accepted=False, message="Risk manager blocked trade: " + "; ".join(rs['blocks']), risk_state=rs)

        symbol = resolve_symbol(data.get('symbol'))
        if not symbol:
            return jsonify(accepted=False, message="MT5 symbol not found"), 404

        max_positions = int(data.get('max_positions', 1))
        open_positions = mt5.positions_get() or []
        if len(open_positions) >= max_positions:
            return jsonify(accepted=False, message=f"Max positions reached: {len(open_positions)}/{max_positions}")

        state = load_state()
        cooldown_sec = max(0, int(data.get('cooldown_sec') or 0))
        last_exit = int(state.get('last_exit_by_symbol', {}).get(symbol, 0))
        if cooldown_sec and last_exit and now - last_exit < cooldown_sec:
            left = cooldown_sec - (now - last_exit)
            append_log("signal_skipped", reason="COOLDOWN", symbol=symbol, seconds_left=left)
            return jsonify(accepted=False, message=f"Cooldown active: {left}s left")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return jsonify(accepted=False, message="No current MT5 quote"), 503
        spr = spread_pips(symbol, tick)
        max_spread = float(data.get('max_spread_pips') or 0)
        if max_spread > 0 and spr is not None and spr > max_spread:
            append_log("signal_skipped", reason="SPREAD", symbol=symbol, spread_pips=spr, max_spread_pips=max_spread)
            return jsonify(accepted=False, message=f"Spread {spr:.2f} pips > {max_spread:.2f} pips")

        order_type = mt5.ORDER_TYPE_BUY if side == 'BUY' else mt5.ORDER_TYPE_SELL
        price = float(tick.ask if side == 'BUY' else tick.bid)
        api_entry = float(data.get('api_entry') or 0)
        max_drift = float(data.get('max_price_drift_pct') or 0.05)
        drift = abs(price - api_entry) / api_entry * 100.0 if api_entry > 0 else 0.0
        if api_entry > 0 and drift > max_drift:
            append_log("signal_skipped", reason="DRIFT", symbol=symbol, drift_pct=drift, max_drift_pct=max_drift)
            return jsonify(accepted=False, message=f"Price drift {drift:.4f}% > {max_drift:.4f}%")

        sl = float(data.get('sl') or 0)
        tp1 = float(data.get('tp1') or 0)
        tp2 = float(data.get('tp2') or 0)
        risk_pct = float(data.get('risk_pct') or 0.5)
        volume, volume_err = risk_volume(symbol, order_type, price, sl, risk_pct, float(account.equity))
        if volume_err:
            return jsonify(accepted=False, message=volume_err)

        snapshot = {
            "signal": side,
            "symbol": symbol,
            "quality": quality,
            "api_entry": api_entry,
            "mt5_price": price,
            "drift_pct": drift,
            "spread_pips": spr,
            "risk_pct": risk_pct,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "timeframe": data.get('timeframe'),
            "signal_mode": data.get('signal_mode'),
            "components": data.get('components'),
            "why": data.get('why'),
        }
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp1,
            "deviation": 20,
            "magic": MAGIC,
            "comment": "FXM1 V7.1 DEMO",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result is None:
            append_log("order_failed", reason=str(mt5.last_error()), snapshot=snapshot)
            return jsonify(accepted=False, message=f"order_send returned None: {mt5.last_error()}"), 500
        ok = result.retcode == mt5.TRADE_RETCODE_DONE
        exec_price = float(getattr(result, "price", 0.0) or price)
        slippage_pips = None
        info = mt5.symbol_info(symbol)
        if info:
            pip = point_pip(info)
            if pip > 0:
                slippage_pips = abs(exec_price - price) / pip
        ticket = int(result.order) if result.order else None
        if ok:
            state = load_state()
            pos_meta = state.setdefault('positions', {})
            # order ticket and position ticket are often same in hedging demo; manager also backfills later.
            if ticket:
                pos_meta[str(ticket)] = {
                    "open_price": exec_price,
                    "initial_sl": sl,
                    "initial_volume": volume,
                    "be_done": False,
                    "partial_done": False,
                }
            save_state(state)
            append_log("order_opened", ticket=ticket, deal=int(result.deal) if result.deal else None, volume=volume, execution_price=exec_price, slippage_pips=slippage_pips, snapshot=snapshot)
        else:
            append_log("order_rejected", retcode=int(result.retcode), message=result.comment, snapshot=snapshot)
        return jsonify(
            accepted=ok,
            message=("DEMO order opened" if ok else f"MT5 retcode {result.retcode}: {result.comment}"),
            ticket=ticket,
            deal=int(result.deal) if result.deal else None,
            symbol=symbol,
            volume=volume,
            execution_price=exec_price,
            requested_price=price,
            slippage_pips=slippage_pips,
            spread_pips=spr,
            retcode=int(result.retcode),
            risk_state=rs,
        )


@app.post('/manage-positions')
def manage_positions():
    data = request.get_json(silent=True) or {}
    with LOCK:
        payload, err = manage_positions_impl(data)
        if err:
            return err
        return jsonify(payload)


@app.post('/position-action')
def position_action():
    data = request.get_json(silent=True) or {}
    with LOCK:
        account, err = demo_guard()
        if err:
            return err
        ticket = int(data.get('ticket') or 0)
        action = str(data.get('action') or '').lower()
        positions = mt5.positions_get(ticket=ticket) or []
        if not positions:
            return jsonify(ok=False, message=f"Position {ticket} not found"), 404
        p = positions[0]
        if action == 'close':
            ok, msg, r = send_close_position(p)
            if ok:
                state = load_state()
                state.setdefault('last_exit_by_symbol', {})[p.symbol] = int(time.time())
                state.setdefault('positions', {}).pop(str(ticket), None)
                save_state(state)
            append_log("position_close", ticket=ticket, ok=ok, message=msg)
            return jsonify(ok=ok, message=msg)
        if action == 'breakeven':
            ok, msg, _ = modify_sl_tp(p, sl=float(p.price_open))
            append_log("position_breakeven", ticket=ticket, ok=ok, message=msg)
            return jsonify(ok=ok, message=msg)
        if action == 'partial':
            pct = max(10.0, min(float(data.get('pct') or 50.0), 90.0))
            info = mt5.symbol_info(p.symbol)
            vol = float(p.volume) * pct / 100.0
            if info:
                vol = floor_volume(vol, info.volume_step, info.volume_min, info.volume_max)
            if not info or vol < info.volume_min or vol >= float(p.volume):
                return jsonify(ok=False, message="Partial volume is invalid for broker minimum/step")
            ok, msg, _ = send_close_position(p, vol, "FXM1 V7.1 PARTIAL MANUAL")
            append_log("position_partial", ticket=ticket, ok=ok, message=msg, volume=vol)
            return jsonify(ok=ok, message=msg, volume=vol)
        return jsonify(ok=False, message="Unknown action"), 400


@app.post('/close-all')
def close_all():
    with LOCK:
        account, err = demo_guard()
        if err:
            return err
        positions = mt5.positions_get() or []
        results = []
        state = load_state()
        for p in positions:
            ok, msg, r = send_close_position(p, comment="FXM1 V7.1 CLOSE ALL")
            if ok:
                state.setdefault('last_exit_by_symbol', {})[p.symbol] = int(time.time())
                state.setdefault('positions', {}).pop(str(int(p.ticket)), None)
            results.append({"ticket": int(p.ticket), "ok": ok, "retcode": int(r.retcode) if r else None, "message": msg})
        save_state(state)
        success = all(x['ok'] for x in results) if results else True
        append_log("close_all", ok=success, results=results)
        return jsonify(ok=success, message=f"Closed {sum(1 for x in results if x['ok'])}/{len(results)} positions", results=results)


@app.get('/trade-log')
def trade_log():
    limit = 100
    try:
        limit = max(1, min(int(request.args.get('limit', '100')), 500))
    except Exception:
        pass
    rows = []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                try: rows.append(json.loads(line))
                except Exception: pass
    except Exception:
        pass
    return jsonify(ok=True, events=rows[-limit:][::-1])


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
    print(f'FX M1 MT5 Bridge V{BRIDGE_VERSION}: http://{ip}:{port}')
    app.run(host=host, port=port, debug=False, threaded=True)
