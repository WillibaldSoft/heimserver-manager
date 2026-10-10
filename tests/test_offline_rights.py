import json,os,pwd,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from modules.offline_files import rights,scope,rootfd,worker,dispatch
class Rights(unittest.TestCase):
 def setUp(self):
  self.user=pwd.getpwuid(os.getuid())
 def test_linux_only_and_smb_denial(self):
  with patch.object(rights.configuration,'smb_shares',return_value=[]),patch.object(rights.configuration,'nfs_exports',return_value=[]):self.assertTrue(rights.permission('/data/files',self.user,'192.0.2.1'))
  with patch.object(rights.configuration,'smb_shares',return_value=[dict(name='Docs',config={'path':'/data'})]),patch.object(rights.helpers,'run',return_value=dict(ok=True,out='Account Flags: [U ]')),patch.object(rights.access,'effective_configs',return_value={'docs':{'read only':'yes','invalid users':self.user.pw_name}}):
   with self.assertRaises(ValueError):rights.permission('/data/files',self.user,'192.0.2.1')
 @patch('modules.offline_files.samba_acl.check_share')
 def test_smb_readonly_and_unknown(self,check_share):
  with patch.object(rights.configuration,'smb_shares',return_value=[dict(name='Docs',config={'path':'/data'})]),patch.object(rights.configuration,'nfs_exports',return_value=[]),patch.object(rights.helpers,'run',return_value=dict(ok=True,out='Account Flags: [U ]')):
   with patch.object(rights.access,'effective_configs',return_value={'docs':{'read only':'yes','log file':'/var/log/samba/log.%m','passwd program':'/usr/bin/passwd %u'}}):self.assertFalse(rights.permission('/data/files',self.user,'192.0.2.1'))
   with patch.object(rights.access,'effective_configs',return_value={'docs':{'force user':'root'}}):
    with self.assertRaises(ValueError):rights.permission('/data/files',self.user,'192.0.2.1')
 def test_nfs_client_readonly_and_squash(self):
  with patch.object(rights.configuration,'smb_shares',return_value=[]):
   with patch.object(rights.configuration,'nfs_exports',return_value=[dict(path='/data',clients='192.0.2.0/24(ro,sync,root_squash)')]):
    self.assertFalse(rights.permission('/data/files',self.user,'192.0.2.1'))
    with self.assertRaises(ValueError):rights.permission('/data/files',self.user,'198.51.100.1')
   with patch.object(rights.configuration,'nfs_exports',return_value=[dict(path='/data',clients='192.0.2.0/24(rw,all_squash)')]):
    with self.assertRaises(ValueError):rights.permission('/data/files',self.user,'192.0.2.1')
 def test_emergency_account_not_linux_user(self):
  con=SimpleNamespace(execute=lambda *args:SimpleNamespace(fetchone=lambda:{'principal':json.dumps(dict(kind='local',name='ADMIN'))}),close=lambda:None)
  with self.assertRaises(ValueError):rights.identity(SimpleNamespace(db=lambda:con),{'id':1})
 def test_subfolder_browser_cannot_escape(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'one'/'two').mkdir(parents=True);(p/'link').symlink_to('/tmp',target_is_directory=True);st=p.stat();row=dict(path=tmp,identity=[st.st_dev,st.st_ino],id='grant')
   with rootfd(row) as fd:
    listing=scope.browse(fd,'grant','',False);self.assertEqual(['one'],[v['name'] for v in listing['folders']])
    gid=listing['folders'][0]['id'];self.assertEqual(('grant','one'),scope.split(gid))
    sub=scope.open_sub(fd,'one/two');os.close(sub)
    with self.assertRaises((ValueError,OSError)):scope.open_sub(fd,'../outside')
    with self.assertRaises((ValueError,OSError)):scope.open_sub(fd,'link')
 @patch('modules.offline_files.rights.uses_samba',return_value=False)
 def test_worker_uses_explicit_os_identity(self,uses_samba):
  with patch.object(dispatch.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr=b'{"error":"denied"}')) as run:
   with self.assertRaises(ValueError):dispatch.invoke(dict(action='scan'),self.user)
   self.assertEqual(run.call_args.kwargs['user'],self.user.pw_uid);self.assertEqual(run.call_args.kwargs['group'],self.user.pw_gid)
   self.assertEqual(run.call_args.kwargs['extra_groups'],os.getgrouplist(self.user.pw_name,self.user.pw_gid))
 @patch('modules.offline_files.samba_acl.check_share')
 def test_smb_route_does_not_enable_https_writes_or_override_nfs(self,check_share):
  shares=[dict(name='Docs',config={'path':'/data'})]
  with patch.object(rights.configuration,'smb_shares',return_value=shares),patch.object(rights.configuration,'nfs_exports',return_value=[]),patch.object(rights.helpers,'run',return_value=dict(ok=True,out='Account Flags: [U ]')),patch.object(rights.access,'effective_configs',return_value={'docs':{'read only':'no'}}):
   self.assertFalse(rights.permission('/data/files',self.user,'192.0.2.1'))
   route=rights.smb_target('/data/files',self.user,'192.0.2.1');self.assertEqual('Docs',route['share']);self.assertEqual('files',route['path']);self.assertEqual(self.user.pw_name,route['user'])
   with patch.object(rights.configuration,'nfs_exports',return_value=[dict(path='/data',clients='192.0.2.0/24(ro,sync)')]):self.assertIsNone(rights.smb_target('/data/files',self.user,'192.0.2.1'))
