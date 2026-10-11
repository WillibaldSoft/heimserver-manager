import json,tempfile,time,unittest,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask,session,g
from authentication import register
from modules.accounts import system,policy
from modules.accounts.store import Users

class SystemUsers(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.people=[dict(name='alice',uid=1001,label='Alice',home='/home/alice'),dict(name='bob',uid=1002,label='Bob',home='/home/bob')]
  for name,value in [('candidates',lambda:self.people),('identity',lambda name,secret:dict(next(u for u in self.people if u['name']==name),stamp='valid') if name in ('alice','bob') else None),('verify',lambda name,password:password=='linux-secret'),('ensure_policy',lambda:None),('ready',lambda:True)]:
   p=patch.object(system,name,side_effect=value);p.start();self.addCleanup(p.stop)
  self.app=Flask(__name__);self.app.testing=True;register(self.app,self.root)
  self.touched=[]
  def view():
   from flask import request
   self.touched.append(request.path);return 'ok'
  for path in ['/','/downloads','/downloads/file','/downloads/upload','/tv','/tv/epg/record/12','/tv/recordings/delete','/speicher','/speicher/smart-test','/apps','/apps/demo/backup','/api/apps/demo','/api/private','/clients/desktop/profile/5','/clients/install/5','/backup/desktop','/settings/https','/future/module']:
   self.app.add_url_rule(path,endpoint=path,view_func=view,methods=['GET','POST','DELETE'])
  self.client=self.app.test_client();self.client.set_cookie('server_manager_language','de');self.users=self.app.extensions['server_manager_users']
 def grant(self,name='alice',role='user',modules=('downloads','tv'),enabled=True):
  self.users.change(name,role,list(modules),enabled,self.users.read()['revision'],'ADMIN')
 def login(self,name='alice',password='linux-secret',client=None):
  client=client or self.client;client.get('/login')
  with client.session_transaction() as s:token=s['auth_csrf']
  return client.post('/login',data={'auth_csrf':token,'username':name,'password':password})
 def token(self):
  with self.client.session_transaction() as s:return s['auth_csrf']
 def test_only_explicitly_granted_accounts_can_sign_in(self):
  self.assertEqual(self.login().status_code,401);self.grant();self.assertEqual(self.login().status_code,303)
  self.assertEqual(self.client.get('/downloads').status_code,200)
  self.assertEqual(self.login(name='bob').status_code,401)
 def test_no_system_password_stored(self):
  self.grant();self.login();data=self.users.path.read_text()
  self.assertNotIn('linux-secret',data);self.assertNotIn('password',data);self.assertEqual(self.users.path.stat().st_mode&0o777,0o600)
 def test_user_actions_limited_to_assigned_modules(self):
  self.grant();self.login();headers={'X-Server-Manager-CSRF':self.token()}
  self.assertEqual(self.client.post('/downloads/upload',headers=headers).status_code,200)
  self.assertEqual(self.client.post('/tv/epg/record/12',headers=headers).status_code,200)
  for path in ['/apps/demo/backup','/tv/recordings/delete','/backup/desktop','/settings/https','/future/module']:
   self.assertEqual(self.client.post(path,headers=headers).status_code,403);self.assertNotIn(path,self.touched)
 def test_readonly_blocks_writes_even_with_valid_csrf(self):
  self.grant(role='viewer');self.login()
  self.assertEqual(self.client.get('/downloads/file').status_code,200)
  self.assertEqual(self.client.post('/downloads/upload',headers={'X-Server-Manager-CSRF':self.token()}).status_code,403)
  self.assertEqual(self.client.delete('/downloads/file',headers={'X-Server-Manager-CSRF':self.token()}).status_code,403)
 def test_legacy_get_mutations_and_other_clients_denied(self):
  self.grant(modules=tuple(policy.SCOPES));self.login()
  for path in ['/speicher/smart-test?dev=/dev/sda','/clients/desktop/profile/5','/clients/install/5','/api/apps/demo','/api/private','/settings/users','/future/module']:
   self.assertEqual(self.client.get(path).status_code,403,path)
 def test_revocation_and_role_change_end_current_sessions(self):
  self.grant(role='admin');self.login();self.assertEqual(self.client.get('/api/private').status_code,200)
  self.grant(role='viewer');self.assertEqual(self.client.get('/api/private').status_code,401)
  self.login();self.assertEqual(self.client.get('/api/private').status_code,403)
  self.grant(enabled=False);self.assertEqual(self.client.get('/api/private').status_code,401);self.assertEqual(self.login().status_code,401)
 def test_uid_change_or_locked_linux_account_revokes(self):
  self.grant();self.login()
  with patch.object(system,'identity',return_value=None):self.assertEqual(self.client.get('/api/private').status_code,401)
  with patch.object(system,'identity',return_value=dict(name='alice',uid=1009,stamp='valid')):self.assertEqual(self.client.get('/api/private').status_code,401)
 def test_linux_password_change_revokes_session(self):
  self.grant();self.login()
  with patch.object(system,'identity',return_value=dict(name='alice',uid=1001,stamp='new-password')):self.assertEqual(self.client.get('/api/private').status_code,401)
 def test_role_not_taken_from_cookie(self):
  self.grant(role='viewer');self.login()
  with self.client.session_transaction() as s:s['auth_role']='admin';s['role']='admin'
  self.assertEqual(self.client.get('/api/private').status_code,403)
 def test_admin_pam_has_full_rights_but_not_emergency_password_editor(self):
  self.grant(role='admin');self.login();self.assertEqual(self.client.get('/api/private').status_code,200)
  self.assertIn(b'Systemkonto',self.client.get('/settings/access').data)
  response=self.client.post('/settings/access',data={'auth_csrf':self.token(),'current_password':'linux-secret','username':'hijack','new_password':'strongpassword'})
  self.assertEqual(self.app.extensions['server_manager_auth'].read()['username'],'ADMIN')
 def test_admin_management_requires_reauthentication_and_csrf(self):
  self.login('ADMIN','ADMIN')
  data=dict(username='alice',role='user',modules=['downloads'],enabled='yes',revision='initial',current_password='ADMIN')
  self.assertEqual(self.client.post('/settings/users',data=data).status_code,403)
  data['auth_csrf']=self.token();data['current_password']='wrong'
  self.assertEqual(self.client.post('/settings/users',data=data).status_code,403)
  data['current_password']='ADMIN';self.assertEqual(self.client.post('/settings/users',data=data).status_code,200)
  self.assertTrue(self.users.read()['users']['alice']['enabled'])
  self.assertEqual(self.client.post('/settings/users',data=data).status_code,400)
 def test_deletion_keeps_linux_user_and_fallback(self):
  self.grant();self.login();self.users.change('alice','user',[],False,self.users.read()['revision'],'ADMIN',remove=True)
  self.assertEqual(len(self.people),2);self.assertEqual(self.client.get('/api/private').status_code,401)
  self.assertEqual(self.login('ADMIN','ADMIN').status_code,303)
 def test_damaged_users_file_does_not_break_emergency_login(self):
  self.users.path.write_text('{}');self.assertEqual(self.login('ADMIN','ADMIN').status_code,303)
  self.assertEqual(self.client.get('/api/private').status_code,200);self.assertEqual(self.login().status_code,401)
 def test_module_navigation_and_forms_filtered(self):
  p=dict(role='viewer',modules=['downloads'])
  with self.app.test_request_context('/downloads'):
   g.auth_principal=p
   body=policy.filter_html("<a href='/settings/users'>Users</a><a href='/downloads/file?path=test'>Read</a><form method='post' action='/downloads/upload'><button>Upload</button></form>")
   self.assertNotIn("href='/settings/users'",body);self.assertNotIn('Upload',body);self.assertIn('Read',body)
 def test_new_routes_default_to_admin_only(self):
  for role in ('user','viewer'):
   p=dict(role=role,modules=list(policy.SCOPES))
   for method in ('GET','HEAD','POST','DELETE','OPTIONS'):self.assertFalse(policy.allowed(p,'/future/new-module',method))
 def test_empty_scopes_have_no_access(self):
  self.grant(modules=[]);self.login();self.assertEqual(self.client.get('/downloads').status_code,403)
  self.assertEqual(self.client.get('/account').status_code,200)

class LocalIdentities(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  for attr in ('PASSWD','SHADOW','LOGIN_DEFS'):
   path=self.root/attr;path.write_text('');p=patch.object(system,attr,path);p.start();self.addCleanup(p.stop)
  system.PASSWD.write_text('root:x:0:0:Root:/root:/bin/bash\nalice:x:1001:1001:Alice:/home/alice:/bin/bash\nscanner:x:1002:1002:Scanner:/srv/scanner:/usr/sbin/nologin\nnobody:x:65534:65534::/:/bin/bash\n')
 def test_excludes_root_services_and_nobody(self):self.assertEqual([x['name'] for x in system.candidates()],['alice'])
 def identity(self,line):
  system.SHADOW.write_text(line)
  with patch.object(system.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=1001)):return system.identity('alice','secret')
 def test_locked_empty_expired_and_reset_passwords_fail_closed(self):
  for line in ['alice:!:20000:0:99999:7:::\n','alice::20000:0:99999:7:::\n','alice:$6$hash:0:0:99999:7:::\n','alice:$6$hash:20000:0:99999:7::1:\n','alice:$6$hash:1:0:1:7:::\n']:
   self.assertIsNone(self.identity(line))
 def test_stamp_changes_without_exposing_hash(self):
  a=self.identity('alice:$6$one:20000:0:99999:7:::\n');b=self.identity('alice:$6$two:20000:0:99999:7:::\n')
  self.assertNotEqual(a['stamp'],b['stamp']);self.assertNotIn('$6$',json.dumps(a))
 def test_pam_auth_and_account_management_real_library(self):
  import ctypes
  if not hasattr(ctypes.CDLL('libpam.so.0'),'pam_start_confdir'):self.skipTest('isolated PAM confdir not supported')
  from modules.accounts.pam_worker import authenticate
  for auth,account,expected in [('pam_permit.so','pam_permit.so',True),('pam_deny.so','pam_permit.so',False),('pam_permit.so','pam_deny.so',False)]:
   (self.root/'server-manager').write_text('auth required '+auth+'\naccount required '+account+'\n')
   self.assertEqual(authenticate('test-user','not-a-real-password',_test_confdir=self.root),expected)
  self.assertFalse(authenticate('test-user','',_test_confdir=self.root))

class SystemBackupGrants(SystemUsers):
 def test_grant_requires_user_role_and_client_scope(self):
  for role,modules,expected in [('user',['client'],True),('viewer',['client'],False),('user',[],False)]:
   self.users.change('alice',role,modules,True,self.users.read()['revision'],'ADMIN',system_backup=True)
   self.assertEqual(expected,self.users.principal('alice','test')['system_backup'])
 def test_default_off_and_strict_type(self):
  self.grant(modules=['client']);self.assertFalse(self.users.principal('alice','test')['system_backup'])
  data=self.users.read();data['users']['alice']['system_backup']='yes';self.users.path.write_text(json.dumps(data))
  with self.assertRaises(ValueError):self.users.read()
