import io,json,sys,threading,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import backup,core,incremental

class Reauthentication(unittest.TestCase):
 def setUp(self):
  self.saved=(backup.ACCOUNT,backup.CURRENT_BACKUP,backup.REAUTH_HANDLER)
  self.access=dict(username='alice',backup=True,csrf='old')
  backup.ACCOUNT=('https://server.example',None,self.access)
  backup.CURRENT_BACKUP=backup.BackupJob();backup.CURRENT_BACKUP.lease_checked=True
  self.cfg=patch.object(core,'load',return_value=dict(core.DEFAULTS,SERVER_URL='https://server.example',TOKEN='test-token',CLIENT_NAME='test-client'))
  self.cfg.start()
 def tearDown(self):
  self.cfg.stop();backup.ACCOUNT,backup.CURRENT_BACKUP,backup.REAUTH_HANDLER=self.saved
 def login(self,user,password):
  backup.ACCOUNT=('https://server.example',None,dict(self.access,csrf='new'))
 def test_same_block_and_upload_retried_after_login(self):
  calls=[];expired=False
  def request(action,data=None,query='',binary=False):
   nonlocal expired
   calls.append((action,data,query,backup.ACCOUNT[2]['csrf']))
   if action=='block-has':return dict(present=False)
   if action=='block-put' and not expired:
    expired=True;raise backup.AuthenticationExpired('expired')
   return dict(ok=True)
  backup.REAUTH_HANDLER=lambda *args:('alice','secret')
  stream=incremental.Stream('a'*32,lambda _:None,check=backup.check_cancel)
  with patch.object(backup,'_call_once',side_effect=request),patch.object(backup,'account_login',side_effect=self.login):
   stream.write(b'payload');stream.finish()
  puts=[x for x in calls if x[0]=='block-put']
  self.assertEqual(2,len(puts));self.assertEqual(puts[0][:3],puts[1][:3]);self.assertEqual(['old','new'],[x[3] for x in puts])
  self.assertEqual(7,stream.sent);self.assertEqual(1,len(stream.refs));self.assertEqual('cas-finish',calls[-1][0])
 def test_wrong_password_can_retry_without_losing_job(self):
  prompts=[]
  backup.REAUTH_HANDLER=lambda user,message,job:(prompts.append(message) or ('alice','secret'))
  with patch.object(backup,'_call_once',side_effect=[backup.AuthenticationExpired('expired'),{'ok':True}]),patch.object(backup,'account_login',side_effect=[core.Error('wrong password'),None]):
   self.assertTrue(backup.call('block-put',b'x','&id=abc')['ok'])
  self.assertEqual(2,len(prompts));self.assertEqual('wrong password',prompts[1])
 def test_different_account_never_retries(self):
  backup.REAUTH_HANDLER=lambda *args:('bob','secret')
  def login(*args):backup.ACCOUNT=('https://server.example',None,dict(self.access,username='bob'))
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')) as request,patch.object(backup,'account_login',side_effect=login):
   with self.assertRaises(core.Error):backup.call('block-put',b'x')
  self.assertEqual(1,request.call_count)
 def test_cancelled_prompt_keeps_remote_data(self):
  backup.REAUTH_HANDLER=lambda *args:None
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')) as request:
   with self.assertRaises(core.Error):backup.call('block-put',b'x')
  self.assertEqual(1,request.call_count);self.assertFalse(backup.CURRENT_BACKUP.event.is_set())
 def test_explicit_job_cancel_interrupts_pause(self):
  def prompt(*args):backup.CURRENT_BACKUP.event.set();return ('alice','secret')
  backup.REAUTH_HANDLER=prompt
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')),patch.object(backup,'account_login') as login:
   with self.assertRaises(backup.Cancelled):backup.call('block-put',b'x')
  login.assert_not_called()
 def test_permission_denied_is_not_reauthentication(self):
  with patch.object(backup,'_call_once',side_effect=core.Error('permission_denied')),patch.object(backup,'REAUTH_HANDLER') as prompt:
   with self.assertRaises(core.Error):backup.call('block-put',b'x')
  prompt.assert_not_called()
 def test_non_backup_thread_does_not_prompt(self):
  backup.CURRENT_BACKUP.thread=-1
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')),patch.object(backup,'REAUTH_HANDLER') as prompt:
   with self.assertRaises(backup.AuthenticationExpired):backup.call('list')
  prompt.assert_not_called()
 def test_second_401_does_not_loop(self):
  backup.REAUTH_HANDLER=lambda *args:('alice','secret')
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')) as request,patch.object(backup,'account_login',side_effect=self.login):
   with self.assertRaises(backup.AuthenticationExpired):backup.call('block-put',b'x')
  self.assertEqual(2,request.call_count)
 def test_http_401_uses_fresh_cookie_transport_and_csrf(self):
  requests=[]
  class Old:
   def open(self,req,**kwargs):
    requests.append(req)
    raise urllib.error.HTTPError(req.full_url,401,'Unauthorized',{},io.BytesIO(b'{}'))
  class New:
   def open(self,req,**kwargs):requests.append(req);return io.BytesIO(b'{"ok":true}')
  backup.ACCOUNT=('https://server.example',Old(),self.access)
  backup.REAUTH_HANDLER=lambda *args:('alice','secret')
  def login(*args):backup.ACCOUNT=('https://server.example',New(),dict(self.access,csrf='new'))
  with patch('device_identity.headers',return_value={}),patch.object(backup,'account_login',side_effect=login):
   self.assertTrue(backup.call('block-put',b'payload','&id=same')['ok'])
  self.assertEqual(2,len(requests));self.assertEqual(requests[0].full_url,requests[1].full_url)
  self.assertEqual(requests[0].data,requests[1].data)
  self.assertEqual('new',requests[1].get_header('X-server-manager-csrf'))
 def test_changed_server_stops_before_login(self):
  backup.REAUTH_HANDLER=lambda *args:('alice','secret')
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')),patch.object(core,'load',return_value=dict(core.DEFAULTS,SERVER_URL='https://other.example',TOKEN='test',CLIENT_NAME='test')),patch.object(backup,'account_login') as login:
   with self.assertRaises(core.Error):backup.call('block-put',b'x')
  login.assert_not_called()

 def test_declined_prompt_is_not_reopened_by_archive_cleanup(self):
  with patch.object(backup,'_call_once',side_effect=backup.AuthenticationExpired('expired')),patch.object(backup,'REAUTH_HANDLER',return_value=None) as prompt:
   for _ in range(2):
    with self.assertRaises(core.Error):backup.call('block-put',b'x')
  self.assertEqual(1,prompt.call_count)
 def test_run_credential_is_opened_once_and_closed(self):
  backup.CURRENT_BACKUP=None;calls=[]
  def request(action,*args,**kwargs):
   calls.append(action)
   if action=='list':return dict(capabilities=['backup-session-v1'])
   if action=='session-begin':return dict(token='lease')
   return dict(ok=True)
  @backup.cancellable
  def run():
   backup.call('list');backup.call('list')
   self.assertEqual('lease',backup.CURRENT_BACKUP.lease)
  with patch.object(backup,'_call_once',side_effect=request):run()
  self.assertEqual(1,calls.count('session-begin'));self.assertEqual('session-end',calls[-1]);self.assertIsNone(backup.CURRENT_BACKUP)
