import importlib.util,sys,tempfile,unittest,json,subprocess,os
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.app_manager import security_updates as s
class Security(unittest.TestCase):
 def test_origins(self):
  self.assertEqual(s.origins({'ID':'debian','VERSION_CODENAME':'trixie'}),['origin=Debian,codename=trixie-security,label=Debian-Security'])
  self.assertEqual(s.origins({'ID':'linuxmint','VERSION_CODENAME':'wilma','UBUNTU_CODENAME':'noble'}),['origin=Ubuntu,archive=noble-security'])
  for d in [{'ID':'fedora','VERSION_CODENAME':'foo'},{'ID':'debian','VERSION_CODENAME':'bad";'}]:
   with self.assertRaises(ValueError):s.origins(d)
 def test_policy_effective(self):
  dump=subprocess.check_output(['/usr/bin/apt-config','dump'],text=True)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'apt.conf';p.write_text(s.apt_config(dump+'\nUnattended-Upgrade::Origins-Pattern {"origin=Unsafe";};\nUnattended-Upgrade::Automatic-Reboot "true";',s.origins({'ID':'debian','VERSION_CODENAME':'trixie'})))
   result=subprocess.check_output(['/usr/bin/apt-config','dump'],env=dict(os.environ,APT_CONFIG=str(p)),text=True)
  self.assertNotIn('origin=Unsafe',result);self.assertIn('codename=trixie-security',result);self.assertIn('Automatic-Reboot "false"',result)
 def test_restart_status(self):
  result=s.restart_status('NEEDRESTART-SVC: nginx.service\nNEEDRESTART-KSTA: 3\nNEEDRESTART-SVC: nginx.service\n')
  self.assertEqual(result['pending_services'],['nginx.service']);self.assertTrue(result['reboot_required'])
 def test_disable_does_not_stop_running_job(self):
  with patch.object(s.cfg,'atomic') as save,patch.object(s.subprocess,'run') as run:
   s.configure(False)
  self.assertEqual(run.call_args.args[0],['systemctl','disable','--now','server-manager-security-updates.timer'])
  self.assertEqual(save.call_args.args[1],{'enabled':False})
 def test_enable_refuses_missing_dependencies(self):
  with patch.object(s,'prerequisites',return_value=['needrestart']),patch.object(s.subprocess,'run') as run:
   with self.assertRaises(ValueError):s.configure(True)
  run.assert_not_called()
 def test_tick_disabled_no_job(self):
  with patch.object(s,'settings',return_value={'enabled':False}),patch.object(s,'busy') as busy:s.tick()
  busy.assert_not_called()
 def test_execution_order_and_no_reboot(self):
  calls=[]
  def run(args,**kw):
   calls.append(args)
   return subprocess.CompletedProcess(args,0,stdout='NEEDRESTART-KSTA: 3\n' if '-b' in args else '',stderr='')
  with tempfile.TemporaryDirectory() as tmp,patch.object(s.cfg,'atomic'),patch.object(s,'installed_versions',return_value={}),patch('modules.app_manager.security_notify.send',return_value='nothing-due'),patch.object(s,'prerequisites',return_value=[]),patch.object(s,'busy',return_value=''),patch.object(s,'origins',return_value=['origin=Debian,codename=trixie-security,label=Debian-Security']),patch.object(s.shutil,'which',side_effect=lambda x:'/usr/sbin/'+x),patch.object(s.subprocess,'run',side_effect=run),patch.object(s,'pending_security',return_value=['held-package']):
   with open(Path(tmp)/'log','w') as log:result=s.execute(log,'a'*32)
  self.assertEqual([x[0].split('/')[-1] for x in calls],['apt-get','apt-config','unattended-upgrade','needrestart','needrestart'])
  self.assertEqual(calls[-2][1:],['-r','a']);self.assertEqual(calls[-1][1:],['-b','-r','l'])
  self.assertTrue(result['batch_check_completed']);self.assertTrue(result['service_restart_check_completed']);self.assertEqual(result['state'],'attention');self.assertEqual(result['pending_security_packages'],['held-package'])
 def test_failed_update_never_restarts(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(s.cfg,'atomic'),patch.object(s,'installed_versions',return_value={}),patch('modules.app_manager.security_notify.send',return_value='nothing-due'),patch.object(s,'prerequisites',return_value=[]),patch.object(s,'busy',return_value=''),patch.object(s.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['apt-get'])) as run:
   with open(Path(tmp)/'log','w') as log:
    with self.assertRaises(subprocess.CalledProcessError):s.execute(log,'a'*32)
  self.assertEqual(run.call_count,1)
if __name__=='__main__':unittest.main()
