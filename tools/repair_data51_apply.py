"""Apply the exact reviewed R5.1 candidate, with base and output hashes checked.

The two base64 parts carry a compressed text patch, not executable binary code.
No workflow files, credentials or user state are included in the product patch.
"""
from pathlib import Path
import base64,hashlib,json,lzma,subprocess,sys
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'tools/repair_data51_manifest.json').read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
def check(which):
    for name,hashes in manifest.items():
        p=root/name
        if name.startswith('/') or '..' in Path(name).parts or name.startswith('.github/'):
            raise ValueError('Unsafe product path: '+name)
        if digest(p)!=hashes[which]:raise ValueError('Source hash mismatch '+which+': '+name)
if '--verify' in sys.argv:
    check('after');print('R51_SOURCE_HASHES_VERIFIED',len(manifest));raise SystemExit
check('before')
encoded=''.join((root/('tools/repair_data51.part'+str(i))).read_text().strip() for i in (1,2))
patch=lzma.decompress(base64.b64decode(encoded,validate=True))
assert hashlib.sha256(patch).hexdigest()=='6b47f9ed05e35f8ba2abb5b9c15f5e7038ac4f9fceb536e55a4ea3f5da2bb9d5'
subprocess.run(['git','apply','--unidiff-zero','--check','-'],input=patch,cwd=root,check=True)
subprocess.run(['git','apply','--unidiff-zero','-'],input=patch,cwd=root,check=True)
check('after')
subprocess.run(['git','add','--',*manifest],cwd=root,check=True)
print('R51_EXACT_PATCH_APPLIED',len(manifest))
