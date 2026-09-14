from pathlib import Path
import base64, subprocess

root=Path(__file__).resolve().parents[2]
here=Path(__file__).resolve().parent
parts=sorted(here.glob('part*.b64'))
if len(parts)!=8:
    raise SystemExit(f'Expected 8 patch parts, got {len(parts)}')
raw=base64.b64decode(''.join(p.read_text(encoding='ascii') for p in parts))
patch=Path('/tmp/ec1-r2.patch')
patch.write_bytes(raw)
subprocess.run(['patch','-p1','--forward','--batch','-i',str(patch)],cwd=root,check=True)
# VERSION remains compatible with the installed APK; BUILD identifies this repair.
init=root/'mt5_bridge/event_core/__init__.py'
text=init.read_text(encoding='utf-8').replace("BUILD = '10.9-EC1-R1'","BUILD = '10.9-EC1-R2'")
init.write_text(text,encoding='utf-8')
print('EC1 R2 patch applied:', len(raw), 'bytes')
