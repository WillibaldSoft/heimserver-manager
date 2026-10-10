import unittest,importlib.util,io,contextlib,json,sqlite3
from unittest.mock import patch
from types import SimpleNamespace
from tools.nextcloud_wake import gateway as g
from modules.sleep_engine import runtime as r
class AuditTests(unittest.TestCase):
 def test_metadata_does_not_leak(self):
  q=SimpleNamespace(remote='127.0.0.1',headers={'X-Forwarded-For':'192.0.2.44','User-Agent':'DAVx5 secret-user','Authorization':'Basic secret-password'},path='/nextcloud/remote.php/dav/files/private-user/password',method='PROPFIND')
  value=json.dumps(g.request_meta(q,'private-token'))
  for secret in ['192.0.2.44','secret-user','secret-password','private-user','private-token']:self.assertNotIn(secret,value)
  self.assertEqual('davx',g.request_meta(q,'private-token')['client'])
 def test_rate_limit(self):
  g._AUDIT_WINDOW.clear();g._AUDIT_DROPPED=0
  out=io.StringIO()
  with contextlib.redirect_stdout(out):
   for i in range(150):g.audit('test')
  self.assertEqual(120,len(out.getvalue().splitlines()))
  g._AUDIT_WINDOW.clear();g._AUDIT_DROPPED=0
 def test_reset_records_cause_not_payload(self):
  con=sqlite3.connect(':memory:')
  with patch.object(r,'managed_blocker',return_value=False):
   r.record_grace_reset(con,'poweroff',[dict(source='client',title='Nextcloud Wake',token='do-not-log')])
  row=con.execute('SELECT mode,result,details FROM sleep_engine_actions').fetchone()
  self.assertEqual(('grace-reset','active-blockers'),row[:2]);self.assertNotIn('do-not-log',row[2]);self.assertIn('Nextcloud Wake',row[2])

class PollingTests(unittest.IsolatedAsyncioTestCase):
 def request(self,method='PROPFIND',path='/nextcloud/remote.php/dav/files/user',ua='Nextcloud desktop'):
  return SimpleNamespace(remote='127.0.0.1',host='cloud.example.test',headers={'User-Agent':ua},path=path,method=method)
 def test_classification(self):
  self.assertTrue(g.background_poll(self.request()))
  self.assertTrue(g.background_poll(self.request('GET','/nextcloud/ocs/v2.php/apps/notifications/api/v2/notifications')))
  for request in [self.request(ua='DAVx5'),self.request('PUT'),self.request('REPORT'),self.request('GET'),self.request('GET','/unknown')]:
   self.assertFalse(g.background_poll(request))
 async def test_sleeping_poll_has_no_wake_lease_or_tail(self):
  from unittest.mock import AsyncMock
  gateway=g.Gateway(dict(domain='cloud.example.test',token='test',hold_seconds=600))
  gateway.ready=AsyncMock(return_value='unreachable');gateway.ensure_ready=AsyncMock();gateway.lease=AsyncMock()
  with self.assertRaises(g.web.HTTPServiceUnavailable):await gateway.handle(self.request())
  gateway.ensure_ready.assert_not_awaited();gateway.lease.assert_not_awaited()
  self.assertEqual(0,gateway.tail_until);self.assertFalse(gateway.active);self.assertFalse(gateway.protected)
 async def test_davx_still_uses_wake(self):
  from unittest.mock import AsyncMock
  gateway=g.Gateway(dict(domain='cloud.example.test',token='test',hold_seconds=600))
  gateway.ensure_ready=AsyncMock(return_value=False)
  with self.assertRaises(g.web.HTTPServiceUnavailable):await gateway.handle(self.request(ua='DAVx5'))
  gateway.ensure_ready.assert_awaited_once();self.assertFalse(gateway.protected)
