"""Package exact verified R5.7 APK/source without user state or signing material."""
from pathlib import Path
import hashlib
import importlib.metadata as md
import json
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'evidence'
CERTIFICATE = '3d55a491046e661664f99c2a3e4a51338a794b313beb3e32d7ed88181a7a1885'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_certificate_report(report):
    lines=[line.strip() for line in report.splitlines() if 'certificate SHA-256 digest:' in line]
    if not lines:
        raise ValueError('APK original signing identity was not verified')
    for line in lines:
        match=re.fullmatch(r'(?:Signer #[1-9]\d*|V[1-4] Signer):? certificate SHA-256 digest: ([0-9a-fA-F]{64})',line)
        if match is None or match.group(1).lower()!=CERTIFICATE:
            raise ValueError('APK original signing identity was not verified')


def add_tree(archive, directory, prefix=''):
    for path in sorted(directory.rglob('*')):
        if path.is_file():
            archive.write(path, prefix + path.relative_to(directory).as_posix())


def main():
    sys.path.insert(0, str(ROOT / 'mt5_bridge'))
    from event_core import BUILD, PROTOCOL, REVISION, VERSION
    from audit57_report import main as audit_report
    from make_bridge_installer import build_installer

    if (VERSION, BUILD, PROTOCOL) != ('10.9-EC1', '10.9-EC1-R5.7', 'fxm1.event.v1'):
        raise ValueError('Bridge compatibility/build mismatch')
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD'], cwd=ROOT, check=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if (DEST / 'COMMIT.txt').read_text().strip() != commit:
        raise ValueError('Test evidence source does not match packaged source')
    signature = (DEST / 'apk-signature.txt').read_text()
    verify_certificate_report(signature)
    audit_report()

    # Clear only generated staging so stale release modules cannot survive repackaging.
    package = DEST / 'package'
    if package.exists():
        shutil.rmtree(package)
    bridge = package / 'Bridge'
    bridge.mkdir(parents=True)
    apk = package / 'FXM1_10_9_EVENT_CORE_DEMO.apk'
    shutil.copy2(ROOT / 'app/build/outputs/apk/debug/app-debug.apk', apk)
    for name in ('bridge_v10_0.py', 'START_BRIDGE_V10_0.bat', 'requirements_event.txt',
                 'export_ticks.py', 'research_config.json', 'CHECK_BROKER_CLOCK.py', 'CHECK_BROKER_CLOCK.cmd'):
        shutil.copy2(ROOT / 'mt5_bridge' / name, bridge / name)
    shutil.copytree(ROOT / 'mt5_bridge/event_core', bridge / 'event_core',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.orig'))
    installer = package / 'INSTALL_BRIDGE_R57.cmd'
    build_installer(bridge, installer, BUILD)

    # Pure-Python fallbacks with their licenses. Never copy platform extensions.
    vendor = bridge / '_vendor'
    vendor.mkdir()
    for distribution in ('Flask', 'Werkzeug', 'Jinja2', 'MarkupSafe', 'itsdangerous', 'click', 'blinker', 'colorama'):
        dist = md.distribution(distribution)
        for file in dist.files or []:
            path = Path(str(file))
            if path.is_absolute() or '..' in path.parts or path.suffix in ('.pyc', '.so', '.pyd', '.dll') or '__pycache__' in path.parts:
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = vendor / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    for name in ('START_HERE_R57_RU.md', 'INSTALL_RU.md', 'READ_ME_RU.md'):
        shutil.copy2(ROOT / 'docs/UPGRADE_R57.md', package / name)

    source_zip = DEST / 'FXM1_EVENT_CORE_SOURCE.zip'
    subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(source_zip), 'HEAD'], cwd=ROOT, check=True)
    # Prove each packaged first-party Bridge file came from the archived commit.
    with zipfile.ZipFile(source_zip) as source:
        for path in bridge.rglob('*'):
            if path.is_file() and '_vendor' not in path.relative_to(bridge).parts:
                name = 'mt5_bridge/' + path.relative_to(bridge).as_posix()
                if source.read(name) != path.read_bytes():
                    raise ValueError('Packaged Bridge differs from archived source: ' + name)
    metadata = {
        'commit': commit, 'version': VERSION, 'build': BUILD, 'version_code': 926,
        'protocol': PROTOCOL, 'revision': REVISION, 'apk_sha256': sha256(apk),
        'apk_certificate_sha256': CERTIFICATE, 'source_sha256': sha256(source_zip),
        'installer_sha256': sha256(installer),
        'bridge_files_sha256': {path.relative_to(bridge).as_posix(): sha256(path)
                                for path in sorted(bridge.rglob('*')) if path.is_file()},
        'status': 'DEMO_RESEARCH_CANDIDATE', 'market_backtest': 'not_run',
        'physical_phone': 'not_tested', 'real_trading': 'disabled_in_adapter',
    }
    (package / 'PROVENANCE.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    with zipfile.ZipFile(DEST / 'FXM1_10_9_EVENT_CORE_PACKAGE.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        add_tree(archive, package)
    shutil.copy2(apk, DEST / apk.name)

    full = DEST / 'FXM1_R5_7_FULL.zip'
    with zipfile.ZipFile(full, 'w', zipfile.ZIP_DEFLATED) as archive:
        add_tree(archive, package)
        archive.write(source_zip, 'Sources/FXM1_R5_7_SOURCE.zip')
        for name in ('COMMIT.txt', 'python-tests.log', 'android-build.log', 'android-runtime.log', 'native-fixes.log',
                     'R56_RED_UI_CONFIRMED.txt', 'R57_RED_UI_CONFIRMED.txt', 'R57_RED_PYTHON.log',
                     'R57_RED_PYTHON.json', 'apk-signature.txt',
                     'signing-certificate-sha256.txt', 'package-check.txt', 'ANDROID_TESTS.json',
                     'R57_RESULTS.json', 'R57_REPORT_RU.md'):
            path = DEST / name
            if path.exists():
                archive.write(path, 'Verification/' + name)
        for folder in ('r56-red', 'r57-red'):
            for path in sorted((DEST / folder).rglob('*.xml')):
                archive.write(path, 'Verification/' + path.relative_to(DEST).as_posix())
        for path in sorted((ROOT / 'docs/verification').glob('R57_*')):
            if path.is_file():
                archive.write(path, 'Verification/' + path.name)
        for path in sorted((ROOT / 'app/build/outputs/androidTest-results').rglob('TEST-*.xml')):
            archive.write(path, 'Verification/android-results/' + path.relative_to(ROOT / 'app/build/outputs/androidTest-results').as_posix())
        for path in sorted((DEST / 'ui').rglob('*.png')):
            archive.write(path, 'Verification/' + path.relative_to(DEST).as_posix())
    with zipfile.ZipFile(full) as archive:
        if archive.testzip() is not None:
            raise ValueError('Full release ZIP failed integrity check')
        if archive.read(apk.name) != apk.read_bytes():
            raise ValueError('Full release APK does not match tested APK')
    if full.stat().st_size >= 32 * 1024 * 1024:
        raise ValueError('Delivery ZIP exceeds the 32 MiB download limit')
    with zipfile.ZipFile(DEST / 'FXM1_R5_7_BRIDGE.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        add_tree(archive, bridge, 'Bridge/')
        for name in ('INSTALL_BRIDGE_R57.cmd', 'INSTALL_RU.md', 'PROVENANCE.json'):
            archive.write(package / name, name)
    (DEST / 'SHA256SUMS.txt').write_text(''.join(sha256(path) + '  ' + path.name + '\n' for path in
        (full, DEST / apk.name, source_zip, DEST / 'FXM1_R5_7_BRIDGE.zip')), encoding='ascii')
    print('R57_PACKAGE_OK', commit, full.stat().st_size, sha256(full))


if __name__ == '__main__':
    main()
