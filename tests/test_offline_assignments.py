import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from modules import offline_files as api
from modules.offline_files import mounts
class Assignments(unittest.TestCase):
 def test_independent_clients_and_shared_folder(self):
  rows=[dict(id='one',path='/data/one',clients=[1,2],write=False),dict(id='two',path='/data/two',clients=[2],write=True)]
  old=copy.deepcopy(rows)
  changed=api.assign_client(rows,['/data/two'],1,[1,2],['/data/one','/data/two'])
  self.assertEqual(rows,old);self.assertEqual(changed[0]['clients'],[2]);self.assertEqual(changed[1]['clients'],[2,1]);self.assertEqual(changed[1]['id'],'two')
  cleared=api.assign_client(changed,[],1,[1,2],[]);self.assertEqual([r['clients'] for r in cleared],[[2],[2]])
 def test_disallow_deep_or_unknown_client(self):
  for client,paths in [(3,['/data/one']),(1,['/data/one/deeper'])]:
   with self.assertRaises(ValueError):api.assign_client([],paths,client,[1,2],['/data/one'])
 def test_preserve_existing_deeper_grant(self):
  row=dict(id='one',path='/data/one/deep',clients=[1],write=False)
  self.assertEqual(api.assign_client([row],[row['path']],1,[1],[]),[row])
 def test_no_directory_expansion(self):
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp);(p/'child'/'deep').mkdir(parents=True)
   row=dict(target=temp,fstype='ext4')
   self.assertEqual(mounts.choices([row]),[temp])
