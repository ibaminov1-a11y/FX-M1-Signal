"""Apply reviewed R5 diff bundle in RED then GREEN phases; no network or secrets."""
from pathlib import Path
import hashlib,json,lzma,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
DIGEST='f637e6db3fe7258ef086ea6bea8b5dd6564d9fc5e219bb7f678625a25d153711'
RED={'tests/event_core/test_r5_lot_history.py','app/src/androidTest/java/com/openai/fxm1/R5SettingsHistoryTest.java'}
phase=sys.argv[1]
assert phase in ('red','green')
raw=b''.join((ROOT/f'tools/r5bundle.part{i:02d}').read_bytes() for i in range(6))
assert hashlib.sha256(raw).hexdigest()==DIGEST,'Change bundle hash mismatch'
data=json.loads(lzma.decompress(raw))
for name,entry in data.items():
    path=Path(name)
    assert not path.is_absolute() and '..' not in path.parts and path.parts[0] in ('app','mt5_bridge','tests','tools','docs','.github'),name
    if (name in RED)!=(phase=='red'):continue
    if entry['kind']=='patch':
        subprocess.run(['git','apply','--unidiff-zero','-'],cwd=ROOT,input=entry['data'].encode(),check=True)
    else:
        assert entry['kind']=='file',entry['kind']
        target=ROOT/path;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(entry['data'],encoding='utf-8')
    print(phase,name)
