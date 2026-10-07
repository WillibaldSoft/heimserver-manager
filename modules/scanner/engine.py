"""Manage the existing Scanner API; preserve its Home Assistant endpoints."""
import os
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import pwd
import grp
import stat
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.request import urlopen

ROOT=Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'scanner'))
CONFIG=ROOT/'config.json'
API=Path('/opt/scanner-api/scan_api.py')
UNIT=Path('/etc/systemd/system/scanner-api.service')
DROPIN=Path('/etc/systemd/system/scanner-api.service.d/server-manager.conf')
ENV=Path('/etc/scanner-api/server-manager.env')
SANE=Path('/etc/scanner-api/sane')
SESSION=Path('/var/lib/scansession')
PACKAGES=['python3','python3-flask','sane-utils','sane-airscan','img2pdf']
ORIGINAL='e50ba5953e85ea011588ac5bb459c831d636c1ecba616c5dc163066c688101df'
TERMINAL={'completed','failed','interrupted'}
DEFAULT=dict(mode='auto',ip='',protocol='eSCL',scanner_port=80,path='/eSCL/',device='auto',outdir='/srv/scanner/output',bind='127.0.0.1',port=8181,user='scanner',access='keep',access_group='')

class Problem(ValueError):pass

def run(args,timeout=20,**kwargs):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout,**kwargs)
    if r.returncode:raise Problem((r.stderr or r.stdout or 'Befehl fehlgeschlagen: '+args[0])[-1500:])
    return r.stdout

def atomic(path,data,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(data if isinstance(data,str) else json.dumps(data,ensure_ascii=False,indent=2))
    os.chmod(temp,mode);os.replace(temp,path)

def load():
    if CONFIG.exists():return dict(DEFAULT,**json.loads(CONFIG.read_text()))
    cfg=dict(DEFAULT)
    try:
        info=read_api(cfg,'/')
        cfg.update(device=info['device'],outdir=info['outdir'])
    except (OSError,ValueError,KeyError):pass
    # Discover the existing service identity instead of embedding a host account.
    if UNIT.exists():
        try:
            match=re.search(r'^User=([a-z_][a-z0-9_-]*)$', UNIT.read_text(), re.M)
            if match:cfg['user']=match[1]
        except OSError:pass
    return cfg

def revision():return hashlib.sha256(CONFIG.read_bytes() if CONFIG.exists() else b'initial').hexdigest()

def validate(data,allow_create=False):
    c={k:str(data.get(k,v)).strip() for k,v in DEFAULT.items()}
    if c['mode'] not in ('auto','ip'):raise Problem('Ungültiger Verbindungsmodus.')
    if c['protocol'] not in ('eSCL','WSD'):raise Problem('Bitte eSCL oder WSD wählen.')
    for key in ('ip','bind'):
        if key=='ip' and c['mode']=='auto' and not c[key]:continue
        try:ip=ipaddress.ip_address(c[key])
        except ValueError:raise Problem('Ungültige IP-Adresse: '+key) from None
        if ip.version!=4:raise Problem('Hier bitte eine IPv4-Adresse verwenden.')
        if key=='ip' and (ip.is_unspecified or ip.is_multicast or ip.is_loopback):raise Problem('Bitte die IPv4-Adresse des Netzwerk-Scanners angeben.')
    for key in ('port','scanner_port'):
        try:c[key]=int(c[key])
        except ValueError:raise Problem('Port muss eine Zahl sein.') from None
        if not 1<=c[key]<=65535:raise Problem('Port muss zwischen 1 und 65535 liegen.')
    if c['port']==9877:raise Problem('Port 9877 gehört dem Server Manager.')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]*',c['path']) or '..' in c['path'].split('/'):raise Problem('Ungültiger Scanner-Endpunktpfad.')
    if not re.fullmatch(r'[A-Za-z0-9 _.:/-]{1,180}',c['device']):raise Problem('Ungültige SANE-Gerätekennung.')
    out=Path(c['outdir'])
    if not out.is_absolute() or '..' in out.parts or len(out.parts)<4 or out.parts[1] not in ('Serverspeicher','srv','home','mnt','media') or any(x in c['outdir'] for x in '\n\r"\\'):
        raise Problem('Installationspfad muss ein absoluter Pfad in einem erlaubten Datenbereich sein.')
    if any(p.is_symlink() for p in [out,*out.parents]):raise Problem('Ausgabeordner darf keine symbolischen Links enthalten.')
    if c['access'] not in ('keep','private','read','write'):raise Problem('Ungültige Ordnerrechte.')
    if c['access'] in ('read','write'):
        try:grp.getgrnam(c['access_group'])
        except KeyError:raise Problem('Bitte eine vorhandene Zugriffsgruppe wählen.') from None
    if c['access']!='keep' and out.exists() and any(x in os.listxattr(out) for x in ('system.posix_acl_access','system.posix_acl_default')):
        raise Problem('Der Ordner besitzt zusätzliche ACL-Rechte. Rechte beibehalten oder einen neuen Scan-Ordner wählen; ACLs werden nicht überschrieben.')
    if not re.fullmatch('[a-z_][a-z0-9_-]{0,31}',c['user']):raise Problem('Ungültiger Dienstbenutzer.')
    try:account=pwd.getpwnam(c['user'])
    except KeyError:
        if allow_create and c['user']=='scanner':return c
        raise Problem('Dienstbenutzer existiert nicht. Für das Standardkonto scanner bitte Scanner-API installieren / reparieren wählen; andere Benutzer vorher anlegen.') from None
    if account.pw_uid==0:raise Problem('Scanner-API darf nicht als root laufen.')
    return c

def device(c):return ('airscan:'+('e0' if c['protocol']=='eSCL' else 'w0')+':Server Manager Scanner') if c['mode']=='ip' else c['device']
def scanner_url(c):return 'http://'+c['ip']+':'+str(c['scanner_port'])+c['path']
def sane_config(c):return '[devices]\nServer Manager Scanner = '+scanner_url(c)+', '+c['protocol']+'\n[options]\ndiscovery = disable\n'
def api_host(c):return '127.0.0.1' if c['bind']=='0.0.0.0' else c['bind']
def read_api(c,path):
    with urlopen('http://'+api_host(c)+':'+str(c['port'])+path,timeout=4) as r:return json.loads(r.read(262144))
def service_state():
    r=subprocess.run(['systemctl','is-active','scanner-api.service'],capture_output=True,text=True,timeout=5)
    return r.stdout.strip() or 'unbekannt'
def missing_packages():
    result=[]
    for name in PACKAGES:
        r=subprocess.run(['dpkg-query','-W','-f=${Status}',name],capture_output=True,text=True,timeout=5)
        if r.returncode or r.stdout.strip()!='install ok installed':result.append(name)
    return result

def check(c):
    results=[]
    for title,func in [('API-Status',lambda:read_api(c,'/status')),('API-Konfiguration',lambda:read_api(c,'/'))]:
        try:results.append({'name':title,'ok':True,'message':json.dumps(func(),ensure_ascii=False)})
        except (OSError,ValueError) as exc:results.append({'name':title,'ok':False,'message':str(exc)[:400]})
    try:
        with socket.create_connection((c['ip'],c['scanner_port']),timeout=4):pass
        results.append(dict(name='Scanner-Netzwerk',ok=True,message=c['ip']+':'+str(c['scanner_port'])+' erreichbar'))
    except OSError as exc:results.append(dict(name='Scanner-Netzwerk',ok=False,message=str(exc)))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ)
            if c['mode']=='ip':
                Path(tmp,'dll.conf').write_text('airscan\n');Path(tmp,'airscan.conf').write_text(sane_config(c));env['SANE_CONFIG_DIR']=tmp
            output=run(['scanimage','-f','%d%n'],timeout=25,env=env)
            found=device(c) in output.splitlines()
            results.append(dict(name='SANE-Geräteerkennung',ok=found,message=output.strip() or 'Kein Scanner gefunden.'))
    except (OSError,Problem,subprocess.TimeoutExpired) as exc:results.append(dict(name='SANE-Geräteerkennung',ok=False,message=str(exc)[:500]))
    return results

@contextlib.contextmanager
def lock(blocking=True):
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(ROOT/'lock','a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:raise Problem("Ein Scanner-Auftrag läuft bereits.") from None
        yield

def job_path(key):
    if not re.fullmatch('[a-f0-9]{32}',key):raise Problem('Ungültiger Auftrag.')
    return ROOT/'jobs'/key

def job(key):
    value=json.loads((job_path(key)/'status.json').read_text())
    if value['state'] not in TERMINAL and time.time()-value['created']>30:
        r=subprocess.run(['systemctl','is-active','servermgr-scanner-'+key+'.service'],capture_output=True,text=True,timeout=5)
        if r.stdout.strip() not in ('active','activating','reloading'):value.update(state='interrupted',message='Auftrag unterbrochen. Sicherung und Dienstzustand prüfen.')
    return value

def active():
    if not (ROOT/'active.json').exists():return None
    value=job(json.loads((ROOT/'active.json').read_text())['id'])
    return value if value['state'] not in TERMINAL else None

def start(data,action,expected):
    if action not in ('install','apply'):raise Problem('Ungültige Aktion.')
    c=validate(data,allow_create=action=='install')
    with lock(blocking=False):
        if active():raise Problem('Ein Scanner-Auftrag läuft bereits.')
        if expected!=revision():raise Problem('Einstellungen wurden inzwischen geändert. Seite neu laden.')
        key=uuid.uuid4().hex;folder=job_path(key);folder.mkdir(parents=True,mode=0o700)
        atomic(folder/'request.json',dict(config=c,action=action,revision=expected))
        state=dict(id=key,state='queued',message='Auftrag wird gestartet.',created=time.time())
        atomic(folder/'status.json',state);atomic(ROOT/'active.json',{'id':key})
        try:run(['systemd-run','--quiet','--collect','--unit=servermgr-scanner-'+key,'--property=Type=exec','--property=UMask=0077','--property=RuntimeMaxSec=30m',*['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE','SERVER_MANAGER_DB','SERVER_MANAGER_PORT') if k in os.environ],'/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key])
        except (OSError,Problem,subprocess.TimeoutExpired):
            atomic(folder/'status.json',dict(state,state='failed',message='Auftrag konnte nicht gestartet werden.'))
            raise Problem('Auftrag konnte nicht gestartet werden.') from None
        return key

def apply(c,folder):
    """Back up managed files, preserve service account/data, restore on restart failure."""
    if API.exists() and hashlib.sha256(API.read_bytes()).hexdigest() not in (ORIGINAL,'1470faad46308e3ddbb07a1429eea65cdf67a5e6f3c2e21da8b2ab9feacfb773',hashlib.sha256(Path(__file__).with_name('scan_api.py').read_bytes()).hexdigest()):
        raise Problem('Scanner-API wurde außerhalb dieses Moduls geändert. Bestand zuerst prüfen; keine Dateien ersetzt.')
    if UNIT.exists():
        text=UNIT.read_text()
        if 'ExecStart=/usr/bin/python3 /opt/scanner-api/scan_api.py' not in text:raise Problem('Abweichende Scanner-Service-Definition; keine automatische Übernahme.')
    old=load();was_active=service_state()=='active'
    SESSION.mkdir(parents=True,exist_ok=True)
    if (SESSION/'session.json').exists():raise Problem('Aktive Scan-Session: zuerst in Home Assistant fertigstellen oder abbrechen.')
    with open(SESSION/'scan.lock','a') as scanlock:
        try:fcntl.flock(scanlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Problem('Scanner ist beschäftigt; Einstellungen später übernehmen.') from None
        if (SESSION/'session.json').exists():raise Problem('Eine Scan-Session wurde gerade gestartet.')
        if c['port']!=old['port'] or c['bind']!=old['bind'] or not was_active:
            with socket.socket() as sock:
                try:sock.bind((c['bind'],c['port']))
                except OSError:raise Problem('Gewählte API-Adresse ist nicht lokal verfügbar oder der Port ist belegt.') from None
        account=pwd.getpwnam(c['user']);out=Path(c['outdir'])
        if not out.exists():
            missing=[];parent=out.parent
            while not parent.exists():missing.append(parent);parent=parent.parent
            for parent in reversed(missing):
                parent.mkdir(mode=0o711);parent.chmod(0o711)
            out.mkdir(mode=0o775);os.chown(out,account.pw_uid,account.pw_gid)
        out_stat=out.stat()
        out_before=(out_stat.st_uid,out_stat.st_gid,stat.S_IMODE(out_stat.st_mode))
        owners=[(p,p.stat().st_uid,p.stat().st_gid) for p in (SESSION,SESSION/'scan.lock')]
        paths=[API,UNIT,DROPIN,ENV,SANE/'dll.conf',SANE/'airscan.conf',CONFIG]
        saved=[]
        backup=folder/'backup';backup.mkdir(mode=0o700)
        for i,path in enumerate(paths):
            if path.is_symlink():raise Problem('Verwaltete Datei ist ein symbolischer Link: '+str(path))
            dest=backup/str(i)
            if path.exists():shutil.copy2(path,dest)
            saved.append((path,dest if path.exists() else None))
        atomic(folder/'backup-files.json',[str(p) for p in paths])
        try:
            access=c.get('access','keep')
            group=grp.getgrgid(account.pw_gid).gr_name
            if access in ('read','write'):group=c['access_group']
            if access!='keep':
                if any(x in os.listxattr(out) for x in ('system.posix_acl_access','system.posix_acl_default')):raise Problem('Zielordner besitzt zusätzliche ACL-Rechte; keine automatische Änderung.')
                os.chown(out,account.pw_uid,grp.getgrnam(group).gr_gid)
                os.chmod(out,{'private':0o700,'read':0o2750,'write':0o2770}[access])
            try:run(['runuser','-u',c['user'],'-g',group,'--','/usr/bin/python3','-c','import os,sys;sys.exit(0 if os.access(sys.argv[1],os.W_OK|os.X_OK) else 1)',str(out)])
            except Problem:raise Problem('Dienstbenutzer '+c['user']+' kann den Scan-Ordner nicht betreten oder beschreiben. Auch die Zugriffsrechte aller übergeordneten Ordner prüfen: '+str(out)) from None
            run(['systemctl','stop','scanner-api.service']) if UNIT.exists() else None
            for p,_,_ in owners:os.chown(p,account.pw_uid,account.pw_gid)
            API.parent.mkdir(parents=True,exist_ok=True)
            os.chmod(API.parent,0o755)
            atomic(API,Path(__file__).with_name('scan_api.py').read_text(),0o644)
            if not UNIT.exists():atomic(UNIT,'[Unit]\nDescription=Network Scanner API\nAfter=network-online.target\nWants=network-online.target\n[Service]\nType=simple\nWorkingDirectory=/opt/scanner-api\nExecStart=/usr/bin/python3 /opt/scanner-api/scan_api.py\nRestart=on-failure\nRestartSec=5\nNoNewPrivileges=true\nPrivateTmp=true\n[Install]\nWantedBy=multi-user.target\n',0o644)
            # Group uses the account's primary group, including after a user change.
            atomic(DROPIN,'[Service]\nUser='+c['user']+'\nGroup='+group+'\nUMask='+('0022' if access=='keep' else '0007' if access=='write' else '0027' if access=='read' else '0077')+'\nEnvironmentFile='+str(ENV)+'\n',0o644)
            env={'SCANNER_DEVICE':device(c),'SCAN_OUTDIR':c['outdir'],'SCAN_SESSION_DIR':str(SESSION),'SCAN_BIND':c['bind'],'SCAN_PORT':str(c['port']),'SANE_CONFIG_DIR':str(SANE) if c['mode']=='ip' else '/etc/sane.d'}
            env['SCAN_FILE_MODE']={'keep':'0664','private':'0600','read':'0640','write':'0660'}[access]
            atomic(ENV,''.join(k+'="'+v+'"\n' for k,v in env.items()),0o600)
            SANE.mkdir(parents=True,exist_ok=True,mode=0o755)
            os.chmod(SANE.parent,0o755);os.chmod(SANE,0o755)
            atomic(SANE/'dll.conf','airscan\n',0o644);atomic(SANE/'airscan.conf',sane_config(c),0o644)
            run(['systemctl','daemon-reload']);run(['systemctl','restart','scanner-api.service'])
            for attempt in range(15):
                try:
                    info=read_api(c,'/')
                    if info.get('device')!=device(c) or info.get('outdir')!=c['outdir']:raise Problem('API meldet abweichende Einstellungen.')
                    break
                except OSError:
                    if attempt==14:raise
                    time.sleep(1)
            run(['systemctl','enable','scanner-api.service'])
            atomic(CONFIG,c)
        except Exception:
            os.chown(out,out_before[0],out_before[1]);os.chmod(out,out_before[2])
            for p,uid,gid in owners:os.chown(p,uid,gid)
            for path,source in saved:
                if source:shutil.copy2(source,path)
                else:path.unlink(missing_ok=True)
            run(['systemctl','daemon-reload'])
            if was_active:run(['systemctl','restart','scanner-api.service'])
            else:subprocess.run(['systemctl','stop','scanner-api.service'],capture_output=True,timeout=20)
            raise

def ensure_service_account(c):
    try:account=pwd.getpwnam(c['user'])
    except KeyError:
        if c['user']!='scanner':raise Problem('Dienstbenutzer existiert nicht.') from None
        run(['/usr/sbin/useradd','--system','--no-create-home','--home-dir','/nonexistent','--shell','/usr/sbin/nologin','scanner'])
        account=pwd.getpwnam('scanner')
    if account.pw_uid==0:raise Problem('Scanner-API darf nicht als root laufen.')
    return account


def worker(key):
    folder=job_path(key);state=json.loads((folder/'status.json').read_text());request=json.loads((folder/'request.json').read_text())
    try:
        state.update(state='running',message='Voraussetzungen und Scan-Session prüfen.');atomic(folder/'status.json',state)
        with lock():
            if revision()!=request['revision']:raise Problem('Konfiguration wurde inzwischen geändert.')
            missing=missing_packages()
            if missing:
                if request['action']!='install':raise Problem('Fehlende Pakete: '+', '.join(missing)+'. Bitte Installer verwenden.')
                state['message']='Fehlende Pakete installieren: '+', '.join(missing);atomic(folder/'status.json',state)
                run(['apt-get','update'],timeout=600)
                run(['apt-get','install','-y','--no-remove',*missing],timeout=1200,env=dict(os.environ,DEBIAN_FRONTEND='noninteractive'))
            if request['action']=='install':ensure_service_account(request['config'])
            apply(validate(request['config']),folder)
        state.update(state='completed',message='Scanner-API eingerichtet, Einstellungen übernommen und API geprüft. Vorhandene Scans bleiben erhalten.')
    except Exception as exc:state.update(state='failed',message=str(exc)[:1500])
    state['finished']=time.time();atomic(folder/'status.json',state)
    return 0 if state['state']=='completed' else 1

def get_blockers(ctx=None):
    reasons=[]
    if active():reasons.append('Scanner-API wird eingerichtet')
    if (SESSION/'session.json').exists():reasons.append('Scan-Session noch nicht abgeschlossen')
    return [dict(source='Scanner',type='scanner',title='Scanner aktiv',reason='; '.join(reasons),priority=90,url='/scanner')] if reasons else []

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit('Nur interner Worker-Aufruf.')
    raise SystemExit(worker(sys.argv[2]))
