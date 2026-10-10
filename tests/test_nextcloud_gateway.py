import unittest,sys,asyncio
from pathlib import Path
from tools.nextcloud_wake.gateway import create_app,clean_headers
from aiohttp import web,ClientSession
from aiohttp.test_utils import TestServer
from multidict import CIMultiDict

class GatewayTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.seen=[];self.leases=[];self.recovers=0;self.ready=True;self.allow=True
  async def status(r):return web.json_response(dict(installed=self.ready,maintenance=False))
  async def target(r):
   self.seen.append((r.method,r.raw_path,dict(r.headers),await r.read()))
   if r.path=='/redirect':return web.Response(status=302,headers={'Location':'/other','Set-Cookie':'session=private'})
   return web.Response(status=207 if r.method=='PROPFIND' else 200,body=self.seen[-1][3] or b'reply',headers=CIMultiDict([('Set-Cookie','a=1'),('Set-Cookie','b=2')]))
  async def heartbeat(r):
   self.leases.append((dict(r.headers),await r.json()));return web.json_response(dict(ok=True,sleep_blocker_enabled=self.allow))
  async def recover(r):self.recovers+=1;self.ready=True;return web.Response(status=202)
  backend=web.Application(client_max_size=0,handler_args={"auto_decompress":False});backend.router.add_get('/status.php',status);backend.router.add_get('/nextcloud/status.php',status);backend.router.add_route('*','/{path:.*}',target)
  manager=web.Application();manager.router.add_post('/api/clients/heartbeat',heartbeat);manager.router.add_get('/recover',recover)
  self.bs=TestServer(backend);self.ms=TestServer(manager);await self.bs.start_server();await self.ms.start_server()
  self.app=create_app(dict(backend=str(self.bs.make_url('')).rstrip('/'),manager_url=str(self.ms.make_url('')).rstrip('/'),recovery_url=str(self.ms.make_url('/recover')),domain='cloud.example.test',token='secret',wake_wait=0.05,hold_seconds=30,wake_cooldown=120))
  self.gs=TestServer(self.app);await self.gs.start_server();self.client=ClientSession(headers={'Host':'cloud.example.test'})
 async def asyncTearDown(self):
  await self.client.close();await self.gs.close();await self.ms.close();await self.bs.close()
 async def test_stream_upload_and_dav(self):
  data=b'xyz'*400000
  async def chunks():
   for n in range(0,len(data),17000):yield data[n:n+17000]
  async with self.client.put(self.gs.make_url('/remote.php/dav/a%20b?x=1'),data=chunks(),headers={'Authorization':'Basic user-secret'}) as r:self.assertEqual(200,r.status);self.assertEqual(data,await r.read());self.assertEqual(['a=1','b=2'],r.headers.getall('Set-Cookie'))
  self.assertEqual('/remote.php/dav/a%20b?x=1',self.seen[-1][1]);self.assertEqual(data,self.seen[-1][3]);self.assertEqual('Bearer secret',self.leases[-1][0]['Authorization']);self.assertEqual('Basic user-secret',self.seen[-1][2]['Authorization'])
  async with self.client.request('PROPFIND',self.gs.make_url('/dav')) as r:self.assertEqual(207,r.status)
 async def test_no_redirect_or_cookie_reuse(self):
  async with self.client.get(self.gs.make_url('/redirect'),allow_redirects=False) as r:self.assertEqual(302,r.status)
  async with self.client.get(self.gs.make_url('/new')) as r:await r.read()
  self.assertEqual(2,len(self.seen));self.assertNotIn('Cookie',self.seen[-1][2])
 async def test_missing_blocker_refuses_data(self):
  self.allow=False
  async with self.client.put(self.gs.make_url('/dav'),data=b'neverforward') as r:self.assertEqual(503,r.status)
  self.assertEqual([],self.seen)
 async def test_maintenance_no_recover(self):
  self.ready=False
  async with self.client.get(self.gs.make_url('/dav')) as r:self.assertEqual(503,r.status)
  self.assertEqual(0,self.recovers)
 async def test_wrong_host_and_upgrade(self):
  async with self.client.get(self.gs.make_url('/'),headers={'Host':'wrong.test'}) as r:self.assertEqual(421,r.status)
  async with self.client.get(self.gs.make_url('/'),headers={'Upgrade':'websocket'}) as r:self.assertEqual(501,r.status)
 async def test_concurrent_recovery_coalesced(self):
  g=self.app['gateway'];self.ready=False
  original=g.ready
  async def ready():return await original() if self.ready else 'unreachable'
  g.ready=ready
  results=await asyncio.gather(*(g.ensure_ready() for _ in range(6)))
  self.assertEqual([True]*6,results);self.assertEqual(1,self.recovers)
 async def test_drain_protects_active_requests(self):
  g=self.app['gateway'];g.active.add(asyncio.current_task())
  async with self.client.post(self.gs.make_url('/__wake_drain'),headers={'Authorization':'Bearer secret'}) as r:self.assertEqual(409,r.status)
  g.active.clear()
  async with self.client.post(self.gs.make_url('/__wake_drain')) as r:self.assertEqual(403,r.status)
  async with self.client.post(self.gs.make_url('/__wake_drain'),headers={'Authorization':'Bearer secret'}) as r:self.assertEqual(200,r.status)
  async with self.client.get(self.gs.make_url('/dav')) as r:self.assertEqual(503,r.status)
 async def test_encoded_body_is_not_changed(self):
  import gzip
  payload=gzip.compress(b'test payload'*1000)
  async with self.client.put(self.gs.make_url('/dav'),data=payload,headers={'Content-Encoding':'gzip'}) as r:self.assertEqual(200,r.status);await r.read()
  self.assertEqual(payload,self.seen[-1][3])
 async def test_hop_headers_removed(self):
  h=clean_headers(CIMultiDict(Connection='custom',custom='private',Keep_This='yes'))
  self.assertNotIn('custom',h);self.assertNotIn('Connection',h);self.assertEqual('yes',h['Keep_This'])
if __name__=='__main__':unittest.main()

class SubpathTests(GatewayTests):
 async def test_subpath_status_and_dav(self):
  self.app['gateway'].c['health_path']='/nextcloud/status.php'
  async with self.client.request('PROPFIND',self.gs.make_url('/nextcloud/remote.php/dav/files/user/'),headers={'Depth':'1'}) as response:
   self.assertEqual(207,response.status)
  self.assertEqual('/nextcloud/remote.php/dav/files/user/',self.seen[-1][1])
  self.assertEqual('1',self.seen[-1][2]['Depth']);self.assertEqual(0,self.recovers)
