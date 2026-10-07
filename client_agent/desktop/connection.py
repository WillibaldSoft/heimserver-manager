try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,os,socket,subprocess,urllib.request,urllib.parse,tempfile
from pathlib import Path
import core
PROFILE=Path.home()/'.config/server-manager-client/https.json'
def load():return json.loads(PROFILE.read_text()) if PROFILE.exists() else {}
def import_profile(path):
    data=json.loads(Path(path).read_text())
    https=data.get('https')
    if not https:
        PROFILE.unlink(missing_ok=True);return
    if https:
        from https_admin import validate
        validate(https['ca_pem'],https['sha256'],https['hostname'],https.get('ip',''))
        port=int(https['port'])
        if not 1<=port<=65535:raise core.Error(tr('Ungültiger HTTPS-Port.'))
        core.atomic(PROFILE,json.dumps(https))

def apply(data,action):
    from https_admin import validate
    validate(data['ca_pem'],data['sha256'],data['hostname'],data.get('ip',''))
    with tempfile.TemporaryDirectory(prefix='hsm-trust-') as tmp:
        p=Path(tmp)/'profile.json';p.write_text(json.dumps(data));p.chmod(0o600)
        r=subprocess.run(['pkexec','/usr/bin/python3',str(core.LIB/'https_admin.py'),action,str(p)],capture_output=True,text=True)
        if r.returncode:raise core.Error(r.stderr.strip() or tr('Administratorfreigabe abgebrochen.'))
    core.atomic(PROFILE,json.dumps(data))
    return tr('Lokales Zertifikatsvertrauen aktualisiert. Verbindung jetzt testen.')
def test(data):
    socket.getaddrinfo(data['hostname'],int(data['port']))
    url='https://'+data['hostname']+':'+str(int(data['port']))
    from backup import NoRedirect
    with urllib.request.build_opener(NoRedirect).open(url+'/api/health',timeout=10) as r:
        if r.status!=200:raise core.Error(tr('Manager nicht erreichbar.'))
    return url
