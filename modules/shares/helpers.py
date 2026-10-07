import os
# -*- coding: utf-8 -*-
import os, re, html, json, subprocess, shutil
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
SMB_CONF = Path('/etc/samba/smb.conf')
SMB_SHARES_DIR = Path('/etc/samba/shares.d')
NFS_EXPORTS = Path('/etc/exports')
CLIENT_SCRIPT = BASE / 'tools/client-scripts/client-mount-manager-v2.3.4.sh'
HELPER = BASE / 'tools/helpers/server-manager-shares-helper'
BACKUP_DIR = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'backups/shares'))

RIGHT_LABELS = {
    'none': 'Kein Zugriff',
    'read': 'Nur Lesen',
    'write': 'Lesen/Schreiben',
    'admin': 'Vollzugriff/Admin',
}
RIGHT_HELP = {
    'none': 'Kein Samba-Zugriff; ACL-Eintrag wird entfernt.',
    'read': 'Darf Dateien sehen und öffnen, aber nicht ändern.',
    'write': 'Darf Dateien erstellen, ändern und löschen.',
    'admin': 'Wie Schreiben, zusätzlich Samba-Adminrechte für diese Freigabe.',
}

def esc(x):
    return html.escape(str(x or ''))

def safe_name(name):
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', str(name or '').strip()).strip('_')
    return s or 'share'

def run(cmd, timeout=30, input_text=None):
    try:
        p = subprocess.run(cmd, text=True, input=input_text, capture_output=True, timeout=timeout)
        return {'ok': p.returncode == 0, 'rc': p.returncode, 'out': p.stdout or '', 'err': p.stderr or '', 'cmd': cmd}
    except Exception as e:
        return {'ok': False, 'rc': 999, 'out': '', 'err': str(e), 'cmd': cmd}

def sudo_run(cmd, password='', timeout=30):
    if os.geteuid() == 0:
        return run(cmd, timeout=timeout)
    if password:
        return run(['sudo','-S','-p',''] + list(cmd), timeout=timeout, input_text=str(password)+'\n')
    return run(['sudo','-n'] + list(cmd), timeout=timeout)

def service_state(name):
    r = run(['systemctl','is-active',name], timeout=8)
    return (r['out'] or r['err'] or 'unknown').strip()

def backup_file(path):
    p = Path(path)
    if not p.exists():
        return ''
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    import datetime
    dst = BACKUP_DIR / (p.name + '.' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.bak')
    try:
        shutil.copy2(str(p), str(dst))
        return str(dst)
    except Exception:
        return ''

def json_response(ctx, data, code=200):
    return ctx.Response(json.dumps(data, ensure_ascii=False, indent=2), status=code, mimetype='application/json')

def is_path_safe(path):
    p = str(path or '').strip()
    if not p.startswith('/'):
        return False
    bad = ['/etc', '/bin', '/sbin', '/usr', '/lib', '/lib64', '/boot', '/proc', '/sys', '/dev', '/run']
    return not any(p == b or p.startswith(b + '/') for b in bad)

def sudo_input(cmd,text,password='',timeout=30):
    """Keep account passwords out of argv and shell command text."""
    if os.geteuid()==0:return run(cmd,timeout=timeout,input_text=text)
    if password:
        auth=run(['sudo','-S','-p','','-v'],timeout=15,input_text=password+'\n')
        if not auth['ok']:return auth
    return run(['sudo','-n',*cmd],timeout=timeout,input_text=text)
