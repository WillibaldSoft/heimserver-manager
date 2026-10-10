import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'client_agent/desktop'))
import offline_lifecycle as m
class Lifecycle(unittest.TestCase):
 def test_offline_shutdown_does_not_sync_or_wake(self):
  with patch.object(m.offline,'config',return_value=[dict(id='x',sync_shutdown=True,wake=True)]),patch.object(m,'reachable',return_value=False),patch.object(m.offline,'sync') as sync,patch.object(m,'record') as record:
   m.run_event('shutdown');sync.assert_not_called();self.assertEqual('offline',record.call_args.args[1])
 def test_shutdown_never_wakes_and_only_selected(self):
  rows=[dict(id='x',sync_shutdown=True,wake=True),dict(id='y',sync_startup=True)]
  with patch.object(m.offline,'config',return_value=rows),patch.object(m,'reachable',return_value=True),patch.object(m.offline,'sync') as sync,patch.object(m,'record'):
   m.run_event('shutdown');self.assertEqual(1,sync.call_count);self.assertFalse(sync.call_args.args[0]['wake']);self.assertTrue(rows[0]['wake'])
 def test_startup_keeps_wake_preference_and_records_errors(self):
  with patch.object(m.offline,'config',return_value=[dict(id='x',sync_startup=True,wake=True)]),patch.object(m.offline,'sync',side_effect=ValueError('conflict')) as sync,patch.object(m,'record') as record:
   m.run_event('startup');self.assertTrue(sync.call_args.args[0]['wake']);self.assertEqual('pending',record.call_args.args[1])
 def test_timeout_terminates_and_records_pending(self):
  process=Mock();process.wait.side_effect=[m.subprocess.TimeoutExpired('sync',1),0]
  with patch.object(m.os,'killpg') as kill,patch.object(m.subprocess,'Popen',return_value=process),patch.object(m,'record') as record:
   m.bounded('shutdown',1);kill.assert_called_once_with(process.pid,m.signal.SIGTERM);self.assertEqual('pending',record.call_args.args[1])
