import hashlib,time,unittest
from unittest.mock import patch
from tests.test_client_account_access import AccountBackup

class BackupLease(AccountBackup):
 def start(self):
  self.setup_api();self.grant(modules=['client']);self.login()
  self.headers={'Origin':'http://localhost','X-HSM-Device':'a'*64,'X-HSM-User':'b'*64}
  result=self.client.post('/api/account/backup?action=session-begin',json={},headers=self.headers)
  self.assertEqual(200,result.status_code,result.json)
  self.headers['X-HSM-Backup-Session']=result.json['token']
 def call(self,action,data=None):
  return self.client.get('/api/account/backup?action='+action,headers=self.headers) if data is None else self.client.post('/api/account/backup?action='+action,json=data,headers=self.headers)
 def expire(self):
  with self.client.session_transaction() as s:s['auth_expires']=time.time()-1
 def test_backup_completes_after_cookie_expiry(self):
  self.start();sid=self.call('cas-begin',{}).json['id'];self.expire()
  self.assertEqual(401,self.client.get('/api/account/access').status_code)
  data=b'PK\x03\x04payload';sha=hashlib.sha256(data).hexdigest()
  put=self.client.post('/api/account/backup?action=block-put&id='+sid+'&hash='+sha,data=data,headers=self.headers)
  self.assertEqual(200,put.status_code,put.json)
  result=self.call('cas-finish&id='+sid,dict(chunks=[dict(sha256=sha,bytes=len(data))],bytes=len(data),sha256=sha))
  self.assertEqual(200,result.status_code,result.json)
  self.assertEqual(200,self.call('session-end',{}).status_code)
  self.assertEqual(401,self.call('list').status_code)
 def test_no_general_login_or_other_upload_access(self):
  self.start();self.expire()
  self.assertEqual(401,self.client.get('/api/account/access',headers=self.headers).status_code)
  self.assertEqual(401,self.call('block-has&id='+'c'*32+'&hash='+'d'*64).status_code)
  self.assertEqual(401,self.call('cancel',{}).status_code)
  self.assertEqual(401,self.call('download&id='+'c'*32).status_code)
  self.assertEqual(401,self.call('cas-begin&pc='+'e'*64,{}).status_code)
 def test_binding_and_cross_origin(self):
  self.start();self.expire();self.headers['X-HSM-User']='c'*64
  self.assertEqual(401,self.call('list').status_code)
  self.headers['X-HSM-User']='b'*64;self.headers['Origin']='https://evil.example'
  self.assertEqual(403,self.call('cas-begin',{}).status_code)
 def test_disabled_account_and_revoked_grant(self):
  self.start();self.grant(modules=['client'],enabled=False)
  self.assertEqual(401,self.call('list').status_code)
 def test_active_run_slides_idle_expiry(self):
  self.start();now=time.time();self.expire()
  with patch('modules.backup.session_lease.time.time',return_value=now+23*3600):self.assertEqual(200,self.call('list').status_code)
  with patch('modules.backup.session_lease.time.time',return_value=now+46*3600):self.assertEqual(200,self.call('list').status_code)
  with patch('modules.backup.session_lease.time.time',return_value=now+71*3600):self.assertEqual(401,self.call('list').status_code)

 def test_background_status_scope_after_cookie_expiry(self):
  self.start();sid=self.call('cas-begin',{}).json['id'];self.expire()
  self.assertEqual(200,self.call('cas-status&id='+sid).status_code)
  self.assertEqual(401,self.call('cas-status&id='+'c'*32).status_code)
  self.assertEqual(401,self.call('cas-finalize&id='+'c'*32,{}).status_code)
