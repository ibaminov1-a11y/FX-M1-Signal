"""Scope check, not a runtime test: forbid trading/transport changes in the theme build."""
import subprocess
from pathlib import Path
BASE='dbaaa9caca51e6013ea34200d76537bd8cbbdfea'
def previous(path):
    return subprocess.check_output(['git','show',BASE+':'+path])
for path in subprocess.check_output(['git','ls-tree','-r','--name-only',BASE],text=True).splitlines():
    if path.startswith('v11_bridge/') or path.endswith('/V11Api.java') or path.endswith('/AndroidManifest.xml'):
        assert Path(path).read_bytes()==previous(path), 'Unrequested trading/transport change: '+path
service='app/src/main/java/com/openai/fxm1/V11Service.java'
expected=previous(service).decode().replace(
    'expanded.setTextViewText(R.id.n_reason,reason);',
    'expanded.setTextViewText(R.id.n_reason,V11Activity.colorizeSides(reason));').replace(
    '.setContentTitle("FX M1 · V11")',
    '.setColor(V11Activity.BLUE).setContentTitle("FX M1 · V11")')
assert Path(service).read_text()==expected, 'Unexpected service logic change'
print('PASS: Bridge, strategy, risk, protocol, permissions and command/latch logic unchanged')
