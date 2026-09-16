import unittest

import event_core.model as model
from event_core.model import Bar, Decision


NOW=1800000000
TF=300


def bars_from_closes(closes):
    rows=[]
    start=NOW-len(closes)*TF
    for i,c in enumerate(closes):
        o=c-0.00002
        rows.append(Bar(start+i*TF,o,c+0.00004,o-0.00004,c,10))
    return rows


class R3MarketMapTests(unittest.TestCase):
    def test_decision_exposes_path_and_structure_without_breaking_old_fields(self):
        d=Decision()
        self.assertTrue(hasattr(d,'path'),'R3 Decision needs explicit path')
        self.assertTrue(hasattr(d,'structure'),'R3 Decision needs chart structure')
        self.assertEqual(d.path,'SEARCH')
        self.assertEqual(d.structure,())
        self.assertEqual(d.signal,'WAIT')

    def test_swing_map_labels_confirmed_hh_hl_and_direction(self):
        self.assertTrue(hasattr(model,'swing_labels'),'R3 needs swing_labels()')
        self.assertTrue(hasattr(model,'context_direction'),'R3 needs context_direction()')
        bars=bars_from_closes([
            1.1000,1.1010,1.1040,1.1020,1.1005,
            1.1020,1.1055,1.1030,1.1015,
            1.1030,1.1070,1.1040,1.1025,
            1.1040,1.1060,1.1050,1.1055,
        ])
        labels=model.swing_labels(bars)
        kinds=[p['kind'] for p in labels]
        self.assertIn('HH',kinds)
        self.assertIn('HL',kinds)
        self.assertTrue(all(p['known_at']<=bars[-1].time for p in labels))
        self.assertEqual(model.context_direction(bars),1)

    def test_flat_alternating_context_can_remain_neutral(self):
        self.assertTrue(hasattr(model,'context_direction'),'R3 needs context_direction()')
        bars=bars_from_closes([
            1.1000,1.1010,1.1030,1.1010,1.0990,
            1.1010,1.1030,1.1010,1.0990,
            1.1010,1.1030,1.1010,1.0990,
            1.1010,1.1020,1.1010,1.1005,
        ])
        self.assertEqual(model.context_direction(bars),0)


if __name__=='__main__':
    unittest.main()
