#!/usr/bin/env python3
"""Install/update known Recovery APIs; never execute imported legacy source."""
import argparse,ast,fcntl,getpass,hashlib,ipaddress,json,os,shutil,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
try:from .power_api import validate,VERSION
except ImportError:from power_api import validate,VERSION
ROOT=Path('/opt/server-manager-power-api');CONFIG=Path('/etc/server-manager-power-api')
UNIT=Path('/etc/systemd/system/ipmi-power-api.service');LEGACY=Path('/opt/ipmi-power-api.py')
STATE=Path('/var/lib/server-manager-power-api');BACKUPS=Path('/var/lib/server-manager/power-api-backups')
MARKER='# Heimserver Manager Power API installer'
UNIT_TEXT='''# Heimserver Manager Power API installer
[Unit]
Description=IPMI Power and Recovery API
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
DynamicUser=yes
StateDirectory=server-manager-power-api
LoadCredential=config.json:/etc/server-manager-power-api/config.json
LoadCredential=ipmi-password:/etc/server-manager-power-api/ipmi-password
ExecStart=/usr/bin/python3 /opt/server-manager-power-api/power_api.py
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=CAP_NET_RAW
AmbientCapabilities=CAP_NET_RAW
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_INET AF_UNIX
[Install]
WantedBy=multi-user.target
'''

def literals(path):
    result={}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            try:result[node.targets[0].id]=ast.literal_eval(node.value)
            except (ValueError,TypeError):pass
    return result

def fingerprint():
    h=hashlib.sha256()
    for p in (UNIT,LEGACY,ROOT/'power_api.py',CONFIG/'config.json',CONFIG/'ipmi-password'):
        h.update(str(p).encode());h.update(p.read_bytes() if p.is_file() else b'missing')
    return h.hexdigest()

def service_state():
    r=subprocess.run(['systemctl','show','ipmi-power-api.service','-p','ActiveState','-p','UnitFileState','-p','FragmentPath','-p','DropInPaths'],capture_output=True,text=True,timeout=10,check=True)
    return dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)

def inspect():
    props=service_state();kind='missing';version='';conf={};reason=''
    paths=(UNIT,LEGACY,ROOT/'power_api.py',CONFIG/'config.json',CONFIG/'ipmi-password')
    if any(p.is_symlink() for p in paths):raise ValueError('Symbolische Verknüpfungen im Installationsbestand: manuell prüfen.')
    if props.get('DropInPaths'):kind='unknown';reason='Eigene systemd-Erweiterungen erkannt; zuerst manuell prüfen.'
    elif UNIT.exists():
        text=UNIT.read_text();commands=[line.strip() for line in text.splitlines() if line.strip().startswith('Exec')]
        if MARKER in text and commands==['ExecStart=/usr/bin/python3 /opt/server-manager-power-api/power_api.py'] and (ROOT/'power_api.py').is_file() and (CONFIG/'config.json').is_file() and (CONFIG/'ipmi-password').is_file():
            version=str(literals(ROOT/'power_api.py').get('VERSION',''))
            kind='managed' if version in ('1.0','2.2') else 'unknown';conf=json.loads((CONFIG/'config.json').read_text())
        elif LEGACY.is_file() and commands==['ExecStart=/usr/bin/python3 /opt/ipmi-power-api.py']:
            old=literals(LEGACY);version=str(old.get('APP_VERSION',''))
            required=('SERVER_IP','IPMI_HOST','IPMI_USER','IPMI_PASS','LISTEN_HOST','LISTEN_PORT')
            if version=='2.1-stable' and all(k in old for k in required):
                kind='legacy';conf=dict(server_name=old.get('SERVER_NAME','Server'),server_ip=old['SERVER_IP'],ipmi_host=old['IPMI_HOST'],ipmi_user=old['IPMI_USER'],listen_host=old['LISTEN_HOST'],port=old['LISTEN_PORT'],allowed_clients=[],wait_seconds=old.get('BOOT_TIMEOUT',180),soft_wait_seconds=old.get('SOFT_TIMEOUT',180),reset_wait_seconds=old.get('RESET_TIMEOUT',180),allow_soft=True,allow_reset=True)
            else:kind='unknown'
        else:kind='unknown'
    elif LEGACY.exists() or ROOT.exists() or CONFIG.exists() or props.get('FragmentPath'):kind='unknown'
    if kind=='unknown':reason=reason or 'Unbekannte oder unvollständige Installation. Keine automatische Überschreibung.'
    return dict(kind=kind,version=version,config=conf,active=props.get('ActiveState','unknown'),enabled=props.get('UnitFileState',''),revision=fingerprint(),reason=reason,available=VERSION)

def api_status(conf):
    host=conf['listen_host'];host='127.0.0.1' if host=='0.0.0.0' else host
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**k):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect)
    with opener.open('http://'+host+':'+str(int(conf['port']))+'/status',timeout=40) as r:
        data=json.loads(r.read(65536))
    if type(data.get('recover_active')) is not bool:raise ValueError('Recovery-Aktivität nicht eindeutig prüfbar.')
    return data

def write(path,data,mode=0o600):
    fd,temp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(temp,mode);os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
def run(args):subprocess.run(args,check=True,stdin=subprocess.DEVNULL)

def apply(conf,password,expected):
    if os.geteuid()!=0:raise ValueError('Installation benötigt root-Rechte.')
    validate(conf)
    if not isinstance(password,str) or '\n' in password or '\r' in password or '\x00' in password:raise ValueError('Ungültiges Passwortformat.')
    BACKUPS.mkdir(parents=True,exist_ok=True,mode=0o700);BACKUPS.chmod(0o700)
    with (BACKUPS/'install.lock').open('a') as lock:
        os.chmod(lock.name,0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        old=inspect()
        if old['revision']!=expected or old['kind']=='unknown':raise ValueError('Bestand geändert oder nicht unterstützt. Neu prüfen.')
        if old['kind']=='missing' and not password:raise ValueError('IPMI-Passwort erforderlich.')
        if not password:
            password=(literals(LEGACY)['IPMI_PASS'] if old['kind']=='legacy' else (CONFIG/'ipmi-password').read_text().rstrip('\n'))
        if not isinstance(password,str) or not password or any(c in password for c in '\r\n\x00'):raise ValueError('Gespeichertes Passwort nicht übernehmbar.')
        running=old['active'] in ('active','activating','reloading')
        if running and api_status(old['config'])['recover_active']:raise ValueError('Recovery läuft. Installation erst nach Abschluss möglich.')
        if not running or (conf['listen_host'],int(conf['port']))!=(old['config'].get('listen_host'),int(old['config'].get('port',0))):
            # Changing wildcard to its local LAN address uses the same listener until stop.
            same=running and old['config'].get('listen_host')=='0.0.0.0' and int(conf['port'])==int(old['config']['port'])
            if not same:
                with socket.socket() as sock:sock.bind((conf['listen_host'],int(conf['port'])))
        run(['apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'])
        run(['apt-get','-o','DPkg::Lock::Timeout=60','--no-remove','-y','install','python3-flask','python3-waitress','ipmitool','iputils-ping'])
        if fingerprint()!=expected:raise ValueError('Bestand während Paketinstallation geändert. Erneut prüfen.')
        previous_status=api_status(old['config']) if running else {}
        if previous_status.get('recover_active'):raise ValueError('Recovery inzwischen gestartet. Keine Dienständerung vorgenommen.')
        backup=BACKUPS/(time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex());backup.mkdir(mode=0o700)
        files=[UNIT,LEGACY,ROOT/'power_api.py',CONFIG/'config.json',CONFIG/'ipmi-password',STATE/'status.json'];saved=[]
        for i,p in enumerate(files):
            if p.is_file():
                dst=backup/str(i);shutil.copyfile(p,dst);dst.chmod(0o600);saved.append((p,dst,p.stat().st_mode&0o777))
        write(backup/'inventory.json',json.dumps(dict(version=old['version'],active=old['active'],enabled=old['enabled'],files=[str(p) for p,_,_ in saved])))
        print('Geschützte Rücksicherung: '+str(backup),flush=True)
        try:
            run(['systemctl','stop','ipmi-power-api.service']) if old['kind']!='missing' else None
            CONFIG.mkdir(parents=True,exist_ok=True,mode=0o700);CONFIG.chmod(0o700);ROOT.mkdir(parents=True,exist_ok=True)
            write(CONFIG/'config.json',json.dumps(conf,indent=2)+'\n');write(CONFIG/'ipmi-password',password+'\n')
            write(ROOT/'power_api.py',Path(__file__).with_name('power_api.py').read_text(),0o644);write(UNIT,UNIT_TEXT,0o644)
            # Legacy plaintext credential remains only inside the protected backup.
            if old['kind']=='legacy':
                LEGACY.unlink()
                STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
                migrated={k:previous_status[k] for k in ('last_action','last_error','recover_count','reset_count') if k in previous_status}
                migrated.update(recover_active=False,phase='idle')
                write(STATE/'status.json',json.dumps(migrated))
            run(['systemctl','daemon-reload'])
            if old['kind']=='missing':run(['systemctl','enable','ipmi-power-api.service'])
            if running or old['kind']=='missing':
                run(['systemctl','start','ipmi-power-api.service']);time.sleep(2)
                run(['systemctl','is-active','--quiet','ipmi-power-api.service'])
                status=api_status(conf)
                if status.get('version')!=VERSION:raise ValueError('Neue API-Version nicht bestätigt.')
        except Exception:
            subprocess.run(['systemctl','stop','ipmi-power-api.service'],check=False)
            present={p for p,_,_ in saved}
            for p in files:
                if p not in present:p.unlink(missing_ok=True)
            for p,src,mode in saved:p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,p);p.chmod(mode)
            run(['systemctl','daemon-reload'])
            if old['kind']=='missing':subprocess.run(['systemctl','disable','ipmi-power-api.service'],check=False)
            if running:run(['systemctl','start','ipmi-power-api.service'])
            if old['kind']=='missing':
                for directory in (ROOT,CONFIG):
                    try:directory.rmdir()
                    except OSError:pass
            raise ValueError('Installation fehlgeschlagen; bisherige Dateien zurückgesichert. Dienststatus und Protokoll prüfen.') from None
        print('API '+VERSION+' installiert. Kein Power-/Reset-Befehl ausgelöst. Bisheriger Aktivierungs-/Autostartzustand bei Updates erhalten.',flush=True)

def ask(label,default=''):
    return input(label+(' ['+str(default)+']' if default!='' else '')+': ').strip() or default

def main():
    parser=argparse.ArgumentParser(description='Recovery-API installieren, aktualisieren oder bekannten Altbestand migrieren.')
    parser.add_argument('--configure',action='store_true',help='Kompatibler Alias; Bestand wird immer geprüft.')
    parser.parse_args()
    if os.geteuid()!=0:raise ValueError('Mit sudo python3 install.py oder als root ausführen.')
    old=inspect();print('Bestand:',old['kind'],old['version'])
    if old['kind']=='unknown':raise ValueError(old['reason'])
    conf=dict(old['config'])
    for k,label,default in [('server_name','Zielserver-Name','Server'),('server_ip','Zielserver IPv4',''),('ipmi_host','BMC IPv4',''),('ipmi_user','BMC Benutzer',''),('listen_host','Lokale konkrete LAN-IPv4','127.0.0.1'),('port','API-Port',8182),('wait_seconds','Wartezeit Einschalten',180),('soft_wait_seconds','Wartezeit Soft',180),('reset_wait_seconds','Wartezeit Reset',180)]:
        conf[k]=ask(label,conf.get(k,default))
    for k in ('port','wait_seconds','soft_wait_seconds','reset_wait_seconds'):conf[k]=int(conf[k])
    conf['allowed_clients']=[x.strip() for x in ask('Erlaubte Client-IPv4/Netze (kommagetrennt)',','.join(conf.get('allowed_clients',[]))).split(',') if x.strip()]
    conf['allowed_clients']=list(dict.fromkeys(conf['allowed_clients']+[conf['listen_host']+'/32','127.0.0.1/32']))
    print('Soft kann einen laufenden Rechner herunterfahren. Reset kann Datenverlust verursachen. Fehlender Ping unterscheidet Standby nicht von Netzwerkfehlern.')
    for k,label in [('allow_soft','Soft bei eingeschaltetem, nicht pingbarem Server'),('allow_reset','Einmaligen Reset nach Wartezeit')]:conf[k]=ask(label+' erlauben? ja/NEIN','ja' if conf.get(k,False) else 'NEIN')=='ja'
    validate(conf);password=getpass.getpass('BMC-Passwort (Bestand: leer = beibehalten): ')
    print('Während der Migration keine Recovery-Aufrufe starten. Bestandsadressen/Zugriffe nachher prüfen. Manuelle /soft, /reset und /cycle entfallen.')
    if ask('Geprüfte Einstellungen anwenden? ja/NEIN','NEIN')=='ja':apply(conf,password,old['revision'])
if __name__=='__main__':
    try:main()
    except Exception as exc:print('Fehler:',str(exc) if isinstance(exc,ValueError) else 'Installation fehlgeschlagen; Dienst und Paketverwaltung prüfen.',file=sys.stderr);raise SystemExit(1)
