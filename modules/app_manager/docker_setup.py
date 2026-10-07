"""Explicit Docker package operations; never remove container data."""
import os,subprocess,json
from pathlib import Path
PACKAGES=('docker.io','docker-ce','docker-ce-cli','docker-compose','docker-compose-v2','docker-compose-plugin','docker-buildx-plugin','docker-buildx','docker-ce-rootless-extras')
def run(args):
 r=subprocess.run(args,capture_output=True,text=True,timeout=120,env=dict(os.environ,LC_ALL='C'))
 if r.returncode:raise ValueError('Befehl fehlgeschlagen: '+args[0]+': '+r.stderr[-1500:])
 return r.stdout.strip()
def installed():
 return [p for p in PACKAGES if subprocess.run(['dpkg-query','-W','-f=${db:Status-Status}',p],capture_output=True,text=True,timeout=15).stdout.strip()=='installed']
def docker(*args):return run(['docker','--host','unix:///var/run/docker.sock',*args])
def status():
 pkgs=installed();engine=any(p in pkgs for p in ('docker.io','docker-ce'))
 try:docker('info','--format','{{.ServerVersion}}');ready=True
 except (ValueError,OSError,subprocess.SubprocessError):ready=False
 try:docker('compose','version');compose=True
 except (ValueError,OSError,subprocess.SubprocessError):compose=False
 service=subprocess.run(['systemctl','show','docker.service','-p','LoadState','-p','ActiveState'],capture_output=True,text=True,timeout=15)
 props=dict(line.split('=',1) for line in service.stdout.splitlines() if '=' in line)
 if engine and ready and compose:action='complete'
 elif engine and ready:action='compose'
 elif engine and props.get('LoadState')=='loaded' and props.get('ActiveState')=='inactive':action='start'
 elif not pkgs and props.get('LoadState')=='not-found' and not ready and not __import__('shutil').which('docker'):action='install'
 else:action='diagnose'
 return dict(packages=pkgs,engine=engine,ready=ready,compose=compose,action=action,service=props.get('ActiveState','unknown'))

def install_packages(pkgs):
 if 'docker-ce' in pkgs:return ['docker-compose-plugin']
 if 'docker-ce-cli' in pkgs:raise ValueError('Unvollständige Docker-CE-Installation: zuerst vorhandene Paketquelle prüfen.')
 info={}
 for line in Path('/etc/os-release').read_text().splitlines():
  if '=' in line:
   k,v=line.split('=',1);info[k]=v.strip('"')
 if info.get('ID')=='debian' and info.get('VERSION_ID')=='13':return ['docker.io','docker-compose']
 if info.get('ID')=='linuxmint' and info.get('UBUNTU_CODENAME')=='noble':return ['docker.io','docker-compose-v2']
 if info.get('ID')=='ubuntu' and info.get('VERSION_ID') in ('24.04','26.04'):return ['docker.io','docker-compose-v2']
 raise ValueError('Automatische Neuinstallation unterstützt Debian 13, Linux Mint 22 und Ubuntu 24.04/26.04. Andere Systeme manuell einrichten.')
def removal_packages():
 pkgs=installed()
 if not any(p in pkgs for p in ('docker.io','docker-ce')):raise ValueError('Keine unterstützte Docker-Engine-Paketinstallation erkannt.')
 if docker('ps','-aq'):raise ValueError('Deinstallation gesperrt: Container vorhanden, auch gestoppte. Zuerst die Container-Apps verwalten.')
 if docker('info','--format','{{.Swarm.LocalNodeState}}')!='inactive':raise ValueError('Deinstallation gesperrt: Docker-Swarm ist aktiv.')
 return pkgs
def execute(action,log):
 env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',LC_ALL='C')
 def apt(args):
  command=['apt-get','-o','DPkg::Lock::Timeout=60','-o','Dpkg::Options::=--force-confold',*args]
  print('Befehl: '+' '.join(command),file=log,flush=True)
  subprocess.run(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,check=True)
 if action=='docker-start':
  if status()['action']!='start':raise ValueError('Dienstzustand hat sich geändert. Seite neu laden.')
  run(['systemctl','start','docker.service']);docker('info');return
 if action=='docker-install':
  current=status()
  if current['action'] not in ('install','compose'):raise ValueError('Installation in diesem Zustand nicht erforderlich oder nicht sicher prüfbar. Seite neu laden.')
  packages=install_packages(installed())
  if current['action']=='compose':packages=[p for p in packages if p!='docker.io']
  apt(['-o','APT::Update::Error-Mode=any','update'])
  apt(['--no-remove','--yes','install',*packages])
  run(['systemctl','enable','--now','docker.service'])
  docker('info');docker('compose','version')
 elif action=='docker-remove':
  packages=removal_packages()
  preview=run(['apt-get','--simulate','--no-auto-remove','remove',*packages])
  removals={line.split()[1].split(':')[0] for line in preview.splitlines() if line.startswith('Remv ')}
  if not removals or removals-set(packages):raise ValueError('Weitere abhängige Pakete würden entfernt. Automatische Deinstallation gesperrt.')
  removal_packages()
  apt(['--no-auto-remove','--yes','remove',*packages])
 else:raise ValueError('Unbekannte Docker-Aktion.')
 print('Abgeschlossen. Docker-Daten und Konfiguration wurden nicht gelöscht.',file=log,flush=True)
