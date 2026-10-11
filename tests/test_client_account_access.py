import unittest,tempfile,io,zipfile,hashlib
from pathlib import Path
from unittest.mock import patch
from tests import test_system_users as fixtures
from modules.backup import client_api

class AccountBackup(unittest.TestCase):
 setUp=fixtures.SystemUsers.setUp
 grant=fixtures.SystemUsers.grant
 login=fixtures.SystemUsers.login
 token=fixtures.SystemUsers.token
 def setup_api(self):
  client_api.register(self.app,getattr(self,'ctx',None))
  for target,value in [('guard',{'enabled':True,'quota_gib':100})]:
   p=patch.object(client_api,target,return_value=value);p.start();self.addCleanup(p.stop)
  p=patch.object(client_api.server_settings,'get',return_value=str(self.root));p.start();self.addCleanup(p.stop)
  p=patch.object(client_api.shutil,'disk_usage',return_value=type('Space',(),{'free':1000*1024**3})());p.start();self.addCleanup(p.stop)
 def req(self,action,method='get',**kwargs):
  return getattr(self.client,method)('/api/account/backup?action='+action,headers={'Origin':'http://localhost'},**kwargs)
 def test_system_uid_gid_come_from_authenticated_server_account(self):
  from types import SimpleNamespace
  self.setup_api();self.grant(modules=['client']);self.login()
  with patch('pwd.getpwnam',return_value=SimpleNamespace(pw_name='alice',pw_uid=1001,pw_gid=2001)),patch('grp.getgrgid',return_value=SimpleNamespace(gr_name='users')):
   self.assertEqual(dict(username='alice',uid=1001,gid=2001,group='users'),self.client.get('/api/account/access').json['system_identity'])
  with patch('pwd.getpwnam',return_value=SimpleNamespace(pw_name='alice',pw_uid=9999,pw_gid=2001)),patch('grp.getgrgid',return_value=SimpleNamespace(gr_name='users')):
   self.assertIsNone(self.client.get('/api/account/access').json['system_identity'])
 def test_no_grant_and_no_login(self):
  self.setup_api();self.assertEqual(401,self.req('list').status_code)
  self.grant(modules=['apps']);self.login();self.assertEqual(403,self.req('list').status_code)
  self.assertEqual(403,self.client.get('/api/account/access').status_code)
 def test_upload_restore_isolation_and_revocation(self):
  self.setup_api();self.grant(modules=['client']);self.login()
  self.assertTrue(self.client.get('/api/account/access').json['backup'])
  stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w') as z:z.writestr('files/sample.txt','test')
  data=stream.getvalue()
  r=self.req('begin','post',json={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()});self.assertEqual(200,r.status_code,r.data);sid=r.json['id']
  self.assertEqual(200,self.req('part&id='+sid+'&offset=0','post',data=data).status_code)
  self.assertEqual(200,self.req('finish&id='+sid,'post',json={}).status_code)
  r=self.req('download&id='+sid);self.assertEqual(data,r.data);r.close()
  self.grant('bob',modules=['client']);self.login('bob')
  self.assertEqual([],self.req('list').json['backups']);self.assertEqual(400,self.req('download&id='+sid).status_code)
  self.assertTrue(all(p.name.startswith('-') for p in (self.root/'desktop-client-backup').iterdir()))
  self.grant('bob',modules=['client'],enabled=False);self.assertEqual(401,self.req('list').status_code)
 def test_viewer_restore_only_and_csrf(self):
  self.setup_api();self.grant(role='viewer',modules=['client']);self.login()
  access=self.client.get('/api/account/access').json;self.assertTrue(access['restore']);self.assertFalse(access['backup'])
  self.assertEqual(200,self.req('list').status_code)
  self.assertEqual(403,self.req('cancel','post',json={}).status_code)
  self.grant(modules=['client']);self.login()
  self.assertEqual(403,self.client.post('/api/account/backup?action=cancel',json={}).status_code)
  self.assertEqual(403,self.client.post('/api/account/backup?action=cancel',json={},headers={'Origin':'https://evil.invalid'}).status_code)
  self.assertEqual(403,self.client.post('/apps/demo/backup',headers={'Origin':'http://localhost'}).status_code)
 def test_own_other_pc_backups_available_only_to_account_owner(self):
  import sqlite3,json
  from types import SimpleNamespace
  database=self.root/'clients.sqlite'
  def connect():
   con=sqlite3.connect(database);con.row_factory=sqlite3.Row;return con
  con=connect();con.execute('CREATE TABLE client_bindings(agent_id INTEGER,account_key TEXT)');con.execute('CREATE TABLE client_agents(id INTEGER,name TEXT)')
  con.executemany('INSERT INTO client_bindings VALUES(?,?)',[(1,'system:alice:1001'),(2,'system:bob:1002')]);con.executemany('INSERT INTO client_agents VALUES(?,?)',[(1,'Alice old PC'),(2,'Bob PC')]);con.commit();con.close()
  self.ctx=SimpleNamespace(db=connect);self.setup_api();self.grant(modules=['client']);self.login()
  sid='a'*32;folder=client_api.base(1)/sid;folder.mkdir();(folder/'files.zip').write_bytes(b'own-old-pc')
  (folder/'manifest.json').write_text(json.dumps(dict(id=sid,created='2026-01-01',name='system',bytes=10,sha256=hashlib.sha256(b'own-old-pc').hexdigest())))
  rows=self.req('list').json['backups'];self.assertEqual(1,rows[0]['source_agent']);self.assertEqual('Alice old PC',rows[0]['source_label'])
  r=self.req('download&id='+sid+'&source_agent=1');self.assertEqual(b'own-old-pc',r.data);r.close()
  self.assertEqual(400,self.req('download&id='+sid+'&source_agent=2').status_code)
  self.grant('bob',modules=['client']);self.login('bob')
  self.assertEqual([],self.req('list').json['backups']);self.assertEqual(400,self.req('download&id='+sid+'&source_agent=1').status_code)
 def test_desktop_login_and_requests_over_verified_tls(self):
  import ssl,threading,subprocess,urllib.request
  from wsgiref.simple_server import make_server,WSGIRequestHandler
  from tests.test_client_file_backup import backup,core
  self.setup_api();self.grant(modules=['client'])
  cert=self.root/'cert.pem';key=self.root/'key.pem'
  subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  class Quiet(WSGIRequestHandler):
   def log_message(self,*args):pass
  def secure_app(environ,start_response):
   environ['wsgi.url_scheme']='http';return self.app(environ,start_response)
  server=make_server('127.0.0.1',0,secure_app,handler_class=Quiet)
  tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key);server.socket=tls.wrap_socket(server.socket,server_side=True)
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  url='https://127.0.0.1:'+str(server.server_port)
  cfg=dict(core.DEFAULTS,SERVER_URL=url,TOKEN='legacy-test-token',CLIENT_NAME='test')
  original=urllib.request.build_opener;trusted=ssl.create_default_context(cafile=str(cert))
  try:
   with patch.object(core,'load',return_value=cfg),patch.object(urllib.request,'build_opener',side_effect=lambda *handlers:original(*handlers,urllib.request.HTTPSHandler(context=trusted))):
    self.assertEqual('alice',backup.account_login('alice','linux-secret')['username'])
    self.assertEqual([],backup.call('list')['backups'])
    self.assertTrue(backup.call('cancel',{})['ok'])
    self.grant(modules=['client'],enabled=False)
    with self.assertRaisesRegex(core.Error,'Anmeldung abgelaufen'):backup.call('list')
    backup.account_logout()
    with self.assertRaisesRegex(core.Error,'anmelden'):backup.call('list')
    with self.assertRaises(core.Error):backup.account_login('alice','wrong')
  finally:
   backup.ACCOUNT=None;backup.ACCOUNT_REQUIRED=False;server.shutdown();thread.join();server.server_close()
