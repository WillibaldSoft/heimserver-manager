"""Sequential daily snapshots. Local configuration only; no embedded host data."""
import datetime,fcntl,gzip,json,os,shutil,sqlite3,subprocess,threading,time,uuid
from pathlib import Path
import server_settings as cfg
LABELS={'oscam':'OSCam','nextcloud_config':'Nextcloud Config','nextcloud_apps':'Nextcloud Apps','nextcloud_db':'Nextcloud DB','server_manager':'Server Manager'}
RUNNING=False

def settings():return cfg.read(cfg.CONFIG_DIR/'daily-backup.json')
def state():return cfg.read(cfg.STATE_DIR/'daily-backup.json')
def save_state(value):cfg.atomic(cfg.STATE_DIR/'daily-backup.json',value)
def command(args,timeout=3600,**kwargs):return subprocess.run(args,check=True,timeout=timeout,**kwargs)
def root():return Path(cfg.get('system_backup_root'))/'daily_incremental'
def backup_uuid():
    result=command(['findmnt','--noheadings','--raw','--output','UUID','--target',str(Path(cfg.get('system_backup_root')).resolve())],timeout=15,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    value=result.stdout.strip()
    if not value or len(value.splitlines())!=1:
        raise ValueError('Backup-Dateisystem hat keine eindeutig erkennbare UUID. Datenträger und Einhängung prüfen.')
    return value.casefold()

def verify_backup_uuid(conf,actual):
    expected=conf.get('filesystem_uuid')
    if not expected:raise ValueError('Backup-Datenträger noch nicht per UUID bestätigt. Tägliche Sicherungskette prüfen und Einstellungen speichern.')
    if actual!=expected:raise ValueError('UUID des Backup-Dateisystems stimmt nicht überein. Richtigen Backup-Datenträger einhängen.')

def preflight():
    for name in ('rsync','php','mariadb-dump','sudo'):
        if not shutil.which(name):raise ValueError('Benötigtes Programm fehlt: '+name)
    for p in (cfg.get('system_backup_root'),cfg.get('oscam_config'),cfg.get('nextcloud_root'),cfg.CONFIG_DIR,cfg.STATE_DIR):
        if not Path(p).is_dir():raise ValueError('Erforderlicher Sicherungspfad fehlt: '+str(p))
    for p in (Path(cfg.get('nextcloud_root'))/'config/config.php',Path(cfg.get('nextcloud_root'))/'occ'):
        if not p.is_file():raise ValueError('Nextcloud-Datei fehlt: '+str(p))
    if root().resolve().is_relative_to(cfg.BASE_DIR.resolve()):raise ValueError('Backup-Ziel darf nicht innerhalb des Manager-Quellcodes liegen.')
    return backup_uuid()

def configure(enabled,clock):
    datetime.datetime.strptime(clock,'%H:%M')
    if len(clock)!=5:raise ValueError('Zeit als HH:MM angeben.')
    old=settings()
    filesystem_uuid=preflight() if enabled else old.get('filesystem_uuid')
    cfg.atomic(cfg.CONFIG_DIR/'daily-backup.json',dict(enabled=enabled,time=clock,filesystem_uuid=filesystem_uuid,start_date=old.get('start_date') or (datetime.date.today()+datetime.timedelta(days=1)).isoformat()))

def copy_tree(source,target,previous=None,excludes=()):
    source=Path(source)
    if not source.is_dir():raise ValueError('Sicherungsquelle fehlt: '+str(source))
    target.mkdir(parents=True,exist_ok=True)
    args=['rsync','-aHAX','--numeric-ids']
    for pattern in excludes:args+=['--exclude='+pattern]
    if previous and previous.is_dir():args+=['--link-dest='+str(previous.resolve())]
    command(args+['--',str(source)+'/',str(target)+'/'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

def occ(*args):
    p=command(['sudo','-n','-u',cfg.get('nextcloud_user'),'php',str(Path(cfg.get('nextcloud_root'))/'occ'),*args],timeout=120,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    return p.stdout

def snapshot(key):
    base=root()/key;base.mkdir(parents=True,exist_ok=True,mode=0o700)
    if base.is_symlink() or base.stat().st_mode & 0o077:raise ValueError('Backup-Unterordner muss privat sein (0700).')
    previous=base/'latest';previous=previous.resolve() if previous.is_symlink() else None
    if previous and (previous.parent!=base.resolve() or not (previous/'complete.json').is_file()):raise ValueError('Ungültiger vorheriger Sicherungsstand.')
    name=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    stage=base/('.partial-'+name);stage.mkdir(mode=0o700)
    def tree(label,source,excludes=()):copy_tree(source,stage/label,previous/label if previous else None,excludes)
    nc=Path(cfg.get('nextcloud_root'))
    if key=='oscam':
        tree('config',cfg.get('oscam_config'))
        for source in ('/usr/local/bin/oscam','/etc/systemd/system/oscam.service'):
            if Path(source).is_file():shutil.copy2(source,stage/Path(source).name)
    elif key=='nextcloud_config':
        tree('config',nc/'config')
        if Path('/etc/apache2').is_dir():tree('apache','/etc/apache2')
    elif key=='nextcloud_apps':
        # Core and app code, excluding separately protected configuration and user data.
        excludes=['/config/','/data/']
        data=Path(cfg.get('nextcloud_data')).resolve()
        if data.is_relative_to(nc.resolve()):excludes.append('/'+str(data.relative_to(nc.resolve()))+'/')
        tree('code',nc,excludes)
    elif key=='nextcloud_db':
        code='$CONFIG=[];require $argv[1];echo json_encode([$CONFIG["dbname"],$CONFIG["dbhost"],$CONFIG["dbtype"]]);'
        result=command(['php','-r',code,str(nc/'config/config.php')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=30)
        name_db,host,kind=json.loads(result.stdout)
        if kind!='mysql' or host not in ('localhost','127.0.0.1'):raise ValueError('Tagesbackup unterstützt hier nur die lokale MariaDB.')
        raw=stage/'database.sql'
        with raw.open('wb') as out:
            command(['mariadb-dump','--single-transaction','--quick','--routines','--events','--triggers','--default-character-set=utf8mb4','--databases','--',name_db],stdout=out,stderr=subprocess.PIPE)
        if not raw.stat().st_size:raise ValueError('Datenbank-Dump ist leer.')
        with raw.open('rb') as src,gzip.open(stage/'database.sql.gz','wb') as dst:shutil.copyfileobj(src,dst)
        raw.unlink()
    elif key=='server_manager':
        tree('program',cfg.BASE_DIR,('/.git/','/dist/','/__pycache__/'))
        tree('configuration',cfg.CONFIG_DIR)
        unit=Path('/etc/systemd/system/server-manager.service')
        if unit.is_file():shutil.copy2(unit,stage/unit.name)
        tree('state',cfg.STATE_DIR,('*.sqlite*','*.db','*.db-*'))
        # SQLite online backup also includes committed data from WAL files.
        database=Path(os.environ.get('SERVER_MANAGER_DB',str(cfg.STATE_DIR/'server-manager.sqlite3')))
        if not database.is_file():raise ValueError('Manager-Datenbank fehlt.')
        with sqlite3.connect('file:'+str(database)+'?mode=ro',uri=True) as src,sqlite3.connect(stage/'manager.sqlite3') as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite-Prüfung fehlgeschlagen.')
    else:raise ValueError('Unbekannte Sicherung')
    cfg.atomic(stage/'complete.json',dict(key=key,completed=time.time(),mode='database-dump' if key=='nextcloud_db' else 'incremental-hardlinks'))
    final=base/name;stage.rename(final)
    link=base/('.latest-'+uuid.uuid4().hex);link.symlink_to(name);os.replace(link,base/'latest')
    return str(final)

def run_chain():
    global RUNNING
    cfg.STATE_DIR.mkdir(parents=True,exist_ok=True)
    with (cfg.STATE_DIR/'daily-backup.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        conf=settings();filesystem_uuid=preflight()
        verify_backup_uuid(conf,filesystem_uuid)
        root().mkdir(mode=0o700,parents=True,exist_ok=True)
        if root().is_symlink() or root().stat().st_mode & 0o077:raise ValueError('Tagesbackup-Ordner muss privat sein (0700).')
        RUNNING=True;info=state();info.pop('error',None);info.update(state='running',date=datetime.date.today().isoformat(),started=time.time(),steps={},current='');save_state(info)
        maintenance_changed=False
        def step(key):
            info['current']=LABELS[key];save_state(info)
            try:
                path=snapshot(key);info['steps'][key]={'ok':True,'path':path,'finished':time.time()}
            except Exception as exc:info['steps'][key]={'ok':False,'error':type(exc).__name__}
            save_state(info)
        try:
            step('oscam')
            try:
                status=json.loads(occ('status','--output=json'))
                if not status.get('maintenance'):
                    occ('maintenance:mode','--on');maintenance_changed=True
                for key in ('nextcloud_config','nextcloud_apps','nextcloud_db'):step(key)
            except Exception as exc:
                for key in ('nextcloud_config','nextcloud_apps','nextcloud_db'):info['steps'].setdefault(key,{'ok':False,'error':type(exc).__name__})
            finally:
                if maintenance_changed:occ('maintenance:mode','--off');maintenance_changed=False
            step('server_manager')
            info['state']='completed' if len(info['steps'])==5 and all(x['ok'] for x in info['steps'].values()) else 'failed'
        except Exception as exc:info.update(state='failed',error=type(exc).__name__)
        finally:
            if maintenance_changed:
                try:occ('maintenance:mode','--off')
                except Exception:info.update(state='failed',error='Nextcloud-Wartungsmodus bitte prüfen')
            info.update(current='',finished=time.time());save_state(info);RUNNING=False

def due(conf,info,now):
    return conf.get('enabled') and now.strftime('%Y-%m-%d')>=conf['start_date'] and now.strftime('%H:%M')>=conf['time'] and info.get('date')!=now.strftime('%Y-%m-%d')

def start(app):
    if app.testing or app.extensions.get('daily_backup'):return
    app.extensions['daily_backup']=True
    previous=state()
    if previous.get('state')=='running':
        previous.update(state='failed',error='Sicherung wurde unterbrochen. Nextcloud-Wartungsmodus prüfen.');save_state(previous)
    def loop():
        while True:
            time.sleep(30)
            try:
                if not due(settings(),state(),datetime.datetime.now()):continue
                from .central import active
                from modules.app_manager.plugin import get_active_job,set_active_job
                if active() or get_active_job():continue
                set_active_job('server_manager','backup',None)
                try:run_chain()
                finally:set_active_job()
            except Exception as exc:
                info=state();info.update(state='failed',date=datetime.date.today().isoformat(),error=type(exc).__name__);save_state(info)
    threading.Thread(target=loop,name='daily-backup',daemon=True).start()


def manual_backup(key):
    """Use completion time and persisted contents, never just directory mtime."""
    app='nextcloud' if key.startswith('nextcloud_') else key
    backup=Path(cfg.get('backup_root')).resolve()
    folder=backup/app
    candidates=[]
    if not folder.is_dir():return candidates
    def present(record,directory=False):
        if not isinstance(record,dict) or not record.get('ok'):return False
        raw=record.get('target') or record.get('file')
        if not raw:return False
        path=Path(raw).resolve()
        if not path.is_relative_to(backup):return False
        return path.is_dir() if directory else path.is_file() and path.stat().st_size>0
    for run in folder.iterdir():
        if not run.is_dir() or run.is_symlink() or not (run/'session.json').is_file():continue
        try:
            session=cfg.read(run/'session.json');result=cfg.read(run/'result.json')
            if session.get('state')!='completed' or (session.get('statistics') or {}).get('failed'):continue
            completed=datetime.datetime.fromisoformat(session['finished_at']).timestamp()
            if completed>time.time()+300:continue
            archive=Path(result.get('archive') or '')
            if not archive.is_file() or not archive.resolve().is_relative_to(backup) or archive.stat().st_size==0:continue
            steps=result.get('steps') or {};files=steps.get('config_files') or {};paths=steps.get('paths') or {};db=steps.get('database') or {}
            good=False
            if key=='nextcloud_db':good=bool(db.get('supported')) and present(db)
            elif key=='nextcloud_config':
                good=present(files.get('config.php'))
                if not good and present(paths.get('nextcloud_app'),True):good=(Path(paths['nextcloud_app']['target'])/'config/config.php').is_file()
            elif key=='nextcloud_apps':good=present(paths.get('nextcloud_app'),True) and (Path(paths['nextcloud_app']['target'])/'apps').is_dir()
            elif key=='oscam':good=(bool(files) and all(present(v) for v in files.values())) or present(paths.get('config'),True)
            elif key=='server_manager':good=(present(paths.get('configuration'),True) or present(paths.get('server_manager'),True)) and present(db)
            if good:candidates.append((completed,str(run),'Manuelles App-Backup'))
        except (OSError,ValueError,KeyError,TypeError):continue
    return candidates


def monitored(item):
    if not settings():return None
    key=next((k for k,v in LABELS.items() if v==item['name']),None)
    if not key:return None
    candidates=manual_backup(key)
    path=root()/key/'latest'
    try:
        target=path.resolve(strict=True)
        if target.parent!=(root()/key).resolve():raise ValueError('Ungültiger Snapshot')
        completed=float(cfg.read(target/'complete.json')['completed'])
        if completed<=time.time()+300:candidates.append((completed,str(target),'Täglicher inkrementeller Stand'))
    except (OSError,ValueError,KeyError,TypeError):pass
    if not candidates:return {**item,'state':'FEHLT','age_h':None,'latest':'','size':''}
    completed,target,origin=max(candidates)
    age=max(0,int((time.time()-completed)/3600))
    return {**item,'state':'OK' if age<=36 else 'WARN' if age<=72 else 'ALT','age_h':age,'latest':target,'size':origin,'completed_at':completed}
