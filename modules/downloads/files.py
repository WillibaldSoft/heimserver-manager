import os
import stat
import threading
from pathlib import Path
import server_settings as cfg

_lock=threading.Lock()
_active=0
class Invalid(ValueError):pass

def parts(value):
    if not isinstance(value,str) or value.startswith('/') or '\\' in value:raise Invalid('Ungültiger relativer Pfad.')
    result=value.split('/') if value else []
    if any(not p or p.startswith('.') or any(ord(c)<32 or ord(c)==127 for c in p) for p in result):raise Invalid('Versteckte Dateien und übergeordnete Pfade sind nicht freigegeben.')
    return result

def open_path(value='',directory=False):
    relative=parts(value)
    root=Path(cfg.get('download_root'))
    cfg.path_value(str(root))
    chain=list(root.parts[1:])+relative
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        for i,name in enumerate(chain):
            flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK
            if i<len(chain)-1 or directory:flags|=os.O_DIRECTORY
            new=os.open(name,flags,dir_fd=fd);os.close(fd);fd=new
        info=os.fstat(fd)
        if directory:
            if not stat.S_ISDIR(info.st_mode):raise Invalid('Kein Ordner.')
        elif not relative or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise Invalid('Nur reguläre Dateien ohne Hardlinks können heruntergeladen werden.')
        return fd,info
    except BaseException:
        os.close(fd);raise

def entries(value,query='',page=1):
    fd,_=open_path(value,directory=True)
    try:
        rows=[];count=0
        with os.scandir(fd) as stream:
            for entry in stream:
                count+=1
                if count>50000:raise Invalid('Dieser Ordner enthält zu viele Einträge. Bitte kleinere Unterordner verwenden.')
                try:
                    parts(entry.name)
                    info=entry.stat(follow_symlinks=False)
                    directory=stat.S_ISDIR(info.st_mode)
                    if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1):continue
                    if query.casefold() not in entry.name.casefold():continue
                    rows.append(dict(name=entry.name,directory=directory,size=info.st_size,modified=info.st_mtime))
                except (OSError,ValueError):continue
        rows.sort(key=lambda row:(not row['directory'],row['name'].casefold(),row['name']))
        pages=max(1,(len(rows)+99)//100);page=min(max(1,page),pages)
        return rows[(page-1)*100:page*100],page,pages,len(rows)
    finally:os.close(fd)

def track():
    global _active
    with _lock:_active+=1
    done=False
    def finish():
        nonlocal done
        global _active
        with _lock:
            if not done:_active-=1;done=True
    return finish

def get_blockers(ctx=None):
    with _lock:count=_active
    return [dict(source='Downloads',type='download',title='Dateidownload aktiv',reason=str(count)+' laufende Übertragungen',priority=90,url='/downloads')] if count else []


UPLOAD_LIMIT=512*1024**2

def upload(stream,name):
    """Publish a complete new file using a directory fd; never overwrite."""
    import secrets
    if len(parts(name))!=1 or len(name.encode('utf-8'))>240:
        raise Invalid('Bitte einen einfachen Dateinamen mit höchstens 240 Bytes verwenden.')
    fd,info=open_path('',directory=True)
    temp='.upload-'+secrets.token_hex(16);created=False
    try:
        out=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd);created=True
        with os.fdopen(out,'wb') as target:
            count=0
            while True:
                chunk=stream.read(1024*1024)
                if not chunk:break
                count+=len(chunk)
                if count>UPLOAD_LIMIT:raise Invalid('Die Datei überschreitet das Upload-Limit von 512 MiB.')
                target.write(chunk)
            target.flush();os.fsync(target.fileno())
            if os.geteuid()==0:os.fchown(target.fileno(),info.st_uid,info.st_gid)
            os.fchmod(target.fileno(),0o640)
        try:os.link(temp,name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
        except FileExistsError:raise Invalid('Eine Datei mit diesem Namen ist bereits vorhanden. Bitte vorher lokal umbenennen.') from None
        os.unlink(temp,dir_fd=fd);created=False;os.fsync(fd)
        return count
    finally:
        if created:os.unlink(temp,dir_fd=fd)
        os.close(fd)
