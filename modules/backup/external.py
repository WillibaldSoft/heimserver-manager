"""External, UUID-bound copies of existing backup repositories."""
import contextlib,datetime,fcntl,hashlib,json,os,re,shutil,subprocess,sys,time,uuid,threading
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import server_settings as cfg
ROOT=cfg.STATE_DIR/'external-backup'
CONFIG=cfg.CONFIG_DIR/'external-backup.json'
TERMINAL={'completed','failed','interrupted'}
FILESYSTEMS={'ext2','ext3','ext4','xfs','btrfs'}

def command(args,timeout=30):
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout,env={**os.environ,"LC_ALL":"C"})
    if result.returncode:raise ValueError((result.stderr.strip() or 'Befehl fehlgeschlagen: '+args[0])[-1500:])
    return result.stdout

def settings():return cfg.read(CONFIG)
def save(value):
    if active():raise ValueError('Externe Sicherung läuft. Einstellungen danach ändern.')
    device=select_device(value.get('uuid',''))
    if device['fstype'] not in FILESYSTEMS:raise ValueError('Für Linux-Rechte, ACLs und Hardlinks wird ext4, XFS oder Btrfs benötigt. Hier wird nichts formatiert.')
    extras=[]
    for raw in value.get('extra', '').splitlines():
        if raw.strip():extras.append(str(safe_source(raw.strip())))
    conf={'uuid':device['uuid'],'unmount':bool(value.get('unmount')), 'extra':extras}
    if 'selection' in settings():conf['selection']=settings()['selection']
    paths,_=inventory(conf)
    conf['sources']=validate_sources(paths,device['uuid'])
    cfg.atomic(CONFIG,conf)

def devices():
    data=json.loads(command(['lsblk','-J','-b','-p','-o','NAME,UUID,LABEL,FSTYPE,SIZE,MOUNTPOINTS,RO']))
    rows=[]
    def walk(items):
        for d in items:
            if d.get('uuid') and d.get('fstype') in FILESYSTEMS and not d.get('ro'):
                rows.append({'uuid':d['uuid'],'device':d['name'],'label':d.get('label') or '', 'fstype':d['fstype'],'size':int(d.get('size') or 0),'mounts':[x for x in d.get('mountpoints',[]) if x]})
            walk(d.get('children',[]))
    walk(data['blockdevices']);return rows

def select_device(value):
    if not re.fullmatch('[A-Za-z0-9-]{4,80}',value):raise ValueError('Bitte eine Festplatte mit Dateisystem-UUID auswählen.')
    matches=[x for x in devices() if x['uuid']==value]
    if len(matches)!=1:raise ValueError('Zielfestplatte fehlt oder UUID ist nicht eindeutig. Datenträger anschließen.')
    d=matches[0]
    if any(p=='/' or p.startswith(('/boot','/usr','/var','/etc','/home')) for p in d['mounts']):raise ValueError('System- oder Benutzerdateisystem ist kein externes Sicherungsziel.')
    if len(d['mounts'])>1:raise ValueError('Zieldateisystem ist mehrfach eingebunden. Bitte einen eindeutigen Mount verwenden.')
    return d

def safe_source(raw):
    p=Path(raw)
    if not p.is_absolute() or '..' in p.parts or p==Path('/') or len(p.parts)<3:raise ValueError('Nur konkrete absolute Backup-Unterordner zulässig: '+str(p))
    if p.is_symlink() or p.resolve()!=p:raise ValueError('Backupquelle darf keinen symbolischen Pfad enthalten: '+str(p))
    if not p.is_dir():raise ValueError('Backupordner fehlt: '+str(p))
    return p

def monitored_sources():
    from . import daily
    rows=[]
    for item in cfg.get('backup_items'):
        current=daily.monitored(item)
        if current and current.get('latest'):
            # Use the actual completed daily/app backup rather than retired monitoring paths.
            rows.append((item['name']+' · aktueller Sicherungsstand ('+current['state']+')',Path(current['latest'])))
        elif current is not None:
            key=next((key for key,name in daily.LABELS.items() if name==item['name']),None)
            rows.append((item['name']+' · noch kein abgeschlossener Sicherungsstand',daily.root()/key if key else Path(item['path'])))
        else:rows.append((str(item.get('name','Backup')),Path(item['path'])))
    return rows

def source_candidates(conf):
    labels={'system_backup_root':'Zentrale Sicherungsablage (alle Unterordner)','backup_root':'App-Sicherungen und Snapshots','restore_log_root':'App-Wiederherstellungen','update_log_root':'App-Updates und Rücksicherungen'}
    rows=[(labels[k],Path(cfg.get(k))) for k in labels]
    app_root=Path(cfg.get('backup_root'))
    if app_root.is_dir():rows += [('App-Sicherung: '+p.name,p) for p in app_root.iterdir() if p.is_dir() and not p.is_symlink()]
    rows += monitored_sources()
    central=Path(cfg.get('system_backup_root'))
    rows += [(label,central/name) for label,name in [('Tägliche inkrementelle Sicherungen','daily_incremental'),('VM-Archive','kvm'),('Server-Sicherungen','linux-server-backup'),('Client-Sicherungen','linux-client-backup'),('Desktop-Client-Sicherungen (DEB / EXE)','desktop-client-backup')]]
    daily=central/'daily_incremental'
    if daily.is_dir():rows += [('Tagesbackup: '+p.name,p) for p in daily.iterdir() if p.is_dir() and not p.is_symlink()]
    rows += [(label,cfg.STATE_DIR/name) for label,name in [('Freigaben-Rücksicherungen','backups'),('VM-Konfigurationskopien (optional)','kvm-xml-backups'),('DynDNS-Rücksicherungen','dyndns/backups'),('Systemreparaturen','repair-backups'),('Netzwerk-Rücksicherung','bridge-migration')]]
    for pattern in ('fotolabor-original-*','fotolabor-repair-*'):
        rows += [('Fotolabor-Originale / Reparatur',p) for p in cfg.STATE_DIR.glob(pattern) if p.is_dir()]
    import pwd
    for user in pwd.getpwall():
        if 1000<=user.pw_uid<60000 and Path(user.pw_dir).is_dir() and not Path(user.pw_dir).is_symlink():
            rows += [('Desktop-Reparatursicherung',p) for p in Path(user.pw_dir).glob('.xrdp-fix-backup-*') if p.is_dir()]

    for base,pattern in [(cfg.STATE_DIR/'manager-updates','*/before-update'),(cfg.STATE_DIR/'scanner','jobs/*/backup'),(cfg.STATE_DIR/'web-security','jobs/*')]:
        if base.is_dir():rows += [('Interne Rücksicherung',p) for p in base.glob(pattern) if p.is_dir()]
    rows += [('Domäne',p) for pattern in ('server-manager-domain-*','server-manager-ad-*') for p in Path('/var/backups').glob(pattern) if p.is_dir()]
    rows += [('Zusätzlicher Backupordner',Path(p)) for p in conf.get('extra',[])]
    return rows

def inventory(conf):
    found=set();missing=[]
    if 'selection' in conf:
        from .selection import selected_sources
        candidates=selected_sources(conf)
    else:candidates=source_candidates(conf)
    for label,p in candidates:
        if not p.exists():missing.append(str(p));continue
        p=safe_source(str(p))
        found.add(p)
    # A containing repository already includes its configured subdirectories.
    roots=[p for p in sorted(found,key=lambda p:(len(p.parts),str(p))) if not any(parent in found for parent in p.parents)]
    return roots,sorted(set(missing))

def inventory_details(conf):
    roots,missing=inventory(conf);legacy={str(Path(x['path'])) for x in cfg.get('backup_items')}
    rows=[];root_set=set(roots)
    candidates=source_candidates(conf)
    if 'selection' in conf:
        from .selection import selected_sources
        candidates+=selected_sources(conf)
    seen=set()
    for label,p in candidates:
        if (label,str(p)) in seen:continue
        seen.add((label,str(p)))
        covering=next((str(parent) for parent in (p,*p.parents) if parent in root_set),None)
        exists=p.is_dir()
        if 'selection' in conf and not covering:continue
        state='enthalten' if exists and covering else 'fehlt'
        if not exists:
            if str(p) in legacy:state='Alter Überwachungseintrag ohne Ordner; kein aktueller Backupnachweis'
            elif str(p) in conf.get('extra',[]):state='Zusätzlicher Quellordner fehlt'
            else:state='Noch nicht angelegt / derzeit nicht vorhanden'
        rows.append(dict(label=label,path=str(p),state=state,covering=covering if exists else None,exists=exists))
    return roots,rows

SIZE_LOCK=threading.Lock()
SIZE_RUNNING=False

def human_size(value):
    if value is None:return 'Noch nicht ermittelt'
    value=float(value)
    for unit in ('B','KiB','MiB','GiB','TiB','PiB'):
        if abs(value)<1024 or unit=='PiB':return ('%.2f %s'%(value,unit)).replace('.',',')
        value/=1024

def config_key(conf):return hashlib.sha256(json.dumps(conf,sort_keys=True).encode()).hexdigest()

def size_status():
    data=cfg.read(ROOT/'size.json')
    if data.get('state')=='running' and not SIZE_RUNNING:data.update(state='interrupted',message='Größenprüfung durch Neustart unterbrochen; erneut ermitteln.')
    return data

def source_bytes(path):
    return int(command(['du','--summarize','--apparent-size','--block-size=1','--',str(path)],timeout=3600).split()[0])

def transferred_bytes(source,destination,previous=None):
    report=command(copy_args(previous)+['--dry-run','--stats','--',str(source)+'/',str(destination)+'/'],timeout=86400)
    match=re.search(r'Total transferred file size: ([0-9,]+) bytes',report)
    if not match:raise ValueError('Platzbedarf konnte nicht ermittelt werden.')
    return int(match.group(1).replace(',',''))

def measure(conf):
    paths,missing=inventory(conf)
    result=dict(state='running',created=time.time(),message='Gesamtgröße der Backupordner ermitteln …',rows=[],total_bytes=0,uuid=conf.get('uuid'),missing=missing,config_key=config_key(conf))
    cfg.atomic(ROOT/'size.json',result)
    last_progress=0
    for path in paths:
        result['message']='Größe ermitteln: '+str(path)
        if time.monotonic()-last_progress>=2:
            cfg.atomic(ROOT/'size.json',result);last_progress=time.monotonic()
        size=source_bytes(path);result['rows'].append({'path':str(path),'bytes':size});result['total_bytes']+=size
    result.update(additional_bytes=None,free_bytes=None,target_note='Zielfestplatte auswählen und speichern, um den zusätzlichen Bedarf zu vergleichen.')
    try:
        if conf.get('uuid'):
            device=select_device(conf['uuid'])
            if device['mounts']:
                target=Path(device['mounts'][0]);disjoint(paths,target);rows=validate_sources(paths,conf['uuid'])
                if filesystem(target)['uuid']!=conf['uuid']:raise ValueError('UUID der Zielfestplatte stimmt nicht überein.')
                parent=target/'Heimserver-Manager-Vollbackups'
                if parent.is_symlink():raise ValueError('Zielordner darf kein symbolischer Link sein.')
                previous=previous_sources(parent) if parent.is_dir() else {}
                result['additional_bytes']=0;result['message']='Neue/geänderte Daten mit externem Bestand vergleichen …';cfg.atomic(ROOT/'size.json',result)
                # rsync --dry-run creates no target files, including this intentionally absent directory.
                destination=target/('.server-manager-size-'+uuid.uuid4().hex)
                for index,path in enumerate(paths):result['additional_bytes']+=transferred_bytes(path,destination/str(index),previous.get(str(path)))
                check_sources(rows)
                if filesystem(target)['uuid']!=conf['uuid']:raise ValueError('Zielfestplatte wurde getrennt.')
                result['free_bytes']=shutil.disk_usage(target).free
                result['reserve_bytes']=max(256*1024**2,result['additional_bytes']//20)
                result['target_note']='Mit den vorhandenen bestätigten externen Ständen verglichen (nur Lesetest).'
            else:result['target_note']='Zielfestplatte nicht eingehängt. Gesamtgröße ermittelt; inkrementeller Bedarf wird nach Einhängen unter Speicher oder beim Sicherungsstart berechnet.'
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        result.update(additional_bytes=None,free_bytes=None,target_note='Inkrementeller Zielvergleich derzeit nicht möglich: '+str(exc))
    result.update(state='completed',message='Größenprüfung abgeschlossen.',finished=time.time());cfg.atomic(ROOT/'size.json',result)
    return result

def start_measure():
    global SIZE_RUNNING
    with SIZE_LOCK:
        if SIZE_RUNNING:return
        if active():raise ValueError('Sicherung läuft; Größe steht beim laufenden Auftrag.')
        conf=settings();SIZE_RUNNING=True
        cfg.atomic(ROOT/'size.json',dict(state='running',created=time.time(),message='Größenprüfung gestartet.'))
        def run():
            global SIZE_RUNNING
            try:measure(conf)
            except Exception as exc:
                data=cfg.read(ROOT/'size.json');data.update(state='failed',message=str(exc),finished=time.time());cfg.atomic(ROOT/'size.json',data)
            finally:SIZE_RUNNING=False
        try:threading.Thread(target=run,name='external-backup-size',daemon=True).start()
        except Exception:SIZE_RUNNING=False;raise

def filesystem(path):
    rows=json.loads(command(['findmnt','--json','--target',str(path),'--output','TARGET,UUID,OPTIONS']))['filesystems']
    if len(rows)!=1 or not rows[0].get('uuid'):raise ValueError('Dateisystem-UUID nicht erkennbar: '+str(path))
    return rows[0]

def nested_mounts(path):
    rows=json.loads(command(['findmnt','--json','--list','--output','TARGET,UUID']))['filesystems']
    return sorted([(r['target'],r.get('uuid')) for r in rows if Path(r['target'])!=Path(path) and Path(r['target']).is_relative_to(path)])

def validate_sources(paths,target_uuid):
    result=[]
    for p in paths:
        fs=filesystem(p)
        if fs['uuid']==target_uuid:raise ValueError('Quelle und Ziel dürfen nicht auf demselben Dateisystem liegen: '+str(p))
        nested=nested_mounts(p)
        if any(not uid or uid==target_uuid for _,uid in nested):raise ValueError('Untergeordneter Mount ist nicht eindeutig als Backupquelle nutzbar: '+str(p))
        result.append({'path':str(p),'uuid':fs['uuid'],'mount':fs['target'],'nested':nested})
    if not result:raise ValueError('Keine vorhandenen Backupordner gefunden.')
    return result

def check_sources(rows):
    for row in rows:
        safe_source(row['path']);fs=filesystem(row['path'])
        if 'nested' in row and [list(x) for x in nested_mounts(row['path'])]!=[list(x) for x in row['nested']]:raise ValueError('Untergeordnete Quell-Mounts wurden verändert: '+row['path'])
        if (fs['uuid'],fs['target'])!=(row['uuid'],row['mount']):raise ValueError('Backup-Quelldatenträger wurde gewechselt oder ausgehängt: '+row['path'])

def status():
    info=cfg.read(ROOT/'status.json')
    if info.get('state') in ('queued','running') and time.time()-info.get('created',0)>30:
        r=subprocess.run(['systemctl','is-active','server-manager-external-backup-'+info['id']],capture_output=True,text=True,timeout=10)
        if r.stdout.strip() not in ('active','activating','reloading'):info.update(state='interrupted',message='Sicherung unterbrochen. Teilordner ist kein bestätigtes Vollbackup.')
    return info

def active():return status().get('state') in ('queued','running')
def get_blockers():return [dict(source='Backup',type='external-backup',title='Externe Sicherung / Rücksicherung läuft',reason='Ausgewählte Ordner werden kopiert und geprüft',priority=95,url='/backup/external')] if active() else []

@contextlib.contextmanager
def locked():
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (ROOT/'lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX);yield

def busy(ctx):
    from modules.backup import central,daily
    from modules.app_manager.plugin import get_active_job
    from modules.app_manager.install_jobs import active as installers
    from modules.web_security.jobs import active as web
    from modules.scanner.engine import active as scanner
    if central.RUNNING or daily.RUNNING or get_active_job() or installers() or web() or scanner():raise ValueError('Laufende Sicherungs-, App- oder Konfigurationsaufträge zuerst abschließen lassen.')
    if any(x['type']!='external-backup' for x in central.get_blockers()):raise ValueError('Server-/Client-Sicherung läuft. Bitte Abschluss abwarten.')
    con=ctx.db()
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='kvm_jobs'").fetchone() and con.execute("SELECT 1 FROM kvm_jobs WHERE state IN ('queued','running','uploading') LIMIT 1").fetchone():raise ValueError('VM-Auftrag läuft. Bitte Abschluss abwarten.')
    finally:con.close()

def start(ctx):
    with locked():
        if active():raise ValueError('Externe Sicherung läuft bereits.')
        busy(ctx)
        if not shutil.which('rsync'):raise ValueError('rsync fehlt. Bitte über APT installieren.')
        conf=settings();device=select_device(conf.get('uuid',''));paths,missing=inventory(conf)
        disjoint(paths,ROOT.resolve())
        rows=validate_sources(paths,device['uuid'])
        expected={r['path']:r for r in conf.get('sources',[])}
        for row in rows:
            if row['path'] in expected:
                old=expected[row['path']]
                if row['uuid']!=old['uuid'] or [list(x) for x in row.get('nested',[])]!=[list(x) for x in old.get('nested',[])]:raise ValueError('UUID oder Unter-Mounts der Backupquelle stimmen nicht mehr: '+row['path'])
        key=uuid.uuid4().hex
        plan={'id':key,'created':time.time(),'state':'queued','message':'Externe Sicherung wird gestartet.','config':conf,'sources':rows,'missing':missing}
        (ROOT/'copy.log').write_text('');(ROOT/'verify.log').write_text('')
        cfg.atomic(ROOT/'status.json',plan)
        args=['systemd-run','--quiet','--collect','--unit=server-manager-external-backup-'+key,'--property=Type=exec','--property=UMask=0077','--property=RuntimeMaxSec=7d']
        args += ['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE') if k in os.environ]
        try:command(args+['/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key])
        except Exception:
            cfg.atomic(ROOT/'status.json',{**plan,'state':'failed','message':'Hintergrunddienst konnte nicht gestartet werden.'});raise
        return key

def mount_target(conf):
    d=select_device(conf['uuid']);owned=False
    if d['mounts']:p=Path(d['mounts'][0])
    else:
        p=Path('/mnt/server-manager-external')/d['uuid']
        p.mkdir(parents=True,exist_ok=True,mode=0o700)
        if p.resolve()!=p or any(p.iterdir()):raise ValueError('Automatischer Mountpunkt ist nicht leer oder enthält einen symbolischen Pfad.')
        command(['mount','-o','nosuid,nodev,noexec','--source','UUID='+d['uuid'],'--target',str(p)]);owned=True
    try:
        fs=filesystem(p)
        if fs['uuid']!=conf['uuid'] or Path(fs['target'])!=p or 'rw' not in fs['options'].split(','):raise ValueError('Zielfestplatte ist nicht korrekt schreibbar eingehängt.')
    except Exception:
        if owned:command(['umount','--',str(p)])
        raise
    return p,owned

def disjoint(paths,target):
    for p in paths:
        if p.is_relative_to(target) or target.is_relative_to(p):raise ValueError('Backupquelle und externes Ziel dürfen nicht ineinander liegen.')

def copy_args(previous=None):
    args=['rsync','-aHAX','--numeric-ids','--sparse','--checksum']
    if previous:args+=['--link-dest='+str(previous.resolve())]
    return args

def previous_sources(parent):
    candidates=[]
    for p in parent.iterdir():
        if p.name.startswith('.') or p.is_symlink() or not p.is_dir():continue
        manifest=cfg.read(p/'manifest.json')
        if manifest.get('format')=='heimserver-external-backup':candidates.append((float(manifest.get('completed',0)),p,manifest))
    result={}
    # Newest confirmed copy for each source, even if it was absent in a later run.
    for _,p,manifest in sorted(candidates,key=lambda x:x[0],reverse=True):
        for row in manifest.get('sources',[]):
            name=row.get('directory','')
            if not name or Path(name).name!=name or name in ('.','..'):continue
            dest=p/name
            if dest.is_dir() and not dest.is_symlink():result.setdefault(row['path'],dest.resolve())
    return result

def rsync(source,target,log,verify=False,previous=None):
    args=copy_args(previous)
    if verify:args+=['--dry-run','--itemize-changes','--delete']
    with log.open('a') as output:
        result=subprocess.run(args+['--',str(source)+'/',str(target)+'/'],stdout=output,stderr=output)
    if result.returncode:raise ValueError('Kopier-/Prüfschritt fehlgeschlagen (rsync '+str(result.returncode)+'). Protokoll prüfen.')

def worker(key):
    info=cfg.read(ROOT/'status.json')
    if info.get('id')!=key or info.get('state')!='queued':return 1
    target=None;owned=False;original=Path.cwd()
    def update(**values):info.update(values);cfg.atomic(ROOT/'status.json',info)
    try:
        update(state='running',message='Zielfestplatte prüfen und einhängen …')
        target,owned=mount_target(info['config']);rows=info['sources'];check_sources(rows)
        disjoint([Path(r['path']) for r in rows],target)
        # Pin the mounted filesystem as cwd: no fallback writes onto the host root if unmounted.
        os.chdir(target)
        parent=Path('Heimserver-Manager-Vollbackups')
        if parent.is_symlink():raise ValueError('Zielordner darf kein symbolischer Link sein.')
        parent.mkdir(mode=0o700,exist_ok=True)
        if parent.stat().st_uid!=os.geteuid() or parent.stat().st_mode&0o077:raise ValueError('Zielordner muss root gehören und privat sein (0700).')
        name=datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')+'-'+key[:8]
        stage=parent/('.partial-'+name);stage.mkdir(mode=0o700)
        update(destination=str(target/stage),message='Platzbedarf für neue und geänderte Dateien ermitteln …')
        previous=previous_sources(parent)
        total_bytes=sum(source_bytes(Path(row['path'])) for row in rows)
        update(total_bytes=total_bytes)
        needed=0
        for index,row in enumerate(rows,1):
            dest=stage/(str(index).zfill(3)+'-'+Path(row['path']).name)
            needed+=transferred_bytes(Path(row['path']),dest,previous.get(row['path']))
        if shutil.disk_usage('.').free<needed+max(256*1024**2,needed//20):raise ValueError('Nicht genügend freier Platz für neue oder geänderte Dateien.')
        update(destination=str(target/stage),message='Neue und geänderte Sicherungsdateien werden kopiert …',estimated_bytes=needed,free_bytes=shutil.disk_usage('.').free)

        manifest=[]
        for index,row in enumerate(rows,1):
            check_sources(rows)
            if filesystem(target)['uuid']!=info['config']['uuid']:raise ValueError('Zielfestplatte wurde getrennt.')
            source=Path(row['path']);dest=stage/(str(index).zfill(3)+'-'+source.name);dest.mkdir(mode=0o700)
            update(message='Kopieren '+str(index)+'/'+str(len(rows))+': '+str(source),current=index,total=len(rows))
            rsync(source,dest,ROOT/'copy.log',previous=previous.get(str(source)))
            manifest.append({**row,'directory':dest.name})
        for index,row in enumerate(manifest,1):
            update(message='Inhalt und Rechte prüfen '+str(index)+'/'+str(len(rows))+': '+row['path'])
            verification=ROOT/'verify.log';verification.write_text('');rsync(Path(row['path']),stage/row['directory'],verification,True)
            if verification.stat().st_size:raise ValueError('Quelle hat sich geändert oder Kopie weicht ab. Keine vollständige Sicherung bestätigt; Prüfprotokoll beachten.')
        check_sources(rows)
        if filesystem(target)['uuid']!=info['config']['uuid']:raise ValueError('Zielfestplatte wurde getrennt.')
        cfg.atomic(stage/'manifest.json',{'format':'heimserver-external-backup','version':1,'completed':time.time(),'sources':manifest,'not_present':info['missing'],'verification':'rsync checksum and metadata comparison','mode':'incremental hardlinks'})
        (stage/'WIEDERHERSTELLUNG.txt').write_text('Externe Kopie vorhandener Backupordner.\nmanifest.json ordnet die nummerierten Ordner den ursprünglichen Pfaden zu.\nZur Wiederherstellung einen einzelnen Sicherungsstand mit dem jeweiligen Manager-Modul oder Backup-Werkzeug verwenden.\nAlternativ als root mit rsync -aHAX --numeric-ids aus dem gewählten Ordner an den passenden neuen Backup-Pfad kopieren. Ziel vorher prüfen; vorhandene Dateien nicht blind überschreiben.\nUnveränderte Dateien können über Hardlinks mit älteren Ständen verbunden sein. Dateien in den externen Sicherungsständen nicht bearbeiten.\nDies ist kein startfähiges Abbild des Servers. Enthaltene unvollständige Quell-Backups bleiben unvollständig.\n')
        final_bytes=source_bytes(stage)
        update(total_bytes=final_bytes)
        command(['sync','-f',str(stage)],timeout=3600)
        final=parent/name;stage.rename(final);command(['sync','-f',str(parent)],timeout=3600)
        update(state='completed',message='Gesamtsicherung abgeschlossen und durch Inhaltsvergleich geprüft.',destination=str(target/final),finished=time.time())
    except Exception as exc:update(state='failed',message=str(exc),finished=time.time())
    finally:
        os.chdir(original)
        if owned and info['config'].get('unmount'):
            try:command(['umount','--',str(target)]);update(unmounted=True)
            except Exception as exc:update(unmount_error='Automatisches Aushängen fehlgeschlagen: '+str(exc))
    return 0 if info['state']=='completed' else 1

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker' or not re.fullmatch('[a-f0-9]{32}',sys.argv[2]):raise SystemExit('Nur interner Sicherungsauftrag.')
    raise SystemExit(worker(sys.argv[2]))
