"""Ephemeral, read-only scenario observers; never dispatch or archive trade events."""
from dataclasses import asdict, replace
import copy

from .model import Blocked, Decision, TF_SECONDS, bar_close_time, live_structure, validate_bar_history
from .scenarios.core import ScenarioCore

PUBLIC_TIMEFRAMES=('M1','M5','M15','M30','H1','H4','D1','W1','MN1')
CONTEXT={'M1':'M5','M5':'M15','M10':'H1','M15':'H1','M30':'H1','H1':'H4',
         'H4':'D1','D1':'W1','W1':'MN1','MN1':'MN1'}


class ForecastObservers:
    """All methods run under the Engine lock, including native MT5 reads.

    Two frames per worker cycle keep startup bounded to four cycles. Bar reads
    share a one-second cache with the selected pipeline. HTTP reads never poll
    MT5 or advance a scenario. Observer state deliberately does not survive a
    restart and is never written to the selected engine's scenario archive.
    """
    def __init__(self):
        self.identity=None;self.cores={};self.views={};self.series={};self.attempts={};self.cursor=0

    def source_identity(self,engine):
        profile=asdict(replace(engine.config,approved=False))
        clock=engine.broker.clock_identity() if hasattr(engine.broker,'clock_identity') else engine.broker_clock_identity
        return (engine.account_key,engine.account.get('key',''),engine.market_scope(),
                engine.broker_clock_identity,clock,tuple(sorted(profile.items())))

    def sync(self,engine):
        identity=self.source_identity(engine)
        if identity!=self.identity:
            self.__init__();self.identity=identity

    def remember(self,tf,bars,now,error=''):
        self.series[tf]=dict(bars=list(bars),at=now,error=error)

    def _bars(self,engine,tf,now):
        prior=self.series.get(tf)
        if prior is None or not 0<=now-prior['at']<1:
            try:
                symbol=engine.info['name']
                if prior is None and hasattr(engine.broker,'history_bars'):
                    bars=list(engine.broker.history_bars(symbol,tf,1200))
                else:bars=list(engine.broker.bars(symbol,tf))
                if not bars:raise Blocked('MT5 вернул пустую историю '+tf)
                validate_bar_history(bars,tf,now)
                # Retain earlier genuine candles in memory, never another frame's series.
                merged={b.time:b for b in (prior or {}).get('bars',[])}
                merged.update({b.time:b for b in bars})
                bars=sorted(merged.values(),key=lambda b:b.time)[-1200:]
                validate_bar_history(bars,tf,now)
                self.remember(tf,bars,now)
            except Exception as exc:
                self.remember(tf,(prior or {}).get('bars',[]),now,'История '+tf+' не обновлена: '+str(exc))
            prior=self.series[tf]
        if prior['error']:raise Blocked(prior['error'])
        bars=prior['bars']
        if now-bar_close_time(bars[-1].time,tf,bars[-1].clock_offset_seconds)>TF_SECONDS[tf]*1.5:
            raise Blocked('Закрытые свечи '+tf+' устарели')
        return bars

    def blocked_reason(self,engine,now):
        if not engine.account or engine.account.get('key')!=engine.account_key:
            return 'Счёт MT5 не привязан; наблюдения прошлого счёта скрыты'
        if self.identity[3]!=self.identity[4]:return 'Часы MT5 изменены; требуется перезапуск Bridge'
        if engine.config.engine_mode!='SCENARIO_V2':return 'Независимые сценарии доступны в профиле Scenario V2'
        if not engine.quote_ready or engine.quote is None:return 'Нет пригодной свежей котировки MT5'
        if not -2<=now-engine.quote.time_msc/1000<=10:return 'Котировка MT5 устарела'
        if not 0<=now-engine.account_time<10:return 'Снимок счёта MT5 устарел'
        return ''

    def refresh(self,engine,now,budget=2):
        self.sync(engine)
        if self.blocked_reason(engine,now):return
        done=0
        for _ in PUBLIC_TIMEFRAMES:
            tf=PUBLIC_TIMEFRAMES[self.cursor];self.cursor=(self.cursor+1)%len(PUBLIC_TIMEFRAMES)
            if tf==engine.config.timeframe or 0<=now-self.attempts.get(tf,-1e30)<1:continue
            self.attempts[tf]=now;done+=1
            config=replace(engine.config,timeframe=tf)
            core=self.cores.setdefault(tf,ScenarioCore(config))
            view=copy.deepcopy(self.views.get(tf,{}))
            try:
                bars=self._bars(engine,tf,now)
                live=engine.broker.current_bar(engine.info['name'],tf)
                if live.time>now+60:raise Blocked('MT5 вернул текущую '+tf+' свечу из будущего')
                if live.time<=bars[-1].time:raise Blocked('Текущая '+tf+' свеча не следует за закрытой историей')
                view.update(bars=[asdict(b) for b in bars],live_bar=asdict(live),
                    live_structure=list(live_structure(bars,live)))
                context=self._bars(engine,CONTEXT[tf],now)
                m15=self._bars(engine,'M15',now) if tf=='M5' else []
                h1=self._bars(engine,'H1',now) if tf=='M5' else []
                decision=core.evaluate(bars,self._bars(engine,'M1',now),m15,h1,live,engine.quote,now,context=context,
                    context_tf=CONTEXT[tf],clock_generation=engine.broker_clock_identity,market_scope=engine.market_scope())
                if not decision.forecast.get('available'):
                    raise Blocked(decision.reason)
                price_forecast=decision.forecast.get('price_forecast',{})
                if price_forecast.get('available'):
                    engine.store.save_price_forecast(price_forecast)
                    engine.store.settle_price_forecasts(price_forecast['scope'],engine.quote,now)
                view.update(available=True,reason=decision.reason,decision=decision.json(),
                    forecast=copy.deepcopy(decision.forecast),analysis_time=now,market_time=now,
                    context_time=context[-1].time,quote=asdict(engine.quote),market_errors=[])
            except Exception as exc:
                core.suspend()
                reason=str(exc)
                view.update(available=False,reason=reason,market_errors=[reason],
                    decision=Decision(phase='DATA_BLOCK',reason=reason).json())
                view.setdefault('forecast',{}).update(available=False,stale=True,reason=reason)
            # Observers cannot enqueue execution audit records in the selected namespace.
            core.pending_snapshots.clear();core.events.clear()
            self.views[tf]=view
            if done>=max(1,min(int(budget),len(PUBLIC_TIMEFRAMES))):break

    def _record(self,engine,tf):
        if tf==engine.config.timeframe:
            return dict(available=bool(engine.forecast.get('available',bool(engine.forecast))) and not engine.market_errors,
                forecast=engine.forecast,decision=engine.decision.json(),analysis_time=engine.analysis_time,
                market_time=engine.market_time,market_errors=engine.market_errors,
                reason='; '.join(engine.market_errors) or engine.decision.reason,
                context_time=engine.context[-1].time if engine.context else 0,
                quote=asdict(engine.quote) if engine.quote else None)
        return self.views.get(tf,{})

    def _status(self,record,tf,now,blocked):
        reason=blocked
        if not reason and record.get('analysis_time') and not 0<=now-record['analysis_time']<=10:
            reason='Прогноз '+tf+' устарел; ожидаем новый расчёт'
        return (bool(record.get('available')) and not reason,
                reason or record.get('reason') or 'Прогноз '+tf+' ещё не рассчитан')

    def _wrong_identity(self,engine):
        return not engine.account or engine.account.get('key')!=engine.account_key or self.identity[3]!=self.identity[4]

    def frame(self,engine,tf,now):
        self.sync(engine)
        config=asdict(replace(engine.config,timeframe=tf))
        record=self._record(engine,tf)
        available,reason=self._status(record,tf,now,self.blocked_reason(engine,now))
        out=dict(config=config,trade_timeframe=engine.config.timeframe,view_only=True,source='MT5',
            account=copy.deepcopy(engine.account),account_age=now-engine.account_time,
            market_scope=engine.market_scope(),market_history_generation=engine.broker_clock_identity,
            instrument=copy.deepcopy(engine.info),server_time=now,chart_market=None,
            bars=[],live_bar=None,live_structure=[],forecast={},decision=Decision().json(),
            analysis_time=0.,market_time=0.,context_time=0,quote=None,market_errors=[],entry_allowed=False,
            entry_gate=dict(allowed=False,blocks=['VIEW_ONLY'],reason='Только наблюдение'),
            archive_scope='SELECTED_TRADE_FRAME_ONLY')
        out.update(copy.deepcopy(record))
        if isinstance(out.get('forecast'),dict):
            out['forecast']['show_price_forecast']=False
        if tf==engine.config.timeframe:
            out.update(bars=[asdict(b) for b in engine.bars[-1200:]],
                live_bar=asdict(engine.live_bar) if engine.live_bar else None,
                live_structure=list(live_structure(engine.bars,engine.live_bar)))
        if self._wrong_identity(engine):
            out.update(bars=[],live_bar=None,live_structure=[],forecast={},quote=None,analysis_time=0.)
        out.update(available=available,reason=reason)
        if not available:
            out['forecast'].update(available=False,stale=True,reason=reason)
            out['decision']=Decision(phase='DATA_BLOCK',reason=reason).json()
        out['quote_fresh']=bool(available and out['quote'] and -2<=now-out['quote']['time_msc']/1000<=10)
        return out

    def overview(self,engine,now):
        # Summary reads only metadata: copying all nine charts on every /state
        # poll would make the observer cost proportional to 10,800 candles.
        self.sync(engine)
        blocked=self.blocked_reason(engine,now);wrong_identity=self._wrong_identity(engine)
        rows=[]
        for tf in PUBLIC_TIMEFRAMES:
            record=self._record(engine,tf);forecast={} if wrong_identity else record.get('forecast',{})
            available,reason=self._status(record,tf,now,blocked)
            primary=next((s for s in forecast.get('scenarios',[]) if s.get('scenario_id')==forecast.get('primary_scenario_id')),None)
            lead=primary or next(iter(forecast.get('scenarios',[])),{})
            rows.append(dict(timeframe=tf,available=available,side=int(forecast.get('side',0) or 0),
                stage=lead.get('stage',record.get('decision',{}).get('phase','DATA_BLOCK')),
                title=lead.get('title',forecast.get('regime','Нет прогноза')),
                next_event=lead.get('next_event') or forecast.get('reason') or reason,
                data_asof=forecast.get('data_asof',0),analysis_time=0. if wrong_identity else record.get('analysis_time',0.),reason=reason))
        reference=next((x for x in rows if x['timeframe']==engine.config.timeframe),{})
        for row in rows:
            side=row['side'];other=reference.get('side',0)
            if not row['available']:alignment='UNAVAILABLE';detail='нет свежего независимого прогноза'
            elif row['timeframe']==engine.config.timeframe:alignment='REFERENCE';detail='рабочий таймфрейм входа'
            elif not reference.get('available') or not other or not side:alignment='NEUTRAL';detail='направление одной из гипотез не определено'
            elif side==other:alignment='SUPPORTS';detail='направление совпадает с '+engine.config.timeframe
            else:alignment='OPPOSES';detail='направление противоположно '+engine.config.timeframe
            row.update(alignment=alignment,alignment_reason=row['timeframe']+': '+detail)
        supports=[x['timeframe'] for x in rows if x['alignment']=='SUPPORTS']
        opposes=[x['timeframe'] for x in rows if x['alignment']=='OPPOSES']
        context=dict(reference_timeframe=engine.config.timeframe,affects_execution=False,
            supports=supports,opposes=opposes,summary='Совпадают: '+(', '.join(supports) or 'нет')+
            '; против: '+(', '.join(opposes) or 'нет')+'. Независимые наблюдения; условия входа не меняются.')
        return rows,context
