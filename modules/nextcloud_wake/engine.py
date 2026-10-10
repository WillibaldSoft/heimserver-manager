"""Local wake-gateway installer; public routing is a separate explicit step."""
import hashlib,json,os,re,socket,ssl,subprocess,tempfile,time
from pathlib import Path
from urllib.parse import urlsplit
CONF=Path('/etc/server-manager-nextcloud-wake/config.json')
UNIT=Path('/etc/systemd/system/server-manager-nextcloud-wake.service')
PROGRAM=Path('/opt/server-manager-nextcloud-wake/gateway.py')
STATE=Path('/var/lib/server-manager/nextcloud-wake')
MARKER='# Heimserver Manager Nextcloud Wake'
UNIT_TEXT='''# Heimserver Manager Nextcloud Wake
[Unit]
Description=Nextcloud Wake Gateway
After=network-online.target
Wants=network-online.target
[Service]
DynamicUser=yes
LoadCredential=config.json:/etc/server-manager-nextcloud-wake/config.json
ExecStart=/usr/bin/python3 /opt/server-manager-nextcloud-wake/gateway.py
Restart=on-failure
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
[Install]
WantedBy=multi-user.target
'''
def load():return json.loads(CONF.read_text()) if CONF.exists() else {}
def load_draft():
    p=STATE/'draft.json'
    return json.loads(p.read_text()) if p.exists() else {}
def revision():return hashlib.sha256(((STATE/'draft.json').read_bytes() if (STATE/'draft.json').exists() else b'')+(CONF.read_bytes() if CONF.exists() else b'')+(UNIT.read_bytes() if UNIT.exists() else b'')).hexdigest()
def validate(conf,require_credentials=True):
    from modules.web_security.reverse_proxy import backend
    if len(conf['domain'])>253 or not all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',part) for part in conf['domain'].split('.')):raise ValueError('Gültigen Nextcloud-Domainnamen eingeben.')
    up=backend(conf['backend']);conf=dict(conf,backend=up['url'].rstrip('/'))
    health=conf.get('health_path','/status.php')
    if not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*status\.php',health):raise ValueError('Status-Pfad muss /status.php oder /unterordner/status.php sein.')
    conf['health_path']=health
    for key in ('recovery_url','manager_url'):
        value=conf[key];u=urlsplit(value)
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.fragment or u.query or any(c.isspace() for c in value):raise ValueError('Ungültige '+key)
        if key=='manager_url' and (u.scheme!='https' or u.path not in ('','/')):raise ValueError('Manager-Adresse muss HTTPS ohne Unterpfad verwenden.')
        if key=='recovery_url' and u.path!='/recover':raise ValueError('Recovery-Adresse muss auf /recover enden.')
        u.port
    conf['manager_url']=conf['manager_url'].rstrip('/')
    for key,low,high in [('port',1024,65535),('wake_wait',10,180),('hold_seconds',30,3600),('wake_cooldown',30,1800)]:
        conf[key]=int(conf[key])
        if not low<=conf[key]<=high:raise ValueError(key+': Wert außerhalb erlaubtem Bereich.')
    if (require_credentials or conf.get('token')) and not re.fullmatch(r'[A-Za-z0-9_-]{20,256}',conf.get('token','')):raise ValueError('Dediziertes Blocker-Profil vom Nextcloud-Server erforderlich.')
    if conf.get('ca_pem'):ssl.create_default_context().load_verify_locations(cadata=conf['ca_pem'])
    if up['port']==conf['port'] and up['host'] in ('localhost','127.0.0.1'):raise ValueError('Gateway darf nicht sein eigenes Ziel sein.')
    return conf

def atomic(p,text,mode=0o600):
    p.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=p.parent)
    try:
        with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,mode);os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def save_draft(config,expected_revision):
    import fcntl
    checked=validate(config,require_credentials=False)
    # Drafts intentionally contain no agent credentials and never start services.
    checked={k:v for k,v in checked.items() if k not in ('token','ca_pem')}
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (STATE/'draft.lock').open('a') as lock:
        os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX)
        if revision()!=expected_revision:raise ValueError('Einstellungen geändert. Erneut öffnen.')
        atomic(STATE/'draft.json',json.dumps(checked))
    return checked

def info():
    if any(p.is_symlink() for p in (CONF,UNIT,PROGRAM)):raise ValueError('Abweichender Installationspfad; manuell prüfen.')
    installed=UNIT.exists()
    if installed and UNIT.read_text()!=UNIT_TEXT:raise ValueError('Unbekannter Gateway-Dienst; keine Überschreibung.')
    status=subprocess.run(['systemctl','is-active','server-manager-nextcloud-wake.service'],capture_output=True,text=True,timeout=10).stdout.strip()
    return dict(installed=installed,active=status,revision=revision())
def execute(plan,credentials):
    conf=validate(dict(plan['config'],**credentials));state=info()
    if revision()!=plan['revision']:raise ValueError('Einstellungen geändert. Erneut öffnen.')
    if state['installed'] and state['active']=='active':
        import urllib.request
        with urllib.request.urlopen('http://127.0.0.1:'+str(load()['port'])+'/__wake_health',timeout=5) as r:
            if json.load(r).get('active',1):raise ValueError('Übertragungen aktiv. Aktualisierung später durchführen.')
    if state['active']!='active' or conf['port']!=load().get('port'):
        with socket.socket() as s:s.bind(('127.0.0.1',conf['port']))
    for args in (['apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'],['apt-get','-o','DPkg::Lock::Timeout=60','--no-remove','-y','install','python3-aiohttp']):subprocess.run(args,check=True)
    if revision()!=plan['revision']:raise ValueError('Einstellungen inzwischen geändert.')
    backup=STATE/('before-'+str(time.time_ns()));backup.mkdir(parents=True,mode=0o700);STATE.chmod(0o700)
    previous={p:p.read_bytes() if p.exists() else None for p in (CONF,UNIT,PROGRAM)}
    for i,(p,data) in enumerate(previous.items()):
        if data is not None:atomic(backup/str(i),data.decode())
    if state['active']=='active':
        import urllib.request
        old=load()
        req=urllib.request.Request('http://127.0.0.1:'+str(old['port'])+'/__wake_drain',data=b'',headers={'Authorization':'Bearer '+old['token']})
        with urllib.request.urlopen(req,timeout=5) as r:
            if not json.load(r).get('ok'):raise ValueError('Dienst konnte nicht angehalten werden.')
    try:
        CONF.parent.mkdir(parents=True,exist_ok=True,mode=0o700);CONF.parent.chmod(0o700)
        atomic(CONF,json.dumps(conf));atomic(UNIT,UNIT_TEXT,0o644)
        atomic(PROGRAM,(Path(__file__).resolve().parents[2]/'tools/nextcloud_wake/gateway.py').read_text(),0o644)
        for cmd in (['systemctl','daemon-reload'],['systemctl','enable','server-manager-nextcloud-wake.service'],['systemctl','restart','server-manager-nextcloud-wake.service']):subprocess.run(cmd,check=True)
        time.sleep(2);subprocess.run(['systemctl','is-active','--quiet','server-manager-nextcloud-wake.service'],check=True)
    except Exception:
        if not state['installed']:subprocess.run(['systemctl','disable','--now','server-manager-nextcloud-wake.service'])
        for p,data in previous.items():
            if data is None:p.unlink(missing_ok=True)
            else:atomic(p,data.decode(),0o600 if p==CONF else 0o644)
        subprocess.run(['systemctl','daemon-reload'])
        subprocess.run(['systemctl','restart' if state['active']=='active' else 'stop','server-manager-nextcloud-wake.service'])
        raise ValueError('Gateway-Installation fehlgeschlagen; Dateien zurückgesichert. Dienst prüfen.') from None
    print('Wake-Gateway installiert, nur auf Loopback. Öffentliche Verbindung unverändert. HTTPS-Proxy separat einrichten.',flush=True)
