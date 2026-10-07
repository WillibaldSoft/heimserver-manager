"""Native Pi-hole updates with bound configuration/SQLite backup evidence."""
import contextlib,hashlib,json,os,shutil,signal,sqlite3,subprocess,time
from pathlib import Path
CONFIG=Path('/etc/pihole')

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def snapshot(manager,workdir):
    target=Path(workdir)/'pihole-native';target.mkdir(mode=0o700);os.chmod(target,0o700)
    if not CONFIG.is_dir() or CONFIG.is_symlink():raise ValueError('Pi-hole-Konfigurationsordner fehlt oder ist ein Link.')
    # Current configuration and active databases; historical caches/backups are excluded.
    paths=[p for p in CONFIG.iterdir() if p.is_symlink() or not p.is_dir()]
    if (CONFIG/'hosts').is_dir() and not (CONFIG/'hosts').is_symlink():paths+=list((CONFIG/'hosts').rglob('*'))
    required={'pihole.toml','gravity.db','pihole-FTL.db'}
    if not all((CONFIG/name).is_file() for name in required):raise ValueError('Pi-hole-v6-Konfiguration oder Datenbanken fehlen.')
    needed=sum(p.stat().st_size for p in paths if p.is_file())
    if shutil.disk_usage(target).free<needed*2+256*1024**2:raise ValueError('Zu wenig Platz für die Pi-hole-Sicherung.')
    inventory={}
    for source in paths:
        if source.name.endswith(('-wal','-shm','-journal')):continue
        if source.is_symlink():raise ValueError('Symbolischer Link in Pi-hole-Konfiguration; Sicherung manuell prüfen.')
        if source.is_dir():continue
        if not source.is_file():raise ValueError('Ungewöhnlicher Dateityp in Pi-hole-Konfiguration.')
        relative=str(source.relative_to(CONFIG));dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if source.suffix=='.db':
            deadline=time.monotonic()+120
            def progress(*args):
                if time.monotonic()>deadline:raise ValueError('Zeitlimit bei Pi-hole-Datenbanksicherung.')
            with contextlib.closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,contextlib.closing(sqlite3.connect(dest)) as db:
                src.backup(db,pages=512,progress=progress)
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Pi-hole-Datenbanksicherung ist nicht konsistent.')
        else:shutil.copy2(source,dest)
        os.chmod(dest,0o600);inventory[relative]=sha(dest)
    versions=manager.installed_components()
    manifest=target/'snapshot.json';manifest.write_text(json.dumps(dict(schema=1,files=inventory,versions=versions)));os.chmod(manifest,0o600)
    return dict(ok=True,message='Pi-hole-Konfiguration, Zertifikate, lokale Hosts und SQLite-Datenbanken gesichert und geprüft.',pihole_native_schema=1,manifest=str(manifest),manifest_sha256=sha(manifest),versions=versions)

def backup_evidence(session):
    backup=session.get('backup_check',{}).get('backup',{}).get('backup',{})
    extra=backup.get('steps',{}).get('extra',{})
    if not backup.get('ok') or not extra.get('ok') or extra.get('pihole_native_schema')!=1:raise ValueError('Neues Backup vorbereiten: der alte Prepare-Lauf enthält keine geprüfte Pi-hole-Sicherung.')
    root=Path(backup['work_dir'])/'extra'/'pihole-native';manifest=root/'snapshot.json'
    if str(manifest)!=extra.get('manifest') or manifest.is_symlink() or sha(manifest)!=extra.get('manifest_sha256'):raise ValueError('Pi-hole-Sicherungsnachweis fehlt oder wurde verändert.')
    data=json.loads(manifest.read_text());files=data.get('files',{})
    if not {'pihole.toml','gravity.db','pihole-FTL.db'}.issubset(files):raise ValueError('Pi-hole-Sicherung ist unvollständig.')
    for name,digest in files.items():
        rel=Path(name)
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Ungültiger Sicherungspfad.')
        path=root/rel
        if path.is_symlink() or sha(path)!=digest:raise ValueError('Pi-hole-Sicherungsdatei fehlt oder wurde verändert.')
    return data

def dns_ok():
    result=subprocess.run(['dig','@127.0.0.1','pi.hole','A','+time=2','+tries=1'],capture_output=True,text=True,timeout=5)
    return result.returncode==0 and 'status: NOERROR' in result.stdout

def run_updater(log):
    with log.open('w') as output:
        os.chmod(log,0o600)
        process=subprocess.Popen(['/usr/local/bin/pihole','-up'],stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',TERM='dumb'))
        try:return process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            raise ValueError('Pi-hole-Update hat das Zeitlimit überschritten; Protokoll prüfen.') from None

def log_tail(log):
    if not log or not log.exists():return ''
    with log.open('rb') as stream:
        stream.seek(max(0,log.stat().st_size-20000))
        return stream.read().decode('utf-8','replace')

def execute(manager,session):
    def result(ok,action,status,message,changed=False,**extra):
        return dict(ok=ok,supported=True,message=message,steps=[dict(id=action,action=action,title='Pi-hole · '+action,status=status,message=message,changed=changed,**extra)])
    if not session or session.get('simulate',True):return result(True,'simulation','simulated','Simulation: Sicherung prüfen, pihole -up ausführen, Versionen und DNS prüfen.')
    from .settings import bool_setting
    if not bool_setting('update_execution_enabled',False) or not session.get('execution_gate_passed'):
        return result(False,'gate','blocked','Bestätigter Echtlauf und bestandene Sicherheitsprüfung erforderlich.')
    changed=False;log=None
    try:
        evidence=backup_evidence(session)
        current=manager.installed_components()
        if evidence['versions']!=current:raise ValueError('Pi-hole-Version seit der Sicherung verändert. Neues Backup vorbereiten.')
        check=manager.update_check()
        if not check.get('ok'):raise ValueError(check.get('message','Versionsprüfung fehlgeschlagen.'))
        if not dns_ok():raise ValueError('Lokale DNS-Prüfung bereits vor Update fehlgeschlagen. Pi-hole zuerst prüfen.')
        manager._expected_versions=check['details']['available']
        if not check.get('update_available'):return result(True,'preflight','skipped','Pi-hole ist bereits aktuell.')
        log=Path(session['run_dir'])/'pihole-update.log'
        session.update(current_action='pihole_update',current_step=1)
        state=Path(session['run_dir'])/'session.json';temp=state.with_suffix('.tmp');temp.write_text(json.dumps(session));os.chmod(temp,0o600);os.replace(temp,state)
        changed=True
        if run_updater(log):raise ValueError('pihole -up meldet einen Fehler. Änderungen können teilweise erfolgt sein; keine automatische Rücknahme.')
        return result(True,'pihole_update','executed','Offizieller Pi-hole-Updater beendet. Versionen, Dienst und DNS werden anschließend geprüft.',True,log_file=str(log),output=log_tail(log))
    except Exception as exc:
        tail=log_tail(log)
        return result(False,'pihole_update' if changed else 'preflight','failed' if changed else 'blocked',str(exc),changed,output=tail,log_file=str(log) if log else None)
