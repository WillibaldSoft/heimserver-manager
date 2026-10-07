"""Official Qwen catalog and persistent local Ollama download jobs."""
import os
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from html.parser import HTMLParser
from urllib.request import Request, urlopen

ROOT = Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'qwen-models'))
OLLAMA = 'http://127.0.0.1:11434'
TERMINAL = {'completed', 'failed', 'interrupted'}
FAMILY = r'qwen[a-z0-9.-]{0,60}'
MODEL = FAMILY + r':[a-zA-Z0-9_.-]{1,80}'

class Invalid(ValueError):
    pass


def validate_model(name):
    if not re.fullmatch(MODEL, name) or any(s in name.split(':')[1].lower() for s in ('cloud', 'mlx', 'mxfp', 'nvfp')):
        raise Invalid('Bitte ein lokales Qwen-Modell aus der offiziellen Bibliothek wählen.')
    return name


def fetch(url, limit=4*1024*1024, accept="application/json"):
    with urlopen(Request(url, headers={'User-Agent': 'ServerManager-Qwen', 'Accept': accept}), timeout=15) as response:
        data = response.read(limit+1)
        if len(data) > limit:
            raise Invalid('Antwort des Modellkatalogs zu groß.')
        return data


def local_models():
    return json.loads(fetch(OLLAMA+'/api/tags')).get('models', [])


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.current = [dict(attrs).get('href', ''), []]
    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.links.append((self.current[0], ' '.join(self.current[1])))
            self.current = None


def families():
    parser = Links(); parser.feed(fetch('https://ollama.com/search?q=qwen', accept='text/html').decode())
    names = {href[len('/library/'):] for href, _ in parser.links if re.fullmatch('/library/'+FAMILY, href)}
    if not names:
        raise Invalid('Offizieller Qwen-Katalog derzeit nicht lesbar. Später erneut prüfen.')
    return sorted(names, key=lambda n: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', n)], reverse=True)


def parse_tags(source, family):
    parser = Links(); parser.feed(source)
    result = {}
    for href, text in parser.links:
        name = href.removeprefix('/library/')
        if not name.startswith(family+':'):
            continue
        try:
            validate_model(name)
        except Invalid:
            continue
        digest = re.search(r'\b([a-f0-9]{12,64})\b', text)
        size = re.search(r'\b([\d.]+)\s*(GB|MB|TB)\b', text)
        if not digest or not size:
            continue
        result[name] = dict(name=name, digest=digest[1], size=size[0], bytes=int(float(size[1])*{'MB':10**6,'GB':10**9,'TB':10**12}[size[2]]))
    if not result:
        raise Invalid('Keine lokal installierbaren Varianten gefunden; eventuell nur Cloud-Modelle oder geändertes Katalogformat.')
    return sorted(result.values(), key=lambda m: (m['bytes'], m['name']))


def catalog(family):
    if not re.fullmatch(FAMILY, family):
        raise Invalid('Ungültige Modellfamilie.')
    return parse_tags(fetch('https://ollama.com/library/'+family+'/tags', accept='text/html').decode(), family)


def manifest(name):
    validate_model(name)
    family, tag = name.split(':')
    raw = fetch('https://registry.ollama.ai/v2/library/'+family+'/manifests/'+tag)
    data = json.loads(raw)
    layers = data.get('layers', [])
    if not layers or not any(layer.get('mediaType') == 'application/vnd.ollama.image.model' for layer in layers):
        raise Invalid('Dieses Modell enthält keine lokal installierbaren Modellgewichte.')
    return {'digest':hashlib.sha256(raw).hexdigest(), 'bytes':sum(int(l.get('size',0)) for l in layers)}


def atomic(path, data):
    temp = path.with_suffix('.tmp')
    with open(temp, 'w') as out:
        os.chmod(temp, 0o600)
        json.dump(data, out, ensure_ascii=False)
    os.replace(temp, path)


def job_path(key):
    if not re.fullmatch('[a-f0-9]{32}', key):
        raise Invalid('Ungültiger Downloadauftrag.')
    return ROOT/key


def load(key):
    value = json.loads((job_path(key)/'status.json').read_text())
    if value['state'] not in TERMINAL and time.time()-value['created'] > 30:
        result = subprocess.run(['systemctl','is-active','servermgr-qwen-'+key+'.service'],capture_output=True,text=True,timeout=5)
        if result.stdout.strip() not in ('active','activating','reloading'):
            value.update(state='interrupted', message='Download wurde unterbrochen. Erneut installieren setzt vorhandene Downloads fort.')
    return value


def active():
    if not (ROOT/'active.json').exists():
        return None
    value = load(json.loads((ROOT/'active.json').read_text())['id'])
    return value if value['state'] not in TERMINAL else None


def recent():
    if not ROOT.exists():
        return []
    paths = sorted(ROOT.glob('*/status.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:8]
    return [load(p.parent.name) for p in paths]


def start(name):
    validate_model(name)
    local_models()  # No job if local Ollama is unreachable.
    remote = manifest(name)  # Reject missing tags and cloud-only manifests before queueing.
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(ROOT/'lock','a') as lock:
        os.chmod(lock.name,0o600)
        fcntl.flock(lock,fcntl.LOCK_EX)
        if active():
            raise Invalid('Ein Modelldownload läuft bereits. Bitte dessen Abschluss abwarten.')
        key = uuid.uuid4().hex
        folder = job_path(key);folder.mkdir(mode=0o700)
        state = dict(id=key,model=name,created=time.time(),state='queued',message='Download wird gestartet.',expected_digest=remote['digest'],model_bytes=remote['bytes'])
        atomic(folder/'status.json',state)
        atomic(ROOT/'active.json',{'id':key})
        try:
            result = subprocess.run(['systemd-run','--quiet','--collect','--unit=servermgr-qwen-'+key,'--property=Type=exec','--property=UMask=0077','--property=RuntimeMaxSec=24h',*['--setenv='+k+'='+os.environ[k] for k in ('SERVER_MANAGER_CONFIG','SERVER_MANAGER_STATE','SERVER_MANAGER_DB','SERVER_MANAGER_PORT') if k in os.environ],'/usr/bin/python3',str(Path(__file__).resolve()),'--worker',key],capture_output=True,text=True,timeout=20)
            if result.returncode:
                raise Invalid('Download-Dienst konnte nicht gestartet werden.')
        except (OSError,subprocess.TimeoutExpired,Invalid):
            atomic(folder/'status.json',dict(state,state='failed',message='Download-Dienst konnte nicht gestartet werden.'))
            raise Invalid('Download-Dienst konnte nicht gestartet werden.') from None
        return key


def remove(name, expected_digest):
    """Delete one confirmed installed tag, serialized with download startup."""
    if not re.fullmatch(MODEL, name):
        raise Invalid('Ungültiger Qwen-Modellname.')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(ROOT/'lock', 'a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if active():
            raise Invalid('Während eines Modelldownloads ist keine Deinstallation möglich.')
        current = next((m for m in local_models() if m.get('name') == name), None)
        if current is None:
            raise Invalid('Dieses Modell ist nicht mehr installiert. Bitte die Übersicht neu laden.')
        if not expected_digest or current.get('digest') != expected_digest:
            raise Invalid('Das Modell wurde inzwischen geändert. Bitte die Deinstallation erneut öffnen.')
        request = Request(OLLAMA+'/api/delete', method='DELETE',
                          data=json.dumps({'model': name}).encode(),
                          headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=60) as response:
            response.read(65536)
        if any(m.get('name') == name for m in local_models()):
            raise Invalid('Die Entfernung konnte nicht bestätigt werden. Bitte die Modellübersicht prüfen.')


def worker(key):
    path = job_path(key)/'status.json'
    state = json.loads(path.read_text());success = False;last_write = 0
    try:
        validate_model(state['model'])
        state.update(state='running',message='Ollama lädt das Modell.');atomic(path,state)
        request = Request(OLLAMA+'/api/pull',data=json.dumps({'model':state['model'],'stream':True}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request,timeout=180) as response:
            while True:
                line = response.readline(65537)
                if not line:
                    break
                if len(line)>65536:
                    raise Invalid('Ungültige Fortschrittsantwort.')
                data = json.loads(line)
                if data.get('error'):
                    raise Invalid(str(data['error'])[:600])
                status = str(data.get('status','Download läuft'))[:200]
                total = max(0,int(data.get('total',0)));completed=max(0,int(data.get('completed',0)))
                state.update(message=status,total=total,completed=completed,percent=min(100,round(100*completed/total,1)) if total else None)
                if status=='success':
                    success=True
                if time.monotonic()-last_write>1 or success:
                    atomic(path,state);last_write=time.monotonic()
        if not success:
            raise Invalid('Ollama hat den Download ohne Erfolgsmeldung beendet. Erneut versuchen.')
        found = next((m for m in local_models() if m.get('name')==state['model']),None)
        if not found:
            raise Invalid('Download gemeldet, Modell aber nicht in Ollama gefunden.')
        state.update(state='completed',message='Modell installiert. In Open WebUI die Modellauswahl neu laden.',digest=found.get('digest'),percent=100)
        if found.get('digest','').removeprefix('sha256:') != state['expected_digest']:
            state['message'] += ' Der veröffentlichte Tag hat sich seit dem Start geändert; Katalog erneut prüfen.'
    except Exception as exc:
        state.update(state='failed',message=str(exc)[:600] if isinstance(exc,Invalid) else 'Ollama-Download fehlgeschlagen ('+type(exc).__name__+'). Dienst/Verbindung prüfen und erneut versuchen.')
    state['finished']=time.time();atomic(path,state)
    return 0 if state['state']=='completed' else 1


def get_blockers(ctx=None):
    job = active()
    return [dict(source='Apps',type='qwen-download',title='Qwen-Modell wird installiert',reason=job['model'],priority=90,url='/apps/open_webui/models/jobs/'+job['id'])] if job else []


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--worker':
        raise SystemExit('Nur interner Worker-Aufruf unterstützt.')
    raise SystemExit(worker(sys.argv[2]))
