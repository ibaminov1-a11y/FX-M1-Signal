"""Keep fixed live status slots from regressing to wrap-content heights."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

class LiveLayoutResourceTests(unittest.TestCase):
    def test_dynamic_statuses_reserve_fixed_line_budgets(self):
        root=Path(__file__).resolve().parents[2]
        tree=ET.parse(root/'app/src/main/res/layout/activity_main.xml')
        a='{http://schemas.android.com/apk/res/android}'
        dynamic={'levelsText','contextText','whyWaitText','componentScoresText'}
        fixed={'statusText','marketStatusText','marketSessionText','confidenceText','signalAgeText',
            'autoStatusText','accountText','positionsText','priceCompareText','smartStatusText','statsText',
            'signalHistoryText','tradeHistoryText','serverStatusText','journalText'}
        found={el.get(a+'id','').split('/')[-1]:el for el in tree.iter()}
        for name in sorted(fixed):
            with self.subTest(field=name):
                el=found[name];self.assertEqual(el.tag,'com.openai.fxm1.StableLiveTextView')
                self.assertGreater(int(el.get(a+'lines','0')),0);self.assertEqual(el.get(a+'ellipsize'),'end')
        for name in sorted(dynamic):
            with self.subTest(dynamic_field=name):
                el=found[name];self.assertEqual(el.tag,'com.openai.fxm1.StableLiveTextView')
                self.assertIsNone(el.get(a+'lines'));self.assertGreater(int(el.get(a+'maxLines','0')),0)
                self.assertEqual(el.get(a+'ellipsize'),'end')
