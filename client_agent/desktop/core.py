"""Unprivileged configuration and service control for the existing shell agent."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,os,re,shlex,shutil,subprocess,tempfile,time,urllib.request,urllib.parse,urllib.error
from pathlib import Path
LIB=Path(__file__).resolve().parent
CONFIG=Path.home()/'.config/server-manager-client/config'
KEYS=['SERVER_URL','IPMI_RECOVER_URL','TOKEN','CLIENT_NAME','CLIENT_MAC','CLIENT_MODE','WAKE_METHOD','SERVER_MAC','WAKE_TIMEOUT']
DEFAULTS=dict(SERVER_URL='',IPMI_RECOVER_URL='',TOKEN='',CLIENT_NAME='Client',CLIENT_MAC='',CLIENT_MODE='without_server',WAKE_METHOD='none',SERVER_MAC='',WAKE_TIMEOUT='40')
UNITS=['server-manager-client-heartbeat.timer','server-manager-client.service','server-manager-client-heartbeat.service']
class Error(ValueError):pass

def parse_config(text):
    if len(text)>65536:raise Error(tr('Konfiguration ist zu groß.'))
    values=dict(DEFAULTS)
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        key,sep,value=line.partition('=')
        if not sep or key not in KEYS:raise Error(tr('Unbekannte Konfigurationszeile. Bitte JSON-Profil aus dem Manager verwenden.'))
        # Parse shell quoting as data, never source or evaluate it in the GUI.
        if "$'" in value:raise Error(tr('Spezielle Bash-Zeichenfolge: bitte JSON-Profil importieren.'))
        words=shlex.split(value,posix=True)
        if len(words)>1:raise Error(tr('Ungültige Konfigurationszeile.'))
        values[key]=words[0] if words else ''
    values['CLIENT_MODE']={'connected':'with_server','auto':'with_server','release-only':'without_server','disabled':'without_server'}.get(values['CLIENT_MODE'],values['CLIENT_MODE'])
    return values

def load():
    return parse_config(CONFIG.read_text()) if CONFIG.exists() else dict(DEFAULTS)

def validate(values):
    result={k:str(values.get(k,DEFAULTS[k])).strip() for k in KEYS}
    for key,value in result.items():
        if len(value)>2048 or any(ord(c)<32 for c in value):raise Error(tr('Ungültige Eingabe: ')+key)
    for key in ['SERVER_URL','IPMI_RECOVER_URL']:
        if not result[key] and key=='IPMI_RECOVER_URL':continue
        u=urllib.parse.urlsplit(result[key])
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.fragment or any(c.isspace() for c in result[key]):raise Error(tr('HTTP(S)-Adresse ohne Zugangsdaten eingeben: ')+key)
        if key=='SERVER_URL' and u.query:raise Error(tr('Manager-Adresse ohne Abfrageparameter eingeben.'))
        try:u.port
        except ValueError:raise Error(tr('Ungültiger Port.'))
    if not result['TOKEN'] or not result['CLIENT_NAME']:raise Error(tr('Token und Client-Name sind erforderlich.'))
    for key in ['CLIENT_MAC','SERVER_MAC']:
        if result[key] and not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',result[key]):raise Error(tr('Ungültige MAC-Adresse: ')+key)
    if result['CLIENT_MODE'] not in ('with_server','without_server','wake_on_access'):raise Error(tr('Ungültiger Betriebsmodus.'))
    if result['WAKE_METHOD'] not in ('none','recover','wol','both'):raise Error(tr('Ungültige Weckmethode.'))
    if result['WAKE_METHOD'] in ('wol','both') and not result['SERVER_MAC']:raise Error(tr('Für Wake-on-LAN fehlt die Server-MAC.'))
    if result['WAKE_METHOD'] in ('recover','both') and not result['IPMI_RECOVER_URL']:raise Error(tr('Recovery-Adresse fehlt.'))
    if not result['WAKE_TIMEOUT'].isdigit() or not 1<=int(result['WAKE_TIMEOUT'])<=300:raise Error(tr('Timeout: 1 bis 300 Sekunden.'))
    result['SERVER_URL']=result['SERVER_URL'].rstrip('/')
    return result

def atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def save(values):
    values=validate(values)
    atomic(CONFIG,''.join(k+'='+shlex.quote(values[k])+'\n' for k in KEYS))
    return values

def read_profile(path):
    path=Path(path)
    if path.stat().st_size>65536:raise Error(tr('Profil zu groß.'))
    data=json.loads(path.read_text())
    if data.get('format')!='heimserver-manager-client' or data.get('version')!=1:raise Error(tr('Kein unterstütztes Client-Profil.'))
    return validate(data['config'])

def systemctl(*args,check=True):
    p=subprocess.run(['systemctl','--user',*args],capture_output=True,text=True,timeout=30)
    if check and p.returncode:raise Error(tr('Benutzerdienst konnte nicht geändert werden. Anmeldung und systemd-Benutzersitzung prüfen.'))
    return p.stdout.strip()

def enabled():return systemctl('is-enabled','server-manager-client-heartbeat.timer',check=False)=='enabled'

def install_user():
    import device_identity
    save(device_identity.enroll(validate(load())))
    directory=Path.home()/'.config/systemd/user';directory.mkdir(parents=True,exist_ok=True)
    backup=Path.home()/'.local/state/heimserver-manager-client'/('before-'+str(time.time_ns()));backup.mkdir(parents=True,mode=0o700)
    previous={}
    for name in UNITS:
        target=directory/name
        if target.is_symlink():raise Error(tr('Vorhandene Unit ist ein symbolischer Link; bitte manuell prüfen.'))
        previous[name]=target.read_bytes() if target.exists() else None
        if target.exists():shutil.copyfile(target,backup/name)
    if CONFIG.exists():shutil.copyfile(CONFIG,backup/'config');(backup/'config').chmod(0o600)
    was_enabled={name:systemctl('is-enabled',name,check=False)=='enabled' for name in UNITS}
    systemctl('stop',*UNITS,check=False)
    try:
        for name in UNITS:atomic(directory/name,(LIB/'units'/name).read_text())
        systemctl('daemon-reload');systemctl('enable','server-manager-client.service')
        systemctl('enable','--now','server-manager-client-heartbeat.timer')
        atomic(Path.home()/'.config/autostart/heimserver-manager-client.desktop',(LIB/'autostart.desktop').read_text())
    except Exception:
        systemctl('disable','--now',*UNITS,check=False)
        for name,content in previous.items():
            if content is None:(directory/name).unlink(missing_ok=True)
            else:atomic(directory/name,content.decode())
        systemctl('daemon-reload',check=False)
        for name,active in was_enabled.items():
            if active:systemctl('enable',name,check=False)
        if was_enabled[UNITS[0]]:systemctl('start',UNITS[0],check=False)
        raise
    return tr('Agent aktiviert. Bisherige Units und Konfiguration gesichert. Kein zusätzlicher Agent eingerichtet.')

def deactivate():
    systemctl('disable','--now',*UNITS,check=False)
    atomic(Path.home()/'.config/autostart/heimserver-manager-client.desktop','[Desktop Entry]\nType=Application\nName=Heimserver Manager Client\nHidden=true\n')
    return tr('Agent und Desktop-Autostart deaktiviert. Konfiguration bleibt erhalten.')

def action(name):
    if name not in ('wake','need','release','connect','access','status','auto'):raise Error(tr('Unbekannte Aktion.'))
    save(load())
    result=subprocess.run(['/bin/bash',str(LIB/'agent.sh'),name],capture_output=True,text=True,timeout=720)
    if result.returncode:raise Error(tr('Agent-Aktion fehlgeschlagen. Verbindung und Einstellungen prüfen.'))
    return tr('Aktion beendet. Die Erreichbarkeit wird separat geprüft.')

def status():
    config=load();state=dict(online=False,connected=False,service=False,message=tr('Noch nicht eingerichtet'))
    if not config['SERVER_URL']:return state
    try:
        # Health probe deliberately carries no agent token and follows no redirects.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        response=urllib.request.build_opener(NoRedirect).open(config['SERVER_URL']+'/api/health',timeout=4)
        state['online']=response.status==200;response.close()
        state['message']=tr('Server erreichbar · Agenten-Anmeldung nicht bestätigt')
        if config.get('TOKEN') and not config['TOKEN'].startswith('setup:'):
            import device_identity
            headers=dict(device_identity.headers(),Authorization='Bearer '+config['TOKEN'])
            req=urllib.request.Request(config['SERVER_URL']+'/api/clients/status',headers=headers)
            try:
                with urllib.request.build_opener(NoRedirect).open(req,timeout=4) as r:
                    state['connected']=r.status==200 and json.load(r).get('ok') is True
                if state['connected']:state['message']=tr('Verbunden · Agenten-Anmeldung bestätigt')
            except Exception:pass
    except Exception:state['message']=tr('Server nicht erreichbar')
    try:state['service']=systemctl('is-active','server-manager-client-heartbeat.timer',check=False)=='active'
    except Exception:pass
    return state

def logs():
    result=subprocess.run(['journalctl','--user','-u','server-manager-client-heartbeat.service','-u','server-manager-client.service','-n','60','--no-pager','-o','cat'],capture_output=True,text=True,timeout=15)
    text=result.stdout
    try:
        cfg=load()
        for key in ['TOKEN','IPMI_RECOVER_URL']:
            if cfg[key]:text=text.replace(cfg[key],'[geschützt]')
    except Exception:pass
    return text or tr('Keine Benutzerprotokolle verfügbar.')


def hostname():
    import socket
    return socket.gethostname()

def rename_host(value):
    value=value.strip().lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',value) or value.isdigit():
        raise Error('Hostname: 1–63 Buchstaben/Ziffern oder Bindestriche, ohne Leerzeichen; keine reine Zahl.')
    if value==hostname():return tr('Hostname unverändert.')
    # systemd-hostnamed performs the privileged operation through Polkit.
    result=subprocess.run(['/usr/bin/hostnamectl','set-hostname',value],capture_output=True,text=True,timeout=120)
    if result.returncode:raise Error(tr('Hostname nicht geändert. Administratorfreigabe abgebrochen oder vom System abgelehnt.'))
    if hostname()!=value:raise Error(tr('Hostname noch nicht aktiv. Betriebssystem-Einstellungen prüfen.'))
    return tr('Hostname geändert. Agent aktivieren / übernehmen, damit der nächste Heartbeat den neuen Namen meldet.')
