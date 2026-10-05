"""Display catalog contracts on real numeric candles; no injected detections."""
import copy
from dataclasses import replace
import importlib.util
import json
import unittest
from event_core.model import Bar, bar_close_time
from pattern_fixtures_r732 import VARIANTS, FRAMES, INSTRUMENTS, fixture, live_after

class CatalogTests(unittest.TestCase):
    def catalog(self):
        self.assertIsNotNone(importlib.util.find_spec('event_core.scenarios.pattern_view'),
                             'DISPLAY_CATALOG_MISSING: numeric geometry has no read-only chart catalog')
        from event_core.scenarios.pattern_view import PatternCatalog
        return PatternCatalog()

    def update(self,catalog,bars,live=None,now=None,tf='M5',symbol='EURUSD',scope='demo-1',scenarios=()):
        default,t=live_after(bars,tf)
        return catalog.update(bars,default if live is None else live,symbol=symbol,timeframe=tf,
            mode='NORMAL',scope=scope,clock_generation='UTC_TEST',now=t if now is None else now,scenarios=scenarios)

    def check_view(self,out,bars,live,now,tf='M5'):
        self.assertEqual(out['version'],1);self.assertLessEqual(len(out['patterns']),32)
        source={b.time:b for b in bars+[live]};ids=set()
        for p in out['patterns']:
            self.assertNotIn(p['view_id'],ids);ids.add(p['view_id'])
            self.assertLessEqual(p['first_seen_at'],now);self.assertLessEqual(p['updated_at'],now)
            self.assertLessEqual(p['start_at'],p['end_at']);self.assertLessEqual(p['end_at'],now)
            for a in p['anchors']:
                self.assertIn(a['time'],source);b=source[a['time']]
                self.assertGreaterEqual(a['price'],b.low-1e-9);self.assertLessEqual(a['price'],b.high+1e-9)
                self.assertLessEqual(a['observed_at'],now)
                if not a['provisional']:
                    self.assertIsNotNone(a['confirmed_at']);self.assertLessEqual(a['confirmed_at'],now)
                    if a['role'] not in ('POLE_START','POLE_END'):
                        times=[x.time for x in bars];i=times.index(a['time'])
                        self.assertGreaterEqual(len(bars),i+3)
                        self.assertGreaterEqual(a['confirmed_at'],bar_close_time(bars[i+2].time,tf,bars[i+2].clock_offset_seconds))
                else:self.assertIsNone(a['confirmed_at'])
            for segment in p['segments']:
                self.assertLessEqual(segment['from_time'],segment['to_time'])
                self.assertLessEqual(segment['to_time'],now)
            if p['geometry_state']=='FORMING':
                self.assertIsNone(p['confirmed_at']);self.assertEqual(p['scenario_ids'],[])
                self.assertIsNone(p['execution_pattern_id']);self.assertTrue(any(a['provisional'] for a in p['anchors']))

    def positive_geometry(self,pair):
        b=fixture(*pair);live,now=live_after(b);out=self.update(self.catalog(),b)
        self.assertTrue(out['available'],out)
        found=[p for p in out['patterns'] if (p['family'],p['variant'])==pair and p['geometry_state']=='DETECTED']
        self.assertTrue(found,pair);p=found[0];self.assertTrue(p['title'])
        self.assertTrue(p['anchors']);self.assertTrue(p['segments']);self.check_view(out,b,live,now)
        roles={a['role'] for a in p['anchors']};lines={s['role'] for s in p['segments']}
        if pair[0]=='HEAD_SHOULDERS':
            self.assertTrue({'LEFT_SHOULDER','HEAD','RIGHT_SHOULDER','NECK'}<=roles)
            self.assertIn('NECKLINE',lines)
        elif pair[0]=='MULTI_EXTREME':
            kind='TOP' if pair[1].endswith('TOP') else 'BOTTOM';n=3 if pair[1].startswith('TRIPLE') else 2
            self.assertTrue({kind+str(i) for i in range(1,n+1)}<=roles);self.assertIn('NECKLINE',lines)
        elif pair[0] in ('FLAG','PENNANT'):
            self.assertTrue({'POLE_START','POLE_END'}<=roles);self.assertIn('POLE',lines)
            self.assertLess(p['start_at'],min(a['time'] for a in p['anchors'] if a['role'].startswith('TOUCH')))
        else:self.assertTrue({'UPPER','LOWER'}<=lines)

    def near_miss_rejected(self,pair):
        out=self.update(self.catalog(),fixture(*pair,negative=True))
        self.assertNotIn(pair,{(p['family'],p['variant']) for p in out['patterns'] if p['geometry_state'] in ('FORMING','DETECTED')})

    def prefix_visibility(self,pair):
        b=fixture(*pair);catalog=self.catalog();previous=[];found=False
        for n in range(24,len(b)+1):
            live,now=(b[n],bar_close_time(b[n].time,'M5')-.001) if n<len(b) else live_after(b)
            out=self.update(catalog,b[:n],live,now);self.check_view(out,b[:n],live,now)
            found|=any((p['family'],p['variant'])==pair and p['geometry_state']=='DETECTED' for p in out['patterns'])
            frozen=json.dumps(out,sort_keys=True);previous.append((out,frozen))
        self.assertTrue(found,pair)
        for out,frozen in previous:self.assertEqual(json.dumps(out,sort_keys=True),frozen,'Previously published view repainted')

    def test_prices_frames_and_identity(self):
        for pair in VARIANTS:
            for tf in FRAMES:
                for symbol in INSTRUMENTS:
                    with self.subTest(pair=pair,tf=tf,symbol=symbol):
                        b=fixture(*pair,tf=tf,symbol=symbol);live,now=live_after(b,tf)
                        out=self.update(self.catalog(),b,live,now,tf,symbol)
                        self.assertTrue(out['available'],out.get('reason'))
                        self.assertIn(pair,{(p['family'],p['variant']) for p in out['patterns'] if p['geometry_state']=='DETECTED'})
                        self.check_view(out,b,live,now,tf)

    def test_forming_anchor_and_confirmation_keep_identity(self):
        b=fixture('HEAD_SHOULDERS','TOP');c=self.catalog();seen={};promoted=[]
        for n in range(24,len(b)+1):
            live,now=(b[n],bar_close_time(b[n].time,'M5')-.01) if n<len(b) else live_after(b)
            out=self.update(c,b[:n],live,now)
            for p in out['patterns']:
                if p['family']!='HEAD_SHOULDERS':continue
                if p['geometry_state']=='FORMING':
                    seen[p['view_id']]=copy.deepcopy(p);self.assertEqual(p['scenario_ids'],[])
                    self.assertTrue(p['anchors'][-1]['provisional']);self.assertIsNone(p['confirmed_at'])
                elif p['geometry_state']=='DETECTED' and p['view_id'] in seen:promoted.append(p)
        self.assertTrue(seen,'No observed forming right shoulder')
        self.assertTrue(promoted,'Confirmation replaced the forming identity')
        self.assertEqual(promoted[0]['first_seen_at'],seen[promoted[0]['view_id']]['first_seen_at'])

    def test_moving_candidate_keeps_identity(self):
        b=fixture('TRIANGLE','SYMMETRIC');found=False
        for n in range(24,len(b)):
            c=self.catalog();live=b[n];now=bar_close_time(live.time,'M5')-.1
            out=self.update(c,b[:n],live,now)
            candidates=[p for p in out['patterns'] if p['geometry_state']=='FORMING' and p['anchors'][-1]['time']==live.time]
            if not candidates:continue
            p=candidates[0];kind=p['anchors'][-1]['kind']
            moved=replace(live,high=live.high+1e-8) if kind=='H' else replace(live,low=live.low-1e-8)
            after=self.update(c,b[:n],moved,now+.01)
            q=next((q for q in after['patterns'] if q['view_id']==p['view_id']),None)
            self.assertIsNotNone(q);self.assertEqual(q['geometry_state'],'FORMING');found=True;break
        self.assertTrue(found,'No forming current-bar candidate exercised')

    def test_outside_bar_does_not_invent_intrabar_order(self):
        b=fixture('HEAD_SHOULDERS','TOP');n=46;closed=b[:n]
        outside=replace(b[n],high=max(x.high for x in closed[-6:])+.001,low=min(x.low for x in closed[-6:])-.001)
        out=self.update(self.catalog(),closed,outside,bar_close_time(outside.time,'M5')-.1)
        self.assertFalse(any(p['geometry_state']=='FORMING' and any(a['provisional'] and a['time']==outside.time for a in p['anchors']) for p in out['patterns']))

    def test_corrections_and_scopes_do_not_mutate_old_snapshots(self):
        c=self.catalog();b=fixture('RANGE','HORIZONTAL');first=self.update(c,b);saved=copy.deepcopy(first)
        changed=list(b);changed[-2]=replace(changed[-2],high=changed[-2].high+.000001)
        second=self.update(c,changed);self.assertNotEqual(first['source_revision'],second['source_revision'])
        other=self.update(c,b,scope='other-account');self.assertEqual(first,saved)
        self.assertFalse({p['view_id'] for p in first['patterns']}&{p['view_id'] for p in other['patterns']})

    def test_monthly_freshness_is_eight_calendar_bars_not_240_days(self):
        from event_core.scenarios.structure import detect_patterns
        b=fixture('HEAD_SHOULDERS','TOP',tf='MN1')
        self.assertIn(('HEAD_SHOULDERS','TOP'),{(p['family'],p['variant']) for p in detect_patterns(b,'EURUSD','MN1')})
        live,now=live_after(b,'MN1');last=replace(live,open=b[-1].close,high=b[-1].high,low=b[-1].low,close=b[-1].close)
        self.assertNotIn(('HEAD_SHOULDERS','TOP'),{(p['family'],p['variant']) for p in detect_patterns(b+[last],'EURUSD','MN1')})

    def test_future_closed_history_is_unavailable(self):
        b=fixture('RANGE','HORIZONTAL');live,now=live_after(b)
        out=self.update(self.catalog(),b+[live],replace(live,time=live.time+300),now)
        self.assertFalse(out['available']);self.assertEqual(out['patterns'],[])

    def test_catalog_is_bounded_and_inputs_are_read_only(self):
        c=self.catalog();b=fixture('RANGE','HORIZONTAL');original=copy.deepcopy(b)
        scenarios=[{'scenario_id':'unrelated','pattern':{'pattern_id':'not-here'},'status':'WATCHING'}];saved=copy.deepcopy(scenarios)
        for n in range(30):
            shifted=[replace(x,time=x.time+300*n) for x in b];out=self.update(c,shifted,scenarios=scenarios)
            self.assertLessEqual(len(out['patterns']),32)
        self.assertEqual(b,original);self.assertEqual(scenarios,saved)

# Individual test names preserve variant-level reporting in CI (not a single count for a family).
for _pair in VARIANTS:
    for _name in ('positive_geometry','near_miss_rejected','prefix_visibility'):
        def _test(self,pair=_pair,method=_name):getattr(self,method)(pair)
        setattr(CatalogTests,'test_'+_name+'_'+'_'.join(_pair).lower(),_test)

if __name__=='__main__':unittest.main()
