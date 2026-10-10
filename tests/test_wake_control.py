import asyncio,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,AsyncMock
from flask import Flask,g
from tools.nextcloud_wake import gateway
from modules.app_manager import wake_control as ui
class WakeControlTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.file=Path(self.tmp.name)/'switch.json'
  for module,name in [(gateway,'WAKE_CONTROL'),(ui,'CONTROL')]:
   p=patch.object(module,name,self.file);p.start();self.addCleanup(p.stop)
 def test_default_invalid_and_persistence(self):
  for fn in (gateway.wake_enabled,ui.wake_enabled):self.assertTrue(fn())
  for value in ('broken','null','{"mode":"bad"}','{"mode":"inactive"}'):
   self.file.write_text(value)
   for fn in (gateway.wake_enabled,ui.wake_enabled):self.assertFalse(fn())
  ui.save(dict(mode='active'));self.assertTrue(gateway.wake_enabled())
 def test_daily_windows_and_midnight(self):
  ui.save(ui.parse(dict(mode='schedule',default='inactive',start0='06:00',end0='08:00',state0='active',start1='22:00',end1='01:00',state1='active')))
  for h,m,result in [(5,59,False),(6,0,True),(7,59,True),(8,0,False),(21,59,False),(22,0,True),(0,59,True),(1,0,False)]:
   now=time.struct_time((2026,10,10,h,m,0,5,283,1))
   with patch.object(gateway.time,'localtime',return_value=now):
    self.assertEqual(gateway.wake_enabled(),result);self.assertEqual(ui.wake_enabled(),result)
 def test_inactive_window_and_manual_override(self):
  c=ui.parse(dict(mode='schedule',default='active',start0='00:00',end0='23:59',state0='inactive'));ui.save(c)
  with patch.object(gateway.time,'localtime',return_value=time.struct_time((2026,10,10,12,0,0,5,283,1))):
   self.assertFalse(gateway.wake_enabled());ui.save(dict(c,mode='active'));self.assertTrue(gateway.wake_enabled());ui.save(dict(c,mode='inactive'));self.assertFalse(gateway.wake_enabled())
 def test_invalid_or_overlapping_periods(self):
  base=dict(mode='schedule',default='inactive',start0='22:00',end0='02:00',state0='active')
  for change in [dict(start0='24:00'),dict(end0='22:00'),dict(end0=''),dict(start1='01:00',end1='03:00',state1='inactive')]:
   with self.assertRaises(ValueError):ui.parse(dict(base,**change))
  ui.parse(dict(base,start1='02:00',end1='03:00',state1='active'))
 def test_gateway_disabled_allows_ready_backend_only(self):
  ui.save(dict(mode='inactive'));obj=object.__new__(gateway.Gateway);obj.ready=AsyncMock(return_value='unreachable')
  self.assertFalse(asyncio.run(obj.wake_wait()));obj.ready=AsyncMock(return_value='ready');self.assertTrue(asyncio.run(obj.wake_wait()))
 def test_ui_auth_csrf_stale_and_save(self):
  app=Flask(__name__);app.secret_key='test';role=['user']
  @app.before_request
  def auth():g.auth_principal={'role':role[0]}
  ui.register(app);client=app.test_client()
  with client.session_transaction() as s:s['app_install_csrf']='csrf'
  data=dict(csrf='csrf',mode='inactive',default='inactive',revision='missing')
  with patch.object(ui,'supported',return_value=True):
   self.assertEqual(client.post('/apps/nextcloud/wake/control',data=data).status_code,403);role[0]='admin'
   self.assertEqual(client.post('/apps/nextcloud/wake/control',data={**data,'csrf':'bad'}).status_code,403)
   self.assertEqual(client.post('/apps/nextcloud/wake/control',data=data).status_code,303);self.assertFalse(gateway.wake_enabled())
   self.assertEqual(client.post('/apps/nextcloud/wake/control',data=data).status_code,409)
 def test_recovery_source_unaffected(self):
  from tools.power_api import power_api
  self.assertFalse(hasattr(power_api,'wake_enabled'))
