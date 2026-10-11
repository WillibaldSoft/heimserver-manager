"""Adapt verified HTTPS snapshots to the installed, fixed migration engine.

Never execute a program from the backup. Staging is private to root on the
selected local Linux filesystem. The original archive stays immutable.
"""
import hashlib,json,os,re,shutil,stat,subprocess,sys,tempfile,zipfile
from pathlib import Path
import system_recovery as gates
import system_restore as restore

RESERVE=1024**3

def regular(root,relative):
    p=root/relative
    if any(a.is_symlink() for a in (p,*p.parents)) or not p.is_file():
        raise ValueError('Migration metadata must be a regular file: '+relative)
    return p

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value,encoding='utf-8');path.chmod(0o600)

def output(inv,key,user=None):
    row=(inv.get('users',{}).get(user,{}) if user else inv.get('commands',{})).get(key,{})
    return row.get('output','') if row.get('status')=='ok' else ''

def users(root,allow_missing=False):
    result={}
    for line in regular(root,'etc/passwd').read_text().splitlines():
        r=line.split(':')
        if len(r)!=7 or not r[2].isdigit() or not r[3].isdigit():continue
        if not 1000<=int(r[2])<60000 or not re.fullmatch('[a-z_][a-z0-9_-]*',r[0]):continue
        h=Path(r[5])
        if not h.is_absolute() or '..' in h.parts or len(h.parts)<3 or h.parts[1]!='home':continue
        home=root/str(h).lstrip('/')
        if any(p.is_symlink() for p in (home,*home.parents)) or (not home.is_dir() and not allow_missing):continue
        result[r[0]]=r
    return result

def copy_payload(root,destination,relative):
    """Keep ACL/xattrs and hard links; never follow restored symlink ancestors."""
    src=root/relative
    if not src.exists() and not src.is_symlink():return
    if any(p.is_symlink() for p in (src,*src.parents)):
        raise ValueError('Review symlinked migration component separately: '+relative)
    dest=destination/relative;dest.parent.mkdir(parents=True,exist_ok=True)
    # Same-filesystem hard links avoid a second full copy and retain xattrs.
    if src.is_dir():shutil.copytree(src,dest,symlinks=True,copy_function=os.link,ignore=lambda folder,names:[n for n in names if (Path(folder)/n).is_symlink()])
    else:os.link(src,dest)

def mount_layout(root,folder):
    # Reuse the original declarative network-mount reconstruction. Credentials
    # remain inside the root-private work area, never in the download profile.
    snapshot=dict(version=19,paths=[],fstab=[],units={},credentials={});paths=set()
    def read(relative):
        try:return regular(root,relative).read_text(errors='replace')
        except (OSError,ValueError):return ''
    def valid(path):return path=='/SVL' or (path.startswith('/SVL/') and '..' not in Path(path).parts and not any(c.isspace() for c in path))
    for line in read('etc/fstab').splitlines():
        fields=line.split()
        if len(fields)>=4 and not line.lstrip().startswith('#') and valid(fields[1]):snapshot['fstab'].append(line);paths.add(fields[1])
    d=root/'etc/systemd/system'
    if d.is_dir() and not d.is_symlink():
        for p in sorted(d.iterdir()):
            if p.suffix not in ('.mount','.automount') or p.is_symlink():continue
            text=read('etc/systemd/system/'+p.name);where=re.findall(r'^Where=(.+)$',text,re.M)
            if not where or not valid(where[-1].strip()):continue
            paths.add(where[-1].strip());drops={}
            for base in ('usr/lib/systemd/system','etc/systemd/system'):
                dd=root/base/(p.name+'.d')
                if dd.is_dir() and not dd.is_symlink():
                    for conf in dd.glob('*.conf'):drops[conf.name]=read(str(conf.relative_to(root)))
            snapshot['units'][p.name]=dict(text=text,dropins=drops)
    snapshot['paths']=sorted(paths)
    for text in snapshot['fstab']+[u['text'] for u in snapshot['units'].values()]:
        for name in re.findall(r'(?:credentials|cred)=([^,\s]+)',text):
            if name.startswith('/') and '..' not in Path(name).parts and not valid(name):
                value=read(name.lstrip('/'))
                if len(value.encode())<=1024**2:snapshot['credentials'][name]=value
    write(folder/'svl-config-v19/snapshot.json',json.dumps(snapshot))


def layout(root,folder,inv,user):
    records=users(root,inv.get('component')=='system')
    if user not in records:raise ValueError('Choose a backed-up normal user: '+', '.join(records))
    row=records[user];base=folder/'migration-v20';folder.mkdir(mode=0o700)
    if inv.get('component')=='system':(folder/'files').mkdir()
    else:(folder/'files').symlink_to(root/row[5].lstrip('/'),target_is_directory=True)
    if inv.get('component')=='personal':write(folder/'personal-component','1')
    write(folder/'apps/os-release',inv['os_release'])
    for key,name in [('packages','dpkg-installed.tsv'),('manual-packages','apt-manual.txt'),('rpm-user','rpm-user.txt')]:
        write(folder/'apps'/name,output(inv,key))
    for relative in ('etc/passwd','etc/group','etc/hostname','etc/locale.conf','etc/default/locale','etc/timezone','etc/shells'):
        try:value=regular(root,relative).read_text()
        except (ValueError,FileNotFoundError):continue
        write(base/'inventory'/relative.replace('/','_'),value)
    write(base/'inventory/etc_os-release',inv['os_release'])
    write(base/'inventory/architecture',inv.get('architecture','unknown'))
    write(base/'inventory/units',output(inv,'units'))
    for key,name in [('package-selections','dpkg-selections'),('snap','snap-list'),('root-cron','crontab-root'),('flatpak-system-apps','flatpak-system-apps'),('flatpak-system-remotes','flatpak-system-remotes')]:
        write(base/'software'/name,output(inv,key))
    for key,name in [('pip','pip-user.txt'),('pipx','pipx.json'),('npm','npm-user.json'),('dconf','dconf.ini'),('cron','crontab-user'),('flatpak-apps','flatpak-user-apps'),('flatpak-remotes','flatpak-user-remotes')]:
        write(base/'software'/name,output(inv,key,user))
    for relative in ('etc/apt','usr/share/keyrings','usr/local/bin','usr/local/sbin','usr/local/share/fonts','usr/local/share/themes','usr/local/share/icons','etc/crontab','etc/cron.d','etc/cron.daily','etc/cron.weekly','etc/cron.monthly','etc/cups','etc/udev/rules.d','etc/samba','etc/nfs.conf','etc/idmapd.conf','opt'):
        copy_payload(root,base/'payload',relative)
    units=[];directory=root/'etc/systemd/system'
    if directory.is_dir() and not directory.is_symlink():
        for p in sorted(directory.iterdir()):
            if p.is_symlink() or not p.is_file() or not re.fullmatch(r'[A-Za-z0-9_.@:-]+\.(service|timer|mount|automount|socket|target|path)',p.name):continue
            if any((root/v/p.name).exists() for v in ('usr/lib/systemd/system','lib/systemd/system')):continue
            if re.search(r'^Where=/SVL(?:/|$)',p.read_text(errors='replace'),re.M):continue
            units.append(p.name);copy_payload(root,base/'payload','etc/systemd/system/'+p.name)
            copy_payload(root,base/'payload','etc/systemd/system/'+p.name+'.d')
    write(base/'custom-units.json',json.dumps(units))
    mount_layout(root,folder)
    write(folder/'reports/https-inventory.json',json.dumps(inv,indent=2))
    write(folder/'https-source.json',json.dumps({'user':user,'home':row[5],'root':str(root)}))
    return folder

def migration_storage(cache):
    p=gates.direct(cache)
    if gates.mount_info(p)['fstype'] not in ('ext2','ext3','ext4','btrfs','xfs','f2fs'):raise ValueError('Migration work area requires a local Linux filesystem.')
    return str(p)

def private_stage(cache):
    cache=Path(migration_storage(cache));mount=Path(gates.mount_info(cache)['target'])
    if gates.mount_info(cache)['fstype'] not in ('ext2','ext3','ext4','btrfs','xfs','f2fs'):
        raise ValueError('Migration work area requires a local Linux filesystem.')
    # Shell tools must never traverse directories replaceable by desktop users.
    for p in (mount,*mount.parents):
        st=p.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:
            raise ValueError('Migration work disk mount and parents must be root-owned and not group/world-writable: '+str(p))
    if mount==Path('/'):
        mount=Path('/var/lib/heimserver-manager-client/migrations')
        for p in reversed((mount,*mount.parents)):
            if not p.exists():p.mkdir(mode=0o700)
            st=p.lstat()
            if p.is_symlink() or st.st_uid or st.st_mode&0o022:raise ValueError('Unsafe private migration directory: '+str(p))
    return Path(tempfile.mkdtemp(prefix='.hsm-migration-',dir=mount))

def prepare(source,sha,cache,user):
    stage=private_stage(cache);root=stage/'system';root.mkdir(mode=0o700)
    try:
        fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as src,tempfile.TemporaryFile(dir=stage) as secure:
            if not stat.S_ISREG(os.fstat(src.fileno()).st_mode):raise ValueError('Archive is not a regular file.')
            size=os.fstat(src.fileno()).st_size;digest=hashlib.sha256();count=0
            while data:=src.read(4*1024**2):
                count+=len(data)
                if count>size or shutil.disk_usage(stage).free<len(data)+RESERVE:raise ValueError('Migration work disk is full or archive changed.')
                secure.write(data);digest.update(data)
            if count!=size or digest.hexdigest()!=sha:raise ValueError('Archive checksum mismatch. Target unchanged.')
            secure.seek(0)
            with zipfile.ZipFile(secure) as z:
                if len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate ZIP entries.')
                info=z.getinfo('files/system-inventory.json')
                if info.file_size>32*1024**2:raise ValueError('Inventory too large.')
                inv=json.loads(z.read(info))
                with z.open('files/system.tar') as stream:
                    size,count=restore.inspect(stream,root)
                    while stream.read(4*1024**2):pass
                if shutil.disk_usage(stage).free<size+RESERVE:raise ValueError('Migration requires space for the unpacked system in addition to two archive copies.')
                with z.open('files/system.tar') as stream, tempfile.TemporaryFile(dir=stage) as log:
                    p=subprocess.Popen(['tar','--extract','--file=-','--directory='+str(root),'--numeric-owner','--same-owner','--same-permissions','--acls','--xattrs','--xattrs-include=*','--delay-directory-restore'],stdin=subprocess.PIPE,stdout=log,stderr=log)
                    try:shutil.copyfileobj(stream,p.stdin,4*1024**2)
                    finally:p.stdin.close()
                    if p.wait():
                        log.seek(0);raise ValueError('Migration staging failed: '+log.read(4096).decode(errors='replace'))
                folder=layout(root,stage/'backup',inv,user)
                # Provenance is data only. No script from the archive is executed.
                write(stage/'inventory.json',json.dumps(inv))
                write(stage/'provenance.json',json.dumps({'sha256':sha,'source_user':user,'format':1}))
                return folder
    except Exception:
        shutil.rmtree(stage);raise

def network(folder,target):
    folder=Path(folder);target=gates.direct(target)
    # The caller passes a root-private adapter directory, never arbitrary backup code.
    for p in (folder,*folder.parents):
        st=p.lstat()
        if p.is_symlink() or st.st_uid or st.st_mode&0o022:raise ValueError('Unsafe migration work directory.')
    meta=json.loads((folder/'https-source.json').read_text())
    source=Path(meta['root'])/'etc/NetworkManager/system-connections'
    dest=target/'etc/NetworkManager/system-connections'
    if not source.exists():print('No network profiles in this backup.');return
    for p in (source,*source.parents,dest,*dest.parents):
        if p.is_symlink():raise ValueError('Symlink in network-profile path.')
    dest.mkdir(parents=True,exist_ok=True)
    for p in source.iterdir():
        if p.is_symlink() or not p.is_file():continue
        data=p.read_bytes()
        if len(data)>1024**2:raise ValueError('Network profile too large.')
        try:fd=os.open(dest/p.name,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        except FileExistsError:print('Existing profile retained: '+p.name);continue
        with os.fdopen(fd,'wb') as out:out.write(data)
        print('Imported without activation: '+p.name)


def data_volume(folder,source_mount,destination):
    """Restore an explicitly selected extra volume, never the active OS root."""
    import uuid
    folder=gates.direct(folder);stage=folder.parent
    for p in (stage,*stage.parents):
        st=p.lstat()
        if st.st_uid or st.st_mode&0o022:raise ValueError('Unsafe migration work directory.')
    inv=json.loads(regular(stage,'inventory.json').read_text())
    from system_stream import SYSTEM_MOUNTS
    allowed={r['target'] for r in inv.get('selected_mounts',[]) if r['target'] not in SYSTEM_MOUNTS}
    if source_mount not in allowed:raise ValueError('Choose a backed-up additional volume: '+', '.join(sorted(allowed)))
    src=stage/'system'/source_mount.lstrip('/')
    src=gates.direct(src);dest=gates.direct(destination)
    if not dest.is_mount() or dest==Path('/') or gates.mount_info(dest)['fstype'] not in ('ext2','ext3','ext4','btrfs','xfs','f2fs'):raise ValueError('Choose a mounted local Linux data volume, not the running system root.')
    if stage==dest or stage.is_relative_to(dest) or dest.is_relative_to(stage):raise ValueError('Work area and restore target overlap.')
    from system_stream import mounts
    if any(Path(r['target'])!=dest and Path(r['target']).is_relative_to(dest) for r in mounts()):raise ValueError('Unmount nested target volumes before data restore.')
    needed=0
    for base,dirs,files in os.walk(src,followlinks=False):
        dirs[:]=[n for n in dirs if not (Path(base)/n).is_symlink()]
        for name in files:
            p=Path(base)/name
            if p.is_file() and not p.is_symlink():needed+=p.stat().st_size
    if shutil.disk_usage(dest).free<needed+RESERVE:raise ValueError('Insufficient target data space including recovery reserve.')
    signature=dest.stat().st_dev
    print('HSM_RECOVERY_PROMPT:Restore '+source_mount+' to '+str(dest)+'? Close applications using this volume. Changed files receive recovery copies. Type WIEDERHERSTELLEN.',flush=True)
    if sys.stdin.readline().strip()!='WIEDERHERSTELLEN':raise ValueError('Cancelled; data volume unchanged.')
    if not dest.is_mount() or dest.stat().st_dev!=signature:raise ValueError('Target volume changed.')
    recovery=dest/('.hsm-before-restore-'+uuid.uuid4().hex);recovery.mkdir(mode=0o700)
    report=folder/'reports'/('data-'+uuid.uuid4().hex+'.log')
    with report.open('x') as log:
        result=subprocess.run(['rsync','-aHAXx','--numeric-ids','--no-devices','--no-specials','--safe-links','--backup','--backup-dir='+str(recovery),'--',str(src)+'/',str(dest)+'/'],stdout=log,stderr=subprocess.STDOUT)
    print('Data restore report: '+str(report),flush=True)
    if result.returncode:raise ValueError('Data restore incomplete; review report and recovery copies.')


def launch(folder,target,target_user):
    if not re.fullmatch('[a-z_][a-z0-9_-]*',target_user):raise ValueError('Invalid target user.')
    if target!='/':restore.target_check(target,folder.parent)
    elif gates.live():raise ValueError('Choose the installed target, not the live system.')
    print('Migration work directory: '+str(folder.parent),flush=True)
    helper=Path(__file__).with_name('system-recovery.sh')
    os.execv('/bin/bash',['/bin/bash',str(helper),'--https-migration',str(folder),target,target_user])

def resume(stage,target,user,target_user):
    stage=gates.direct(stage)
    for p in (stage,*stage.parents):
        st=p.lstat()
        if st.st_uid!=0 or st.st_mode&0o022:raise ValueError('Unsafe migration work directory.')
    meta=json.loads(regular(stage,'provenance.json').read_text())
    if meta.get('format')!=1:raise ValueError('Unknown migration work format.')
    if not re.fullmatch('[a-z_][a-z0-9_-]*',user):raise ValueError('Invalid source user.')
    folder=stage/('backup-'+user)
    if not folder.exists():
        try:layout(stage/'system',folder,json.loads(regular(stage,'inventory.json').read_text()),user)
        except Exception:
            if folder.exists():shutil.rmtree(folder)
            raise
    launch(folder,target,target_user)

def main():
    if os.geteuid()!=0:raise ValueError('Administrator authorization required.')
    if len(sys.argv)==5 and sys.argv[1]=='--data':data_volume(*sys.argv[2:]);return
    if len(sys.argv)==4 and sys.argv[1]=='--network':network(*sys.argv[2:]);return
    if len(sys.argv)==6 and sys.argv[1]=='--resume':resume(*sys.argv[2:]);return
    if len(sys.argv)!=7:raise ValueError('Archive, SHA256, target, work disk, source user and target user required.')
    source,sha,target,cache,user,target_user=sys.argv[1:]
    if not re.fullmatch('[a-z_][a-z0-9_-]*',target_user):raise ValueError('Invalid target user.')
    if target!='/':restore.target_check(target,cache)
    elif gates.live():raise ValueError('Choose the installed target, not the live system.')
    print('Preparing verified migration data; no target changes yet.',flush=True)
    folder=prepare(source,sha,cache,user)
    launch(folder,target,target_user)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error':str(exc)}),flush=True);sys.exit(1)
