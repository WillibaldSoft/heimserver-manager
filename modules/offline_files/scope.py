import base64,os,stat
from . import parts,mount_id
from .samba_acl import guard

def split(gid):
    base,sep,encoded=gid.partition('.')
    if not sep:return base,''
    try:sub=base64.urlsafe_b64decode(encoded.encode()+b'='*((-len(encoded))%4)).decode('utf-8')
    except Exception:raise ValueError('Invalid subfolder selection')
    parts(sub)
    if make(base,sub)!=gid:raise ValueError('Invalid subfolder selection')
    return base,sub

def make(base,sub):
    return base+'.'+base64.urlsafe_b64encode(sub.encode()).decode().rstrip('=') if sub else base

def open_sub(fd,sub):
    result=os.dup(fd);dev=mount_id(fd)
    try:
        for name in parts(sub) if sub else []:
            other=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=result);os.close(result);result=other
            if mount_id(result)!=dev:raise ValueError('Nested mounts must be granted separately')
            guard(result)
        guard(result)
        return result
    except Exception:os.close(result);raise

def browse(fd,base,sub,write):
    rows=[]
    for name in sorted(os.listdir(fd)):
        if name.startswith('.hsm-'):continue
        try:
            parts(name);s=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if not stat.S_ISDIR(s.st_mode):continue
            child=open_sub(fd,name)
            try:os.listdir(child)
            finally:os.close(child)
        except (OSError,ValueError):continue
        rel=(sub+'/' if sub else '')+name
        rows.append(dict(id=make(base,rel),name=name,write=write))
        if len(rows)>1000:raise ValueError('Too many subfolders; narrow the server grant')
    return dict(folders=rows,parent=make(base,sub.rpartition('/')[0]) if sub else '',current=make(base,sub),current_name=sub)
