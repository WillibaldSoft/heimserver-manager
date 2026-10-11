"""Revocable, device-bound backup-run credentials; never general login sessions."""
import hashlib,json,os,re,secrets,time,fcntl,contextlib
from pathlib import Path
IDLE_SECONDS=24*60*60
ACTIONS={'list','pc-status','begin','part','finish','cas-begin','cas-finish','cas-finalize','cas-status','cas-pending','cas-retire','block-has','block-put','abort','session-end'}
class Leases:
 def __init__(self,directory):self.directory=Path(directory)
 @contextlib.contextmanager
 def locked(self,token):
  if not re.fullmatch('[a-f0-9]{64}',token or ''):raise ValueError('Invalid backup credential')
  self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
  path=self.directory/hashlib.sha256(token.encode()).hexdigest()
  # Open an existing record only; revoked credentials cannot recreate it.
  fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
  with os.fdopen(fd,'r+') as f:
   fcntl.flock(f,fcntl.LOCK_EX);record=json.load(f)
   if record.get('closed') or time.time()-record['seen']>IDLE_SECONDS:raise ValueError('Backup credential expired')
   yield record
   f.seek(0);json.dump(record,f);f.truncate();f.flush()
 def issue(self,auth,device,user):
  if not re.fullmatch('[a-f0-9]{64}',device or '') or not re.fullmatch('[a-f0-9]{64}',user or ''):raise ValueError('Device identity required')
  self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
  token=secrets.token_hex(32);path=self.directory/hashlib.sha256(token.encode()).hexdigest()
  fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
  with os.fdopen(fd,'w') as f:json.dump(dict(auth=auth,device=device,user=user,seen=time.time(),uploads=[],closed=False),f)
  return token
 def validate(self,token,device,user,action,method,query,resolve):
  with self.locked(token) as r:
   if r['device']!=device or r['user']!=user:raise ValueError('Wrong backup device')
   if action not in ACTIONS:raise ValueError('Action outside backup run')
   if method!=('GET' if action in ('list','pc-status','block-has','cas-status','cas-pending') else 'POST'):raise ValueError('Wrong method')
   if query.get('pc','') not in ('',device) or query.get('source_agent') or query.get('shared_pc'):raise ValueError('Wrong backup scope')
   principal=resolve(r['auth'])
   if not principal:raise ValueError('Account revoked')
   if action in ('part','finish','cas-finish','cas-finalize','cas-status','block-has','block-put','abort'):
    key=[query.get('id',''),query.get('pc',''),query.get('personal','')]
    if key not in r['uploads']:raise ValueError('Upload outside backup run')
   r['seen']=time.time()
   return principal
 def remember(self,token,sid,pc,personal):
  with self.locked(token) as r:
   key=[sid,pc,personal]
   if key not in r['uploads']:r['uploads'].append(key)
   r['seen']=time.time()
 def close(self,token):
  with self.locked(token) as r:r['closed']=True
