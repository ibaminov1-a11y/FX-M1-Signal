import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'mt5_bridge'))
from event_core.model import Bar,Quote,Config
from event_core.strategy import Strategy

NOW=1800000000
TF=300

def bars_from_closes(closes):
    out=[]
    for i,c in enumerate(closes):
        o=c-0.00002
        out.append(Bar(NOW-(len(closes)-i)*TF,o,c+0.00004,o-0.00004,c,10))
    return out

def sell_pullback_bars():
    anchors={2:1.2100,7:1.2080,12:1.2092,17:1.2070,22:1.2082,27:1.2060,31:1.2069}
    n=32;cl=[None]*n;idx=sorted(anchors)
    for a,b in zip(idx[:-1],idx[1:]):
        va,vb=anchors[a],anchors[b]
        for i in range(a,b+1):
            t=(i-a)/(b-a);cl[i]=va+(vb-va)*t
    for i in range(idx[0]):cl[i]=anchors[idx[0]]+0.0001*(idx[0]-i)
    return bars_from_closes(cl)

def mirror(rows):
    return [Bar(b.time,2.4-b.open,2.4-b.low,2.4-b.high,2.4-b.close,b.volume) for b in rows]

class PullbackBootstrapTests(unittest.TestCase):
    def test_established_trend_with_completed_pullback_arms_fresh_trigger(self):
        for side in (-1,1):
            with self.subTest(side=side):
                bars=sell_pullback_bars();
                if side==1: bars=mirror(bars)
                cfg=Config(symbol='EUR/USD',timeframe='M5',mode='NORMAL',fee_per_lot=0,approved=True)
                s=Strategy(cfg)
                bid=bars[-1].close
                q=Quote(NOW*1000,bid,bid+0.00001)
                d=s.update(bars,bars,q,NOW)
                self.assertEqual(d.phase,'TRIGGER',d.reason)
                self.assertEqual(d.side,side)
                self.assertIsNotNone(s.setup)
                self.assertEqual(s.setup.phase,'TRIGGER')
                self.assertEqual(d.signal,'WAIT')
                # Arm on the safe side first; no immediate/retrospective entry is allowed.
                d=s.update(bars,bars,Quote((NOW+1)*1000,bid,bid+0.00001),NOW+1)
                self.assertEqual(d.phase,'TRIGGER')
                trigger=s.setup.trigger
                crossed=trigger+side*0.00002
                d=s.update(bars,bars,Quote((NOW+2)*1000,crossed,crossed+0.00001),NOW+2)
                self.assertEqual(d.phase,'ENTRY_READY',d.reason)
                self.assertEqual(d.side,side)

if __name__=='__main__':unittest.main()
