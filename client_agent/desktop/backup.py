"""User file snapshots, authenticated transport and non-overwriting restore."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import contextlib,uuid,subprocess
import io
import datetime,hashlib,json,os,stat,tempfile,urllib.request,urllib.parse,urllib.error,zipfile,shutil
from pathlib import Path
import core
CHUNK=4*1024*1024
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

# Account cookies stay in memory only and are bound to this exact server URL.
ACCOUNT=None
ACCOUNT_REQUIRED=False

def account_logout():
    global ACCOUNT,ACCOUNT_REQUIRED
    ACCOUNT=None;ACCOUNT_REQUIRED=True

def account_login(username,password):
    global ACCOUNT,ACCOUNT_REQUIRED
    import http.cookiejar
    from html.parser import HTMLParser
    cfg=core.validate(core.load());url=cfg['SERVER_URL']
    if not url.startswith('https://'):raise core.Error(tr('Manager-Anmeldung benötigt HTTPS mit gültigem Zertifikat.'))
    account_logout()
    opener=urllib.request.build_opener(NoRedirect,urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    class Form(HTMLParser):
        csrf=''
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='input' and a.get('name')=='auth_csrf':self.csrf=a.get('value','')
    f=Form()
    with opener.open(url+'/login',timeout=30) as r:f.feed(r.read().decode())
    if not f.csrf:raise core.Error(tr('Anmeldeformular nicht erkannt.'))
    payload=urllib.parse.urlencode(dict(username=username,password=password,auth_csrf=f.csrf,next='/api/account/access')).encode()
    try:
        opener.open(urllib.request.Request(url+'/login',payload,{'Origin':url}),timeout=30).close()
        raise core.Error(tr('Anmeldung nicht bestätigt.'))
    except urllib.error.HTTPError as exc:
        if exc.code!=303:raise core.Error(tr('Anmeldung abgelehnt. Konto, Passwort und Freigabe prüfen.')) from None
        exc.close()
    try:
        with opener.open(url+'/api/account/access',timeout=30) as response:access=json.load(response)
    except urllib.error.HTTPError:raise core.Error(tr('Client-Sicherungen sind für dieses Konto nicht freigegeben.')) from None
    ACCOUNT=(url,opener,access)
    return access

def call(action,data=None,query='',binary=False):
    cfg=core.validate(core.load());url=cfg['SERVER_URL'];headers={}
    if ACCOUNT:
        server,opener,access=ACCOUNT
        if server!=url:raise core.Error(tr('Server geändert. Erneut am Manager anmelden.'))
        path='/api/account/backup';headers['X-Server-Manager-CSRF']=access['csrf']
        if data is not None and not access.get('backup'):raise core.Error(tr('Nur Lesen: Sicherung nicht freigegeben.'))
    else:
        if ACCOUNT_REQUIRED:raise core.Error(tr('Bitte zuerst wieder am Manager anmelden.'))
        opener=urllib.request.build_opener(NoRedirect)
        path='/api/clients/backup';headers['Authorization']='Bearer '+cfg['TOKEN']
        import device_identity
        headers.update(device_identity.headers())
    if isinstance(data,dict):data=json.dumps(data).encode();headers['Content-Type']='application/json'
    elif data is not None:headers['Content-Type']='application/octet-stream'
    req=urllib.request.Request(url+path+'?action='+action+query,data,headers)
    try:
        response=opener.open(req,timeout=300)
        if binary:return response
        with response:return json.load(response)
    except urllib.error.HTTPError as e:
        try:message=json.loads(e.read(4096)).get('error',tr('Anfrage abgelehnt.'))
        except Exception:message=tr('Anfrage abgelehnt (HTTP ')+str(e.code)+').'
        if ACCOUNT:
            if e.code==401:message=tr('Anmeldung abgelaufen. Erneut am Manager anmelden.')
            elif message=='permission_denied':message=tr('Diese Aktion ist für dein Konto nicht freigegeben.')
            elif message in ('cross_origin_request','csrf_required'):message=tr('Sicherheitsprüfung der Anfrage fehlgeschlagen. Client aktualisieren und erneut anmelden.')
        raise core.Error(message) from None

def finish_upload(sid,size,sha,progress=lambda text:None):
    import time
    try:return call('finish',dict(bytes=size,sha256=sha),'&id='+sid)
    except (core.Error,OSError) as original:
        if isinstance(original,core.Error) and not any(code in str(original) for code in ('HTTP 502','HTTP 503','HTTP 504')):raise
        # The proxy can time out while the server is still hashing. Never
        # repeat finish or report success without matching completed metadata.
        for attempt in range(180):
            progress(tr('Abschlussantwort fehlt; fertigen Serverstand prüfen …'))
            try:
                for item in call('list').get('backups',[]):
                    if item.get('id')==sid and item.get('bytes')==size and item.get('sha256')==sha:return item
            except (core.Error,OSError):pass
            time.sleep(5)
        raise core.Error(tr('Abschluss nicht bestätigt. Sicherungsstände später aktualisieren; Übertragung nicht vorschnell verwerfen. ')+str(original)) from original

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(CHUNK),b''):h.update(block)
    return h.hexdigest()

class UploadStream(io.RawIOBase):
    def __init__(self,sid,progress):
        self.sid=sid;self.progress=progress;self.buffer=bytearray();self.offset=0;self.hash=hashlib.sha256()
    def writable(self):return True
    def seekable(self):return False
    def tell(self):return self.offset+len(self.buffer)
    def write(self,data):
        count=len(data);self.hash.update(data)
        view=memoryview(data)
        while view:
            n=min(CHUNK-len(self.buffer),len(view));self.buffer.extend(view[:n]);view=view[n:]
            if len(self.buffer)==CHUNK:self.flush()
        return count
    def flush(self):
        if self.buffer:
            call('part',bytes(self.buffer),'&id='+self.sid+'&offset='+str(self.offset))
            self.offset+=len(self.buffer);self.buffer.clear()
            self.progress(tr('Direkt übertragen: ')+str(self.offset//1024**2)+' MiB')


def usb_target(folder):
    mount=json.loads(subprocess.check_output(['findmnt','-J','-T',str(folder),'-o','TARGET,FSTYPE'],text=True))['filesystems'][0]
    mountpoint=Path(mount['target']).resolve()
    if mountpoint==Path('/') or mount['fstype'] in ('nfs','nfs4','cifs','smb3','tmpfs','overlay') or folder.stat().st_dev==Path('/').stat().st_dev:
        raise core.Error(tr('Eingehängte USB-/Datenplatte wählen; das Systemlaufwerk ist als Ziel gesperrt.'))
    return folder.stat().st_dev


class LocalStream:
    def __init__(self,folder,name):
        self.folder=Path(folder).resolve()
        if not self.folder.is_dir():raise core.Error(tr('Lokales Sicherungsziel fehlt.'))
        self.device=usb_target(self.folder)
        label='Client-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.partial=self.folder/('.'+label+'.partial');self.final=self.folder/(label+'.zip')
        self.file=self.partial.open('xb');os.chmod(self.partial,0o600)
        self.offset=0;self.hash=hashlib.sha256();self.name=name
    def tell(self):return self.offset
    def seekable(self):return False
    def write(self,data):
        if self.folder.stat().st_dev!=self.device:raise core.Error(tr('Zieldatenträger wurde getrennt.'))
        if shutil.disk_usage(self.folder).free<len(data)+512*1024**2:raise core.Error(tr('Speicherreserve am Sicherungsziel erreicht.'))
        size=self.file.write(data);self.offset+=size;self.hash.update(data[:size]);return size
    def flush(self):self.file.flush()
    def finish(self):
        self.file.flush();os.fsync(self.file.fileno());self.file.close()
        manifest=dict(format='client-zip-v1',bytes=self.offset,sha256=self.hash.hexdigest(),name=self.name,created=datetime.datetime.now().astimezone().isoformat())
        meta=self.partial.with_suffix('.json');meta.write_text(json.dumps(manifest));os.chmod(meta,0o600)
        self.partial.rename(self.final);meta.rename(self.final.with_suffix('.json'))
    def abort(self):
        self.file.close()
        # Remove only the exact incomplete file created by this operation.
        if self.folder.exists() and self.folder.stat().st_dev==self.device:self.partial.unlink(missing_ok=True)


def create(source,progress=lambda s:None,destination=None):
    source=Path(source).resolve()
    if not source.is_dir() or source==Path('/'):raise core.Error(tr('Einen Benutzerordner wählen, nicht das gesamte System.'))
    if destination is not None:
        folder=Path(destination).resolve()
        if folder==source or folder.is_relative_to(source):raise core.Error(tr('Sicherungsziel darf nicht im gesicherten Ordner liegen.'))
        target=LocalStream(folder,source.name);sid=None
    else:
        if 'stream-zip-v1' not in call('list').get('capabilities',[]):
            raise core.Error(tr('Manager benötigt das Streaming-Backup-Update. Es wird kein lokales Zwischenarchiv erstellt.'))
        job=call('begin',dict(bytes=0,sha256='',name=source.name,stream=True));sid=job['id']
        target=UploadStream(sid,progress)
    try:
        skipped=0;count=0
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
            for root,dirs,files in os.walk(source,followlinks=False):
                omitted=[d for d in dirs if (Path(root)/d).is_symlink() or os.path.ismount(Path(root)/d)]
                skipped+=len(omitted);dirs[:]=[d for d in dirs if d not in omitted]
                if Path(root)!=source:
                    zi=zipfile.ZipInfo('files/'+str(Path(root).relative_to(source)).replace(os.sep,'/')+'/');zi.external_attr=(stat.S_IFDIR|0o700)<<16;archive.writestr(zi,b'')
                for name in files:
                    path=Path(root)/name;before=path.lstat()
                    if not stat.S_ISREG(before.st_mode):skipped+=1;continue
                    # O_NOFOLLOW rejects replacement with symlinks while collecting.
                    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                    with os.fdopen(fd,'rb') as f:
                        info=os.fstat(f.fileno())
                        if (info.st_dev,info.st_ino)!=(before.st_dev,before.st_ino):raise core.Error(tr('Quelle wurde während der Sicherung geändert.'))
                        zi=zipfile.ZipInfo('files/'+str(path.relative_to(source)).replace(os.sep,'/'))
                        zi.compress_type=zipfile.ZIP_DEFLATED;zi.external_attr=(stat.S_IFREG|(info.st_mode&0o777))<<16
                        when=datetime.datetime.fromtimestamp(info.st_mtime)
                        if 1980<=when.year<=2107:zi.date_time=when.timetuple()[:6]
                        with archive.open(zi,'w',force_zip64=True) as out:shutil.copyfileobj(f,out,CHUNK)
                        after=os.fstat(f.fileno())
                        if (info.st_size,info.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise core.Error(tr('Datei während der Sicherung verändert; bitte erneut sichern.'))
                    count+=1;progress(tr('Dateien sammeln: ')+str(count))
            archive.writestr('hsm-backup.json',json.dumps({'format':'client-zip-v1','source_name':source.name,'files':count,'skipped_special_files':skipped,'scope':'user-files'}))
        target.flush()
        progress(tr('Server prüft das Archiv …'))
        if sid:finish_upload(sid,target.offset,target.hash.hexdigest(),progress)
        else:target.finish()
        return tr('Sicherung abgeschlossen: ')+str(count)+tr(' Dateien. Spezialdateien/Links nicht gesichert: ')+str(skipped)+tr('. Kein lokales Zwischenarchiv.')
    except Exception:
        # Prevent destructor flush from retrying a failed upload.
        if sid:target.buffer.clear()
        else:target.abort()
        raise

def local_item(path):
    path=Path(path).resolve()
    meta=path.with_suffix('.json')
    if not path.is_file() or not meta.is_file():raise core.Error(tr('Archiv und zugehörige JSON-Prüfsumme müssen zusammen vorliegen.'))
    item=json.loads(meta.read_text());item['local_path']=str(path);item['id']=path.stem
    if item.get('format')!='client-zip-v1' or item.get('bytes')!=path.stat().st_size:raise core.Error(tr('Lokales Archiv passt nicht zu seinen Metadaten.'))
    return item


def restore(item,target,progress=lambda s:None,selected=''):
    target=Path(target).absolute()
    if target.exists() or '..' in target.parts or any(p.is_symlink() for p in target.parents):raise core.Error(tr('Einen neuen Zielordner ohne symbolische Links wählen.'))
    if not target.parent.is_dir():raise core.Error(tr('Übergeordneter Zielordner fehlt.'))
    local=item.get('local_path')
    with (contextlib.nullcontext(None) if local else tempfile.TemporaryDirectory(prefix='hsm-restore-')) as tmp:
        if local:
            archive=Path(local)
            if archive.stat().st_size!=item['bytes'] or digest(archive)!=item['sha256']:raise core.Error(tr('Prüfsumme stimmt nicht. Keine Wiederherstellung.'))
        else:
            archive=Path(tmp)/'files.zip';h=hashlib.sha256()
            if shutil.disk_usage(tmp).free<int(item['bytes'])+512*1024**2:
                raise core.Error(tr('Zu wenig temporärer Speicher für dieses alte ZIP-Restore-Verfahren. Kein Download gestartet.'))
            with call('download',query='&id='+item['id'],binary=True) as response,archive.open('wb') as out:
                count=0
                for part in iter(lambda:response.read(CHUNK),b''):
                    if count+len(part)>int(item['bytes']) or shutil.disk_usage(tmp).free<len(part)+512*1024**2:raise core.Error(tr('Downloadgröße oder temporäre Speicherreserve überschritten.'))
                    out.write(part);h.update(part);count+=len(part);progress(tr('Heruntergeladen: ')+str(count//1024**2)+' MiB')
            if h.hexdigest()!=item['sha256']:raise core.Error(tr('Prüfsumme stimmt nicht. Keine Wiederherstellung.'))
        with zipfile.ZipFile(archive) as z:
            items=[];names=set();total=0
            for info in z.infolist():
                name=info.filename
                if name=='hsm-backup.json':continue
                isdir=info.is_dir();parts=name.rstrip('/').split('/')
                if not name.startswith('files/') or any(p in ('','..','.') for p in parts) or '\\' in name or ':' in name or stat.S_ISLNK(info.external_attr>>16):raise core.Error(tr('Unsicherer Archiveintrag.'))
                relative=Path(*parts[1:]);key=str(relative)
                if key in names:raise core.Error(tr('Doppelter Archiveintrag.'))
                names.add(key)
                wanted=selected.strip('/')
                if not wanted or key==wanted or key.startswith(wanted+'/'):
                    items.append((info,relative));total+=info.file_size
            if not items:raise core.Error(tr('Ausgewählte Datei bzw. Ordner nicht im Archiv gefunden.'))
            if shutil.disk_usage(target.parent).free<total+128*1024**2:raise core.Error(tr('Zu wenig freier Platz für die Rücksicherung.'))
            target.mkdir(mode=0o700)
            for index,(info,relative) in enumerate(items):
                dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                if info.is_dir():dest.mkdir(exist_ok=True);continue
                with z.open(info) as src,dest.open('xb') as out:shutil.copyfileobj(src,out,CHUNK)
                when=datetime.datetime(*info.date_time).timestamp();os.utime(dest,(when,when))
                os.chmod(dest,(info.external_attr>>16)&0o700 or 0o600)
                progress(tr('Wiederherstellen: ')+str(index+1)+' / '+str(len(items)))
    return tr('Wiederhergestellt in ')+str(target)+tr('. Bei Abbruch bleibt ein möglicher Teilstand dort erhalten.')
