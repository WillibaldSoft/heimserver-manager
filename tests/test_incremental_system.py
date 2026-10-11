import io,json,hashlib,os,sys,tempfile,unittest,zipfile,tarfile,contextlib,subprocess
from pathlib import Path
from unittest.mock import patch
from tests import test_client_backup_api as fixtures
from modules.backup import chunks,client_api
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import backup,incremental,system_components,system_files,system_restore,system_stream
from tests.test_system_restore import tar_data
class Incremental(unittest.TestCase):
 setUp=fixtures.Isolation.setUp
 tearDown=fixtures.Isolation.tearDown
 req=fixtures.Isolation.req
 def client_call(self,action,data=None,query='',binary=False):
  kw={}
  if isinstance(data,dict):kw['json']=data
  elif data is not None:kw['data']=data
  r=self.req(action+query,'get' if data is None else 'post',**kw)
  if r.status_code!=200:raise ValueError(r.get_json())
  return r.json
 def upload(self,data):
  sid=self.client_call('cas-begin',{'name':'Linux-System'})['id']
  stream=incremental.Stream(sid,lambda x:None)
  with patch.object(backup,'call',side_effect=self.client_call):
   stream.write(data);stream.finish()
  return sid,stream
 def zip(self,data):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w',zipfile.ZIP_STORED) as z:z.writestr(zipfile.ZipInfo('files/system.tar',(1980,1,1,0,0,0)),data)
  return b.getvalue()
 def test_reuses_unchanged_blocks_and_downloads_complete_stands(self):
  data=self.zip(os.urandom(2*backup.CHUNK+1200));sid,a=self.upload(data);sid2,b=self.upload(data)
  self.assertEqual(len(data),a.sent);self.assertEqual(0,b.sent);self.assertEqual(len(data),b.reused)
  changed=data[:-600]+b'X'+data[-599:];sid3,c=self.upload(changed)
  self.assertLess(c.sent,len(data));self.assertGreater(c.reused,0)
  for name,content in [(sid,data),(sid2,data),(sid3,changed)]:
   response=self.req('download&id='+name);self.assertEqual(content,response.data);response.close()
  self.assertEqual([],self.req('list',user='b').json['backups'])
  self.assertEqual(400,self.req('download&id='+sid,user='b').status_code)
  before=chunks.used(self.root/'desktop-client-backup/1')
  self.req('cancel','post',json={})
  self.assertEqual(before,chunks.used(self.root/'desktop-client-backup/1'))
 def test_corrupt_block_refused_and_unfinished_not_listed(self):
  sid=self.client_call('cas-begin',{})['id'];data=b'abcd';sha=hashlib.sha256(data).hexdigest()
  self.assertEqual(400,self.req('block-put&id='+sid+'&hash='+sha,'post',data=b'wrong').status_code)
  self.assertEqual([],self.req('list').json['backups'])
  self.assertEqual(400,self.req('cas-finish&id='+sid,'post',json={'bytes':4,'sha256':sha,'chunks':[{'bytes':4,'sha256':sha}]}).status_code)
  self.assertEqual(400,self.req('block-has&hash=../../etc/shadow').status_code)
 def test_cancel_reclaims_only_unreferenced_blocks(self):
  sid,stream=self.upload(self.zip(b'a'*1000));before=chunks.used(self.root/'desktop-client-backup/1')
  unfinished=self.client_call('cas-begin',{})['id'];data=b'unused';sha=hashlib.sha256(data).hexdigest()
  self.assertEqual(200,self.req('block-put&id='+unfinished+'&hash='+sha,'post',data=data).status_code)
  self.assertGreater(chunks.used(self.root/'desktop-client-backup/1'),before)
  self.req('cancel','post',json={});self.assertEqual(before,chunks.used(self.root/'desktop-client-backup/1'))
  self.assertEqual(1,len(self.req('list').json['backups']))
 def test_quota(self):
  sid=self.client_call('cas-begin',{})['id'];data=b'abcd';sha=hashlib.sha256(data).hexdigest()
  with patch.object(client_api,'guard',return_value={'enabled':True,'quota_gib':0}):
   self.assertEqual(400,self.req('block-put&id='+sid+'&hash='+sha,'post',data=data).status_code)

class Components(unittest.TestCase):
 def test_real_tar_is_repeatable_and_preserves_hidden_files_links(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp);(source/'home/u/.config').mkdir(parents=True);(source/'home/u/.config/settings').write_text('settings')
   os.link(source/'home/u/.config/settings',source/'home/u/hardlink');(source/'home/u/link').symlink_to('.config/settings')
   rows=[{'target':'/','fstype':'ext4'}];options={'source_root':str(source)}
   with patch.object(system_stream,'source_root',return_value=source):args=system_stream.command(options,[{'target':str(source),'fstype':'ext4'}])
   args=args[:args.index('--')]+['--no-recursion','--null','--verbatim-files-from','--files-from=-']
   names=b''.join(os.fsencode(n)+b'\0' for n in system_stream.file_names(source,options,rows))
   first=subprocess.check_output(args,input=names);second=subprocess.check_output(args,input=names)
   self.assertEqual(first,second)
   with tarfile.open(fileobj=io.BytesIO(first)) as t:
    self.assertEqual(b'settings',t.extractfile('./home/u/.config/settings').read());self.assertTrue(t.getmember('./home/u/link').issym())
    self.assertTrue(any(m.islnk() for m in t))
 def archive(self,root):
  f=root/'system.zip'
  with zipfile.ZipFile(f,'w') as z:
   z.writestr('files/system.tar',tar_data());z.writestr('hsm-backup.json',json.dumps({'scope':'linux-system-tar-v2'}))
  return f,hashlib.sha256(f.read_bytes()).hexdigest()
 def test_single_file_restore_and_checksum_no_target_changes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);f,sha=self.archive(root);target=root/'new'
   with self.assertRaises(ValueError):system_files.restore(f,'0'*64,target,root,'etc/config')
   self.assertFalse(target.exists())
   system_files.restore(f,sha,target,root,'etc/config')
   self.assertEqual('config',(target/'etc/config').read_text());self.assertFalse((target/'etc/passwd').exists())
   with self.assertRaises(ValueError):system_files.restore(f,sha,target,root,'etc/config')
 def test_identity_only_and_target_fstab_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);f,sha=self.archive(root);target=root/'target';target.mkdir();(target/'etc').mkdir();(target/'etc/fstab').write_text('target')
   with patch.object(system_restore.gates,'storage',return_value=str(root)),patch.object(system_restore,'target_check',return_value=(target,1)),patch.object(sys,'stdin',io.StringIO('WIEDERHERSTELLEN\n')),patch.object(system_restore.os,'sync'),contextlib.redirect_stdout(io.StringIO()):
    system_restore.run(str(f),sha,str(target),str(root),'identity')
   self.assertTrue((target/'etc/passwd').exists());self.assertFalse((target/'etc/config').exists());self.assertEqual('target',(target/'etc/fstab').read_text())
 def test_scope_and_extra_mount_validation(self):
  self.assertTrue(system_components.selected('var/lib/flatpak/app/file','software'))
  self.assertTrue(system_components.selected('home/user/.config/dconf/user','desktop'))
  self.assertFalse(system_components.selected('etc/shadow','home'))
  with self.assertRaises(ValueError):system_components.selected('etc/passwd','files','../etc')
  rows=[{'target':'/','fstype':'ext4'},{'target':'/srv/data','fstype':'ext4'},{'target':'/remote','fstype':'nfs4'}]
  with patch.object(Path,'is_symlink',return_value=False):args=system_stream.command({'extra_mounts':['/srv/data']},rows)
  self.assertIn('srv/data',args);self.assertIn('--exclude=./remote',args);self.assertIn('--exclude=./etc/NetworkManager/system-connections',args)
  args=system_stream.command({'extra_mounts':['/remote']},rows)
  self.assertIn('remote',args);self.assertNotIn('--exclude=remote',args)
 def test_file_enumeration_does_not_repeat_selected_mounts(self):
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp);(source/'home/u').mkdir(parents=True);(source/'home/u/file').write_text('home');(source/'srv/data').mkdir(parents=True);(source/'srv/data/item').write_text('data');(source/'remote').mkdir();(source/'remote/private').write_text('skip');(source/'proc').mkdir();(source/'proc/runtime').write_text('skip')
   rows=[{'target':'/','fstype':'ext4'},{'target':'/home','fstype':'ext4'},{'target':'/srv/data','fstype':'ext4'},{'target':'/remote','fstype':'nfs4'}]
   options={'source_root':str(source),'extra_mounts':['/srv/data']}
   names=list(system_stream.file_names(source,options,rows))
   self.assertEqual(len(names),len(set(names)));self.assertIn('./home/u/file',names);self.assertIn('./srv/data/item',names);self.assertNotIn('./remote/private',names);self.assertNotIn('./proc/runtime',names)
 def test_selected_fstab_is_safe_in_new_user_folder(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);f,sha=self.archive(root);target=root/'files'
   system_files.restore(f,sha,target,root,'etc/fstab')
   self.assertEqual('OLD DISK',(target/'etc/fstab').read_text())
 def test_different_platform_blocked_before_restore(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'etc').mkdir();(root/'etc/os-release').write_text('ID=target\nVERSION_ID=1')
   b=io.BytesIO()
   with zipfile.ZipFile(b,'w') as z:z.writestr('files/system-inventory.json',json.dumps({'os_release':'ID=other\nVERSION_ID=2','architecture':os.uname().machine}))
   with zipfile.ZipFile(b) as z,self.assertRaises(ValueError):system_restore.platform_check(z,root,'all')
