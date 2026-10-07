"""Opt-in native Pi-hole v6 install using a reviewed upstream installer."""
import hashlib,ipaddress,json,os,shutil,socket,subprocess,urllib.request
from pathlib import Path
from . import install_runtime as runtime,install_catalog as c
CONFIG=Path('/etc/pihole')
URL='https://raw.githubusercontent.com/pi-hole/pi-hole/f47b8ede5a8e38f9c703202d324a074dbdba4ca9/automated%20install/basic-install.sh'

def validate(plan):
 if runtime.pihole_existing() or CONFIG.exists() or Path('/etc/.pihole').exists() or shutil.which('pihole'):raise ValueError('Pi-hole oder Installationsreste vorhanden. Keine Neuinstallation und kein Wechsel der Installationsart.')
 if not Path('/etc/debian_version').is_file():raise ValueError('Dieser Installer ist für Debian/Ubuntu vorgesehen.')
 ip=ipaddress.IPv4Address(plan['bind']);up=ipaddress.IPv4Address(plan['upstream']);port=int(plan['port'])
 if ip.is_unspecified or ip.is_loopback or ip.is_multicast or not ip.is_private:raise ValueError('Eine feste LAN-IPv4 dieses Servers wählen.')
 if up.is_unspecified or up.is_loopback or up.is_multicast or up==ip:raise ValueError('Gültigen externen oder lokalen Upstream-DNS angeben, nicht Pi-hole selbst.')
 if not 1024<=port<=65535:raise ValueError('Webport zwischen 1024 und 65535 wählen.')
 with socket.socket() as sock:
  try:sock.bind((str(ip),0))
  except OSError:raise ValueError('LAN-Adresse gehört nicht zum Server.') from None
 # Native DNS may bind wildcard sockets: do not stop a pre-existing DNS daemon.
 for address,p,kind in [('0.0.0.0',53,socket.SOCK_STREAM),('0.0.0.0',53,socket.SOCK_DGRAM),(str(ip),port,socket.SOCK_STREAM)]:
  with socket.socket(socket.AF_INET,kind) as sock:
   try:sock.bind((address,p))
   except OSError:raise ValueError('Benötigter Port belegt: '+str(p)+'. Bestehenden Dienst zuerst prüfen.') from None
 return dict(bind=str(ip),port=port,upstream=str(up))

def execute(plan,credentials,folder):
 plan=validate(plan)
 from .pihole_network import validate_password
 password=validate_password(credentials.get('password',''))
 if not password:raise ValueError('Adminpasswort ist erforderlich.')
 print('Offiziellen Pi-hole-Installer laden; vorhandene Installation wird nicht überschrieben.',flush=True)
 with urllib.request.urlopen(URL,timeout=60) as response:data=response.read(2*1024*1024)
 if not data.startswith(b'#!/') or len(data)>=2*1024*1024:raise ValueError('Installerdownload ungültig.')
 script=folder/'pihole-basic-install.sh';script.write_bytes(data);os.chmod(script,0o600)
 print('Installer-SHA256: '+hashlib.sha256(data).hexdigest(),flush=True)
 CONFIG.mkdir(mode=0o755)
 # Seed v6 config for unattended mode. Web access stays disabled until password is set.
 config='[dns]\nupstreams = ['+json.dumps(plan['upstream'])+']\nlisteningMode = "LOCAL"\n[webserver]\nport = ""\n'
 path=CONFIG/'pihole.toml';path.write_text(config);os.chmod(path,0o600)
 result=subprocess.run(['bash',str(script),'--unattended'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=1800,env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'})
 if result.returncode:raise ValueError('Offizieller Installer fehlgeschlagen. Native Teilinstallation bleibt zur Diagnose erhalten; keine automatische Neuinstallation. Pi-hole-Installationsprotokoll auf dem Server prüfen.')
 def run(args,input=None):
  r=subprocess.run(args,input=input,capture_output=True,text=True,timeout=90)
  if r.returncode:raise ValueError('Pi-hole-Ersteinrichtung fehlgeschlagen; Dienst und geschützte Konfiguration prüfen.')
 run(['pihole','setpassword'],password+'\n'+password+'\n')
 run(['pihole-FTL','--config','webserver.port',f"{plan['bind']}:{plan['port']}"])
 run(['systemctl','enable','--now','pihole-FTL.service']);run(['systemctl','restart','pihole-FTL.service'])
 import time
 url=f"http://{plan['bind']}:{plan['port']}/admin/"
 for attempt in range(15):
  try:
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=3) as response:
    if response.status==200:break
  except OSError:
   if attempt==14:raise ValueError('Installation durchgeführt, Webzugriff aber nicht bestätigt. Dienst prüfen.')
   time.sleep(1)
 saved=c.read();saved.setdefault('web',{})['pihole']=url;c.write(saved)
 print('Native Pi-hole-Installation abgeschlossen: '+url+'. Eigenes Adminpasswort verwenden. Blocklisten und DNS in Pi-hole prüfen; Router und Client-DNS wurden nicht geändert.',flush=True)
