"""Conservative ifupdown migration with independent, persistent rollback."""
import configparser,io,contextlib,fcntl,hashlib,json,os,re,subprocess,sys,tempfile,time,uuid
from pathlib import Path
ROOT=Path(os.environ.get('SERVER_MANAGER_STATE','/var/lib/server-manager'))/'bridge-migration'
UNIT='server-manager-bridge-rollback'
UNIT_DIR=Path('/etc/systemd/system')
class MigrationError(ValueError):pass

def run(args,timeout=60):
 p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if p.returncode:raise MigrationError('Befehl fehlgeschlagen: '+args[0]+': '+p.stderr[-700:])
 return p.stdout

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def atomic(path,text,mode=0o600):
 path=Path(path);fd,name=tempfile.mkstemp(dir=path.parent)
 try:
  with os.fdopen(fd,'w') as f:f.write(text);f.flush();os.fsync(f.fileno())
  os.chmod(name,mode);os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)
def state():
 try:return json.loads((ROOT/'state.json').read_text())
 except FileNotFoundError:return {}
def store(s):atomic(ROOT/'state.json',json.dumps(s))
@contextlib.contextmanager
def lock():
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (ROOT/'lock').open('a') as f:
  fcntl.flock(f,fcntl.LOCK_EX);yield

def transform(text,port,bridge,mac):
 """Move simple IPv4/IPv6 stanzas and preserve declarative options verbatim."""
 lines=text.splitlines(True);out=[];families=[];i=0
 allowed={'address','netmask','broadcast','network','gateway','metric','mtu','dns-nameservers','dns-search','dns-domain','hostname','client','leasehours','leasetime','vendor','hwaddress'}
 while i<len(lines):
  line=lines[i];words=line.split('#',1)[0].split()
  if words and words[0] in ('auto','allow-hotplug') and port in words[1:]:
   left=[v for v in words[1:] if v!=port]
   if left:out.append(words[0]+' '+' '.join(left)+'\n')
   i+=1;continue
  if words and words[0]=='iface' and len(words)>1 and words[1]==port:
   if len(words)!=4 or words[2] not in ('inet','inet6') or words[3] not in ('static','dhcp'):raise MigrationError('Nur einfache statische oder DHCP-Stanzas sind unterstützt.')
   if words[2] in families:raise MigrationError('Mehrere Stanzas derselben Adressfamilie sind nicht unterstützt.')
   if words[2]=='inet6' and words[3]=='dhcp':raise MigrationError('DHCPv6 benötigt eine gesonderte DUID/IAID-Migration.')
   families.append(words[2]);out.append('iface '+bridge+' '+' '.join(words[2:])+'\n');i+=1
   while i<len(lines):
    row=lines[i];opts=row.split('#',1)[0].split()
    if opts and (opts[0] in ('iface','auto','source','source-directory','mapping') or opts[0].startswith('allow-')):break
    if opts:
     if opts[0] not in allowed:raise MigrationError('Nicht unterstützte Netzoption: '+opts[0])
     if any(c in row for c in ('\\',';','`','$')):raise MigrationError('Dynamische Netzoptionen werden nicht automatisch übernommen.')
     if opts[0]=='hwaddress':i+=1;continue
    out.append(row);i+=1
   out.extend([f'    bridge_ports {port}\n',f'    bridge_hw {mac}\n','    bridge_stp off\n','    bridge_fd 0\n']);continue
  if port in words and words and words[0] not in ('#',):raise MigrationError('Weitere Referenz auf die Schnittstelle; manuelle Prüfung nötig.')
  out.append(line);i+=1
 if not families:raise MigrationError('Keine passende ifupdown-Konfiguration gefunden.')
 return 'auto '+bridge+'\n'+''.join(out),families

def nm_transform(text,port,bridge,mac):
 cfg=configparser.ConfigParser(interpolation=None,strict=True);cfg.optionxform=str;cfg.read_string(text)
 if set(cfg.sections())-{'connection','ethernet','802-3-ethernet','ipv4','ipv6','proxy'}:raise MigrationError('NetworkManager-Profil enthält zusätzliche Einstellungen; automatische Übernahme nicht unterstützt.')
 if cfg.get('connection','type',fallback='') not in ('ethernet','802-3-ethernet'):raise MigrationError('Nur kabelgebundene NetworkManager-Profile werden übernommen.')
 for key in ('controller','master','secondaries'):
  if cfg.get('connection',key,fallback=''):raise MigrationError('Verschachtelte NetworkManager-Verbindung nicht unterstützt.')
 old_uuid=cfg.get('connection','uuid');uuid.UUID(old_uuid)
 cfg['connection']['type']='bridge';cfg['connection']['interface-name']=bridge
 cfg['connection']['autoconnect']='true';cfg['connection']['autoconnect-slaves']='1'
 cfg['connection']['permissions']=''
 cfg['bridge']={'stp':'false','mac-address':mac}
 for section in ('ethernet','802-3-ethernet'):
  if cfg.has_section(section):
   # Ethernet-specific link settings belong on the physical port.
   break
 else:section='ethernet'
 ethernet=dict(cfg[section]) if cfg.has_section(section) else {}
 for name in ('ethernet','802-3-ethernet'):cfg.remove_section(name)
 cfg['ethernet']={'cloned-mac-address':mac}
 if ethernet.get('mtu'):cfg['ethernet']['mtu']=ethernet['mtu']
 out=io.StringIO();cfg.write(out,space_around_delimiters=False)
 port_cfg=configparser.ConfigParser(interpolation=None);port_cfg.optionxform=str
 port_uuid=str(uuid.uuid5(uuid.UUID(old_uuid),'server-manager-port:'+port+':'+bridge))
 port_cfg['connection']={'id':'server-manager-'+bridge+'-port','uuid':port_uuid,'type':'ethernet','interface-name':port,'master':old_uuid,'slave-type':'bridge','autoconnect':'true'}
 port_cfg['ethernet']=ethernet;port_cfg['ethernet']['cloned-mac-address']=mac
 port_out=io.StringIO();port_cfg.write(port_out,space_around_delimiters=False)
 return out.getvalue(),port_out.getvalue(),old_uuid,port_uuid

def nm_plan(port,bridge,iface):
 active=run(['nmcli','-g','GENERAL.CON-UUID','device','show',port]).strip()
 try:uuid.UUID(active)
 except ValueError:raise MigrationError('Kein eindeutiges aktives NetworkManager-Profil.')
 matches=[]
 for folder in ('/etc/NetworkManager/system-connections','/run/NetworkManager/system-connections'):
  for path in Path(folder).glob('*'):
   if not path.is_file() or path.is_symlink():continue
   cfg=configparser.ConfigParser(interpolation=None);cfg.read(path)
   if cfg.get('connection','uuid',fallback='')==active:matches.append(path)
 if len(matches)!=1 or str(matches[0].parent)!='/etc/NetworkManager/system-connections':raise MigrationError('Das aktive NetworkManager-Profil muss eindeutig dauerhaft unter /etc/NetworkManager/system-connections gespeichert sein.')
 target=matches[0];text=target.read_text()
 replacement,port_text,connection,port_uuid=nm_transform(text,port,bridge,iface['address'])
 port_file=target.parent/('server-manager-'+bridge+'-port.nmconnection')
 if port_file.exists():raise MigrationError('Bridge-Port-Profil existiert bereits.')
 addresses=[a['local'] for a in iface.get('addr_info',[]) if a.get('scope')=='global']
 if not addresses:raise MigrationError('Keine aktive IP-Adresse zur Übernahme gefunden.')
 return dict(mode='migrate',backend='NetworkManager',port=port,bridge=bridge,mac=iface['address'],addresses=addresses,files={str(target):text},target=str(target),replacement=replacement,port_file=str(port_file),port_text=port_text,connection=connection,port_uuid=port_uuid,description='NetworkManager: '+port+' auf '+bridge+' übernehmen. MAC, Profil-UUID und IPv4/IPv6-Einstellungen bleiben erhalten; automatischer Start und Rücksicherung nach fünf Minuten.')

def plan(port,bridge):
 for name in (port,bridge):
  if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,14}',name):raise MigrationError('Ungültiger Schnittstellenname.')
 if port==bridge or (Path('/sys/class/net')/bridge).exists():raise MigrationError('Bridge-Name bereits belegt.')
 iface=next((x for x in json.loads(run(['ip','-j','address','show'])) if x['ifname']==port),None)
 if not iface or iface.get('master') or iface.get('link_type')!='ether' or not (Path('/sys/class/net')/port/'device').exists() or (Path('/sys/class/net')/port/'wireless').exists():raise MigrationError('Eine eigenständige physische LAN-Karte auswählen.')
 if iface.get('mtu',1500)!=1500:raise MigrationError('Abweichende MTU benötigt eine gesonderte Bridge-Prüfung.')
 mac=iface.get('address','')
 if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}',mac):raise MigrationError('MAC-Adresse nicht eindeutig.')
 if subprocess.run(['systemctl','is-active','--quiet','NetworkManager'],timeout=10).returncode==0:return nm_plan(port,bridge,iface)
 if subprocess.run(['systemctl','is-active','--quiet','systemd-networkd'],timeout=10).returncode==0:raise MigrationError('systemd-networkd benötigt eine gesonderte Bridge-Einrichtung.')
 files=[Path('/etc/network/interfaces')]
 main=files[0].read_text()
 for line in main.splitlines():
  words=line.split('#',1)[0].split()
  if words and words[0] in ('source','source-directory'):
   if words not in (['source','/etc/network/interfaces.d/*'],['source-directory','/etc/network/interfaces.d']):raise MigrationError('Unbekannte Include-Struktur; keine automatische Übernahme.')
   files.extend(sorted(p for p in Path('/etc/network/interfaces.d').glob('*') if p.is_file()))
 originals={str(p):p.read_text() for p in files}
 if any(re.search(r'(?<![\w-])'+re.escape(bridge)+r'(?![\w-])',text) for text in originals.values()):raise MigrationError('Bridge-Name wird bereits in einer Konfiguration verwendet.')
 if any(Path(p).is_symlink() for p in originals):raise MigrationError('Symlink-Konfiguration nicht unterstützt.')
 matches=[p for p,text in originals.items() if re.search(r'^\s*iface\s+'+re.escape(port)+r'\s',text,re.M)]
 if len(matches)!=1:raise MigrationError('Genau eine Konfigurationsdatei für die Schnittstelle erforderlich.')
 target=matches[0]
 if any(re.search(r'(?<![\w-])'+re.escape(port)+r'(?![\w-])',text) for p,text in originals.items() if p!=target):raise MigrationError('Schnittstellenkonfiguration verteilt; manuelle Prüfung erforderlich.')
 new,families=transform(originals[target],port,bridge,mac)
 for p in (Path('/etc/dhcp/dhclient.conf'),Path('/etc/dhcpcd.conf')):
  if p.exists() and re.search(r'(?<![\w-])'+re.escape(port)+r'(?![\w-])',p.read_text()):raise MigrationError('Schnittstellenspezifische DHCP-Konfiguration zuerst manuell prüfen.')
 addresses=[x['local'] for x in iface.get('addr_info',[]) if x.get('scope')=='global']
 if not addresses:raise MigrationError('Keine aktive IP-Adresse zur Übernahme gefunden.')
 return dict(port=port,bridge=bridge,mac=mac,addresses=addresses,files=originals,target=target,replacement=new,mode='migrate',description='Aktive LAN-Karte '+port+' auf '+bridge+' übernehmen; MAC/IP beibehalten. Bestätigung innerhalb von fünf Minuten erforderlich.')

def healthy(s):
 rows=json.loads(run(['ip','-j','address','show','dev',s['bridge']]))
 if len(rows)!=1:return False
 current=rows[0]
 return current.get('address','').lower()==s['mac'].lower() and set(s['addresses'])<=set(x['local'] for x in current.get('addr_info',[]))

def arm(s):
 # Copy rollback executable into protected persistent storage, independent of the app process.
 atomic(ROOT/'rollback.py',Path(__file__).read_text())
 env=str(ROOT.parent).replace('%','%%').replace('"','\\"')
 script=str(ROOT/'rollback.py').replace('%','%%').replace('"','\\"')
 service='[Unit]\nDescription=Rollback unconfirmed host bridge\nDefaultDependencies=no\nAfter=local-fs.target\nBefore=network-pre.target networking.service NetworkManager.service\nWants=network-pre.target\n[Service]\nType=oneshot\nRestart=on-failure\nRestartSec=15\nEnvironment="SERVER_MANAGER_STATE='+env+'"\nExecStart=/usr/bin/python3 "'+script+'" rollback\n[Install]\nWantedBy=multi-user.target\n'
 timer='[Unit]\nDescription=Bridge confirmation deadline\n[Timer]\nOnActiveSec=300\nAccuracySec=1s\nUnit='+UNIT+'.service\n[Install]\nWantedBy=timers.target\n'
 for suffix in ('service','timer'):
  if (UNIT_DIR/(UNIT+'.'+suffix)).exists():raise MigrationError('Rücksicherungsdienst existiert bereits; zuerst prüfen.')
 for suffix,text in (('service',service),('timer',timer)):
  path=UNIT_DIR/(UNIT+'.'+suffix)
  if path.exists():raise MigrationError('Rücksicherungsdienst existiert bereits; zuerst prüfen.')
  atomic(path,text,0o644)
 run(['systemctl','daemon-reload']);run(['systemctl','enable',UNIT+'.service']);run(['systemctl','enable','--now',UNIT+'.timer'])
 if run(['systemctl','is-active',UNIT+'.timer']).strip()!='active':raise MigrationError('Rücksicherungstimer nicht aktiv.')

def disarm():
 run(['systemctl','disable','--now',UNIT+'.timer'])
 run(['systemctl','disable',UNIT+'.service'])
 for suffix in ('service','timer'):(UNIT_DIR/(UNIT+'.'+suffix)).unlink(missing_ok=True)
 run(['systemctl','daemon-reload'])

def apply(profile):
 with lock():
  if state().get('status') in ('applying','pending','rolling-back'):raise MigrationError('Eine Bridge-Übernahme wartet bereits auf Bestätigung.')
  p=plan(profile['interface'],profile['bridge'])
  if digest(p)!=profile.get('migration_digest'):raise MigrationError('Netzwerkkonfiguration hat sich seit der Vorschau geändert.')
  s=dict(p,id=uuid.uuid4().hex,status='applying',deadline=time.time()+300,boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
  # Refuse existing units before arming so error cleanup cannot touch foreign units.
  if any((UNIT_DIR/(UNIT+'.'+suffix)).exists() for suffix in ('service','timer')):raise MigrationError('Rücksicherungsdienst existiert bereits.')
  store(s)
  try:arm(s)
  except Exception:
   s['status']='failed-before-change';store(s)
   try:disarm()
   except Exception:pass
   raise
  try:
   if p.get('backend')=='NetworkManager':
    atomic(p['port_file'],p['port_text'])
    atomic(p['target'],p['replacement'])
    run(['nmcli','connection','reload'])
    run(['nmcli','connection','down','uuid',p['connection']],120)
    run(['nmcli','connection','up','uuid',p['connection']],120)
    run(['nmcli','connection','up','uuid',p['port_uuid']],120)
    s['status']='pending';store(s);return s
   run(['systemctl','enable','networking.service'])
   # ifdown must still see the original configuration.
   run(['ifdown',p['port']],120)
   atomic(p['target'],p['replacement'],Path(p['target']).stat().st_mode & 0o777)
   run(['ifup',p['bridge']],120)
   s['status']='pending';store(s)
  except Exception:
   rollback_locked(s);raise
 return s

def rollback_locked(s):
 s['status']='rolling-back';store(s)
 same_boot=s['boot']==Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 if s.get('backend')=='NetworkManager':
  atomic(s['target'],s['files'][s['target']])
  Path(s['port_file']).unlink(missing_ok=True)
  if same_boot:
   subprocess.run(['nmcli','connection','down','uuid',s['port_uuid']],capture_output=True,timeout=60)
   subprocess.run(['nmcli','connection','down','uuid',s['connection']],capture_output=True,timeout=60)
   run(['nmcli','connection','reload'])
   run(['nmcli','connection','up','uuid',s['connection']],120)
  s['status']='rolled-back';store(s);disarm();return
 if same_boot:
  subprocess.run(['ifdown',s['bridge']],capture_output=True,timeout=120)
 atomic(s['target'],s['files'][s['target']],Path(s['target']).stat().st_mode & 0o777)
 if same_boot:
  subprocess.run(['ip','link','set',s['port'],'nomaster'],capture_output=True,timeout=20)
  subprocess.run(['ip','link','delete',s['bridge'],'type','bridge'],capture_output=True,timeout=20)
  run(['ifup','--force',s['port']],120)
 s['status']='rolled-back';store(s)
 # Do not stop the currently running rollback service itself.
 disarm()

def rollback():
 with lock():
  s=state()
  if s.get('status') in ('applying','pending','rolling-back'):rollback_locked(s)

def confirm(transaction):
 with lock():
  s=state()
  if s.get('id')!=transaction or s.get('status')!='pending':raise MigrationError('Keine passende offene Umstellung.')
  if time.time()>=s['deadline']:raise MigrationError('Bestätigungsfrist abgelaufen; Rücksicherung abwarten.')
  if not healthy(s):raise MigrationError('Bisherige MAC/IP nicht vollständig an der Bridge; keine Bestätigung möglich.')
  # Define libvirt linkage only after connectivity confirmation.
  import tempfile
  if 'servermgr-lan' in run(['virsh','-c','qemu:///system','net-list','--all','--name']).splitlines():raise MigrationError('servermgr-lan existiert bereits; bitte prüfen.')
  xml="<network><name>servermgr-lan</name><forward mode='bridge'/><bridge name='"+s['bridge']+"'/></network>"
  with tempfile.NamedTemporaryFile(mode='w',suffix='.xml') as f:
   f.write(xml);f.flush();run(['virsh','-c','qemu:///system','net-define',f.name])
  try:
   run(['virsh','-c','qemu:///system','net-start','servermgr-lan']);run(['virsh','-c','qemu:///system','net-autostart','servermgr-lan'])
  except Exception:
   subprocess.run(['virsh','-c','qemu:///system','net-destroy','servermgr-lan'],capture_output=True,timeout=30)
   subprocess.run(['virsh','-c','qemu:///system','net-undefine','servermgr-lan'],capture_output=True,timeout=30);raise
  s['status']='confirmed';store(s);disarm()
 return s

if __name__=='__main__':
 if sys.argv[1:]!=['rollback']:raise SystemExit('Nur rollback unterstützt')
 rollback()
