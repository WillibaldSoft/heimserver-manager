"""Fixed repair catalog; no arbitrary script paths or shell commands from requests."""
import hashlib,pwd,subprocess
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[2]/'tools/repair-scripts/fix-xrdp-xfce.sh'

def users():
    return [u for u in pwd.getpwall() if 1000<=u.pw_uid<60000 and not u.pw_shell.endswith(('nologin','false')) and Path(u.pw_dir).is_dir()]

def plan(username,xwrapper=False,tmp=False):
    try:u=pwd.getpwnam(username)
    except KeyError:raise ValueError('Lokaler Benutzer nicht gefunden.') from None
    if u not in users() or Path(u.pw_dir).is_symlink():raise ValueError('Normalen Desktop-Benutzer mit vorhandenem Homeverzeichnis auswählen.')
    return dict(script='xrdp-xfce',username=u.pw_name,uid=u.pw_uid,home=u.pw_dir,xwrapper=bool(xwrapper),tmp=bool(tmp),sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest())

def validate(value):
    if not isinstance(value,dict) or value.get('script')!='xrdp-xfce':raise ValueError('Ungültiges Reparaturskript.')
    current=plan(value.get('username',''),value.get('xwrapper',False),value.get('tmp',False))
    if current!=value:raise ValueError('Benutzer oder Skript seit Vorschau geändert; bitte erneut prüfen.')
    return current

def execute(value):
    value=validate(value)
    args=['/bin/sh',str(SCRIPT),value['username']]
    if value['xwrapper']:args.append('--xwrapper')
    if value['tmp']:args.append('--tmp')
    result=subprocess.run(args,timeout=3500)
    if result.returncode:raise ValueError('XRDP-Reparatur fehlgeschlagen. Protokoll und Sicherungen prüfen; Änderungen können teilweise erfolgt sein.')
