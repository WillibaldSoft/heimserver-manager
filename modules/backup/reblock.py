"""Re-index immutable snapshot bytes with the desktop content-defined boundaries."""
import hashlib,json,re,shutil,tempfile,os
from . import chunks
ANCHOR=re.compile(b'\x13\x37[\x00-\x1f]')
def pieces(source):
    buf=bytearray()
    for data in source:
        view=memoryview(data)
        while view:
            n=min(chunks.MAX_CHUNK-len(buf),len(view));buf.extend(view[:n]);view=view[n:]
            while len(buf)>=1024**2:
                match=ANCHOR.search(buf,1024**2-3)
                if not match and len(buf)<chunks.MAX_CHUNK:break
                size=match.end() if match else len(buf)
                yield bytes(buf[:size]);del buf[:size]
    if buf:yield bytes(buf)

def migrate(root,sid,api):
    """Caller runs during maintenance. Never changes the restored archive bytes."""
    with api.locked(root):
        if list(root.glob('.upload-*')):raise ValueError('Unfinished upload exists; finish or cancel it first.')
        folder=api.direct(root/api.identifier(sid));path=api.direct(folder/'manifest.json')
        m=json.loads(path.read_text())
        if m.get('format')!=chunks.FORMAT:raise ValueError('Snapshot is not a block archive.')
        if m.get('chunking')=='content-defined-v1':return dict(changed=False,id=sid)
        refs=[];total=0;digest=hashlib.sha256();added=0
        for data in pieces(chunks.iterate(root,m,api.direct)):
            key=hashlib.sha256(data).hexdigest();p=chunks.block(root,key,api.direct)
            if p.exists():
                if p.read_bytes()!=data:raise ValueError('Corrupt existing block')
            else:
                if shutil.disk_usage(root).free<len(data)+api.RESERVE:raise ValueError('Insufficient free space for safe re-indexing')
                fd,temp=tempfile.mkstemp(dir=p.parent,prefix='.reblock-')
                try:
                    with os.fdopen(fd,'wb') as f:
                        f.write(data);f.flush();os.fsync(f.fileno())
                    os.replace(temp,p)
                finally:
                    if os.path.exists(temp):os.unlink(temp)
                added+=len(data)
            digest.update(data);total+=len(data);refs.append(dict(sha256=key,bytes=len(data)))
        if total!=m['bytes'] or digest.hexdigest()!=m['sha256']:raise ValueError('Archive verification failed')
        updated=dict(m,chunks=refs,chunking='content-defined-v1');chunks.valid_manifest(updated)
        # Atomic manifest replacement; old blocks remain until explicit cleanup.
        api.save(path,updated)
        return dict(changed=True,id=sid,bytes=total,new_block_bytes=added,blocks=len(refs))
