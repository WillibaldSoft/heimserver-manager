"""Private HTTPS for fresh Open WebUI installs; never expose the HTTP backend."""
import argparse,ipaddress,json,os,re,secrets,shutil,socket,ssl,subprocess,tempfile
from pathlib import Path
APACHE=Path('/etc/apache2')
UNITS=Path('/etc/systemd/system')
SITE='server-manager-open-webui.conf'
UNIT='server-manager-open-webui-tls'
def run(args):subprocess.run(args,check=True,timeout=300,stdin=subprocess.DEVNULL)
def values(profile):
 host=str(profile.get('https_host') or socket.gethostname()).lower().rstrip('.')
 if len(host)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',x) for x in host.split('.')):raise ValueError('Ungültiger HTTPS-Hostname.')
 port=int(profile.get('https_port',3443))
 if not 1024<=port<=65535 or port in (int(profile['port']),11434):raise ValueError('HTTPS benötigt einen eigenen Port zwischen 1024 und 65535.')
 ip=str(profile.get('https_ip') or '').strip()
 if ip:
  addr=ipaddress.ip_address(ip)
  if addr.version!=4 or not addr.is_private or addr.is_unspecified or addr.is_multicast:raise ValueError('Zusätzliche HTTPS-IP muss eine konkrete private IPv4-Adresse sein.')
 return host,port,ip
def checks(profile):
 issues=[]
 try:
  host,port,ip=values(profile)
  with socket.socket() as sock:sock.bind(('0.0.0.0',port))
 except (ValueError,OSError) as exc:issues.append('HTTPS: '+str(exc))
 for path in (APACHE/'sites-available'/SITE,APACHE/'sites-enabled'/SITE,UNITS/(UNIT+'.service'),UNITS/(UNIT+'.timer')):
  if path.exists() or path.is_symlink():issues.append('Vorhandene WebUI-HTTPS-Einrichtung wird nicht überschrieben: '+str(path))
 return issues

def write(path,text,mode=0o600):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=path.parent)
 try:
  with os.fdopen(fd,'w') as out:out.write(text)
  os.chmod(tmp,mode);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def certificate(profile,force=False):
 host,port,ip=values(profile);tls=Path(profile['target'])/'https';tls.mkdir(mode=0o700,exist_ok=True)
 # Reuse the Manager CA if available, without changing it.
 manager=Path(os.environ.get('SERVER_MANAGER_CONFIG','/etc/server-manager'))/'manager-tls'
 issuer=tls/'issuer.json'
 if issuer.exists():
  ca=Path(json.loads(issuer.read_text())['ca']);key=ca.with_name('root-ca.key')
  if not ca.exists() or not key.exists():raise ValueError('Bisherige Zertifizierungsstelle fehlt; keine automatische CA-Rotation.')
 else:
  ca,key=manager/'root-ca.crt',manager/'root-ca.key'
  if ca.exists()!=key.exists():raise ValueError('Manager-Stammzertifikat unvollständig; keine automatische Neuerstellung.')
  if not ca.exists():
   ca,key=tls/'root-ca.crt',tls/'root-ca.key'
   if ca.exists()!=key.exists():raise ValueError('WebUI-Stammzertifikat unvollständig.')
   if not ca.exists():
    run(['openssl','req','-x509','-newkey','rsa:3072','-nodes','-days','3650','-sha256','-subj','/CN=Heimserver Local AI CA','-addext','basicConstraints=critical,CA:TRUE,pathlen:0','-addext','keyUsage=critical,keyCertSign,cRLSign','-keyout',str(key),'-out',str(ca)])
    key.chmod(0o600)
  write(issuer,json.dumps({'ca':str(ca)}))
 run(['openssl','x509','-checkend',str(366*86400),'-noout','-in',str(ca)])
 cert,private=tls/'server.crt',tls/'server.key'
 if cert.exists() and private.exists() and not force:
  valid=subprocess.run(['openssl','x509','-checkend',str(30*86400),'-noout','-in',str(cert)],capture_output=True).returncode==0
  checks=[['openssl','verify','-CAfile',str(ca),'-verify_hostname',host,str(cert)]]
  if ip:checks.append(['openssl','verify','-CAfile',str(ca),'-verify_ip',ip,str(cert)])
  valid=valid and all(subprocess.run(args,capture_output=True).returncode==0 for args in checks)
  if valid:return cert,private
 with tempfile.TemporaryDirectory(dir=tls) as folder:
  d=Path(folder);ext=d/'extensions.cnf'
  ext.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:'+host+(',IP:'+ip if ip else '')+'\n')
  run(['openssl','req','-new','-newkey','rsa:2048','-nodes','-subj','/CN='+host,'-keyout',str(d/'key'),'-out',str(d/'csr')])
  run(['openssl','x509','-req','-in',str(d/'csr'),'-CA',str(ca),'-CAkey',str(key),'-set_serial','0x'+secrets.token_hex(16),'-days','365','-sha256','-extfile',str(ext),'-out',str(d/'cert')])
  run(['openssl','verify','-CAfile',str(ca),'-verify_hostname',host,str(d/'cert')])
  os.chmod(d/'key',0o600);os.replace(d/'key',private);os.replace(d/'cert',cert)
 write(tls/'trust-ca.crt',ca.read_text(),0o644)
 return cert,private

def render(profile,cert,key):
 host,port,ip=values(profile)
 return ('# Managed by Heimserver Manager: Open WebUI HTTPS\nListen '+str(port)+' https\n<VirtualHost *:'+str(port)+'>\n ServerName '+host+'\n'+(' ServerAlias '+ip+'\n' if ip else '')+
 ' SSLEngine on\n SSLProtocol -all +TLSv1.2 +TLSv1.3\n SSLCertificateFile '+json.dumps(str(cert))+'\n SSLCertificateKeyFile '+json.dumps(str(key))+'\n ProxyRequests Off\n ProxyPreserveHost On\n RequestHeader set X-Forwarded-Proto "https"\n LimitRequestBody 0\n ProxyTimeout 600\n ProxyPass / http://127.0.0.1:'+str(profile['port'])+'/ upgrade=websocket\n ProxyPassReverse / http://127.0.0.1:'+str(profile['port'])+'/\n <Location />\n Require ip 127.0.0.0/8 ::1/128 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 fc00::/7 fe80::/10\n </Location>\n</VirtualHost>\n')

def install(profile):
 problems=checks(profile)
 if problems:raise ValueError('; '.join(problems))
 if not shutil.which('apache2ctl') or not shutil.which('openssl'):
  env=dict(os.environ,DEBIAN_FRONTEND='noninteractive')
  for args in (['apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'],['apt-get','-o','DPkg::Lock::Timeout=60','--no-remove','--yes','install','apache2','openssl']):subprocess.run(args,check=True,env=env,timeout=1800,stdin=subprocess.DEVNULL)
 run(['apache2ctl','configtest'])
 cert,key=certificate(profile)
 run(['a2enmod','ssl','proxy','proxy_http','headers'])
 available=APACHE/'sites-available'/SITE;enabled=APACHE/'sites-enabled'/SITE
 write(available,render(profile,cert,key),0o644)
 try:
  enabled.symlink_to(available);run(['apache2ctl','configtest'])
  run(['systemctl','enable','--now','apache2.service']);run(['systemctl','reload','apache2.service'])
  host,port,ip=values(profile)
  context=ssl.create_default_context(cafile=str(cert.parent/'trust-ca.crt'))
  with socket.create_connection(('127.0.0.1',port),timeout=10) as raw:
   with context.wrap_socket(raw,server_hostname=host) as secured:secured.getpeercert()
 except Exception:
  enabled.unlink(missing_ok=True);available.unlink(missing_ok=True)
  subprocess.run(['systemctl','reload','apache2.service'],check=False,timeout=60)
  raise
 target=Path(profile['target']);helper=target/'openwebui_https.py';shutil.copyfile(__file__,helper);helper.chmod(0o600)
 write(target/'https-profile.json',json.dumps(profile))
 quote=lambda x:json.dumps(str(x)).replace('%','%%')
 write(UNITS/(UNIT+'.service'),'[Unit]\nDescription=Open WebUI private TLS renewal\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 '+quote(helper)+' --renew '+quote(target/'https-profile.json')+'\n',0o644)
 write(UNITS/(UNIT+'.timer'),'[Unit]\nDescription=Open WebUI private TLS renewal\n[Timer]\nOnCalendar=daily\nPersistent=true\nRandomizedDelaySec=1h\n[Install]\nWantedBy=timers.target\n',0o644)
 run(['systemctl','daemon-reload']);run(['systemctl','enable','--now',UNIT+'.timer'])
 print('HTTPS: https://'+host+':'+str(port)+' · Stammzertifikat: '+str(cert.parent/'trust-ca.crt')+' · HTTP nur intern, kein LAN-Zugriff. Hostname im Router/DNS oder hosts auflösen lassen.')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--renew',required=True);args=parser.parse_args()
 profile=json.loads(Path(args.renew).read_text());certificate(profile);run(['apache2ctl','configtest']);run(['systemctl','reload','apache2.service'])
