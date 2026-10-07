"""Fixed APT actions in persistent systemd jobs, independent of the web process."""
import fcntl,json,os,re,subprocess,sys,time,uuid
from pathlib import Path
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import server_settings as cfg
ROOT=cfg.STATE_DIR/'apt-jobs'
COMMANDS={
 'module-dependencies':['Modulabhängigkeiten installieren'],
 'nvidia-detect':['NVIDIA-Hardwareprüfung installieren'],
 'nvidia-install':['NVIDIA-Treiber installieren/aktualisieren'],
 'nvidia-repair':['NVIDIA-Treiber reparieren'],
 'dddvb-install':['dddvb installieren/aktualisieren'],
 'dddvb-install-native':['dddvb mit Kernel-dvb-core installieren/aktualisieren'],
 'dddvb-repair':['dddvb neu bauen'],
 'docker-start':['Docker starten'],
 'docker-install':['Docker Engine und Compose installieren'],
 'docker-remove':['Docker Engine und Compose entfernen'],
 'full-preview':['/usr/bin/apt-get','--simulate','dist-upgrade'],
 'full-upgrade':['/usr/bin/apt-get','-o','DPkg::Lock::Timeout=60','-o','Dpkg::Options::=--force-confold','--yes','dist-upgrade'],
 'update':['/usr/bin/apt-get','-o','APT::Update::Error-Mode=any','update'],
 'list':['/usr/bin/apt','list','--upgradable'],
 'upgrade':['/usr/bin/apt-get','-o','DPkg::Lock::Timeout=60','-o','Dpkg::Options::=--force-confold','--yes','--with-new-pkgs','upgrade'],
}
LABELS={'module-dependencies':'Manager-Modulabhängigkeiten','nvidia-detect':'NVIDIA · Hardwareprüfung','nvidia-install':'NVIDIA · Installation/Update','nvidia-repair':'NVIDIA · Reparatur','dddvb-install':'Digital Devices · Installation/Update','dddvb-install-native':'Digital Devices · Installation/Update (Kernel-dvb-core)','dddvb-repair':'Digital Devices · DKMS-Reparatur','docker-start':'Docker-Dienst starten','docker-install':'Docker Engine & Compose installieren','docker-remove':'Docker Engine & Compose deinstallieren','full-preview':'Full-Upgrade simulieren','full-upgrade':'Systempakete vollständig aktualisieren','update':'Paketlisten aktualisieren','list':'Verfügbare Updates anzeigen','upgrade':'Systempakete aktualisieren'}
TERMINAL={'completed','failed','interrupted'}
def folder(key):
 if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Ungültiger Auftrag.')
 return ROOT/key

def load(key):
 value=json.loads((folder(key)/'status.json').read_text())
 if value['state'] not in TERMINAL and time.time()-value['created']>30:
  result=subprocess.run(['/usr/bin/systemctl','is-active','server-manager-apt-'+key+'.service'],capture_output=True,text=True,timeout=10)
  if result.stdout.strip() not in ('active','activating','reloading'):value=dict(value,state='interrupted',message='Auftrag unterbrochen. Protokoll vor erneutem Start prüfen.')
 return value

def latest():
 try:return load(json.loads((ROOT/'latest.json').read_text())['id'])
 except FileNotFoundError:return None

def active():
 job=latest();return job if job and job['state'] not in TERMINAL else None

def start(action,parameters=None):
 if action not in COMMANDS:raise ValueError('Ungültige APT-Aktion.')
 ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
 with open(ROOT/'lock','a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if active():raise ValueError('Ein APT-Auftrag läuft bereits.')
  from modules.app_manager.install_jobs import active as installers
  from modules.web_security.jobs import active as web
  from modules.scanner.engine import active as scanner
  if installers() or web() or scanner():raise ValueError('Bitte laufende Installationsaufträge abwarten.')
  key=uuid.uuid4().hex;path=folder(key);path.mkdir(mode=0o700)
  value=dict(parameters=parameters,id=key,action=action,state='queued',created=time.time(),message='Auftrag wartet.')
  cfg.atomic(path/'status.json',value);cfg.atomic(ROOT/'latest.json',{'id':key})
  args=['systemd-run','--quiet','--collect','--unit=server-manager-apt-'+key,'--property=Type=exec','--property=UMask=0077']
  args+=['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE') if k in os.environ]
  args+=['/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key]
  try:subprocess.run(args,check=True,capture_output=True,text=True,timeout=15)
  except (OSError,subprocess.SubprocessError):
   cfg.atomic(path/'status.json',dict(value,state='failed',message='Hintergrundauftrag konnte nicht gestartet werden.'));raise
  return key

def refresh_for_update_checks(progress=None, timeout=1800):
 """Refresh once through the regular persistent APT job; never install packages."""
 key=start('update')
 if progress:progress(key)
 deadline=time.monotonic()+timeout
 while True:
  job=load(key)
  if job['state'] in TERMINAL:
   if job['state']=='completed' and job.get('returncode')==0 and job.get('action')=='update':return key
   raise ValueError('APT-Paketlisten konnten nicht aktualisiert werden. App-Prüfung abgebrochen; bisherige Ergebnisse sind nicht neu geprüft. APT-Protokoll öffnen.')
  if time.monotonic()>=deadline:
   raise ValueError('Zeitlimit beim Aktualisieren der APT-Paketlisten. App-Prüfung abgebrochen; den weiterlaufenden APT-Auftrag im Protokoll prüfen.')
  time.sleep(1)

def worker(key):
 path=folder(key);job=json.loads((path/'status.json').read_text());action=job['action']
 if action not in COMMANDS:raise ValueError('Ungültige Aktion.')
 cfg.atomic(path/'status.json',dict(job,state='running',message=LABELS[action]))
 try:
  with open(path/'run.log','w',buffering=1) as log:
   os.chmod(log.name,0o600);log.write('Befehl: '+' '.join(COMMANDS[action])+'\n')
   env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',APT_LISTCHANGES_FRONTEND='none',TERM='dumb')
   if action=='module-dependencies':
    from modules.first_start.config import packages
    requested=packages((job.get('parameters') or {}).get('modules'))
    if not requested:raise ValueError('Keine Modulabhängigkeiten gewählt.')
    subprocess.run(['/usr/bin/apt-get','-o','APT::Update::Error-Mode=any','update'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,check=True)
    result=subprocess.run(['/usr/bin/apt-get','-o','DPkg::Lock::Timeout=60','--yes','--no-install-recommends','install',*requested],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env)
   elif action.startswith('nvidia-'):
    from modules.app_manager.nvidia import execute
    execute(action,log,job.get('parameters'));result=subprocess.CompletedProcess([],0)
   elif action.startswith('dddvb-'):
    from modules.app_manager.dddvb import execute
    execute(action,log,job.get('parameters'));result=subprocess.CompletedProcess([],0)
   elif action in ('docker-install','docker-remove','docker-start'):
    from modules.app_manager.docker_setup import execute
    execute(action,log);result=subprocess.CompletedProcess([],0)
   else:
    result=subprocess.run(COMMANDS[action],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env)
  state='completed' if result.returncode==0 else 'failed'
  cfg.atomic(path/'status.json',dict(job,state=state,returncode=result.returncode,finished=time.time(),message='Abgeschlossen.' if state=='completed' else 'APT meldet einen Fehler; Protokoll prüfen.',reboot_required=Path('/var/run/reboot-required').exists() or action.startswith('dddvb-') or action in ('nvidia-install','nvidia-repair')))
  return result.returncode
 except Exception as exc:
  cfg.atomic(path/'status.json',dict(job,state='failed',finished=time.time(),message=str(exc)));return 1

def log_tail(key):
 try:
  with open(folder(key)/'run.log','rb') as stream:
   stream.seek(0,2);stream.seek(max(0,stream.tell()-100000));return stream.read().decode('utf-8',errors='replace')
 except FileNotFoundError:return 'Ausführung noch nicht gestartet.'

def get_blockers(ctx=None):
 job=active()
 return [dict(source='APT',type='apt-job',title=LABELS[job['action']],reason='Systempaketverwaltung läuft',priority=95,url='/apps/apt/jobs/'+job['id'])] if job else []
if __name__=='__main__':
 if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit(2)
 raise SystemExit(worker(sys.argv[2]))
