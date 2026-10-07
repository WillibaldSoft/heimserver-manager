import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from modules.shares import user_admin as s

class LocalUserAdmin(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
  self.passwd=root/'passwd';self.group=root/'group'
  self.passwd.write_text('alice:x:1001:1001:Alice:/home/alice:/bin/bash\nroot:x:0:0:root:/root:/bin/bash\nservice:x:50:50:svc:/:/usr/sbin/nologin\n')
  self.group.write_text('root:x:0:\nalice:x:1001:\nsudo:x:27:\nvideo:x:44:alice\nshared:x:1002:alice\n')
  for name,value in [('PASSWD',self.passwd),('GROUP',self.group)]:
   p=patch.object(s,name,value);p.start();self.addCleanup(p.stop)
  for owner,name,value in [(s.accounts.pwd,'getpwnam',SimpleNamespace(pw_uid=1001,pw_gid=1001)),(s.accounts.grp,'getgrgid',SimpleNamespace(gr_name='alice'))]:
   p=patch.object(owner,name,return_value=value);p.start();self.addCleanup(p.stop)
 def revision(self):return s.inspect('alice')['revision']
 def test_root_service_and_external_accounts_rejected(self):
  for name in ('root','service','unknown','-x'):
   with self.assertRaises(ValueError):s.inspect(name)
 def test_stale_user_identity_rejected(self):
  old=self.revision();self.passwd.write_text(self.passwd.read_text().replace('Alice:','Renamed:'))
  with patch.object(s,'sudo_run') as run,self.assertRaises(ValueError):s.apply('alice',old,'add_group','sudo',acknowledged=True)
  run.assert_not_called()
 def test_privileged_group_requires_explicit_confirmation(self):
  with patch.object(s,'sudo_run') as run,self.assertRaises(ValueError):s.apply('alice',self.revision(),'add_group','sudo')
  run.assert_not_called()
 def test_group_add_preserves_other_memberships_and_verifies(self):
  def execute(cmd,**kw):
   self.assertEqual(cmd,['usermod','-aG','sudo','alice']);self.group.write_text(self.group.read_text().replace('sudo:x:27:','sudo:x:27:alice'));return {'ok':True}
  with patch.object(s,'sudo_run',side_effect=execute):s.apply('alice',self.revision(),'add_group','sudo',acknowledged=True)
  self.assertEqual(s.inspect('alice')['groups'],['shared','sudo','video'])
 def test_remove_only_selected_group(self):
  def execute(cmd,**kw):
   self.assertEqual(cmd,['gpasswd','-d','alice','shared']);self.group.write_text(self.group.read_text().replace('shared:x:1002:alice','shared:x:1002:'));return {'ok':True}
  with patch.object(s,'sudo_run',side_effect=execute):s.apply('alice',self.revision(),'remove_group','shared')
  self.assertEqual(s.inspect('alice')['groups'],['video'])
 def test_primary_unknown_and_root_groups_rejected(self):
  for group in ('alice','missing','root'):
   with patch.object(s,'sudo_run') as run,self.assertRaises(ValueError):s.apply('alice',self.revision(),'add_group',group,acknowledged=True)
   run.assert_not_called()
 def test_checkbox_batch_add_remove(self):
  def execute(cmd,**kw):
   data=self.group.read_text()
   if cmd[0]=='usermod':data=data.replace('sudo:x:27:','sudo:x:27:alice')
   else:data=data.replace('shared:x:1002:alice','shared:x:1002:')
   self.group.write_text(data);return {'ok':True}
  with patch.object(s,'sudo_run',side_effect=execute) as run:
   s.apply('alice',self.revision(),'set_groups',selected_groups=['sudo','video'],acknowledged=True)
   self.assertEqual(run.call_count,2)
  self.assertEqual(s.inspect('alice')['groups'],['sudo','video'])
 def test_checkbox_invalid_privileged_and_stale_catalog(self):
  for wanted in (['root'],['alice'],['missing'],['sudo']):
   with patch.object(s,'sudo_run') as run,self.assertRaises(ValueError):s.apply('alice',self.revision(),'set_groups',selected_groups=wanted)
   run.assert_not_called()
  old=self.revision();self.group.write_text(self.group.read_text()+'newgroup:x:2001:\n')
  with patch.object(s,'sudo_run') as run,self.assertRaises(ValueError):s.apply('alice',old,'set_groups',selected_groups=[])
  run.assert_not_called()
 def test_checkbox_noop_and_partial_failure(self):
  with patch.object(s,'sudo_run') as run:s.apply('alice',self.revision(),'set_groups',selected_groups=['video','shared'])
  run.assert_not_called()
  with patch.object(s,'sudo_run',return_value={'ok':False}),self.assertRaisesRegex(ValueError,'Teiländerungen'):
   s.apply('alice',self.revision(),'set_groups',selected_groups=[])
 def test_legacy_group_selection_preserves_unlisted_sudo(self):
  with patch.object(s.accounts,'user_groups',return_value=['alice','shared','sudo','video']),patch.object(s.accounts,'groups',return_value=[dict(name='shared')]),patch.object(s.accounts,'sudo_run',return_value={'ok':True}) as run:
   s.accounts.set_user_groups('alice',[])
  self.assertEqual(run.call_args.args[0],['gpasswd','-d','alice','shared']);self.assertEqual(run.call_count,1)
 def test_password_in_stdin_only_and_linux_smb_separate(self):
  password='example-secret:123'
  for action,cmd in [('linux_password',['chpasswd']),('smb_password',['smbpasswd','-s','-a','alice'])]:
   with patch.object(s,'sudo_input',return_value={'ok':True}) as run:
    message=s.apply('alice',self.revision(),action,new_password=password,confirmation=password)
    self.assertEqual(run.call_args.args[0],cmd);self.assertIn(password,run.call_args.args[1]);self.assertNotIn(password,message)
 def test_password_confirmation_validation_and_failure_redaction(self):
  for password,confirmation in [('short','short'),('long-enough','different'),('unsafe\npassword','unsafe\npassword')]:
   with patch.object(s,'sudo_input') as run,self.assertRaises(ValueError):s.apply('alice',self.revision(),'linux_password',new_password=password,confirmation=confirmation)
   run.assert_not_called()
  with patch.object(s,'sudo_input',return_value={'ok':False,'err':'sensitive-test-value'}),self.assertRaises(ValueError) as caught:
   s.apply('alice',self.revision(),'linux_password',new_password='example-secret',confirmation='example-secret')
  self.assertNotIn('sensitive-test-value',str(caught.exception))

class AdminRoutes(unittest.TestCase):
 def setUp(self):
  import html
  from flask import Flask
  from authentication import register
  from modules.accounts import system
  from modules.shares.plugin import register as register_ui
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  with patch.object(system,'ensure_policy'):self.app=Flask(__name__);register(self.app,Path(self.tmp.name))
  import sqlite3
  self.app.testing=True
  def db():
   con=sqlite3.connect(Path(self.tmp.name)/'shares.sqlite');con.row_factory=sqlite3.Row;return con
  register_ui(self.app,SimpleNamespace(db=db,esc=html.escape,page=lambda title,body,*args:body))
  self.client=self.app.test_client();self.client.set_cookie('server_manager_language','de')
  self.client.get('/login')
  with self.client.session_transaction() as session:self.csrf=session['auth_csrf']
  self.client.post('/login',data=dict(auth_csrf=self.csrf,username='ADMIN',password='ADMIN'))
  with self.client.session_transaction() as session:self.csrf=session['auth_csrf']
  self.user=dict(name='alice',uid=1001,gid=1001,label='<Alice>',home='/home/alice',shell='/bin/bash',primary='alice',groups=['video'],revision='rev')
  for name,value in [('inspect',self.user),('local_groups',[dict(name='sudo',gid=27),dict(name='video',gid=44)])]:
   p=patch.object(s,name,return_value=value);p.start();self.addCleanup(p.stop)
 def test_reauth_csrf_and_password_not_echoed(self):
  form=dict(username='alice',revision='rev',action='linux_password',new_password='new-secret-value',confirm_password='new-secret-value',current_password='ADMIN')
  with patch.object(s,'apply',return_value='Linux-Passwort geändert.') as apply:
   self.assertEqual(self.client.post('/freigaben/users/edit',data=form).status_code,403);apply.assert_not_called()
   self.client.get('/freigaben/users/edit?user=alice')
   with self.client.session_transaction() as session:form['csrf']=session['shares_csrf']
   form['auth_csrf']=self.csrf;form['current_password']='wrong'
   self.assertEqual(self.client.post('/freigaben/users/edit',data=form).status_code,403);apply.assert_not_called()
   form['current_password']='ADMIN';res=self.client.post('/freigaben/users/edit',data=form)
   self.assertEqual(res.status_code,200);apply.assert_called_once();self.assertNotIn('new-secret-value',res.text)
 def test_get_is_read_only_and_escaped_in_both_languages(self):
  with patch.object(s,'apply') as apply:
   for lang,label in [('de','Linux-Passwort ändern'),('en','Change Linux password')]:
    self.client.set_cookie('server_manager_language',lang);res=self.client.get('/freigaben/users/edit?user=alice')
    self.assertEqual(res.status_code,200);self.assertIn(label,res.text);self.assertIn('&lt;Alice&gt;',res.text)
   apply.assert_not_called()
 def test_nonadmin_denied_even_with_forged_form(self):
  from modules.accounts import policy
  for role in ('user','viewer'):
   self.assertFalse(policy.allowed(dict(role=role,modules=list(policy.SCOPES)),'/freigaben/users/edit','POST'))
  self.client.post('/logout',data=dict(auth_csrf=self.csrf))
  with patch.object(s,'apply') as apply:
   self.assertEqual(self.client.post('/freigaben/users/edit',data={'current_password':'ADMIN'}).status_code,401);apply.assert_not_called()
