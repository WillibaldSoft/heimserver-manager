"""Persistent, serialized installer jobs owned by a dedicated systemd unit."""
import os
import contextlib,fcntl,io,json,os,re,subprocess,sys,time,uuid,zipfile
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from modules.app_manager import install_catalog as c,install_runtime as runtime
else:
    from . import install_catalog as c,install_runtime as runtime
JOBS=Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'app-installers/jobs'))
TERMINAL={'completed','failed','interrupted'}

def atomic(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2));os.chmod(temp,0o600);os.replace(temp,path)

@contextlib.contextmanager
def lock():
    JOBS.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(JOBS/'lock','a') as stream:
        os.chmod(stream.name,0o600)
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield

def job_path(key):
    if not re.fullmatch('[a-f0-9]{32}',key):raise c.Invalid('Ungültiger Installationsauftrag.')
    return JOBS/key

def load(key):
    path=job_path(key)/'status.json'
    if not path.is_file():raise c.Invalid('Installationsauftrag nicht gefunden.')
    value=json.loads(path.read_text())
    if value['state'] not in TERMINAL and time.time()-value['created']>30:
        unit='servermgr-app-install-'+key+'.service'
        r=subprocess.run(['systemctl','is-active',unit],capture_output=True,text=True,timeout=10)
        if r.stdout.strip() not in ('active','activating','reloading'):
            value=dict(value,state='interrupted',message='Installationsprozess wurde beendet. Protokoll prüfen; vorhandene Dateien bleiben erhalten.')
    return value

def active():
    pointer=JOBS/'active.json'
    if not pointer.exists():return None
    state=load(json.loads(pointer.read_text())['id'])
    return state if state['state'] not in TERMINAL else None

def start(profile,bind,action="install",plan=None,credentials=None):
    if action not in ('install','uninstall','restore','repair','manager_update','pihole_network','pihole_native_install','pihole_password','pihole_import','power_api','nextcloud_wake'):raise c.Invalid('Ungültige App-Aktion.')
    import ipaddress,socket
    if ipaddress.ip_address(bind).version!=4:raise c.Invalid('Bitte eine lokale IPv4-Bind-Adresse wählen.')
    with socket.socket() as check_socket:
        try:check_socket.bind((bind,0))
        except OSError:raise c.Invalid('Diese IPv4-Adresse ist auf dem Server nicht verfügbar.') from None
    from .install_ui import package
    with lock():
        if active():raise c.Invalid('Ein App-Auftrag läuft bereits.')
        if action=='nextcloud_wake':
            from modules.nextcloud_wake import engine as wake
            from .apt_jobs import active as apt_active
            from modules.web_security.jobs import active as web_active
            if apt_active() or web_active():raise c.Invalid('Laufende Paketinstallation abwarten.')
            if wake.revision()!=plan['revision']:raise c.Invalid('Gateway-Einstellungen geändert.')
            wake.validate(dict(plan['config'],**(credentials or {})))
        if action=='power_api':
            from tools.power_api.install import inspect
            from tools.power_api.power_api import validate as validate_power
            from .apt_jobs import active as apt_active
            from modules.web_security.jobs import active as web_active
            from modules.scanner.engine import active as scanner_active
            if apt_active() or web_active() or scanner_active():raise c.Invalid('Bitte laufende Installationsaufträge abwarten.')
            validate_power(plan['config'])
            current=inspect()
            if current['kind']=='unknown' or current['revision']!=plan['revision']:raise c.Invalid('Recovery-Bestand geändert oder nicht unterstützt.')
        if action=='manager_update':
            from modules.manager_update.engine import validate
            from modules.app_manager.apt_jobs import active as apt_active
            from modules.web_security.jobs import active as web_active
            from modules.scanner.engine import active as scanner_active
            if apt_active() or web_active() or scanner_active():raise c.Invalid('Bitte laufende Paket- oder Installationsaufträge abwarten.')
            validate(plan)
        if action=='pihole_import':
            from .pihole_transfer import validate
            if profile['app_id']!='pihole':raise c.Invalid('Ungültige App.')
            validate(plan)
        if action=='pihole_password':
            from .pihole_password import prepare
            if profile['app_id']!='pihole' or prepare()!=plan:raise c.Invalid('Passwortprüfung veraltet.')
        if action=='pihole_native_install':
            from .pihole_setup import validate
            if profile['app_id']!='pihole' or validate(plan)!=plan:raise c.Invalid('Installationsprüfung veraltet.')
        if action=='pihole_network':
            from .pihole_network import prepare
            if profile['app_id']!='pihole' or prepare(plan['bind'],plan['port'])!=plan:raise c.Invalid('Netzwerkprüfung veraltet.')
        if action=='repair':
            from modules.repair_scripts.engine import validate
            validate(plan)
        if action=='install' and (profile.get('local_ai') or profile.get('https')):
            from modules.app_manager.apt_jobs import active as apt_active
            from modules.web_security.jobs import active as web_active
            from modules.scanner.engine import active as scanner_active
            if apt_active() or web_active() or scanner_active():raise c.Invalid('Bitte laufende Paketinstallationen abwarten.')
        issues=runtime.checks(profile) if action == 'install' else []
        if issues:raise c.Invalid('Installation nicht möglich: '+'; '.join(issues))
        # Existing backup/update jobs must finish before a new app installation.
        from .plugin import get_active_job
        if get_active_job():raise c.Invalid('Ein App-Backup oder anderer Auftrag läuft. Bitte dessen Abschluss abwarten.')
        key=uuid.uuid4().hex;folder=job_path(key);folder.mkdir(mode=0o700)
        if action == 'install':
            data=package(profile)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    if '/' in name or '\\' in name or name in ('.','..'):raise c.Invalid('Ungültiger Paketinhalt.')
                    path=folder/name;path.write_bytes(archive.read(name));os.chmod(path,0o600)
        if action=='manager_update':
            from modules.manager_update.engine import claim
            claim(plan)
        if credentials is not None:atomic(folder/'credentials.json',credentials)
        state=dict(id=key,app_id=profile['app_id'],label=profile['label'],created=time.time(),state='queued',bind=bind,action=action,plan=plan,message='App-Auftrag wird gestartet.')
        atomic(folder/'status.json',state);atomic(JOBS/'active.json',{'id':key})
        args=['systemd-run','--quiet','--collect','--unit=servermgr-app-install-'+key,'--property=Type=exec','--property=UMask=0077','--property=RuntimeMaxSec=1h',*['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE','SERVER_MANAGER_DB','SERVER_MANAGER_PORT') if k in os.environ],'/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key]
        try:
            result=subprocess.run(args,capture_output=True,text=True,timeout=20)
            if result.returncode:raise c.Invalid('Installationsdienst konnte nicht gestartet werden.')
        except (OSError,subprocess.TimeoutExpired,c.Invalid):
            (folder/'credentials.json').unlink(missing_ok=True)
            atomic(folder/'status.json',dict(state,state='failed',message='Installationsdienst konnte nicht gestartet werden.'))
            raise c.Invalid('Installationsdienst konnte nicht gestartet werden.') from None
        return key

def worker(key):
    folder=job_path(key);state=json.loads((folder/'status.json').read_text())
    with open(folder/'install.log','a',buffering=1) as log:
        os.chmod(log.name,0o600);os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
        atomic(folder/'status.json',dict(state,state='running',message='App-Auftrag läuft. Bitte Abschluss abwarten.'))
        try:
            if state.get('action', 'install') == 'install':
                profile=json.loads((folder/'profile.json').read_text())
                credential_file=folder/'credentials.json'
                try:
                    if profile['kind']=='nextcloud_setup':
                        runtime.install(profile,folder,state['bind'],credentials=json.loads(credential_file.read_text()) if credential_file.exists() else {})
                        from modules.app_manager.nextcloud_ui import remember_installation
                        remember_installation(profile)
                    else:
                        runtime.install(profile,folder,state['bind'])
                        if profile['app_id']=='open_webui' and profile.get('https'):
                            from .openwebui_https import values
                            host,port,ip=values(profile);saved=c.read();saved.setdefault('web',{})['open_webui']='https://'+host+':'+str(port);c.write(saved)
                finally:credential_file.unlink(missing_ok=True)
            elif state.get('action')=='manager_update':
                from modules.manager_update.engine import execute
                execute(state['plan'])
            elif state.get('action')=='pihole_import':
                from modules.app_manager.pihole_transfer import execute
                execute(state['plan'],folder)
            elif state.get('action')=='pihole_password':
                from modules.app_manager.pihole_password import execute
                credential_file=folder/'credentials.json'
                try:execute(state['plan'],json.loads(credential_file.read_text()) if credential_file.exists() else {})
                finally:credential_file.unlink(missing_ok=True)
            elif state.get('action')=='pihole_native_install':
                from modules.app_manager.pihole_setup import execute
                credential_file=folder/'credentials.json'
                try:execute(state['plan'],json.loads(credential_file.read_text()) if credential_file.exists() else {},folder)
                finally:credential_file.unlink(missing_ok=True)
            elif state.get('action')=='pihole_network':
                from modules.app_manager.pihole_network import execute
                credential_file=folder/'credentials.json'
                try:execute(state['plan'],json.loads(credential_file.read_text()) if credential_file.exists() else {})
                finally:credential_file.unlink(missing_ok=True)
            elif state.get('action')=='nextcloud_wake':
                from modules.nextcloud_wake.engine import execute
                credential_file=folder/'credentials.json'
                try:execute(state['plan'],json.loads(credential_file.read_text()))
                finally:credential_file.unlink(missing_ok=True)
            elif state.get('action')=='power_api':
                from tools.power_api.install import apply
                credential_file=folder/'credentials.json'
                try:apply(state['plan']['config'],json.loads(credential_file.read_text()).get('password',''),state['plan']['revision'])
                finally:credential_file.unlink(missing_ok=True)
            elif state.get('action')=='repair':
                from modules.repair_scripts.engine import execute
                execute(state['plan'])
            else:
                from modules.app_manager import lifecycle
                from modules.app_manager.registry import get_manager
                manager=get_manager(state['app_id'])
                if manager is None:raise c.Invalid('App nicht gefunden.')
                if state['action']=='uninstall':lifecycle.execute(manager,state['plan'])
                elif state['action']=='restore':lifecycle.restore(manager)
                else:raise c.Invalid('Ungültige Aktion.')
            if state.get('action') not in ('uninstall','repair','manager_update','pihole_network','power_api','nextcloud_wake'):
                from modules.app_manager.visibility import set_hidden, set_removed
                set_hidden(state['app_id'],False);set_removed(state['app_id'],False)
            result=dict(state,state='completed',message='Manager-Update abgeschlossen.' if state.get('action')=='manager_update' else 'Reparatur abgeschlossen. Ergebnisprotokoll prüfen.' if state.get('action')=='repair' else 'App-Auftrag abgeschlossen. Ergebnis in Apps verwalten prüfen.',finished=time.time())
        except Exception as exc:
            print('App-Auftrag fehlgeschlagen:',str(exc) if isinstance(exc,(c.Invalid,runtime.InstallError,ValueError)) else type(exc).__name__,flush=True)
            result=dict(state,state='failed',message=('Endgültige Deinstallation fehlgeschlagen. Daten können bereits unwiderruflich gelöscht sein. Protokoll und verbleibenden Bestand prüfen; keine automatische Rücksicherung.' if isinstance(state.get('plan'),dict) and state['plan'].get('mode')=='purge' else 'App-Auftrag fehlgeschlagen. Protokoll prüfen; Änderungen können teilweise erfolgt sein. Aufbewahrte Daten bleiben erhalten.'),finished=time.time())
        atomic(folder/'status.json',result)
    return 0 if result['state']=='completed' else 1

def get_blockers(ctx=None):
    state=active()
    if not state:return []
    return [dict(source='Apps',type='app-installation',title='App-Auftrag läuft',reason=state['label'],priority=90,url='/apps/installers/jobs/'+state['id'])]

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit('Nur interner Worker-Aufruf unterstützt.')
    raise SystemExit(worker(sys.argv[2]))
