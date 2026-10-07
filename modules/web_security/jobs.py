"""Serialized systemd jobs survive HTTP requests and block automatic sleep."""
from pathlib import Path
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import uuid
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
    from modules.web_security import engine as e
else:from . import engine as e


def folder(key):
    if not re.fullmatch('[a-f0-9]{32}',key):raise e.Problem('Ungültiger Auftrag.')
    return e.ROOT/'jobs'/key

def load(key):
    value=json.loads((folder(key)/'status.json').read_text())
    if value['state'] not in e.TERMINAL and time.time()-value['created']>30:
        state=e.service('servermgr-web-security-'+key+'.service')
        if state not in ('active','activating','reloading'):
            value=dict(value,state='interrupted',message='Auftrag unterbrochen. Protokoll und Systemzustand vor erneutem Versuch prüfen.')
    return value

def active():
    pointer=e.ROOT/'active.json'
    if not pointer.exists():return None
    value=load(json.loads(pointer.read_text())['id'])
    return value if value['state'] not in e.TERMINAL else None

def start(plan):
    e.ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(e.ROOT/'lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if active():raise e.Problem('Ein Auftrag für Web & Sicherheit läuft bereits.')
        from modules.app_manager.install_jobs import active as app_install
        from modules.scanner.engine import active as scanner
        if app_install() or scanner():raise e.Problem('Bitte laufenden App-/Scanner-Auftrag abwarten.')
        key=uuid.uuid4().hex;path=folder(key);path.mkdir(parents=True,mode=0o700)
        value=dict(id=key,action=plan['action'],state='queued',created=time.time(),message='Auftrag wartet.')
        e.atomic(path/'plan.json',plan);e.atomic(path/'status.json',value);e.atomic(e.ROOT/'active.json',{'id':key})
        args=['systemd-run','--quiet','--collect','--unit=servermgr-web-security-'+key,'--property=Type=exec','--property=UMask=0077','--property=RuntimeMaxSec=1h']
        args+=['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE','SERVER_MANAGER_PORT') if k in os.environ]
        args+=['/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key]
        try:e.run(args)
        except (OSError,ValueError,subprocess.SubprocessError):
            e.atomic(path/'status.json',dict(value,state='failed',message='Auftrag konnte nicht gestartet werden.'))
            raise
        return key

def worker(key):
    path=folder(key);state=load(key)
    with open(path/'run.log','a',buffering=1) as log:
        os.chmod(log.name,0o600);os.dup2(log.fileno(),1);os.dup2(log.fileno(),2)
        e.atomic(path/'status.json',dict(state,state='running',message='Auftrag wird ausgeführt.'))
        try:
            p=json.loads((path/'plan.json').read_text())
            for step in p['steps']:print(step,flush=True)
            result=e.execute(p,path)
            e.atomic(path/'result.json',result)
            e.atomic(path/'status.json',dict(state,state='completed',message='Auftrag abgeschlossen. Ergebnis unten prüfen.',finished=time.time()))
        except Exception as exc:
            message=str(exc) if isinstance(exc,(ValueError,OSError,subprocess.SubprocessError)) else type(exc).__name__
            print('Fehler:',message,flush=True)
            e.atomic(path/'status.json',dict(state,state='failed',message=message,finished=time.time()))
            return 1
    return 0

def get_blockers(ctx=None):
    job=active()
    return [dict(source='web-security',type='web-security-job',title='Web & Sicherheit',reason=job['action'],priority=95,url='/web-security/jobs/'+job['id'])] if job else []

if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':raise SystemExit(2)
    raise SystemExit(worker(sys.argv[2]))
