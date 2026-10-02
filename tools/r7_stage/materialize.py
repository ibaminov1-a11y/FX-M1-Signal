"""One-time verified transport of the already tested source delta; no runtime updater."""
from pathlib import Path
import base64,hashlib,subprocess,zlib
ROOT=Path(__file__).resolve().parents[2]
EXPECTED='f6e412617011ba82da0d1214293d27b1cff9843e6ba16ca3bbb0fc76ba638e7d'
FILES=['app/build.gradle', 'app/src/androidTest/java/com/openai/fxm1/R7ReleaseUiTest.java', 'app/src/main/java/com/openai/fxm1/EventClient.java', 'app/src/main/java/com/openai/fxm1/PriceForecastPlot.java', 'app/src/main/java/com/openai/fxm1/ScenarioMapRenderer.java', 'app/src/main/java/com/openai/fxm1/ScenarioUi.java', 'app/src/main/java/com/openai/fxm1/SparklineView.java', 'mt5_bridge/event_core/__init__.py', 'mt5_bridge/event_core/engine.py', 'mt5_bridge/event_core/mt5_adapter.py', 'mt5_bridge/event_core/observers.py', 'mt5_bridge/event_core/price_forecast.py', 'mt5_bridge/event_core/risk.py', 'mt5_bridge/event_core/scenarios/core.py', 'mt5_bridge/event_core/scenarios/lifecycle.py', 'mt5_bridge/event_core/scenarios/structure.py', 'mt5_bridge/event_core/server.py', 'mt5_bridge/event_core/store.py', 'tests/event_core/test_r7_forecast_integration.py', 'tests/event_core/test_r7_price_forecast.py']
INSERT='d+Md42lSYFOaDwbOCKhnaAegVoGMZML+C2z5FCUOpfnk5kyLgTDJWPkNGsqbb+J3rH93OASBZ5Cza40333yjzbJGgmqkekvIQCPWvG6iazk0xyxk+iX65nUtL2iejsKLGev7X2E5X13+R1AUvsLlVNbv8mcafHyuwZM/Q6HPYYkRFf528rKBz34HL19NPkM8gEKEGj+Cr68AFwA54NFd3+seu7mda2fJqtdNF3wW/1SkXd8FCXUgIXRoExGAkUqTAdGVV4VCxDaT2M8wWFCkko8ebd6zfPg1PMWvsHcSuKd2RuxrxCL4UBBMwNPFCnZOu6aK/YDQhpblo9ckoFnZYW4yml/1BqIGsYFTNFoIGsoUtsL/WdZqr3prdY1J60LXfbKAiD83vZzSMFLNilkBmmmuVYBi3iiNnM5jUGW0lCkH8ONGCaT4oR9KOxCaiUYnXiewWElsTC/wEPoVznwfnsx4vQeLdz9+P/SPrQ+C4cDCpV33fediyjte9vglsdRx6PWtr'

def main():
    folder=Path(__file__).resolve().parent
    parts=[(folder/f'part{i}').read_text(encoding='ascii') for i in range(3)]
    # Restore a known transport omission. No source change; complete bytes pinned below.
    assert len(parts[0])==8483
    parts[0]=parts[0][:2052]+INSERT+parts[0][2052:]
    expected=['2c501b7323e294723ca644af0743f2ac6fab362a','b9a3c1b358e02ad9c8b927319d2d1ebe2a5793c2','6e3ccd0706a675e22e5bcd5016254861235d98af']
    for p,digest in zip(parts,expected):
        b=p.encode('ascii')
        assert hashlib.sha1(('blob '+str(len(b))+'\0').encode()+b).hexdigest()==digest
    patch=zlib.decompress(base64.b64decode(''.join(parts),validate=True))
    assert len(patch)==65456 and hashlib.sha256(patch).hexdigest()==EXPECTED
    names=[line.split()[2][2:] for line in patch.decode().splitlines() if line.startswith('diff --git ')]
    assert names==FILES,(names,FILES)
    subprocess.run(['git','apply','--check','-'],input=patch,cwd=ROOT,check=True)
    subprocess.run(['git','apply','-'],input=patch,cwd=ROOT,check=True)
    print('R7_SOURCE_DELTA_VERIFIED',EXPECTED,len(FILES))
if __name__=='__main__':main()
