"""Add HTTPS to a manager-created local Nextcloud, preserving its local vhost."""
import json,hashlib,re,shutil,time,subprocess
from pathlib import Path
from . import nextcloud_setup as s,install_catalog as catalog

def plan(data):
 from modules.web_security.engine import hostname
 key=data.get('app_id','nextcloud')
 if key not in ('nextcloud','nextcloud_docker'):raise ValueError('Ungültige Nextcloud-Auswahl.')
 profile=catalog.recipe(key);c=s.validate(profile.get('setup',{}))
 if c['access']!='local':raise ValueError('Diese Funktion benötigt eine vom Manager eingerichtete lokale Installation.')
 marker=Path(c['target'])/'.server-manager-install.json'
 if not marker.is_file():raise ValueError('Bestätigte lokale Installation fehlt.')
 domain=hostname(data.get('domain',''))
 import ipaddress
 try:ipaddress.ip_address(domain)
 except ValueError:pass
 else:raise ValueError('Für HTTPS einen vollständigen Domainnamen angeben.')
 email=data.get('email','').strip()
 if not re.fullmatch(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}',email):raise ValueError('Gültige E-Mail angeben.')
 if data.get('terms')!='1':raise ValueError('Let’s-Encrypt-Bedingungen bestätigen.')
 site=Path('/etc/apache2/sites-available/server-manager-nextcloud-public-'+key+'.conf')
 if site.exists() or site.with_name(site.stem+'-le-ssl.conf').exists() or (Path('/etc/letsencrypt/live')/domain).exists():raise ValueError('Öffentliche Website oder Zertifikat bereits vorhanden; unter Web & Sicherheit verwalten.')
 for file in Path('/etc/apache2/sites-enabled').glob('*.conf'):
  if domain in file.read_text():raise ValueError('Domain bereits in Apache verwendet.')
 config=Path(c['target'])/('html/config/config.php' if c['mode']=='docker' else 'config/config.php')
 snapshot={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (marker,config)}
 snapshot['profile']=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
 if c['mode']=='docker':
  p=Path(c['target'])/'compose.json';snapshot[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
 return dict(action='nextcloud_https',data=dict(app_id=key,domain=domain,email=email,terms='1'),snapshot=snapshot,steps=['Domain '+domain+' zusätzlich für Nextcloud einrichten','Konfiguration sichern; lokale Adresse und lokalen Webzugang beibehalten','Öffentliche Apache-Website und Let’s-Encrypt-Zertifikat einrichten; DNS sowie eingehende Ports 80/443 müssen vorbereitet sein','Docker-App wird bei Docker-Installation kurz neu erstellt; Datenbank und Daten bleiben erhalten','Erreichbarkeit prüfen; automatische Zertifikatserneuerung aktivieren. Bei Fehler Konfigurationskopien im Auftragsordner für Rücksicherung prüfen.'])

def execute(p,folder):
 profile=catalog.recipe(p['data']['app_id']);c=s.validate(profile['setup']);domain=p['data']['domain'];root=Path(c['target'])
 for index,name in enumerate(p['snapshot']):
  if name=='profile':continue
  destination=folder/('before-'+str(index)+'-'+Path(name).name)
  shutil.copy2(name,destination);destination.chmod(0o600)
 s.packages(['certbot','python3-certbot-apache'])
 # A dedicated public vhost forwards to the existing local endpoint.
 site=Path('/etc/apache2/sites-available/server-manager-nextcloud-public-'+p['data']['app_id']+'.conf')
 target='http://127.0.0.1:'+str(c['port'])+'/' if c['mode']=='docker' else None
 text='<VirtualHost *:80>\n ServerName '+domain+'\n'
 if target:
  text+=' ProxyPreserveHost On\n ProxyPass / '+target+'\n ProxyPassReverse / '+target+'\n'
  s.command(['a2enmod','proxy','proxy_http','headers'])
 else:text+=' DocumentRoot '+str(root)+'\n <Directory '+str(root)+'>\n Require all granted\n AllowOverride All\n Options FollowSymLinks\n </Directory>\n'
 s.write(site,text+'</VirtualHost>\n',0o644)
 try:
  s.command(['a2ensite',site.name]);s.command(['apache2ctl','configtest']);s.command(['systemctl','reload','apache2'])
  s.command(['certbot','--apache','--non-interactive','--agree-tos','--redirect','--email',p['data']['email'],'--cert-name',domain,'-d',domain],timeout=600)
 except Exception:
  for name in (site.name,site.stem+'-le-ssl.conf'):
   subprocess.run(['a2dissite',name],capture_output=True,timeout=30)
  s.command(['apache2ctl','configtest']);s.command(['systemctl','reload','apache2']);raise
 if c['mode']=='docker':
  file=root/'compose.json';spec=json.loads(file.read_text());env=spec['services']['app']['environment']
  for name in ('OVERWRITEPROTOCOL','OVERWRITEHOST'):env.pop(name,None)
  env.pop('NEXTCLOUD_TRUSTED_DOMAINS',None);env['OVERWRITECLIURL']='https://'+domain
  file.write_text(json.dumps(spec,indent=2));file.chmod(0o600)
  for key in ('overwriteprotocol','overwritehost'):s.occ(c,['config:system:delete',key])
  s.command(['docker','compose','-f',str(file),'up','-d','--no-deps','app'],timeout=300)
  # Forwarded protocol is set only in the generated TLS vhost; local HTTP stays HTTP.
  ssl=site.with_name(site.stem+'-le-ssl.conf')
  if not ssl.is_file():raise ValueError('TLS-Website fehlt; Protokoll prüfen.')
  text=ssl.read_text().replace('</VirtualHost>',' RequestHeader set X-Forwarded-Proto "https"\n</VirtualHost>');ssl.write_text(text)
  s.command(['apache2ctl','configtest']);s.command(['systemctl','reload','apache2'])
 for attempt in range(30):
  try:
   state=json.loads(s.occ(c,['status','--output=json']))
   if state.get('installed') and not state.get('maintenance') and not state.get('needsDbUpgrade'):break
  except (s.SetupError,ValueError):pass
  time.sleep(2)
 else:raise ValueError('Nextcloud nach Umstellung nicht bereit; Auftragsprotokoll prüfen.')
 trusted=json.loads(s.occ(c,['config:list','system']))['system']['trusted_domains']
 if isinstance(trusted,dict):indices=[int(k) for k in trusted];values=list(trusted.values())
 elif isinstance(trusted,list):indices=list(range(len(trusted)));values=trusted
 else:raise ValueError('Trusted-Domains-Format nicht eindeutig.')
 if domain not in values:s.occ(c,['config:system:set','trusted_domains',str(max(indices,default=-1)+1),'--value='+domain])
 s.occ(c,['config:system:set','overwrite.cli.url','--value=https://'+domain])
 s.command(['systemctl','enable','--now','certbot.timer'])
 from urllib.request import urlopen
 with urlopen('https://'+domain+'/status.php',timeout=30) as response:health=json.load(response)
 if not health.get('installed') or health.get('maintenance'):raise ValueError('Nextcloud-HTTPS-Prüfung fehlgeschlagen.')
 saved=catalog.read();saved.setdefault('web',{})[p['data']['app_id']]='https://'+domain;catalog.write(saved)
 return {'message':'Domain und HTTPS eingerichtet. Lokaler Zugang bleibt bestehen.','url':'https://'+domain}
