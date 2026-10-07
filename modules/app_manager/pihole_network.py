"""Change published ports only for the manager's running Pi-hole Compose app."""
import hashlib,ipaddress,json,os,re,socket,subprocess,tempfile,time,urllib.request
from pathlib import Path
from . import install_catalog as c

def command(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=240)
 if r.returncode:raise ValueError('Docker-Prüfung oder Umstellung fehlgeschlagen. Keine Konfigurationsinhalte werden protokolliert.')
 return r.stdout.strip()

def current():
 profile=c.recipe('pihole');path=Path(profile['target'])/'compose.json'
 if not path.is_file() or path.resolve()!=path:raise ValueError('Automatische Umstellung nur für die vom Manager angelegte Docker-Installation. Native oder fremde Installationen separat konfigurieren.')
 raw=path.read_bytes();data=json.loads(raw);services=data.get('services',{})
 if set(services)!={'app'}:raise ValueError('Abweichende Compose-Struktur; keine automatische Änderung.')
 app=services['app']
 if not re.match(r'^(?:docker.io/)?pihole/pihole(?::|@|$)',app.get('image','')) or app.get('network_mode'):raise ValueError('Nicht unterstützte Pi-hole-Konfiguration.')
 name=app.get('container_name','')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name):raise ValueError('Containername nicht eindeutig.')
 config=command(['docker','inspect','--format','{{index .Config.Labels "com.docker.compose.project.config_files"}}',name])
 if config!=str(path):raise ValueError('Container gehört nicht zu dieser Compose-Datei.')
 if command(['docker','inspect','--format','{{.State.Running}}',name])!='true':raise ValueError('Pi-hole muss für diese Umstellung bereits laufen.')
 parsed=[]
 for port in app.get('ports',[]):
  m=re.fullmatch(r'(\d+\.\d+\.\d+\.\d+):(\d+):(\d+)(?:/(tcp|udp))?',port) if isinstance(port,str) else None
  if not m:raise ValueError('Abweichende Portzuordnung; keine automatische Änderung.')
  ip,host,inside,proto=m.groups();parsed.append((ip,int(host),int(inside),proto or 'tcp'))
 if len(parsed)!=3 or {(x[2],x[3]) for x in parsed}!={(80,'tcp'),(53,'tcp'),(53,'udp')}:raise ValueError('Erwartete Web-/DNS-Ports fehlen oder zusätzliche Ports vorhanden.')
 web=next(x for x in parsed if x[2]==80)
 return path,raw,data,parsed,web

def prepare(bind,port):
 if not (Path(c.recipe('pihole')['target'])/'compose.json').exists():
  from . import pihole_native_network as native
  return native.prepare(bind,port)
 ip=ipaddress.ip_address(bind)
 if ip.version!=4 or ip.is_unspecified or ip.is_multicast or ip.is_reserved or not (ip.is_private or ip.is_loopback):raise ValueError('Konkrete lokale LAN-IPv4 oder 127.0.0.1 wählen.')
 port=int(port)
 if not 1024<=port<=65535:raise ValueError('Webport zwischen 1024 und 65535 wählen.')
 path,raw,data,old,web=current()
 new=[(str(ip),port,80,'tcp'),(str(ip),53,53,'tcp'),(str(ip),53,53,'udp')]
 with socket.socket() as probe:
  try:probe.bind((str(ip),0))
  except OSError:raise ValueError('Die Adresse ist diesem Server nicht zugeordnet.') from None
 for addr,host,inside,proto in new:
  if (addr,host,inside,proto) in old:continue
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM if proto=='udp' else socket.SOCK_STREAM) as probe:
   try:probe.bind((addr,host))
   except OSError:raise ValueError('Port bereits belegt: '+addr+':'+str(host)+'/'+proto) from None
 return dict(bind=str(ip),port=port,path=str(path),digest=hashlib.sha256(raw).hexdigest(),old_ports=[list(x) for x in old])

def write(path,data):
 fd,tmp=tempfile.mkstemp(dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:os.fchmod(f.fileno(),0o600);f.write(data)
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def validate_password(password):
 if password and (len(password)<12 or len(password)>128 or any(ord(x)<32 for x in password) or '$' in password):raise ValueError('Passwort: 12–128 Zeichen, keine Steuerzeichen oder Dollarzeichen.')
 return password

def execute(plan,credentials=None):
 if plan.get('mode')=='native':
  from . import pihole_native_network as native
  return native.execute(plan,credentials)
 password=validate_password((credentials or {}).get('password',''))
 fresh=prepare(plan['bind'],plan['port'])
 if fresh!=plan:raise ValueError('Konfiguration geändert. Netzwerkumstellung erneut prüfen.')
 path,raw,data,old,web=current()
 backup=path.parent/('compose.before-network-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex()+'.json')
 with backup.open('xb') as f:os.chmod(backup,0o600);f.write(raw)
 data['services']['app']['ports']=[f"{plan['bind']}:{plan['port']}:80",f"{plan['bind']}:53:53/tcp",f"{plan['bind']}:53:53/udp"]
 env=data['services']['app'].setdefault('environment',{})
 if not isinstance(env,dict):raise ValueError('Abweichende Konfiguration; keine automatische Änderung.')
 env['FTLCONF_webserver_port']='80'
 if password:env['FTLCONF_webserver_api_password']=password
 args=['docker','compose','-f',str(path)]
 def up():command(args+['up','-d','--no-deps','--pull','never','--no-build','--wait','--wait-timeout','90','app'])
 try:
  write(path,json.dumps(data,indent=2).encode());command(args+['config','--quiet']);up()
  url=f"http://{plan['bind']}:{plan['port']}/admin/"
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=15) as response:
   if response.status!=200:raise ValueError('Pi-hole-Weboberfläche antwortet nicht erfolgreich.')
 except Exception:
  write(path,raw)
  try:up()
  except Exception:raise ValueError('Umstellung fehlgeschlagen; alte Datei zurückgesichert, Containerstart der alten Konfiguration fehlgeschlagen. App-Protokoll und Docker prüfen.') from None
  raise ValueError('Umstellung fehlgeschlagen. Bisherige Konfiguration wiederhergestellt.') from None
 if password:write(path.parent/'admin-password.txt',(password+'\n').encode())
 saved=c.read();saved.setdefault('web',{})['pihole']=url;c.write(saved)
 print('Pi-hole-Netzwerk umgestellt. Webadresse: '+url+'; DNS: '+plan['bind']+':53. Konfigurationssicherung: '+str(backup),flush=True)
