"""Privileged fixed-scope system stream and inventories; never holds network credentials."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import stat
import json,os,pwd,grp,shutil,subprocess,sys,tempfile,threading,signal,time
from pathlib import Path
CANCELLED=threading.Event()
RUNNING=[]
def check_cancelled():
    if CANCELLED.is_set():raise ValueError(tr('Sicherung abgebrochen.'))
def watch_cancel():
    if sys.stdin.readline().strip()!='cancel':return
    CANCELLED.set()
    for process in list(RUNNING):
        try:
            if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
EXCLUDED=('proc','sys','dev','run','tmp','mnt','media','lost+found')
FILESYSTEMS={'ext2','ext3','ext4','btrfs','xfs','f2fs','vfat'}
NETWORK_FILESYSTEMS={'nfs','nfs4','cifs','smb3','fuse.sshfs'}
BACKUP_FILESYSTEMS=FILESYSTEMS|NETWORK_FILESYSTEMS
SYSTEM_MOUNTS={'/','/home','/boot','/boot/efi','/usr','/var','/opt','/root'}
def mounts():return json.loads(subprocess.check_output(['/usr/bin/findmnt','-J','-l','-o','TARGET,FSTYPE,SOURCE,UUID'],text=True))['filesystems']
def selection(options,rows):
    extra=options.get('extra_mounts',[])
    if not isinstance(extra,list) or len(extra)>32 or any(not isinstance(p,str) for p in extra):raise ValueError(tr('Ungültige zusätzliche Datenträgerauswahl.'))
    allowed={r['target'] for r in rows if r['fstype'] in BACKUP_FILESYSTEMS}
    for p in extra:
        q=Path(options.get('source_root','/'))/p.lstrip('/')
        if p not in allowed or p in ('/proc','/sys','/dev','/run','/tmp') or not q.is_absolute() or '..' in q.parts or any(a.is_symlink() for a in (q,*q.parents)):raise ValueError(tr('Zusatzablage muss ein direkt eingehängtes unterstütztes Dateisystem sein.'))
    # Network shares are never automatic, even when mounted at /home or /var.
    return {r['target'] for r in rows if r['target'] in SYSTEM_MOUNTS and r['fstype'] in FILESYSTEMS}|set(extra)
def source_root(options):
    p=Path(options.get('source_root','/'))
    if not p.is_absolute() or '..' in p.parts or any(x.is_symlink() for x in (p,*p.parents)) or not p.is_dir():raise ValueError(tr('Direktes installiertes Linux-Quellsystem wählen.'))
    if not (p/'etc/os-release').is_file() or not (p/'etc/passwd').is_file():raise ValueError(tr('Quelle enthält kein installiertes Linux-System.'))
    if p!=Path('/') and not p.is_mount():raise ValueError(tr('Offline-Quellsystem zuerst separat einhängen.'))
    return p

def relative_mounts(source,rows):
    if source==Path('/'):return rows
    result=[]
    for row in rows:
        p=Path(row['target'])
        if p==source or p.is_relative_to(source):
            relative=str(p.relative_to(source));result.append(dict(row,target='/' if relative=='.' else '/'+relative))
    return result

def component_homes(source):
    """Exclude all normal account homes, including nonstandard locations."""
    homes={'/home'}
    for line in (source/'etc/passwd').read_text().splitlines():
        fields=line.split(':')
        if len(fields)==7 and fields[2].isdigit() and 1000<=int(fields[2])<65534:
            p=Path(fields[5])
            if not p.is_absolute() or '..' in p.parts or str(p) in ('/','/etc','/usr','/var','/opt','/root'):
                raise ValueError(tr('Unsicherer Benutzer-Home-Pfad; vor gemeinsamer Systemsicherung prüfen.'))
            homes.add(str(p))
    return homes

def personal_user():
    uid=int(os.environ.get('PKEXEC_UID',os.getuid())) if os.geteuid()==0 else os.getuid()
    user=pwd.getpwuid(uid)
    if not 1000<=uid<65534 or not user.pw_dir.startswith('/home/') or '..' in Path(user.pw_dir).parts:
        raise ValueError(tr('Persönliche Sicherung benötigt einen normalen Benutzer mit Home unter /home.'))
    return user

def personal_inventory():
    user=personal_user();rows=mounts();home=Path(user.pw_dir)
    parents=[r for r in rows if home==Path(r['target']) or Path(r['target']) in home.parents]
    containing=max(parents,key=lambda r:len(Path(r['target']).parts),default=None)
    excluded=[r for r in rows if Path(r['target'])!=home and Path(r['target']).is_relative_to(home)]
    return dict(format='linux-system-inventory-v1',component='personal',architecture=os.uname().machine,
        os_release=Path('/etc/os-release').read_text(),personal_home=user.pw_dir,personal_user=user.pw_name,
        selected_mounts=[containing] if containing else [],excluded_mounts=excluded,commands={},users={user.pw_name:{key:capture(argv) for key,argv in {
        'flatpak-apps':['flatpak','list','--user','--columns=ref,origin'],
        'flatpak-remotes':['flatpak','remotes','--user','--columns=name,url'],
        'pip':['python3','-m','pip','list','--user','--format=freeze'],
        'pipx':['pipx','list','--json'],'dconf':['dbus-run-session','--','dconf','dump','/'],
        'cron':['crontab','-l']}.items()}})

def command(options=None,rows=None):
    options=options or {};source=source_root(options) if options.get('source_root','/')!='/' else Path('/')
    rows=relative_mounts(source,rows if rows is not None else mounts());allowed=selection(options,rows)
    if options.get('component')=='system':
        homes=component_homes(source)
        if any(any(p==h or p.startswith(h+'/') for h in homes) for p in options.get('extra_mounts',[])):
            raise ValueError(tr('Zusätzliche gemeinsame Datenträger müssen außerhalb der Benutzer-Homes liegen. Home-Daten separat persönlich sichern.'))
    roots=['/'];exclude=set(EXCLUDED)|{'var/lib/heimserver-manager-client/migrations'}
    for item in rows:
        target=item['target']
        if target=='/':continue
        if target in allowed and item['fstype'] in BACKUP_FILESYSTEMS:
            roots.append(target)
            # Explicit selected subtree must not be hidden by a blanket /mnt or /media rule.
            exclude={x for x in exclude if not (target=='/'+x or target.startswith('/'+x+'/'))}
        else:exclude.add(target.lstrip('/'))
    if options.get('component')=='system':exclude.update(p.lstrip('/') for p in component_homes(source))
    # An explicitly selected nested mount must remain selectable below an excluded parent.
    exclude={x for x in exclude if not any(p!='/' and (p=='/'+x or p.startswith('/'+x+'/')) for p in roots)}
    # Exclude unselected siblings below /mnt or /media when a selected volume is there.
    for parent in ('/mnt','/media'):
        if any(p.startswith(parent+'/') for p in roots):
            if (source/parent.lstrip('/')).is_dir():
                for child in (source/parent.lstrip('/')).iterdir():
                    name='/'+str(child.relative_to(source))
                    if not any(p==name or p.startswith(name+'/') for p in roots):exclude.add(name.lstrip('/'))
    if options.get('component')=='system':exclude.update(p.lstrip('/') for p in component_homes(source))
    if not options.get('network_profiles',False):exclude.add('etc/NetworkManager/system-connections')
    args=['/usr/bin/tar','--create','--file=-','--format=pax','--sort=name','--pax-option=delete=atime,delete=ctime','--acls','--xattrs','--xattrs-include=*','--numeric-owner','--sparse','--one-file-system','--anchored']
    for value in sorted(exclude):args+=['--exclude='+value,'--exclude=./'+value]
    args+=['--directory='+str(source),'--','.',*sorted(p.lstrip('/') for p in roots if p!='/')]
    return args

def capture(argv):
    check_cancelled()
    if not shutil.which(argv[0]):return dict(status='not-installed')
    process=None
    try:
        process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True);RUNNING.append(process)
        deadline=time.monotonic()+30
        while True:
            check_cancelled()
            try:output,error=process.communicate(timeout=.2);break
            except subprocess.TimeoutExpired:
                if time.monotonic()>deadline:raise subprocess.TimeoutExpired(argv,30)
        check_cancelled();truncated=len(output)>2*1024**2
        return dict(status='ok' if process.returncode==0 and not truncated else 'failed',returncode=process.returncode,output=output[:2*1024**2],error=('Inventory output truncated; not suitable for automatic migration. ' if truncated else '')+error[:4096])
    except (OSError,subprocess.TimeoutExpired):return dict(status='failed',error=tr('Inventar nicht rechtzeitig lesbar.'))
    finally:
        if process is not None:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            process.communicate();RUNNING.remove(process)

def architecture(source):
    if source==Path('/'):return os.uname().machine
    for relative in ('usr/bin/dpkg','usr/bin/env'):
        try:
            with (source/relative).open('rb') as f:h=f.read(20)
            if h[:4]==b'\x7fELF':
                code=int.from_bytes(h[18:20],'little' if h[5]==1 else 'big')
                return {62:'x86_64',3:'i686',183:'aarch64',40:'armv7l',243:'riscv64'}.get(code,'unknown')
        except OSError:pass
    return 'unknown'

def offline_packages(source):
    """Read Debian package state as data; never chroot/execute source programs."""
    status=source/'var/lib/dpkg/status'
    if not status.is_file() or status.is_symlink():return {}
    def paragraphs(path):
        rows=[]
        for block in path.read_text(errors='replace').split('\n\n'):
            fields={}
            for line in block.splitlines():
                if ': ' in line and not line.startswith((' ','\t')):
                    k,v=line.split(': ',1);fields[k]=v
            rows.append(fields)
        return rows
    installed=[r for r in paragraphs(status) if r.get('Status') in ('install ok installed','hold ok installed') and r.get('Package')]
    extended=source/'var/lib/apt/extended_states';auto=set()
    if extended.is_file() and not extended.is_symlink():auto={r.get('Package') for r in paragraphs(extended) if r.get('Auto-Installed')=='1'}
    def record(lines):return dict(status='ok',output='\n'.join(lines)+'\n')
    return {'packages':record('\t'.join((r['Package'],r.get('Version',''),r.get('Architecture',''))) for r in installed),
            'manual-packages':record(r['Package'] for r in installed if r['Package'] not in auto),
            'package-selections':record(r['Package']+'\t'+r['Status'].split()[0] for r in installed)}

def inventory(options):
    if options.get('component')=='personal':return personal_inventory()
    source=source_root(options);rows=relative_mounts(source,mounts());allowed=selection(options,rows)
    result=dict(format='linux-system-inventory-v1',architecture=architecture(source),os_release=(source/'etc/os-release').read_text(),source_root=str(source),selected_mounts=[r for r in rows if r['target'] in allowed and r['fstype'] in BACKUP_FILESYSTEMS],excluded_mounts=[r for r in rows if r['target'] not in allowed or r['fstype'] not in BACKUP_FILESYSTEMS],network_profiles=bool(options.get('network_profiles')),commands={})
    commands={
      'packages':['dpkg-query','-W','-f=${db:Status-Status}\t${binary:Package}\t${Version}\t${Architecture}\n'],
      'package-selections':['dpkg','--get-selections'],'manual-packages':['apt-mark','showmanual'],'held-packages':['apt-mark','showhold'],
      'flatpak-system-apps':['flatpak','list','--system','--columns=ref,origin'],'flatpak-system-remotes':['flatpak','remotes','--system','--columns=name,url'],
      'rpm-packages':['rpm','-qa','--qf','%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n'],
      'rpm-user-xml':['zypper','--xmlout','search','--installed-only','--userinstalled','--type','package'],
      'modules':['lsmod'],'locale':['locale'],'ip-address':['ip','-brief','address'],'ip-route':['ip','route','show'],
      'network-connections':['nmcli','-f','NAME,UUID,TYPE,DEVICE','connection','show'],
      'snap':['snap','list'],'dkms':['dkms','status'],'units':['systemctl','list-unit-files','--no-pager'],
      'mounts':['findmnt','-J','-l'],'block-devices':['lsblk','-J','-b','-o','NAME,PATH,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS'],
      'firmware-entries':['efibootmgr','-v'],'pci':['lspci','-nn'],'usb':['lsusb'],'kernel':['uname','-a'],
      'root-cron':['crontab','-u','root','-l'],'printers':['lpstat','-p','-d']}
    for key,argv in commands.items():
        result['commands'][key]=capture(argv) if source==Path('/') else dict(status='offline',output=tr('Originale Programm-/Konfigurationsdateien im Systemarchiv; kein Quellsystem-Code im Live-System ausgeführt.'))
    packages=result['commands'].get('packages',{})
    if packages.get('status')=='ok':packages['output']='\n'.join(line.split('\t',1)[1] for line in packages['output'].splitlines() if line.startswith('installed\t'))+'\n'
    # Store zypper's user-selected package names as data, never shell expressions.
    rpm=result['commands'].get('rpm-user-xml',{})
    if rpm.get('status')=='ok':
        import xml.etree.ElementTree as ET
        try:
            names=sorted({x.attrib['name'] for x in ET.fromstring(rpm['output']).iter('solvable') if x.attrib.get('name')})
            result['commands']['rpm-user']=dict(status='ok',output='\n'.join(names))
        except (ET.ParseError,KeyError):result['commands']['rpm-user']=dict(status='failed',error='Invalid package inventory')
    # Partition metadata is reference, never automatically applied to a target disk.
    disks=capture(['lsblk','-J','-o','PATH,TYPE'])
    if disks.get('status')=='ok':
        for d in json.loads(disks['output']).get('blockdevices',[]):
            if d.get('type')=='disk':result['commands']['partition-table:'+d['path']]=capture(['sfdisk','--dump',d['path']])
    result['users']={}
    for user in (pwd.getpwall() if source==Path('/') and options.get('component')!='system' else []):
        if user.pw_uid<1000 or user.pw_uid>=60000 or user.pw_shell.endswith(('nologin','false')):continue
        base=['runuser','-u',user.pw_name,'--','env','HOME='+user.pw_dir]
        result['users'][user.pw_name]={key:capture(base+argv) for key,argv in {
          'flatpak-apps':['flatpak','list','--user','--columns=ref,origin'],
          'flatpak-remotes':['flatpak','remotes','--user','--columns=name,url'],
          'pip':['python3','-m','pip','list','--user','--format=freeze'],
          'pipx':['pipx','list','--json'],'npm':['npm','list','-g','--depth=0','--json'],
          'dconf':['dbus-run-session','--','dconf','dump','/'],'cron':['crontab','-l']}.items()}
    if source!=Path('/'):
        result['commands'].update(offline_packages(source))
        for name in ('var/lib/dpkg/status','var/lib/apt/extended_states','etc/apt/sources.list'):
            path=source/name
            if path.is_file():result['commands']['offline:'+name]=dict(status='ok',output=path.read_text(errors='replace')[:8*1024**2])
    result['component']=options.get('component','legacy-full')
    result['excluded_user_homes']=sorted(component_homes(source)) if options.get('component')=='system' else []
    omitted=[r for r in result['selected_mounts'] if any(r['target']==h or r['target'].startswith(h+'/') for h in result['excluded_user_homes'])]
    result['selected_mounts']=[r for r in result['selected_mounts'] if r not in omitted]
    result['excluded_mounts'].extend(omitted)
    result['coverage']=['root-files','all-local-users','native-programs','repositories-and-keys','flatpak-and-snap-files','local-programs-and-appimages','desktop-state','uid-gid-acl-xattr','custom-units-and-enable-links','cron','printers-udev-samba-nfs','selected-local-data-mounts']
    if options.get('component')=='system':result['coverage'].remove('all-local-users');result['coverage'].remove('desktop-state')
    result['limitations']=['No automatic partitioning or bootloader installation','Live databases/VMs require shutdown or application-consistent backups','Network profiles only if explicitly selected','Cross-distribution migration uses target packages; binary system restore requires the same platform']
    return result

def personal_exclusions():
    """Explicit per-user exclusions, relative to that user's home only."""
    home=Path(personal_user().pw_dir)
    config=home/'.config/server-manager-client/backup-exclusions.json'
    if not config.exists():return []
    values=json.loads(config.read_text()).get('personal',[])
    if not isinstance(values,list) or len(values)>256:raise ValueError('Invalid personal backup exclusions')
    for value in values:
        if not isinstance(value,str) or not value or value=='.' or Path(value).is_absolute() or '..' in Path(value).parts:
            raise ValueError('Personal backup exclusions must be relative paths within home')
    return sorted({str(home/value) for value in values})

def approved_exclusions(options):
    values=options.get('approved_exclusions',[])
    if not isinstance(values,list) or len(values)>10000:raise ValueError('Invalid backup exclusions')
    for value in values:
        if not isinstance(value,str) or not value.startswith('/') or value=='/' or '..' in Path(value).parts:
            raise ValueError('Invalid backup exclusion path')
    return set(values)

def preflight(options):
    source=source_root(options);rows=relative_mounts(source,mounts());blocked=[]
    def denied(exc):
        if not isinstance(exc,PermissionError):raise exc
        path=Path(exc.filename)
        relative='/'+str(path.relative_to(source))
        blocked.append(dict(path=relative,reason=str(exc)))
    for name in file_names(source,options,rows,denied):
        path=source/name.removeprefix('./')
        try:
            info=path.lstat()
            if stat.S_ISREG(info.st_mode):
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);os.close(fd)
        except PermissionError as exc:denied(exc)
    return dict(blocked=list({r['path']:r for r in blocked}.values()))

def file_names(source,options,rows,on_denied=None):
    """Enumerate each selected filesystem once, including same-device bind mounts."""
    allowed=selection(options,rows)
    selected=[r['target'] for r in rows if r['target'] in allowed and r['fstype'] in BACKUP_FILESYSTEMS]
    roots=['/']+sorted(set(selected)-{'/'})
    excluded=component_homes(source) if options.get('component')=='system' else set()
    if options.get('component')=='personal':
        home=personal_user().pw_dir
        if any((r['target']==home or home.startswith(r['target'].rstrip('/')+'/')) and r['fstype'] in NETWORK_FILESYSTEMS for r in rows):raise ValueError(tr('Das persönliche Home liegt auf einer Netzwerkfreigabe; separat ausdrücklich sichern.'))
        roots=[home]
        excluded.update(personal_exclusions())
    excluded.update(approved_exclusions(options))
    roots=[p for p in roots if not any(p==h or p.startswith(h+'/') for h in excluded)]
    mounted={str(source/r['target'].lstrip('/')) for r in rows if r['target']!='/'}
    def fail(error):
        if on_denied and isinstance(error,PermissionError):on_denied(error)
        else:raise error
    for root in roots:
        top=source/root.lstrip('/')
        for base,dirs,files in os.walk(top,topdown=True,followlinks=False,onerror=fail):
            check_cancelled()
            relative=Path(base).relative_to(source)
            yield '.' if str(relative)=='.' else './'+str(relative)
            kept=[]
            for name in sorted(dirs):
                path=Path(base)/name;rel=str(path.relative_to(source))
                if str(path) in mounted or any('/'+rel==h or ('/'+rel).startswith(h+'/') for h in excluded):continue
                if rel=='var/lib/heimserver-manager-client/migrations' or name.startswith('.hsm-migration-'):continue
                try:
                    if not path.is_symlink() and (path/'.hsm-system-restore-work').is_file():continue
                except PermissionError as exc:
                    exc.filename=str(path);fail(exc);continue
                if root=='/' and rel.split('/')[0] in EXCLUDED:continue
                if rel=='etc/NetworkManager/system-connections' and not options.get('network_profiles'):continue
                if path.is_symlink():yield './'+rel
                else:kept.append(name)
            dirs[:]=kept
            for name in sorted(files):
                check_cancelled()
                path=Path(base)/name;rel=str(path.relative_to(source))
                if str(path) in mounted or any('/'+rel==h or ('/'+rel).startswith(h+'/') for h in excluded):continue
                yield './'+str(path.relative_to(source))


def estimate_archive(options):
    """Metadata-only estimate using the same mount/exclusion walk as tar."""
    source=source_root(options);rows=relative_mounts(source,mounts())
    total=10240;count=0;seen=set()
    for name in file_names(source,options,rows):
        check_cancelled()
        info=(source/name.removeprefix('./')).lstat()
        total+=2048;count+=1  # tar/PAX headers, ACLs and xattrs vary
        if stat.S_ISREG(info.st_mode):
            key=(info.st_dev,info.st_ino)
            if key in seen:continue
            seen.add(key)
            size=min(info.st_size,info.st_blocks*512) if hasattr(info,'st_blocks') else info.st_size
            total+=((size+511)//512)*512
    return dict(bytes=total,entries=count,estimated=True)


def main():
    if not 2<=len(sys.argv)<=3 or sys.argv[1] not in ('backup','inventory','preflight'):raise SystemExit(tr('Unbekannte Aktion.'))
    options=json.loads(sys.argv[2]) if len(sys.argv)==3 else {}
    if not isinstance(options,dict):raise SystemExit(tr('Ungültige Auswahl.'))
    if options.get('component') not in (None,'system','personal'):raise ValueError(tr('Unbekannte Sicherungskomponente.'))
    personal=options.get('component')=='personal'
    if not personal and os.geteuid()!=0:raise SystemExit(tr('Administratorfreigabe erforderlich.'))
    if personal:
        if options.get('source_root','/')!='/':raise ValueError(tr('Persönliche Sicherung benötigt den laufenden Client.'))
        user=personal_user()
        if os.geteuid()==0:
            os.initgroups(user.pw_name,user.pw_gid);os.setgid(user.pw_gid);os.setuid(user.pw_uid)
        os.environ['HOME']=user.pw_dir;os.environ['USER']=user.pw_name
        options=dict(options,extra_mounts=[])
    if options.get('cancellable'):threading.Thread(target=watch_cancel,daemon=True).start()
    check_cancelled()
    if sys.argv[1]=='preflight':
        print(json.dumps(preflight(options)));return
    if sys.argv[1]=='inventory':
        result=inventory(options)
        result['approved_exclusions']=sorted(approved_exclusions(options))
        if personal:result['configured_exclusions']=personal_exclusions()
        if options.get('estimate_size'):result['archive_estimate']=estimate_archive(options)
        print(json.dumps(result));return
    source=source_root(options);host_rows=mounts();rows=relative_mounts(source,host_rows);args=command(options,host_rows)
    args=args[:args.index('--')]+['--no-recursion','--null','--verbatim-files-from','--files-from=-']
    with tempfile.TemporaryDirectory(prefix='hsm-personal-metadata-') as tmp:
        if personal:
            # Only this account's public identity; never another user's files or secrets.
            meta=Path(tmp)/'etc';meta.mkdir()
            (meta/'passwd').write_text(':'.join([user.pw_name,'x',str(user.pw_uid),str(user.pw_gid),'',user.pw_dir,user.pw_shell])+'\n')
            (meta/'group').write_text(grp.getgrgid(user.pw_gid).gr_name+':x:'+str(user.pw_gid)+':\n')
            (meta/'os-release').write_text(Path('/etc/os-release').read_text())
            for entry in meta.iterdir():os.utime(entry,(0,0))
            os.utime(meta,(0,0))
            args+=['--directory='+tmp,'etc','etc/passwd','etc/group','etc/os-release']
        p=subprocess.Popen(args,stdin=subprocess.PIPE,start_new_session=True);RUNNING.append(p)
        try:
            for name in file_names(source,options,rows):p.stdin.write(os.fsencode(name)+b'\0')
            p.stdin.close();code=p.wait();check_cancelled()
        except Exception:
            if not p.stdin.closed:p.stdin.close()
            p.wait();raise
        finally:RUNNING.remove(p)
    raise SystemExit(code)
def cli():
    try:main()
    except PermissionError as exc:
        print(tr('Keine Leseberechtigung für Sicherungsquelle: ')+str(exc.filename or exc)+tr('. Rechte prüfen oder diesen Pfad ausdrücklich ausschließen. Sicherung nicht abgeschlossen.'),file=sys.stderr)
        raise SystemExit(1)
    except (OSError,ValueError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
if __name__=='__main__':cli()
