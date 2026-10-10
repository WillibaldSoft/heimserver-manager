import sys,unittest,io,os,hashlib,tempfile,stat
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import offline_smb as m
class SMB(unittest.TestCase):
 def writer(self):
  w=object.__new__(m.Writer);w.host='server.example';w.meta={'share':'Docs','user':'test'};w.prefix=['one'];w.ctx=Mock();return w
 def test_url_and_traversal(self):
  w=self.writer();self.assertEqual('smb://server.example/Docs/one/a%20b.txt',w.url('a b.txt'))
  for value in ('../escape','one/../../outside','a\\b','/abs'):
   with self.assertRaises(ValueError):w.url(value)
 def test_keyring_password_never_in_arguments(self):
  with patch.object(m,'attributes',return_value=('host',['application','test'])),patch.object(m.subprocess,'run',return_value=Mock(returncode=0,stdout='')) as run:
   m.password({},'private-test-password');self.assertNotIn('private-test-password',str(run.call_args.args));self.assertEqual('private-test-password',run.call_args.kwargs['input'])
 def test_conflict_never_opens_for_writing(self):
  w=self.writer()
  with patch.object(w,'revision',return_value='changed'):
   with self.assertRaises(ValueError):w.mutate('file','old',io.BytesIO(b'new'),sha='new')
  w.ctx.open.assert_not_called()
 def test_existing_file_is_not_replaced_and_history_precedes_truncation(self):
  w=self.writer();h=hashlib.sha256(b'new').hexdigest();dest=Mock();dest.write.side_effect=lambda data:len(data);w.ctx.open.return_value=dest
  with tempfile.TemporaryDirectory() as tmp,patch.object(m.Path,'home',return_value=Path(tmp)),patch.object(w,'parents'),patch.object(w,'copy') as copy,patch.object(w,'revision',side_effect=['old','old','old',h]):
   self.assertEqual(h,w.mutate('file','old',io.BytesIO(b'new'),sha=h)['sha']);copy.assert_called_once()
   w.ctx.rename.assert_not_called();self.assertTrue(any(c.args[1]&os.O_TRUNC for c in w.ctx.open.call_args_list));self.assertEqual([],list(Path(tmp).rglob('smb-recovery-*.json')))
 def test_failed_write_retains_recovery_record(self):
  w=self.writer();dest=Mock();dest.write.side_effect=OSError('connection lost');w.ctx.open.return_value=dest
  with tempfile.TemporaryDirectory() as tmp,patch.object(m.Path,'home',return_value=Path(tmp)),patch.object(w,'parents'),patch.object(w,'copy'),patch.object(w,'revision',side_effect=['old','old','old']):
   with self.assertRaises(ValueError):w.mutate('file','old',io.BytesIO(b'new'),sha='new')
   self.assertEqual(1,len(list(Path(tmp).rglob('smb-recovery-*.json'))));w.ctx.unlink.assert_not_called()
 def test_new_file_never_overwrites_existing_file(self):
  w=self.writer();dest=Mock();dest.write.side_effect=lambda data:len(data);w.ctx.open.return_value=dest;h=hashlib.sha256(b'new').hexdigest()
  with tempfile.TemporaryDirectory() as tmp,patch.object(m.Path,'home',return_value=Path(tmp)),patch.object(w,'parents'),patch.object(w,'revision',side_effect=[None,h]):
   w.mutate('new','',io.BytesIO(b'new'),sha=h);self.assertTrue(w.ctx.open.call_args.args[1]&os.O_EXCL)
 def test_backup_acl_mismatch_prevents_copying_data(self):
  w=self.writer();src=Mock();dst=Mock();w.ctx.open.side_effect=[src,dst];w.ctx.getxattr.side_effect=['old-acl','different-acl']
  with self.assertRaises(ValueError):w.copy('file','history')
  src.read.assert_not_called();dst.write.assert_not_called()
 def test_write_permission_denied_does_not_backup_or_truncate(self):
  w=self.writer();w.ctx.open.side_effect=PermissionError('denied')
  with patch.object(w,'parents'),patch.object(w,'revision',return_value='old'),patch.object(w,'copy') as copy:
   with self.assertRaises(PermissionError):w.mutate('file','old',io.BytesIO(b'new'),sha='new')
   copy.assert_not_called();self.assertEqual(os.O_WRONLY,w.ctx.open.call_args.args[1])
 def test_changed_file_during_backup_not_overwritten(self):
  w=self.writer()
  with patch.object(w,'parents'),patch.object(w,'copy'),patch.object(w,'revision',side_effect=['old','old','changed']):
   with self.assertRaises(ValueError):w.mutate('file','old',io.BytesIO(b'new'),sha='new')
  self.assertFalse(any(c.args[1]&os.O_TRUNC for c in w.ctx.open.call_args_list))
