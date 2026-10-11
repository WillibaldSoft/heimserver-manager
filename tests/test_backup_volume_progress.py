import os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import system_https,system_stream,incremental
class Volume(unittest.TestCase):
 def test_weighted_components_and_server_finish(self):
  messages=[];v=system_https.VolumeProgress(1000,messages.append)
  v.update(0);v.update(400);v.component_done(800);v.update(100);v.update(9000)
  self.assertTrue(messages[0].endswith('0 %'));self.assertTrue(messages[1].endswith('40 %'));self.assertTrue(messages[2].endswith('90 %'));self.assertTrue(messages[3].endswith('99 %'))
  self.assertFalse(any(x.endswith('100 %') for x in messages));v.finish();self.assertTrue(messages[-1].endswith('100 %'))
 def test_reused_blocks_count_as_processed(self):
  counts=[]
  stream=incremental.Stream('a'*32,lambda _:None,call=lambda *a,**k:{'present':True,'bytes':4},on_bytes=counts.append)
  stream.write(b'data');stream.flush()
  self.assertEqual([4],counts);self.assertEqual(4,stream.reused);self.assertEqual(0,stream.sent)
 def test_failed_block_does_not_advance(self):
  counts=[]
  def call(*a,**k):raise OSError('offline')
  stream=incremental.Stream('a'*32,lambda _:None,call=call,on_bytes=counts.append)
  stream.write(b'data')
  with self.assertRaises(OSError):stream.flush()
  stream.buffer.clear();self.assertEqual([],counts)
 def test_estimator_respects_mounts_hardlinks_and_symlinks(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'local').mkdir();(root/'local/file').write_bytes(b'x'*8192)
   os.link(root/'local/file',root/'local/link');(root/'network').mkdir();(root/'network/large').write_bytes(b'x'*100000)
   (root/'local/sym').symlink_to(root/'network/large')
   rows=[dict(target='/',fstype='ext4'),dict(target='/network',fstype='nfs')]
   with patch.object(system_stream,'source_root',return_value=root),patch.object(system_stream,'mounts',return_value=[]),patch.object(system_stream,'relative_mounts',return_value=rows):
    result=system_stream.estimate_archive({})
   self.assertEqual(5,result['entries']);self.assertEqual(10240+5*2048+8192,result['bytes'])
