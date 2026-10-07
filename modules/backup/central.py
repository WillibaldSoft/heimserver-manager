"""Central configuration snapshots and downloadable portable client bundles."""
import time,stat
import datetime,grp,hashlib,io,json,os,pwd,re,shutil,socket,subprocess,tempfile,threading,uuid,zipfile
from pathlib import Path
import server_settings as cfg
LOCK=threading.Lock()
RUNNING=False

def identities():
    result=[]
    for u in pwd.getpwall():
        if 1000<=u.pw_uid<60000 and u.pw_shell not in ('/usr/sbin/nologin','/bin/false'):
            result.append(dict(user=u.pw_name,uid=u.pw_uid,gid=u.pw_gid,group=grp.getgrgid(u.pw_gid).gr_name,home=u.pw_dir))
    return sorted(result,key=lambda x:x['user'])

def identifier(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',value):raise ValueError('Rechnerkennung: 1–64 Buchstaben, Ziffern, Punkt, Bindestrich oder Unterstrich.')
    return value

def bundle(client,user,share):
    identifier(client)
    identity=next((x for x in identities() if x['user']==user),None)
    if identity is None:raise ValueError('Serverbenutzer ist nicht vorhanden.')
    if not re.fullmatch(r'//[A-Za-z0-9.-]+/[A-Za-z0-9_ -]+',share):raise ValueError('SMB-Adresse im Format //SERVER/Backup angeben.')
    base=Path(__file__).resolve().parents[2]/'tools/backup'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name in ('backup_client.py','identity_sync.py','install-client.sh','migration.sh','README.md'):z.write(base/name,'Server-Backup/'+name)
        z.writestr('Server-Backup/client.json',json.dumps(dict(client=client,user=user,share=share,server_identity=identity),ensure_ascii=False,indent=2))
    out.seek(0);return out

def root():
    p=Path(cfg.get('system_backup_root'));cfg.path_value(str(p))
    if not p.is_dir():raise ValueError('Backup-Hauptordner fehlt. Datenträger einbinden und Einstellungen prüfen.')
    return p

def provision(client,user):
    identifier(client)
    owner=next((u for u in identities() if u['user']==user),None)
    if not owner:raise ValueError('Serverbenutzer fehlt.')
    identifier(user)
    fd=directory_fd(root())
    try:
        for index,part in enumerate(['linux-client-backup',client,user]):
            created=False
            try:os.mkdir(part,0o700 if index==2 else 0o755,dir_fd=fd);created=True
            except FileExistsError:pass
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
            if created:
                os.fchmod(fd,0o700 if index==2 else 0o755)
                if index==2:os.fchown(fd,owner['uid'],owner['gid'])
            elif index==2:
                st=os.fstat(fd)
                if st.st_uid!=owner['uid'] or st.st_mode & 0o077:raise ValueError('Vorhandener Clientordner hat abweichende Rechte. Bitte unter Freigaben prüfen.')
    finally:os.close(fd)

def state_file():return cfg.STATE_DIR/'central-backup-job.json'
def status():
    try:return json.loads(state_file().read_text())
    except FileNotFoundError:return {}
def active():
    from .daily import RUNNING as daily_running
    from .external import active as external_active
    from .client_api import get_blockers as desktop_blockers
    return RUNNING or daily_running or external_active() or bool(desktop_blockers())
def get_blockers(ctx=None):
    from .external import get_blockers as external_blockers
    from .daily import RUNNING as daily_running
    rows=[dict(source='Backup',type='backup',title='Server-Sicherung läuft',reason='Konfiguration wird archiviert und geprüft',priority=95,url='/backup/central')] if RUNNING or daily_running else []
    rows.extend(external_blockers())
    from .client_api import get_blockers as desktop_blockers
    rows.extend(desktop_blockers())
    try:fd=directory_fd(root()/'linux-client-backup')
    except (OSError,ValueError):return rows
    def sub(parent,name):return os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
    try:
        for client in os.listdir(fd)[:1000]:
            try:cf=sub(fd,client)
            except OSError:continue
            try:
                for user in os.listdir(cf)[:1000]:
                    try:uf=sub(cf,user)
                    except OSError:continue
                    try:
                        for name in os.listdir(uf)[:5000]:
                            if not re.fullmatch(r'\.active-[0-9a-f]{32}',name):continue
                            try:info=os.stat(name,dir_fd=uf,follow_symlinks=False)
                            except OSError:continue
                            if stat.S_ISREG(info.st_mode) and info.st_nlink==1 and -15<=time.time()-info.st_mtime<180:
                                rows.append(dict(source='Client-Backup',type='client-backup',title=client+' / '+user,reason='Backup-/Restore-Werkzeug aktiv (SMB-Lebenszeichen)',priority=95,url='/backup/central'))
                    finally:os.close(uf)
            finally:os.close(cf)
    finally:os.close(fd)
    return rows

def directory_fd(path):
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        return fd
    except BaseException:os.close(fd);raise

def publish(stage,destination,owner):
    fd=directory_fd(root())
    try:
        for index,part in enumerate(destination):
            final=index==len(destination)-1
            try:os.mkdir(part,0o700 if final else 0o755,dir_fd=fd)
            except FileExistsError:
                if final:raise ValueError('Sicherungsstand existiert bereits.')
            new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=new
            if final:os.fchmod(fd,0o700)
        for name in ('system.tar','manifest.json'):
            out=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
            with os.fdopen(out,'wb') as target,open(stage/name,'rb') as source:
                shutil.copyfileobj(source,target,4*1024*1024);target.flush();os.fsync(target.fileno());os.fchown(target.fileno(),owner['uid'],owner['gid'])
        os.fchown(fd,owner['uid'],owner['gid'])
    finally:os.close(fd)

def start(user):
    global RUNNING
    owner=next((u for u in identities() if u['user']==user),None)
    if not owner:raise ValueError('SMB-Eigentümer auswählen.')
    root()
    with LOCK:
        if active():raise ValueError('Eine Server-Sicherung läuft bereits.')
        RUNNING=True
    try:
        job=dict(id=uuid.uuid4().hex,state='running',started=datetime.datetime.now().astimezone().isoformat(),message='Konfiguration wird gesichert.')
        cfg.atomic(state_file(),job)
        threading.Thread(target=worker,args=(job,owner),name='central-backup',daemon=True).start()
    except BaseException:
        RUNNING=False;raise
    return job

def worker(job,owner):
    global RUNNING
    try:
        private=cfg.STATE_DIR/'backup-work';private.mkdir(mode=0o700,parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=private) as temp:
            stage=Path(temp);archive=stage/'system.tar'
            sources=['etc','usr/local',str(cfg.BASE_DIR).lstrip('/')]
            args=['tar','--create','--file',str(archive),'--format=pax','--numeric-owner','--acls','--xattrs','--one-file-system','--exclude=*.pyc','--exclude=*/__pycache__','--exclude=*/.git','--exclude=*/dist','--exclude='+str(root()).lstrip('/'),'--exclude='+str(cfg.STATE_DIR).lstrip('/')]
            subprocess.run(args+['-C','/','--']+sources,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=3600)
            h=hashlib.sha256()
            with archive.open('rb') as f:
                for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
            subprocess.run(['tar','--list','--file',str(archive)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=600)
            host=identifier(socket.gethostname().split('.')[0]);stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+job['id'][:8]
            meta=dict(format=1,kind='server-config',archive='system.tar',sha256=h.hexdigest(),client=host,user=owner['user'],source_uid=0,source_gid=0,created=job['started'],sources=sources,scope='Systemkonfiguration; keine Datenbanken, VM-Datenträger oder vollständige Systemsicherung')
            (stage/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
            destination=['linux-server-backup',host,stamp];publish(stage,destination,owner)
            job.update(state='completed',message='Archiv geprüft und gespeichert.',destination=str(root().joinpath(*destination)))
    except Exception as exc:
        job.update(state='failed',message=str(exc)[:1000])
    finally:
        job['finished']=datetime.datetime.now().astimezone().isoformat()
        try:cfg.atomic(state_file(),job)
        finally:RUNNING=False

def archive_fd(value):
    parts=value.split('/')
    if len(parts) not in (4,5) or parts[0] not in ('linux-client-backup','linux-server-backup'):raise ValueError('Ungültiger Sicherungspfad.')
    if (parts[0]=='linux-client-backup') != (len(parts)==5):raise ValueError('Ungültige Sicherungsstruktur.')
    for part in parts[1:-1]:identifier(part)
    if parts[-1] not in ('home.tar','system.tar','manifest.json'):raise ValueError('Keine Sicherungsdatei.')
    fd=directory_fd(root())
    try:
        for part in parts[:-1]:
            new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=new
        out=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        info=os.fstat(out)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:os.close(out);raise ValueError('Nur normale Archivdateien ohne Hardlinks.')
        return out,info
    finally:os.close(fd)

def inventory():
    result=[]
    def walk(fd,parts,depth):
        for name in sorted(os.listdir(fd))[:1000]:
            if len(result)>=200:return
            try:identifier(name);child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except (ValueError,OSError):continue
            try:
                if depth>1:walk(child,parts+[name],depth-1)
                else:
                    rel='/'.join(parts+[name]);mf,info=archive_fd(rel+'/manifest.json')
                    with os.fdopen(mf,'r') as stream:
                        if info.st_size>32768:continue
                        meta=json.load(stream)
                    archive=meta.get('archive')
                    if archive not in ('home.tar','system.tar'):continue
                    af,ai=archive_fd(rel+'/'+archive);os.close(af)
                    result.append(dict(path=rel+'/'+archive,client=meta.get('client',parts[1] if len(parts)>1 else ''),user=meta.get('user',''),kind=meta.get('kind',''),created=meta.get('created',name),bytes=ai.st_size))
            except (OSError,ValueError,TypeError):continue
            finally:os.close(child)
    for kind,depth in [('linux-client-backup',3),('linux-server-backup',2)]:
        try:fd=directory_fd(root()/kind)
        except (OSError,ValueError):continue
        try:walk(fd,[kind],depth)
        finally:os.close(fd)
    return sorted(result,key=lambda x:str(x['created']),reverse=True)
