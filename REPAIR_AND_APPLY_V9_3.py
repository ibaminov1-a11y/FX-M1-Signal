from pathlib import Path
import shutil, subprocess, sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
HERE = Path(__file__).resolve().parent

backups = sorted(
    [p for p in ROOT.glob("_V9_2_BACKUP_*") if p.is_dir()],
    key=lambda p: p.stat().st_mtime,
    reverse=True
)
if not backups:
    print("ERROR: не найдена папка _V9_2_BACKUP_* от неудачного запуска V9.3")
    sys.exit(1)

backup = backups[0]
print("Использую backup:", backup)

rels = [
    Path("mt5_bridge/bridge_v9_2.py"),
    Path("app/src/main/java/com/openai/fxm1/MonitoringService.java"),
    Path("app/src/main/java/com/openai/fxm1/FeatureEngine.java"),
    Path("app/src/main/java/com/openai/fxm1/MainActivity.java"),
    Path("app/build.gradle"),
]

for rel in rels:
    src = backup / rel
    dst = ROOT / rel
    if not src.exists():
        print("ERROR: в backup нет", rel)
        sys.exit(1)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print("RESTORE:", rel)

print()
print("Backup восстановлен. Запускаю исправленный V9.3 updater...")
cmd = [sys.executable, str(HERE / "APPLY_V9_3_FIXED.py"), str(ROOT)]
rc = subprocess.call(cmd)
sys.exit(rc)
