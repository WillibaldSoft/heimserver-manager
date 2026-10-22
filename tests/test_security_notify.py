import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.app_manager import security_notify as n
class Notify(unittest.TestCase):
 def test_dedup_privacy_and_retries(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(n,'RECORD',Path(tmp)/'sent.json'),patch.object(n.engine,'config',return_value={'enabled':True,'topic':'test','details':False}),patch.object(n.engine,'publish',side_effect=[False,True]) as publish:
   result={'state':'attention','pending_services':['private-service.service'],'reboot_required':True}
   self.assertEqual(n.send(result),'failed');self.assertEqual(n.send(result),'sent');self.assertEqual(n.send(result),'unchanged')
   self.assertNotIn('private-service',publish.call_args.args[2]);self.assertEqual(publish.call_count,2)
 def test_disabled_never_sends(self):
  with patch.object(n.engine,'config',return_value={'enabled':False,'topic':'test'}),patch.object(n.engine,'publish') as publish:
   self.assertEqual(n.send({'state':'failed'}),'disabled');publish.assert_not_called()
if __name__=='__main__':unittest.main()
