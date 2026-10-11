"""Explicit retirement of idle uploads; immutable blocks are never collected."""
import fcntl,json,os,time
from flask import request,jsonify

def scoped(folder,api):
 m=json.loads(api.direct(folder/'manifest.json').read_text())
 device=request.headers.get('X-HSM-Device','')
 component='system' if request.args.get('pc') else 'personal'
 if not device or m.get('device_id')!=device or m.get('component')!=component:raise ValueError('Interrupted backup belongs to another device or component')
 if m.get('format')!='client-cas-zip-v1' or folder.name!='.upload-'+api.identifier(m.get('id')):raise ValueError('Invalid interrupted backup')
 return m

def handle(root,action,api):
 fd=os.open(api.direct(root/'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise ValueError('Backup storage is busy; retry after the current operation completes')
  if action=='cas-pending' and request.method=='GET':
   rows=[]
   for folder in root.glob('.upload-*'):
    api.direct(folder);m=scoped(folder,api);stamp=folder.stat().st_mtime_ns
    rows.append(dict(id=m['id'],created=m['created'],name=m.get('name',''),revision=str(stamp),idle_seconds=max(0,int(time.time()-stamp/1e9))))
   return jsonify(uploads=rows)
  if action!='cas-retire' or request.method!='POST':raise ValueError('Invalid retirement method')
  data=request.get_json();sid=api.identifier(data.get('id'));folder=api.direct(root/('.upload-'+sid));scoped(folder,api)
  stamp=folder.stat().st_mtime_ns
  if str(stamp)!=data.get('revision') or time.time()-stamp/1e9<600:raise ValueError('Backup is active or changed; no data modified. Retry after ten minutes without activity.')
  from . import finalize
  if (str(root),sid) in finalize.RUNNING:raise ValueError('Backup verification is still running')
  if data.get('confirmed') is not True:raise ValueError('Explicit confirmation required')
  dest=api.direct(root/('.interrupted-'+sid))
  if dest.exists():raise ValueError('Retired backup already exists')
  folder.rename(dest)
  return jsonify(ok=True,blocks_preserved=True)
 finally:os.close(fd)
