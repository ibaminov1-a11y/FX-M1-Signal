from pathlib import Path
import re, shutil, datetime, subprocess, sys

ROOT = Path.cwd().resolve()
BASE = ROOT / "app/src/main/java/com/openai/fxm1"
MAIN = BASE / "MainActivity.java"
MON = BASE / "MonitoringService.java"
BUILDER = ROOT / "BUILD_APK_V10_SDK.py"

for p in (MAIN, MON):
    if not p.exists():
        print("ERROR: not found", p)
        input("Enter...")
        sys.exit(1)

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = ROOT / ("_V10_JAVA_COMPILE_FIX_BACKUP_" + stamp)
backup.mkdir(parents=True)
shutil.copy2(MAIN, backup / "MainActivity.java")
shutil.copy2(MON, backup / "MonitoringService.java")

def fix_vote_redeclarations(text):
    pos = 0
    while True:
        m = re.search(r'\\b(?:private|public)\\s+Analysis\\s+analyzeAdaptive\\s*\\(', text[pos:])
        if not m:
            break
        start = pos + m.start()
        brace = text.find("{", start)
        if brace < 0:
            break
        depth = 0
        end = None
        for i in range(brace, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            break
        block = text[start:end]
        pattern = r'int\\s+buyVotes\\s*=\\s*0\\s*(?:,\\s*sellVotes\\s*=\\s*0\\s*;|;\\s*\\n\\s*int\\s+sellVotes\\s*=\\s*0\\s*;)'
        matches = list(re.finditer(pattern, block))
        if len(matches) > 1:
            for mm in reversed(matches[1:]):
                indent = re.search(r'(?m)^(\\s*)', block[mm.start():]).group(1)
                repl = "buyVotes = 0;\n" + indent + "sellVotes = 0;"
                block = block[:mm.start()] + repl + block[mm.end():]
            text = text[:start] + block + text[end:]
            pos = start + len(block)
        else:
            pos = end
    return text

main = fix_vote_redeclarations(MAIN.read_text(encoding="utf-8"))
mon = fix_vote_redeclarations(MON.read_text(encoding="utf-8"))

if not re.search(r'\\bSharedPreferences\\s+prefs\\s*\\(\\s*\\)', mon):
    anchor = re.search(r'(?m)^\\s*private\\s+String\\s+currentSymbol\\s*\\(', mon)
    if not anchor:
        print("ERROR: currentSymbol anchor not found. No files changed.")
        input("Enter...")
        sys.exit(1)
    helper = '    private SharedPreferences prefs() {\n        return getSharedPreferences("fxm1", MODE_PRIVATE);\n    }\n\n'
    mon = mon[:anchor.start()] + helper + mon[anchor.start():]

MAIN.write_text(main, encoding="utf-8", newline="\n")
MON.write_text(mon, encoding="utf-8", newline="\n")

print("OK: MainActivity vote redeclarations fixed")
print("OK: MonitoringService vote redeclarations fixed")
print("OK: MonitoringService prefs() restored")
print("Backup:", backup)

if not BUILDER.exists():
    print("ERROR: BUILD_APK_V10_SDK.py not found.")
    input("Enter...")
    sys.exit(1)

print("\nStarting APK build again...")
r = subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT)
sys.exit(r.returncode)
