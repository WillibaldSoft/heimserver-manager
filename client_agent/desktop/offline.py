import offline_mounts
import base64
"""Conservative file synchronization. Successful individual files checkpoint atomically."""
import fcntl,contextlib,hashlib,json,os,shutil,stat,tempfile,threading,time,urllib.parse,urllib.request,urllib.error
from pathlib import Path
import core,backup,device_identity
from client_i18n import tr
ROOT=Path.home()/'.config/server-manager-client/offline'
RUN_LOCK=threading.Lock()
def digest(path):
    with open(path,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else backup.digest(path)
def config():
    return json.loads((ROOT/'folders.json').read_text()) if (ROOT/'folders.json').exists() else []
def save_config(rows):core.atomic(ROOT/'folders.json',json.dumps(rows))
def call(action,gid='',path='',sha='',data=None,binary=False,exclude='',content_sha=''):
    cfg=core.validate(core.load())
    if not cfg['SERVER_URL'].startswith('https://'):raise core.Error(tr('Offline-Dateien benötigen HTTPS.'))
    query=urllib.parse.urlencode(dict(action=action,id=gid,path=path,sha=sha,exclude=exclude,content_sha=content_sha))
    headers={'Authorization':'Bearer '+cfg['TOKEN'],**device_identity.headers()}
    if data is not None:
        headers['Content-Type']='application/octet-stream'
        headers['Content-Length']=str(os.fstat(data.fileno()).st_size) if hasattr(data,'fileno') else str(len(data))
    req=urllib.request.Request(cfg['SERVER_URL']+'/api/clients/offline?'+query,data=data,headers=headers)
    try:
        r=urllib.request.build_opener(backup.NoRedirect).open(req,timeout=300)
        if binary:return r
        with r:return json.load(r)
    except urllib.error.HTTPError as e:
        try:message=json.loads(e.read(4096)).get('error','HTTP '+str(e.code))
        except Exception:message='HTTP '+str(e.code)
        raise core.Error(message) from None

def relative(value):
    p=value.split('/')
    if not value or any(not x or x in ('.','..') or x.lower().startswith('.hsm-') or '\\' in x or ':' in x for x in p):raise core.Error('Invalid file path')
    return p

def local_scan(root,exclude=()):
    root=Path(root)
    if not root.is_dir() or any(p.is_symlink() for p in (root,*root.parents)):raise core.Error(tr('Lokaler Ordner fehlt oder ist ein Link.'))
    result={};dev=root.stat().st_dev
    for folder,dirs,files in os.walk(root,followlinks=False):
        def selected(n):
            rel=(Path(folder)/n).relative_to(root).as_posix()
            return not any(rel==x or rel.startswith(x+'/') for x in exclude)
        dirs[:]=[d for d in dirs if not d.lower().startswith('.hsm-') and selected(d)]
        names=dirs+[f for f in files if not f.lower().startswith('.hsm-') and selected(f)]
        if len({n.casefold() for n in names})!=len(names):raise core.Error('Filename collision')
        for name in names:
            p=Path(folder)/name;st=p.lstat();rel=p.relative_to(root).as_posix();relative(rel)
            if stat.S_ISLNK(st.st_mode) or st.st_dev!=dev:raise core.Error('Links and nested mounts are unsupported')
            if stat.S_ISDIR(st.st_mode):continue
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise core.Error('Only regular files without hard links are supported')
            sha=digest(p);after=p.stat()
            if (st.st_size,st.st_mtime_ns,st.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise core.Error('File changed during scan')
            result[rel]=dict(sha=sha,size=st.st_size)
            if len(result)>5000:raise core.Error('Maximum 5000 files')
    return result

def decision(base,local,remote,write,delete):
    if local==remote:return 'same'
    if local==base:
        return 'get' if remote else ('trash' if delete else 'pending-delete')
    if remote==base:
        if local is None:return ('delete' if write and delete else ('get' if not write and remote else 'pending-delete'))
        return 'put' if write else 'conflict'
    return 'conflict'

def sync(row,progress=lambda s:None):
    if not RUN_LOCK.acquire(False):raise core.Error(tr('Synchronisierung läuft bereits.'))
    try:
        ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
        with (ROOT/'.sync-lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            return _sync(row,progress)
    finally:RUN_LOCK.release()

def _sync(row,progress):
    cfg=core.validate(core.load());gid=row['id'];root=Path(row['local']).absolute()
    offline_mounts.validate_local(root,row.get('source_mount'))
    if row.get('wake'):core.action('access')
    allowed=next((r for r in call('list')['folders'] if r['id']==gid.split('.',1)[0]),None)
    if allowed is None:raise core.Error(tr('Ordner nicht mehr freigegeben.'))
    smb=None
    if row.get('write') and allowed.get('smb'):
        import offline_smb
        encoded=gid.partition('.')[2]
        sub=base64.urlsafe_b64decode(encoded+'='*((-len(encoded))%4)).decode() if encoded else ''
        smb=offline_smb.Writer(allowed['smb'],sub)
    if row.get('write') and not allowed['write'] and smb is None:raise core.Error(tr('Schreibfreigabe wurde entzogen.'))
    # Fail closed on a different account/profile/server or local folder.
    scope=hashlib.sha256((cfg['SERVER_URL']+'\0'+cfg['TOKEN']+'\0'+gid+'\0'+str(root)).encode()).hexdigest()
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    state=ROOT/(scope+'.json');base=json.loads(state.read_text()) if state.exists() else {}
    stop=threading.Event();errors=[]
    call('lease',gid,data=b'')
    def renew():
        while not stop.wait(30):
            try:call('lease',gid,data=b'')
            except Exception:errors.append(True);return
    worker=threading.Thread(target=renew,daemon=True);worker.start()
    try:
        excluded=[x.strip().strip('/') for x in row.get('exclude','').split(',') if x.strip()]
        for x in excluded:relative(x)
        remote={v['path']:v for v in call('scan',gid,exclude=row.get('exclude',''))['files']};local=local_scan(root,excluded)
        def selected(name):return not any(name==x or name.startswith(x+'/') for x in excluded)
        remote={k:v for k,v in remote.items() if selected(k)};local={k:v for k,v in local.items() if selected(k)}
        maximum=int(row.get('limit_gib',10))*1024**3
        if sum(v['size'] for v in remote.values())+sum(v['size'] for k,v in local.items() if k not in remote)>maximum:raise core.Error(tr('Lokales Speicherlimit überschritten.'))
        conflicts=[];changed=0
        for name in sorted(set(base)|set(local)|set(remote)):
            if not selected(name):continue
            if errors:raise core.Error(tr('Schlafblocker konnte nicht erneuert werden.'))
            relative(name);l=(local.get(name) or {}).get('sha');r=(remote.get(name) or {}).get('sha')
            action=decision(base.get(name),l,r,row.get('write',False),row.get('delete',False))
            progress(name+' · '+action)
            p=root.joinpath(*relative(name))
            if action in ('conflict','pending-delete'):
                conflicts.append(name);continue
            if action=='put':
                if p.is_symlink() or digest(p)!=l:raise core.Error('Local file changed')
                call('lease',gid,data=b'')  # recheck the assignment before each change
                with p.open('rb') as src:
                    result=smb.mutate(name,r or '',src,sha=l) if smb else call('put',gid,name,r or '',src,content_sha=l)
                if result.get('sha')!=l:raise core.Error('Upload confirmation mismatch')
                r=l;changed+=1
            elif action=='delete':
                call('lease',gid,data=b'')
                if smb:smb.mutate(name,r or '',delete=True)
                else:call('delete',gid,name,r or '',b'')
                r=None;changed+=1
            elif action in ('get','trash'):
                if any(x.is_symlink() for x in (p,*p.parents)):raise core.Error('Unsafe local path')
                if (digest(p) if p.exists() else None)!=l:raise core.Error('Local file changed')
                p.parent.mkdir(parents=True,exist_ok=True)
                if action=='get':
                    size=remote[name]['size']
                    # Include retained revisions and temporary space in the configured quota.
                    used=sum(f.stat().st_size for f in root.rglob('*') if f.is_file() and not f.is_symlink())
                    if used+size>maximum or shutil.disk_usage(root).free<size+512*1024**2:raise core.Error(tr('Zu wenig freier Speicher für Offline-Dateien.'))
                    fd,tmp=tempfile.mkstemp(prefix='.hsm-part-',dir=p.parent)
                    try:
                        with os.fdopen(fd,'wb') as dst,call('get',gid,name,r,binary=True) as src:
                            count=0
                            for data in iter(lambda:src.read(1024*1024),b''):
                                count+=len(data)
                                if count>size:raise core.Error('Download too large')
                                dst.write(data)
                            dst.flush();os.fsync(dst.fileno())
                        if digest(tmp)!=r:raise core.Error('Download checksum mismatch')
                        if (digest(p) if p.exists() else None)!=l:raise core.Error('Local file changed')
                        if p.exists():retain(root,p)
                        os.replace(tmp,p)
                    finally:
                        if os.path.exists(tmp):os.unlink(tmp)
                elif p.exists():retain(root,p)
                changed+=1
            if r:base[name]=r
            else:base.pop(name,None)
            core.atomic(state,json.dumps(base))
        if row.get('_require_clean') and conflicts:raise core.Error('Resolve synchronization conflicts before completing this action')
        return tr('Abgleich beendet. Änderungen: ')+str(changed)+tr(' · Konflikte / ausstehende Löschungen: ')+str(len(conflicts))+ ('\n'+'\n'.join(conflicts[:30]) if conflicts else '')
    finally:
        stop.set();worker.join(timeout=1)
        try:call('release',gid,data=b'')
        except Exception:pass

def retain(root,path):
    target=root/'.hsm-recovery'/str(time.time_ns())/path.relative_to(root)
    if any(p.is_symlink() for p in (target,*target.parents)):raise core.Error('Unsafe recovery path')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.replace(path,target)

_LAST={}
def due():
    now=time.monotonic()
    for row in config():
        minutes=int(row.get('interval',0))
        if minutes and now-_LAST.get(row['id'],0)>=minutes*60:
            _LAST[row['id']]=now
            return row

def configure_many(grants,selected,destination):
    """Add independent pairs in one transaction, retaining all existing settings."""
    import re
    selected=list(dict.fromkeys(selected))
    if not selected:raise core.Error(tr('Mindestens einen Ordner anhaken.'))
    available={g['id']:g for g in grants}
    if any(gid not in available for gid in selected):raise core.Error(tr('Freigaben erneut laden.'))
    root=Path(destination).expanduser().absolute()
    if len(root.parts)<2 or root==Path.home() or any(p.is_symlink() for p in (root,*root.parents)):raise core.Error(tr('Eigenen Unterordner auswählen.'))
    offline_mounts.validate_local(root)
    rows=config();known={r['id'] for r in rows};planned=[]
    for gid in selected:
        if gid in known:continue
        grant=available[gid]
        slug=re.sub(r'[^\w.-]+','-',grant['name']).strip('.-')[:60] or 'Offline'
        target=root/(slug+'-'+hashlib.sha256(gid.encode()).hexdigest()[:12])
        for row in rows+planned:
            p=Path(row['local']).absolute()
            if target==p or target in p.parents or p in target.parents:raise core.Error('Overlapping local folders')
        if target.exists():local_scan(target)
        planned.append(dict(id=gid,name=grant['name'],local=str(target),write=False,delete=False,wake=False,interval=0,limit_gib=10,exclude=''))
    for row in planned:
        p=Path(row['local']);p.mkdir(parents=True,exist_ok=True);local_scan(p)
    save_config(rows+planned)
    return [r for r in rows+planned if r['id'] in selected]

def sync_many(selected,progress=lambda s:None):
    selected=list(dict.fromkeys(selected));rows={r['id']:r for r in config()}
    if not selected:raise core.Error(tr('Mindestens einen Ordner anhaken.'))
    if any(gid not in rows for gid in selected):raise core.Error(tr('Ausgewählte Ordner zuerst einrichten.'))
    if not RUN_LOCK.acquire(False):raise core.Error(tr('Synchronisierung läuft bereits.'))
    try:
        ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
        with (ROOT/'.sync-lock').open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            results=[]
            for gid in selected:
                row=rows[gid];name=row.get('name',gid)
                try:result=_sync(row,lambda value:progress(name+' · '+value))
                except Exception as exc:result=tr('Fehler: ')+str(exc)
                results.append(name+'\n'+result)
            return '\n\n'.join(results)
    finally:RUN_LOCK.release()
