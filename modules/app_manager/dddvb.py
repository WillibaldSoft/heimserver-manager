"""Digital Devices driver inventory and explicitly approved DKMS operations."""
import hashlib,json,os,re,shutil,subprocess,tarfile,tempfile,time,urllib.request
from pathlib import Path
import server_settings as cfg
VERSION='0.9.41'
SHA256='356e54fb48437550b95caadb905af49db4c4621c2375cc3f236c3d8f6aa2ea3a'
URL='https://codeload.github.com/DigitalDevices/dddvb/tar.gz/refs/tags/'+VERSION
API='https://api.github.com/repos/DigitalDevices/dddvb/releases/latest'
ROOT=cfg.STATE_DIR/'dddvb'
SOURCE=Path('/usr/src')/('dddvb-'+VERSION)
ACTIONS={'dddvb-install','dddvb-install-native','dddvb-repair'}
FRONTENDS=('drxk','lnbp21','stv090x','stv6110x','cxd2099','tda18271c2dd','stv0367dd','tda18212dd','cxd2843','stv6111','stv0910','lnbh25','mxl5xx')
def tool(name):
 return shutil.which(name) or (str(Path('/usr/sbin')/name) if (Path('/usr/sbin')/name).exists() else None)
def output(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=20,env=dict(os.environ,LC_ALL='C'))
 if r.returncode:raise ValueError(args[0]+': '+r.stderr.strip()[-1000:])
 return r.stdout.strip()
def read(p):
 try:return Path(p).read_text().strip()
 except FileNotFoundError:return ''
def parse_dkms(text):
 rows=[]
 for line in text.splitlines():
  if not line.startswith(('dddvb/','dddvb,')):continue
  match=re.fullmatch(r'dddvb[/,]\s*([^, :]+)(?:,\s*([^, :]+),\s*([^:]+))?:\s*(.+)',line.strip())
  if not match:raise ValueError('Unbekanntes DKMS-Statusformat für dddvb')
  v,k,arch,state=match.groups();rows.append(dict(version=v,kernel=k or '',arch=arch or '',state=state))
 return rows

def status():
 kernel=os.uname().release;errors=[];cards=[]
 for p in sorted(Path('/sys/bus/pci/devices').glob('*')):
  if read(p/'vendor')=='0xdd01':cards.append(dict(slot=p.name,device=read(p/'device'),revision=read(p/'revision'),driver=(p/'driver').resolve().name if (p/'driver').exists() else 'nicht gebunden'))
 dkms=tool('dkms');rows=[]
 if dkms:
  try:rows=parse_dkms(output([dkms,'status','-m','dddvb']))
  except (ValueError,OSError,subprocess.SubprocessError) as e:errors.append(str(e))
 module={}
 for field in ('version','filename'):
  try:module[field]=output([tool('modinfo') or 'modinfo','-k',kernel,'-F',field,'ddbridge'])
  except (ValueError,OSError,subprocess.SubprocessError):module[field]=''
 secure='disabled'
 if Path('/sys/firmware/efi').exists():
  try:
   text=output([tool('mokutil') or 'mokutil','--sb-state'])
   secure='enabled' if 'SecureBoot enabled' in text else 'disabled' if 'SecureBoot disabled' in text else 'unknown'
  except (ValueError,OSError,subprocess.SubprocessError):secure='unknown'
 enrolled=False
 if secure=='enabled' and Path('/var/lib/dkms/mok.pub').is_file():
  try:output([tool('mokutil') or 'mokutil','--test-key','/var/lib/dkms/mok.pub']);enrolled=True
  except (ValueError,OSError,subprocess.SubprocessError):pass
 conf=SOURCE/'dkms.conf';config_hash=hashlib.sha256(conf.read_bytes()).hexdigest() if conf.is_file() else ''
 try:osinfo=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
 except OSError:osinfo={}
 current=[r for r in rows if r['kernel']==kernel and r['state'].startswith('installed')]
 loaded=read('/sys/module/ddbridge/version')
 state=dict(kernel=kernel,cards=cards,dkms=bool(dkms),registrations=rows,module=module,loaded=loaded,secure_boot=secure,key_enrolled=enrolled,headers=(Path('/lib/modules')/kernel/'build').is_dir(),source_exists=SOURCE.exists(),config_hash=config_hash,current=current,errors=errors,supported_os=osinfo.get('ID','').strip('"')=='debian' and osinfo.get('VERSION_ID','').strip('"')=='13')
 try:marker=json.loads((ROOT/'last-install.json').read_text())
 except FileNotFoundError:marker={}
 state['reboot_pending']=bool(marker.get('boot_id') and marker['boot_id']==read('/proc/sys/kernel/random/boot_id'))
 state['fingerprint']=hashlib.sha256(json.dumps({k:state[k] for k in ('kernel','registrations','module','loaded','secure_boot','key_enrolled','source_exists','config_hash')},sort_keys=True).encode()).hexdigest()
 return state

def plan(action,state):
 if action not in ACTIONS:raise ValueError('Unbekannte Treiberaktion')
 if state['errors']:raise ValueError('DKMS-Status unklar: '+ '; '.join(state['errors']))
 if not state['supported_os']:raise ValueError('Automatische Treiberinstallation ist für Debian 13 vorgesehen.')
 if not state['cards']:raise ValueError('Keine Digital-Devices-PCI-Karte erkannt.')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,150}',state['kernel']):raise ValueError('Ungültiger Kernelname')
 if state['secure_boot']=='unknown':raise ValueError('Secure-Boot-Status unklar. mokutil und Firmwarezustand prüfen.')
 if state['secure_boot']=='enabled' and not state['key_enrolled']:raise ValueError('Secure Boot: DKMS-Schlüssel noch nicht nachweislich eingeschrieben. Zuerst MOK-Einrichtung abschließen.')
 registered=any(r['version']==VERSION for r in state['registrations'])
 if action=='dddvb-repair':
  if not registered or not state['source_exists'] or not state['config_hash']:raise ValueError('Reparatur benötigt die vorhandenen registrierten Quellen von dddvb/'+VERSION)
 else:
  if state['source_exists'] or registered:raise ValueError('Zielversion bereits vorhanden. Für Neubau die Reparatur verwenden; vorhandene Quellen werden nicht überschrieben.')
  # Replacing unknown manually installed modules is not an automatic upgrade.
  if '/updates/' in state['module'].get('filename','') and not state['current']:raise ValueError('Nicht durch DKMS zugeordnete Treiberinstallation erkannt. Zuerst manuell prüfen.')
  for row in state['registrations']:
   if not re.fullmatch(r'0\.9\.(?:[0-9]|[1-3][0-9]|40)[a-z]?',row['version']):raise ValueError('Neuere oder unbekannte Bestandsversion; kein automatischer Versionswechsel.')
 return dict(action=action,fingerprint=state['fingerprint'],kernel=state['kernel'],target=VERSION)

def latest():
 try:return json.loads((ROOT/'release.json').read_text())
 except FileNotFoundError:return {}
def check_release():
 result=dict(checked=time.time(),status='unknown')
 try:
  req=urllib.request.Request(API,headers={'Accept':'application/vnd.github+json','User-Agent':'Heimserver-Manager'})
  with urllib.request.urlopen(req,timeout=20) as response:data=json.loads(response.read(1024*1024))
  tag=str(data.get('tag_name','')).removeprefix('v')
  if data.get('draft') or data.get('prerelease') or not re.fullmatch(r'\d+\.\d+\.\d+[a-z]?',tag):raise ValueError('Keine eindeutig stabile Herstellerversion')
  result.update(status='checked',version=tag,installable=tag==VERSION,url='https://github.com/DigitalDevices/dddvb/releases')
 except (OSError,ValueError) as e:result['error']='Herstellerprüfung fehlgeschlagen: '+str(e)[:300]
 cfg.atomic(ROOT/'release.json',result);return result

def dkms_config(native=False):
 modules=([('dvb-core','dvb-core')] if not native else [])+[('ddbridge','ddbridge')]+([('octonet','ddbridge')] if not native else [])+[(m,'frontends') for m in FRONTENDS]
 flags=' KERNEL_DVB_CORE=y' if native else ''
 text='PACKAGE_NAME="dddvb"\nPACKAGE_VERSION="'+VERSION+'"\nAUTOINSTALL="yes"\nMAKE[0]="make -j4'+flags+' KDIR=/lib/modules/${kernelver}/build kernelver=${kernelver}"\nCLEAN="make'+flags+' clean"\n'
 for i,(name,folder) in enumerate(modules):text+=f'BUILT_MODULE_NAME[{i}]="{name}"\nBUILT_MODULE_LOCATION[{i}]="{folder}"\nDEST_MODULE_LOCATION[{i}]="/updates/dkms"\n'
 return text

def unpack(archive,dest):
 with tarfile.open(archive,'r:gz') as tar:
  members=tar.getmembers()
  if sum(m.size for m in members)>100_000_000:raise ValueError('Treiberarchiv zu groß')
  for m in members:
   p=Path(m.name)
   if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='dddvb-'+VERSION or not (m.isdir() or m.isfile()):raise ValueError('Unerlaubter Eintrag im Treiberarchiv')
  tar.extractall(dest,members=members,filter='data')

def execute(action,log,expected):
 current=status();p=plan(action,current)
 if not isinstance(expected,dict) or expected!=p:raise ValueError('Treiber- oder Kernelstand hat sich geändert. Neue Vorschau erforderlich.')
 def run(args,timeout=3600):
  print('Befehl: '+' '.join(args),file=log,flush=True)
  subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,check=True,timeout=timeout,env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',LC_ALL='C'))
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 backup=ROOT/('before-'+str(time.time_ns()));backup.mkdir(mode=0o700)
 cfg.atomic(backup/'inventory.json',current)
 if (SOURCE/'dkms.conf').is_file():shutil.copy2(SOURCE/'dkms.conf',backup/'dkms.conf')
 # Download and validate before package or module changes.
 with tempfile.TemporaryDirectory(prefix='dddvb-') as temp:
  temp=Path(temp)
  if action!='dddvb-repair':
   archive=temp/'driver.tar.gz'
   with urllib.request.urlopen(URL,timeout=30) as response,archive.open('wb') as out:
    total=0
    while block:=response.read(65536):
     total+=len(block)
     if total>10_000_000:raise ValueError('Treiberdownload zu groß')
     out.write(block)
   if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise ValueError('Treiber-Prüfsumme stimmt nicht. Keine Installation.')
   unpack(archive,temp/'source')
  run(['apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'])
  run(['apt-get','-o','DPkg::Lock::Timeout=60','--no-remove','--yes','install','dkms','build-essential','linux-headers-'+p['kernel']])
  if not (Path('/lib/modules')/p['kernel']/'build').is_dir():raise ValueError('Kernel-Header fehlen trotz Paketinstallation')
  # Recheck changes made outside the manager; APT may have registered modules.
  after=status()
  if after['kernel']!=p['kernel'] or after['registrations']!=current['registrations'] or after['loaded']!=current['loaded']:raise ValueError('Kernel- oder Treiberstand während der Vorbereitung geändert; neue Vorschau erforderlich')
  if action!='dddvb-repair':
   plan(action,after)
   shutil.copytree(temp/'source'/('dddvb-'+VERSION),SOURCE)
   (SOURCE/'dkms.conf').write_text(dkms_config(action.endswith('-native')))
   run([tool('dkms'),'add','-m','dddvb','-v',VERSION])
  elif after['config_hash']!=current['config_hash']:raise ValueError('DKMS-Konfiguration zwischenzeitlich geändert')
  run([tool('dkms'),'build','-m','dddvb','-v',VERSION,'-k',p['kernel'],'--force'])
  run([tool('dkms'),'install','-m','dddvb','-v',VERSION,'-k',p['kernel'],'--force'])
  final=status()
  if not any(r['version']==VERSION and r['kernel']==p['kernel'] and r['state'].startswith('installed') for r in final['registrations']):raise ValueError('DKMS-Installation nicht bestätigt')
  cfg.atomic(ROOT/'last-install.json',dict(version=VERSION,kernel=p['kernel'],finished=time.time(),reboot_required=True,boot_id=read('/proc/sys/kernel/random/boot_id')))
 print('DKMS installiert. Geladene Module unverändert; Aktivierung beim geplanten Neustart. Keine Tvheadend-Neustarts und keine Firmwareänderung. Alte Quellen und DKMS-Stände bleiben erhalten. Sicherung: '+str(backup),file=log,flush=True)
