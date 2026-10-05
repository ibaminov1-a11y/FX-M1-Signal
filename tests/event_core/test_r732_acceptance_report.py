import importlib.util,json,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
class AcceptanceReportTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('r732_acceptance_report'),'ACCEPTANCE_VERIFIER_MISSING')
  import r732_acceptance_report
  return r732_acceptance_report
 def test_absent_evidence_cannot_be_pass(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   r=m.build_report(Path(d),'a'*40)
   self.assertFalse(r['release_allowed']);self.assertEqual(len(r['gates']),24)
   self.assertTrue(all(g['status']!='PASS' for g in r['gates'].values()))
 def test_invalid_native_xml_does_not_close_gate(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'androidTest-results').mkdir();(root/'androidTest-results/bad.xml').write_text('<not-junit>')
   r=m.build_report(root,'a'*40);self.assertFalse(r['release_allowed']);self.assertNotEqual(r['gates']['21']['status'],'PASS')
 def test_wrong_certificate_and_source_are_not_accepted(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'IDENTITY.json').write_text(json.dumps({'source_sha':'b'*40,'certificate_sha256':'new-key','version_code':933}))
   r=m.build_report(root,'a'*40);self.assertFalse(r['release_allowed']);self.assertNotEqual(r['gates']['24']['status'],'PASS')
 def test_skipped_or_failed_native_case_not_passed(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'androidTest-results').mkdir();(root/'androidTest-results/case.xml').write_text('<testsuite><testcase classname="com.openai.fxm1.R732ChartStateUiTest" name="serverForbidsAnalogueAfterRefresh"><skipped/></testcase></testsuite>')
   r=m.build_report(root,'a'*40);self.assertNotEqual(r['gates']['02']['status'],'PASS')
 def test_missing_png_has_no_visual_pass(self):
  m=self.module()
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'VISUAL_REVIEW.json').write_text(json.dumps({'source_sha':'a'*40,'reviewer':'self-review','files':{}}))
   r=m.build_report(root,'a'*40);self.assertNotEqual(r['gates']['22']['status'],'PASS')
if __name__=='__main__':unittest.main()
