import hashlib,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import incremental
class ContentDefined(unittest.TestCase):
 def setUp(self):self.blocks={}
 def run_stream(self,data,step=4*1024*1024):
  def call(action,data=None,query=''):
   if action=='block-has':
    key=query.split('&hash=')[1].split('&')[0];value=self.blocks.get(key)
    return dict(present=value is not None,bytes=len(value) if value is not None else 0)
   if action=='block-put':self.blocks[hashlib.sha256(data).hexdigest()]=data;return {}
   if action=='cas-finish':return data
   raise AssertionError(action)
  s=incremental.Stream('a'*32,lambda _:None,call=call,content_defined=True)
  for i in range(0,len(data),step):s.write(data[i:i+step]);self.assertLessEqual(len(s.buffer),4*1024*1024)
  manifest=s.finish();restored=b''.join(self.blocks[r['sha256']] for r in manifest['chunks'])
  self.assertEqual(data,restored);self.assertEqual(hashlib.sha256(data).hexdigest(),manifest['sha256'])
  return s
 def test_insertion_and_removal_reuse_unchanged_suffix(self):
  old=random.Random(43).randbytes(24*1024*1024);self.run_stream(old)
  inserted=old[:1000]+b'new file metadata'*37+old[1000:]
  s=self.run_stream(inserted);self.assertGreater(s.reused,len(old)*.7)
  changed=old[:1000]+old[1731:]
  s=self.run_stream(changed);self.assertGreater(s.reused,len(old)*.7)
 def test_write_fragmentation_does_not_change_blocks(self):
  data=random.Random(12).randbytes(7*1024*1024)
  a=self.run_stream(data);b=self.run_stream(data,step=7777)
  self.assertEqual(a.refs,b.refs);self.assertEqual(0,b.sent)
 def test_no_anchor_still_bounds_blocks_and_roundtrips(self):
  s=self.run_stream(b'x'*(10*1024*1024));self.assertTrue(all(r['bytes']<=4*1024*1024 for r in s.refs))
