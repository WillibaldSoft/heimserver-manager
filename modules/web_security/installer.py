#!/usr/bin/env python3
"""Standalone Debian/Ubuntu installers. Default operation is read-only --check."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

COMPONENTS={
 'apache':{'label':'Apache','packages':['apache2'],'service':'apache2.service','binary':'apache2ctl'},
 'certbot':{'label':'Zertifikate / Certbot','packages':['certbot','python3-certbot-apache'],'service':'certbot.timer','binary':'certbot'},
 'fail2ban':{'label':'Fail2ban','packages':['fail2ban','python3-systemd','nftables'],'service':'fail2ban.service','binary':'fail2ban-client'},
}
class Problem(ValueError):pass

def command(args,timeout=30,check=True):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout,env={**os.environ,'LC_ALL':'C','DEBIAN_FRONTEND':'noninteractive'})
    if check and r.returncode:raise Problem((r.stderr or r.stdout or 'Befehl fehlgeschlagen')[-5000:])
    return r

def installed(package):
    r=command(['dpkg-query','-W','-f=${Status}',package],check=False)
    return r.returncode==0 and r.stdout.strip()=='install ok installed'

def plan(component):
    if component not in COMPONENTS:raise Problem('Unbekannte Komponente.')
    c=COMPONENTS[component];blocked=[]
    system=Path('/etc/os-release').read_text() if Path('/etc/os-release').exists() else ''
    if not shutil.which('apt-get') or not any(word in system.lower() for word in ('debian','ubuntu')):blocked.append('Dieser Installer unterstützt Debian und Ubuntu mit APT.')
    missing=[p for p in c['packages'] if not installed(p)] if shutil.which('dpkg-query') else list(c['packages'])
    if c['packages'][0] in missing and shutil.which(c['binary']):blocked.append('Vorhandene Installation außerhalb von APT erkannt; keine parallele Installation.')
    if component=='apache' and 'apache2' in missing:
        if not shutil.which('ss'):blocked.append('Portprüfung benötigt iproute2 (ss).')
        else:
            r=command(['ss','-H','-ltn','sport = :80 or sport = :443'],check=False)
            if r.returncode:blocked.append('Ports 80/443 konnten nicht geprüft werden.')
            elif r.stdout.strip():blocked.append('Port 80 oder 443 ist bereits belegt. Vorhandenen Webserver zuerst prüfen.')
    return dict(component=component,label=c['label'],missing=missing,blocked=blocked,service=c['service'],
                steps=(['Paketlisten aktualisieren','Fehlende Pakete installieren: '+', '.join(missing)] if missing else ['Pakete sind bereits installiert.'])+
                ['Konfiguration prüfen',c['service']+' aktivieren und starten'])

def install(component,expected=None):
    p=plan(component)
    if expected is not None and p!=expected:raise Problem('Installationsstand hat sich geändert. Vorschau neu erstellen.')
    if p['blocked']:raise Problem('; '.join(p['blocked']))
    if os.geteuid()!=0:raise Problem('Die Installation benötigt root / sudo.')
    if p['missing']:
        print('Paketlisten werden aktualisiert.',flush=True);command(['apt-get','update'],timeout=600)
        print('Fehlende Pakete werden installiert.',flush=True)
        command(['apt-get','-o','DPkg::Lock::Timeout=120','-o','Dpkg::Options::=--force-confdef','-o','Dpkg::Options::=--force-confold','install','-y','--no-remove','--no-upgrade',*p['missing']],timeout=1800)
    if component=='apache':command(['apache2ctl','configtest'])
    elif component=='fail2ban':command(['fail2ban-client','-t'])
    elif component=='certbot':command(['certbot','--version'])
    command(['systemctl','enable','--now',p['service']],timeout=120)
    command(['systemctl','is-active',p['service']])
    print(p['label']+' installiert und aktiv. Bestehende Konfigurationsdateien wurden vom Installer nicht ersetzt.',flush=True)
    return p

def main(default_component=None):
    parser=argparse.ArgumentParser(description='Server Manager · Web & Sicherheit Installer')
    if default_component is None:parser.add_argument('component',choices=COMPONENTS)
    parser.add_argument('--check',action='store_true');parser.add_argument('--install',action='store_true')
    args=parser.parse_args();component=default_component or args.component
    try:
        if args.install:install(component)
        else:print(json.dumps(plan(component),ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,subprocess.SubprocessError) as exc:print('Fehler:',str(exc));return 1

if __name__=='__main__':raise SystemExit(main())
