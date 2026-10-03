from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class R71UiSourceContractTests(unittest.TestCase):
    def test_entry_plan_is_not_hardcoded_to_scalp_m1(self):
        src=(ROOT/'app/src/main/java/com/openai/fxm1/ScenarioUi.java').read_text(encoding='utf-8')
        self.assertNotIn('!"SCALP".equals(cfg.optString("mode"))||!"M1".equals(cfg.optString("timeframe"))', src)
        self.assertIn('ПЛАН ВХОДА · ', src)
        self.assertIn('Уровень подтверждения: ещё не сформирован', src)

    def test_empty_live_hypotheses_are_not_rendered_as_a_section(self):
        src=(ROOT/'app/src/main/java/com/openai/fxm1/ScenarioUi.java').read_text(encoding='utf-8')
        self.assertIn('boolean hasRows=rows!=null&&rows.length()>0', src)
        self.assertIn('if(valid&&hasRows)', src)

    def test_entry_plan_uses_compact_fixed_live_height(self):
        xml=(ROOT/'app/src/main/res/layout/activity_main.xml').read_text(encoding='utf-8')
        levels=next(x for x in xml.splitlines() if '@+id/levelsText' in x)
        self.assertIn('android:lines="5"', levels)
        self.assertNotIn('android:lines="8"', levels)
        self.assertIn('ПЛАН ВХОДА: ожидаем анализ', levels)

    def test_risk_budget_label_is_a_limit_not_a_planned_loss(self):
        src=(ROOT/'app/src/main/java/com/openai/fxm1/MainActivity.java').read_text(encoding='utf-8')
        self.assertNotIn('Плановый риск всей кампании:', src)
        self.assertIn('Лимит риска кампании при текущей настройке:', src)

if __name__=='__main__': unittest.main()
