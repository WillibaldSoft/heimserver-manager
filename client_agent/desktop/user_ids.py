"""Explicit, root-authorized UID/GID transition at boot, before user sessions.

No live account changes. A private journal makes metadata updates restartable.
Network filesystems are never traversed. Numeric ACLs are translated as well.
"""
import errno, grp, hashlib, json, os, pwd, shutil, sqlite3, stat, struct, subprocess, sys
from pathlib import Path

BASE=Path('/var/lib/heimserver-manager-client/user-id-change')
UNIT=Path('/etc/systemd/system/heimserver-manager-user-ids.service')
DROP=Path('/etc/systemd/system/systemd-user-sessions.service.d/hsm-user-ids.conf')
IDENTITIES=Path('/var/lib/heimserver-manager-client-identities')
HELPER='/usr/lib/heimserver-manager-client/user_ids.py'
LOCAL={'ext2','ext3','ext4','btrfs','xfs','f2fs'}
ENV={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C.UTF-8'}

def run(*args):
    return subprocess.check_output(args,text=True,env=ENV).strip()

def secure(path):
    for p in (path,*path.parents):
        st=p.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise ValueError('Unsafe administrative path: '+str(p))

def save(path,data):
    temp=path.with_name(path.name+'.'+__import__('uuid').uuid4().hex+'.new')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(data,f);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)

def compare(identity):
    """Read-only comparison; no administrator prompt or filesystem traversal."""
    p=pwd.getpwuid(os.getuid())
    uid,gid=identity.get('uid'),identity.get('gid')
    if type(uid)!=int or type(gid)!=int or not 1000<=uid<=59999 or not 1000<=gid<=59999:
        raise ValueError('Server account has no supported normal-user UID/GID.')
    return dict(name=p.pw_name,old_uid=p.pw_uid,old_gid=p.pw_gid,uid=uid,gid=gid,
                matches=p.pw_uid==uid and p.pw_gid==gid)

def account(name,uid,gid):
    if type(uid)!=int or type(gid)!=int or not 1000<=uid<=59999 or not 1000<=gid<=59999:
        raise ValueError('Only normal user UID/GID values from 1000 to 59999 are supported.')
    p=pwd.getpwnam(name);g=grp.getgrgid(p.pw_gid)
    if p.pw_uid<1000 or p.pw_gid<1000:raise ValueError('System accounts cannot be converted.')
    # Shadow-utils must operate on local accounts, never an NSS directory account.
    if not any(row.startswith(name+':') for row in Path('/etc/passwd').read_text().splitlines()):
        raise ValueError('A local account is required.')
    if not any(row.startswith(g.gr_name+':') for row in Path('/etc/group').read_text().splitlines()):
        raise ValueError('A local primary group is required.')
    if any(x.pw_uid==uid and x.pw_name!=name for x in pwd.getpwall()):raise ValueError('Target UID is already in use.')
    if any(x.gr_gid==gid and x.gr_name!=g.gr_name for x in grp.getgrall()):raise ValueError('Target GID is already in use.')
    if gid!=p.pw_gid and (set(g.gr_mem)-{name} or any(x.pw_gid==p.pw_gid and x.pw_name!=name for x in pwd.getpwall())):
        raise ValueError('The primary group is shared with another user; automatic conversion refused.')
    if not Path(p.pw_dir).is_dir() or Path(p.pw_dir).is_symlink():raise ValueError('Home directory is not directly available.')
    if run('findmnt','-n','-o','FSTYPE','--target',p.pw_dir) not in LOCAL:raise ValueError('Home must be on a local Linux filesystem.')
    return dict(name=name,home=p.pw_dir,group=g.gr_name,old_uid=p.pw_uid,old_gid=p.pw_gid,uid=uid,gid=gid)

def mounts():
    rows=json.loads(run('findmnt','--json','--list','--output','TARGET,FSTYPE,UUID,FSROOT,OPTIONS'))['filesystems']
    result=[]
    for row in rows:
        if row['fstype'] in LOCAL:
            if any('quota' in opt for opt in row.get('options','').split(',')):raise ValueError('Filesystem quotas require a separate ID migration: '+row['target'])
            if not row.get('uuid'):raise ValueError('Local volume has no stable UUID: '+row['target'])
            result.append(dict(path=row['target'],uuid=row['uuid'],fsroot=row['fsroot']))
    # Read-only Btrfs snapshots retain historical numeric owners and must not be rewritten.
    if any(row['fstype']=='btrfs' for row in rows):
        for row in rows:
            if row['fstype']=='btrfs' and run('btrfs','subvolume','list','-r',row['target']):
                raise ValueError('Read-only Btrfs snapshots detected; automatic UID/GID conversion is unavailable.')
    if not any(r['path']=='/' for r in result):raise ValueError('Root filesystem is not a supported local Linux filesystem.')
    return result

def acl_map(value,plan,check=False):
    if value is None:return None
    if len(value)<4 or struct.unpack_from('<I',value)[0]!=2 or (len(value)-4)%8:raise ValueError('Unknown POSIX ACL format.')
    result=bytearray(value)
    for offset in range(4,len(value),8):
        tag,perm,identity=struct.unpack_from('<HHI',value,offset)
        key='uid' if tag==2 else 'gid' if tag==8 else None
        if key and plan['old_'+key]!=plan[key]:
            if check and identity==plan[key]:raise ValueError('Target numeric identity already appears in a filesystem ACL.')
            if identity==plan['old_'+key]:struct.pack_into('<I',result,offset+4,plan[key])
    return bytes(result)

def attr(path,name):
    try:return os.getxattr(path,name,follow_symlinks=False)
    except OSError as e:
        if e.errno in (errno.ENODATA,errno.ENOTSUP,errno.EOPNOTSUPP) or (Path(path).is_symlink() and e.errno==errno.EPERM):return None
        raise

def paths(volumes):
    boundaries={Path(row['target']) for row in json.loads(run('findmnt','--json','--list','--output','TARGET'))['filesystems']}
    for volume in volumes:
        root=Path(volume['path']);device=root.stat().st_dev
        yield root
        def failed(error):raise error
        for base,dirs,files in os.walk(root,followlinks=False,onerror=failed):
            kept=[]
            for name in dirs:
                p=Path(base)/name
                if p in boundaries or p.lstat().st_dev!=device:continue
                yield p
                if not p.is_symlink():kept.append(name)
            dirs[:]=kept
            for name in files:yield Path(base)/name

def inventory(plan):
    """No mutation until the entire inventory and target-ID conflict check pass."""
    db=sqlite3.connect(BASE/'metadata.sqlite')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, dev INTEGER, ino INTEGER, uid INTEGER, gid INTEGER, mode INTEGER, access BLOB, defaults BLOB, cap BLOB, done INTEGER DEFAULT 0)')
        db.execute('DELETE FROM files')
        for p in paths(plan['volumes']):
            if p==BASE or BASE in p.parents:continue
            try:st=p.lstat()
            except FileNotFoundError:continue
            if (plan['uid']!=plan['old_uid'] and st.st_uid==plan['uid']) or (plan['gid']!=plan['old_gid'] and st.st_gid==plan['gid']):
                raise ValueError('Unassigned target ID already owns a file: '+str(p))
            access=attr(p,'system.posix_acl_access');defaults=attr(p,'system.posix_acl_default')
            a=acl_map(access,plan,True);d=acl_map(defaults,plan,True)
            if st.st_uid==plan['old_uid'] or st.st_gid==plan['old_gid'] or a!=access or d!=defaults:
                db.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?,?,?,0)',(str(p),st.st_dev,st.st_ino,st.st_uid,st.st_gid,st.st_mode,access,defaults,attr(p,'security.capability')))
        db.commit()
    finally:db.close()

def apply_metadata(plan):
    db=sqlite3.connect(BASE/'metadata.sqlite')
    try:
        for path,dev,ino,uid,gid,mode,access,defaults,cap in db.execute('SELECT path,dev,ino,uid,gid,mode,access,defaults,cap FROM files WHERE done=0'):
            st=os.lstat(path)
            # st_dev may change between boots. Each volume UUID was verified first.
            if st.st_ino!=ino or stat.S_IFMT(st.st_mode)!=stat.S_IFMT(mode):raise ValueError('File changed since inventory: '+path)
            if st.st_uid not in (uid,plan['uid'] if uid==plan['old_uid'] else uid) or st.st_gid not in (gid,plan['gid'] if gid==plan['old_gid'] else gid):raise ValueError('File ownership changed: '+path)
            os.chown(path,plan['uid'] if uid==plan['old_uid'] else uid,plan['gid'] if gid==plan['old_gid'] else gid,follow_symlinks=False)
            if not stat.S_ISLNK(mode):
                os.chmod(path,stat.S_IMODE(mode),follow_symlinks=False)
                for key,value in [('system.posix_acl_access',acl_map(access,plan)),('system.posix_acl_default',acl_map(defaults,plan)),('security.capability',cap)]:
                    if value is not None:os.setxattr(path,key,value,follow_symlinks=False)
            db.execute('UPDATE files SET done=1 WHERE path=?',(path,));db.commit()
    finally:db.close()

def cancel():
    secure(BASE)
    plan=json.loads((BASE/'plan.json').read_text())
    if plan['phase']!='scheduled':raise ValueError('Conversion has started; keep its journal for recovery.')
    run('systemctl','disable',UNIT.name)
    UNIT.unlink(missing_ok=True)
    DROP.unlink(missing_ok=True)
    plan['phase']='cancelled';save(BASE/'plan.json',plan);run('systemctl','daemon-reload')

def schedule(plan):
    if BASE.exists():
        secure(BASE)
        if (BASE/'plan.json').exists() and json.loads((BASE/'plan.json').read_text()).get('phase') not in ('complete','cancelled'):
            raise ValueError('A user-ID change is already pending.')
        archive=BASE.with_name('user-id-change-'+__import__('time').strftime('%Y%m%d-%H%M%S'))
        BASE.rename(archive)
    BASE.mkdir(parents=True,mode=0o700);BASE.chmod(0o700);secure(BASE)
    plan.update(volumes=mounts(),phase='scheduled')
    # The caller supplies no identity value: derive the original binding locally.
    plan['local_user']=hashlib.sha256(('hsm-user:'+str(plan['old_uid'])).encode()).hexdigest()
    marker=IDENTITIES/str(plan['old_uid'])
    if marker.exists():
        secure(marker);old=json.loads(marker.read_text())
        if old['name']!=plan['name'] or old['home']!=plan['home']:raise ValueError('Existing binding identity does not match.')
        plan['local_user']=old['local_user']
    future=IDENTITIES/str(plan['uid'])
    if future.exists() and plan['uid']!=plan['old_uid']:raise ValueError('The target UID has a retained client identity; administrator review required.')
    save(BASE/'plan.json',plan)
    UNIT.write_text('[Unit]\nDescription=Heimserver Manager UID/GID conversion\nDefaultDependencies=no\nAfter=local-fs.target\nBefore=sysinit.target systemd-user-sessions.service display-manager.service\nConditionPathExists='+str(BASE/'plan.json')+'\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 '+HELPER+' apply\nTimeoutStartSec=infinity\nRemainAfterExit=yes\nUMask=0077\n[Install]\nWantedBy=sysinit.target\n')
    UNIT.chmod(0o644)
    DROP.parent.mkdir(exist_ok=True)
    DROP.write_text('[Unit]\nRequires='+UNIT.name+'\nAfter='+UNIT.name+'\n')
    run('systemctl','daemon-reload');run('systemctl','enable',UNIT.name)

def apply():
    secure(BASE);plan=json.loads((BASE/'plan.json').read_text())
    if plan['phase'] in ('complete','cancelled'):return
    if any(p.stat().st_uid in {plan['old_uid'],plan['uid']} for p in Path('/proc').iterdir() if p.name.isdigit()):
        raise ValueError('User processes are active. Conversion is only allowed before login.')
    actual=mounts()
    if any(v not in actual for v in plan['volumes']):raise ValueError('A recorded local filesystem is not mounted with its original UUID.')
    p=pwd.getpwnam(plan['name']);g=grp.getgrnam(plan['group'])
    if p.pw_uid not in {plan['old_uid'],plan['uid']} or p.pw_gid not in {plan['old_gid'],plan['gid']} or g.gr_gid not in {plan['old_gid'],plan['gid']}:raise ValueError('Account changed after scheduling.')
    if any(x.pw_uid==plan['uid'] and x.pw_name!=plan['name'] for x in pwd.getpwall()) or any(x.gr_gid==plan['gid'] and x.gr_name!=plan['group'] for x in grp.getgrall()):raise ValueError('Target ID is now in use.')
    if plan['phase']=='scheduled':
        for name in ('passwd','group','shadow','gshadow'):
            shutil.copyfile('/etc/'+name,BASE/name);(BASE/name).chmod(0o600)
        inventory(plan);plan['phase']='metadata';save(BASE/'plan.json',plan)
    apply_metadata(plan)
    if g.gr_gid!=plan['gid']:run('groupmod','-g',str(plan['gid']),plan['group'])
    if p.pw_uid!=plan['uid'] or p.pw_gid!=plan['gid']:run('usermod','-u',str(plan['uid']),'-g',str(plan['gid']),plan['name'])
    # Preserve this device/user binding, without accepting an imported JSON value.
    directory=IDENTITIES;directory.mkdir(mode=0o755,exist_ok=True);secure(directory);directory.chmod(0o755)
    marker=directory/str(plan['uid']);save(marker,{k:plan[k] for k in ('name','home','local_user')});marker.chmod(0o644)
    if plan['old_uid']!=plan['uid']:(directory/str(plan['old_uid'])).unlink(missing_ok=True)
    plan['phase']='complete';save(BASE/'plan.json',plan)
    run('systemctl','disable',UNIT.name)
    UNIT.unlink(missing_ok=True)
    DROP.unlink(missing_ok=True)
    print('UID/GID conversion complete. Private recovery journal: '+str(BASE))

def main():
    if os.geteuid()!=0:raise ValueError('Administrator authorization is required.')
    if sys.argv[1]=='apply':apply();return
    if sys.argv[1]=='cancel':cancel();return
    caller=pwd.getpwuid(int(os.environ['PKEXEC_UID']))
    plan=account(caller.pw_name,int(sys.argv[2]),int(sys.argv[3]))
    if sys.argv[1]=='preview':plan['volumes']=mounts();print(json.dumps(plan));return
    if sys.argv[1]!='schedule':raise ValueError('Unknown action.')
    if plan['old_uid']==plan['uid'] and plan['old_gid']==plan['gid']:raise ValueError('UID and GID already match.')
    schedule(plan);print('Scheduled for the next boot; no UID/GID changed in this session.')

if __name__=='__main__':
    try:
        if os.geteuid()!=0:raise ValueError('Administrator authorization is required.')
        BASE.parent.mkdir(parents=True,exist_ok=True);secure(BASE.parent)
        import fcntl
        fd=os.open(BASE.parent/'.user-id-change.lock',os.O_CREAT|os.O_NOFOLLOW|os.O_RDWR,0o600)
        with os.fdopen(fd,'w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            main()
    except Exception as e:print(str(e),file=sys.stderr);sys.exit(1)
