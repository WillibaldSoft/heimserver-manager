import hashlib,io,json,sqlite3,sys,tarfile,tempfile,unittest,zipfile,subprocess,os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests.test_client_account_access import AccountBackup
from modules.backup import client_api
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import system_stream,system_https,backup

class SharedPC(AccountBackup):
 def setup_shared(self):
  db=self.root/'shared.sqlite'
  def connect():
   c=sqlite3.connect(db);c.row_factory=sqlite3.Row;return c
  c=connect();c.execute('CREATE TABLE client_bindings(agent_id INTEGER,account_key TEXT,device_id TEXT,local_user TEXT)');c.execute('CREATE TABLE client_agents(id INTEGER,name TEXT,enabled INTEGER)')
  c.executemany('INSERT INTO client_bindings VALUES(?,?,?,?)',[(1,'system:alice:1001','a'*64,'1'*64),(2,'system:bob:1002','a'*64,'2'*64)])
  c.executemany('INSERT INTO client_agents VALUES(?,?,1)',[(1,'Alice'),(2,'Bob')]);c.commit();c.close()
  self.ctx=SimpleNamespace(db=connect);self.setup_api();self.grant(role='admin',modules=['client']);self.login()
 def request(self,action,data=None,device='a'*64,user='1'*64):
  headers={'Origin':'http://localhost','X-HSM-Device':device,'X-HSM-User':user}
  if data is None:return self.client.get('/api/account/backup?action='+action,headers=headers)
  return self.client.post('/api/account/backup?action='+action,headers=headers,**({'json':data} if isinstance(data,dict) else {'data':data}))
 def upload(self,query,payload=b'PK\x03\x04fixture',ref=''):
  r=self.request('cas-begin'+query,dict(name='fixture',system_id=ref));self.assertEqual(200,r.status_code,r.data);sid=r.json['id'];sha=hashlib.sha256(payload).hexdigest()
  self.assertEqual(200,self.request('block-put&id='+sid+'&hash='+sha+query,payload).status_code)
  self.assertEqual(200,self.request('cas-finish&id='+sid+query,dict(chunks=[dict(sha256=sha,bytes=len(payload))],bytes=len(payload),sha256=sha)).status_code)
  return sid
 def test_shared_reuse_and_admin_only_download_even_for_paired_user(self):
  self.setup_shared();sid=self.upload('&pc='+'a'*64)
  self.assertEqual(sid,self.request('pc-status').json['system']['id'])
  self.grant('bob',modules=['client']);self.login('bob')
  state=self.request('pc-status',user='2'*64).json;self.assertEqual(sid,state['system']['id']);self.assertFalse(state['system_admin'])
  self.assertEqual([],self.request('list',user='2'*64).json['backups'])
  for action,data in [('download&id='+sid,None),('block-has&hash='+'a'*64,None),('cas-begin',{}),('cancel',{})]:
   self.assertEqual(403,self.request(action+'&pc='+'a'*64,data,user='2'*64).status_code)
  self.assertEqual(400,self.request('pc-status',device='b'*64,user='2'*64).status_code)
  self.grant('bob',role='admin',modules=['client']);self.login('bob')
  r=self.request('download&id='+sid+'&pc='+'a'*64);self.assertEqual(b'PK\x03\x04fixture',r.data);r.close()
 def test_personal_reference_isolated_and_forgery_rejected(self):
  self.setup_shared();shared=self.upload('&pc='+'a'*64)
  self.grant(modules=['client']);self.login()
  own=self.upload('&personal=1',ref=shared)
  item=self.request('list').json['backups'][0];self.assertEqual('personal',item['component']);self.assertEqual(shared,item['system_id'])
  self.grant('bob',modules=['client']);self.login('bob')
  self.assertEqual([],self.request('list',user='2'*64).json['backups'])
  self.assertEqual(400,self.request('download&id='+own,user='2'*64).status_code)
  self.assertEqual(400,self.request('cas-begin&personal=1',{'system_id':'f'*32},user='2'*64).status_code)
  self.assertEqual(400,self.request('cas-begin&personal=1',{},device='b'*64,user='2'*64).status_code)
 def test_old_full_backup_is_not_silently_shared(self):
  self.setup_shared();self.upload('')
  self.assertIsNone(self.request('pc-status').json['system'])

class Components(unittest.TestCase):
 def fixture(self,root):
  for name in ('etc/passwd','etc/os-release','etc/config','home/alice/.config/data','home/bob/secret','srv/other/secret','mnt/share/remote'):
   p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('content')
  (root/'etc/passwd').write_text('alice:x:1001:1001::/home/alice:/bin/bash\nbob:x:1002:1002::/home/bob:/bin/bash\nother:x:1003:1003::/srv/other:/bin/bash\n')
 def test_shared_system_excludes_every_home_and_nested_selected_mount(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.fixture(root)
   rows=[dict(target='/',fstype='ext4'),dict(target='/home',fstype='ext4'),dict(target='/home/bob',fstype='ext4'),dict(target='/mnt/share',fstype='cifs')]
   names=list(system_stream.file_names(root,dict(component='system',extra_mounts=['/home/bob'],source_root=str(root)),rows))
   self.assertIn('./etc/config',names)
   for secret in ('./home/bob/secret','./home/alice/.config/data','./srv/other/secret','./mnt/share/remote'):self.assertNotIn(secret,names)
 def test_personal_preserves_hidden_files_but_not_other_users_or_mounts(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.fixture(root);p=root/'home/alice/share/secret';p.parent.mkdir();p.write_text('network')
   rows=[dict(target='/',fstype='ext4'),dict(target='/home/alice/share',fstype='cifs')]
   with patch.object(system_stream,'personal_user',return_value=SimpleNamespace(pw_dir='/home/alice')):
    names=list(system_stream.file_names(root,{'component':'personal'},rows))
   self.assertIn('./home/alice/.config/data',names);self.assertNotIn('./etc/config',names);self.assertNotIn('./home/bob/secret',names);self.assertNotIn('./home/alice/share/secret',names)
 def test_workflow_reuses_system_and_keeps_personal_reference(self):
  state=dict(device_id='a'*64,system=dict(id='b'*32,created='date'),system_admin=False)
  with patch.object(backup,'call',side_effect=[{'capabilities':['shared-pc-v1']},state]),patch.object(system_https,'create_component',return_value=('c'*32,'done')) as create:
   result=system_https.create()
   self.assertEqual(1,create.call_count);self.assertEqual('personal',create.call_args.args[1]['component']);self.assertEqual('b'*32,create.call_args.args[-1]);self.assertIn('done',result)
 def test_refresh_requires_admin(self):
  with patch.object(backup,'call',side_effect=[{'capabilities':['shared-pc-v1']},dict(system=None,system_admin=False)]),patch.object(system_https,'create_component') as create:
   with self.assertRaises(Exception):system_https.create(options={'refresh_system':True})
   create.assert_not_called()
 def test_real_personal_tar_and_metadata_are_repeatable(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);self.fixture(root)
   script='''import system_stream as s,pwd,os
from pathlib import Path
root=Path(os.environ['TEST_SOURCE'])
u=pwd.getpwuid(os.getuid())
s.personal_user=lambda:pwd.struct_passwd(('alice','x',u.pw_uid,u.pw_gid,'','/home/alice','/bin/bash'))
s.source_root=lambda options:root
s.mounts=lambda:[dict(target=str(root),fstype='ext4')]
original=s.command
s.command=lambda options,rows:original(dict(options,source_root=str(root)),rows)
s.main()
'''
   env=dict(os.environ,TEST_SOURCE=tmp,PYTHONPATH=str(Path(system_stream.__file__).parent))
   command=[sys.executable,'-c',script,'backup',json.dumps({'component':'personal'})]
   first=subprocess.check_output(command,env=env);second=subprocess.check_output(command,env=env)
   self.assertEqual(first,second)
   with tarfile.open(fileobj=io.BytesIO(first)) as t:
    self.assertEqual(b'content',t.extractfile('./home/alice/.config/data').read())
    self.assertNotIn('./home/bob/secret',t.getnames());self.assertNotIn('bob',t.extractfile('etc/passwd').read().decode())
    self.assertIn('etc/os-release',t.getnames())

 def test_split_migration_layout_keeps_user_data_separate(self):
  import system_migration
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'source';root.mkdir();self.fixture(root)
   inv=dict(component='personal',os_release='ID=debian',architecture='x86_64',users={},commands={})
   personal=system_migration.layout(root,Path(tmp)/'personal',inv,'alice')
   self.assertTrue((personal/'personal-component').is_file())
   self.assertEqual(root/'home/alice',(personal/'files').resolve())
   import shutil
   shutil.rmtree(root/'home')
   inv['component']='system'
   shared=system_migration.layout(root,Path(tmp)/'shared',inv,'alice')
   self.assertFalse((shared/'personal-component').exists());self.assertEqual([],list((shared/'files').iterdir()))

class DelegatedSystemBackup(SharedPC):
 def test_explicit_grant_and_revocation(self):
  self.setup_shared();sid=self.upload('&pc='+'a'*64)
  self.users.change('bob','user',['client'],True,self.users.read()['revision'],'ADMIN',system_backup=True)
  self.login('bob')
  self.assertTrue(self.request('pc-status',user='2'*64).json['system_admin'])
  r=self.request('download&id='+sid+'&pc='+'a'*64,user='2'*64)
  self.assertEqual(200,r.status_code);r.close()
  self.assertTrue(any(x['id']==sid for x in self.request('list',user='2'*64).json['backups']))
  self.upload('&pc='+'b'*64)
  self.assertEqual(403,self.client.get('/settings/users').status_code)
  self.grant('bob',modules=['client'])
  self.assertNotEqual(200,self.request('list',user='2'*64).status_code)
  self.login('bob')
  self.assertEqual(403,self.request('download&id='+sid+'&pc='+'a'*64,user='2'*64).status_code)
