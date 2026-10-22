import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('check_run',Path(__file__).resolve().parents[1]/'tools/security/check_run.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Diagnostics(unittest.TestCase):
 def test_completed_legacy_run(self):
  self.assertTrue(m.batch_completed({'pending_services':[],'kernel_status':'1','microcode_status':'1','reboot_required':False}))
 def test_incomplete_not_claimed_verified(self):
  self.assertIsNone(m.batch_completed({'state':'completed'}))
 def test_explicit_marker_takes_priority(self):
  self.assertTrue(m.batch_completed({'batch_check_completed':True}))
  self.assertFalse(m.batch_completed({'batch_check_completed':False,'pending_services':[],'kernel_status':'1','microcode_status':'1','reboot_required':False}))
if __name__=='__main__':unittest.main()
