"""Password-only changes; preserve all published ports and network settings."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from . import install_catalog as c,pihole_network as network

def prepare():
 path=Path(c.recipe('pihole')['target'])/'compose.json'
 if path.exists():
  path,raw,data,ports,web=network.current();mode='docker'
  if not isinstance(data['services']['app'].get('environment',{}),dict):raise ValueError('Abweichende Docker-Konfiguration.')
 else:
  from . import pihole_native_network as native
  path=native.CONFIG
  if not path.is_file() or path.resolve()!=path:raise ValueError('Native Pi-hole-v6-Konfiguration fehlt.')
  raw=path.read_bytes();mode='native'
 return {'mode':mode,'path':str(path),'digest':hashlib.sha256(raw).hexdigest()}

def execute(plan,credentials):
 password=network.validate_password(credentials.get('password',''))
 if not password:raise ValueError('Neues Passwort erforderlich.')
 if prepare()!=plan:raise ValueError('Pi-hole-Konfiguration geändert. Passwortänderung erneut starten.')
 path=Path(plan['path']);raw=path.read_bytes();stat=path.stat()
 backup=path.parent/(path.name+'.before-password-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex())
 with backup.open('xb') as f:os.chmod(backup,0o600);f.write(raw)
 def run(args,input=None):
  result=subprocess.run(args,input=input,text=True,capture_output=True,timeout=180)
  if result.returncode:raise ValueError('Pi-hole-Passwortänderung fehlgeschlagen.')
 def restart():
  if plan['mode']=='native':run(['systemctl','restart','pihole-FTL.service'])
  else:run(['docker','compose','-f',str(path),'up','-d','--no-deps','--pull','never','--no-build','--wait','--wait-timeout','90','app'])
 try:
  if plan['mode']=='native':run(['pihole','setpassword'],password+'\n'+password+'\n')
  else:
   data=json.loads(raw);data['services']['app'].setdefault('environment',{})['FTLCONF_webserver_api_password']=password
   network.write(path,json.dumps(data,indent=2).encode());run(['docker','compose','-f',str(path),'config','--quiet'])
  restart()
 except Exception:
  network.write(path,raw);os.chown(path,stat.st_uid,stat.st_gid);os.chmod(path,stat.st_mode & 0o777)
  try:restart()
  except Exception:raise ValueError('Alte Konfiguration zurückgesichert; Dienststart fehlgeschlagen. Pi-hole prüfen.') from None
  raise ValueError('Passwortänderung fehlgeschlagen; bisherige Konfiguration wiederhergestellt.') from None
 if plan['mode']=='docker':network.write(path.parent/'admin-password.txt',(password+'\n').encode())
 print('Adminpasswort geändert. Netzwerkadressen, Ports und DNS-Einstellungen unverändert. In Pi-hole neu anmelden.',flush=True)
