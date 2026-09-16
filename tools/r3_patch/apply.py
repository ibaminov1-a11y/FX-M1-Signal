from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def replace_once(path, old, new):
    p=ROOT/path
    text=p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'expected source block not found in {path}')
    if text.count(old)!=1:
        raise SystemExit(f'expected source block is not unique in {path}')
    p.write_text(text.replace(old,new,1),encoding='utf-8')

replace_once(
    Path('mt5_bridge/event_core/mt5_adapter.py'),
    """        if not values:\n            raise Blocked('MT5 не вернул ни одной закрытой свечи '+tf+': '+str(self.mt5.last_error()))\n        return values[-count:]\n\n    def positions(self):\n""",
    """        if not values:\n            raise Blocked('MT5 не вернул ни одной закрытой свечи '+tf+': '+str(self.mt5.last_error()))\n        return values[-count:]\n\n    def current_bar(self,symbol,tf):\n        \"\"\"Return the currently forming MT5 bar without mixing it into closed history.\"\"\"\n        timeframe=getattr(self.mt5,'TIMEFRAME_'+tf,None)\n        if timeframe is None: raise Blocked('Таймфрейм MT5 не поддерживается')\n        rows=self.mt5.copy_rates_from_pos(symbol,timeframe,0,1)\n        if rows is None or len(rows)==0:\n            raise Blocked('MT5 не вернул текущую свечу '+tf+': '+str(self.mt5.last_error()))\n        x=rows[-1]\n        return Bar(int(x['time']),float(x['open']),float(x['high']),float(x['low']),float(x['close']),float(x['tick_volume']))\n\n    def positions(self):\n"""
)

replace_once(
    Path('mt5_bridge/event_core/engine.py'),
    """        self.last_bars_at=0.;self.bars=[];self.context=[];self.quote=None;self.info={}\n        self.market_time=0.;self.market_errors=[];self.quote_ready=False\n""",
    """        self.last_bars_at=0.;self.bars=[];self.context=[];self.quote=None;self.info={}\n        # R3 M5 hierarchy. Closed bars stay separate from the forming M5 candle.\n        self.m1=[];self.m15=[];self.h1=[];self.live_bar=None\n        self.market_time=0.;self.market_errors=[];self.quote_ready=False\n"""
)
