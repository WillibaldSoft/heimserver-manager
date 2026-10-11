import hashlib,threading,time,unittest
from unittest.mock import patch
from tests.test_incremental_system import Incremental
from modules.backup import finalize,chunks,client_api

class Background(Incremental):
 def prepare(self):
  data=self.zip(b'payload');sid=self.client_call('cas-begin',{})['id'];sha=hashlib.sha256(data).hexdigest()
  self.client_call('block-put',data,'&id='+sid+'&hash='+sha)
  return sid,dict(bytes=len(data),sha256=sha,chunks=[dict(bytes=len(data),sha256=sha)])
 def wait(self):
  for _ in range(300):
   if not finalize.RUNNING:return
   time.sleep(.01)
  self.fail('Worker did not finish')
 def test_async_poll_and_duplicate_do_not_wait_for_verification(self):
  sid,data=self.prepare();entered=threading.Event();release=threading.Event();original=chunks.iterate;before=set(client_api.ACTIVE)
  def slow(*args):
   entered.set();release.wait(5);yield from original(*args)
  with patch.object(chunks,'iterate',side_effect=slow):
   try:
    self.assertEqual(202,self.req('cas-finalize&id='+sid,'post',json=data).status_code)
    self.assertTrue(entered.wait(2));self.assertNotEqual(before,set(client_api.ACTIVE))
    self.assertIn(self.req('cas-status&id='+sid).json['state'],('queued','verifying'))
    self.assertEqual(202,self.req('cas-finalize&id='+sid,'post',json=data).status_code)
    self.assertEqual(400,self.req('cas-finalize&id='+sid,'post',json=dict(data,sha256='0'*64)).status_code)
   finally:release.set();self.wait()
  result=self.req('cas-status&id='+sid).json
  self.assertEqual('complete',result['state']);self.assertEqual(data['sha256'],result['sha256']);self.assertEqual(before,set(client_api.ACTIVE))
 def test_corruption_keeps_upload_and_never_reports_complete(self):
  sid,data=self.prepare();data['sha256']='0'*64
  self.assertEqual(202,self.req('cas-finalize&id='+sid,'post',json=data).status_code);self.wait()
  self.assertEqual('failed',self.req('cas-status&id='+sid).json['state'])
  self.assertEqual([],self.req('list').json['backups'])

 def test_cancellation_preserves_blocks_without_false_completion(self):
  sid,data=self.prepare();entered=threading.Event();release=threading.Event();original=chunks.iterate
  def slow(*args):
   entered.set();release.wait(5);yield from original(*args)
  with patch.object(chunks,'iterate',side_effect=slow):
   try:
    self.assertEqual(202,self.req('cas-finalize&id='+sid,'post',json=data).status_code)
    self.assertTrue(entered.wait(2))
    (self.root/'desktop-client-backup/1'/('.upload-'+sid)/'cancel-requested').touch()
   finally:release.set();self.wait()
  self.assertEqual('failed',self.req('cas-status&id='+sid).json['state'])
  self.assertEqual([],self.req('list').json['backups'])
  self.assertTrue(list((self.root/'desktop-client-backup/1/.blocks').iterdir()))
 def test_interrupted_state_is_explicit_and_preserves_upload(self):
  sid,data=self.prepare();folder=self.root/'desktop-client-backup/1'/('.upload-'+sid)
  client_api.save(folder/'verification-status.json',dict(state='verifying',id=sid))
  self.assertEqual('interrupted',self.req('cas-status&id='+sid).json['state']);self.assertTrue(folder.is_dir())

class Client(unittest.TestCase):
 def test_initial_timeout_polls_same_job_without_resubmitting(self):
  import incremental,backup
  stream=incremental.Stream('a'*32,lambda msg:None,async_finish=True)
  sha=stream.hash.hexdigest();calls=[]
  def call(action,*args,**kw):
   calls.append(action)
   if action=='cas-finalize':raise TimeoutError('timed out')
   return dict(state='complete',id=stream.sid,bytes=0,sha256=sha)
  stream.call=call
  self.assertEqual('complete',stream.finish()['state'])
  self.assertEqual(['cas-finalize','cas-status'],calls)
