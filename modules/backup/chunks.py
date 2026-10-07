"""Per-account content-addressed ZIP snapshots. Immutable chunks, atomic manifests."""
import datetime,hashlib,json,os,re,shutil,uuid,time
from flask import request,jsonify,Response
MAX_CHUNK=4*1024**2
MAX_REFS=262144
FORMAT='client-cas-zip-v1'
def digest(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):raise ValueError('Ungültige Blockkennung.')
    return value

def objects(root,direct):
    p=direct(root/'.blocks');p.mkdir(mode=0o700,exist_ok=True);return p

def used(root):
    if (root/'.blocks').is_symlink():raise ValueError('Unsicherer Blockspeicher.')
    return sum(p.stat().st_size for p in root.glob('*/files.zip') if not p.is_symlink())+sum(p.stat().st_size for p in (root/'.blocks').glob('*') if not p.is_symlink() and p.is_file())

def block(root,key,direct):return direct(objects(root,direct)/digest(key))

def valid_manifest(m):
    refs=m.get('chunks')
    if m.get('format')!=FORMAT or not isinstance(refs,list) or not 0<len(refs)<=MAX_REFS:raise ValueError('Ungültiger Sicherungsstand.')
    total=0
    for row in refs:
        if not isinstance(row,dict) or type(row.get('bytes')) is not int or not 0<row['bytes']<=MAX_CHUNK:raise ValueError('Ungültiger Block.')
        digest(row.get('sha256'));total+=row['bytes']
    if total!=m.get('bytes'):raise ValueError('Größe des Sicherungsstands stimmt nicht.')
    digest(m.get('sha256'));return refs

def iterate(root,m,direct):
    total=hashlib.sha256()
    for row in valid_manifest(m):
        data=block(root,row['sha256'],direct).read_bytes()
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Sicherungsblock fehlt oder ist beschädigt.')
        total.update(data);yield data
    if total.hexdigest()!=m['sha256']:raise ValueError('Sicherungsstand beschädigt.')

def handle(root,action,quota,api):
    if request.method=='GET':
        if action=='block-has':
            if request.args.get('id'):
                folder=api.direct(root/('.upload-'+api.identifier(request.args['id'])))
                if not folder.is_dir():raise ValueError('Sicherungsauftrag nicht mehr aktiv.')
                os.utime(folder,None)
            key=digest(request.args.get('hash'));p=block(root,key,api.direct)
            if not p.exists():return jsonify(present=False)
            data=p.read_bytes()
            if hashlib.sha256(data).hexdigest()!=key:raise ValueError('Gespeicherter Block beschädigt; Administrator kontaktieren.')
            return jsonify(present=True,bytes=len(data))
        raise ValueError('Unbekannte Blockaktion.')
    with api.locked(root):
        if action=='cas-begin':
            for old in root.glob('.upload-*'):
                if not old.is_symlink() and time.time()-old.stat().st_mtime>86400:shutil.rmtree(old)
            if list(root.glob('.upload-*')):raise ValueError('Unvollständige Übertragung vorhanden. Zuerst im Client verwerfen oder abschließen.')
            if len(api.listing(root))>=500:raise ValueError('Maximal 500 Sicherungsstände erreicht.')
            sid=uuid.uuid4().hex;folder=root/('.upload-'+sid);folder.mkdir(mode=0o700)
            data=request.get_json() or {}
            api.save(folder/'manifest.json',dict(id=sid,format=FORMAT,created=datetime.datetime.now().astimezone().isoformat(),name=str(data.get('name','Linux-System'))[:120]))
            return jsonify(id=sid)
        sid=api.identifier(request.args.get('id'));folder=api.direct(root/('.upload-'+sid))
        m=json.loads(api.direct(folder/'manifest.json').read_text())
        if m.get('format')!=FORMAT:raise ValueError('Kein inkrementeller Auftrag.')
        os.utime(folder,None)
        if action=='block-put':
            key=digest(request.args.get('hash'));data=request.stream.read(MAX_CHUNK+1)
            if not 0<len(data)<=MAX_CHUNK or hashlib.sha256(data).hexdigest()!=key:raise ValueError('Blockprüfsumme stimmt nicht.')
            p=block(root,key,api.direct)
            if p.exists():
                if p.read_bytes()!=data:raise ValueError('Block beschädigt.')
                return jsonify(ok=True,stored=False)
            if used(root)+len(data)>quota:raise ValueError('Sicherungslimit erreicht (inklusive gemeinsam verwendeter Blöcke).')
            if shutil.disk_usage(root).free<len(data)+api.RESERVE:raise ValueError('Speicherreserve am Server erreicht.')
            temp=objects(root,api.direct)/('.'+uuid.uuid4().hex)
            try:
                with temp.open('xb') as f:os.chmod(temp,0o600);f.write(data);f.flush();os.fsync(f.fileno())
                os.replace(temp,p)
            finally:temp.unlink(missing_ok=True)
            return jsonify(ok=True,stored=True)
        if action=='cas-finish':
            data=request.get_json();m.update(chunks=data.get('chunks'),bytes=data.get('bytes'),sha256=data.get('sha256'),scope='linux-system-tar-v2')
            valid_manifest(m)
            first=True
            for chunk in iterate(root,m,api.direct):
                if first and not chunk.startswith(b'PK\x03\x04'):raise ValueError('Kein ZIP-Sicherungsstrom.')
                first=False
            api.save(folder/'manifest.json',m);folder.rename(root/sid)
            return jsonify(ok=True,id=sid)
        raise ValueError('Unbekannte Blockaktion.')

def download(root,m,api):
    valid_manifest(m)
    # Validate existence before HTTP headers; each block is hashed during transfer.
    for row in m['chunks']:
        if block(root,row['sha256'],api.direct).stat().st_size!=row['bytes']:raise ValueError('Sicherungsblock unvollständig.')
    response=Response(iterate(root,m,api.direct),mimetype='application/zip')
    response.headers['Content-Length']=str(m['bytes'])
    response.headers['Content-Disposition']='attachment; filename=Client-'+api.identifier(m['id'])+'.zip'
    response.headers['X-Backup-SHA256']=m['sha256'];return response

def collect_unused(root,api):
    """Caller holds root lock; no unfinished snapshot may lose its uploaded blocks."""
    if list(root.glob('.upload-*')):return 0
    keep=set()
    for path in root.glob('*/manifest.json'):
        if path.parent.name.startswith('.'):continue
        m=json.loads(api.direct(path).read_text())
        if m.get('format')==FORMAT:keep.update(row['sha256'] for row in valid_manifest(m))
    removed=0
    for p in objects(root,api.direct).iterdir():
        if p.name not in keep and re.fullmatch('[a-f0-9]{64}',p.name):api.direct(p).unlink();removed+=1
    return removed
