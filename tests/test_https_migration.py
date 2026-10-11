import hashlib,io,json,os,pwd,shutil,subprocess,sys,tarfile,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import system_migration as migration

class Migration(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.system=self.root/'system';self.system.mkdir()
  self.put('etc/passwd','alice:x:1000:1000:Alice:/home/alice:/bin/bash\nroot:x:0:0:root:/root:/bin/bash\n')
  self.put('etc/group','alice:x:1000:\n');self.put('home/alice/data','hello')
  self.inv=dict(os_release='ID=debian\nVERSION_ID=13\n',architecture='x86_64',commands={'manual-packages':dict(status='ok',output='gimp\n')},users={'alice':{'pip':dict(status='ok',output='example==1.0\n')}})
 def put(self,name,value):
  p=self.system/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value);return p
 def test_maps_inventory_home_and_source_identity(self):
  b=migration.layout(self.system,self.root/'backup',self.inv,'alice')
  self.assertEqual((b/'files/data').read_text(),'hello');self.assertEqual((b/'apps/apt-manual.txt').read_text(),'gimp\n')
  self.assertEqual((b/'migration-v20/software/pip-user.txt').read_text(),'example==1.0\n')
  self.assertIn('alice:x:1000',(b/'migration-v20/inventory/etc_passwd').read_text())
 def test_unknown_user_rejected(self):
  with self.assertRaises(ValueError):migration.layout(self.system,self.root/'backup',self.inv,'root')
 def test_metadata_symlink_cannot_read_host(self):
  (self.system/'etc/passwd').unlink();(self.system/'etc/passwd').symlink_to('/etc/passwd')
  with self.assertRaises(ValueError):migration.users(self.system)
 def test_source_home_symlink_not_used(self):
  (self.system/'home/alice/data').unlink();(self.system/'home/alice').rmdir();(self.system/'home/alice').symlink_to('/tmp')
  self.assertEqual({},migration.users(self.system))
 def test_payload_does_not_follow_symlinks(self):
  original=self.put('opt/app/config','safe');(original.parent/'external').symlink_to('/etc')
  b=migration.layout(self.system,self.root/'backup',self.inv,'alice')
  dest=b/'migration-v20/payload/opt/app/config'
  self.assertEqual(dest.stat().st_ino,original.stat().st_ino)
  self.assertFalse((dest.parent/'external').exists())
 def test_units_only_custom_regular(self):
  self.put('etc/systemd/system/local.service','[Service]\nExecStart=/bin/true\n')
  self.put('etc/systemd/system/vendor.service','[Service]\n');self.put('usr/lib/systemd/system/vendor.service','vendor')
  (self.system/'etc/systemd/system/evil.service').symlink_to('/etc/passwd')
  b=migration.layout(self.system,self.root/'backup',self.inv,'alice')
  self.assertEqual(['local.service'],json.loads((b/'migration-v20/custom-units.json').read_text()))
 def test_mounts_data_only_and_credentials_remain_private(self):
  self.put('etc/fstab','//example.invalid/files /SVL/files cifs credentials=/etc/example.cred 0 0\nUUID=example / ext4 defaults 0 1\n')
  self.put('etc/example.cred','username=example\npassword=example\n')
  b=migration.layout(self.system,self.root/'backup',self.inv,'alice');p=b/'svl-config-v19/snapshot.json';data=json.loads(p.read_text())
  self.assertEqual(['/SVL/files'],data['paths']);self.assertEqual(1,len(data['fstab']));self.assertEqual(0o600,p.stat().st_mode&0o777)
 def test_cancel_migration_menu_without_target_changes(self):
  if os.getuid()<1000:self.skipTest('Needs normal local user for cancelled menu fixture')
  user=pwd.getpwuid(os.getuid())
  if not Path(user.pw_dir).is_dir():self.skipTest('No existing home')
  repo=Path(__file__).resolve().parents[1];bin=self.root/'bin';bin.mkdir()
  for name in ('system_recovery.py','client_i18n.py','client_en.json'):shutil.copy(repo/'client_agent/desktop'/name,bin/name)
  shutil.copy(repo/'tools/backup/migration.sh',bin/'system-migration.sh')
  text=(repo/'client_agent/desktop/system-recovery.sh').read_text()
  # This fixture runs unprivileged and only selects Cancel, never a restore.
  text=text.replace("[[ $EUID == 0 ]] || { echo 'Mit Administratorfreigabe starten.'; exit 1; }",':')
  (bin/'system-recovery.sh').write_text(text)
  b=migration.layout(self.system,self.root/'backup',self.inv,'alice')
  result=subprocess.run(['bash',str(bin/'system-recovery.sh'),'--https-migration',str(b),'/',user.pw_name],input='0\n',text=True,capture_output=True,timeout=10)
  self.assertEqual(0,result.returncode,result.stdout+result.stderr)
  self.assertIn('HSM_RECOVERY_PROMPT:',result.stdout)
  self.assertIn('Migrationslauf beendet',result.stdout)
 def test_offline_packages_are_read_without_running_source_programs(self):
  from system_stream import offline_packages
  self.put('var/lib/dpkg/status','Package: gimp\nStatus: install ok installed\nVersion: 2.0\nArchitecture: amd64\n\nPackage: removed\nStatus: deinstall ok config-files\n\nPackage: libexample\nStatus: install ok installed\nVersion: 1\nArchitecture: amd64\n')
  self.put('var/lib/apt/extended_states','Package: libexample\nAuto-Installed: 1\n')
  data=offline_packages(self.system)
  self.assertEqual('gimp\n',data['manual-packages']['output'])
  self.assertNotIn('removed',data['packages']['output'])
 def test_running_home_requires_confirmation_and_preserves_client_identity(self):
  if os.getuid()<1000 or not shutil.which('rsync'):self.skipTest('Normal user and rsync required')
  import shlex
  repo=Path(__file__).resolve().parents[1]
  b=self.root/'home-backup';(b/'files/.config/server-manager-client').mkdir(parents=True)
  (b/'files/.config/server-manager-client/config').write_text('source-device')
  (b/'files/document').write_text('restored')
  target=self.root/'target';(target/'.config/server-manager-client').mkdir(parents=True)
  (target/'.config/server-manager-client/config').write_text('target-device')
  base='source '+shlex.quote(str(repo/'tools/backup/migration.sh'))+'\n'
  base+='BACKUP_DIR='+shlex.quote(str(b))+'; SOURCE_HOME='+shlex.quote(str(target))+'; SOURCE_UID='+str(os.getuid())+'; SOURCE_GID='+str(os.getgid())+'; SOURCE_USER=test; LIVE_MODE=false; HSM_HTTPS_MIGRATION=true\n'
  base+='v20_compat(){ V20_SAME=true; }; pgrep(){ return 0; }; RESTORE_EXCLUDES=(--exclude=/.config/server-manager-client/)\n'
  no=subprocess.run(['bash','-c',base+'v20_confirm(){ return 1; }; v20_home'],capture_output=True,text=True)
  self.assertNotEqual(0,no.returncode);self.assertFalse((target/'document').exists())
  yes=subprocess.run(['bash','-c',base+'v20_confirm(){ return 0; }; v20_home'],capture_output=True,text=True)
  self.assertEqual(0,yes.returncode,yes.stdout+yes.stderr)
  self.assertEqual('restored',(target/'document').read_text());self.assertEqual('target-device',(target/'.config/server-manager-client/config').read_text())
 def test_online_work_directory_accepts_local_disk_but_not_network(self):
  with patch.object(migration.gates,'mount_info',return_value={'target':'/','fstype':'ext4'}):
   self.assertEqual(str(self.root),migration.migration_storage(str(self.root)))
  with patch.object(migration.gates,'mount_info',return_value={'target':'/mnt/share','fstype':'nfs'}),self.assertRaises(ValueError):migration.migration_storage(str(self.root))
 def test_additional_data_refuses_running_root(self):
  # Unit test the preflight without granting write permission to the real OS.
  stage=self.root/'stage';stage.mkdir();folder=stage/'backup';folder.mkdir();(stage/'system/data').mkdir(parents=True)
  (stage/'inventory.json').write_text(json.dumps({'selected_mounts':[{'target':'/data'}]}))
  real_lstat=Path.lstat
  def metadata(p):
   st=real_lstat(p)
   from types import SimpleNamespace
   return SimpleNamespace(st_uid=0,st_mode=st.st_mode&~0o022)
  with patch.object(Path,'lstat',metadata),self.assertRaises(ValueError):migration.data_volume(str(folder),'/data','/')
 def test_system_backup_excludes_its_own_restore_work_data(self):
  import system_stream
  self.put('home/alice/System-Restore-example/.hsm-system-restore-work','')
  self.put('home/alice/System-Restore-example/system.zip','do not recurse')
  self.put('var/lib/heimserver-manager-client/migrations/example/system/etc/passwd','old')
  names=list(system_stream.file_names(self.system,{},[{'target':'/','fstype':'ext4'}]))
  self.assertFalse(any('System-Restore-example' in n or '/migrations/' in n for n in names))
  self.assertIn('./home/alice/data',names)
 def archive(self,unsafe=False):
  tar=io.BytesIO()
  with tarfile.open(fileobj=tar,mode='w') as t:
   for name,content in [('etc/passwd',(self.system/'etc/passwd').read_text()),('etc/group','alice:x:1000:\n'),('etc/os-release',self.inv['os_release']),('home/alice/data','hello')]+([('../escape','bad')] if unsafe else []):
    m=tarfile.TarInfo(name);m.uid=os.getuid();m.gid=os.getgid();raw=content.encode();m.size=len(raw);t.addfile(m,io.BytesIO(raw))
  path=self.root/'backup.zip'
  with zipfile.ZipFile(path,'w') as z:z.writestr('files/system.tar',tar.getvalue());z.writestr('files/system-inventory.json',json.dumps(self.inv))
  return path,hashlib.sha256(path.read_bytes()).hexdigest()
 def test_corrupt_archive_rejected_without_extracting(self):
  path,sha=self.archive();stage=self.root/'stage';stage.mkdir()
  with patch.object(migration,'private_stage',return_value=stage),self.assertRaises(ValueError):migration.prepare(path,'0'*64,self.root,'alice')
  self.assertFalse(stage.exists());self.assertFalse((self.root/'escape').exists())
 def test_archive_path_traversal_rejected(self):
  path,sha=self.archive(True);stage=self.root/'stage';stage.mkdir()
  with patch.object(migration,'private_stage',return_value=stage),self.assertRaises(ValueError):migration.prepare(path,sha,self.root,'alice')
  self.assertFalse((self.root/'escape').exists())
 def test_real_tar_to_migration_adapter(self):
  path,sha=self.archive();stage=self.root/'stage';stage.mkdir()
  with patch.object(migration,'private_stage',return_value=stage):b=migration.prepare(path,sha,self.root,'alice')
  self.assertEqual('hello',(b/'files/data').read_text())
  self.assertEqual(sha,json.loads((stage/'provenance.json').read_text())['sha256'])
if __name__=='__main__':unittest.main()
