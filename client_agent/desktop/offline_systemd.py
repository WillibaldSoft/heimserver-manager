"""Reversible systemd automount suspension without changing enablement or unit files."""
import hashlib,json,os,subprocess,uuid
from pathlib import Path
SYSTEM=Path('/etc/systemd/system')
def command(*args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE,timeout=60).strip()
def names(target):
    mount=command('/usr/bin/systemd-escape','--path','--suffix=mount',str(target))
    if '/' in mount or not mount.endswith('.mount'):raise ValueError('Invalid mount unit name')
    return mount,mount[:-6]+'.automount'
def properties(unit):
    text=command('/usr/bin/systemctl','show',unit,'--no-pager','--property=LoadState,ActiveState,UnitFileState,Where,What,Type,FragmentPath,DropInPaths,ForceUnmount,LazyUnmount')
    return dict(line.split('=',1) for line in text.splitlines() if '=' in line)
def inspect(target):
    mount,auto=names(target);a=properties(auto)
    if a.get('LoadState')=='not-found':return None
    m=properties(mount)
    if any(p.get('LoadState')!='loaded' for p in (a,m)):raise ValueError('Automount units are unavailable or masked')
    if any(p.get('Where')!=str(target) for p in (a,m)) or m.get('Type') not in ('cifs','smb3','nfs','nfs4'):raise ValueError('Only matching SMB/NFS automount units are supported')
    if m.get('ForceUnmount')=='yes' or m.get('LazyUnmount')=='yes':raise ValueError('Forced or lazy unmount is not supported')
    if any(p.get('ActiveState') not in ('active','inactive') for p in (a,m)):raise ValueError('Automount state is changing or failed; check it first')
    return {'mount':mount,'automount':auto,'units':{mount:m,auto:a}}
def control_path(unit):return SYSTEM/(unit+'.d')/'90-heimserver-offline.conf'
def dropin(marker):return '[Unit]\n# Managed offline alias; original enablement remains unchanged.\nConditionPathExists=!'+str(marker)+'\n'
def fingerprints(info):
    result={}
    for p in info['units'].values():
        for name in [p.get('FragmentPath',''),*p.get('DropInPaths','').split()]:
            if not name:continue
            path=Path(name)
            if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:raise ValueError('Unit configuration must be root-owned and not writable by other users')
            result[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result
def check_original(state):
    for name,digest in state['fingerprints'].items():
        p=Path(name)
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('Original automount configuration changed; review before restoring')
def verify_block(state):
    for unit in (state['mount'],state['automount']):
        text=command('/usr/bin/systemctl','cat',unit,'--no-pager')
        section='';found=False
        for raw in text.splitlines():
            line=raw.strip()
            if line.startswith(('#',';')):continue
            if line.endswith('\\'):raise ValueError('Continued unit directives require manual review')
            if line.startswith('['):section=line
            if section=='[Unit]' and '=' in line:
                key,value=(x.strip() for x in line.split('=',1))
                if key.startswith('Condition') and not value:found=False
                if key=='ConditionPathExists' and value=='!'+state['marker']:found=True
        if not found:raise ValueError('Another drop-in overrides the offline start condition')
def block(state):
    marker=Path(state['marker']);marker.write_text('offline\n');marker.chmod(0o600)
    for unit in (state['mount'],state['automount']):
        path=control_path(unit);path.parent.mkdir(exist_ok=True)
        if path.is_symlink() or (path.exists() and path.read_text()!=dropin(marker)):raise ValueError('Offline control drop-in already exists or changed')
        path.write_text(dropin(marker));path.chmod(0o644)
    command('/usr/bin/systemctl','daemon-reload')
    verify_block(state)
def unblock(state):
    marker=Path(state['marker'])
    for unit in (state['mount'],state['automount']):
        path=control_path(unit)
        if not path.is_file() or path.is_symlink() or path.read_text()!=dropin(marker):raise ValueError('Offline control drop-in changed')
    for unit in (state['mount'],state['automount']):control_path(unit).unlink()
    marker.unlink();command('/usr/bin/systemctl','daemon-reload')
def stop(state):
    command('/usr/bin/systemctl','stop',state['automount'],state['mount'])
    if any(properties(u).get('ActiveState')!='inactive' for u in (state['automount'],state['mount'])):raise ValueError('Mounts did not stop cleanly')
def restart_previous(state):
    for unit in (state['automount'],state['mount']):
        if state['units'][unit]['ActiveState']=='active':command('/usr/bin/systemctl','start',unit)
def replace(target,local,uid,record,info):
    state=dict(info,kind='systemd',target=str(target),local=str(local),uid=uid,phase='prepared',marker=str(record.with_suffix('.blocked')),saved=str(target.parent/('.hsm-mount-'+uuid.uuid4().hex)),fingerprints=fingerprints(info))
    for unit in (state['mount'],state['automount']):
        p=control_path(unit)
        if p.exists() or p.is_symlink():raise ValueError('Offline unit drop-in already exists')
        if p.parent.exists() and (p.parent.is_symlink() or p.parent.stat().st_uid!=0 or p.parent.stat().st_mode&0o022):raise ValueError('Unsafe unit drop-in directory')
    record.write_text(json.dumps(state));record.chmod(0o600)
    moved=False
    try:
        block(state);stop(state)
        if os.path.ismount(target) or target.is_symlink() or not target.is_dir() or any(target.iterdir()):raise ValueError('Underlying mount directory must be empty')
        target.rename(state['saved']);moved=True;target.symlink_to(local,target_is_directory=True)
        state['phase']='active';record.write_text(json.dumps(state))
    except Exception:
        if moved:
            if target.is_symlink() and os.readlink(target)==str(local):target.unlink()
            if not target.exists():Path(state['saved']).rename(target)
        try:unblock(state);restart_previous(state);record.unlink()
        except Exception:
            state['phase']='failed';record.write_text(json.dumps(state))
        raise

def restore(target,uid,record,state):
    if state['uid']!=uid or state['phase']!='active':raise ValueError('No active offline replacement for this user')
    if not target.is_symlink() or os.readlink(target)!=state['local']:raise ValueError('Offline path changed')
    saved=Path(state['saved'])
    if saved.parent!=target.parent or saved.is_symlink() or not saved.is_dir() or any(saved.iterdir()):raise ValueError('Saved mount directory changed')
    check_original(state)
    # Validate both drop-ins before touching the alias.
    for unit in (state['mount'],state['automount']):
        p=control_path(unit)
        if p.is_symlink() or not p.is_file() or p.read_text()!=dropin(Path(state['marker'])):raise ValueError('Offline unit drop-in changed')
    target.unlink();saved.rename(target)
    try:unblock(state);restart_previous(state)
    except Exception:
        try:
            block(state);stop(state)
            if os.path.ismount(target) or any(target.iterdir()):raise ValueError('Cannot restore offline alias safely')
            target.rename(saved);target.symlink_to(state['local'],target_is_directory=True)
        except Exception:
            state['phase']='restore-failed';record.write_text(json.dumps(state))
        raise
    record.unlink()
