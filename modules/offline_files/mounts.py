"""Discover explicitly mounted data folders without following directory links."""
import json,subprocess
from pathlib import Path

def mounts():
    result=subprocess.run(['findmnt','--json','--list','--output','TARGET,SOURCE,FSTYPE,UUID'],capture_output=True,text=True,timeout=8,check=True)
    rows=[]
    for row in json.loads(result.stdout).get('filesystems',[]):
        target=row.get('target','');kind=row.get('fstype','')
        if not target.startswith('/') or kind in ('proc','sysfs','devtmpfs','devpts','cgroup2','overlay','squashfs','autofs','securityfs','debugfs','tracefs','configfs','fusectl','mqueue','hugetlbfs'):continue
        rows.append(dict(target=target,source=row.get('source',''),fstype=kind,uuid=row.get('uuid') or ''))
    return rows

def containing(path,rows):
    path=Path(path)
    candidates=[r for r in rows if Path(r['target'])==path or Path(r['target']) in path.parents]
    return max(candidates,key=lambda r:len(Path(r['target']).parts)) if candidates else None

def signature(row):
    # A UUID survives changing /dev/sdX device numbers; network mounts use their source.
    return dict(target=row['target'],fstype=row['fstype'],volume=row['uuid'] or row['source'])

def choices(rows):
    result=[]
    for row in rows:
        if row['fstype']=='tmpfs':continue
        p=Path(row['target'])
        if len(p.parts)<2 or p.parts[1] in ('etc','proc','sys','dev','run','usr','bin','sbin','lib','lib64','boot','root','var','opt'):continue
        candidates=[p]
        for candidate in candidates:
            if len(candidate.parts)>=3 and not any(x.is_symlink() for x in (candidate,*candidate.parents)):
                result.append(str(candidate))
    return sorted(set(result))

def server_choices(rows):
    from modules.shares.configuration import smb_shares,nfs_exports
    result=set(choices(rows))
    for row in smb_shares()+nfs_exports():
        path=row.get('path','');p=Path(path)
        if not p.is_absolute() or len(p.parts)<3 or p.parts[1] in ('etc','proc','sys','dev','run','usr','bin','sbin','lib','lib64','boot','root','var','opt'):continue
        if p.is_dir() and not any(x.is_symlink() for x in (p,*p.parents)):result.add(str(p))
    return sorted(result)
