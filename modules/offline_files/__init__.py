"""Explicit, device-bound offline-folder grants; HTTPS and optimistic file revisions."""
import contextlib,fcntl,hashlib,html,json,os,re,shutil,stat,tempfile,time,uuid
from pathlib import Path
from flask import request,jsonify,g,session,send_file,after_this_request
import server_settings
from . import mounts as storage
from .samba_acl import guard
from ui_translation import html_literal as H, text as T
MAX_FILES=5000
LEASES={}
ACTIVE=set()
CONFIG=lambda:server_settings.CONFIG_DIR/'offline-files.json'
def grants():return server_settings.read(CONFIG()).get('folders',[])
def blockers():
    return [dict(source='Offline-Dateien',type='offline-sync',title='Offline-Dateien werden synchronisiert',reason='Befristete Übertragung',priority=95,url='/clients/offline') ] if ACTIVE or any(v>time.monotonic() for v in list(LEASES.values())) else []
def parts(value):
    if not isinstance(value,str) or len(value)>700:raise ValueError('Invalid path')
    p=value.split('/')
    if not p or any(not x or x in ('.','..') or x.lower().startswith('.hsm-') or x[-1:] in ('.',' ') or re.search(r'[\x00-\x1f<>:"\\|?*]',x) or re.match(r'(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)',x) for x in p):raise ValueError('Unsupported filename')
    return p
@contextlib.contextmanager
def rootfd(row):
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in Path(row['path']).parts[1:]:
            other=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=other
            guard(fd)
        st=os.fstat(fd)
        if row.get('mount'):
            current=storage.containing(row['path'],storage.mounts())
            if current is None or storage.signature(current)!=row['mount'] or st.st_dev!=Path(current['target']).stat().st_dev:
                raise ValueError('Configured disk or network mount is unavailable or changed')
            if st.st_ino!=row['identity'][1]:raise ValueError('Folder changed; administrator must renew the grant')
        elif [st.st_dev,st.st_ino]!=row['identity']:raise ValueError('Folder or disk changed; administrator must renew the grant')
        guard(fd)
        yield fd
    finally:os.close(fd)
def mount_id(fd):
    for line in Path('/proc/self/fdinfo/'+str(fd)).read_text().splitlines():
        if line.startswith('mnt_id:'):return line.split(':',1)[1].strip()
    raise ValueError('Mount identity unavailable')
@contextlib.contextmanager
def parent(fd,path,create=False,directory_mode=0o750):
    fd=os.dup(fd);original_mount=mount_id(fd)
    try:
        for p in parts(path)[:-1]:
            if create:
                try:
                    os.mkdir(p,directory_mode,dir_fd=fd)
                    st=os.fstat(fd)
                    if os.geteuid()==0:os.chown(p,st.st_uid,st.st_gid,dir_fd=fd,follow_symlinks=False)
                except FileExistsError:pass
            n=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_DIRECTORY,dir_fd=fd);os.close(fd);fd=n
            if mount_id(fd)!=original_mount:raise ValueError('Nested mounts must be granted separately')
            guard(fd)
        yield fd,parts(path)[-1]
    finally:os.close(fd)
def fingerprint(fd,name):
    try:f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    except FileNotFoundError:return None
    with os.fdopen(f,'rb') as stream:
        guard(stream.fileno())
        before=os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise ValueError('Only regular files without hard links are supported')
        h=hashlib.sha256()
        for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
        after=os.fstat(stream.fileno())
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('File changed during scan')
        return dict(sha=h.hexdigest(),size=after.st_size)
def scan(fd,prefix='',out=None,exclude=()):
    out=[] if out is None else out
    guard(fd)
    names=os.listdir(fd);seen=set()
    for n in sorted(names):
        if n.lower().startswith('.hsm-'):continue
        path=prefix+n
        if any(path==x or path.startswith(x+'/') for x in exclude):continue
        parts(path)
        if n.casefold() in seen:raise ValueError('Case-insensitive filename collision')
        seen.add(n.casefold());st=os.stat(n,dir_fd=fd,follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            f=os.open(n,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            try:
                if mount_id(f)!=mount_id(fd):raise ValueError('Nested mounted folders are not supported')
                scan(f,path+'/',out,exclude)
            finally:os.close(f)
        else:
            info=fingerprint(fd,n)
            if info is None:raise ValueError('File disappeared during scan')
            out.append(dict(path=path,**info))
        if len(out)>MAX_FILES:raise ValueError('Maximum 5000 files per folder')
    return out
@contextlib.contextmanager
def lock(fd):
    inherited=os.environ.get('HSM_OFFLINE_LOCK_FD')
    if inherited:
        os.fstat(int(inherited))
        yield
        return
    f=os.open('.hsm-sync-lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        if os.fstat(f).st_nlink!=1:raise ValueError('Unsafe lock')
        fcntl.flock(f,fcntl.LOCK_EX);yield
    finally:os.close(f)
def mutate(fd,path,expected,stream,size,delete=False,content_sha=None,file_mode=0o660,directory_mode=0o750):
    with lock(fd),parent(fd,path,create=not delete,directory_mode=directory_mode) as (p,n):
        current=fingerprint(p,n)
        if (current or {}).get('sha','')!=expected:raise FileExistsError('Conflict: server file changed')
        if delete and current is None:return
        if shutil.disk_usage('/proc/self/fd/'+str(fd)).free<size+512*1024**2:raise ValueError('Server storage reserve reached')
        tmp='.hsm-part-'+uuid.uuid4().hex
        try:
            new=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,file_mode,dir_fd=p)
            with os.fdopen(new,'wb') as target:
                count=0
                if not delete:
                    while True:
                        data=stream.read(min(1024*1024,size-count+1))
                        if not data:break
                        count+=len(data)
                        if count>size:raise ValueError('Upload too large')
                        target.write(data)
                    if count!=size:raise ValueError('Incomplete upload')
                old=os.stat(n,dir_fd=p,follow_symlinks=False) if current else os.fstat(p)
                if current:
                    if os.geteuid()!=0 and old.st_uid!=os.geteuid():raise PermissionError('Cannot preserve another owner during atomic replacement')
                    os.fchown(target.fileno(),old.st_uid,old.st_gid);os.fchmod(target.fileno(),old.st_mode&0o777)
                    source=os.open(n,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=p)
                    try:
                        import errno
                        try:acl=os.getxattr(source,'system.posix_acl_access')
                        except OSError as exc:
                            if exc.errno not in (errno.ENODATA,errno.ENOTSUP):raise
                            acl=None
                        if acl is not None:os.setxattr(target.fileno(),'system.posix_acl_access',acl)
                    finally:os.close(source)
                target.flush();os.fsync(target.fileno())
            if not delete and content_sha is not None and fingerprint(p,tmp)['sha']!=content_sha:raise ValueError('Upload checksum mismatch')
            if fingerprint(p,n)!=current:raise FileExistsError('Conflict: server file changed')
            if current:
                # Revision is retained next to its source, inaccessible through this API.
                history='.hsm-history-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex+'-'+n[:60]
                with os.fdopen(os.open(n,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=p),'rb') as src:
                    h=os.open(history,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=p)
                    with os.fdopen(h,'wb') as dst:shutil.copyfileobj(src,dst);dst.flush();os.fsync(dst.fileno())
                if fingerprint(p,n)!=current:raise FileExistsError('Conflict: file changed while retaining revision')
            if delete:os.unlink(n,dir_fd=p)
            else:os.replace(tmp,n,src_dir_fd=p,dst_dir_fd=p)
            os.fsync(p)
        finally:
            try:os.unlink(tmp,dir_fd=p)
            except FileNotFoundError:pass

def add_grants(rows,paths,name,clients,allowed,write=False):
    paths=list(dict.fromkeys(p.strip() for p in paths if p.strip()))
    if not paths or len(paths)>100:raise ValueError('Choose between 1 and 100 folders')
    if not clients or not set(clients)<=set(allowed):raise ValueError('Paired clients required')
    result=list(rows)
    mounted=storage.mounts()
    for value in paths:
        path=Path(value)
        if not path.is_absolute() or len(path.parts)<3 or path.parts[1] in ('etc','proc','sys','dev','run','usr','bin','sbin','lib','lib64','boot','root','var','opt') or '..' in path.parts:raise ValueError('Choose a dedicated absolute data folder outside system directories')
        label=name.strip() if len(paths)==1 and name.strip() else ((name.strip()+' · ') if name.strip() else '')+path.name
        st=path.stat();row=dict(id=uuid.uuid4().hex,name=label[:80],path=str(path),identity=[st.st_dev,st.st_ino],clients=clients,write=bool(write))
        mount=storage.containing(path,mounted)
        if mount is not None:row['mount']=storage.signature(mount)
        with rootfd(row):pass
        if any(path==Path(r['path']) or path in Path(r['path']).parents or Path(r['path']) in path.parents for r in result):raise ValueError('Overlapping grants are not allowed; remove the previous grant first')
        result.append(row)
    return result

def assign_client(rows,selected,client,allowed,choices):
    import copy
    if client not in allowed:raise ValueError('Choose an enabled paired client')
    selected=set(selected)
    previous={r['path'] for r in rows if client in r['clients']}
    if not selected <= set(choices)|previous:raise ValueError('Only mounted roots or configured share folders can be selected')
    chosen=[Path(x) for x in selected]
    if any(a in b.parents or b in a.parents for i,a in enumerate(chosen) for b in chosen[i+1:]):raise ValueError('Overlapping grants are not allowed')
    result=copy.deepcopy(rows)
    for row in result:
        if row['path'] in selected:
            if client not in row['clients']:row['clients'].append(client)
        else:row['clients']=[c for c in row['clients'] if c!=client]
    result=[row for row in result if row['clients']]
    for path in sorted(selected):
        if not any(row['path']==path and client in row['clients'] for row in result):
            result=add_grants(result,[path],'',[client],allowed,True)
    return result

def grants_revision(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()

def register(app,ctx):
    @app.route('/api/clients/offline',methods=['GET','POST'])
    def offline_api():
        from modules.heimnetz_clients import agent_by_token
        agent=agent_by_token(ctx)
        if agent is None or not getattr(g,'bound_client',False):return jsonify(error='Paired user/device profile required'),403
        if not request.is_secure:return jsonify(error='HTTPS required'),403
        try:
            from . import rights,scope,dispatch
            user=rights.identity(ctx,agent)
            rows=[r for r in grants() if int(agent['id']) in r['clients']]
            action=request.args.get('action','list');gid=request.args.get('id','')
            if action=='list' and request.method=='GET':
                result=[];denied=[]
                for candidate in rows:
                    try:
                        write=rights.permission(candidate['path'],user,request.remote_addr) and candidate['write']
                        dispatch.invoke(dict(row=candidate,sub='',action='lease'),user)
                        smb=rights.smb_target(candidate['path'],user,request.remote_addr) if candidate['write'] else None
                        result.append(dict(id=candidate['id'],name=candidate['name'],write=write,smb=smb))
                    except (OSError,ValueError) as exc:denied.append(dict(name=candidate['name'],reason=str(exc)))
                if denied and not result:return jsonify(error='Assigned folders unavailable: '+'; '.join(x['name']+': '+x['reason'] for x in denied)),403
                return jsonify(folders=result,unavailable=denied)
            base,sub=scope.split(gid)
            row=next((r for r in rows if r['id']==base),None)
            if row is None:return jsonify(error='Folder not authorized'),403
            key=(agent['id'],gid)
            if action=='release' and request.method=='POST':LEASES.pop(key,None);return jsonify(ok=True)
            LEASES[key]=time.monotonic()+120
            activity=uuid.uuid4().hex;ACTIVE.add(activity)
            @after_this_request
            def finish(response):
                response.direct_passthrough=False
                response.call_on_close(lambda:ACTIVE.discard(activity))
                response.headers['Cache-Control']='no-store'
                return response
            expected=request.args.get('sha','')
            if expected and not re.fullmatch('[a-f0-9]{64}',expected):raise ValueError('Invalid revision')
            excluded=[x.strip().strip('/') for x in request.args.get('exclude','').split(',') if x.strip()]
            if len(excluded)>100:raise ValueError('Too many exclusions')
            for x in excluded:parts(x)
            write=rights.permission(row['path'],user,request.remote_addr) and row['write']
            size=request.content_length or 0;content_sha=request.args.get('content_sha','')
            if action not in ('browse','scan','get','lease','put','delete'):raise ValueError('Unknown action')
            if request.method!=('POST' if action in ('lease','put','delete') else 'GET'):raise ValueError('Invalid method')
            if action in ('put','delete'):
                if not write:return jsonify(error='Read-only share'),403
                if request.content_length is None or size<0:raise ValueError('A valid content length is required')
                if action=='put' and not re.fullmatch('[a-f0-9]{64}',content_sha):raise ValueError('Upload checksum required')
            file_mode,directory_mode=rights.creation_modes(row['path']) if action in ('put','delete') else (0o660,0o750)
            spec=dict(file_mode=file_mode,directory_mode=directory_mode,row=row,sub=sub,action=action,path=request.args.get('path',''),sha=expected,exclude=excluded,write=write,size=size,content_sha=content_sha or None)
            result=dispatch.invoke(spec,user,request.stream if action in ('put','delete') else None)
            if action=='get':
                response=send_file(result,mimetype='application/octet-stream');response.call_on_close(result.close);return response
            return jsonify(result)
        except FileExistsError as e:return jsonify(error=str(e)),409
        except (ValueError,OSError) as e:return jsonify(error=str(e)),400

    @app.route('/clients/offline',methods=['GET','POST'])
    def offline_admin():
        rows=grants();message='';con=ctx.db()
        try:
            from modules.heimnetz_clients import init_tables
            from modules.heimnetz_extra.client_bindings import schema
            init_tables(con);schema(con)
            agents=[dict(r) for r in con.execute('SELECT a.id,a.name,a.ip FROM client_agents a JOIN client_bindings b ON b.agent_id=a.id WHERE a.enabled=1')]
        finally:con.close()
        e=lambda value:html.escape(str(value),quote=True)
        try:options=storage.server_choices(storage.mounts());options_ok=True
        except Exception:options=[];options_ok=False
        try:selected_client=int(request.values.get('client','0'))
        except ValueError:selected_client=0
        current=next((a for a in agents if a['id']==selected_client),None)
        unavailable={}
        if current:
            from . import rights,dispatch
            try:
                user=rights.identity(ctx,current)
                for path in set(options)|{r['path'] for r in rows if selected_client in r['clients']}:
                    try:
                        rights.permission(path,user,current.get('ip') or '')
                        st=os.stat(path,follow_symlinks=False)
                        dispatch.invoke(dict(row=dict(path=path,identity=[st.st_dev,st.st_ino],id='preview'),sub='',action='lease'),user)
                    except (OSError,ValueError) as exc:unavailable[path]=str(exc)
            except (OSError,ValueError) as exc:unavailable={path:str(exc) for path in set(options)|{r['path'] for r in rows if selected_client in r['clients']}}
        if request.method=='POST':
            try:
                if not options_ok:raise ValueError('Folder discovery failed; nothing changed')
                if request.form.get('revision')!=grants_revision(rows):raise ValueError('Assignments changed; reload the page')
                rows=assign_client(rows,request.form.getlist('mounted'),selected_client,[a['id'] for a in agents],[p for p in options if p not in unavailable])
                server_settings.atomic(CONFIG(),dict(folders=rows));message=T('Gespeichert.')
            except (OSError,ValueError,KeyError) as exc:message=str(exc)
        body=H("<div class='card'><h2>Offline-Dateien pro Benutzer / Client</h2><p>Zuerst die Benutzer-Geräte-Kopplung auswählen, dann deren Ausgangsordner festlegen. Die Zuordnung anderer Clients bleibt erhalten. Tiefere Unterordner werden ausschließlich im Client ausgewählt. Bestehende SMB-/NFS- und Linux-Dateirechte bleiben die Obergrenze.</p><form method='get'><label>Benutzer / Client <select name='client' required><option value=''>Bitte auswählen</option>")
        for a in agents:body+="<option value='"+str(a['id'])+"'"+(' selected' if a['id']==selected_client else '')+">"+e(a['name'])+"</option>"
        body+=H("</select></label><button>Zuordnung anzeigen</button></form></div>")
        if message:body+="<div class='card'>"+e(message)+"</div>"
        if current:
            if request.args.get('diagnose') in ('1','tree'):
                from . import rights,dispatch
                body+="<div class='card'><h3>"+e(T('Zugriffsprüfung'))+"</h3><ul>"
                try:
                    user=rights.identity(ctx,current)
                    for row in rows:
                        if selected_client not in row['clients']:continue
                        try:
                            writable=(rights.permission(row['path'],user,current.get('ip') or '') or rights.smb_target(row['path'],user,current.get('ip') or '')) and row['write']
                            dispatch.invoke(dict(row=row,sub='',action='audit' if request.args.get('diagnose')=='tree' else 'lease'),user)
                            status=T('Lesen / Schreiben') if writable else T('Nur lesen')
                        except (OSError,ValueError) as exc:status=str(exc)
                        body+='<li>'+e(row['name'])+': '+e(status)+'</li>'
                except (OSError,ValueError) as exc:body+='<li>'+e(str(exc))+'</li>'
                body+='</ul></div>'
            body+="<div class='card'><a class='btn' href='?client="+str(selected_client)+"&amp;diagnose=1'>"+e(T('Zugriffsprüfung'))+'</a></div>'
            assigned={r['path'] for r in rows if selected_client in r['clients']}
            body+="<div class='card'><h3>"+e(current['name'])+"</h3>"+H("<p>Nur Mounts und eingerichtete SMB-/NFS-Freigabeordner. Keine Auflistung weiterer Unterordner. Haken entfernen entzieht nur diesem Client den Offline-Zugriff; vorhandene lokale Kopien bleiben erhalten.</p><form method='post'><input type='hidden' name='auth_csrf' value='")+e(session['auth_csrf'])+"'><input type='hidden' name='client' value='"+str(selected_client)+"'><input type='hidden' name='revision' value='"+grants_revision(rows)+"'>"
            for path in sorted((set(options)|assigned)-set(unavailable)):
                body+="<label style='display:block'><input type='checkbox' name='mounted' value='"+e(path)+"'"+(' checked' if path in assigned else '')+(' disabled' if path in unavailable and path not in assigned else '')+"> "+e(path)+(' · '+e(unavailable[path]) if path in unavailable else '')+((' · '+T('Bisherige Zuordnung (nicht neu auswählbar)')) if path not in options else '')+"</label>"
            body+=H('<p><button>Zuordnung speichern</button></p></form><p>Die Auswahl erteilt keine zusätzlichen Dateirechte. Das Notfallkonto ADMIN ist kein Linux-Dateibenutzer. Nicht eindeutig prüfbare Freigaberegeln werden gesperrt.</p></div>')
        return ctx.page(T('Offline-Dateien'),body,'Netzwerk')
