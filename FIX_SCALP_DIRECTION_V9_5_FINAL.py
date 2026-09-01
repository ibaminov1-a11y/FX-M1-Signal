from pathlib import Path
import sys, shutil, datetime

ROOT = Path.cwd().resolve()
target = ROOT / "app" / "src" / "main" / "java" / "com" / "openai" / "fxm1" / "MonitoringService.java"

if not target.exists():
    print("ERROR: Положи файл в корень FX-M1-Signal и запусти.")
    input("Enter...")
    sys.exit(1)

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / f"_SCALP_DIRECTION_FINAL_BACKUP_{stamp}" / "MonitoringService.java"
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(target, backup)

s = target.read_text(encoding="utf-8")

quality_anchor = '        int quality = setupQualityAdaptive(signal, sHigher2, sHigher1, sEntry, sFast, structure, breakout);'
sl_anchor = '        double slMult = "SCALP".equals(mode) ? 0.85 : 1.8;'

q = s.find(quality_anchor)
if q < 0:
    print("ERROR: Не найден quality anchor. Ничего не изменено.")
    input("Enter...")
    sys.exit(1)

start = q + len(quality_anchor)
end = s.find(sl_anchor, start)
if end < 0:
    print("ERROR: Не найден slMult anchor. Ничего не изменено.")
    input("Enter...")
    sys.exit(1)

new_logic = '''

        // V9.5 FINAL FIX: independent SCALP directional bias.
        // Direction only. Bridge still requires pullback -> rejection -> resume -> micro-break.
        int scalpDirectionScore = 0;
        String scalpIntent = "WAIT";

        if ("SCALP".equals(mode)) {
            scalpDirectionScore += sHigher2 * 18;
            scalpDirectionScore += sHigher1 * 24;
            scalpDirectionScore += sEntry   * 28;
            scalpDirectionScore += sFast    * 20;
            scalpDirectionScore += structure * 10;
            scalpDirectionScore = Math.max(-100, Math.min(100, scalpDirectionScore));

            int buyVotes = 0;
            int sellVotes = 0;
            int[] scalpVotes = {sHigher2, sHigher1, sEntry, sFast, structure};
            for (int v : scalpVotes) {
                if (v > 0) buyVotes++;
                else if (v < 0) sellVotes++;
            }

            boolean localBuy = sEntry > 0 && (sFast >= 0 || structure >= 0);
            boolean localSell = sEntry < 0 && (sFast <= 0 || structure <= 0);

            boolean buyBias =
                    (scalpDirectionScore >= 28 && buyVotes >= 3 && sellVotes <= 2)
                    || (localBuy && buyVotes >= 3 && scalpDirectionScore >= 18);

            boolean sellBias =
                    (scalpDirectionScore <= -28 && sellVotes >= 3 && buyVotes <= 2)
                    || (localSell && sellVotes >= 3 && scalpDirectionScore <= -18);

            if (buyBias && !sellBias) {
                scalpIntent = "BUY";
            } else if (sellBias && !buyBias) {
                scalpIntent = "SELL";
            }
        }

'''

s = s[:start] + new_logic + s[end:]

if s.count("{") != s.count("}"):
    print("ERROR: Нарушен баланс скобок. Восстанавливаю исходник.")
    shutil.copy2(backup, target)
    input("Enter...")
    sys.exit(1)

segment = s[s.find(quality_anchor):s.find(sl_anchor, s.find(quality_anchor))]
required = [
    'int scalpDirectionScore = 0;',
    'String scalpIntent = "WAIT";',
    'scalpDirectionScore >= 28',
    'scalpDirectionScore <= -28',
]
for item in required:
    if item not in segment:
        print("ERROR: Проверка не пройдена:", item)
        shutil.copy2(backup, target)
        input("Enter...")
        sys.exit(1)

if 'scalpDirectionScore >= 45' in segment or 'scalpDirectionScore <= -45' in segment:
    print("ERROR: Старый порог 45 остался. Восстанавливаю исходник.")
    shutil.copy2(backup, target)
    input("Enter...")
    sys.exit(1)

target.write_text(s, encoding="utf-8", newline="\n")

print("==============================================")
print("DONE: SCALP DIRECTION V9.5 FINAL")
print("Adaptive direction: 18/28")
print("Global signal does NOT directly open SCALP")
print("Bridge micro-trigger remains mandatory")
print("Network throttle 1s/2s: НЕ ТРОГАЛ")
print("File:", target)
print("Backup:", backup)
print("==============================================")
input("Нажми Enter...")
