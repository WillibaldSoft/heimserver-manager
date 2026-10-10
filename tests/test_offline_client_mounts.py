import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import offline_mounts as m
class Mounts(unittest.TestCase):
 def test_active_and_fstab(self):
  rows=m.discover('12 1 0:1 / /mnt/shares/Example rw - cifs //server/Andi rw\n13 1 0:2 / /media/My\\040Files rw - nfs server:/files rw','//server/Downloads /SVL/Downloads cifs noauto 0 0')
  self.assertEqual(3,len(rows));self.assertTrue(next(r for r in rows if r['target']=='/mnt/shares/Example')['active']);self.assertFalse(next(r for r in rows if r['target']=='/SVL/Downloads')['active']);self.assertIn('/media/My Files',[r['target'] for r in rows])
 def test_network_source_never_destination(self):
  with patch.object(m.Path,'resolve',lambda p:p),patch.object(m,'discover',return_value=[dict(target='/mnt/shares/Example')]):
   for path in ('/mnt/shares/Example','/mnt/shares/Example/docs','/mnt/shares'):
    with self.assertRaises(ValueError):m.validate_local(path)
   self.assertEqual(Path('/tmp/offline'),m.validate_local('/tmp/offline'))
  with patch.object(m.Path,'resolve',lambda p:p),patch.object(m,'discover',return_value=[]):
   with self.assertRaises(ValueError):m.validate_local('/mnt/shares/Example/docs',dict(target='/mnt/shares/Example'))
 def test_only_simple_exact_fstab_entry_can_be_replaced(self):
  import offline_mount_admin as admin
  target=Path('/mnt/shares/Example')
  entry='//server/Andi /mnt/shares/Example cifs credentials=/etc/smb-secret 0 0\n'
  self.assertEqual(entry,admin.matching_line(entry,target)[2])
  for text in ('',entry+entry,entry.replace('credentials=/etc/smb-secret','x-systemd.automount'),entry.replace(' cifs ',' ext4 ')):
   with self.assertRaises(ValueError):admin.matching_line(text,target)
 def test_local_alias_does_not_block_its_offline_folder(self):
  import tempfile
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);local=root/'offline';local.mkdir();link=root/'mount';link.symlink_to(local)
   with patch.object(m,'discover',return_value=[]):self.assertEqual(local,m.validate_local(local,dict(target=str(link))))
 def test_switch_and_restore_leave_offline_files_intact(self):
  import tempfile,os,sys
  import offline_mount_admin as a
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);target=root/'mount';target.mkdir();local=root/'offline';local.mkdir();(local/'file').write_text('retained')
   table=root/'fstab';original='//server/Andi '+str(target)+' cifs defaults 0 0\n';table.write_text(original)
   uid=os.getuid() or 1000
   with patch.object(a.offline_systemd,'inspect',return_value=None),patch.object(a,'STATE',root/'state'),patch.object(a,'FSTAB',table),patch.object(a,'trusted_parent'),patch.object(a,'validate_local',return_value=local),patch.object(a.os,'geteuid',return_value=0),patch.dict(os.environ,{'PKEXEC_UID':str(uid)}),patch.object(a,'discover',return_value=[dict(target=str(target),source='//server/Andi',active=True)]),patch.object(a,'atomic',side_effect=table.write_text),patch.object(a,'run'):
    if local.stat().st_uid!=uid:return self.skipTest('requires non-root fixture owner')
    with patch.object(sys,'argv',['helper','replace',str(target),str(local)]):a.main()
    self.assertTrue(target.is_symlink());self.assertEqual('retained',(target/'file').read_text());self.assertIn('# HSM-OFFLINE',table.read_text())
    with patch.object(sys,'argv',['helper','restore',str(target),str(local)]):a.main()
    self.assertFalse(target.is_symlink());self.assertTrue(target.is_dir());self.assertEqual(original,table.read_text());self.assertEqual('retained',(local/'file').read_text())
 def test_destination_suggestion_is_stable_separate_and_reuses_existing(self):
  with patch.object(m.Path,'resolve',lambda p:p),patch.object(m,'discover',return_value=[dict(target='/mnt/shares/Example')]),patch.object(m.Path,'home',return_value=Path('/home/example')):
   a=m.suggested_destination('one','Andi',source_mount=dict(target='/mnt/shares/Example'))
   self.assertEqual(Path('/mnt/shares/Offline/Example'),a)
   self.assertEqual(Path('/SVL/Offline/Downloads'),m.suggested_destination('downloads','Downloads',source_mount=dict(target='/SVL/Downloads')))
   self.assertEqual(Path('/mnt/nested/Offline/share'),m.suggested_destination('nested','share',source_mount=dict(target='/mnt/nested/share'))) 
   self.assertNotEqual(a,m.suggested_destination('two','Andi'))
   self.assertTrue(str(m.suggested_destination('one','Andi')).startswith('/home/example/Offline-Dateien/Andi-'))
   self.assertEqual(Path('/tmp/existing'),m.suggested_destination('one','Andi','/tmp/existing'))
   with self.assertRaises(ValueError):m.suggested_destination('one','Andi','/mnt/shares/Example')

class PrepareFolder(unittest.TestCase):
 def test_create_and_repair_only_directory(self):
  import tempfile,os,stat,types
  import offline_mount_admin as admin
  with tempfile.TemporaryDirectory(dir=Path.cwd()) as base:
   target=Path(base)/'offline';user=types.SimpleNamespace(pw_dir=base,pw_gid=os.getgid())
   real_stat=os.fstat
   def safe_stat(fd):
    values=list(real_stat(fd));values[0]&=~0o022;values[4]=os.getuid();return os.stat_result(values)
   with patch.object(admin.os,'fstat',side_effect=safe_stat),patch.object(admin.pwd,'getpwuid',return_value=user),patch.object(admin,'validate_local',side_effect=lambda p:p),patch.object(admin.os,'fchown') as chown:
    admin.prepare_folder(target,os.getuid())
    self.assertTrue(target.is_dir());chown.assert_called_once()
    child=target/'existing';child.write_text('unchanged');child.chmod(0o400);target.chmod(0o500)
    admin.prepare_folder(target,os.getuid())
    self.assertEqual(0o700,stat.S_IMODE(target.stat().st_mode))
    self.assertEqual(0o400,stat.S_IMODE(child.stat().st_mode));self.assertEqual('unchanged',child.read_text())
    link=Path(base)/'link';link.symlink_to(target)
    with self.assertRaises(OSError):admin.prepare_folder(link,os.getuid())
 def test_system_folder_rejected(self):
  import offline_mount_admin as admin,os
  with self.assertRaises(ValueError):admin.prepare_folder(Path('/etc/new-folder'),os.getuid())
