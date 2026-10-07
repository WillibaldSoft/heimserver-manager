"""Privileged fixed-scope system stream and inventories; never holds network credentials."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,os,pwd,shutil,subprocess,sys
from pathlib import Path
EXCLUDED=('proc','sys','dev','run','tmp','mnt','media','lost+found')
FILESYSTEMS={'ext2','ext3','ext4','btrfs','xfs','f2fs','vfat'}
SYSTEM_MOUNTS={'/','/home','/boot','/boot/efi','/usr','/var','/opt','/root'}
def mounts():return json.loads(subprocess.check_output(['/usr/bin/findmnt','-J','-l','-o','TARGET,FSTYPE,SOURCE,UUID'],text=True))['filesystems']
def selection(options,rows):
    extra=options.get('extra_mounts',[])
    if not isinstance(extra,list) or len(extra)>32 or any(not isinstance(p,str) for p in extra):raise ValueError(tr('Ungültige zusätzliche Datenträgerauswahl.'))
    allowed={r['target'] for r in rows if r['fstype'] in FILESYSTEMS}
    for p in extra:
        q=Path(options.get('source_root','/'))/p.lstrip('/')
        if p not in allowed or p in ('/proc','/sys','/dev','/run','/tmp') or not q.is_absolute() or '..' in q.parts or any(a.is_symlink() for a in (q,*q.parents)):raise ValueError(tr('Zusatzablage muss ein direkt eingehängtes lokales Dateisystem sein.'))
    return SYSTEM_MOUNTS|set(extra)
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

def command(options=None,rows=None):
    options=options or {};source=source_root(options) if options.get('source_root','/')!='/' else Path('/')
    rows=relative_mounts(source,rows if rows is not None else mounts());allowed=selection(options,rows)
    roots=['/'];exclude=set(EXCLUDED)
    for item in rows:
        target=item['target']
        if target=='/':continue
        if target in allowed and item['fstype'] in FILESYSTEMS:
            roots.append(target)
            # Explicit selected subtree must not be hidden by a blanket /mnt or /media rule.
            exclude={x for x in exclude if not (target=='/'+x or target.startswith('/'+x+'/'))}
        else:exclude.add(target.lstrip('/'))
    # Exclude unselected siblings below /mnt or /media when a selected volume is there.
    for parent in ('/mnt','/media'):
        if any(p.startswith(parent+'/') for p in roots):
            if (source/parent.lstrip('/')).is_dir():
                for child in (source/parent.lstrip('/')).iterdir():
                    name='/'+str(child.relative_to(source))
                    if not any(p==name or p.startswith(name+'/') for p in roots):exclude.add(name.lstrip('/'))
    if not options.get('network_profiles',False):exclude.add('etc/NetworkManager/system-connections')
    args=['/usr/bin/tar','--create','--file=-','--format=pax','--sort=name','--pax-option=delete=atime,delete=ctime','--acls','--xattrs','--xattrs-include=*','--numeric-owner','--sparse','--one-file-system','--anchored']
    for value in sorted(exclude):args+=['--exclude='+value,'--exclude=./'+value]
    args+=['--directory='+str(source),'--','.',*sorted(p.lstrip('/') for p in roots if p!='/')]
    return args

def capture(argv):
    if not shutil.which(argv[0]):return dict(status='not-installed')
    try:
        p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30,text=True)
        return dict(status='ok' if p.returncode==0 else 'failed',returncode=p.returncode,output=p.stdout[:2*1024**2],error=p.stderr[:4096])
    except (OSError,subprocess.TimeoutExpired):return dict(status='failed',error=tr('Inventar nicht rechtzeitig lesbar.'))

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

def inventory(options):
    source=source_root(options);rows=relative_mounts(source,mounts());allowed=selection(options,rows)
    result=dict(format='linux-system-inventory-v1',architecture=architecture(source),os_release=(source/'etc/os-release').read_text(),source_root=str(source),selected_mounts=[r for r in rows if r['target'] in allowed and r['fstype'] in FILESYSTEMS],excluded_mounts=[r for r in rows if r['target'] not in allowed or r['fstype'] not in FILESYSTEMS],network_profiles=bool(options.get('network_profiles')),commands={})
    commands={
      'packages':['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\n'],
      'package-selections':['dpkg','--get-selections'],'manual-packages':['apt-mark','showmanual'],'held-packages':['apt-mark','showhold'],
      'flatpak-system-apps':['flatpak','list','--system','--columns=ref,origin'],'flatpak-system-remotes':['flatpak','remotes','--system','--columns=name,url'],
      'snap':['snap','list'],'dkms':['dkms','status'],'units':['systemctl','list-unit-files','--no-pager'],
      'mounts':['findmnt','-J','-l'],'block-devices':['lsblk','-J','-b','-o','NAME,PATH,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS'],
      'firmware-entries':['efibootmgr','-v'],'pci':['lspci','-nn'],'usb':['lsusb'],'kernel':['uname','-a'],
      'root-cron':['crontab','-u','root','-l'],'printers':['lpstat','-p','-d']}
    for key,argv in commands.items():
        result['commands'][key]=capture(argv) if source==Path('/') else dict(status='offline',output=tr('Originale Programm-/Konfigurationsdateien im Systemarchiv; kein Quellsystem-Code im Live-System ausgeführt.'))
    # Partition metadata is reference, never automatically applied to a target disk.
    disks=capture(['lsblk','-J','-o','PATH,TYPE'])
    if disks.get('status')=='ok':
        for d in json.loads(disks['output']).get('blockdevices',[]):
            if d.get('type')=='disk':result['commands']['partition-table:'+d['path']]=capture(['sfdisk','--dump',d['path']])
    result['users']={}
    for user in (pwd.getpwall() if source==Path('/') else []):
        if user.pw_uid<1000 or user.pw_uid>=60000 or user.pw_shell.endswith(('nologin','false')):continue
        base=['runuser','-u',user.pw_name,'--','env','HOME='+user.pw_dir]
        result['users'][user.pw_name]={key:capture(base+argv) for key,argv in {
          'flatpak-apps':['flatpak','list','--user','--columns=ref,origin'],
          'flatpak-remotes':['flatpak','remotes','--user','--columns=name,url'],
          'pip':['python3','-m','pip','list','--user','--format=freeze'],
          'pipx':['pipx','list','--json'],'npm':['npm','list','-g','--depth=0','--json'],
          'dconf':['dbus-run-session','--','dconf','dump','/'],'cron':['crontab','-l']}.items()}
    if source!=Path('/'):
        for name in ('var/lib/dpkg/status','var/lib/apt/extended_states','etc/apt/sources.list'):
            path=source/name
            if path.is_file():result['commands']['offline:'+name]=dict(status='ok',output=path.read_text(errors='replace')[:8*1024**2])
    result['coverage']=['root-files','all-local-users','native-programs','repositories-and-keys','flatpak-and-snap-files','local-programs-and-appimages','desktop-state','uid-gid-acl-xattr','custom-units-and-enable-links','cron','printers-udev-samba-nfs','selected-local-data-mounts']
    result['limitations']=['No automatic partitioning or bootloader installation','Live databases/VMs require shutdown or application-consistent backups','Network profiles only if explicitly selected','Cross-distribution binary restore unsupported']
    return result

def file_names(source,options,rows):
    """Enumerate each selected filesystem once, including same-device bind mounts."""
    allowed=selection(options,rows)
    selected=[r['target'] for r in rows if r['target'] in allowed and r['fstype'] in FILESYSTEMS]
    roots=['/']+sorted(set(selected)-{'/'})
    mounted={str(source/r['target'].lstrip('/')) for r in rows if r['target']!='/'}
    def fail(error):raise error
    for root in roots:
        top=source/root.lstrip('/')
        for base,dirs,files in os.walk(top,topdown=True,followlinks=False,onerror=fail):
            relative=Path(base).relative_to(source)
            yield '.' if str(relative)=='.' else './'+str(relative)
            kept=[]
            for name in sorted(dirs):
                path=Path(base)/name;rel=str(path.relative_to(source))
                if str(path) in mounted:continue
                if root=='/' and rel.split('/')[0] in EXCLUDED:continue
                if rel=='etc/NetworkManager/system-connections' and not options.get('network_profiles'):continue
                if path.is_symlink():yield './'+rel
                else:kept.append(name)
            dirs[:]=kept
            for name in sorted(files):yield './'+str((Path(base)/name).relative_to(source))


def main():
    if os.geteuid()!=0:raise SystemExit(tr('Administratorfreigabe erforderlich.'))
    if not 2<=len(sys.argv)<=3 or sys.argv[1] not in ('backup','inventory'):raise SystemExit(tr('Unbekannte Aktion.'))
    options=json.loads(sys.argv[2]) if len(sys.argv)==3 else {}
    if not isinstance(options,dict):raise SystemExit(tr('Ungültige Auswahl.'))
    if sys.argv[1]=='inventory':print(json.dumps(inventory(options)));return
    source=source_root(options);host_rows=mounts();rows=relative_mounts(source,host_rows);args=command(options,host_rows)
    args=args[:args.index('--')]+['--no-recursion','--null','--verbatim-files-from','--files-from=-']
    p=subprocess.Popen(args,stdin=subprocess.PIPE)
    try:
        for name in file_names(source,options,rows):p.stdin.write(os.fsencode(name)+b'\0')
        p.stdin.close();code=p.wait()
    except Exception:
        p.stdin.close();p.wait();raise
    raise SystemExit(code)
if __name__=='__main__':main()
