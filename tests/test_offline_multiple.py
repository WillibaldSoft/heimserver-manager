import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from modules import offline_files as server
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import offline
class Multiple(unittest.TestCase):
 def test_server_many_atomic_and_separate(self):
  with tempfile.TemporaryDirectory() as tmp:
   a=Path(tmp)/'a';b=Path(tmp)/'b';a.mkdir();b.mkdir()
   rows=server.add_grants([],[str(a),str(b)],'Docs',[1],[1],True)
   self.assertEqual(2,len(rows));self.assertNotEqual(rows[0]['id'],rows[1]['id']);self.assertTrue(all(r['write'] for r in rows))
   (a/'nested').mkdir()
   original=[]
   with self.assertRaises(ValueError):server.add_grants(original,[str(a),str(a/'nested')],'',[1],[1])
   self.assertEqual([],original)
 def test_client_many_preserves_and_prevents_overlap(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(offline,'ROOT',Path(tmp)/'config'):
   root=Path(tmp);existing=dict(id='a',name='A',local=str(root/'existing'),write=True,interval=15,limit_gib=25)
   offline.save_config([existing]);grants=[dict(id='a',name='Docs',write=True),dict(id='b',name='Docs',write=True),dict(id='c',name='Docs',write=True)]
   rows=offline.configure_many(grants,['a','b','c'],root/'Offline')
   self.assertEqual(existing,rows[0]);self.assertFalse(rows[1]['write']);self.assertEqual(0,rows[1]['interval']);self.assertNotEqual(rows[1]['local'],rows[2]['local'])
   self.assertEqual(3,len(offline.config()))
   offline.configure_many(grants,['b','c'],root/'Other');self.assertEqual(rows,offline.config())
   with self.assertRaises(offline.core.Error):offline.configure_many([dict(id='d',name='X')],['d'],Path(existing['local'])/'nested')
   self.assertEqual(rows,offline.config())
 def test_sequential_continues_and_validates_first(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(offline,'ROOT',Path(tmp)):
   offline.save_config([dict(id='a',name='A'),dict(id='b',name='B')]);calls=[]
   def run(row,progress):
    calls.append(row['id'])
    if row['id']=='a':raise OSError('unavailable')
    return 'done'
   with patch.object(offline,'_sync',side_effect=run):
    value=offline.sync_many(['a','b']);self.assertEqual(['a','b'],calls);self.assertIn('unavailable',value);self.assertIn('done',value)
    with self.assertRaises(offline.core.Error):offline.sync_many(['a','missing'])
    self.assertEqual(['a','b'],calls)
if __name__=='__main__':unittest.main()
