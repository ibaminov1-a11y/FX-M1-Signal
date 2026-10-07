"""Export real Engine/risk replay snapshots, never real brokerage evidence."""
import copy,json
from pathlib import Path
from test_r75_ten_positions import SeriesFixture

def export():
    result=[]
    for side in (1,-1):
        f=SeriesFixture(side,'SCALP')
        try:
            state=f.tick(f.zone+side*.5*f.a)
            result.append(dict(side=side,count=0,state=copy.deepcopy(state)))
            for d in (.04,.20,.24):state=f.tick(f.zone+side*d*f.a)
            assert len(f.b.sent)==1
            result.append(dict(side=side,count=1,state=copy.deepcopy(state)))
            for count in range(2,11):
                state=f.add();assert len(f.b.sent)==count
                if count in (2,10):result.append(dict(side=side,count=count,state=copy.deepcopy(state)))
        finally:f.close()
    out=Path('app/src/androidTest/assets');out.mkdir(parents=True,exist_ok=True)
    (out/'r75-series.json').write_text(json.dumps(result,allow_nan=False))
    return result
if __name__=='__main__':print('R75_SERIES_SNAPSHOTS',len(export()))
