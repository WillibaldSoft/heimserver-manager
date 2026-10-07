"""Debian NVIDIA inventory and confirmed package-managed driver operations."""
import hashlib,json,os,re,subprocess,time
from pathlib import Path
import server_settings as cfg
from .dddvb import output,read,tool
ROOT=cfg.STATE_DIR/'nvidia'
ACTIONS={'nvidia-detect','nvidia-install','nvidia-repair'}
PACKAGES=('nvidia-driver','nvidia-kernel-dkms')
def candidate(package):
 text=output(['apt-cache','policy',package])
 match=re.search(r'^\s*Candidate:\s*(\S+)',text,re.M)
 return match[1] if match and match[1]!='(none)' else ''
def status():
 kernel=os.uname().release;errors=[];cards=[]
 for p in sorted(Path('/sys/bus/pci/devices').glob('*')):
  if read(p/'vendor')=='0x10de' and read(p/'class').startswith('0x03'):
   cards.append(dict(slot=p.name,device=read(p/'device'),driver=(p/'driver').resolve().name if (p/'driver').exists() else 'nicht gebunden'))
 installed={}
 try:
  data=output(['dpkg-query','-W','-f=${Package}\t${Version}\t${db:Status-Status}\n'])
  for line in data.splitlines():
   fields=line.split('\t')
   if len(fields)==3 and fields[2]=='installed' and ('nvidia' in fields[0] or fields[0]=='cuda-drivers'):installed[fields[0]]=fields[1]
 except (OSError,ValueError,subprocess.SubprocessError) as e:errors.append(str(e))
 candidates={}
 for package in (*PACKAGES,'nvidia-detect','linux-headers-'+kernel):
  try:candidates[package]=candidate(package)
  except (OSError,ValueError,subprocess.SubprocessError) as e:errors.append(str(e))
 module={}
 for field in ('version','filename'):
  module[field]=''
  for name in ('nvidia-current','nvidia'):
   try:module[field]=output([tool('modinfo') or 'modinfo','-k',kernel,'-F',field,name]);break
   except (OSError,ValueError,subprocess.SubprocessError):pass
 dkms=''
 if tool('dkms'):
  try:dkms='\n'.join(line for line in output([tool('dkms'),'status']).splitlines() if line.startswith('nvidia'))
  except (OSError,ValueError,subprocess.SubprocessError) as e:errors.append(str(e))
 secure='disabled';enrolled=False
 if Path('/sys/firmware/efi').exists():
  try:
   text=output([tool('mokutil') or 'mokutil','--sb-state'])
   secure='enabled' if 'SecureBoot enabled' in text else 'disabled' if 'SecureBoot disabled' in text else 'unknown'
  except (OSError,ValueError,subprocess.SubprocessError):secure='unknown'
 if secure=='enabled':
  try:output([tool('mokutil') or 'mokutil','--test-key','/var/lib/dkms/mok.pub']);enrolled=True
  except (OSError,ValueError,subprocess.SubprocessError):pass
 recommendation='';detect_text='nvidia-detect ist noch nicht installiert.'
 if tool('nvidia-detect'):
  try:
   detect_text=output([tool('nvidia-detect')])
   recommendations=re.findall(r'^\s+(nvidia(?:-[a-z0-9]+)*-driver)\s*$',detect_text,re.M)
   if recommendations and set(recommendations)=={'nvidia-driver'}:recommendation='nvidia-driver'
  except (OSError,ValueError,subprocess.SubprocessError) as e:detect_text=str(e)
 gpu='';processes='';loaded=read('/sys/module/nvidia/version')
 if loaded:
  try:
   gpu=output([tool('nvidia-smi') or 'nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'])
   processes=output([tool('nvidia-smi') or 'nvidia-smi','--query-compute-apps=pid,process_name','--format=csv,noheader'])
  except (OSError,ValueError,subprocess.SubprocessError) as e:errors.append('GPU-Nutzung nicht prüfbar: '+str(e))
 osinfo=dict(line.split('=',1) for line in read('/etc/os-release').splitlines() if '=' in line)
 state=dict(kernel=kernel,cards=cards,installed=installed,candidates=candidates,module=module,loaded=loaded,dkms=dkms,secure_boot=secure,key_enrolled=enrolled,recommendation=recommendation,detect_text=detect_text,gpu=gpu,processes=processes,errors=errors,headers=(Path('/lib/modules')/kernel/'build').is_dir(),supported_os=osinfo.get('ID','').strip('"')=='debian' and osinfo.get('VERSION_ID','').strip('"')=='13',run_installer=Path('/usr/bin/nvidia-uninstall').exists())
 try:marker=json.loads((ROOT/'last-install.json').read_text())
 except FileNotFoundError:marker={}
 state['reboot_pending']=marker.get('boot_id')==read('/proc/sys/kernel/random/boot_id')
 return state

def package_args(action,state):
 packages=['nvidia-detect'] if action=='nvidia-detect' else list(PACKAGES)+['linux-headers-'+state['kernel']]
 if action=='nvidia-repair':packages=list(PACKAGES)+['linux-headers-'+state['kernel']]
 return [p+'='+state['candidates'][p] for p in packages]
def simulate(action,state):
 args=['apt-get','--simulate','--no-remove']+(['--reinstall'] if action=='nvidia-repair' else [])+['install']+package_args(action,state)
 text=output(args)
 if re.search(r'^Remv\s',text,re.M) or 'DOWNGRADED' in text:raise ValueError('Paketplan enthält Entfernung oder Downgrade.')
 return '\n'.join(line for line in text.splitlines() if line.startswith(('Inst ','Conf ','Remv ')))
def plan(action,state):
 if action not in ACTIONS:raise ValueError('Unbekannte NVIDIA-Aktion')
 if not state['supported_os']:raise ValueError('Automatische Installation ist für Debian 13 vorgesehen.')
 if state['errors']:raise ValueError('; '.join(state['errors']))
 if not state['cards']:raise ValueError('Keine NVIDIA-Grafikkarte erkannt.')
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,150}',state['kernel']):raise ValueError('Ungültiger Kernelname')
 if action!='nvidia-detect':
  if state['run_installer']:raise ValueError('NVIDIA-.run-Installation erkannt. Zuerst manuell auf Debian-Pakete umstellen.')
  if state['secure_boot']=='unknown' or (state['secure_boot']=='enabled' and not state['key_enrolled']):raise ValueError('Secure Boot und eingeschriebenen DKMS-Schlüssel zuerst klären.')
  installed=state['installed']
  foreign=[p for p in installed if p=='cuda-drivers' or p.startswith(('nvidia-open','nvidia-tesla','nvidia-kernel-open')) or re.match(r'nvidia-(?:legacy-|driver-|dkms-)\d',p)]
  if foreign:raise ValueError('Abweichende Treiberfamilie: '+', '.join(foreign)+'. Kein automatischer Wechsel.')
  existing=all(p in installed for p in PACKAGES)
  if not existing and state['recommendation']!='nvidia-driver':raise ValueError('Zuerst Hardwareprüfung mit nvidia-detect durchführen. Unterstützt wird dessen Empfehlung nvidia-driver.')
  if not existing and (state['loaded'] or state['module']['version'] or state['dkms']):raise ValueError('Vorhandener Treiber nicht eindeutig Debian-Paketen zugeordnet.')
  if action=='nvidia-repair' and not existing:raise ValueError('Reparatur benötigt eine vorhandene Debian-Treiberinstallation.')
  if state['processes']:raise ValueError('GPU-Rechenprozesse sind aktiv. Anwendungen vor Treiberänderungen beenden: '+state['processes'])
  for package in PACKAGES:
   old=installed.get(package);new=state['candidates'].get(package)
   if old and new and subprocess.run(['dpkg','--compare-versions',new,'lt',old]).returncode==0:raise ValueError('Kein automatisches Downgrade von '+package)
 packages=['nvidia-detect'] if action=='nvidia-detect' else [*PACKAGES,'linux-headers-'+state['kernel']]
 for p in packages:
  if not state['candidates'].get(p):raise ValueError('Kein Paketkandidat für '+p+'. Paketquellen und Paketlisten prüfen.')
 changes=simulate(action,state)
 stable={k:state[k] for k in ('kernel','cards','installed','candidates','module','loaded','dkms','secure_boot','key_enrolled','recommendation','run_installer')}
 return dict(action=action,kernel=state['kernel'],packages=package_args(action,state),changes=changes,fingerprint=hashlib.sha256(json.dumps(stable,sort_keys=True).encode()).hexdigest())

def execute(action,log,expected):
 state=status();current=plan(action,state)
 if expected!=current:raise ValueError('Treiber- oder Paketstand geändert. Neue Vorschau erforderlich.')
 def run(args):
  print('Befehl: '+' '.join(args),file=log,flush=True)
  subprocess.run(args,check=True,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,timeout=3600,env=dict(os.environ,LC_ALL='C',DEBIAN_FRONTEND='noninteractive',APT_LISTCHANGES_FRONTEND='none'))
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 cfg.atomic(ROOT/('before-'+str(time.time_ns())+'.json'),state)
 run(['apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'])
 if plan(action,status())!=expected:raise ValueError('Nach Aktualisierung der Paketlisten hat sich der Plan geändert. Neue Vorschau erforderlich; noch keine Treiberinstallation ausgeführt.')
 run(['apt-get','-o','DPkg::Lock::Timeout=60','-o','Dpkg::Options::=--force-confold','--no-remove','--yes']+(['--reinstall'] if action=='nvidia-repair' else [])+['install']+expected['packages'])
 if action!='nvidia-detect':
  final=status()
  if not all(final['installed'].get(p)==state['candidates'][p] for p in PACKAGES):raise ValueError('Installierte Paketversionen entsprechen nicht dem Plan.')
  expected_module=state['candidates']['nvidia-kernel-dkms'].split(':')[-1].rsplit('-',1)[0]
  if final['module']['version']!=expected_module or not any(line.startswith('nvidia-current/'+expected_module+', ') and ', '+state['kernel']+',' in line and ': installed' in line for line in final['dkms'].splitlines()):raise ValueError('DKMS-Modul in Zielversion für laufenden Kernel nicht bestätigt. Protokoll prüfen.')
  cfg.atomic(ROOT/'last-install.json',dict(boot_id=read('/proc/sys/kernel/random/boot_id'),finished=time.time()))
  print('Pakete und Kernelmodul installiert. Neustart separat planen. Keine automatische GPU- oder Display-Neustartaktion.',file=log)
 else:print('Hardwareprüfung installiert. NVIDIA-Seite erneut öffnen und Empfehlung prüfen.',file=log)
