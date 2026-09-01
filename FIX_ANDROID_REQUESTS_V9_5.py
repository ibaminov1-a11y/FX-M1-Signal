from pathlib import Path
import sys, shutil, datetime, re

HERE = Path(__file__).resolve().parent
candidates = [HERE, HERE.parent, Path.cwd(), Path.cwd().parent]
ROOT = None
for c in candidates:
    if (c / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MonitoringService.java").exists():
        ROOT = c.resolve()
        break

if ROOT is None:
    print("ERROR: не найден корень FX-M1-Signal.")
    print("Положи этот файл в корень FX-M1-Signal и запусти ещё раз.")
    input("Enter...")
    sys.exit(1)

target = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MonitoringService.java"
stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"_ANDROID_REQUEST_FIX_BACKUP_{stamp}" / "MonitoringService.java"
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(target, backup)

s = target.read_text(encoding="utf-8")

def fail(msg):
    print("ERROR:", msg)
    print("Исходный файл сохранён:", backup)
    input("Enter...")
    sys.exit(1)

anchor = "    private final ExecutorService liveExecutor = Executors.newSingleThreadExecutor();"
if anchor not in s:
    fail("не найден liveExecutor — файл не похож на текущую V9.4/V9.5")

fields = '''    private static final long MT5_SNAPSHOT_MS = 1000L;
    private static final long POSITION_MANAGE_MS = 2000L;
    private volatile long lastMt5SnapshotDispatchMs = 0L;
    private volatile long lastPositionManageDispatchMs = 0L;
'''
if "MT5_SNAPSHOT_MS" not in s:
    s = s.replace(anchor, anchor + "\n" + fields, 1)

pattern = re.compile(
    r'''    // V9\.4: MT5/UI/position management independent from Twelve Data cadence\.\s*
    private final Runnable liveMt5Runnable = new Runnable\(\) \{.*?^    \};''',
    re.S | re.M
)

replacement = r'''    // V9.5 Android network throttle.
    // Bridge keeps the 100 ms SCALP runtime. Android only reads MT5 state once/sec.
    private final Runnable liveMt5Runnable = new Runnable() {
        @Override
        public void run() {
            if (!running) return;

            long now = SystemClock.elapsedRealtime();
            long elapsed = now - lastMt5SnapshotDispatchMs;
            if (elapsed < MT5_SNAPSHOT_MS) {
                handler.removeCallbacks(this);
                handler.postDelayed(this, MT5_SNAPSHOT_MS - elapsed);
                return;
            }
            lastMt5SnapshotDispatchMs = now;

            liveExecutor.execute(() -> {
                try {
                    refreshMt5Snapshot();
                } catch (Exception ignored) { }
            });

            handler.removeCallbacks(this);
            handler.postDelayed(this, MT5_SNAPSHOT_MS);
        }
    };

    // Position manager is intentionally slower than quote/P&L refresh.
    private final Runnable positionManagerRunnable = new Runnable() {
        @Override
        public void run() {
            if (!running) return;

            long now = SystemClock.elapsedRealtime();
            long elapsed = now - lastPositionManageDispatchMs;
            if (elapsed < POSITION_MANAGE_MS) {
                handler.removeCallbacks(this);
                handler.postDelayed(this, POSITION_MANAGE_MS - elapsed);
                return;
            }
            lastPositionManageDispatchMs = now;

            liveExecutor.execute(() -> {
                try {
                    manageOpenPositions();
                } catch (Exception ignored) { }
            });

            handler.removeCallbacks(this);
            handler.postDelayed(this, POSITION_MANAGE_MS);
        }
    };'''

s2, n = pattern.subn(replacement, s, count=1)
if n != 1:
    if "positionManagerRunnable" not in s:
        fail(f"не удалось заменить старый liveMt5Runnable (совпадений {n})")
else:
    s = s2

old_start = '''        handler.removeCallbacks(liveMt5Runnable);
        handler.post(liveMt5Runnable);'''
new_start = '''        lastMt5SnapshotDispatchMs = 0L;
        lastPositionManageDispatchMs = 0L;
        handler.removeCallbacks(liveMt5Runnable);
        handler.removeCallbacks(positionManagerRunnable);
        handler.post(liveMt5Runnable);
        handler.post(positionManagerRunnable);'''

if new_start not in s:
    if old_start not in s:
        fail("не найден блок запуска liveMt5Runnable")
    s = s.replace(old_start, new_start, 1)

old_stop = '''        handler.removeCallbacks(notificationWatchdog);
        handler.removeCallbacks(liveMt5Runnable);'''
new_stop = '''        handler.removeCallbacks(notificationWatchdog);
        handler.removeCallbacks(liveMt5Runnable);
        handler.removeCallbacks(positionManagerRunnable);'''
s = s.replace(old_stop, new_stop)

s = s.replace(
    '''                refreshMt5Snapshot();
                manageOpenPositions();
                updateWatchlistRadar(key, tf);''',
    '''                updateWatchlistRadar(key, tf);'''
)

if "positionManagerRunnable" not in s:
    fail("positionManagerRunnable отсутствует после изменения")
if "MT5_SNAPSHOT_MS = 1000L" not in s or "POSITION_MANAGE_MS = 2000L" not in s:
    fail("тайминги 1s/2s не установлены")

live_block = re.search(r'private final Runnable liveMt5Runnable.*?^    \};', s, re.S | re.M)
if not live_block:
    fail("liveMt5Runnable не найден после изменения")
if "manageOpenPositions();" in live_block.group(0):
    fail("manageOpenPositions всё ещё находится в 1-sec MT5 loop")

if s.count("{") != s.count("}"):
    fail("нарушен баланс фигурных скобок Java")

target.write_text(s, encoding="utf-8", newline="\n")

print()
print("==============================================")
print("DONE: MonitoringService.java исправлен")
print("MT5 snapshot: 1 сек")
print("Position manager: 2 сек")
print("Bridge SCALP runtime: НЕ менялся (100 ms остаётся в Bridge)")
print("Файл:", target)
print("Backup:", backup)
print("==============================================")
input("Нажми Enter...")
