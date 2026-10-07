#!/usr/bin/env python3
"""Portable, explicit fresh installer. --check never modifies the host."""
import argparse,getpass,json,os,platform,secrets,shutil,socket,subprocess,sys,tarfile,tempfile
from pathlib import Path
from urllib.request import urlopen

class InstallError(RuntimeError):pass

def run(args,timeout=1800):
    result=subprocess.run(args,timeout=timeout)
    if result.returncode:raise InstallError('Befehl fehlgeschlagen: '+args[0]+'. Kein automatisches Löschen von Daten.')

def exists(args):
    try:return subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False

def nextcloud_module():
    try:from . import nextcloud_setup
    except ImportError:import nextcloud_setup
    return nextcloud_setup

def kvm_module():
    try:from . import kvm_setup
    except ImportError:import kvm_setup
    return kvm_setup

def pihole_existing():
    """Read names and published ports only; never inspect container secrets."""
    import re
    found=[]
    try:
        result=subprocess.run(['docker','ps','-a','--format','{{json .}}'],capture_output=True,text=True,timeout=10)
        if result.returncode==0:
            for line in result.stdout.splitlines():
                row=json.loads(line)
                if not re.match(r'^(?:docker.io/)?pihole/pihole(?::|@|$)',row.get('Image','')):continue
                name=row['Names']
                ports=subprocess.run(['docker','inspect','--format','{{json .NetworkSettings.Ports}}',name],capture_output=True,text=True,timeout=10)
                mappings=json.loads(ports.stdout or '{}') if ports.returncode==0 else {}
                url=''
                for key,scheme in [('80/tcp','http'),('443/tcp','https')]:
                    for binding in (mappings or {}).get(key) or []:
                        port=int(binding['HostPort']);host=binding.get('HostIp','127.0.0.1')
                        if host in ('0.0.0.0','::',''):host='127.0.0.1'
                        elif ':' in host:host='['+host+']'
                        url=scheme+'://'+host+':'+str(port)+'/admin/';break
                    if url:break
                found.append(dict(kind='docker',container=name,web_url=url))
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
    if Path('/etc/pihole').is_dir() and exists(['systemctl','cat','pihole-FTL.service']):
        url=''
        try:
            import tomllib
            with open('/etc/pihole/pihole.toml','rb') as stream:config=tomllib.load(stream)
            for value in str(config.get('webserver',{}).get('port','')).split(','):
                match=re.search(r'(?:^|:)([0-9]+)([os]*)$',value.strip())
                if match:
                    url=('https' if 's' in match[2] else 'http')+'://127.0.0.1:'+match[1]+'/admin/';break
        except (OSError,ValueError):pass
        found.append(dict(kind='native',web_url=url))
    return found

def https_module():
    try:from . import openwebui_https
    except ImportError:import openwebui_https
    return openwebui_https

def docker_module():
    try:from . import docker_setup
    except ImportError:import docker_setup
    return docker_setup

def ai_checks(profile):
    issues=[]
    if shutil.which('ollama') or exists(['systemctl','cat','ollama.service']):issues.append('Vorhandenes Ollama erkannt. Komplettinstallation ersetzt es nicht; Variante „Nur Open WebUI“ wählen.')
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',11434))
        except OSError:issues.append('Ollama-Port 11434 ist belegt; vorhandene Installation verwenden.')
    if platform.machine() not in ('x86_64','aarch64','arm64'):issues.append('KI-Komplettinstallation unterstützt amd64 und arm64.')
    for volume in ('servermgr-open-webui-data','servermgr-open-webui-models'):
        if exists(['docker','volume','inspect',volume]):issues.append('Aufbewahrtes KI-Datenvolume vorhanden; keine automatische Neuverwendung: '+volume)
    try:
        docker=docker_module();state=docker.status()
        if state['action']=='diagnose':issues.append('Docker-Bestand nicht eindeutig; zuerst Docker unter Apps prüfen.')
        if state['action'] in ('install','compose'):docker.install_packages(state['packages'])
    except (ValueError,OSError,subprocess.SubprocessError) as exc:issues.append(str(exc))
    return issues

def prepare_ai():
    docker=docker_module();state=docker.status()
    if state['action']=='start':docker.execute('docker-start',sys.stdout);state=docker.status()
    if state['action'] in ('install','compose'):docker.execute('docker-install',sys.stdout)
    if not docker.status()['ready'] or not docker.status()['compose']:raise InstallError('Docker/Compose nicht einsatzbereit.')
    if not shutil.which('rsync'):
        env=dict(os.environ,DEBIAN_FRONTEND='noninteractive')
        for args in (['apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'],['apt-get','-o','DPkg::Lock::Timeout=60','--no-remove','--yes','install','rsync']):
            subprocess.run(args,env=env,stdin=subprocess.DEVNULL,check=True,timeout=1800)


def checks(profile):
    if profile['kind']=='kvm_setup':return kvm_module().checks(profile)
    if profile['kind']=='nextcloud_setup':return nextcloud_module().checks(profile)
    if profile.get('app_id')=='shares_mounts':return []
    issues=[];target=Path(profile['target'])
    if any(parent.is_symlink() for parent in target.parents):issues.append('Zielpfad enthält einen symbolischen Link.')
    if target.exists() or target.is_symlink():issues.append('Ziel existiert bereits: '+str(target)+'; Bestand wird nicht überschrieben.')
    if profile.get('existing') and (Path(profile['existing']).exists() or Path(profile['existing']).is_symlink()):issues.append('Bestehende Installation gefunden: '+profile['existing'])
    if profile.get('container') and exists(['docker','container','inspect',profile['container']]):issues.append('Container existiert bereits: '+profile['container'])
    if profile.get('service') and exists(['systemctl','cat',profile['service']]):issues.append('Systemdienst existiert bereits: '+profile['service'])
    if profile.get('port'):
        with socket.socket() as sock:
            try:sock.bind(('0.0.0.0',profile['port']))
            except OSError:issues.append('Port '+str(profile['port'])+' ist belegt.')
    if profile.get('app_id')=='pihole':
        if pihole_existing():issues.append('Vorhandenes Pi-hole erkannt. Die bestehende Installation wird nicht ersetzt; unter Apps verwalten öffnen.')
        for protocol,kind in (('TCP',socket.SOCK_STREAM),('UDP',socket.SOCK_DGRAM)):
            with socket.socket(socket.AF_INET,kind) as sock:
                try:sock.bind(('0.0.0.0',53))
                except OSError:issues.append('DNS-Port 53/'+protocol+' ist belegt. Bestehenden DNS-Dienst prüfen; er wird nicht automatisch deaktiviert.')
    if not profile.get('local_ai') and profile['kind'] in ('container','paperless','nextcloud','immich') and not exists(['docker','compose','version']):issues.append('Docker Engine mit Compose-Plugin wird benötigt; zuerst installieren.')
    if profile['kind']=='oscam_bundle' and profile.get('architecture')!=platform.machine():issues.append('OSCam-Binary passt nicht zur Zielarchitektur.')
    if profile.get('app_id')=='open_webui' and profile.get('local_ai'):issues+=ai_checks(profile)
    if profile.get('app_id')=='open_webui' and profile.get('https'):issues+=https_module().checks(profile)
    return issues

def write(path,text,mode=0o600):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,'x') as stream:stream.write(text)
    os.chmod(path,mode)

def compose(profile,bind):
    if profile.get('app_id')=='open_webui' and profile.get('https'):bind='127.0.0.1'
    app=profile['app_id'];kind=profile['kind'];port=f"{bind}:{profile['port']}:";password=secrets.token_hex(24)
    if kind=='container':
        service={'image':profile['image'],'container_name':profile['container'],'restart':'unless-stopped','ports':[port+str(profile['container_port'])],'volumes':['./data:'+profile['mount']]}
        if app=='pihole':
            service['ports'] += [bind+':53:53/tcp',bind+':53:53/udp']
            service['environment']={'FTLCONF_dns_listeningMode':'all','FTLCONF_webserver_api_password':password,'FTLCONF_webserver_port':'80'}
        if app=='open_webui':service.update(extra_hosts=['host.docker.internal:host-gateway'],environment={'OLLAMA_BASE_URL':'http://host.docker.internal:11434','WEBUI_SECRET_KEY':secrets.token_hex(32),'WEBUI_AUTH':'true'})
        if app=='open_webui' and profile.get('local_ai'):
            service.pop('extra_hosts',None)
            service['image']='ghcr.io/open-webui/open-webui:ollama'
            service['environment'].update(OLLAMA_BASE_URL='http://127.0.0.1:11434',OLLAMA_HOST='0.0.0.0:11434')
            service['network_mode']='bridge'
            service['ports'].append('127.0.0.1:11434:11434')
            service['volumes']=['webui-data:/app/backend/data','ollama-models:/root/.ollama']
            return {'services':{'app':service},'volumes':{'webui-data':{'name':'servermgr-open-webui-data'},'ollama-models':{'name':'servermgr-open-webui-models'}}}

        if app in ('plex','jellyfin'):
            service['volumes'] += ['./media:/media:ro', './transcode:/transcode' if app=='plex' else './cache:/cache']
        if app=='stirling':service['volumes']+=['./logs:/logs','./tessdata:/usr/share/tessdata','./customFiles:/customFiles','./pipeline:/pipeline']
        return {'services':{'app':service}}
    if kind=='paperless':
        return {'services':{
         'db':{'image':'postgres:16','restart':'unless-stopped','volumes':['./postgres:/var/lib/postgresql/data'],'environment':{'POSTGRES_DB':'paperless','POSTGRES_USER':'paperless','POSTGRES_PASSWORD':password},'healthcheck':{'test':['CMD-SHELL','pg_isready -U paperless'],'interval':'10s','retries':10}},
         'broker':{'image':'redis:7','restart':'unless-stopped','volumes':['./redis:/data']},
         'webserver':{'image':'ghcr.io/paperless-ngx/paperless-ngx:latest','container_name':profile['container'],'restart':'unless-stopped','ports':[port+'8000'],'depends_on':{'db':{'condition':'service_healthy'},'broker':{'condition':'service_started'}},'volumes':['./data:/usr/src/paperless/data','./media:/usr/src/paperless/media','./export:/usr/src/paperless/export','./consume:/usr/src/paperless/consume'],'environment':{'PAPERLESS_REDIS':'redis://broker:6379','PAPERLESS_DBHOST':'db','PAPERLESS_DBPASS':password,'PAPERLESS_SECRET_KEY':secrets.token_hex(32),'PAPERLESS_TIME_ZONE':'Europe/Berlin','PAPERLESS_OCR_LANGUAGE':'deu+eng'}}}}
    if kind=='nextcloud':
        return {'services':{
         'db':{'image':'mariadb:11','restart':'unless-stopped','volumes':['./database:/var/lib/mysql'],'environment':{'MARIADB_DATABASE':'nextcloud','MARIADB_USER':'nextcloud','MARIADB_PASSWORD':password,'MARIADB_RANDOM_ROOT_PASSWORD':'yes'}},
         'app':{'image':'nextcloud:stable-apache','container_name':profile['container'],'restart':'unless-stopped','ports':[port+'80'],'depends_on':['db'],'volumes':['./html:/var/www/html'],'environment':{'MYSQL_HOST':'db','MYSQL_DATABASE':'nextcloud','MYSQL_USER':'nextcloud','MYSQL_PASSWORD':password}}}}
    raise InstallError('Unbekannte Compose-Vorlage.')

def fetch(url):
    if not url.startswith('https://'):raise InstallError('Nur HTTPS-Quellen erlaubt.')
    with urlopen(url,timeout=45) as response:
        data=response.read(8*1024*1024+1)
        if len(data)>8*1024*1024:raise InstallError('Quelldatei zu groß.')
        return data.decode()

def unit(name,text):
    write(Path('/etc/systemd/system')/name,text,0o644)
    run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',name],120)

def install_shares(profile):
    if os.geteuid()!=0:raise InstallError('Installation benötigt root.')
    # Repair is repeatable, including after the old client-only installer.
    run(['apt-get','update'])
    run(['apt-get','install','-y','samba','samba-common-bin','smbclient','nfs-kernel-server','nfs-common','cifs-utils','acl','attr','passwd'])
    smb=Path('/etc/samba/smb.conf')
    if not smb.exists():
        write(smb,'[global]\n    server role = standalone server\n    security = user\n    map to guest = Never\n',0o644)
    exports=Path('/etc/exports')
    if not exports.exists():write(exports,'# NFS exports managed through Heimserver Manager.\n',0o644)
    run(['testparm','-s',str(smb)],60)
    run(['exportfs','-ra'],60)
    run(['systemctl','enable','--now','smbd.service','nfs-server.service'],120)
    run(['systemctl','is-active','--quiet','smbd.service','nfs-server.service'],30)
    print('SMB/NFS-Server und Clientwerkzeuge geprüft. Bestehende Konfigurationen erhalten. Benutzer und Freigaben unter Netzwerk → Freigaben anlegen.')

def install(profile,assets,bind,credentials=None):
    if profile.get('app_id')=='shares_mounts':return install_shares(profile)
    if profile['kind']=='kvm_setup':
        try:return kvm_module().install(profile)
        except kvm_module().SetupError as exc:raise InstallError(str(exc)) from None
    if profile['kind']=='nextcloud_setup':
        try:return nextcloud_module().install(profile,assets,credentials)
        except nextcloud_module().SetupError as exc:raise InstallError(str(exc)) from None
    if profile.get('app_id')=='pihole':
        import ipaddress
        address=ipaddress.ip_address(bind)
        if address.version!=4 or address.is_unspecified or address.is_multicast or not (address.is_private or address.is_loopback):
            raise InstallError('Pi-hole benötigt eine konkrete lokale LAN-IPv4-Adresse oder 127.0.0.1; keine öffentliche Adresse oder 0.0.0.0.')
    problems=checks(profile)
    if problems:raise InstallError('\n'.join(problems))
    if os.geteuid()!=0:raise InstallError('Installation benötigt root; Prüfung ohne sudo möglich.')
    if profile.get('app_id')=='open_webui' and profile.get('local_ai'):prepare_ai()
    target=Path(profile['target']);target.mkdir(parents=True,exist_ok=False,mode=0o700)
    kind=profile['kind']
    if kind in ('container','paperless','nextcloud'):
        spec=compose(profile,bind);file=target/'compose.json';write(file,json.dumps(spec,indent=2))
        if profile.get('app_id')=='pihole':
            write(target/'admin-password.txt',spec['services']['app']['environment']['FTLCONF_webserver_api_password']+'\n')
        run(['docker','compose','-f',str(file),'config','--quiet'],60)
        run(['docker','compose','-f',str(file),'pull'])
        run(['docker','compose','-f',str(file),'up','-d','--wait','--wait-timeout','180'],240)
        if profile.get('app_id')=='open_webui' and profile.get('local_ai'):
            run(['docker','exec',profile['container'],'ollama','pull','qwen3:0.6b'])
            run(['docker','exec',profile['container'],'ollama','show','qwen3:0.6b'],60)
            print('Lokale KI eingerichtet: Open WebUI, Ollama und Qwen3 0.6B. Erstes Administratorkonto in Open WebUI anlegen. Weitere Modelle unter Qwen-Modelle. CPU-Betrieb; GPU-Treiber bleiben separat.')
        if profile.get('app_id')=='pihole':
            print('Pi-hole: Admin-Passwort liegt geschützt in '+str(target/'admin-password.txt')+'. Mit sudo cat anzeigen. Router-DNS und DHCP wurden nicht geändert. Einzelne Clients zuerst auf diese Server-IP als DNS einstellen.')
        if kind=='paperless':print('Admin einmalig anlegen: docker exec -it '+profile['container']+' python manage.py createsuperuser')
    elif kind=='immich':
        # Matching release assets; config is not executed as a shell script.
        release=json.loads(fetch('https://api.github.com/repos/immich-app/immich/releases/latest'))['tag_name']
        if not release.startswith('v') or '/' in release:raise InstallError('Ungültige Release-Antwort.')
        root='https://github.com/immich-app/immich/releases/download/'+release+'/'
        spec=fetch(root+'docker-compose.yml');env=fetch(root+'example.env')
        settings={'UPLOAD_LOCATION':'./library','DB_DATA_LOCATION':'./postgres','IMMICH_VERSION':release,'DB_PASSWORD':secrets.token_hex(24)}
        lines=[line for line in env.splitlines() if line.split('=',1)[0] not in settings]
        write(target/'.env','\n'.join(lines)+'\n'+'\n'.join(k+'='+v for k,v in settings.items())+'\n')
        # Official binding is replaced explicitly to honor the selected interface.
        if "'2283:2283'" in spec:spec=spec.replace("'2283:2283'",json.dumps(bind+':2283:2283'))
        elif '"2283:2283"' in spec:spec=spec.replace('"2283:2283"',json.dumps(bind+':2283:2283'))
        else:raise InstallError('Offizielle Portvorlage hat sich geändert; keine Dienste gestartet.')
        file=target/'docker-compose.yml';write(file,spec)
        run(['docker','compose','--project-directory',str(target),'-f',str(file),'config','--quiet'],60)
        run(['docker','compose','--project-directory',str(target),'-f',str(file),'pull'])
        run(['docker','compose','--project-directory',str(target),'-f',str(file),'up','-d','--wait','--wait-timeout','180'],240)
    elif kind=='packages':
        run(['apt-get','update']);run(['apt-get','install','-y',*profile['packages']])
        if profile.get('service'):run(['systemctl','enable','--now',profile['service']],120)
    elif kind=='comfyui':
        run(['apt-get','update']);run(['apt-get','install','-y','git','python3-venv','python3-dev','build-essential','libgl1','libglib2.0-0'])
        run(['git','clone','--depth','1','https://github.com/Comfy-Org/ComfyUI.git',str(target)])
        run(['python3','-m','venv',str(target/'venv')]);python=str(target/'venv/bin/python')
        run([python,'-m','pip','install','torch','torchvision','torchaudio','--index-url','https://download.pytorch.org/whl/cpu'])
        run([python,'-m','pip','install','-r',str(target/'requirements.txt')])
        if not exists(['id','comfyui']):run(['useradd','--system','--home-dir',str(target),'--shell','/usr/sbin/nologin','comfyui'])
        run(['chown','-R','comfyui:comfyui',str(target)]);os.chmod(target,0o750)
        unit('comfyui.service',f'[Unit]\nDescription=ComfyUI\nAfter=network.target\n[Service]\nUser=comfyui\nWorkingDirectory={target}\nExecStart={python} main.py --cpu --listen {bind} --port 8188\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n')
    elif kind=='oscam_bundle':
        binary=assets/'oscam'
        if not binary.is_file():raise InstallError('OSCam-Binary fehlt im Installerpaket.')
        run(['apt-get','update']);run(['apt-get','install','-y','libusb-1.0-0','libssl3t64','libpcsclite1'])
        # Reader and user credentials are deliberately not copied from the source host.
        config=Path('/var/lib/oscam/config')
        if config.exists():raise InstallError('OSCam-Konfiguration existiert bereits.')
        config.mkdir(parents=True,mode=0o700)
        shutil.copyfile(binary,'/usr/local/bin/oscam');os.chmod('/usr/local/bin/oscam',0o755)
        write(config/'oscam.conf','[webif]\nhttpport = 8888\nhttpuser = admin\nhttppwd = '+secrets.token_hex(24)+'\nhttpallowed = 127.0.0.1\n')
        unit('oscam.service','[Unit]\nDescription=OSCam\nAfter=network.target\n[Service]\nExecStart=/usr/local/bin/oscam -c /var/lib/oscam/config\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n')
        print('Webzugriff zunächst nur lokal. Passwort und erlaubtes Netz in /var/lib/oscam/config/oscam.conf einstellen; Reader separat konfigurieren.')
    elif kind=='server_bundle':
        archive=assets/'server-manager.tar'
        with tarfile.open(archive) as tar:
            for item in tar.getmembers():
                name=Path(item.name)
                if name.is_absolute() or '..' in name.parts or not (item.isfile() or item.isdir()):raise InstallError('Unsicherer Archivinhalt.')
            tar.extractall(target,filter='data')
        run(['apt-get','update']);run(['apt-get','install','-y','python3-venv','iproute2','dnsutils','sqlite3','acl','smbclient','rsync','curl','sudo'])
        run(['python3','-m','venv',str(target/'venv')]);python=str(target/'venv/bin/python')
        run([python,'-m','pip','install','flask','requests','psutil','PyYAML','Pillow','paramiko'])
        secret=Path('/etc/server-manager-install.env');write(secret,'SERVER_MANAGER_SECRET='+secrets.token_hex(32)+'\n')
        unit('server-manager.service',f'[Unit]\nDescription=Server Manager\nAfter=network.target\n[Service]\nWorkingDirectory={target}\nEnvironmentFile={secret}\nExecStart={python} {target}/app.py\nRestart=on-failure\n[Install]\nWantedBy=multi-user.target\n')
    else:raise InstallError('Unbekannter Installertyp.')
    if kind=='server_bundle':print('Server Manager: Erstanmeldung mit Benutzer ADMIN und Passwort ADMIN. Unter Einstellungen → Zugang ändern.')
    if profile.get('app_id')=='open_webui' and profile.get('https'):https_module().install(profile)
    write(target/'.server-manager-install.json',json.dumps(profile,indent=2))
    print('Installation abgeschlossen. WebUI und Ersteinrichtung der App prüfen.')

def main():
    parser=argparse.ArgumentParser(description='App-Installer: Prüfung zuerst, Neuinstallation nur ausdrücklich.')
    parser.add_argument('--install',action='store_true');parser.add_argument('--check',action='store_true');parser.add_argument('--bind',default='127.0.0.1')
    args=parser.parse_args();import ipaddress
    try:
        if ipaddress.ip_address(args.bind).version!=4:raise InstallError('Für diesen Installer bitte eine IPv4-Bind-Adresse verwenden.')
        assets=Path(__file__).resolve().parent;profile=json.loads((assets/'profile.json').read_text())
        print(profile['label']+' · '+profile['kind']+' · '+profile['target'])
        if not args.install:
            problems=checks(profile)
            for problem in problems:print(problem)
            print('Keine Änderungen. Installation mit --install; LAN-Adresse mit --bind festlegen.')
            return 1 if problems else 0
        install(profile,assets,args.bind);return 0
    except (InstallError,OSError,ValueError,subprocess.TimeoutExpired) as exc:print('Abgebrochen: '+str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
