"""Native Pi-hole v6: change one IPv4 HTTP listener, retain DNS and other listeners."""
import hashlib,ipaddress,json,os,re,shutil,socket,subprocess,time,tomllib,urllib.request
from pathlib import Path
from . import install_catalog as c
CONFIG=Path('/etc/pihole/pihole.toml')

def current():
 if not CONFIG.is_file() or CONFIG.resolve()!=CONFIG or not shutil.which('pihole-FTL'):raise ValueError('Native Pi-hole-v6-Konfiguration nicht vorhanden.')
 raw=CONFIG.read_bytes();data=tomllib.loads(raw.decode());ports=data.get('webserver',{}).get('port','')
 entries=ports.split(',');chosen=None
 for i,entry in enumerate(entries):
  m=re.fullmatch(r'(?:(\d+\.\d+\.\d+\.\d+):)?(\d+)(o?)',entry.strip())
  if m:chosen=(i,m.group(1) or '0.0.0.0',int(m.group(2)));break
 if chosen is None:raise ValueError('Kein IPv4-HTTP-Port erkannt. Bestehende HTTPS-Konfiguration in Pi-hole verwalten.')
 return raw,ports,chosen

def prepare(bind,port):
 ip=ipaddress.ip_address(bind);port=int(port)
 if ip.version!=4 or ip.is_unspecified or ip.is_multicast or not (ip.is_private or ip.is_loopback):raise ValueError('Konkrete lokale IPv4-Adresse wählen.')
 if not 1<=port<=65535:raise ValueError('Ungültiger Webport.')
 raw,ports,(index,oldip,oldport)=current()
 with socket.socket() as probe:
  try:probe.bind((str(ip),0))
  except OSError:raise ValueError('IP-Adresse gehört nicht zu diesem Server.') from None
 if not (oldport==port and oldip in ('0.0.0.0',str(ip))):
  with socket.socket() as probe:
   try:probe.bind((str(ip),port))
   except OSError:raise ValueError('Webport bereits belegt.') from None
 entries=ports.split(',');entries[index]=f'{ip}:{port}'
 return dict(mode='native',bind=str(ip),port=port,digest=hashlib.sha256(raw).hexdigest(),old_ports=ports,new_ports=','.join(entries))

def execute(plan,credentials=None):
 from .pihole_network import validate_password
 password=validate_password((credentials or {}).get('password',''))
 if prepare(plan['bind'],plan['port'])!=plan:raise ValueError('Native Konfiguration verändert. Erneut prüfen.')
 raw,_,_=current();stat=CONFIG.stat()
 backup=CONFIG.parent/('pihole.toml.before-manager-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex())
 with backup.open('xb') as f:os.chmod(backup,0o600);f.write(raw)
 def command(args,input=None):
  result=subprocess.run(args,input=input,text=True,capture_output=True,timeout=90)
  if result.returncode:raise ValueError('Native Pi-hole-Umstellung fehlgeschlagen; geschützte Konfiguration prüfen.')
 try:
  command(['pihole-FTL','--config','webserver.port',plan['new_ports']])
  if password:command(['pihole','setpassword'],password+'\n'+password+'\n')
  command(['systemctl','restart','pihole-FTL.service'])
  url=f"http://{plan['bind']}:{plan['port']}/admin/"
  for attempt in range(15):
   try:
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=3) as response:
     if response.status==200:break
   except OSError:
    if attempt==14:raise ValueError('Weboberfläche nach Umstellung nicht erreichbar.')
    time.sleep(1)
 except Exception:
  from .pihole_network import write
  write(CONFIG,raw);os.chown(CONFIG,stat.st_uid,stat.st_gid);os.chmod(CONFIG,stat.st_mode & 0o777)
  try:command(['systemctl','restart','pihole-FTL.service'])
  except Exception:raise ValueError('Alte Konfiguration zurückgesichert; Dienststart fehlgeschlagen. Dienst prüfen.') from None
  raise ValueError('Umstellung fehlgeschlagen; bisherige Konfiguration wiederhergestellt.') from None
 saved=c.read();saved.setdefault('web',{})['pihole']=url;c.write(saved)
 print('Native Pi-hole-Webadresse aktualisiert: '+url+'. DNS und weitere Weblistener unverändert. Rücksicherung: '+str(backup),flush=True)
