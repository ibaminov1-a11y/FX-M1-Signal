"""Transport-only validated line edits. Produces ordinary reviewed source before CI.
No code is executed from the payload; every old/new file is pinned by SHA256.
"""
from pathlib import Path, PurePosixPath
import hashlib, json, lzma
root=Path(__file__).resolve().parents[1]
blob=b''.join((root/'tools/r5delta'/f'part{i:02d}.xz').read_bytes() for i in range(9))
assert hashlib.sha256(blob).hexdigest()=='2bf34be9556fdc4029fbb6fc1501e58b1da99abfc273ecb2c1a329eb1cfab017'
raw=lzma.decompress(blob)
assert len(raw)==185491
changes=json.loads(raw)
prepared=[];seen=set()
for entry in changes:
    p=PurePosixPath(entry['path'])
    assert not p.is_absolute() and '..' not in p.parts and p.parts[0] in ('app','mt5_bridge','tests','tools','docs','.github'),p
    assert p.as_posix() not in seen,p
    seen.add(p.as_posix());path=root/p
    assert not path.is_symlink(),p
    old=path.read_bytes() if path.exists() else b''
    assert (not path.exists()) if entry['old'] is None else hashlib.sha256(old).hexdigest()==entry['old'],f'Preimage mismatch: {p}'
    lines=old.decode('utf-8').splitlines(keepends=True)
    last=len(lines)
    for start,end,text in reversed(entry['changes']):
        assert 0<=start<=end<=last,(p,start,end,last)
        lines[start:end]=text.splitlines(keepends=True);last=start
    result=''.join(lines).encode('utf-8')
    assert hashlib.sha256(result).hexdigest()==entry['new'],f'Postimage mismatch: {p}'
    prepared.append((path,result))
for path,result in prepared:
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(result)
(root/'evidence').mkdir(exist_ok=True)
(root/'evidence/source-manifest.json').write_text(json.dumps({e['path']:e['new'] for e in changes},indent=2),encoding='utf-8')
print('Verified and applied',len(prepared),'source files')
