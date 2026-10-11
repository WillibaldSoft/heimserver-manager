import hashlib,io,json,os,sys,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from tests.test_shared_pc_backup import SharedPC
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import backup,core,incremental,system_stream
from modules.backup import client_api

class ServerCancel(SharedPC):
 def test_targeted_abort_keeps_completed_and_other_uploads(self):
  self.setup_shared();completed=self.upload('&pc='+'a'*64)
  sid=self.request('cas-begin&pc='+'a'*64,dict(name='unfinished')).json['id']
  root=self.root/'desktop-client-backup'/('pc-'+'a'*64)
  other=root/('.upload-'+'d'*32);other.mkdir()
  r=self.request('abort&id='+sid+'&pc='+'a'*64,{})
  self.assertTrue(r.json['aborted']);self.assertTrue((root/completed).exists());self.assertTrue(other.exists());self.assertFalse((root/('.upload-'+sid)).exists())
  self.assertTrue(self.request('abort&id='+completed+'&pc='+'a'*64,{}).json['completed'])
  self.grant('bob',modules=['client']);self.login('bob')
  self.assertEqual(403,self.request('abort&id='+'d'*32+'&pc='+'a'*64,{},user='2'*64).status_code)
 def test_finalization_observes_cancel_signal(self):
  self.setup_shared();query='&pc='+'a'*64
  sid=self.request('cas-begin'+query,{}).json['id'];data=b'PK\x03\x04data';sha=hashlib.sha256(data).hexdigest()
  self.request('block-put&id='+sid+'&hash='+sha+query,data)
  folder=self.root/'desktop-client-backup'/('pc-'+'a'*64)/('.upload-'+sid);(folder/'cancel-requested').touch()
  result=self.request('cas-finish&id='+sid+query,dict(chunks=[dict(bytes=len(data),sha256=sha)],bytes=len(data),sha256=sha))
  self.assertEqual(400,result.status_code);self.assertEqual([],self.request('list'+query).json['backups'])
  self.assertTrue(self.request('abort&id='+sid+query,{}).json['aborted']);self.assertFalse(folder.exists())
 def test_manager_abort_requires_admin_and_csrf(self):
  self.setup_shared();sid=self.request('cas-begin',{}).json['id']
  folder=next((self.root/'desktop-client-backup').glob('*/.upload-'+sid));owner=folder.parent.name
  self.assertEqual(403,self.client.post('/backup/desktop/abort',data=dict(owner=owner,id=sid)).status_code)
  self.grant(role='user',modules=['client']);self.login()
  self.assertEqual(403,self.client.post('/backup/desktop/abort',data=dict(owner=owner,id=sid),headers={'Origin':'http://localhost'}).status_code)
  self.grant(role='admin',modules=['client']);self.login()
  self.assertEqual(303,self.client.post('/backup/desktop/abort',data=dict(owner=owner,id=sid),headers={'Origin':'http://localhost'}).status_code)
  self.assertFalse(folder.exists())

class ClientCancel(unittest.TestCase):
 def tearDown(self):backup.CURRENT_BACKUP=None;system_stream.CANCELLED.clear()
 def test_file_backup_cancels_and_never_finishes(self):
  calls=[];sid='a'*32
  def call(action,data=None,query='',binary=False):
   calls.append(action)
   if action=='list':return dict(capabilities=['stream-zip-v1'])
   if action=='begin':return dict(id=sid)
   if action=='abort':return dict(aborted=True)
   return dict(ok=True)
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'large').write_bytes(os.urandom(backup.CHUNK+100))
   def progress(text):backup.request_cancel()
   with patch.object(backup,'call',side_effect=call):result=backup.create(p,progress)
  self.assertIn('abgebrochen',result);self.assertIn('abort',calls);self.assertNotIn('finish',calls);self.assertFalse(backup.backup_running())
 def test_incremental_cancel_does_not_upload_or_finalize(self):
  job=backup.BackupJob();job.cancel();calls=[]
  stream=incremental.Stream('a'*32,lambda text:None,call=lambda *a,**k:calls.append(a),check=job.check)
  with self.assertRaises(backup.Cancelled):stream.write(b'abc')
  with self.assertRaises(backup.Cancelled):stream.finish()
  self.assertEqual([],calls)
 def test_inventory_cancellation_reaps_child(self):
  import subprocess,time
  process=[];original=system_stream.subprocess.Popen
  def spawn(*a,**k):
   p=original(*a,**k);process.append(p);return p
  timer=threading.Timer(.2,system_stream.CANCELLED.set);timer.start()
  started=time.monotonic()
  try:
   with patch.object(system_stream.subprocess,'Popen',side_effect=spawn):
    with self.assertRaisesRegex(ValueError,'abgebrochen'):system_stream.capture([sys.executable,'-c','import time;time.sleep(20)'])
  finally:timer.cancel()
  self.assertLess(time.monotonic()-started,3);self.assertIsNotNone(process[0].poll())
 def test_late_abort_reports_preserved_completion(self):
  with patch.object(backup,'call',return_value={'completed':True}):
   self.assertIn('fertige Sicherung',backup.abort_upload(backup.call,'a'*32))
