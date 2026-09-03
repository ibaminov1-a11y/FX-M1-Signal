from pathlib import Path
import os, sys, shutil, subprocess, urllib.request, zipfile

ROOT = Path.cwd().resolve()
APP_GRADLE = ROOT / "app" / "build.gradle"
if not APP_GRADLE.exists():
    print("ERROR: Положи BUILD_APK_V10_SDK.py в корень FX-M1-Signal и запусти.")
    input("Enter...")
    sys.exit(1)

TOOLS = ROOT / ".v10-build-tools"
TOOLS.mkdir(exist_ok=True)

def run(cmd, cwd=None, env=None):
    print(">", " ".join(map(str, cmd)))
    p = subprocess.run(cmd, cwd=cwd or ROOT, env=env)
    if p.returncode != 0:
        raise RuntimeError("Команда завершилась с ошибкой: " + " ".join(map(str, cmd)))

def download(url, dst):
    if dst.exists() and dst.stat().st_size > 1024 * 1024:
        print("OK: уже скачано", dst.name)
        return
    print("Скачиваю:", url)
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    print("OK:", dst)

def find_android_sdk():
    candidates = []
    for k in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
        v = os.environ.get(k)
        if v:
            candidates.append(Path(v))
    local = ROOT / "local.properties"
    if local.exists():
        for line in local.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("sdk.dir="):
                raw = line.split("=",1)[1].strip().replace("\\\\","\\")
                candidates.append(Path(raw))
    candidates += [
        Path.home() / "AppData/Local/Android/Sdk",
        Path("C:/Users/Hp/AppData/Local/Android/Sdk"),
        Path("C:/Android/Sdk"),
    ]
    for p in candidates:
        if (p / "platform-tools").exists() or (p / "platforms").exists() or (p / "cmdline-tools").exists():
            return p.resolve()
    return None

env = os.environ.copy()

# Java 17
java_ok = False
try:
    p = subprocess.run(["java","-version"], capture_output=True, text=True)
    txt = (p.stdout or "") + (p.stderr or "")
    java_ok = p.returncode == 0 and any(f'version "{v}' in txt for v in ["17","18","19","20","21"])
except Exception:
    pass

if not java_ok:
    jdk_zip = TOOLS / "temurin17.zip"
    jdk_url = "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
    download(jdk_url, jdk_zip)
    jdk_root = TOOLS / "jdk17"
    if not jdk_root.exists():
        tmp = TOOLS / "_jdk_extract"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        with zipfile.ZipFile(jdk_zip, "r") as z:
            z.extractall(tmp)
        dirs = [p for p in tmp.iterdir() if p.is_dir()]
        if not dirs:
            raise RuntimeError("JDK не распаковался.")
        shutil.move(str(dirs[0]), str(jdk_root))
        shutil.rmtree(tmp, ignore_errors=True)
    env["JAVA_HOME"] = str(jdk_root)
    env["PATH"] = str(jdk_root / "bin") + os.pathsep + env.get("PATH","")

# Gradle 8.9
gradle_zip = TOOLS / "gradle-8.9-bin.zip"
download("https://services.gradle.org/distributions/gradle-8.9-bin.zip", gradle_zip)
gradle_dir = TOOLS / "gradle-8.9"
if not gradle_dir.exists():
    with zipfile.ZipFile(gradle_zip, "r") as z:
        z.extractall(TOOLS)
gradle_bat = gradle_dir / "bin" / "gradle.bat"
if not gradle_bat.exists():
    raise RuntimeError("Gradle 8.9 не найден.")

# Android SDK
sdk = find_android_sdk()
if sdk:
    print("OK: Android SDK найден:", sdk)
else:
    print("Android SDK не найден. Устанавливаю portable SDK...")
    sdk = TOOLS / "android-sdk"
    sdk.mkdir(exist_ok=True)
    cmd_zip = TOOLS / "commandlinetools-win.zip"

    # Current stable command-line tools package for Windows.
    # If Google changes the package ID, the script will fail with a clear error.
    cmd_url = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
    download(cmd_url, cmd_zip)

    latest = sdk / "cmdline-tools" / "latest"
    if not (latest / "bin" / "sdkmanager.bat").exists():
        tmp = TOOLS / "_cmdline_extract"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        with zipfile.ZipFile(cmd_zip, "r") as z:
            z.extractall(tmp)
        src = tmp / "cmdline-tools"
        if not src.exists():
            dirs = [p for p in tmp.iterdir() if p.is_dir()]
            if len(dirs) == 1:
                src = dirs[0]
        latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(latest, ignore_errors=True)
        shutil.move(str(src), str(latest))
        shutil.rmtree(tmp, ignore_errors=True)

    sdkmanager = latest / "bin" / "sdkmanager.bat"
    if not sdkmanager.exists():
        raise RuntimeError("sdkmanager.bat не найден после распаковки Android command-line tools.")

    env["ANDROID_HOME"] = str(sdk)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["PATH"] = str(sdk / "platform-tools") + os.pathsep + str(latest / "bin") + os.pathsep + env.get("PATH","")

    # Accept licenses automatically.
    yes_input = ("y\n" * 100)
    print("Принимаю Android SDK licenses...")
    subprocess.run([str(sdkmanager), "--sdk_root=" + str(sdk), "--licenses"],
                   input=yes_input, text=True, cwd=ROOT, env=env)

    # Detect compileSdk from app/build.gradle; fall back to 35.
    text = APP_GRADLE.read_text(encoding="utf-8", errors="ignore")
    import re
    m = re.search(r'compileSdk(?:Version)?\s+(\d+)', text)
    compile_sdk = m.group(1) if m else "35"

    print("Устанавливаю Android SDK packages...")
    run([str(sdkmanager), "--sdk_root=" + str(sdk),
         "platform-tools",
         f"platforms;android-{compile_sdk}",
         "build-tools;35.0.0"], env=env)

# local.properties
sdk_escaped = str(sdk).replace("\\","\\\\")
(ROOT / "local.properties").write_text("sdk.dir=" + sdk_escaped + "\n", encoding="utf-8")
env["ANDROID_HOME"] = str(sdk)
env["ANDROID_SDK_ROOT"] = str(sdk)

print()
print("==============================================")
print("FX M1 BOT V10.0 — BUILD ANDROID APK + SDK")
print("SDK:", sdk)
print("==============================================")

run([str(gradle_bat), "--no-daemon", "--stacktrace", ":app:assembleDebug"], env=env)

apk = ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
if not apk.exists():
    raise RuntimeError("Gradle завершился, но app-debug.apk не найден.")

print()
print("==============================================")
print("BUILD SUCCESSFUL")
print("APK:", apk)
print("==============================================")
print("Установи APK поверх текущего приложения.")
input("Нажми Enter...")
