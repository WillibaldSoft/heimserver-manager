import importlib.util,io,json,tempfile,unittest,hashlib,zipfile
from pathlib import Path
from unittest.mock import patch
from flask import Flask,request
from modules.backup import client_api as api
import modules.heimnetz_clients
class Isolation(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.guard=patch.object(api,'guard',return_value={'enabled':True,'quota_gib':100});self.guard.start()
  self.p=patch.object(api.server_settings,'get',return_value=str(self.root));self.p.start()
  self.space=patch.object(api.shutil,'disk_usage',return_value=type('Space',(),{'free':1000*1024**3})());self.space.start()
  self.auth=patch('modules.heimnetz_clients.agent_by_token',side_effect=lambda ctx: {'id':{'a':1,'b':2}[request.headers.get('Authorization')]} if request.headers.get('Authorization') in ('a','b') else None);self.auth.start()
  app=Flask(__name__);app.testing=True;api.register(app,None);self.c=app.test_client();self.c.set_cookie('server_manager_language','de')
 def tearDown(self):self.guard.stop();self.auth.stop();self.space.stop();self.p.stop();self.tmp.cleanup()
 def req(self,action,method='get',user='a',**kwargs):
  return getattr(self.c,method)('/api/clients/backup?action='+action,headers={'Authorization':user},**kwargs)
 def archive(self):
  s=io.BytesIO()
  with zipfile.ZipFile(s,'w') as z:z.writestr('files/a.txt','hello')
  return s.getvalue()
 def upload(self):
  data=self.archive();r=self.req('begin','post',json={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'name':'home'})
  self.assertEqual(200,r.status_code,r.data);sid=r.json['id']
  self.assertEqual(200,self.req('part&id='+sid+'&offset=0','post',data=data).status_code)
  self.assertEqual(200,self.req('finish&id='+sid,'post',json={}).status_code);return sid,data
 def test_isolation_download_and_path_traversal(self):
  sid,data=self.upload();response=self.req('download&id='+sid);self.assertEqual(data,response.data);response.close()
  self.assertEqual([],self.req('list',user='b').json['backups'])
  self.assertEqual(400,self.req('download&id='+sid,user='b').status_code)
  self.assertEqual(400,self.req('download&id=../1/'+sid,user='b').status_code)
  self.assertEqual(401,self.req('list',user='invalid').status_code)
 def test_incomplete_not_listed_and_cancel_is_own(self):
  data=self.archive();r=self.req('begin','post',json={'bytes':len(data),'sha256':'a'*64});sid=r.json['id']
  self.assertEqual([],self.req('list').json['backups'])
  self.req('cancel','post',user='b',json={});self.assertTrue((self.root/'desktop-client-backup/1'/('.upload-'+sid)).exists())
  self.assertEqual(400,self.req('finish&id='+sid,'post',json={}).status_code)
  self.req('cancel','post',json={});self.assertFalse((self.root/'desktop-client-backup/1'/('.upload-'+sid)).exists())
 def test_wrong_offset_and_checksum(self):
  data=self.archive();sid=self.req('begin','post',json={'bytes':len(data),'sha256':'a'*64}).json['id']
  self.assertEqual(400,self.req('part&id='+sid+'&offset=1','post',data=data).status_code)
  self.assertEqual(200,self.req('part&id='+sid+'&offset=0','post',data=data).status_code)
  self.assertEqual(400,self.req('finish&id='+sid,'post',json={}).status_code)
  self.assertEqual([],self.req('list').json['backups'])
 def test_streaming_finish_and_quota(self):
  data=self.archive();sid=self.req('begin','post',json={'bytes':0,'sha256':'','stream':True}).json['id']
  self.assertEqual(200,self.req('part&id='+sid+'&offset=0','post',data=data).status_code)
  self.assertEqual([],self.req('list').json['backups'])
  self.assertEqual(400,self.req('finish&id='+sid,'post',json={'bytes':len(data),'sha256':'a'*64}).status_code)
  self.assertEqual(200,self.req('finish&id='+sid,'post',json={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}).status_code)
  self.assertEqual(len(data),self.req('list').json['backups'][0]['bytes'])
  sid=self.req('begin','post',json={'bytes':0,'sha256':'','stream':True}).json['id']
  with patch.object(api,'guard',return_value={'enabled':True,'quota_gib':0}):
   self.assertEqual(400,self.req('part&id='+sid+'&offset=0','post',data=b'x').status_code)
 def test_symlink_target_rejected(self):
  (self.root/'desktop-client-backup').symlink_to(self.root)
  self.assertEqual(400,self.req('list').status_code)
 def test_oversize_and_low_disk(self):
  self.assertEqual(400,self.req('begin','post',json={'bytes':api.QUOTA+1,'sha256':'a'*64}).status_code)
  with patch.object(api.shutil,'disk_usage',return_value=type('Space',(),{'free':0})()):
   self.assertEqual(400,self.req('begin','post',json={'bytes':200,'sha256':'a'*64}).status_code)
if __name__=='__main__':unittest.main()

class AdminBoundary(unittest.TestCase):
 def test_client_token_never_authorizes_server_backup_and_reauth_shown(self):
  from authentication import register
  with tempfile.TemporaryDirectory() as tmp:
   app=Flask(__name__);app.testing=True;register(app,Path(tmp))
   app.add_url_rule('/backup',endpoint='backup',view_func=lambda:'server-backup',methods=['GET','POST'])
   app.add_url_rule('/apps/demo/backup',endpoint='app_backup',view_func=lambda:'server-backup',methods=['POST'])
   c=app.test_client();c.set_cookie('server_manager_language','de')
   self.assertEqual(303,c.get('/backup',headers={'Authorization':'Bearer client-token'}).status_code)
   self.assertEqual(401,c.post('/backup',headers={'Authorization':'Bearer client-token'}).status_code)
   self.assertEqual(401,c.post('/apps/demo/backup',headers={'Authorization':'Bearer client-token'}).status_code)
   c.get('/login')
   with c.session_transaction() as session:token=session['auth_csrf']
   self.assertEqual(303,c.post('/login',data=dict(username='ADMIN',password='ADMIN',auth_csrf=token)).status_code)
   self.assertEqual(200,c.get('/login?reauth=1&next=/backup').status_code)
   self.assertEqual(b'server-backup',c.get('/backup').data)

class BackupResponseLease(Isolation):
 def test_control_response_releases_activity_without_explicit_close(self):
  before=set(api.ACTIVE)
  response=self.req('list')
  self.assertEqual(response.status_code,200)
  self.assertEqual(before,set(api.ACTIVE))
  response.close()
 def test_download_keeps_activity_until_closed(self):
  sid,data=self.upload();before=set(api.ACTIVE)
  response=self.req('download&id='+sid)
  self.assertNotEqual(before,set(api.ACTIVE))
  response.close();self.assertEqual(before,set(api.ACTIVE))
