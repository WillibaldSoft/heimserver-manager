import hashlib,json,random
from tests.test_shared_pc_backup import SharedPC
from modules.backup import client_api,reblock,chunks
import incremental
class Maintenance(SharedPC):
 def test_delete_reference_and_owner(self):
  self.setup_shared();query='&pc='+'a'*64;system=self.upload(query);personal=self.upload('&personal=1',ref=system)
  self.assertEqual(400,self.request('delete&id='+system+query,dict(confirmed=True)).status_code)
  self.assertEqual(400,self.request('delete&id='+personal,{}).status_code)
  self.grant('bob',modules=['client']);self.login('bob')
  self.assertEqual(400,self.request('delete&id='+personal,dict(confirmed=True),user='2'*64).status_code)
  self.login();self.assertEqual(200,self.request('delete&id='+personal,dict(confirmed=True)).status_code)
  self.assertEqual(200,self.request('delete&id='+system+query,dict(confirmed=True)).status_code)
 def test_aborted_blocks_reusable(self):
  self.setup_shared();sid=self.request('cas-begin',{}).json['id'];data=b'PK\x03\x04retained';key=hashlib.sha256(data).hexdigest()
  self.request('block-put&id='+sid+'&hash='+key,data)
  self.assertTrue(self.request('abort&id='+sid,{}).json['blocks_retained'])
  sid2=self.request('cas-begin',{}).json['id']
  self.assertTrue(self.request('block-has&id='+sid2+'&hash='+key).json['present'])
 def test_reblock_preserves_archive_and_matches_client(self):
  self.setup_shared();data=b'PK\x03\x04'+random.Random(42).randbytes(9*1024**2)
  sid=self.request('cas-begin',{}).json['id'];refs=[]
  for pos in range(0,len(data),chunks.MAX_CHUNK):
   part=data[pos:pos+chunks.MAX_CHUNK];key=hashlib.sha256(part).hexdigest();refs.append(dict(sha256=key,bytes=len(part)))
   self.request('block-put&id='+sid+'&hash='+key,part)
  self.request('cas-finish&id='+sid,dict(chunks=refs,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
  root=next((self.root/'desktop-client-backup').glob('*/'+sid)).parent
  result=reblock.migrate(root,sid,client_api);self.assertTrue(result['changed'])
  m=json.loads((root/sid/'manifest.json').read_text());self.assertEqual(data,b''.join(chunks.iterate(root,m,client_api.direct)))
  def call(action,data=None,query=''):
   if action=='block-has':
    key=query.split('&hash=')[1].split('&')[0];p=root/'.blocks'/key
    return dict(present=p.exists(),bytes=p.stat().st_size if p.exists() else 0)
   raise AssertionError(action)
  stream=incremental.Stream('a'*32,lambda _:None,call=call,content_defined=True)
  stream.write(data);stream.flush();self.assertEqual(0,stream.sent);self.assertEqual(m['chunks'],stream.refs)
