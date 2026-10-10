import unittest,json,io
from unittest.mock import patch
from types import SimpleNamespace
from flask import Flask
from modules.nextcloud_wake import engine as e,plugin as ui
class WakeTests(unittest.TestCase):
 def setUp(self):
  self.c=dict(domain='cloud.example.test',backend='http://192.168.1.22:8080',manager_url='https://manager.example.test',recovery_url='http://127.0.0.1:8182/recover',port=8183,wake_wait=60,hold_seconds=600,wake_cooldown=120,token='x'*32,ca_pem='')
  self.app=Flask(__name__);self.app.secret_key='test';ui.register(self.app,SimpleNamespace(page=lambda t,b,s:b));self.client=self.app.test_client();self.client.set_cookie('server_manager_language','de')
  for obj,name,result in [(e,'info',dict(installed=False,active='inactive',revision='rev')),(e,'load',{})]:
   p=patch.object(obj,name,return_value=result);p.start();self.addCleanup(p.stop)
 def test_validation(self):self.assertEqual(8183,e.validate(self.c)['port'])
 def test_invalid_values(self):
  for key,value in [('domain','x..test'),('domain','-bad.test'),('manager_url','http://manager.test'),('recovery_url','http://localhost/reset'),('token',''),('port',80),('backend','http://127.0.0.1:8183')]:
   with self.subTest(key=key),self.assertRaises(ValueError):e.validate(dict(self.c,**{key:value}))
 def test_get_does_not_install(self):
  with patch('modules.app_manager.install_jobs.start') as start:
   r=self.client.get('/apps/nextcloud/wake');self.assertEqual(200,r.status_code);self.assertIn(b'Gateway bereitstellen',r.data);self.assertIn(b'ffentlichen Zugang separat',r.data);start.assert_not_called()
 def test_csrf_and_confirmation(self):
  with patch('modules.app_manager.install_jobs.start') as start:
   self.assertEqual(403,self.client.post('/apps/nextcloud/wake',data={'confirm':'yes'}).status_code)
   self.client.get('/apps/nextcloud/wake')
   with self.client.session_transaction() as session:csrf=session['app_install_csrf']
   self.client.post('/apps/nextcloud/wake',data={'csrf':csrf});start.assert_not_called()
 def test_profile_disabled_network(self):
  self.client.get('/apps/nextcloud/wake')
  with self.client.session_transaction() as session:csrf=session['app_install_csrf']
  with patch('modules.module_selection.config.network_enabled',return_value=False):self.assertEqual(400,self.client.post('/apps/nextcloud/wake/profile',data={'csrf':csrf}).status_code)
 def test_credentials_separate_from_status(self):
  self.client.get('/apps/nextcloud/wake')
  with self.client.session_transaction() as session:csrf=session['app_install_csrf']
  data=dict(self.c,csrf=csrf,confirm='yes',revision='rev');data.pop('token');data.pop('ca_pem')
  data['profile']=(io.BytesIO(json.dumps(dict(format='nextcloud-wake-blocker',manager_url=self.c['manager_url'],token=self.c['token'])).encode()),'profile.json')
  with patch('modules.app_manager.install_jobs.start',return_value='job') as start:
   r=self.client.post('/apps/nextcloud/wake',data=data);self.assertEqual(303,r.status_code)
   kw=start.call_args.kwargs;self.assertNotIn('token',kw['plan']['config']);self.assertEqual(self.c['token'],kw['credentials']['token'])
if __name__=='__main__':unittest.main()

class InstallTests(unittest.TestCase):
 def setUp(self):
  import tempfile
  from pathlib import Path
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  for name,rel in [('CONF','etc/config.json'),('UNIT','unit.service'),('PROGRAM','program.py'),('STATE','state')]:
   p=patch.object(e,name,self.root/rel);p.start();self.addCleanup(p.stop)
  self.conf=dict(domain='cloud.example.test',backend='http://192.168.1.22:8080',manager_url='https://manager.example.test',recovery_url='http://127.0.0.1:8182/recover',port=18183,wake_wait=60,hold_seconds=600,wake_cooldown=120,token='x'*32,ca_pem='')
  self.run=patch.object(e.subprocess,'run',return_value=SimpleNamespace(stdout='inactive',returncode=0));self.mockrun=self.run.start();self.addCleanup(self.run.stop)
  self.sleep=patch.object(e.time,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
 def test_new_install_private_credentials(self):
  e.execute(dict(config=self.conf,revision=e.revision()),{})
  self.assertEqual(0o600,e.CONF.stat().st_mode&0o777);self.assertIn('DynamicUser=yes',e.UNIT.read_text());self.assertTrue(e.PROGRAM.exists())
  self.assertNotIn(self.conf['token'],e.UNIT.read_text())
 def test_stale_revision_refused(self):
  with self.assertRaises(ValueError):e.execute(dict(config=self.conf,revision='stale'),{})
  self.assertFalse(e.CONF.exists())
 def test_failed_service_rolls_back(self):
  import subprocess
  def run(cmd,**kw):
   if cmd[:2]==['systemctl','restart']:raise subprocess.CalledProcessError(1,cmd)
   return SimpleNamespace(stdout='inactive',returncode=0)
  self.mockrun.side_effect=run
  with self.assertRaises(ValueError):e.execute(dict(config=self.conf,revision=e.revision()),{})
  self.assertFalse(e.CONF.exists());self.assertFalse(e.UNIT.exists());self.assertFalse(e.PROGRAM.exists())

class DraftTests(InstallTests):
 def test_draft_does_not_install(self):
  draft=dict(self.conf,health_path='/nextcloud/status.php');draft.pop('token')
  checked=e.save_draft(draft,e.revision())
  self.assertEqual('/nextcloud/status.php',checked['health_path'])
  self.assertNotIn('token',e.load_draft());self.assertFalse(e.CONF.exists());self.assertFalse(e.UNIT.exists())
  self.mockrun.assert_not_called()
  self.assertEqual(0o600,(e.STATE/'draft.json').stat().st_mode&0o777)
 def test_draft_revision(self):
  before=e.revision();e.save_draft(self.conf,before)
  with self.assertRaises(ValueError):e.save_draft(self.conf,before)
 def test_invalid_status_paths(self):
  for path in ['//example.test/status.php','/../status.php','/nextcloud/status.php?x=1','/remote.php/dav','/status.php\n']:
   with self.subTest(path=path),self.assertRaises(ValueError):e.validate(dict(self.conf,health_path=path))

class DraftUiTests(WakeTests):
 def test_save_without_credentials_or_confirmation(self):
  self.client.get('/apps/nextcloud/wake')
  with self.client.session_transaction() as session:csrf=session['app_install_csrf']
  with patch.object(e,'save_draft') as save,patch('modules.app_manager.install_jobs.start') as start:
   response=self.client.post('/apps/nextcloud/wake',data=dict(self.c,csrf=csrf,revision='rev',action='save_draft',health_path='/nextcloud/status.php'))
   self.assertEqual(303,response.status_code);start.assert_not_called();save.assert_called_once()
   self.assertNotIn('token',save.call_args.args[0])
