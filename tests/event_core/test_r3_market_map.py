import unittest

import event_core.model as model
from event_core.model import Bar, Decision
from fakes import wave


class R3MarketMapTests(unittest.TestCase):
    def test_swing_labels_use_confirmed_pivots_only(self):
        bars = wave(1800000000, count=96, tf=300, trend=.00003)
        labels = model.swing_labels(bars)
        self.assertGreaterEqual(len(labels), 4)
        self.assertTrue(all(x['label'] in ('H','L','HH','HL','LH','LL') for x in labels))
        self.assertTrue(all(x['known_at'] <= bars[-1].time for x in labels))
        highs = [x for x in labels if x['kind'] == 'H']
        lows = [x for x in labels if x['kind'] == 'L']
        self.assertEqual(highs[-1]['label'], 'HH')
        self.assertEqual(lows[-1]['label'], 'HL')

    def test_live_structure_extends_to_forming_m5_without_rewriting_confirmed_map(self):
        bars = wave(1800000000, count=96, tf=300, trend=.00003)
        confirmed = model.swing_labels(bars)
        self.assertTrue(confirmed)
        anchor = confirmed[-1]
        t = bars[-1].time + 300
        if anchor['kind'] == 'L':
            reference = max(x['price'] for x in confirmed if x['kind'] == 'H')
            live = Bar(t, reference + .0002, reference + .0008, reference + .0001, reference + .0006, 3)
            expected_kind = 'H'
        else:
            reference = min(x['price'] for x in confirmed if x['kind'] == 'L')
            live = Bar(t, reference - .0002, reference - .0001, reference - .0008, reference - .0006, 3)
            expected_kind = 'L'
        overlay = model.live_structure(bars, live)
        self.assertGreaterEqual(len(overlay), 2)
        self.assertEqual(overlay[0]['time'], anchor['time'])
        self.assertEqual(overlay[0]['price'], anchor['price'])
        self.assertEqual(overlay[1]['kind'], expected_kind)
        self.assertTrue(overlay[1]['label'].endswith('?'))
        self.assertTrue(overlay[1]['provisional'])
        self.assertEqual(model.swing_labels(bars), confirmed)

    def test_context_direction_is_based_on_confirmed_structure(self):
        up = wave(1800000000, count=96, tf=900, trend=.00004)
        down = wave(1800000000, count=96, tf=900, trend=-.00004)
        self.assertEqual(model.context_direction(up), 1)
        self.assertEqual(model.context_direction(down), -1)

    def test_decision_exposes_path_and_structure_without_breaking_existing_fields(self):
        point = {'kind':'H','label':'HH','time':1,'price':1.2,'known_at':2}
        decision = Decision(signal='WAIT', reason='test', path='IMPULSE', structure=(point,))
        payload = decision.json()
        self.assertEqual(payload['signal'], 'WAIT')
        self.assertEqual(payload['reason'], 'test')
        self.assertEqual(payload['path'], 'IMPULSE')
        self.assertEqual(payload['structure'][0]['label'], 'HH')


if __name__ == '__main__':
    unittest.main()
