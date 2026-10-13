"""App-local runtime for unmodified R7.4, after confirmed loss of old local files.
No dependencies are downloaded at launch. No broker order is sent by this wrapper.
"""
from __future__ import annotations
import argparse, hashlib, importlib, json, os, runpy, secrets, socket, sqlite3, struct, sys, time
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class RuntimePaths:
    python: Path
    program_root: Path
    state_dir: Path


def resolve_runtime(root):
    root=Path(root).resolve()
    python=root/'Runtime/python.exe';program=root/'mt5_bridge'
    if not python.is_file():raise RuntimeError('Runtime/python.exe не найден. Извлеките ВСЮ папку из ZIP, не один CMD.')
    if not (program/'event_core/__init__.py').is_file():raise RuntimeError('Код Bridge отсутствует. Извлеките весь архив.')
    local=os.environ.get('LOCALAPPDATA')
    if not local:raise RuntimeError('Windows LOCALAPPDATA отсутствует; папка состояния не выбрана.')
    state=Path(local).resolve()/'FXM1'/'R74-Recovery'/'event_state'
    return RuntimePaths(python,program,state)


def verify_package(root):
    root=Path(root).resolve()
    manifest=json.loads((root/'PROGRAM_MANIFEST.json').read_text(encoding='utf-8'))
    files=manifest['files']
    if not files:raise RuntimeError('Пустой список файлов комплекта.')
    for name,expected in files.items():
        p=(root/name).resolve()
        if not p.is_relative_to(root):raise RuntimeError('Недопустимый путь в manifest.')
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Файл отсутствует или повреждён: '+name+'. Повторно извлеките весь архив в отдельную папку; состояние не удаляйте.')


def state_mode(state):
    state=Path(state)
    if not state.exists():return 'NEW'
    if not state.is_dir():raise RuntimeError('Вместо каталога состояния существует файл.')
    if not any(state.iterdir()):return 'NEW'
    db=state/'campaign.sqlite3';token=state/'bridge-token.txt'
    if not db.is_file() or not token.is_file():
        raise RuntimeError('Локальное состояние неполное: нужны база и ключ вместе. Автоматическая замена запрещена. Ничего не удаляйте: '+str(state))
    if len(token.read_text(encoding='utf-8').strip())<32:
        raise RuntimeError('Локальный ключ повреждён. Новый ключ автоматически не создаётся.')
    try:
        with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Проверка базы состояния не пройдена.')
            names={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'state','intents','campaigns','commands'}<=names:raise RuntimeError('Неизвестный формат базы состояния.')
    except sqlite3.Error as exc:raise RuntimeError('База состояния не читается: '+type(exc).__name__) from exc
    return 'EXISTING'


def initialize_state(state,details):
    state=Path(state)
    if state_mode(state)!='NEW':raise RuntimeError('Существующее состояние сохраняется; повторная инициализация запрещена.')
    state.mkdir(parents=True,exist_ok=True)
    with (state/'recovery-install.json').open('x',encoding='utf-8') as f:
        json.dump(dict(created_at=time.time(),auto_enabled=False,old_local_state_restored=False,
                       account_key=details.get('key',''),terminal=details.get('terminal','')),f,ensure_ascii=False,indent=2)
    with (state/'bridge-token.txt').open('x',encoding='utf-8') as f:f.write(secrets.token_urlsafe(32))
    from event_core.store import Store
    store=Store(state/'campaign.sqlite3')
    store.save('recovery_install',dict(old_local_state_restored=False,auto_enabled=False,created_at=time.time()))
    store.db.close()


def validate_account(a,positions,orders,fresh):
    if a is None or positions is None or orders is None:
        raise RuntimeError('MT5 не подтвердил счёт/позиции/ордера; новое состояние не создаётся.')
    if a.trade_mode!=0 or a.margin_mode!=2 or a.currency!='USD':
        raise RuntimeError('Исходный R7.4 поддерживает только DEMO USD HEDGING. Ограничения не снимались.')
    if fresh and (len(positions)>0 or len(orders)>0):
        raise RuntimeError('На счёте есть позиции или отложенные ордера, а локальная история удалена. Автозапуск остановлен. Проверьте их в MT5; программа сама ничего не закрывает и не принимает под управление.')


def inspect_terminal(terminal=None):
    import MetaTrader5 as mt5
    ok=mt5.initialize(str(terminal),timeout=5000) if terminal else mt5.initialize(timeout=5000)
    if not ok:raise RuntimeError('MT5 не подключён: '+str(mt5.last_error())+'. Откройте терминал и нужный счёт.')
    try:
        t=mt5.terminal_info();a=mt5.account_info();positions=mt5.positions_get();orders=mt5.orders_get()
        if t is None or not t.connected or a is None or positions is None or orders is None:
            raise RuntimeError('Нет подтверждённого соединения MT5 со счётом/историей. Проверьте терминал.')
        exe=Path(terminal) if terminal else Path(t.path)/'terminal64.exe'
        if not exe.is_file():raise RuntimeError('Не найден terminal64.exe выбранного терминала: '+str(exe))
        tick=mt5.symbol_info_tick('EURUSD')
        return a,positions,orders,dict(key=f'{a.login}@{a.server}',terminal=str(exe.resolve()),currency=a.currency,
            trade_mode=int(a.trade_mode),margin_mode=int(a.margin_mode),positions=len(positions),orders=len(orders),
            trading_allowed=bool(a.trade_allowed and a.trade_expert and t.trade_allowed and not getattr(t,'tradeapi_disabled',False)),
            raw_tick_age_seconds=round(time.time()-tick.time_msc/1000,3) if tick else None,
            clock_note='Разница времени — диагностика, не разрешение автоматически сдвигать часы брокера.')
    finally:mt5.shutdown()


def main(argv=None):
    parser=argparse.ArgumentParser(description='R7.4 — автономная установка, исходный торговый движок')
    parser.add_argument('--check',action='store_true',help='Проверка среды без MT5, нового ключа или сервера')
    parser.add_argument('--diagnose',action='store_true',help='Чтение состояния MT5 без торговли и изменения времени')
    parser.add_argument('--terminal',default=None)
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args(argv)
    if not 1<=args.port<=65535:parser.error('Недопустимый порт')
    if sys.platform!='win32' or struct.calcsize('P')!=8:
        raise RuntimeError('Нужна 64-битная Windows 10/11; запускайте CMD из полного архива.')
    root=Path(__file__).resolve().parent;paths=resolve_runtime(root)
    verify_package(root)
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(paths.program_root))
    from bridge_startup import environment_report
    report=environment_report()
    if not report['ok']:raise RuntimeError('Проверка встроенной среды: '+json.dumps(report,ensure_ascii=False))
    print('R7.4 | автономный комплект восстановления | AUTO OFF',flush=True)
    print('Состояние и ключ: '+str(paths.state_dir),flush=True)
    if args.check:
        print(json.dumps(dict(environment=report,state=state_mode(paths.state_dir),mt5_connected=False,
            orders_sent=0,old_venv_required=False),ensure_ascii=False));return 0
    if args.diagnose:
        _,_,_,detail=inspect_terminal(args.terminal)
        print(json.dumps(detail,ensure_ascii=False,indent=2));return 0
    paths.state_dir.parent.mkdir(parents=True,exist_ok=True)
    from event_core.store import ProcessLock
    guard=ProcessLock(paths.state_dir.parent/'recovery-launch.lock')
    try:
        mode=state_mode(paths.state_dir)
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):s.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            try:s.bind(('0.0.0.0',args.port))
            except OSError as exc:raise RuntimeError('Порт уже занят. Закройте другой Bridge; две копии одновременно не запускайте.') from exc
        a,positions,orders,details=inspect_terminal(args.terminal)
        validate_account(a,positions,orders,mode=='NEW')
        print('MT5: '+details['key']+' | '+details['currency']+' | DEMO HEDGING',flush=True)
        if mode=='NEW':
            print('Старое состояние отсутствует. Создаётся НОВЫЙ локальный ключ и база; удалённая локальная история НЕ восстановлена.',flush=True)
            initialize_state(paths.state_dir,details)
        print('На телефоне укажите адрес и НОВЫЙ ключ из следующих строк. AUTO включается только вами в приложении.',flush=True)
        old=sys.argv
        try:
            sys.argv=[str(paths.program_root/'bridge_v10_0.py'),'--host','0.0.0.0','--port',str(args.port),
                      '--state-dir',str(paths.state_dir),'--terminal',details['terminal']]
            runpy.run_path(str(paths.program_root/'bridge_v10_0.py'),run_name='__main__')
        finally:sys.argv=old
        return 0
    finally:guard.close()

if __name__=='__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception as exc:
        print('\nBRIDGE НЕ ЗАПУЩЕН: '+str(exc),flush=True)
        print('Файлы состояния не удаляйте. Пришлите текст ошибки без ключа подключения.',flush=True)
        raise SystemExit(1)
