#!/usr/bin/env python3
"""Read-only security maintenance diagnostics, including pre-marker runs."""
import json,os,sys
from pathlib import Path

def batch_completed(state):
    if 'batch_check_completed' in state:return state['batch_check_completed'] is True
    # Legacy workers populated these fields only after a successful batch call
    # and parsed its output. A command-line log entry was not written then.
    fields=('pending_services','kernel_status','microcode_status','reboot_required')
    if all(key in state for key in fields) and isinstance(state['pending_services'],list):return True
    return None

def main():
    if os.geteuid()!=0:raise SystemExit('Bitte mit sudo ausführen / Run with sudo. Read-only / Nur lesend.')
    root=Path(__file__).resolve().parents[2]
    if not (root/'server_settings.py').exists():root=Path('/opt/server-manager')
    sys.path.insert(0,str(root))
    from modules.app_manager import security_updates as security,apt_jobs
    state=security.state();key=state.get('job')
    print('Sicherheitslauf / Security run:',json.dumps(state,ensure_ascii=False))
    if key:
        job=apt_jobs.load(key)
        print('APT:',json.dumps({k:job.get(k) for k in ['id','state','returncode','reboot_required','message']},ensure_ascii=False))
        log=apt_jobs.log_tail(key)
        print('Dienstneustart-Prüfung ausgeführt / Service restart check completed:',state.get('service_restart_check_completed') is True or any('needrestart -r a' in line for line in log.splitlines()))
        verified=batch_completed(state)
        print('Abschließende Batch-Prüfung ausgeführt / Final batch check completed:',verified if verified is not None else 'Nicht nachweisbar / Not verifiable')
        print('needrestart:',json.dumps([line for line in log.splitlines() if line.startswith('NEEDRESTART-')],ensure_ascii=False))
    print('APT-Schlafblocker / APT sleep blockers:',json.dumps(apt_jobs.get_blockers(),ensure_ascii=False))
    print('Nur gelesen. Kein Update, Neustart oder Versand ausgelöst. / Read only. No update, restart or notification triggered.')
if __name__=='__main__':main()
