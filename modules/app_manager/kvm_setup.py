"""Optional Debian KVM setup with explicitly confirmed host bridge migration."""
import json,os,platform,pwd,re,subprocess,tempfile
try:from tools.platform_check import read_release,matches
except ImportError:from platform_check import read_release,matches
from pathlib import Path
from xml.sax.saxutils import escape
class SetupError(ValueError):pass

def run(args,timeout=120):
 p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if p.returncode:
  hint=' Eine Paketquelle meldet einen Signaturfehler. Quelle oder Schlüssel in der System-Paketverwaltung korrigieren; die Signaturprüfung wird nicht umgangen.' if args[0]=='apt-get' and any(x in p.stderr for x in ('EXPKEYSIG','NO_PUBKEY','BADSIG')) else ''
  raise SetupError('Befehl fehlgeschlagen: '+args[0]+'.'+hint+' '+p.stderr[-1000:])
 return p.stdout

def packages():
 arch=platform.machine()
 if arch in ('x86_64','amd64'):machine=['qemu-system-x86','ovmf']
 elif arch in ('aarch64','arm64'):machine=['qemu-system-arm','qemu-efi-aarch64']
 else:raise SetupError('Unterstützt: amd64 oder arm64.')
 return machine+['qemu-utils','squashfs-tools','swtpm','swtpm-tools','libvirt-daemon-system','libvirt-clients','virtinst','python3-libvirt','dnsmasq-base','bridge-utils','iproute2']

def interfaces():return json.loads(run(['ip','-json','address','show']))
def lan_choices():
 rows=[]
 for item in interfaces():
  name=item.get('ifname','');path=Path('/sys/class/net')/name
  if item.get('link_type')!='ether' or item.get('master') or (path/'wireless').exists():continue
  if not (path/'device').exists() and not (path/'bridge').is_dir():continue
  addresses=[a['local'] for a in item.get('addr_info',[]) if a.get('scope')=='global']
  rows.append(dict(name=name,mac=item.get('address',''),addresses=addresses,bridge=(path/'bridge').is_dir(),state=item.get('operstate','UNKNOWN')))
 return rows

def active_lan():
 routes=json.loads(run(['ip','-json','route','show','default']))
 devices={r.get('dev') for r in routes if r.get('dev')}
 choices=[i for i in lan_choices() if i['name'] in devices and i['addresses']]
 if len(choices)!=1:raise SetupError('Aktive LAN-Verbindung nicht eindeutig. Bitte Schnittstelle ausdrücklich auswählen.')
 return choices[0]

def bridge_name(value):
 if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,14}',value):raise SetupError('Bridge-/Schnittstellenname: maximal 15 Buchstaben, Zahlen, _ oder -.')
 return value

def migration_module():
 try:from . import bridge_migration
 except ImportError:import bridge_migration
 return bridge_migration

def network_plan(profile):
 mode=profile.get('network','nat')
 if mode=='migrate':return migration_module().plan(profile.get('interface',''),profile.get('bridge','br0'))
 if mode=='nat':return {'mode':'nat','description':'Libvirt-NAT-Netz default; keine Änderung der physischen LAN-Schnittstellen.'}
 if mode not in ('existing','new'):raise SetupError('Ungültige Netzwerkauswahl.')
 bridge=bridge_name(profile.get('bridge','br0'))
 if mode=='existing':
  if not (Path('/sys/class/net')/bridge/'bridge').is_dir():raise SetupError('Die ausgewählte Linux-Bridge existiert nicht.')
  return dict(mode=mode,bridge=bridge,description='Vorhandene Bridge '+bridge+' als libvirt-Netz servermgr-lan verwenden.')
 port=bridge_name(profile.get('interface',''))
 if (Path('/sys/class/net')/bridge).exists():raise SetupError('Bridge-Name ist bereits belegt.')
 iface=next((i for i in interfaces() if i['ifname']==port),None)
 if not iface or iface.get('link_type')!='ether' or iface.get('master') or iface.get('addr_info') or not (Path('/sys/class/net')/port/'device').exists() or (Path('/sys/class/net')/port/'wireless').exists():raise SetupError('Neue Bridge benötigt eine freie kabelgebundene Netzkarte ohne IP-Adresse oder Master.')
 for family in ('-4','-6'):
  if any(r.get('dev')==port for r in json.loads(run(['ip',family,'-json','route','show','table','all']))):raise SetupError('Schnittstelle wird für Routing benutzt.')
 main=Path('/etc/network/interfaces')
 if not main.is_file() or not re.search(r'^\s*source(?:-directory)?\s+/etc/network/interfaces.d(?:/\*)?\s*$',main.read_text(),re.M):raise SetupError('Automatische neue Bridge benötigt ifupdown mit eingebundenem interfaces.d. Bestehende Bridge oder NAT wählen.')
 for unit in ('NetworkManager','systemd-networkd'):
  if subprocess.run(['systemctl','is-active','--quiet',unit],timeout=10).returncode==0:raise SetupError('Neue Bridge hier nur mit ifupdown; Bridge zuvor in der aktiven Netzwerkverwaltung anlegen.')
 files=[main]+[p for p in Path('/etc/network/interfaces.d').glob('*') if p.is_file()]
 if any(re.search(r'(?<![\w-])'+re.escape(port)+r'(?![\w-])',p.read_text()) for p in files):raise SetupError('Schnittstelle ist bereits konfiguriert; kein automatisches Überschreiben.')
 text=f'auto {bridge}\niface {bridge} inet manual\n    bridge_ports {port}\n    bridge_stp on\n    bridge_fd 2\n'
 return dict(mode=mode,bridge=bridge,interface=port,text=text,description='Neue LAN-Bridge '+bridge+' über '+port+' ohne eigene Host-IP. VMs erhalten ihre Adresse vom LAN.')

def checks(profile):
 issues=[]
 try:
  osinfo=read_release()
  if not any(matches(target,osinfo) for target in ('debian13','mint22')):raise SetupError('KVM-Installer unterstützt Debian 13 und Linux Mint 22.x mit Ubuntu-Noble-Basis.')
  packages();network_plan(profile)
  user=profile.get('user','')
  if user and (pwd.getpwnam(user).pw_uid<1000 or pwd.getpwnam(user).pw_uid>=60000):raise SetupError('Einen normalen lokalen Benutzer auswählen.')
 except (ValueError,KeyError,OSError,subprocess.SubprocessError) as exc:issues.append(str(exc))
 return issues

def install(profile):
 if os.geteuid()!=0:raise SetupError('Installation benötigt root.')
 issues=checks(profile)
 if issues:raise SetupError('; '.join(issues))
 run(['apt-get','-o','APT::Update::Error-Mode=any','update'],1800);run(['apt-get','--no-remove','install','-y',*packages()],3600)
 run(['systemctl','enable','--now','libvirtd.service'])
 plan=network_plan(profile) # Recheck after package installation.
 if plan['mode']=='migrate':
  run(['virsh','-c','qemu:///system','list','--all'])
  if not Path('/dev/kvm').exists():raise SetupError('Pakete installiert, aber /dev/kvm fehlt. Vor der Bridge-Umstellung Virtualisierung aktivieren.')
  if profile.get('user'):run(['usermod','-aG','libvirt,kvm',profile['user']])
  migration_module().apply(profile)
  print('Bridge aktiviert; innerhalb von fünf Minuten unter Apps → KVM-Installer Verbindung bestätigen. Sonst automatische Rücksicherung.')
  return
 if plan['mode']=='nat':
  names=run(['virsh','-c','qemu:///system','net-list','--all','--name']).splitlines()
  if 'default' not in names:run(['virsh','-c','qemu:///system','net-define','/usr/share/libvirt/networks/default.xml'])
  if 'default' not in run(['virsh','-c','qemu:///system','net-list','--name']).splitlines():run(['virsh','-c','qemu:///system','net-start','default'])
  run(['virsh','-c','qemu:///system','net-autostart','default'])
 else:
  names=run(['virsh','-c','qemu:///system','net-list','--all','--name']).splitlines()
  if 'servermgr-lan' in names:raise SetupError('Libvirt-Netz servermgr-lan existiert bereits; bleibt unverändert.')
  created=None
  if plan['mode']=='new':
   created=Path('/etc/network/interfaces.d')/('servermgr-'+plan['bridge'])
   with created.open('x') as f:f.write(plan['text'])
   os.chmod(created,0o644)
   try:run(['ifup',plan['bridge']])
   except Exception:
    subprocess.run(['ifdown',plan['bridge']],capture_output=True,timeout=60);created.unlink();raise
  xml="<network><name>servermgr-lan</name><forward mode='bridge'/><bridge name='"+escape(plan['bridge'])+"'/></network>"
  with tempfile.NamedTemporaryFile(mode='w',suffix='.xml') as f:
   f.write(xml);f.flush();run(['virsh','-c','qemu:///system','net-define',f.name])
  run(['virsh','-c','qemu:///system','net-start','servermgr-lan']);run(['virsh','-c','qemu:///system','net-autostart','servermgr-lan'])
 if profile.get('user'):run(['usermod','-aG','libvirt,kvm',profile['user']])
 run(['virsh','-c','qemu:///system','list','--all'])
 if not Path('/dev/kvm').exists():raise SetupError('Pakete installiert, aber /dev/kvm fehlt. Virtualisierung im BIOS/UEFI oder Nested Virtualization aktivieren.')
 print('KVM/libvirt eingerichtet. Neue Gruppenmitgliedschaft gilt nach erneuter Anmeldung. VMs unter Server → Virtuelle Maschinen verwalten.')
