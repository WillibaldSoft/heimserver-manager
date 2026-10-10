"""Filesystem operations run in a separate process with the bound Unix user's IDs."""
import json,os,shutil,sys,stat
from . import rootfd,scan,parent,fingerprint,mutate
from .scope import open_sub,browse
from .samba_acl import guard

def run(spec):
    with rootfd(spec['row']) as root:
        fd=open_sub(root,spec['sub'])
        try:
            action=spec['action']
            if action=='audit':return dict(checked=audit(fd))
            if action=='lease':return dict(ok=True)
            if action=='browse':return browse(fd,spec['row']['id'],spec['sub'],spec['write'])
            if action=='scan':return dict(files=scan(fd,exclude=spec['exclude']),max_file_bytes=None)
            if action=='get':
                with parent(fd,spec['path']) as (p,n):
                    if (fingerprint(p,n) or {}).get('sha')!=spec['sha']:raise FileExistsError('File changed; scan again')
                    with os.fdopen(os.open(n,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=p),'rb') as src:
                        guard(src.fileno())
                        from .dispatch import reserve
                        reserve(sys.stdout.fileno(),os.fstat(src.fileno()).st_size)
                        while True:
                            chunk=src.read(1024*1024)
                            if not chunk:break
                            reserve(sys.stdout.fileno(),len(chunk))
                            sys.stdout.buffer.write(chunk)
                return None
            if action in ('put','delete'):
                if not spec['write']:raise PermissionError('Read-only share')
                mutate(fd,spec['path'],spec['sha'],sys.stdin.buffer,spec['size'],action=='delete',spec.get('content_sha'),spec.get('file_mode',0o660),spec.get('directory_mode',0o750))
                return dict(ok=True,sha=spec.get('content_sha',''))
            raise ValueError('Unknown action')
        finally:os.close(fd)

def audit(fd,count=None):
    from . import mount_id
    count=[0] if count is None else count
    guard(fd)
    for name in sorted(os.listdir(fd)):
        if name.startswith('.hsm-'):continue
        count[0]+=1
        if count[0]>5000:raise ValueError('Audit limit reached; choose a smaller folder')
        st=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode)):continue
        child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            if mount_id(child)!=mount_id(fd):continue
            guard(child)
            if stat.S_ISDIR(st.st_mode):audit(child,count)
        finally:os.close(child)
    return count[0]

if __name__=='__main__':
    try:
        spec=json.loads(sys.stdin.buffer.readline(65537));result=run(spec)
        if result is not None:sys.stdout.write(json.dumps(result))
    except Exception as exc:
        sys.stderr.write(json.dumps(dict(error=str(exc),conflict=isinstance(exc,FileExistsError))))
        sys.exit(1)
