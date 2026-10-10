"""Existing network mounts are source hints, never offline destinations."""
import os,re
from pathlib import Path
NETWORK={'cifs','smb3','smbfs','nfs','nfs4','autofs','fuse.sshfs','fuse.rclone'}
def unescape(value):return re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),value)
def discover(mountinfo=None,fstab=None):
    live=mountinfo is None
    if mountinfo is None:mountinfo=Path('/proc/self/mountinfo').read_text()
    if fstab is None:
        try:fstab=Path('/etc/fstab').read_text()
        except FileNotFoundError:fstab=''
    rows={}
    for line in mountinfo.splitlines():
        left,sep,right=line.partition(' - ');a=left.split();b=right.split()
        if sep and len(a)>4 and len(b)>1 and b[0] in NETWORK:
            target=unescape(a[4]);rows[target]=dict(target=target,source=unescape(b[1]),fstype=b[0],active=True)
    for line in fstab.splitlines():
        fields=line.split()
        if len(fields)<3 or fields[0].startswith('#') or fields[2] not in NETWORK:continue
        target=unescape(fields[1]);rows.setdefault(target,dict(target=target,source=unescape(fields[0]),fstype=fields[2],active=False))
    if live:
        from offline_systemd import names,properties
        for row in rows.values():
            if row['fstype']=='autofs':
                try:
                    info=properties(names(row['target'])[0])
                    if info.get('Type') in ('cifs','smb3','nfs','nfs4'):
                        row.update(source=info['What'],fstype=info['Type'],automount=True)
                except (OSError,ValueError,__import__('subprocess').SubprocessError):pass
    return sorted(rows.values(),key=lambda r:r['target'])
def validate_local(path,source_mount=None):
    target=Path(path).expanduser().resolve()
    rows=discover()
    if source_mount:rows.append(source_mount)
    for row in rows:
        mount=Path(row['target']).absolute()
        if target==mount or mount in target.parents or target in mount.parents:
            raise ValueError('Offline copies require a separate local folder, outside network mounts: '+str(mount))
    return target

def suggested_destination(grant_id,name,existing=None,source_mount=None):
    """Reuse configured local data; otherwise suggest a stable, collision-safe folder."""
    import hashlib
    if existing:
        return validate_local(existing,source_mount)
    if source_mount:
        mount=Path(source_mount['target'])
        if not mount.is_absolute() or mount == Path('/') or '..' in mount.parts:
            raise ValueError('Invalid mount path')
        return validate_local(mount.parent/'Offline'/mount.name,source_mount)
    label=re.sub(r'[^\w.-]+','-',name).strip('.-')[:60] or 'Offline'
    suffix=hashlib.sha256(grant_id.encode()).hexdigest()[:10]
    return validate_local(Path.home()/'Offline-Dateien'/(label+'-'+suffix),source_mount)
