"""Actual file roundtrip over a local HTTP transport fixture."""
import hashlib,http.server,importlib.util,io,json,os,sys,tempfile,threading,unittest,urllib.parse,zipfile
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'client_agent/desktop'))
spec=importlib.util.spec_from_file_location('desktop_core_for_backup',BASE/'client_agent/desktop/core.py');core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
with patch.dict(sys.modules,{'core':core}):
 spec=importlib.util.spec_from_file_location('desktop_backup',BASE/'client_agent/desktop/backup.py');backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)
class Roundtrip(unittest.TestCase):
 def test_files_empty_dirs_chunk_boundaries_and_unsafe_archive(self):
  state={};parts=[]
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):self.do_GET()
   def do_GET(self):
    if len(self.headers.get('X-HSM-Device',''))!=64 or len(self.headers.get('X-HSM-User',''))!=64: self.send_error(401);return
    if self.headers.get('Authorization')!='Bearer test-token':self.send_error(401);return
    q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query);action=q['action'][0];data=self.rfile.read(int(self.headers.get('Content-Length','0')));reply={}
    if action=='begin':state.update(json.loads(data));state.update(id='a'*32,content=b'');reply={'id':state['id']}
    elif action=='part':parts.append(int(q['offset'][0]));state['content']+=data
    elif action=='finish':state.update(json.loads(data));reply={'ok':True}
    elif action=='list':reply={'capabilities':['stream-zip-v1'],'backups':[{k:v for k,v in state.items() if k!='content'}]}
    elif action=='download':reply=state['content']
    payload=reply if isinstance(reply,bytes) else json.dumps(reply).encode();self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
  with tempfile.TemporaryDirectory() as tmp,http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   try:
    root=Path(tmp);source=root/'source';source.mkdir();(source/'empty').mkdir();(source/'data').write_bytes(os.urandom(5*1024**2));(source/'link').symlink_to('/etc/passwd')
    cfg=dict(core.DEFAULTS,SERVER_URL='http://127.0.0.1:'+str(server.server_port),TOKEN='test-token',CLIENT_NAME='Test')
    with patch.object(core,'load',return_value=cfg):
     with patch.object(backup.tempfile,'TemporaryDirectory',side_effect=AssertionError('No local archive allowed')):backup.create(source)
     self.assertEqual([0,backup.CHUNK],parts)
     item=backup.call('list')['backups'][0];backup.restore(item,root/'restored')
     self.assertEqual(backup.digest(source/'data'),backup.digest(root/'restored/data'));self.assertTrue((root/'restored/empty').is_dir());self.assertFalse((root/'restored/link').exists())
     with self.assertRaises(core.Error):backup.restore(item,root/'restored')
     bad=io.BytesIO()
     with zipfile.ZipFile(bad,'w') as z:z.writestr('files/../escape','bad')
     state['content']=bad.getvalue();item['sha256']=hashlib.sha256(state['content']).hexdigest();item['bytes']=len(state['content'])
     with self.assertRaises(core.Error):backup.restore(item,root/'malicious')
     self.assertFalse((root/'escape').exists());self.assertFalse((root/'malicious').exists())
   finally:server.shutdown();thread.join(timeout=5)
 def test_nested_mounts_and_file_bind_mounts_excluded(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'home';source.mkdir();dest=root/'backup';dest.mkdir()
   (source/'own.txt').write_text('keep');(source/'network').mkdir();(source/'network'/'private').write_text('omit')
   (source/'mounted-file').write_text('omit');(source/'disk').mkdir();(source/'disk'/'huge').write_text('omit')
   with patch.object(backup,'mount_boundaries',return_value={source/'network',source/'disk',source/'mounted-file'}),patch.object(backup,'usb_target',return_value=dest.stat().st_dev):backup.create(source,destination=dest)
   archive=next(dest.glob('*.zip'))
   with zipfile.ZipFile(archive) as z:
    self.assertIn('files/own.txt',z.namelist())
    self.assertFalse(any('network' in n or 'mounted-file' in n or '/disk' in n for n in z.namelist()))
 def test_mountinfo_failure_prevents_backup_start(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(backup,'mount_boundaries',side_effect=PermissionError('mount list unavailable')),patch.object(backup,'call') as call:
   with self.assertRaises(PermissionError):backup.create(tmp)
   call.assert_not_called()
if __name__=='__main__':unittest.main()
