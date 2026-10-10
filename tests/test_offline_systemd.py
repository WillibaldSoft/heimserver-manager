import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import offline_systemd as s
class Automount(unittest.TestCase):
 def info(self,target,active='inactive'):
  return dict(mount='test.mount',automount='test.automount',units={'test.mount':dict(ActiveState=active,UnitFileState='static'), 'test.automount':dict(ActiveState='active',UnitFileState='enabled')})
 def test_generated_or_native_inspection(self):
  base=dict(LoadState='loaded',Where='/mnt/shares/Example',ActiveState='active')
  with patch.object(s,'names',return_value=('x.mount','x.automount')),patch.object(s,'properties',side_effect=[base,dict(base,Type='cifs',ForceUnmount='no',LazyUnmount='no')]):self.assertEqual('x.mount',s.inspect(Path('/mnt/shares/Example'))['mount'])
  with patch.object(s,'names',return_value=('x.mount','x.automount')),patch.object(s,'properties',side_effect=[base,dict(base,Type='cifs',ForceUnmount='yes')]):
   with self.assertRaises(ValueError):s.inspect(Path('/mnt/shares/Example'))
 def test_replace_restore_exact_previous_state(self):
  for mount_state in ('active','inactive'):
   with self.subTest(mount_state=mount_state),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);units=root/'units';units.mkdir();target=root/'mount';target.mkdir();local=root/'offline';local.mkdir();(local/'file').write_text('preserved');record=root/'state.json';info=self.info(target,mount_state)
    with patch.object(s,'verify_block'),patch.object(s,'SYSTEM',units),patch.object(s,'fingerprints',return_value={}),patch.object(s,'command') as cmd,patch.object(s,'properties',return_value={'ActiveState':'inactive'}):
     s.replace(target,local,1000,record,info)
     self.assertTrue(target.is_symlink());self.assertEqual('preserved',(target/'file').read_text())
     self.assertIn('ConditionPathExists=!',s.control_path('test.automount').read_text())
     import json
     state=json.loads(record.read_text());cmd.reset_mock();s.restore(target,1000,record,state)
     self.assertFalse(target.is_symlink());self.assertFalse(record.exists());self.assertFalse(s.control_path('test.mount').exists())
     starts=[c.args[-1] for c in cmd.call_args_list if 'start' in c.args]
     self.assertEqual(['test.automount']+(['test.mount'] if mount_state=='active' else []),starts)
     self.assertTrue((local/'file').exists())
 def test_busy_mount_rolls_back_controls_without_replacing_path(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);units=root/'units';units.mkdir();target=root/'mount';target.mkdir();local=root/'offline';local.mkdir();record=root/'state.json'
   with patch.object(s,'verify_block'),patch.object(s,'SYSTEM',units),patch.object(s,'fingerprints',return_value={}),patch.object(s,'command'),patch.object(s,'stop',side_effect=ValueError('busy')):
    with self.assertRaises(ValueError):s.replace(target,local,1000,record,self.info(target))
    self.assertFalse(target.is_symlink());self.assertFalse(record.exists());self.assertFalse(s.control_path('test.automount').exists())
 def test_changed_dropin_prevents_restore(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);units=root/'units';units.mkdir();target=root/'mount';target.mkdir();local=root/'offline';local.mkdir();record=root/'state.json'
   with patch.object(s,'verify_block'),patch.object(s,'SYSTEM',units),patch.object(s,'fingerprints',return_value={}),patch.object(s,'command'),patch.object(s,'properties',return_value={'ActiveState':'inactive'}):
    s.replace(target,local,1000,record,self.info(target));s.control_path('test.mount').write_text('changed')
    import json
    with self.assertRaises(ValueError):s.restore(target,1000,record,json.loads(record.read_text()))
    self.assertTrue(target.is_symlink())

 def test_later_condition_reset_is_rejected(self):
  state=dict(mount='x.mount',automount='x.automount',marker='/root/offline-marker')
  text='[Unit]\nConditionPathExists=!/root/offline-marker\n'
  with patch.object(s,'command',return_value=text):s.verify_block(state)
  with patch.object(s,'command',return_value=text+'ConditionPathExists=\n'):
   with self.assertRaises(ValueError):s.verify_block(state)
