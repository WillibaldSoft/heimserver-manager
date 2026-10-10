import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from modules import offline_files as offline
from modules.offline_files import mounts
class MountedFolders(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);(self.root/'Downloads').mkdir()
  self.mount=dict(target=str(self.root),source='/dev/sdz1',uuid='example-uuid',fstype='ext4')
 def test_mount_and_child_are_selectable(self):
  (self.root/'link').symlink_to(self.root/'Downloads',target_is_directory=True)
  result=mounts.choices([self.mount]);self.assertNotIn(str(self.root/'Downloads'),result);self.assertIn(str(self.root),result);self.assertNotIn(str(self.root/'link'),result)
 def test_missing_or_replaced_mount_is_rejected(self):
  with patch.object(mounts,'mounts',return_value=[self.mount]):
   row=offline.add_grants([],[str(self.root/'Downloads')],'',[1],[1])[0]
   with offline.rootfd(row):pass
  for mounted in ([],[dict(self.mount,uuid='other')]):
   with patch.object(mounts,'mounts',return_value=mounted):
    with self.assertRaises(ValueError):
     with offline.rootfd(row):pass
 def test_uuid_survives_device_number_change(self):
  with patch.object(mounts,'mounts',return_value=[self.mount]):row=offline.add_grants([],[str(self.root/'Downloads')],'',[1],[1])[0]
  row['identity'][0]+=1
  with patch.object(mounts,'mounts',return_value=[dict(self.mount,source='/dev/sda1')]):
   with offline.rootfd(row):pass
