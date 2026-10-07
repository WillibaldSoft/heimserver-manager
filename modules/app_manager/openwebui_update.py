"""Transactional update of a standalone Open WebUI container.
The old data volume remains untouched: migrations run on an offline clone.
"""
import os
import contextlib,copy,fcntl,http.client,json,os,shutil,socket,subprocess,time,uuid
from pathlib import Path
from urllib.parse import quote
ROOT=Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'open-webui-updates'))
class UpdateError(RuntimeError):pass

class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(self.timeout);self.sock.connect('/var/run/docker.sock')

def api(method,path,data=None):
    connection=DockerConnection('localhost',timeout=90)
    try:
        body=json.dumps(data).encode() if data is not None else None
        connection.request(method,path,body,{'Content-Type':'application/json'})
        response=connection.getresponse();payload=response.read()
        if response.status>=300 and response.status!=304:raise UpdateError('Docker-Aktion fehlgeschlagen: '+method+' '+path.split('?')[0]+' (HTTP '+str(response.status)+').')
        return json.loads(payload) if payload else {}
    finally:connection.close()

def cmd(args,timeout=1800):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if r.returncode:raise UpdateError('Befehl fehlgeschlagen: '+args[0]+' '+args[1]+'.')
    return r.stdout

def saved(path,data):
    temp=path.with_suffix('.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(data,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(temp,path)

@contextlib.contextmanager
def lock():
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(ROOT/'update.lock','a') as stream:
        os.chmod(stream.name,0o600)
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise UpdateError('Ein Open-WebUI-Update läuft bereits.') from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)

def get_blockers(ctx=None):
    if not (ROOT/'update.lock').exists():return []
    try:
        with lock():return []
    except UpdateError:return [dict(source='Apps',type='open-webui-update',title='Open WebUI wird aktualisiert',reason='Datensicherung, Containerwechsel oder Rückkehr zum bisherigen Stand',priority=95,url='/apps/open_webui/update')]

def bundled(container):
    image=container.get('Config',{}).get('Image','')
    return image.startswith('ghcr.io/open-webui/open-webui:') and (image.split(':')[-1]=='ollama' or image.split(':')[-1].endswith('-ollama'))

def target_image(container,version):
    return 'ghcr.io/open-webui/open-webui:v'+version+('-ollama' if bundled(container) else '')

def data_volume(container):
    mounts=container.get('Mounts',[])
    allowed={'/app/backend/data'}
    if bundled(container):allowed.add('/root/.ollama')
    destinations=[m.get('Destination') for m in mounts]
    if not mounts or len(set(destinations))!=len(mounts) or any(m.get('Type')!='volume' or not m.get('Name') or m.get('Destination') not in allowed for m in mounts) or '/app/backend/data' not in destinations:
        raise UpdateError('Automatisches Update benötigt benannte WebUI-Datenvolumes; bei Ollama zusätzlich ein eigenes Modellvolume.')
    if bundled(container) and '/root/.ollama' not in destinations:raise UpdateError('Persistentes Ollama-Modellvolume fehlt.')
    if len({m['Name'] for m in mounts})!=len(mounts):raise UpdateError('Daten- und Modellvolume müssen getrennt sein.')
    if container['HostConfig'].get('NetworkMode') not in ('bridge','default'):raise UpdateError('Dieses Update unterstützt nur den vorhandenen Docker-Bridge-Betrieb.')
    if container['HostConfig'].get('AutoRemove'):raise UpdateError('AutoRemove-Container können nicht sicher zurückgesetzt werden.')
    return next(m['Name'] for m in mounts if m['Destination']=='/app/backend/data')

def volume_path(info):
    if info.get('Driver')!='local' or info.get('Options'):raise UpdateError('Nur lokale Docker-Volumes ohne externe Mountoptionen werden unterstützt.')
    path=Path(info['Mountpoint'])
    if not path.is_dir() or path.is_symlink():raise UpdateError('Datenvolume nicht zugänglich.')
    return path

def create_spec(old,old_image,new_image,new_volume,transaction):
    """Preserve user overrides, not old image defaults such as build version."""
    config=old['Config'];defaults=old_image.get('Config') or {};spec={}
    fields=('Hostname','Domainname','User','AttachStdin','AttachStdout','AttachStderr','ExposedPorts','Tty','OpenStdin','StdinOnce','Cmd','Healthcheck','ArgsEscaped','Volumes','WorkingDir','Entrypoint','NetworkDisabled','MacAddress','OnBuild','StopSignal','StopTimeout','Shell')
    for key in fields:
        if key in config and config[key]!=defaults.get(key):spec[key]=copy.deepcopy(config[key])
    inherited={s.split('=',1)[0]:s for s in defaults.get('Env',[]) or []}
    spec['Env']=[s for s in config.get('Env',[]) or [] if inherited.get(s.split('=',1)[0])!=s]
    spec['Labels']={k:v for k,v in (config.get('Labels') or {}).items() if (defaults.get('Labels') or {}).get(k)!=v}
    spec['Labels']['server-manager.open-webui-transaction']=transaction
    spec['Image']=new_image;spec['HostConfig']=copy.deepcopy(old['HostConfig'])
    old_volume=data_volume(old);matched=False
    binds=[]
    for item in spec['HostConfig'].get('Binds') or []:
        parts=item.split(':')
        if parts[0]==old_volume and len(parts)>1 and parts[1]=='/app/backend/data':parts[0]=new_volume;matched=True
        binds.append(':'.join(parts))
    if binds:spec['HostConfig']['Binds']=binds
    for mount in spec['HostConfig'].get('Mounts') or []:
        if mount.get('Type')=='volume' and mount.get('Target')=='/app/backend/data' and mount.get('Source')==old_volume:mount['Source']=new_volume;matched=True
    if not matched:raise UpdateError('Datenvolume-Zuordnung nicht eindeutig; kein Containerwechsel.')
    # Default bridge settings are rebuilt by Docker. Runtime IPs are never reused.
    return spec

def execute(manager,session):
    steps=[];changed=False;old=None;stopped=False;renamed=False;new_id=None;backup_name=None;folder=None;transaction={};order=0
    def progress(action):
        nonlocal order
        order+=1
        if session and session.get('run_dir'):
            session.update(state='executing',current_step=order,current_action=action,updated_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
            from .update_engine import _write_json
            _write_json(Path(session['run_dir'])/'session.json',session)
    def step(action,message,mutated=False,status='executed'):
        steps.append(dict(order=order,id=action,action=action,label=message,title=message,status=status,changed=mutated,message=message))
    def record(phase):
        transaction['phase']=phase
        if folder:saved(folder/'transaction.json',transaction)
    with lock():
        try:
            progress('preflight')
            check=manager.update_check()
            if not check.get('ok'):raise UpdateError(check.get('message') or 'Versionsprüfung fehlgeschlagen.')
            if not check.get('update_available'):return dict(ok=True,supported=True,message='Kein neueres Stable-Release verfügbar.',steps=[])
            target=check['latest_version'];manager.version_tuple(target)
            old=api('GET','/containers/'+quote(manager.container,safe='')+'/json')
            old_volume=data_volume(old)
            if not old['State'].get('Running'):raise UpdateError('Open WebUI muss vor dem Update laufen.')
            users=api('GET','/containers/json?all=1&filters='+quote(json.dumps({'volume':[old_volume]})))
            if any(x['Id']!=old['Id'] for x in users):raise UpdateError('Datenvolume wird von weiteren Containern verwendet.')
            source=volume_path(api('GET','/volumes/'+quote(old_volume,safe='')))
            size=int(cmd(['du','-sx','--block-size=1',str(source)],120).split()[0])
            if shutil.disk_usage(source).free<size*1.2+256*1024*1024:raise UpdateError('Zu wenig freier Speicher für eine vollständige Datenkopie.')
            if not shutil.which('rsync'):raise UpdateError('rsync fehlt für die Datensicherung.')
            stamp=uuid.uuid4().hex;folder=ROOT/stamp;folder.mkdir(mode=0o700)
            backup_name=manager.container+'-before-'+stamp[:12];new_volume=manager.container+'-data-'+stamp[:12]
            transaction.update(id=stamp,container=manager.container,old_id=old['Id'],old_volume=old_volume,backup_container=backup_name,new_volume=new_volume,target_version=target)
            saved(folder/'original-container.json',old);record('preflight');step('preflight','Bestand geprüft; Containerkonfiguration geschützt gespeichert.')
            progress('pull_image')
            image=target_image(old,target)
            cmd(['docker','pull',image],2400)
            image_info=api('GET','/images/'+quote(image,safe='')+'/json');old_image=api('GET','/images/'+quote(old['Image'],safe='')+'/json')
            spec=create_spec(old,old_image,image,new_volume,stamp)
            # Stop is only reached after a complete image pull and all checks.
            step('pull_image','Stable-Image vollständig geladen.')
            progress('backup_data');record('stopping')
            stopped=True;changed=True
            api('POST','/containers/'+old['Id']+'/stop?t=60')
            api('POST','/containers/'+old['Id']+'/update',{'RestartPolicy':{'Name':'no','MaximumRetryCount':0}})
            api('POST','/volumes/create',{'Name':new_volume,'Labels':{'server-manager.open-webui-transaction':stamp}})
            dest=volume_path(api('GET','/volumes/'+new_volume))
            cmd(['rsync','-aHAX','--numeric-ids','--',str(source)+'/',str(dest)+'/'],3600)
            record('data_copied');step('backup_data','Offline-Datenkopie erstellt; ursprüngliches Volume bleibt unverändert.',True)
            progress('replace_container')
            renamed=True;api('POST','/containers/'+old['Id']+'/rename?name='+quote(backup_name))
            new_id=api('POST','/containers/create?name='+quote(manager.container),spec)['Id']
            transaction['new_id']=new_id;record('created')
            api('POST','/containers/'+new_id+'/start');step('replace_container','Neuer Container mit bisherigen Einstellungen und kopierten Daten gestartet.',True)
            progress('verify');record('verifying')
            deadline=time.monotonic()+300;healthy=False
            while time.monotonic()<deadline:
                state=api('GET','/containers/'+new_id+'/json')['State']
                if state.get('Running'):
                    try:healthy=manager.installed_version()==target and state.get('Health',{}).get('Status','healthy')=='healthy'
                    except (OSError,ValueError):healthy=False
                    if healthy:break
                time.sleep(3)
            if not healthy:raise UpdateError('Neuer Container meldet nicht die erwartete Version oder wird nicht gesund.')
            record('completed');step('verify','Neue Version und Containerzustand bestätigt.')
            return dict(ok=True,supported=True,message='Open WebUI auf '+target+' aktualisiert. Alter Container und ursprüngliches Datenvolume bleiben als Rückfallstand erhalten.',steps=steps,backup_container=backup_name,backup_volume=old_volume,target_version=target)
        except Exception as exc:
            message=str(exc) if isinstance(exc,UpdateError) else 'Technischer Fehler ('+type(exc).__name__+'); geschützte Transaktionsdaten prüfen.'
            step('update_failed',message,changed,'failed');rollback_ok=not stopped
            if stopped and old:
                try:
                    progress('rollback')
                    # Only delete a replacement created by this transaction.
                    if new_id:api('DELETE','/containers/'+new_id+'?force=1')
                    elif renamed:
                        candidates=api('GET','/containers/json?all=1&filters='+quote(json.dumps({'label':['server-manager.open-webui-transaction='+transaction['id']]})))
                        for candidate in candidates:api('DELETE','/containers/'+candidate['Id']+'?force=1')
                    if renamed and api('GET','/containers/'+old['Id']+'/json').get('Name')!='/'+manager.container:api('POST','/containers/'+old['Id']+'/rename?name='+quote(manager.container))
                    api('POST','/containers/'+old['Id']+'/update',{'RestartPolicy':old['HostConfig']['RestartPolicy']})
                    api('POST','/containers/'+old['Id']+'/start')
                    rollback_ok=True;step('rollback','Ursprünglicher Container mit unverändertem Originalvolume wieder gestartet.',True)
                except Exception:
                    step('rollback','Automatische Rückkehr fehlgeschlagen. Alten Container anhand der Transaktionsdaten wieder starten.',True,'failed')
            if folder:record('rolled_back' if rollback_ok and stopped else 'failed')
            return dict(ok=False,supported=True,message=message,steps=steps,rollback_succeeded=bool(stopped and rollback_ok),backup_container=backup_name)
