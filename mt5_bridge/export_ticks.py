"""Read-only MT5 export. Never sends/modifies/cancels an order. UTC dates required."""
import argparse,csv,json
from datetime import datetime,timezone,timedelta
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description='Export actual Bid/Ask ticks for EventCore replay, no trading')
    p.add_argument('--symbol',default='EURUSD');p.add_argument('--from-date',required=True);p.add_argument('--to-date',required=True)
    p.add_argument('--out',default='research-data');a=p.parse_args()
    start=datetime.fromisoformat(a.from_date).replace(tzinfo=timezone.utc);end=datetime.fromisoformat(a.to_date).replace(tzinfo=timezone.utc)
    if not start<end:raise SystemExit('from-date must precede to-date')
    import MetaTrader5 as mt5
    if not mt5.initialize():raise SystemExit(str(mt5.last_error()))
    try:
        info=mt5.symbol_info(a.symbol);tick=mt5.symbol_info_tick(a.symbol)
        if info is None or tick is None:raise SystemExit('No symbol/tick from MT5')
        margin=mt5.order_calc_margin(mt5.ORDER_TYPE_BUY,a.symbol,1.,tick.ask)
        if margin is None:raise SystemExit('No margin calculation')
        root=Path(a.out);root.mkdir(parents=True,exist_ok=True)
        meta=dict(symbol=info.name,point=info.point,digits=info.digits,tick_size=info.trade_tick_size or info.point,
            stops_level=info.trade_stops_level,freeze_level=info.trade_freeze_level,volume_min=info.volume_min,
            volume_max=info.volume_max,volume_step=info.volume_step,contract_size=info.trade_contract_size,
            currency_profit=info.currency_profit,margin_per_lot=margin,export_time=datetime.now(timezone.utc).isoformat(),
            from_utc=start.isoformat(),to_utc=end.isoformat(),note='Contract/margin snapshot is not historical broker-tier reconstruction')
        destination=root/'ticks.csv'
        if destination.exists():raise SystemExit('ticks.csv already exists; choose a new --out directory')
        n=0;last=None
        with destination.open('w',newline='',encoding='utf-8') as f:
            writer=csv.writer(f);writer.writerow(['time_msc','bid','ask'])
            while start<end:
                stop=min(end,start+timedelta(days=1));rows=mt5.copy_ticks_range(a.symbol,start,stop,mt5.COPY_TICKS_ALL)
                if rows is None:raise RuntimeError(str(mt5.last_error()))
                for x in rows:
                    key=(int(x['time_msc']),float(x['bid']),float(x['ask']))
                    if key==last or key[0]>=int(end.timestamp()*1000) or key[1]<=0 or key[2]<key[1]:continue
                    writer.writerow(key);last=key;n+=1
                start=stop
        meta['ticks']=n;(root/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Exported {n} ticks. No trading commands were sent.')
    finally:mt5.shutdown()
if __name__=='__main__':main()
