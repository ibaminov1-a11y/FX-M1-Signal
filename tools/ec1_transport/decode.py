"""CI-only source transfer. Verify exact baseline before committing readable sources."""
from pathlib import Path
import base64,hashlib,json,lzma,subprocess
root=Path(__file__).resolve().parents[2]
folder=Path(__file__).parent
raw=base64.b64decode(''.join((folder/f'part{i}.b64').read_text() for i in range(6)),validate=True)
assert hashlib.sha256(raw).hexdigest()=='c6f3fa1e2031a5faa85d2739a09f43f3bd013f9b2a6fd8602e2eb25956f1895c'
delta=json.loads(lzma.decompress(raw))
prepared={}
for name,item in delta.items():
    rel=Path(name)
    assert not rel.is_absolute() and '..' not in rel.parts
    assert rel.parts[0] in ('app','mt5_bridge','tests','tools','docs')
    p=root/rel
    if 'new' in item:
        assert not p.exists(),name
        text=item['new']
    else:
        old=p.read_bytes();assert hashlib.sha256(old).hexdigest()==item['sha256'],name
        lines=old.decode('utf-8').splitlines(keepends=True)
        for start,end,replacement in reversed(item['ops']):
            lines[start:end]=[replacement]
        text=''.join(lines)
    prepared[p]=text
for p,text in prepared.items():
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
print('Restored readable sources:',len(prepared))
