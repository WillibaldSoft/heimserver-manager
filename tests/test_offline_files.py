import io,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask,g
from modules import offline_files as server
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import offline as client
class Files(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);st=self.root.stat();self.row=dict(path=str(self.root),identity=[st.st_dev,st.st_ino],id='folder',name='Files',clients=[1],write=True)
 def tearDown(self):self.tmp.cleanup();server.ACTIVE.clear();server.LEASES.clear()
 def test_large_regular_file(self):
  p=self.root/'large.iso'
  with p.open('wb') as f:f.truncate(257*1024**2)
  with server.rootfd(self.row) as fd:remote=server.scan(fd)[0]
  local=client.local_scan(self.root)
  self.assertEqual(257*1024**2,remote['size'])
  self.assertEqual(remote['sha'],local['large.iso']['sha'])
 def test_temp_reserve(self):
  from modules.offline_files.dispatch import reserve
  with tempfile.TemporaryFile() as f:
   with patch('os.fstatvfs',return_value=SimpleNamespace(f_bavail=512,f_frsize=1024**2)):
    with self.assertRaises(ValueError):reserve(f.fileno(),1)
 def test_nested_server_files_are_included(self):
  p=self.root/'documents'/'nested';p.mkdir(parents=True);(p/'example.txt').write_text('nested')
  with server.rootfd(self.row) as fd:
   self.assertEqual(['documents/nested/example.txt'],[r['path'] for r in server.scan(fd)])
   self.assertEqual([],server.scan(fd,exclude=['documents']))
 def test_cas(self):
  p=self.root/'file';p.write_bytes(b'old')
  with server.rootfd(self.row) as fd:
   sha=server.scan(fd)[0]['sha'];server.mutate(fd,'file',sha,io.BytesIO(b'new'),3)
   with self.assertRaises(FileExistsError):server.mutate(fd,'file',sha,io.BytesIO(b'bad'),3)
   self.assertEqual(p.read_bytes(),b'new');self.assertEqual(list(self.root.glob('.hsm-history-*'))[0].read_bytes(),b'old')
   sha=server.scan(fd)[0]['sha'];server.mutate(fd,'file',sha,io.BytesIO(),0,True);self.assertFalse(p.exists())
 def test_paths(self):
  for path in ['../x','/x','a//b','a\\b','a:b','.hsm-history/a','NUL.txt','x.']:
   with self.assertRaises(ValueError):server.parts(path)
  p=self.root/'file';p.write_bytes(b'old');(self.root/'link').symlink_to(p)
  with server.rootfd(self.row) as fd:
   with self.assertRaises((ValueError,OSError)):server.scan(fd)
  (self.root/'link').unlink();os.link(p,self.root/'hard')
  with server.rootfd(self.row) as fd:
   with self.assertRaises(ValueError):server.scan(fd)
  (self.root/'hard').unlink();(self.root/'FILE').write_bytes(b'other')
  with server.rootfd(self.row) as fd:
   with self.assertRaises(ValueError):server.scan(fd)
 def test_identity_and_incomplete(self):
  with self.assertRaises(ValueError):
   with server.rootfd(dict(self.row,identity=[0,0])):pass
  with server.rootfd(self.row) as fd:
   with self.assertRaises(ValueError):server.mutate(fd,'new','',io.BytesIO(b'x'),3)
  self.assertFalse((self.root/'new').exists());self.assertFalse(list(self.root.glob('.hsm-part-*')))
 def test_checksum_and_exclusions(self):
  (self.root/'file').write_bytes(b'old')
  with server.rootfd(self.row) as fd:
   sha=server.scan(fd)[0]['sha']
   with self.assertRaises(ValueError):server.mutate(fd,'file',sha,io.BytesIO(b'new'),3,False,'0'*64)
   self.assertEqual(b'old',(self.root/'file').read_bytes())
   self.assertEqual([],server.scan(fd,exclude=['file']))
  self.assertEqual({},client.local_scan(self.root,['file']))
 def test_admin_policy(self):
  from modules.accounts.policy import allowed
  self.assertFalse(allowed(dict(role='user',modules=['client']),'/clients/offline','POST'))
  self.assertTrue(allowed(dict(role='admin'),'/clients/offline','POST'))
 def test_decisions(self):
  for args,result in [((None,None,'r',True,False),'get'),((None,'l',None,True,False),'put'),(('b','b','r',True,False),'get'),(('b','l','b',True,False),'put'),(('b','l','r',True,True),'conflict'),(('b',None,'b',True,False),'pending-delete'),(('b',None,'b',True,True),'delete'),(('b','b',None,True,True),'trash'),((None,'l','r',True,True),'conflict'),(('b','l','b',False,True),'conflict')]:self.assertEqual(result,client.decision(*args))
 def test_api_permissions(self):
  app=Flask(__name__);app.secret_key='test';server.register(app,SimpleNamespace(db=lambda:None))
  def auth(ctx):g.bound_client=True;return {'id':1}
  with patch('modules.heimnetz_clients.agent_by_token',side_effect=auth),patch.object(server,'grants',return_value=[self.row]),patch('modules.offline_files.rights.identity',return_value=object()),patch('modules.offline_files.rights.permission',return_value=True),patch('modules.offline_files.dispatch.invoke',return_value=dict(ok=True)):
   c=app.test_client();self.assertEqual(403,c.get('/api/clients/offline').status_code);self.assertEqual(200,c.get('/api/clients/offline',base_url='https://example.test').status_code)
   self.assertEqual(403,c.get('/api/clients/offline?action=scan&id=other',base_url='https://example.test').status_code)
   self.row['write']=False;self.assertEqual(403,c.post('/api/clients/offline?action=put&id=folder&path=x',data=b'bad',base_url='https://example.test').status_code)
   with patch('modules.heimnetz_clients.agent_by_token',return_value=None):self.assertEqual(403,c.get('/api/clients/offline',base_url='https://example.test').status_code)
 def test_assigned_but_denied_is_not_empty_success(self):
  app=Flask(__name__);app.secret_key='test';server.register(app,SimpleNamespace(db=lambda:None))
  def auth(ctx):g.bound_client=True;return {'id':1}
  with patch('modules.heimnetz_clients.agent_by_token',side_effect=auth),patch.object(server,'grants',return_value=[self.row]),patch('modules.offline_files.rights.identity',return_value=object()),patch('modules.offline_files.rights.permission',side_effect=ValueError('Unsupported SMB rules: force group')):
   response=app.test_client().get('/api/clients/offline',base_url='https://example.test')
   self.assertEqual(403,response.status_code);self.assertIn('force group',response.json['error'])
   with patch.object(server,'grants',return_value=[]):
    response=app.test_client().get('/api/clients/offline',base_url='https://example.test');self.assertEqual([],response.json['folders'])
 def test_roundtrip(self):
  remote=self.root/'server';local=self.root/'client';remote.mkdir();local.mkdir();(remote/'doc').write_text('first');st=remote.stat();grant=dict(self.row,path=str(remote),identity=[st.st_dev,st.st_ino]);row=dict(id='folder',local=str(local),write=True,delete=True,limit_gib=1)
  def api(action,gid='',path='',sha='',data=None,binary=False,exclude='',content_sha=''):
   if action=='list':return dict(folders=[grant])
   with server.rootfd(grant) as fd:
    if action=='scan':return dict(files=server.scan(fd))
    if action=='get':return io.BytesIO((remote/path).read_bytes())
    if action in ('put','delete'):
     content=data.read() if hasattr(data,'read') else data;server.mutate(fd,path,sha,io.BytesIO(content),len(content),action=='delete',content_sha or None)
   return dict(ok=True,sha=content_sha)
  with patch.object(client,'ROOT',self.root/'state'),patch.object(client,'call',side_effect=api),patch.object(client.core,'load',return_value={}),patch.object(client.core,'validate',return_value=dict(SERVER_URL='https://example.test',TOKEN='test')):
   client.sync(row);self.assertEqual('first',(local/'doc').read_text());(local/'doc').write_text('local');client.sync(row);self.assertEqual('local',(remote/'doc').read_text())
   (remote/'doc').write_text('remote');(local/'doc').write_text('conflict');self.assertIn('doc',client.sync(row));self.assertEqual('remote',(remote/'doc').read_text());self.assertEqual('conflict',(local/'doc').read_text())
   (local/'doc').write_text('remote');client.sync(row);(local/'doc').unlink();client.sync(row);self.assertFalse((remote/'doc').exists());(remote/'doc').write_text('restored');client.sync(row)
   with patch.object(client,'call',side_effect=OSError('offline')):
    with self.assertRaises(OSError):client.sync(row)
   self.assertEqual('restored',(local/'doc').read_text());(remote/'doc').unlink();client.sync(row);self.assertFalse((local/'doc').exists());self.assertTrue(list((local/'.hsm-recovery').rglob('doc')))
if __name__=='__main__':unittest.main()
