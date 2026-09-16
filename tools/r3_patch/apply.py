from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'mt5_bridge/event_core/engine.py'
text=p.read_text(encoding='utf-8')
old="""                q=self.quote;q.validate(now)\n                d=self.strategy.update(self.bars,self.context,q,now,self.campaign['side'] if self.campaign else 0)\n                self.decision=d;self.analysis_time=now\n"""
new="""                q=self.quote;q.validate(now)\n                campaign_side=self.campaign['side'] if self.campaign else 0\n                if self.config.timeframe=='M5':\n                    d=self.strategy.update(self.bars,self.context,q,now,campaign_side,\n                        m1=self.m1,m15=self.m15,h1=self.h1,live_bar=self.live_bar)\n                else:\n                    d=self.strategy.update(self.bars,self.context,q,now,campaign_side)\n                self.decision=d;self.analysis_time=now\n"""
if text.count(old)!=1:
    raise SystemExit('Engine strategy call block not found exactly once')
p.write_text(text.replace(old,new,1),encoding='utf-8')
