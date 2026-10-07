"""Maintenance for installer-owned Nextcloud Compose stacks; never host services."""
import contextlib
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import threading

class DockerError(ValueError):
    pass

def command(args, timeout=60):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    except (OSError,subprocess.SubprocessError):
        raise DockerError('Docker-Aufruf nicht verfügbar oder Zeitlimit überschritten.') from None
    if p.returncode:
        # Neither environment nor output from a credential-bearing process enters logs.
        raise DockerError('Docker-Schritt fehlgeschlagen: '+args[0]+'. Containerzustand prüfen.')
    return p.stdout.strip()

def compose(manager,*args,timeout=60):
    return command(['docker','compose','--project-directory',str(manager.root),'-f',str(manager.root/'compose.json'),*args],timeout)

def inspect(container):
    try:return json.loads(command(['docker','inspect',container]))[0]
    except (ValueError,KeyError,IndexError):raise DockerError('Container nicht eindeutig prüfbar.') from None

def validate(manager):
    root=manager.root
    if not root.is_absolute() or any(p.is_symlink() for p in (root,*root.parents)):
        raise DockerError('Direkter Installationsordner erforderlich.')
    try:
        marker=json.loads((root/'.server-manager-install.json').read_text())
        spec=json.loads((root/'compose.json').read_text())
        if marker.get('setup',{}).get('mode')!='docker':raise ValueError()
        if (root/'compose.json').is_symlink() or (root/'secrets').is_symlink():raise ValueError()
        services=spec['services'];app=services['app'];db=services['db']
        if set(services)!={'app','db','redis'}:raise ValueError()
        if app['container_name']!=manager.container or app['environment']['MYSQL_HOST']!='db':raise ValueError()
        if db['environment']['MARIADB_DATABASE']!='nextcloud':raise ValueError()
        if db['environment']['MARIADB_ROOT_PASSWORD_FILE']!='/run/secrets/root_password':raise ValueError()
        if not re.fullmatch(r'(?:docker.io/library/)?nextcloud(?::[A-Za-z0-9_.-]+|@sha256:[a-f0-9]{64})',app['image']):raise ValueError()
        if not db['image'].startswith('mariadb:'):raise ValueError()
        if app['volumes']!=['./html:/var/www/html',manager.paths['nextcloud_data']+':/var/www/html/data']:raise ValueError()
        if db['volumes']!=['./database:/var/lib/mysql']:raise ValueError()
        if spec['secrets']['root_password']['file']!='./secrets/root_password':raise ValueError()
    except (OSError,ValueError,KeyError,TypeError):
        raise DockerError('Nur der unverwechselbare, vom Installer verwaltete Nextcloud/MariaDB/Redis-Stack wird unterstützt.') from None
    for name in ('compose.json','.server-manager-install.json','secrets/root_password','secrets/db_password','secrets/admin_password'):
        f=root/name
        if not f.is_file() or f.is_symlink():raise DockerError('Installationsdatei fehlt oder ist ein Symlink.')
    app_state=inspect(manager.container)
    db_id=compose(manager,'ps','-a','-q','db')
    if not re.fullmatch('[a-f0-9]{12,64}',db_id):raise DockerError('Datenbank-Container fehlt oder ist mehrdeutig.')
    db_state=inspect(db_id)
    labels=app_state.get('Config',{}).get('Labels',{}) or {}
    other=db_state.get('Config',{}).get('Labels',{}) or {}
    if not labels.get('com.docker.compose.project') or labels.get('com.docker.compose.project')!=other.get('com.docker.compose.project') or other.get('com.docker.compose.service')!='db':
        raise DockerError('Nextcloud und Datenbank gehören nicht zum selben Compose-Projekt.')
    expected={('/var/www/html',str(root/'html')),('/var/www/html/data',manager.paths['nextcloud_data'])}
    actual={(x.get('Destination'),x.get('Source')) for x in app_state.get('Mounts',[]) if x.get('Type')=='bind'}
    if not expected.issubset(actual):raise DockerError('Aktive Nextcloud-Datenpfade weichen von der Installation ab.')
    if not any(x.get('Source')==str(root/'database') and x.get('Destination')=='/var/lib/mysql' for x in db_state.get('Mounts',[])):
        raise DockerError('Aktiver Datenbankpfad weicht von der Installation ab.')
    if not db_state.get('State',{}).get('Running'):raise DockerError('Docker-Datenbank ist nicht gestartet.')
    return spec,app_state,db_id

@contextlib.contextmanager
def lock(manager):
    if getattr(manager,'_operation_owner',None)==threading.get_ident():
        yield;return
    if not manager.root.is_dir():raise DockerError('Nextcloud Docker ist nicht installiert.')
    with (manager.root/'.manager-operation.lock').open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise DockerError('Für diese Docker-Instanz läuft bereits ein Auftrag.') from None
        manager._operation_owner=threading.get_ident()
        try:yield
        finally:manager._operation_owner=None

def occ(manager,*args):
    return command(['docker','exec','--user','www-data',manager.container,'php','occ',*args],300)

@contextlib.contextmanager
def quiesce(manager):
    """Stop all app writers; DB remains online for a logical dump."""
    with lock(manager):
        _,state,_=validate(manager)
        if not state.get('State',{}).get('Running'):raise DockerError('Nextcloud muss vor der Sicherung laufen.')
        status=manager.occ_status()
        if not status.get('ok'):raise DockerError('Nextcloud ist vor der Sicherung nicht betriebsbereit.')
        expected={'dbtype':'mysql','dbhost':'db','dbname':'nextcloud','datadirectory':'/var/www/html/data'}
        for key,value in expected.items():
            if occ(manager,'config:system:get',key)!=value:raise DockerError('Aktive Nextcloud-Konfiguration weicht ab: '+key)
        enabled=False
        stopped=False
        try:
            occ(manager,'maintenance:mode','--on');enabled=True
            # A failed stop can still have stopped the container: always attempt recovery.
            stopped=True;compose(manager,'stop','-t','60','app',timeout=120)
            yield
        finally:
            if stopped:compose(manager,'start','app',timeout=120)
            if enabled:occ(manager,'maintenance:mode','--off')

def copy_path(source,destination,key):
    target=Path(destination)/key
    result=dict(source=str(source),target=str(target),ok=False)
    try:
        if not Path(source).is_dir():raise DockerError('Datenpfad fehlt.')
        target.mkdir(parents=True,exist_ok=False)
        command(['rsync','-aHAX','--numeric-ids','--',str(source).rstrip('/')+'/',str(target)+'/'],timeout=86400)
        result['ok']=True
    except (DockerError,OSError):result['error']='Datenpfad konnte nicht vollständig mit Rechten gesichert werden.'
    return result

def dump(manager,target):
    """Stream the entire Nextcloud database, including triggers/routines/events."""
    target=Path(target);target.mkdir(parents=True,exist_ok=True,mode=0o700)
    result=dict(supported=True,ok=False,type='nextcloud-docker',database='nextcloud',compressed=True,compression='gzip')
    final=target/'nextcloud.sql.gz'
    temp=None
    try:
        _,_,db_id=validate(manager)
        # Credential read happens only inside the DB container. It never reaches host argv/logs.
        script='set -eu; export MYSQL_PWD="$(cat /run/secrets/root_password)"; exec mariadb-dump -u root --single-transaction --quick --routines --events --triggers --hex-blob --default-character-set=utf8mb4 nextcloud'
        fd,temp=tempfile.mkstemp(prefix='.sql-',dir=target);os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as raw:
            p=subprocess.run(['docker','exec',db_id,'sh','-c',script],stdout=raw,stderr=subprocess.DEVNULL,timeout=1800)
        if p.returncode or Path(temp).stat().st_size==0:raise DockerError('Docker-Datenbankdump fehlgeschlagen oder leer.')
        zipped=Path(temp+'.gz')
        try:
            with Path(temp).open('rb') as src,zipped.open('xb') as output:
                os.chmod(zipped,0o600)
                with gzip.GzipFile(fileobj=output,mode='wb') as gz:
                    while chunk:=src.read(1024*1024):gz.write(chunk)
            h=hashlib.sha256()
            with zipped.open('rb') as src:
                while chunk:=src.read(1024*1024):h.update(chunk)
            digest=h.hexdigest()
            os.replace(zipped,final)
        finally:zipped.unlink(missing_ok=True)
        checksum=Path(str(final)+'.sha256');checksum.write_text(digest+'  '+final.name+'\n');checksum.chmod(0o600)
        result.update(ok=True,file=str(final),size=final.stat().st_size,sha256=digest,sha256_file=str(checksum),message='Vollständige Nextcloud-Datenbank aus Docker gesichert.')
    except (DockerError,OSError,subprocess.SubprocessError):
        result['message']='Docker-Datenbanksicherung fehlgeschlagen; keine erfolgreiche Sicherung bestätigt.'
    finally:
        if temp:Path(temp).unlink(missing_ok=True)
    (target/'database-result.json').write_text(json.dumps(result,indent=2))
    return result

def version(text):
    if not re.fullmatch(r'\d+(?:\.\d+){2,3}',str(text)):raise DockerError('Nextcloud-Version nicht eindeutig.')
    return tuple(int(x) for x in text.split('.'))

def check(manager):
    result=dict(supported=True,ok=False,state='missing',label='Inaktiv',update_available=None,requires_backup=True,safe_to_update=False)
    try:
        _,state,_=validate(manager)
        status=manager.occ_status()
        if not status.get('ok'):raise DockerError('Nextcloud-Docker ist nicht betriebsbereit.')
        current=status.get('versionstring');major=version(current)[0]
        image=inspect(state['Image'])
        platform=(image.get('Os','linux'),image.get('Architecture'),image.get('Variant',''))
        remote=json.loads(command(['docker','manifest','inspect','--verbose',f'nextcloud:{major}-apache'],60))
        entries=remote if isinstance(remote,list) else [remote]
        candidates=[]
        for entry in entries:
            descriptor=entry.get('Descriptor',{});p=descriptor.get('platform',{})
            if (p.get('os'),p.get('architecture'),p.get('variant',''))==platform:
                digest=descriptor.get('digest');config=entry.get('SchemaV2Manifest',{}).get('config',{}).get('digest')
                if re.fullmatch(r'sha256:[a-f0-9]{64}',str(digest)) and re.fullmatch(r'sha256:[a-f0-9]{64}',str(config)):
                    candidates.append((digest,config))
        if len(candidates)!=1:raise DockerError('Image-Plattform oder Registry-Antwort nicht eindeutig.')
        digest,config=candidates[0];available=config!=state['Image']
        result.update(ok=True,state='available' if available else 'current',label='Update verfügbar' if available else 'Aktuell',current_version=current,latest_version=f'{major}-apache',update_available=available,target_image='nextcloud@'+digest,target_major=major,target_config=config,message='Docker-Image innerhalb der installierten Hauptversion prüfen; MariaDB und Redis bleiben unverändert.')
    except (DockerError,OSError,ValueError,KeyError,TypeError) as exc:
        result.update(state='error',label='Nicht prüfbar',message=str(exc) if isinstance(exc,DockerError) else 'Docker-Update konnte nicht geprüft werden.')
    return result

def plan(manager):
    result=check(manager)
    result.update(app_id=manager.app_id,label=manager.label,kind=manager.kind,steps=[{'id':key,'label':label,'required':True} for key,label in [('backup','Konsistentes Komplettbackup inklusive Docker-Datenbank'),('image','Geprüftes Nextcloud-Image derselben Hauptversion laden'),('update','Nur Nextcloud-App aktualisieren'),('verify','OCC und Erreichbarkeit prüfen')]])
    result['update_guard']={'blocked':not result['ok'],'message':result.get('message','')}
    return result

def atomic(file,data):
    fd,name=tempfile.mkstemp(dir=file.parent)
    try:
        with os.fdopen(fd,'w') as f:os.fchmod(f.fileno(),0o600);f.write(data)
        os.replace(name,file)
    finally:
        if os.path.exists(name):os.unlink(name)

def execute(manager,session):
    from .settings import bool_setting
    result=dict(supported=True,ok=False,mode='execute',steps=[])
    if not session or session.get('simulate',True):
        return dict(result,ok=True,mode='simulate',message='Simulation: Komplettbackup, Imageprüfung und App-Update; keine Änderungen.',steps=[dict(id='simulate',status='simulated',changed=False)])
    if not session.get('execution_gate_passed') or not session.get('execution_authorized') or not session.get('source_prepare_run_id') or not bool_setting('update_execution_enabled',False):
        return dict(result,blocked=True,message='Freigegebener Echtlauf mit gebundenem Pre-Update-Backup erforderlich.',steps=[dict(id='gate',status='blocked',changed=False)])
    changed=False
    try:
        with lock(manager):
            target=check(manager)
            if not target['ok']:raise DockerError(target['message'])
            if not target['update_available']:return dict(result,ok=True,message='Nextcloud-Docker ist aktuell.')
            command(['docker','pull',target['target_image']],1800)
            actual=command(['docker','run','--rm','--network','none','--entrypoint','php',target['target_image'],'-r','include "/usr/src/nextcloud/version.php"; echo $OC_VersionString;'],60)
            if version(actual)[0]!=target['target_major'] or version(actual)<version(target['current_version']):raise DockerError('Image würde Hauptversion wechseln oder ein Downgrade ausführen.')
            from .backup_engine import run_backup
            # Refresh immediately before applying: user data may have changed since Prepare.
            backup=run_backup(manager,profile='full')
            if not backup.get('ok'):raise DockerError('Aktuelles Komplettbackup fehlgeschlagen; Update abgebrochen.')
            result['backup']=backup.get('work_dir')
            result['steps'].append(dict(id='backup',status='executed',changed=True,message='Konsistentes Komplettbackup abgeschlossen.'))
            spec,_,_=validate(manager)
            spec['services']['app']['image']=target['target_image']
            # After this point no automatic image downgrade: database migrations may have run.
            changed=True
            atomic(manager.root/'compose.json',json.dumps(spec,indent=2)+'\n')
            compose(manager,'up','-d','--no-deps','app',timeout=900)
            deadline=time.monotonic()+300
            while True:
                status=manager.occ_status()
                if status.get('ok') and status.get('versionstring')==actual:break
                if time.monotonic()>=deadline:raise DockerError('Nextcloud nach Update nicht betriebsbereit; Komplettbackup für Rücksicherung vorhanden.')
                time.sleep(3)
            manager._expected_update_version=actual
            result.update(ok=True,message='Nextcloud-Docker aktualisiert; Datenbank und Redis unverändert.',current_version=actual)
            result['steps'].append(dict(id='update',status='executed',changed=True,message='Image und OCC-Version geprüft.'))
    except (DockerError,OSError,ValueError,subprocess.SubprocessError) as exc:
        result.update(message=str(exc) if isinstance(exc,DockerError) else 'Docker-Update fehlgeschlagen. Aufbewahrtes Komplettbackup prüfen.',rollback_required=changed)
        result['steps'].append(dict(id='update',status='failed',changed=changed,message=result['message']))
    return result
