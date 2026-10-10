import os,pwd,tempfile,unittest
from unittest.mock import patch,MagicMock
from modules.offline_files import samba_acl as acl
class SambaACL(unittest.TestCase):
 def test_samba_allow_deny_and_unresolved(self):
  from samba.dcerpc import security
  user=pwd.getpwuid(os.getuid());lp=MagicMock();lp.get.side_effect=lambda k:{'server role':'standalone server','passdb backend':'tdbsam'}[k]
  db=MagicMock();db.sid_to_id.return_value=(user.pw_uid,1)
  def sd(text):return security.descriptor.from_sddl(text,security.dom_sid('S-1-5-21-1-2-3'))
  with patch('samba.samba3.param.get_context',return_value=lp),patch('samba.samba3.passdb.PDB',return_value=db):
   acl.check_descriptor(sd('D:(A;;FR;;;WD)'),user)
   from samba.dcerpc import xattr
   from samba.ndr import ndr_pack,ndr_unpack
   blob=xattr.NTACL();blob.version=1;blob.info=sd('D:(A;;FR;;;WD)')
   decoded=ndr_unpack(xattr.NTACL,ndr_pack(blob))
   acl.check_descriptor(decoded.info,user)
   blob.info=sd('D:(D;;FR;;;WD)(A;;FA;;;WD)')
   with self.assertRaises(PermissionError):acl.check_descriptor(ndr_unpack(xattr.NTACL,ndr_pack(blob)).info,user)
   acl.check_descriptor(sd('D:(A;OICIIO;FA;;;CO)(A;OICIIO;FA;;;CG)(A;;FR;;;WD)'),user)
   # Inherit-only rights alone must not grant access to the current object.
   with self.assertRaises(PermissionError):acl.check_descriptor(sd('D:(A;OICIIO;FA;;;CO)'),user)
   # Effective deny entries must still apply alongside inheritance templates.
   with self.assertRaises(PermissionError):acl.check_descriptor(sd('D:(A;OICIIO;FA;;;CO)(D;;FR;;;WD)(A;;FA;;;WD)'),user)
   with self.assertRaises(ValueError):acl.check_descriptor(sd('D:(A;;FA;;;CO)'),user)
   with self.assertRaises(PermissionError):acl.check_descriptor(sd('D:(D;;FR;;;WD)(A;;FA;;;WD)'),user)
   with self.assertRaises(PermissionError):acl.check_descriptor(sd('D:(D;;FR;;;S-1-22-1-123)(A;;FA;;;WD)'),user)
   db.sid_to_id.side_effect=ValueError('unknown')
   with self.assertRaises(ValueError):acl.check_descriptor(sd('D:(D;;FR;;;S-1-22-1-123)(A;;FA;;;WD)'),user)
 def test_broker_checks_same_open_handle_and_propagates_denial(self):
  with tempfile.TemporaryFile() as f,patch.object(acl,'check_fd') as check:
   with acl.broker(object()) as fd,patch.dict(os.environ,{'HSM_OFFLINE_ACL_FD':str(fd)}):
    acl.guard(f.fileno());self.assertEqual(1,check.call_count)
    check.side_effect=PermissionError('blocked')
    with self.assertRaises(PermissionError):acl.guard(f.fileno())
 def test_unknown_attribute_error_not_allowed(self):
  with patch.object(acl.os,'getxattr',side_effect=PermissionError('denied')):
   with self.assertRaises(ValueError):acl.check_fd(1,object())

 def test_unresolved_allow_never_grants_access_and_deny_stays_closed(self):
  from samba.dcerpc import security
  user=pwd.getpwuid(os.getuid());lp=MagicMock();lp.get.side_effect=lambda k:{'server role':'standalone server','passdb backend':'tdbsam'}[k]
  db=MagicMock();sid='S-1-5-21-1-2-3-501'
  def sd(text):return security.descriptor.from_sddl(text,security.dom_sid('S-1-5-21-1-2-3'))
  with patch('samba.samba3.param.get_context',return_value=lp),patch('samba.samba3.passdb.PDB',return_value=db):
   for unknown in ('exception','unmapped'):
    db.sid_to_id.side_effect=ValueError('unknown') if unknown=='exception' else None
    db.sid_to_id.return_value=(0,0)
    acl.check_descriptor(sd('D:(A;;FR;;;WD)(A;;FA;;;'+sid+')'),user)
    with self.assertRaises(PermissionError):acl.check_descriptor(sd('D:(A;;FA;;;'+sid+')'),user)
    with self.assertRaises(ValueError):acl.check_descriptor(sd('D:(A;;FR;;;WD)(D;;FA;;;'+sid+')'),user)
    with self.assertRaises(ValueError):acl.check_descriptor(sd('D:(A;;FA;;;'+sid+')(D;;FR;;;'+sid+')(A;;FA;;;WD)'),user)
    with self.assertRaises(PermissionError):acl.check_descriptor(sd('D:(D;;FR;;;WD)(A;;FA;;;'+sid+')(A;;FA;;;WD)'),user)
