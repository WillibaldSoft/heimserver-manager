"""Opt-in security-only APT maintenance, serialized with ordinary APT jobs."""
import json,os,re,shutil,subprocess,tempfile,time
from pathlib import Path
import server_settings as cfg
CONFIG=cfg.CONFIG_DIR/'security-updates.json'
STATE=cfg.STATE_DIR/'security-updates.json'
UNIT='server-manager-security-updates'
UNIT_DIR=Path('/etc/systemd/system')

def settings():
 try:value=json.loads(CONFIG.read_text())
 except FileNotFoundError:return {'enabled':False}
 if not isinstance(value,dict) or type(value.get('enabled')) is not bool:raise ValueError('Invalid security update settings')
 return value

def state():
 try:value=json.loads(STATE.read_text())
 except FileNotFoundError:return {}
 if value.get('state') in ('queued','running') and value.get('job'):
  from . import apt_jobs
  job=apt_jobs.load(value['job'])
  if job['state'] in apt_jobs.TERMINAL:value.update(state='failed' if job['state']!='completed' else 'completed',message=job.get('message',''))
 return value

def origins(release=None):
 if release is None:
  import platform
  release=platform.freedesktop_os_release()
 distro=release.get('ID');code=release.get('VERSION_CODENAME','')
 if distro=='linuxmint':distro='ubuntu';code=release.get('UBUNTU_CODENAME','')
 if not re.fullmatch('[a-z][a-z0-9-]*',code):raise ValueError('Unsupported distribution codename')
 if distro=='debian':return ['origin=Debian,codename='+code+'-security,label=Debian-Security']
 if distro=='ubuntu':return ['origin=Ubuntu,archive='+code+'-security']
 raise ValueError('Only Debian and Ubuntu security repositories are supported (Mint: Ubuntu base).')

def prerequisites():
 origins()
 return [name for name in ('unattended-upgrade','needrestart') if not shutil.which(name)]

def configure(enabled):
 if type(enabled) is not bool:raise ValueError('Invalid enabled flag')
 if enabled and prerequisites():raise ValueError('Install unattended-upgrades and needrestart first.')
 if enabled:
  # Fixed command and schedule; no web-supplied shell or systemd syntax.
  service='''[Unit]
Description=Heimserver Manager security maintenance dispatcher
After=network-online.target
[Service]
Type=oneshot
UMask=0077
ExecStart=/usr/bin/python3 -m modules.app_manager.security_updates
WorkingDirectory=/opt/server-manager
'''
  timer='''[Unit]
Description=Heimserver Manager security updates every two hours
[Timer]
OnCalendar=*-*-* 00/2:00:00
Persistent=true
RandomizedDelaySec=300
WakeSystem=false
Unit=server-manager-security-updates.service
[Install]
WantedBy=timers.target
'''
  for suffix,content in [('service',service),('timer',timer)]:
   p=UNIT_DIR/(UNIT+'.'+suffix)
   if p.is_symlink():raise ValueError('Unexpected systemd unit symlink')
   p.write_text(content);p.chmod(0o644)
  subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
  # Save before enabling: a missed timer is allowed to start immediately.
  cfg.atomic(CONFIG,{'enabled':True,'restart_services':True,'reboot':False})
  try:subprocess.run(['systemctl','enable','--now',UNIT+'.timer'],check=True,timeout=30)
  except Exception:
   cfg.atomic(CONFIG,{'enabled':False});raise
 else:
  cfg.atomic(CONFIG,{'enabled':False})
  subprocess.run(['systemctl','disable','--now',UNIT+'.timer'],check=True,timeout=30)

def busy():
 from modules.backup.central import get_blockers,status as central_state
 from modules.backup.daily import state as daily_state
 if central_state().get('state') in ('queued','running') or daily_state().get('state')=='running':return 'Server backup active'
 if get_blockers():return 'Backup active'
 from modules.app_manager.plugin import get_active_job
 if get_active_job():return 'Application maintenance active'
 result=subprocess.run(['systemctl','list-units','--type=service','--state=running,activating','--no-legend','--plain','server-manager-appbackup-*'],capture_output=True,text=True,check=True,timeout=10)
 return 'Scheduled backup active' if result.stdout.strip() else ''

def tick():
 if not settings()['enabled']:return
 from . import apt_jobs
 try:
  reason=busy()
  if reason:raise ValueError(reason)
  key=apt_jobs.start('security-update')
  cfg.atomic(STATE,{'checked_at':time.time(),'state':'queued','job':key})
 except Exception as exc:
  cfg.atomic(STATE,{'checked_at':time.time(),'state':'deferred','message':str(exc)})

def apt_config(dump,allowed):
 # Snapshot existing administrator options/blacklists, then force security-only
 # origins and prevent config.d from broadening these private per-run overrides.
 return dump+'\n'+'''Dir::Etc::Parts "-";
Dir::Etc::main "-";
#clear Unattended-Upgrade::Allowed-Origins;
#clear Unattended-Upgrade::Origins-Pattern;
Unattended-Upgrade::Origins-Pattern {\n'''+''.join('"'+o+'";\n' for o in allowed)+'''};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Dependencies "false";
Unattended-Upgrade::Remove-New-Unused-Dependencies "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "false";
Unattended-Upgrade::Allow-downgrade "false";
Unattended-Upgrade::Allow-APT-Mark-Fallback "false";
APT::Get::AllowUnauthenticated "false";
Acquire::AllowInsecureRepositories "false";
Acquire::AllowDowngradeToInsecureRepositories "false";
Dpkg::Options { "--force-confold"; };
DPkg::Lock::Timeout "60";
'''

def restart_status(text):
 if not any(line.startswith('NEEDRESTART-') for line in text.splitlines()):raise ValueError('needrestart did not return a verifiable batch result')
 services=[];kernel=None;microcode=None
 for line in text.splitlines():
  key,sep,value=line.partition(':');value=value.strip()
  if key=='NEEDRESTART-SVC' and value not in services:services.append(value)
  elif key=='NEEDRESTART-KSTA':kernel=value
  elif key=='NEEDRESTART-UCSTA':microcode=value
 return {'pending_services':services,'kernel_status':kernel,'microcode_status':microcode,
         'reboot_required':Path('/run/reboot-required').exists() or kernel in ('2','3') or microcode in ('2','3')}

def pending_security():
 import apt,apt_pkg
 allowed=[dict(part.split('=',1) for part in rule.split(',')) for rule in origins()]
 pending=[]
 for package in apt.Cache():
  if not package.is_installed:continue
  for version in package.versions:
   if apt_pkg.version_compare(version.version,package.installed.version)<=0:continue
   if any(all(getattr(origin,key,'')==value for key,value in rule.items()) for origin in version.origins for rule in allowed):
    pending.append(package.name);break
 return sorted(pending)

def installed_versions():
 output=subprocess.run(['/usr/bin/dpkg-query','-W','-f=${binary:Package}\t${Version}\n'],capture_output=True,text=True,check=True,timeout=60).stdout
 return dict(line.split('\t',1) for line in output.splitlines() if '\t' in line)

def execute(log,job_id):
 result={'checked_at':time.time(),'state':'running','job':job_id}
 cfg.atomic(STATE,result)
 env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',APT_LISTCHANGES_FRONTEND='none',NEEDRESTART_SUSPEND='1',NEEDRESTART_MODE='l')
 def run(args,**kw):
  log.write('Command: '+' '.join(args)+'\n');log.flush()
  return subprocess.run(args,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,check=True,**kw)
 try:
  if prerequisites():raise ValueError('Security maintenance dependencies are missing')
  reason=busy()
  if reason:raise ValueError(reason)
  before=installed_versions()
  run(['/usr/bin/apt-get','-o','DPkg::Lock::Timeout=60','-o','APT::Update::Error-Mode=any','update'],timeout=1800)
  dump=subprocess.run(['/usr/bin/apt-config','dump'],capture_output=True,text=True,check=True,timeout=30).stdout
  with tempfile.TemporaryDirectory(prefix='hsm-security-') as temp:
   policy=Path(temp)/'apt.conf';policy.write_text(apt_config(dump,origins()));policy.chmod(0o600)
   env['APT_CONFIG']=str(policy)
   run([shutil.which('unattended-upgrade'),'--verbose'])
   del env['APT_CONFIG']
  after=installed_versions()
  result['updated_packages']=sorted(name for name,version in after.items() if before.get(name)!=version)
  # Batch mode never restarts. Use automatic mode first, then batch verification.
  env.pop('NEEDRESTART_SUSPEND',None);env['NEEDRESTART_MODE']='a'
  run([shutil.which('needrestart'),'-r','a'],timeout=1800)
  result['service_restart_check_completed']=True
  log.write('Command: '+shutil.which('needrestart')+' -b -r l\n');log.flush()
  check=subprocess.run([shutil.which('needrestart'),'-b','-r','l'],stdin=subprocess.DEVNULL,capture_output=True,text=True,env=env,timeout=600,check=True)
  log.write(check.stdout+check.stderr);result.update(restart_status(check.stdout))
  result['batch_check_completed']=True
  result['pending_security_packages']=pending_security()
  result.update(state='attention' if result['pending_services'] or result['reboot_required'] or result['pending_security_packages'] else 'completed',finished=time.time())
  cfg.atomic(STATE,result)
  return result
 except Exception as exc:
  result.update(state='failed',finished=time.time(),message=str(exc));cfg.atomic(STATE,result);raise
 finally:
  from .security_notify import send
  result['notification']=send(result);cfg.atomic(STATE,result)

if __name__=='__main__':tick()
