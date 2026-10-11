import os,sys,io,tarfile,tempfile,unittest,zipfile,json,hashlib,contextlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'client_agent/desktop'))
import system_restore as m

def tar_data(extra=()):
 b=io.BytesIO()
 with tarfile.open(fileobj=b,mode='w') as t:
  for name,data in [('etc/os-release',b'ID=test'),('etc/passwd',b'test:x:1000:1000::/home/test:/bin/bash'),('etc/fstab',b'OLD DISK'),('etc/config',b'config')]:
   item=tarfile.TarInfo('./'+name);item.size=len(data);item.mode=0o640;item.uid=os.getuid();item.gid=os.getgid();t.addfile(item,io.BytesIO(data))
  for item in extra:t.addfile(item)
 return b.getvalue()
class Restore(unittest.TestCase):
 def test_safe_archive(self):
  with tempfile.TemporaryDirectory() as tmp:
   size,count=m.inspect(io.BytesIO(tar_data()),Path(tmp));self.assertEqual(4,count);self.assertGreater(size,0)
 def test_traversal_and_special(self):
  for name,kind in [('../outside',tarfile.REGTYPE),('/outside',tarfile.REGTYPE),('dev/device',tarfile.CHRTYPE)]:
   item=tarfile.TarInfo(name);item.type=kind
   with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):m.inspect(io.BytesIO(tar_data([item])),Path(tmp))
 def test_archive_link_parent(self):
  a=tarfile.TarInfo('escape');a.type=tarfile.SYMTYPE;a.linkname='/etc'
  b=tarfile.TarInfo('escape/file')
  with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):m.inspect(io.BytesIO(tar_data([a,b])),Path(tmp))
 def test_target_symlink_parent(self):
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp);(target/'etc').symlink_to('/etc')
   with self.assertRaises(ValueError):m.inspect(io.BytesIO(tar_data()),target)
 def test_hardlink_outside_archive(self):
  a=tarfile.TarInfo('evil');a.type=tarfile.LNKTYPE;a.linkname='missing'
  with tempfile.TemporaryDirectory() as tmp,self.assertRaises(ValueError):m.inspect(io.BytesIO(tar_data([a])),Path(tmp))
 def test_roundtrip_preserves_fstab_and_requires_confirmation(self):
  with tempfile.TemporaryDirectory() as tmp:
   cache=Path(tmp);target=cache/'target';target.mkdir();(target/'etc').mkdir();(target/'etc/fstab').write_text('TARGET DISK')
   archive=cache/'backup.zip'
   with zipfile.ZipFile(archive,'w') as z:
    z.writestr('hsm-backup.json',json.dumps({'scope':'linux-system-tar-v1'}));z.writestr('files/system.tar',tar_data())
   sha=hashlib.sha256(archive.read_bytes()).hexdigest()
   with patch.object(m.gates,'storage',return_value=str(cache)),patch.object(m,'target_check',return_value=(target,target.stat().st_dev)),patch.object(m.os,'sync'),contextlib.redirect_stdout(io.StringIO()):
    with patch.object(sys,'stdin',io.StringIO('ABBRECHEN\n')),self.assertRaises(ValueError):m.run(str(archive),sha,str(target),str(cache))
    self.assertFalse((target/'etc/config').exists())
    with patch.object(sys,'stdin',io.StringIO('WIEDERHERSTELLEN\n')):m.run(str(archive),sha,str(target),str(cache))
    self.assertEqual('TARGET DISK',(target/'etc/fstab').read_text());self.assertEqual('config',(target/'etc/config').read_text())
    self.assertEqual(0o640,(target/'etc/config').stat().st_mode&0o777)
 def test_requires_live(self):
  with patch.object(m.gates,'live',return_value=False),self.assertRaisesRegex(ValueError,'Live-USB'):m.target_check('/mnt/linux','/media/backup')
