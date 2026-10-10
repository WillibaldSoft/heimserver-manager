#!/usr/bin/python3
"""Explicit, reversible replacement of a simple fstab network mount by a local link."""
import contextlib,fcntl,hashlib,json,os,pwd,stat,subprocess,sys,tempfile,uuid
from pathlib import Path
from offline_mounts import discover,unescape,validate_local
import offline_systemd
STATE=Path('/var/lib/heimserver-manager-client/offline-mounts')
FSTAB=Path('/etc/fstab')
def run(*args):subprocess.run(args,check=True,capture_output=True,text=True,timeout=45)
def trusted_parent(target):
    if not target.is_absolute() or '..' in target.parts or len(target.parts)<3:raise ValueError('Choose a data mount below a dedicated parent directory')
    for p in (target.parent,*target.parent.parents):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Mount parent must be a root-owned, non-writable directory')
def atomic(text):
    st=FSTAB.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=0:raise ValueError('Unsafe fstab')
    fd,tmp=tempfile.mkstemp(prefix='.hsm-fstab-',dir='/etc')
    try:
        with os.fdopen(fd,'w') as out:out.write(text);out.flush();os.fsync(out.fileno());os.fchmod(out.fileno(),stat.S_IMODE(st.st_mode))
        os.replace(tmp,FSTAB)
    finally:
        with contextlib.suppress(FileNotFoundError):os.unlink(tmp)
    run('/usr/bin/systemctl','daemon-reload')
def matching_line(text,target):
    matches=[]
    for i,line in enumerate(text.splitlines(keepends=True)):
        f=line.split()
        if f and not f[0].startswith('#') and len(f)>=4 and unescape(f[1])==str(target):matches.append((i,f,line))
    if len(matches)!=1:raise ValueError('Exactly one existing fstab entry is required; custom/GVfs mounts are not changed')
    i,f,line=matches[0]
    if f[2] not in ('cifs','smb3','nfs','nfs4') or any(x in f[3] for x in ('x-systemd.automount','bind','move')):raise ValueError('Only simple SMB/NFS fstab mounts can be replaced')
    return i,f,line

def prepare_folder(target,uid):
    """Change only one dedicated local data directory, never its contents."""
    user=pwd.getpwuid(uid)
    target=Path(target)
    allowed=(Path(user.pw_dir),Path('/SVL'),Path('/mnt'),Path('/media'),Path('/srv'))
    if not target.is_absolute() or '..' in target.parts or not any(root in target.parents for root in allowed):
        raise ValueError('Choose a dedicated local data folder below your home, /SVL, /mnt, /media or /srv')
    validate_local(target)
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in target.parts[1:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
            st=os.fstat(fd)
            if st.st_uid not in (0,uid) or st.st_mode&0o022:
                raise ValueError('Folder parent must be owned by root or the current user and not writable by others')
        try:os.mkdir(target.name,0o700,dir_fd=fd)
        except FileExistsError:pass
        child=os.open(target.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        try:
            st=os.fstat(child)
            if st.st_uid not in (0,uid):raise ValueError('Folder belongs to another user')
            if os.path.ismount(target):raise ValueError('Choose a folder below the mount, not the mount itself')
            os.fchown(child,uid,user.pw_gid)
            os.fchmod(child,stat.S_IMODE(st.st_mode)|0o700)
        finally:os.close(child)
    finally:os.close(fd)

def main():
    if os.geteuid()!=0:raise ValueError('Administrator authorization required')
    action,target_arg,local_arg=sys.argv[1:];target=Path(target_arg);local=Path(local_arg)
    uid=int(os.environ.get('PKEXEC_UID','-1'))
    if uid<=0:raise ValueError('Run through the desktop administrator authorization')
    if action=='prepare-folder':
        prepare_folder(target,uid);print('Local offline folder prepared.');return
    trusted_parent(target)
    STATE.mkdir(parents=True,mode=0o700,exist_ok=True)
    key=hashlib.sha256(str(target).encode()).hexdigest();record=STATE/(key+'.json')
    with (STATE/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if action=='replace':
            if record.exists():raise ValueError('This mount already has a saved replacement')
            if local.is_symlink() or not local.is_dir() or local.stat().st_uid!=uid:raise ValueError('Offline folder must belong to the current user')
            local=validate_local(local)
            automount=offline_systemd.inspect(target)
            if automount:
                offline_systemd.replace(target,local,uid,record,automount)
                print('Automount replaced. Original unit states saved.');return
            text=FSTAB.read_text();index,fields,line=matching_line(text,target)
            active=next((m for m in discover() if m['target']==str(target) and m['active']),None)
            if not active or active['source']!=unescape(fields[0]):raise ValueError('The selected fstab network mount must be mounted before switching')
            tag='# HSM-OFFLINE '+key+' '+line.rstrip('\n')+'\n'
            lines=text.splitlines(keepends=True);lines[index]=tag;updated=''.join(lines)
            saved=target.parent/('.hsm-mount-'+uuid.uuid4().hex)
            data=dict(target=str(target),local=str(local),uid=uid,line=line,marker=tag,saved=str(saved),phase='prepared')
            record.write_text(json.dumps(data));record.chmod(0o600)
            (STATE/(key+'.fstab-before')).write_text(text)
            moved=False;changed=False;unmounted=False
            try:
                run('/usr/bin/umount','--',str(target)) # never lazy or forced
                unmounted=True
                if os.path.ismount(target) or target.is_symlink() or not target.is_dir() or any(target.iterdir()):raise ValueError('Underlying mount directory is not empty; nothing replaced')
                if FSTAB.read_text()!=text:raise ValueError('fstab changed; retry after checking it')
                target.rename(saved);moved=True
                target.symlink_to(local,target_is_directory=True)
                changed=True;atomic(updated)
                data['phase']='active';record.write_text(json.dumps(data))
            except Exception:
                if changed and target.is_symlink() and os.readlink(target)==str(local):target.unlink()
                if moved and not target.exists():saved.rename(target)
                if FSTAB.read_text()==updated:atomic(text)
                if unmounted and not os.path.ismount(target):
                    with contextlib.suppress(Exception):run('/usr/bin/mount','--',str(target))
                if not unmounted:record.unlink()
                else:data['phase']='failed';record.write_text(json.dumps(data))
                raise
        elif action=='restore':
            data=json.loads(record.read_text())
            if data.get('kind')=='systemd':
                offline_systemd.restore(target,uid,record,data)
                print('Original automount state restored. Offline files retained.');return
            if data['uid']!=uid or data['phase']!='active':raise ValueError('No active replacement for this user')
            if not target.is_symlink() or os.readlink(target)!=data['local']:raise ValueError('Mount path changed; nothing restored')
            text=FSTAB.read_text()
            if text.count(data['marker'])!=1:raise ValueError('Saved fstab marker changed; manual review required')
            restored=text.replace(data['marker'],data['line'],1);saved=Path(data['saved'])
            if saved.parent!=target.parent or not saved.is_dir() or saved.is_symlink() or any(saved.iterdir()):raise ValueError('Original mount directory changed')
            target.unlink();saved.rename(target)
            try:atomic(restored);run('/usr/bin/mount','--',str(target))
            except Exception:
                # Restore the local alias if reconnecting fails; preserve user files.
                if not os.path.ismount(target) and target.is_dir() and not any(target.iterdir()):
                    target.rename(saved);target.symlink_to(data['local'],target_is_directory=True)
                    if FSTAB.read_text()==restored:atomic(text)
                else:
                    data['phase']='restore-failed';record.write_text(json.dumps(data))
                raise
            record.unlink()
        else:raise ValueError('Unknown action')
    print('Mount configuration updated. Offline data retained.')
if __name__=='__main__':
    try:main()
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(1)
