"""Background CAS verification; polling never holds the upload lock."""
import json,threading,time,uuid
RUNNING={}

def status(root,sid,api):
 # Final promotion is atomic; recheck completion after reading the upload state.
 def completed():
  p=api.direct(root/sid/'manifest.json')
  if p.is_file():
   m=json.loads(p.read_text())
   return dict(state='complete',id=sid,bytes=m['bytes'],sha256=m['sha256'])
 result=completed()
 if result:return result
 folder=api.direct(root/('.upload-'+sid));p=api.direct(folder/'verification-status.json')
 try:result=json.loads(p.read_text())
 except FileNotFoundError:
  return completed() or dict(state='not-started' if folder.is_dir() else 'missing',id=sid)
 done=completed()
 if done:return done
 if result['state'] in ('queued','verifying') and (str(root),sid) not in RUNNING:
  result=dict(result,state='interrupted',error='Verification interrupted; uploaded blocks are preserved.')
 return result

def start(root,sid,data,api):
 from . import chunks
 key=(str(root),sid);folder=api.direct(root/('.upload-'+sid))
 if key in RUNNING:
  try:submitted=json.loads(api.direct(folder/'verification-request.json').read_text())
  except FileNotFoundError:return status(root,sid,api)
  if any(submitted.get(k)!=data.get(k) for k in ('chunks','bytes','sha256')):raise ValueError('Different finalization already submitted')
  return status(root,sid,api)
 with api.locked(root):
  if api.direct(root/sid).is_dir():return status(root,sid,api)
  m=json.loads(api.direct(folder/'manifest.json').read_text())
  if m.get('format')!=chunks.FORMAT:raise ValueError('Not an incremental backup')
  if (folder/'cancel-requested').exists():raise ValueError('Backup cancelled')
  candidate=dict(m,chunks=data.get('chunks'),bytes=data.get('bytes'),sha256=data.get('sha256'),scope='linux-system-tar-v2')
  chunks.valid_manifest(candidate)
  pending=api.direct(folder/'verification-request.json')
  if pending.exists() and json.loads(pending.read_text())!=candidate:raise ValueError('Different finalization already submitted')
  if key in RUNNING:return status(root,sid,api)
  api.save(pending,candidate)
  api.save(folder/'verification-status.json',dict(state='queued',id=sid,verified_bytes=0,bytes=candidate['bytes']))
  marker=uuid.uuid4().hex;RUNNING[key]=marker;api.ACTIVE[marker]=True
  def worker():
   try:
    with api.locked(root):
     total=0;last=0;first=True
     for chunk in chunks.iterate(root,candidate,api.direct):
      if (folder/'cancel-requested').exists():raise ValueError('Backup cancelled')
      if first and not chunk.startswith(b'PK\x03\x04'):raise ValueError('Invalid ZIP stream')
      first=False;total+=len(chunk)
      if time.monotonic()-last>=1:
       api.save(folder/'verification-status.json',dict(state='verifying',id=sid,verified_bytes=total,bytes=candidate['bytes']))
       last=time.monotonic()
     if (folder/'cancel-requested').exists():raise ValueError('Backup cancelled')
     api.save(folder/'manifest.json',candidate);folder.rename(root/sid)
   except Exception as exc:
    if folder.is_dir():
     try:api.save(folder/'verification-status.json',dict(state='failed',id=sid,error=str(exc)))
     except OSError:pass
   finally:RUNNING.pop(key,None);api.ACTIVE.pop(marker,None)
  try:threading.Thread(target=worker,daemon=True,name='backup-verify-'+sid[:8]).start()
  except Exception:
   RUNNING.pop(key,None);api.ACTIVE.pop(marker,None);raise
  return dict(state='queued',id=sid,verified_bytes=0,bytes=candidate['bytes'])
