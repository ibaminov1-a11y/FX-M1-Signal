"""Apply a hash-checked text-only delta to the reproduced R5.1 candidate."""
from pathlib import Path
import base64,hashlib,json,lzma,subprocess,sys
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'tools/repair_layout52_manifest.json').read_text())
def check(phase):
    for name,hashes in manifest.items():
        assert not name.startswith(('/','.github/')) and '..' not in Path(name).parts,name
        p=root/name
        digest=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
        assert digest==hashes[phase],(phase,name,digest)
if '--verify' in sys.argv:
    check('after');print('R52_SOURCE_HASHES_VERIFIED',len(manifest));raise SystemExit
check('before')
patch=lzma.decompress(base64.b64decode((root/'tools/repair_layout52.b64').read_text().strip(),validate=True))
assert hashlib.sha256(patch).hexdigest()=='f457d1409d2c6fa42fcd9c3a9c6ad9dc5b2382766c849b2597a8870c4d32528b'
(root/'evidence').mkdir(exist_ok=True)
(root/'evidence/R52_PRODUCT.patch').write_bytes(patch)
for args in (['git','apply','--unidiff-zero','--check','-'],['git','apply','--unidiff-zero','-']):
    subprocess.run(args,input=patch,cwd=root,check=True)
check('after')
subprocess.run(['git','add','--',*manifest],cwd=root,check=True)
print('R52_EXACT_PATCH_APPLIED',len(manifest))
