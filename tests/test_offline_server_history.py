import ast,contextlib,fcntl,hashlib,io,os,shutil,stat,tempfile,time,unittest,uuid
from pathlib import Path
source=(Path(__file__).resolve().parents[1]/'modules/offline_files/__init__.py').read_text()
names={'mutate','lock','fingerprint','mount_id','parent','parts'}
tree=ast.parse(source);tree.body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
import re
ns=dict(globals(),guard=lambda fd:None)
exec(compile(tree,'server_offline.py','exec'),ns)
class History(unittest.TestCase):
 def run_case(self,delete):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);p=root/'report.txt';p.write_bytes(b'old');p.chmod(0o640);os.setxattr(p,'user.test',b'preserve')
   before=p.stat();fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
   try:ns['mutate'](fd,'report.txt',hashlib.sha256(b'old').hexdigest(),io.BytesIO(b'new'),0 if delete else 3,delete,hashlib.sha256(b'new').hexdigest())
   finally:os.close(fd)
   history=list((root/'.hsm-history').glob('*/report.txt'));self.assertEqual(len(history),1)
   self.assertEqual(history[0].read_bytes(),b'old');self.assertEqual(history[0].stat().st_ino,before.st_ino)
   self.assertEqual(history[0].stat().st_mode,before.st_mode);self.assertEqual(os.getxattr(history[0],'user.test'),b'preserve')
   if delete:self.assertFalse(p.exists())
   else:self.assertEqual(p.read_bytes(),b'new')
 def test_delete_preserves_original_inode_and_attributes(self):self.run_case(True)
 def test_replace_preserves_original_inode_and_attributes(self):self.run_case(False)
 def test_symlink_history_rejected(self):
  with tempfile.TemporaryDirectory() as tmp,tempfile.TemporaryDirectory() as outside:
   root=Path(tmp);p=root/'report.txt';p.write_bytes(b'old');(root/'.hsm-history').symlink_to(outside,target_is_directory=True);fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY)
   try:
    with self.assertRaises(OSError):ns['mutate'](fd,'report.txt',hashlib.sha256(b'old').hexdigest(),io.BytesIO(),0,True)
   finally:os.close(fd)
   self.assertEqual(p.read_bytes(),b'old');self.assertEqual(list(Path(outside).iterdir()),[])
if __name__=='__main__':unittest.main()
