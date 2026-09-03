from pathlib import Path
import shutil, datetime, subprocess, sys

ROOT=Path.cwd().resolve()
BASE=ROOT/"app/src/main/java/com/openai/fxm1"
MAIN=BASE/"MainActivity.java"
MON=BASE/"MonitoringService.java"
BUILDER=ROOT/"BUILD_APK_V10_SDK.py"

for p in (MAIN,MON,BUILDER):
    if not p.exists(): print("ERROR not found:",p); input("Enter..."); sys.exit(1)
stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup=ROOT/("_V10_FIX2_BACKUP_"+stamp)
backup.mkdir(parents=True)
shutil.copy2(MAIN,backup/MAIN.name)
shutil.copy2(MON,backup/MON.name)

def fix_votes(text):
    pos=0
    while True:
        s=text.find("analyzeAdaptive(",pos)
        if s<0: break
        brace=text.find("{",s)
        if brace<0: break
        depth=0; end=None
        for i in range(brace,len(text)):
            if text[i]=="{": depth+=1
            elif text[i]=="}":
                depth-=1
                if depth==0: end=i+1; break
        if end is None: break
        block=text[s:end]
        # Find declarations line-by-line and keep only first pair.
        ls=block.splitlines(True); seen=False; out=[]; skip_sell=False
        for line in ls:
            stripped=line.strip()
            if stripped=="int buyVotes = 0, sellVotes = 0;":
                if seen:
                    indent=line[:len(line)-len(line.lstrip())]
                    out.append(indent+"buyVotes = 0;\n"); out.append(indent+"sellVotes = 0;\n")
                else: out.append(line); seen=True
                continue
            if stripped=="int buyVotes = 0;":
                if seen:
                    indent=line[:len(line)-len(line.lstrip())]; out.append(indent+"buyVotes = 0;\n"); skip_sell=True
                else: out.append(line); seen=True
                continue
            if stripped=="int sellVotes = 0;" and skip_sell:
                indent=line[:len(line)-len(line.lstrip())]; out.append(indent+"sellVotes = 0;\n"); skip_sell=False; continue
            out.append(line)
        newblock="".join(out)
        text=text[:s]+newblock+text[end:]
        pos=s+len(newblock)
    return text

main=fix_votes(MAIN.read_text(encoding="utf-8"))
mon=fix_votes(MON.read_text(encoding="utf-8"))

if "SharedPreferences prefs()" not in mon:
    anchor=mon.find("private String currentSymbol(")
    if anchor<0: anchor=mon.find("String currentSymbol(")
    if anchor<0:
        print("ERROR currentSymbol anchor not found"); input("Enter..."); sys.exit(1)
    line_start=mon.rfind("\n",0,anchor)+1
    helper="    private SharedPreferences prefs() {\n        return getSharedPreferences(\"fxm1\", MODE_PRIVATE);\n    }\n\n"
    mon=mon[:line_start]+helper+mon[line_start:]

MAIN.write_text(main,encoding="utf-8",newline="\n")
MON.write_text(mon,encoding="utf-8",newline="\n")
print("OK: Java fixes applied")
print("Backup:",backup)
print("Starting APK build...")
sys.exit(subprocess.call([sys.executable,str(BUILDER)],cwd=ROOT))
