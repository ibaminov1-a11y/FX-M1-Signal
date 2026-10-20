"""Install an explicitly preconfirmed account clock at startup, never infer an offset.
Only read-only MT5 calls are made. Identical quotes are observations, not failures.
"""
from __future__ import annotations
import contextlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


def _no_link(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError('CLOCK_PATH_LINK_REFUSED: '+str(path))
    if path.exists() and getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
        raise RuntimeError('CLOCK_PATH_LINK_REFUSED: '+str(path))


def _clock_state_safe(directory: Path) -> None:
    """Read-only confirmation. Never reset a campaign, an order intent, or a token."""
    _no_link(directory)
    dbpath=directory/'campaign.sqlite3'
    _no_link(dbpath)
    if not dbpath.is_file():
        raise RuntimeError('CLOCK_STATE_MISSING: локальная база не найдена; новая взамен неё не создаётся.')
    with contextlib.closing(sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        if db.execute("SELECT 1 FROM intents WHERE status IN ('SENDING','UNKNOWN') LIMIT 1").fetchone():
            raise RuntimeError('CLOCK_UNKNOWN_EXECUTION: есть неизвестное исполнение; время не изменено.')
        for key,body in db.execute("SELECT k,value FROM state WHERE k='engine' OR k LIKE 'profile:%:engine'"):
            saved=json.loads(body)
            if not isinstance(saved,dict):raise RuntimeError('CLOCK_STATE_FORMAT')
            if saved.get('campaign') or saved.get('exit_pending') or saved.get('pending_reversal'):
                raise RuntimeError('CLOCK_SAVED_EXPOSURE: сохранена незавершённая серия; время не изменено.')


def _terminal_guard(mt5, expected_account: str, require_flat: bool) -> None:
    account=mt5.account_info();terminal=mt5.terminal_info()
    if account is None or terminal is None or not terminal.connected:
        raise RuntimeError('CLOCK_MT5_UNCONFIRMED: нет подтверждённого соединения с MT5.')
    if f'{account.login}@{account.server}'!=expected_account:
        raise RuntimeError('CLOCK_ACCOUNT_MISMATCH: настройка предназначена для другого проверенного счёта.')
    if account.trade_mode!=0 or account.margin_mode!=2 or account.currency!='USD':
        raise RuntimeError('CLOCK_ACCOUNT_UNSUPPORTED: ограничения R7.4 DEMO USD HEDGING сохранены.')
    if require_flat:
        positions=mt5.positions_get();orders=mt5.orders_get()
        if positions is None or orders is None:
            raise RuntimeError('CLOCK_MT5_UNCONFIRMED: MT5 не подтвердил позиции и ордера.')
        if len(positions) or len(orders):
            raise RuntimeError('CLOCK_EXPOSURE_ACTIVE: изменение времени запрещено при открытых позициях или ордерах. Ничего не закрыто.')
    # Recheck the identity after the other terminal reads.
    again=mt5.account_info()
    if again is None or f'{again.login}@{again.server}'!=expected_account:
        raise RuntimeError('CLOCK_ACCOUNT_MISMATCH: счёт изменился во время проверки.')


def prepare_startup_clock(directory, terminal, expected_account, offset_minutes=180, *,
                          mt5=None, now=time.time, monotonic=time.monotonic,
                          sleep=time.sleep, log=print, timeout=45.0):
    """Apply only the caller's preconfirmed account/offset, and only without exposure.

    The bundled call is made BEFORE the trading worker exists and while both startup
    locks are held. It never enables AUTO. Saved identical policy is idempotent.
    No offset is estimated from the difference between the tick and computer clock.
    """
    if not isinstance(expected_account,str) or not re.fullmatch(r'\d+@[^\r\n]+',expected_account):
        raise RuntimeError('CLOCK_ACCOUNT_NOT_PRECONFIRMED')
    if type(offset_minutes) is not int or not -840<=offset_minutes<=840:
        raise RuntimeError('CLOCK_INVALID_EXPLICIT_OFFSET')
    if not 0<float(timeout)<=60:raise RuntimeError('CLOCK_INVALID_WAIT_LIMIT')
    directory=Path(directory);target=directory/'broker-clock.json'
    _no_link(directory);_no_link(target)
    expected=dict(account=expected_account,offset_minutes=offset_minutes,confirmed=True)
    exists=target.exists()
    if exists:
        saved=json.loads(target.read_text(encoding='utf-8-sig'))
        if (not isinstance(saved,dict) or saved.get('account')!=expected_account
                or type(saved.get('offset_minutes')) is not int or saved['offset_minutes']!=offset_minutes
                or saved.get('confirmed') is not True):
            raise RuntimeError('CLOCK_POLICY_CONFLICT: другая настройка уже существует; автоматически не заменена.')
    if mt5 is None:
        import MetaTrader5 as mt5
    if not mt5.initialize(str(terminal),timeout=5000):
        raise RuntimeError('CLOCK_MT5_UNCONFIRMED: не удалось прочитать MT5; настройки не изменены.')
    temp=None
    try:
        _terminal_guard(mt5,expected_account,not exists)
        if exists:
            log('CLOCK_POLICY_PRESENT: сохранённое смещение используется без повторной записи.')
            return dict(status='CLOCK_POLICY_PRESENT',offset_minutes=offset_minutes,changed=False)
        _clock_state_safe(directory)
        log('Проверка времени MT5: ждём 3 разные свежие котировки (не более 45 секунд). Одинаковая котировка не считается ошибкой.')
        started=monotonic();wall=now();last_raw=None;accepted=[];last_progress=-10.;observations=0;age=None
        while monotonic()-started<float(timeout):
            elapsed=monotonic()-started
            if abs((now()-wall)-elapsed)>1.5:
                raise RuntimeError('CLOCK_WINDOWS_CHANGED: часы компьютера изменились во время проверки.')
            _terminal_guard(mt5,expected_account,True)
            tick=mt5.symbol_info_tick('EURUSD');observations+=1
            if tick is not None:
                raw=getattr(tick,'time_msc',0)
                bid=getattr(tick,'bid',float('nan'));ask=getattr(tick,'ask',float('nan'))
                if (isinstance(raw,(int,float)) and raw>0 and math.isfinite(raw)
                        and math.isfinite(bid) and math.isfinite(ask) and 0<bid<=ask):
                    age=now()-(raw/1000.0-offset_minutes*60)
                    if last_raw is not None and raw<last_raw:
                        raise RuntimeError('CLOCK_TICK_BACKWARDS: последовательность тиков пошла назад; настройка не сохранена.')
                    # A repeated cached observation is expected. Keep waiting while
                    # preserving the original timestamp; never substitute now().
                    if -2<=age<=10 and (last_raw is None or raw>last_raw):
                        if accepted and now()-accepted[-1]['observed_at']>10:accepted=[]
                        accepted.append(dict(raw_tick_time_msc=raw,observed_at=now(),normalized_age=age))
                    last_raw=raw
                    if len(accepted)>=3:
                        # Recheck all scopes immediately before the only write.
                        _terminal_guard(mt5,expected_account,True);_clock_state_safe(directory)
                        if not -2<=now()-(raw/1000.0-offset_minutes*60)<=10:continue
                        data=(json.dumps(expected,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
                        temp=directory/('.clock-'+uuid.uuid4().hex+'.tmp')
                        with temp.open('xb') as out:
                            out.write(data);out.flush();os.fsync(out.fileno())
                        # Atomic create-if-absent on the same volume. A conflicting
                        # pre-existing policy can never be silently overwritten.
                        os.link(temp,target)
                        temp.unlink();temp=None
                        if json.loads(target.read_text(encoding='utf-8'))!=expected:raise RuntimeError('CLOCK_READBACK_FAILED')
                        log('CLOCK_POLICY_SAVED: смещение сохранено; Bridge продолжает запуск автоматически.')
                        return dict(status='CLOCK_POLICY_SAVED',offset_minutes=offset_minutes,changed=True,
                                    distinct_ticks=len(accepted),observations=observations,samples=accepted,
                                    waited_seconds=round(monotonic()-started,3))
            if elapsed-last_progress>=5:
                log('Ожидание котировок: '+str(len(accepted))+'/3; '+str(int(elapsed))+' с. AUTO остаётся выключенным.')
                last_progress=elapsed
            sleep(min(.5,max(0.,float(timeout)-(monotonic()-started))))
        raise RuntimeError('CLOCK_WAIT_TIMEOUT: за 45 секунд не получены 3 разные пригодные котировки. '
                           'Проверьте соединение и EURUSD в MT5. Настройка не сохранена; время Windows и база не изменены.')
    finally:
        if temp is not None:
            try:temp.unlink()
            except FileNotFoundError:pass
        mt5.shutdown()
