"""Token-isolated desktop archives. No server backup execution or extraction."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import contextlib,datetime,fcntl,hashlib,json,os,re,shutil,time,uuid,tempfile,threading,html,subprocess
from pathlib import Path
from flask import request,jsonify,send_file,session,after_this_request,g
import server_settings
CHUNK=4*1024*1024
RESERVE=2*1024**3
QUOTA=100*1024**3
ACTIVE={}
def settings():return server_settings.read(server_settings.CONFIG_DIR/'desktop-backup.json')
def guard():
    from .daily import backup_uuid,verify_backup_uuid
    conf=settings()
    if not conf.get('enabled'):raise ValueError('Client-Backups sind noch nicht eingerichtet. Manager-Administrator: Backup & Recovery → Desktop-Clients.')
    verify_backup_uuid(conf,backup_uuid())
    return conf
def get_blockers():
    from modules.offline_files import blockers
    rows=blockers()
    if ACTIVE:rows.append(dict(source='Client-Backup',type='client-backup',title='Desktop-Übertragung aktiv',reason='Sicherung oder Wiederherstellung läuft',priority=95,url='/backup/desktop'))
    try:
        root=direct(Path(server_settings.get('system_backup_root'))/'desktop-client-backup')
        if any(not p.is_symlink() and time.time()-p.stat().st_mtime<180 for p in root.glob('*/.upload-*')):
            rows.append(dict(source='Client-Backup',type='client-backup',title='Client-Sicherung wird übertragen',reason='Letzter Abschnitt vor weniger als drei Minuten',priority=95,url='/backup/desktop'))
    except (OSError,ValueError):pass
    return rows

def direct(path):
    path=Path(path).absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Unsicherer Sicherungspfad.')
    return path

def base(cid):
    root=direct(server_settings.get('system_backup_root'))
    if not root.is_dir():raise ValueError('Backup-Hauptordner fehlt. Administrator muss das Speicherziel prüfen.')
    result=direct(root/'desktop-client-backup'/str(int(cid)))
    result.mkdir(parents=True,exist_ok=True,mode=0o700)
    return result

def identifier(value):
    if not re.fullmatch('[a-f0-9]{32}',value or ''):raise ValueError('Ungültige Sicherungskennung.')
    return value

def save(path,data):
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

@contextlib.contextmanager
def locked(root):
    fd=os.open(direct(root/'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:fcntl.flock(fd,fcntl.LOCK_EX);yield
    finally:os.close(fd)

def listing(root):
    rows=[]
    for path in root.glob('*/manifest.json'):
        try:
            if path.parent.name.startswith('.') or path.is_symlink():continue
            m=json.loads(path.read_text());identifier(m['id']);archive=direct(path.parent/'files.zip')
            if archive.is_file() or m.get('format')=='client-cas-zip-v1':
                rows.append({k:v for k,v in m.items() if k!='chunks'})
        except (ValueError,OSError,KeyError):continue
    return sorted(rows,key=lambda x:x['created'],reverse=True)

def register(app,ctx):
    @app.get('/api/account/access')
    def account_backup_access():
        p=g.auth_principal
        return jsonify(username=p['name'],role=p['role'],backup=p['role'] in ('admin','user'),restore=True,csrf=session['auth_csrf'])

    @app.route('/api/account/backup',methods=['GET','POST'])
    @app.route('/api/clients/backup',methods=['GET','POST'])
    def desktop_backup_api():
        if request.path=='/api/account/backup':
            # Separate namespace: never reuse a machine profile's positive ID.
            p=g.auth_principal
            identity=p['kind']+':'+p['name']+':'+str(p.get('uid',''))
            agent={'id':-int(hashlib.sha256(identity.encode()).hexdigest(),16)}
        else:
            from modules.heimnetz_clients import agent_by_token
            agent=agent_by_token(ctx)
        if agent is None:return jsonify(error='Client-Anmeldung erforderlich.'),401
        try:
            conf=guard();quota=int(conf.get('quota_gib',100))*1024**3
            root=base(agent['id']);action=request.args.get('action','list')
            if request.method=='POST':
                limit=32*1024**2 if action=='cas-finish' else (CHUNK if action in ('part','block-put') else 65536)
                if request.content_length is None or not 0<=request.content_length<=limit:raise ValueError('Anfragegröße fehlt oder ist zu groß.')
            activity=uuid.uuid4().hex;ACTIVE[activity]=True
            @after_this_request
            def release(response):
                response.direct_passthrough=False
                response.call_on_close(lambda:ACTIVE.pop(activity,None))
                response.headers['Cache-Control']='no-store'
                return response
            from . import chunks
            import sys
            if action.startswith(('cas-','block-')):return chunks.handle(root,action,quota,sys.modules[__name__])
            if request.method=='GET':
                if action=='list':return jsonify(backups=listing(root),quota_bytes=quota,scope='own-client',capabilities=['stream-zip-v1','system-cas-v1'])
                if action=='download':
                    sid=identifier(request.args.get('id'));folder=direct(root/sid)
                    m=json.loads(direct(folder/'manifest.json').read_text())
                    if m.get('format')==chunks.FORMAT:return chunks.download(root,m,sys.modules[__name__])
                    response=send_file(direct(folder/'files.zip'),as_attachment=True,download_name='Client-'+sid+'.zip',conditional=True)
                    response.headers['X-Backup-SHA256']=m['sha256'];return response
                raise ValueError('Unbekannte Aktion.')
            with locked(root):
                # Interrupted uploads remain resumable for 24h, then are removed.
                for old in root.glob('.upload-*'):
                    if not old.is_symlink() and old.stat().st_mtime < time.time()-86400:shutil.rmtree(old)
                if action=='begin':
                    data=request.get_json();stream=data.get('stream') is True;size=int(data['bytes']);sha=str(data['sha256'])
                    if not ((stream and size==0 and sha=='') or (not stream and 0<size<=quota and re.fullmatch('[a-f0-9]{64}',sha))):raise ValueError('Archivgröße oder Prüfsumme ungültig.')
                    used=chunks.used(root)
                    if used+size>quota:raise ValueError('Sicherungslimit pro Client erreicht. Administrator kontaktieren.')
                    if shutil.disk_usage(root).free<size+RESERVE:raise ValueError('Zu wenig freier Speicher am Server.')
                    if len(listing(root))>=500:raise ValueError('Maximal 500 Sicherungsstände. Administrator muss ältere Stände archivieren.')
                    if list(root.glob('.upload-*')):raise ValueError('Es besteht eine unvollständige Übertragung. Über „Übertragung verwerfen“ freigeben.')
                    sid=uuid.uuid4().hex;folder=root/('.upload-'+sid);folder.mkdir(mode=0o700)
                    m=dict(id=sid,bytes=size,sha256=sha,received=0,stream=stream,created=datetime.datetime.now().astimezone().isoformat(),name=str(data.get('name','Dateisicherung'))[:120],format='client-zip-v1')
                    save(folder/'manifest.json',m);(folder/'files.zip').touch(mode=0o600)
                    return jsonify(id=sid,chunk_bytes=CHUNK)
                if action=='cancel':
                    for folder in root.glob('.upload-*'):
                        if not folder.is_symlink():shutil.rmtree(folder)
                    removed=chunks.collect_unused(root,sys.modules[__name__])
                    return jsonify(ok=True,unused_blocks_removed=removed)
                sid=identifier(request.args.get('id'));folder=direct(root/('.upload-'+sid));m=json.loads(direct(folder/'manifest.json').read_text())
                archive=direct(folder/'files.zip')
                if action=='part':
                    offset=int(request.args.get('offset','-1'));size=request.content_length
                    if size is None or not 0<size<=CHUNK or offset!=m['received'] or (not m.get('stream') and offset+size>m['bytes']):raise ValueError('Ungültiger Übertragungsabschnitt.')
                    used=chunks.used(root)
                    if used+size>quota:raise ValueError('Sicherungslimit pro Client erreicht.')
                    if shutil.disk_usage(root).free<size+RESERVE:raise ValueError('Speicherreserve erreicht.')
                    data=request.stream.read(size+1)
                    if len(data)!=size:raise ValueError('Unvollständiger Abschnitt.')
                    with archive.open('r+b') as f:f.seek(offset);f.write(data);f.truncate();f.flush();os.fsync(f.fileno())
                    m['received']+=size;save(folder/'manifest.json',m);os.utime(folder,None)
                    return jsonify(received=m['received'])
                if action=='finish':
                    if m.get('stream'):
                        data=request.get_json();size=int(data['bytes']);sha=str(data['sha256'])
                        if size!=m['received'] or size<=0 or not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('Streaming-Abschluss ungültig.')
                        m.update(bytes=size,sha256=sha)
                    if m['received']!=m['bytes']:raise ValueError('Übertragung unvollständig.')
                    h=hashlib.sha256()
                    with archive.open('rb') as f:
                        for part in iter(lambda:f.read(CHUNK),b''):h.update(part)
                    if h.hexdigest()!=m['sha256']:raise ValueError('Prüfsumme stimmt nicht.')
                    import zipfile
                    if not zipfile.is_zipfile(archive):raise ValueError('Kein ZIP-Archiv.')
                    save(folder/'manifest.json',m)
                    folder.rename(root/sid);return jsonify(ok=True,id=sid)
                raise ValueError('Unbekannte Aktion.')
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError) as exc:
            # Never disclose server paths or OS exception detail to client tokens.
            text=str(exc) if isinstance(exc,ValueError) else 'Sicherung nicht verfügbar. Eingaben oder Server-Speicher prüfen.'
            return jsonify(error=text),400

    @app.route('/backup/desktop',methods=['GET','POST'])
    def desktop_backup_admin():
        conf=settings();message=''
        if request.method=='POST':
            try:
                from .daily import backup_uuid
                enabled=request.form.get('enabled')=='yes';quota=int(request.form.get('quota_gib','100'))
                if not 1<=quota<=10000:raise ValueError('Limit: 1 bis 10000 GiB pro Client.')
                conf=dict(enabled=enabled,quota_gib=quota,filesystem_uuid=backup_uuid())
                server_settings.atomic(server_settings.CONFIG_DIR/'desktop-backup.json',conf);message='Gespeichert; Backup-Dateisystem per UUID gebunden.'
            except (ValueError,OSError,subprocess.SubprocessError) as exc:message=str(exc)
        e=lambda v:html.escape(str(v),quote=True)
        body=_ui_html("<div class='card'><h2>Desktop-Client-Sicherungen</h2><p>Jeder Benutzer benötigt einen eigenen Eintrag unter Client-Agenten und sein eigenes JSON-Profil. Der Client-Token ermöglicht nur Zugriff auf die zugehörigen Client-Sicherungen, niemals auf Server-Sicherungen. Ein Profil nicht zwischen Benutzern teilen.</p><p>Speicherziel: ")+e(server_settings.get('system_backup_root'))+_ui_html("/desktop-client-backup · <a href='/settings/server-paths'>Server- und Modulpfade</a></p><p>Dateisicherungen und logische Linux-Systemstände über HTTPS. Client ab 0.4.0 überträgt bei Systemsicherungen nur neue 4-MiB-Blöcke; identische Blöcke bleiben pro Konto/Profil gemeinsam gespeichert. Jeder Stand ist vollständig abrufbar. Einzeldateien in neue Ordner; System/Komponenten aus dem Live-System. Kein Festplattenabbild; Partitionierung und Bootloader separat. Unvollständige Übertragungen werden nach 24 Stunden bei der nächsten Client-Anfrage bereinigt.</p><p>")+e(_ui_text(message))+_ui_html("</p><form method='post'><input type='hidden' name='auth_csrf' value='")+e(session.get('auth_csrf',''))+_ui_html("'><label><input type='checkbox' name='enabled' value='yes' ")+('checked' if conf.get('enabled') else '')+_ui_html("> Client-Backups aktivieren</label><label>Speicherlimit pro Client (GiB) <input type='number' name='quota_gib' min='1' max='10000' value='")+e(conf.get('quota_gib',100))+_ui_html("'></label><button>Speichern und Datenträger bestätigen</button></form><p>Server-Backups bleiben ausschließlich dem Manager-Administrator vorbehalten. Private HTTPS-Einrichtung wird empfohlen.</p><p><a href='/backup'>Backup & Recovery</a> · <a href='/clients'>Client-Agenten und Profile</a> · <a href='/settings/https'>HTTPS-Zugang</a></p></div>")
        root=direct(Path(server_settings.get('system_backup_root'))/'desktop-client-backup')
        body+=_ui_html("<div class='card'><h3>Gespeicherte Client-Sicherungen</h3><table><tr><th>Konto / Client</th><th>Stände</th><th>Logische Größe aller Stände</th><th>Belegter Speicher</th></tr>")
        from . import chunks
        labels={}
        try:
            auth=app.extensions['server_manager_auth'].read();name=auth['username']
            labels[str(-int(hashlib.sha256(('local:'+name+':').encode()).hexdigest(),16))]=name
            for name,row in app.extensions['server_manager_users'].read()['users'].items():
                labels[str(-int(hashlib.sha256(('system:'+name+':'+str(row['uid'])).encode()).hexdigest(),16))]=name
        except (KeyError,ValueError,OSError):pass
        if root.is_dir():
            for folder in sorted(root.iterdir()):
                if re.fullmatch('-?[0-9]+',folder.name) and folder.is_dir() and not folder.is_symlink():
                    rows=listing(folder);body+=_ui_html('<tr><td>')+e(labels.get(folder.name,_ui_text('Konto (nicht mehr zugeordnet)') if folder.name.startswith('-') else 'Client '+folder.name))+_ui_html('</td><td>')+str(len(rows))+_ui_html('</td><td>')+str(sum(r['bytes'] for r in rows)//1024**2)+_ui_html(' MiB</td><td>')+str(chunks.used(folder)//1024**2)+_ui_html(' MiB</td></tr>')
        body+=_ui_html('</table></div>')
        return ctx.page(_ui_text('Client-Sicherungen'),body,'Daten')
