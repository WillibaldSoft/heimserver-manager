import json,os,stat,struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from client_agent.desktop import user_ids as ids

class UserIDs(unittest.TestCase):
    def setUp(self):
        self.plan=dict(name='alice',home='/home/alice',group='alice',old_uid=1000,old_gid=1000,uid=2000,gid=2001)
    def acl(self,*entries):return struct.pack('<I',2)+b''.join(struct.pack('<HHI',*r) for r in entries)
    def test_acl_maps_only_named_ids_preserves_permissions(self):
        acl=self.acl((1,7,0xffffffff),(2,4,1000),(8,5,1000),(16,5,0xffffffff),(32,0,0xffffffff))
        result=ids.acl_map(acl,self.plan,True)
        self.assertEqual(result,self.acl((1,7,0xffffffff),(2,4,2000),(8,5,2001),(16,5,0xffffffff),(32,0,0xffffffff)))
    def test_acl_conflict_and_unknown_format_refused(self):
        with self.assertRaises(ValueError):ids.acl_map(self.acl((2,4,2000)),self.plan,True)
        with self.assertRaises(ValueError):ids.acl_map(b'bad',self.plan)
    def test_unchanged_ids_do_not_conflict(self):
        acl=self.acl((2,4,1000));self.assertEqual(acl,ids.acl_map(acl,dict(self.plan,uid=1000,gid=1000),True))
    def test_system_ids_refused_before_account_lookup(self):
        for uid,gid in [(0,2000),(2000,0),(True,2000),(60000,2000)]:
            with self.assertRaises(ValueError):ids.account('root',uid,gid)
    def accounts(self,others=(),members=()):
        u=NS(pw_name='alice',pw_uid=1000,pw_gid=1000,pw_dir='/home/alice')
        g=NS(gr_name='alice',gr_gid=1000,gr_mem=list(members))
        patches=[patch.object(ids.pwd,'getpwnam',return_value=u),patch.object(ids.pwd,'getpwall',return_value=[u,*others]),patch.object(ids.grp,'getgrgid',return_value=g),patch.object(ids.grp,'getgrall',return_value=[g]),patch.object(Path,'read_text',return_value='alice:x:1000:1000::/home/alice:/bin/bash'),patch.object(Path,'is_dir',return_value=True),patch.object(Path,'is_symlink',return_value=False),patch.object(ids,'run',return_value='ext4')]
        for p in patches:p.start();self.addCleanup(p.stop)
    def test_shared_group_refused(self):
        self.accounts(members=['bob'])
        with self.assertRaisesRegex(ValueError,'shared'):ids.account('alice',2000,2001)
    def test_target_uid_conflict_refused(self):
        self.accounts(others=[NS(pw_name='bob',pw_uid=2000,pw_gid=3000)])
        with self.assertRaisesRegex(ValueError,'already'):ids.account('alice',2000,2001)
    def test_network_home_refused(self):
        self.accounts()
        with patch.object(ids,'run',return_value='nfs4'),self.assertRaisesRegex(ValueError,'local Linux'):ids.account('alice',2000,2001)
    def test_plan_keeps_local_name(self):
        self.accounts();self.assertEqual(self.plan,ids.account('alice',2000,2001))
    def test_journal_metadata_is_restartable_without_real_chown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);f=root/'file';f.write_text('unchanged')
            st=f.stat();plan=dict(self.plan,old_uid=st.st_uid,old_gid=st.st_gid)
            with patch.object(ids,'BASE',root/'journal'),patch.object(ids,'paths',return_value=iter([f])),patch.object(ids,'attr',return_value=None):
                ids.BASE.mkdir();ids.inventory(dict(plan,volumes=[]))
                with patch.object(ids.os,'chown') as chown,patch.object(ids.os,'chmod'),patch.object(ids.os,'setxattr'):
                    ids.apply_metadata(plan);ids.apply_metadata(plan)
                    self.assertEqual(1,chown.call_count);self.assertEqual('unchanged',f.read_text())
    def test_changed_inode_stops_before_chown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);f=root/'file';f.write_text('before');st=f.stat();plan=dict(self.plan,old_uid=st.st_uid,old_gid=st.st_gid)
            with patch.object(ids,'BASE',root/'journal'),patch.object(ids,'paths',return_value=iter([f])),patch.object(ids,'attr',return_value=None):
                ids.BASE.mkdir();ids.inventory(dict(plan,volumes=[]));f.rename(root/'old');f.write_text('replacement')
                with patch.object(ids.os,'chown') as chown,self.assertRaisesRegex(ValueError,'changed'):
                    ids.apply_metadata(plan)
                chown.assert_not_called()
    def test_cannot_cancel_started_job(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(ids,'secure'):
            with patch.object(ids,'BASE',Path(tmp)),patch.object(ids,'run') as run:
                (Path(tmp)/'plan.json').write_text(json.dumps({'phase':'metadata'}))
                with self.assertRaisesRegex(ValueError,'started'):ids.cancel()
                run.assert_not_called()
    def test_scheduling_never_changes_ids_or_starts_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);unit=root/'heimserver-manager-user-ids.service';drop=root/'drop'/'hsm-user-ids.conf'
            with patch.object(ids,'BASE',root/'job'),patch.object(ids,'UNIT',unit),patch.object(ids,'DROP',drop),patch.object(ids,'IDENTITIES',root/'identities'),patch.object(ids,'secure'),patch.object(ids,'mounts',return_value=[dict(path='/',uuid='test',fsroot='/')]),patch.object(ids,'run') as run:
                ids.schedule(dict(self.plan))
                calls=[c.args for c in run.call_args_list]
                self.assertEqual([('systemctl','daemon-reload'),('systemctl','enable',unit.name)],calls)
                self.assertIn('Before=sysinit.target',unit.read_text())
                self.assertEqual('scheduled',json.loads((ids.BASE/'plan.json').read_text())['phase'])
                self.assertIn('Requires='+unit.name,drop.read_text())
                ids.cancel();self.assertFalse(unit.exists());self.assertFalse(drop.exists())
    def test_retained_identity_is_carried_forward(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);identity=root/'identities';identity.mkdir()
            (identity/'1000').write_text(json.dumps(dict(name='alice',home='/home/alice',local_user='a'*64)))
            with patch.object(ids,'BASE',root/'job'),patch.object(ids,'UNIT',root/'test.service'),patch.object(ids,'DROP',root/'drop'/'test.conf'),patch.object(ids,'IDENTITIES',identity),patch.object(ids,'secure'),patch.object(ids,'mounts',return_value=[]),patch.object(ids,'run'):
                ids.schedule(dict(self.plan))
                self.assertEqual('a'*64,json.loads((ids.BASE/'plan.json').read_text())['local_user'])
    def test_readonly_comparison_needs_no_privileges(self):
        with patch.object(ids.pwd,'getpwuid',return_value=NS(pw_name='local',pw_uid=1000,pw_gid=1001)),patch.object(ids,'run') as run:
            same=ids.compare(dict(uid=1000,gid=1001))
            self.assertTrue(same['matches'])
            different=ids.compare(dict(uid=1000,gid=2000))
            self.assertFalse(different['matches']);self.assertEqual('local',different['name'])
            run.assert_not_called()
    def test_comparison_rejects_unusable_server_identity(self):
        for identity in ({},{'uid':True,'gid':1000},{'uid':0,'gid':1000}):
            with self.assertRaises(ValueError):ids.compare(identity)
    def test_identity_error_does_not_report_server_offline(self):
        from client_agent.desktop import core
        import sys
        probe=NS(status=200,close=lambda:None)
        identity=NS(headers=lambda:(_ for _ in ()).throw(PermissionError('private directory')))
        with patch.object(core,'load',return_value=dict(SERVER_URL='https://server.invalid',TOKEN='test')),patch.object(core.urllib.request,'build_opener',return_value=NS(open=lambda *a,**k:probe)),patch.object(core,'systemctl',return_value='active'),patch.dict(sys.modules,device_identity=identity):
            state=core.status()
        self.assertTrue(state['online']);self.assertFalse(state['connected'])
        self.assertNotEqual(core.tr('Server nicht erreichbar'),state['message'])
    def test_identity_marker_readable_under_private_boot_umask(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'job';base.mkdir();identities=root/'identities'
            plan=dict(self.plan,phase='metadata',volumes=[],local_user='a'*64)
            (base/'plan.json').write_text(json.dumps(plan))
            with patch.object(ids,'BASE',base),patch.object(ids,'UNIT',root/'test.service'),patch.object(ids,'DROP',root/'test.conf'),patch.object(ids,'IDENTITIES',identities),patch.object(ids,'secure'),patch.object(ids,'mounts',return_value=[]),patch.object(ids,'apply_metadata'),patch.object(ids,'run'),patch.object(Path,'iterdir',return_value=iter([])),patch.object(ids.pwd,'getpwnam',return_value=NS(pw_uid=2000,pw_gid=2001)),patch.object(ids.grp,'getgrnam',return_value=NS(gr_gid=2001)),patch.object(ids.pwd,'getpwall',return_value=[]),patch.object(ids.grp,'getgrall',return_value=[]):
                old=os.umask(0o077)
                try:ids.apply()
                finally:os.umask(old)
            self.assertEqual(0o755,identities.stat().st_mode&0o777)
            self.assertEqual(0o644,(identities/'2000').stat().st_mode&0o777)
    def ui_module(self):
        import importlib.util,sys
        from unittest.mock import Mock
        spec=importlib.util.spec_from_file_location('hsm_ids_ui_test',Path(ids.__file__).with_name('user_ids_ui.py'))
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'gi.repository':NS(Gtk=Mock(),GLib=Mock())}):spec.loader.exec_module(module)
        return module
    def test_uid_check_opens_login_if_missing(self):
        ui=self.ui_module()
        with patch.object(ui.backup,'ACCOUNT',None),patch.object(ui,'login') as login,patch.object(ui,'elevated') as elevated:
            app=NS(busy=False);ui.check(app);login.assert_called_once_with(app);elevated.assert_not_called()
    def test_expired_uid_login_is_directly_reachable(self):
        import urllib.error
        from unittest.mock import Mock
        ui=self.ui_module();opener=Mock();opener.open.side_effect=urllib.error.HTTPError('https://server.invalid',401,'expired',{},None)
        app=NS(busy=False,run_action=lambda fn,on_success:(fn(),on_success()))
        with patch.object(ui.backup,'ACCOUNT',('https://server.invalid',opener,{})),patch.object(ui.backup,'account_logout') as logout,patch.object(ui.core,'load',return_value={}),patch.object(ui.core,'validate',return_value={'SERVER_URL':'https://server.invalid'}),patch.object(ui,'login') as login:
            ui.check(app);logout.assert_called_once();login.assert_called_once_with(app)
