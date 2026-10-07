"""Standalone fresh Nextcloud provisioning for Debian 13; no existing data replacement."""
import getpass,hashlib,json,os,re,secrets,shutil,socket,subprocess,tarfile,tempfile,time
from pathlib import Path
from urllib.request import urlopen

class SetupError(ValueError):pass

def command(args,timeout=120,input=None,cwd=None):
    p=subprocess.run(args,input=input,capture_output=True,text=True,cwd=cwd,timeout=timeout,env={**os.environ,'DEBIAN_FRONTEND':'noninteractive','LC_ALL':'C'})
    if p.returncode:raise SetupError('Schritt fehlgeschlagen: '+args[0]+'. Konfiguration und Dienstprotokoll prüfen; vorhandene Daten bleiben erhalten.')
    return p.stdout

def path(value):
    p=Path(value)
    if not re.fullmatch(r'/(?:srv|opt|var/www|mnt|media|Serverspeicher)/[A-Za-z0-9_./-]+',str(p)) or '..' in p.parts or any(x.is_symlink() for x in (p,*p.parents)):raise SetupError('Installationspfad muss ein absoluter Pfad in einem erlaubten Datenbereich sein.')
    return str(p)

def validate(data):
    mode=data.get('mode','native')
    if mode not in ('native','docker'):raise SetupError('Nativ oder Docker auswählen.')
    access=data.get('access','public')
    if access not in ('public','local'):raise SetupError('Zugangsart ungültig.')
    domain=str(data.get('domain','')).lower().strip().rstrip('.')
    if len(domain)>253 or (access=='public' and '.' not in domain) or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in domain.split('.')):raise SetupError('Gültigen vollständigen Domainnamen angeben.')
    import ipaddress
    try:ipaddress.ip_address(domain)
    except ValueError:pass
    else:
        if access=='public':raise SetupError('Domain statt IP-Adresse angeben.')
    email=str(data.get('email','')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',email):raise SetupError('Gültige E-Mail-Adresse angeben.')
    admin=str(data.get('admin','')).strip()
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}',admin):raise SetupError('Gültigen Admin-Benutzernamen angeben.')
    root=path(str(data.get('target','')));storage=path(str(data.get('data_root','')))
    if Path(root).is_relative_to(Path(storage)) or Path(storage).is_relative_to(Path(root)):raise SetupError('Programm- und Datenordner müssen getrennt liegen.')
    try:port=int(data.get('port',8080))
    except ValueError:raise SetupError('Ungültiger Docker-Port.')
    if not 1024<=port<=65535:raise SetupError('Docker-Port: 1024–65535.')
    if access=='public' and data.get('terms')!='1':raise SetupError('Let’s-Encrypt-Bedingungen bestätigen.')
    bind='';web_port=80
    if access=='local':
        try:
            addr=ipaddress.IPv4Address(data.get('bind',''));web_port=int(data.get('web_port',8081))
        except ValueError:raise SetupError('Private lokale IPv4-Adresse und gültigen Webport angeben.')
        if not any(addr in ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):raise SetupError('Lokalen Zugang an eine private LAN-/WireGuard-Adresse binden.')
        if not 1024<=web_port<=65535 or web_port==port:raise SetupError('Lokaler Webport: 1024–65535, verschieden vom Docker-Port.')
        bind=str(addr)
    return dict(mode=mode,domain=domain,email=email,admin=admin,target=root,data_root=storage,port=port,terms=data.get('terms',''),access=access,bind=bind,web_port=web_port)

def base_url(c):
    return ('http://'+c['domain']+':'+str(c['web_port'])) if c.get('access')=='local' else 'https://'+c['domain']

def password(value):
    if not isinstance(value,str) or len(value)<12 or len(value)>256 or any(ord(c)<32 for c in value):raise SetupError('Admin-Passwort: 12–256 Zeichen ohne Steuerzeichen.')
    return value

def checks(profile):
    c=validate(profile['setup']);issues=[]
    if Path('/etc/server-manager/server.pending.json').exists():issues.append('Vorgemerkte Server-Einstellungen zuerst übernehmen oder verwerfen.')
    system=Path('/etc/os-release').read_text()
    if not re.search(r'^ID=\"?debian\"?$',system,re.M) or not re.search(r'^VERSION_ID=\"?13\"?$',system,re.M):issues.append('Komplettinstallation derzeit für Debian 13 freigegeben.')
    for folder in ([c['target'],c['data_root']]+([profile.get('existing','/var/www/html/nextcloud')] if c['mode']=='native' else [])):
        if Path(folder).exists():issues.append('Vorhandener Ordner wird nicht überschrieben: '+folder)
    if c['mode']=='docker':
        for native_path in (profile.get('existing','/var/www/html/nextcloud'),profile.get('native_data','/srv/nextcloud-data')):
            native=Path(native_path)
            if native.exists() and any(Path(p).is_relative_to(native) or native.is_relative_to(Path(p)) for p in (c['target'],c['data_root'])):
                issues.append('Docker-Ordner müssen vom nativen Nextcloud-Bestand getrennt sein: '+str(native))
    suffix='-docker' if c['mode']=='docker' else ''
    for filename in (Path('/etc/apache2/sites-available/server-manager-nextcloud'+suffix+'.conf'),Path('/etc/letsencrypt/live')/c['domain'],Path('/etc/systemd/system/servermgr-nextcloud'+suffix+'-cron.timer')):
        if filename.exists():issues.append('Vorhandene Einrichtung: '+str(filename))
    if shutil.which('docker'):
        r=subprocess.run(['docker','ps','-a','--format','{{.Names}} {{.Image}}'],capture_output=True,text=True,timeout=20)
        if r.returncode:issues.append('Docker-Bestand kann nicht geprüft werden.')
        elif 'nextcloud' in r.stdout.lower():issues.append('Bestehender Nextcloud-Container erkannt.')
    apache_active=subprocess.run(['systemctl','is-active','apache2'],capture_output=True,text=True,timeout=10).stdout.strip()=='active'
    if c.get('access','public')=='local':
        with socket.socket() as sock:
            try:sock.bind((c['bind'],c['web_port']))
            except OSError:issues.append('Lokale Bind-Adresse nicht vorhanden oder Webport belegt.')
    if not apache_active:
        for port in (80,443):
            with socket.socket() as s:
                try:s.bind(('0.0.0.0',port))
                except OSError:issues.append('Webport '+str(port)+' wird bereits außerhalb des aktiven Apache verwendet.')
    if c['mode']=='docker':
        with socket.socket() as s:
            try:s.bind(('127.0.0.1',c['port']))
            except OSError:issues.append('Docker-Port bereits belegt.')
    if shutil.which('mariadb') and c['mode']=='native':
        try:
            found=command(['mariadb','--batch','--skip-column-names'],input="SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='nextcloud'; SELECT User FROM mysql.user WHERE User='servermgr_nc';")
            if found.strip():issues.append('Nextcloud-Datenbank oder Datenbankkonto bereits vorhanden.')
        except (SetupError,OSError,subprocess.SubprocessError):issues.append('Bestehende MariaDB kann nicht sicher geprüft werden.')
    # Existing vhosts for this name must never be overwritten by certbot.
    apache=Path('/etc/apache2')
    for f in (apache/'sites-enabled').glob('*.conf'):
        if c['domain'] in f.read_text(errors='replace'):issues.append('Domain bereits in Apache eingerichtet: '+f.name)
    return issues

def write(file,text,mode=0o600):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    with file.open('x') as out:out.write(text)
    file.chmod(mode)

def packages(names):
    command(['apt-get','update'],timeout=600)
    command(['apt-get','-o','DPkg::Lock::Timeout=120','-o','Dpkg::Options::=--force-confdef','-o','Dpkg::Options::=--force-confold','install','-y','--no-remove',*names],timeout=1800)

def occ(c,args,input=None):
    if c['mode']=='docker':return command(['docker','exec','--user','www-data','servermgr-nextcloud','php','occ',*args],timeout=300,input=input)
    return command(['runuser','-u','www-data','--','php','-d','apc.enable_cli=1',str(Path(c['target'])/'occ'),*args],timeout=300,input=input)

def docker_spec(c,dbpass,adminpass):
    # Secrets are files, never environment literals or command-line arguments.
    appenv={'MYSQL_HOST':'db','MYSQL_DATABASE':'nextcloud','MYSQL_USER':'nextcloud','MYSQL_PASSWORD_FILE':'/run/secrets/db_password','NEXTCLOUD_ADMIN_USER':c['admin'],'NEXTCLOUD_ADMIN_PASSWORD_FILE':'/run/secrets/admin_password','NEXTCLOUD_TRUSTED_DOMAINS':c['domain'],'OVERWRITEPROTOCOL':'http' if c.get('access')=='local' else 'https','OVERWRITEHOST':c['domain']+(':'+str(c['web_port']) if c.get('access')=='local' else ''),'OVERWRITECLIURL':base_url(c),'REDIS_HOST':'redis'}
    return {'services':{'db':{'image':'mariadb:11.4','restart':'unless-stopped','volumes':['./database:/var/lib/mysql'],'environment':{'MARIADB_DATABASE':'nextcloud','MARIADB_USER':'nextcloud','MARIADB_PASSWORD_FILE':'/run/secrets/db_password','MARIADB_ROOT_PASSWORD_FILE':'/run/secrets/root_password'},'secrets':['db_password','root_password'],'healthcheck':{'test':['CMD','healthcheck.sh','--connect','--innodb_initialized'],'interval':'10s','timeout':'5s','retries':30}},'redis':{'image':'redis:7-alpine','restart':'unless-stopped'},'app':{'image':'nextcloud:stable-apache','container_name':'servermgr-nextcloud','restart':'unless-stopped','ports':['127.0.0.1:'+str(c['port'])+':80'],'volumes':['./html:/var/www/html',c['data_root']+':/var/www/html/data'],'environment':appenv,'secrets':['db_password','admin_password'],'depends_on':{'db':{'condition':'service_healthy'},'redis':{'condition':'service_started'}}}},'secrets':{name:{'file':'./secrets/'+name} for name in ('db_password','admin_password','root_password')}}

def native(c,dbpass,adminpass):
    packages(['mariadb-server','libapache2-mod-php','php-cli','php-mysql','php-curl','php-gd','php-mbstring','php-intl','php-xml','php-zip','php-bcmath','php-gmp','php-imagick','php-apcu','php-redis','redis-server','bzip2'])
    command(['systemctl','enable','--now','mariadb','redis-server'])
    sql="CREATE DATABASE nextcloud CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci; CREATE USER 'servermgr_nc'@'localhost' IDENTIFIED BY '"+dbpass+"'; GRANT ALL PRIVILEGES ON nextcloud.* TO 'servermgr_nc'@'localhost';"
    command(['mariadb'],input=sql)
    root=Path(c['target'])
    with tempfile.TemporaryDirectory(prefix='nextcloud-source-') as temp:
        archive=Path(temp)/'nextcloud.tar.bz2';h=hashlib.sha256()
        with urlopen('https://download.nextcloud.com/server/releases/latest.tar.bz2',timeout=90) as remote,archive.open('wb') as out:
            total=0
            while True:
                chunk=remote.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>2*1024**3:raise SetupError('Nextcloud-Archiv unerwartet groß.')
                h.update(chunk);out.write(chunk)
        with urlopen('https://download.nextcloud.com/server/releases/latest.tar.bz2.sha256',timeout=30) as remote:expected=remote.read(2048).decode().split()[0]
        if h.hexdigest()!=expected:raise SetupError('Prüfsumme des Nextcloud-Archivs stimmt nicht. Erneut starten nach Prüfung des Paketstands.')
        with tarfile.open(archive) as tar:
            members=tar.getmembers()
            if any(not (m.isfile() or m.isdir()) or Path(m.name).is_absolute() or '..' in Path(m.name).parts or Path(m.name).parts[0]!='nextcloud' for m in members):raise SetupError('Unsicherer Archivinhalt.')
            tar.extractall(temp,filter='data')
        shutil.copytree(Path(temp)/'nextcloud',root,dirs_exist_ok=True)
    command(['chown','-R','www-data:www-data',str(root),c['data_root']])
    command(['chmod','755',str(root)]);command(['chmod','750',c['data_root']])
    # Supply secrets via stdin to the trusted OCC process, not argv or a log.
    args=['occ','maintenance:install','--database=mysql','--database-host=localhost','--database-name=nextcloud','--database-user=servermgr_nc','--database-pass='+dbpass,'--admin-user='+c['admin'],'--admin-pass='+adminpass,'--admin-email='+c['email'],'--data-dir='+c['data_root'],'--no-interaction']
    php='$argv=json_decode(stream_get_contents(STDIN),true); $_SERVER["argv"]=$argv; require "occ";'
    command(['runuser','-u','www-data','--','php','-d','apc.enable_cli=1','-r',php],input=json.dumps(args),cwd=str(root),timeout=600)
    occ(c,['config:system:set','memcache.local','--value=\\OC\\Memcache\\APCu'])
    occ(c,['config:system:set','memcache.locking','--value=\\OC\\Memcache\\Redis'])
    occ(c,['config:system:set','redis','host','--value=127.0.0.1']);occ(c,['config:system:set','redis','port','--value=6379','--type=integer'])

def install(profile,assets,credentials=None):
    c=validate(profile['setup']);adminpass=password((credentials or {}).get('password') or getpass.getpass('Nextcloud Admin-Passwort: '))
    issues=checks(profile)
    if issues:raise SetupError('; '.join(issues))
    if os.geteuid()!=0:raise SetupError('Installation benötigt root.')
    print('Nextcloud-Neuinstallation: '+c['mode']+' · '+c['domain'],flush=True)
    previous=os.umask(0o022)
    try:
        root=Path(c['target']);root.mkdir(parents=True,exist_ok=False);Path(c['data_root']).mkdir(parents=True,exist_ok=False)
        packages(['apache2','ca-certificates','curl','rsync']+(['certbot','python3-certbot-apache'] if c['access']=='public' else []))
        dbpass=secrets.token_hex(32)
        if c['mode']=='native':native(c,dbpass,adminpass)
        else:
            if not shutil.which('docker'):packages(['docker.io','docker-compose'])
            try:command(['docker','compose','version'])
            except SetupError:raise SetupError('Docker Compose v2 fehlt. Passendes Compose-Plugin zur vorhandenen Docker-Installation ergänzen.')
            command(['systemctl','enable','--now','docker'])
            root.chmod(0o700);(root/'secrets').mkdir(mode=0o700)
            for name,value in [('db_password',dbpass),('admin_password',adminpass),('root_password',secrets.token_hex(32))]:write(root/'secrets'/name,value)
            write(root/'compose.json',json.dumps(docker_spec(c,dbpass,adminpass),indent=2))
            command(['docker','compose','-f',str(root/'compose.json'),'up','-d','--wait','--wait-timeout','600'],timeout=1800)
            for attempt in range(60):
                try:
                    state=json.loads(occ(c,['status','--output=json']))
                    if state.get('installed'):break
                except (SetupError,ValueError):pass
                time.sleep(3)
            else:raise SetupError('Nextcloud-Ersteinrichtung nicht rechtzeitig fertig.')
        if c['mode']=='docker':
            gateway=command(['docker','inspect','--format','{{range .NetworkSettings.Networks}}{{.Gateway}} {{end}}','servermgr-nextcloud']).split()[0]
            import ipaddress
            gateway=str(ipaddress.ip_address(gateway))
            occ(c,['config:system:set','trusted_proxies','0','--value='+gateway])
        occ(c,['config:system:set','trusted_domains','0','--value='+c['domain']])
        occ(c,['config:system:set','overwrite.cli.url','--value='+base_url(c)])
        occ(c,['config:system:set','default_phone_region','--value=DE'])
        occ(c,['user:setting',c['admin'],'settings','email',c['email']])
        occ(c,['background:cron'])
        suffix='-docker' if c['mode']=='docker' else ''
        host=c['domain'];site=Path('/etc/apache2/sites-available/server-manager-nextcloud'+suffix+'.conf')
        endpoint=c['bind']+':'+str(c['web_port']) if c['access']=='local' else '*:80'
        text=('Listen '+endpoint+'\n' if c['access']=='local' else '')+'<VirtualHost '+endpoint+'>\n ServerName '+host+'\n'
        if c['mode']=='native':
            text+=' DocumentRoot '+str(root)+'\n <Directory '+str(root)+'>\n Require all granted\n AllowOverride All\n Options FollowSymLinks\n </Directory>\n'
            command(['a2enmod','rewrite','headers','env','dir','mime','setenvif'])
        else:
            text+=' ProxyPreserveHost On\n RequestHeader set X-Forwarded-Proto "'+('http' if c['access']=='local' else 'https')+'"\n ProxyPass / http://127.0.0.1:'+str(c['port'])+'/\n ProxyPassReverse / http://127.0.0.1:'+str(c['port'])+'/\n'
            command(['a2enmod','proxy','proxy_http','headers','rewrite'])
        if c['mode']=='native' and c['access']=='local':
            text='<Directory '+str(root)+'>\n Require all denied\n</Directory>\n'+text
        write(site,text+'</VirtualHost>\n',0o644)
        try:
            command(['a2ensite',site.name]);command(['apache2ctl','configtest']);command(['systemctl','enable','--now','apache2']);command(['systemctl','reload','apache2'])
        except Exception:
            subprocess.run(['a2dissite',site.name],capture_output=True);raise
        if c['access']=='public':
            command(['certbot','--apache','--non-interactive','--agree-tos','--redirect','--email',c['email'],'--cert-name',host,'-d',host],timeout=600)
            command(['systemctl','enable','--now','certbot.timer'])
        cron=(['/usr/bin/docker','exec','--user','www-data','servermgr-nextcloud','php','-f','/var/www/html/cron.php'] if c['mode']=='docker' else ['/usr/bin/php','-d','apc.enable_cli=1','-f',str(root/'cron.php')])
        write('/etc/systemd/system/servermgr-nextcloud'+suffix+'-cron.service','[Unit]\nDescription=Nextcloud background jobs\n[Service]\nType=oneshot\n'+('User=www-data\n' if c['mode']=='native' else '')+'ExecStart='+' '.join(cron)+'\n',0o644)
        write('/etc/systemd/system/servermgr-nextcloud'+suffix+'-cron.timer','[Unit]\nDescription=Nextcloud background schedule\n[Timer]\nOnBootSec=5min\nOnUnitActiveSec=5min\n[Install]\nWantedBy=timers.target\n',0o644)
        command(['systemctl','daemon-reload']);command(['systemctl','enable','--now','servermgr-nextcloud'+suffix+'-cron.timer'])
        state=json.loads(occ(c,['status','--output=json']))
        if not state.get('installed') or state.get('maintenance') or state.get('needsDbUpgrade'):raise SetupError('Nextcloud meldet keinen einsatzbereiten Zustand.')
        with urlopen(base_url(c)+'/status.php',timeout=30) as response:health=json.load(response)
        if not health.get('installed') or health.get('maintenance'):raise SetupError('Web-Abschlussprüfung fehlgeschlagen.')
        write(root/'.server-manager-install.json',json.dumps(profile,indent=2))
        print('Nextcloud eingerichtet: '+base_url(c)+' · Admin: '+c['admin']+' · Webzugang und OCC geprüft.',flush=True)
    finally:os.umask(previous)
