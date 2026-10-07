"""Bounded, read-only discovery; never execute discovered PHP configuration."""
import json,re,subprocess,shutil,hashlib
from pathlib import Path
from server_settings import get
ROOTS=('/var/www','/srv/www','/srv/http','/opt/nextcloud','/usr/share/nextcloud','/snap/nextcloud/current/htdocs')
CONFIGS=('/etc/apache2/sites-enabled','/etc/apache2/sites-available','/etc/nginx/sites-enabled','/etc/nginx/sites-available','/etc/nginx/conf.d')
def discover():
 candidates={str(Path(get('nextcloud_root'))):'Eingestellter Pfad'};warnings=[]
 for base in ROOTS:
  p=Path(base);candidates[str(p)]='Typischer Installationsort'
  try:
   for child in list(p.iterdir())[:100]:
    if child.is_dir():
     candidates[str(child)]='Typischer Installationsort'
     for sub in ('nextcloud','html/nextcloud','html'):candidates[str(child/sub)]='Typischer Installationsort'
  except (OSError,ValueError):pass
 for directory in CONFIGS:
  try:files=list(Path(directory).iterdir())[:100]
  except OSError:continue
  for file in files:
   try:
    if not file.is_file() or file.stat().st_size>1024*1024:continue
    text=file.read_text(errors='replace')
    for line in text.splitlines():
     if line.lstrip().startswith('#'):continue
     match=re.match(r'\s*(?:DocumentRoot|Alias\s+\S+|root|alias)\s+["\x27]?(/[^;"\x27\s]+)',line,re.I)
     if match:
      p=match[1];candidates[p]='Webserver-Konfiguration';candidates[p+'/nextcloud']='Webserver-Konfiguration'
   except OSError:warnings.append('Eine Webserver-Konfiguration war nicht lesbar.')
 found=[];seen=set()
 for raw,origin in candidates.items():
  try:
   p=Path(raw).resolve()
   if str(p) in seen or not all((p/f).is_file() for f in ('occ','version.php','index.php')):continue
   if 'OC_Version' not in (p/'version.php').read_text(errors='replace')[:65536]:continue
   seen.add(str(p));found.append(dict(kind='native',path=str(p),label=str(p),origin=origin))
  except OSError:continue
 if shutil.which('docker'):
  try:
   ids=subprocess.run(['docker','ps','-aq'],capture_output=True,text=True,timeout=10,check=True).stdout.split()
   if ids:
    objects=json.loads(subprocess.run(['docker','inspect',*ids[:100]],capture_output=True,text=True,timeout=15,check=True).stdout)
    for obj in objects:
     image=obj.get('Config',{}).get('Image','');name=obj.get('Name','').lstrip('/')
     if 'nextcloud' not in image.lower() and 'nextcloud' not in name.lower():continue
     labels=obj.get('Config',{}).get('Labels') or {};mounts=[m.get('Source','') for m in obj.get('Mounts',[]) if m.get('Destination') in ('/var/www/html','/config')]
     found.append(dict(kind='docker',label=name,image=image,path=labels.get('com.docker.compose.project.working_dir') or (mounts[0] if mounts else ''),origin='Docker-Container (auch gestoppte)',running=bool(obj.get('State',{}).get('Running'))))
  except (OSError,ValueError,subprocess.SubprocessError):warnings.append('Docker-Bestand konnte nicht geprüft werden; Erkennung unvollständig.')
 for item in found:item['id']=hashlib.sha256((item['kind']+item['label']).encode()).hexdigest()[:24]
 return found,sorted(set(warnings))

APACHE_ENABLED=Path('/etc/apache2/sites-enabled')

def websites(item):
 """Associate enabled Apache vhosts with a detected native document root.

 Docker/reverse-proxy associations require additional evidence and are not guessed.
 Only public certificate metadata is read; PHP and private keys are never opened.
 """
 if item.get('kind')!='native':return []
 result=[]
 for file in sorted(APACHE_ENABLED.glob('*.conf'))[:100]:
  try:
   if file.stat().st_size>1024*1024:continue
   text='\n'.join(line for line in file.read_text(errors='replace').splitlines() if not line.lstrip().startswith('#'))
   for block in re.findall(r'<VirtualHost\b[^>]*>(.*?)</VirtualHost>',text,re.I|re.S):
    roots=re.findall(r'^\s*DocumentRoot\s+["\x27]?([^\s"\x27]+)',block,re.I|re.M)
    aliases=re.findall(r'^\s*Alias\s+([^\s]+)\s+["\x27]?([^\s"\x27]+)',block,re.I|re.M)
    roots.extend(root for route,root in aliases)
    if not any(Path(root).resolve()==Path(item['path']).resolve() for root in roots):continue
    domains=[]
    for value in re.findall(r'^\s*Server(?:Name|Alias)\s+([^\n]+)',block,re.I|re.M):domains.extend(value.split())
    tls=bool(re.search(r'^\s*SSLEngine\s+on\b',block,re.I|re.M));certificate='Kein TLS in dieser Website konfiguriert'
    if tls:
     certificate='TLS konfiguriert; Zertifikat nicht geprüft'
     cert=re.search(r'^\s*SSLCertificateFile\s+["\x27]?([^\s"\x27]+)',block,re.I|re.M)
     if cert:
      response=subprocess.run(['openssl','x509','-in',cert[1],'-noout','-enddate'],capture_output=True,text=True,timeout=5)
      if response.returncode==0 and response.stdout.startswith('notAfter='):certificate='Lokales Zertifikat · Ablauf: '+response.stdout.strip().split('=',1)[1]
      else:certificate='TLS konfiguriert; lokale Zertifikatsdatei nicht lesbar oder ungültig'
    result.append(dict(domains=domains,site=file.name,tls=tls,certificate=certificate,routes=[route for route,root in aliases if Path(root).resolve()==Path(item['path']).resolve()]))
  except (OSError,ValueError,subprocess.SubprocessError):continue
 return result
