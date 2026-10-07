"""Privileged Live-USB restore of a verified, immutable temporary ZIP snapshot."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,json,os,shutil,subprocess,sys,tarfile,tempfile,zipfile
from pathlib import Path,PurePosixPath
import system_recovery as gates
import system_components as components
RESERVE=512*1024**2
PRESERVE={'etc/fstab','etc/crypttab'}
def normalized(name):
    if name.startswith('/') or '\\' in name or any(ord(c)<32 for c in name):raise ValueError(tr('Unsicherer Archivpfad.'))
    parts=name.split('/')
    if '..' in parts:raise ValueError(tr('Unsicherer Archivpfad.'))
    return '/'.join(p for p in parts if p not in ('','.'))
def inspect(archive,target,scope="all",selection="",members=None):
    entries={};links={};total=0
    with tarfile.open(fileobj=archive,mode='r|') as tar:
        for item in tar:
            name=normalized(item.name)
            if not name:
                if item.isdir():continue
                raise ValueError(tr('Ungültiger Wurzeleintrag.'))
            if name in entries and not (item.isdir() and entries[name]=='dir'):raise ValueError(tr('Doppelter Archiveintrag: ')+name)
            if not (item.isfile() or item.isdir() or item.issym() or item.islnk() or item.isfifo()):raise ValueError(tr('Nicht unterstützte Spezialdatei: ')+name)
            kind='dir' if item.isdir() else 'link' if item.issym() else 'hard' if item.islnk() else 'file'
            entries[name]=kind
            if item.islnk():links[name]=normalized(item.linkname)
            if (scope=='files' or name not in PRESERVE) and components.selected(name,scope,selection):
                if members is not None:members.append((item.name,name,item.size,kind))
                for parent in PurePosixPath(name).parents:
                    if str(parent)=='.':continue
                    path=target/str(parent)
                    if path.is_symlink():raise ValueError(tr('Ziel enthält symbolischen übergeordneten Ordner: ')+str(parent))
                dest=target/name
                if dest.is_symlink() and not item.issym():raise ValueError(tr('Zielpfad ist ein symbolischer Link: ')+name)
                if item.size<0:raise ValueError(tr('Ungültige Dateigröße.'))
                total+=item.size
    for name in entries:
        for parent in PurePosixPath(name).parents:
            if str(parent) in entries and entries[str(parent)]!='dir':raise ValueError(tr('Archivpfad unterhalb eines Links oder einer Datei.'))
    for name,link in links.items():
        seen={name}
        while entries.get(link)=='hard':
            if link in seen:raise ValueError(tr('Zyklischer Hardlink.'))
            seen.add(link);link=links[link]
        if entries.get(link)!='file':raise ValueError(tr('Hardlink verweist nicht auf Archivdatei.'))
    if members is not None and scope!='files':
        chosen={name for _,name,_,_ in members}
        for name in chosen:
            if name in links and links[name] not in chosen:raise ValueError(tr('Hardlink benötigt eine weitere Komponente; vollständige Rücksicherung wählen.'))
    for name in ('etc/os-release','etc/passwd'):
        if name not in entries:raise ValueError(tr('Kein vollständiges Linux-Systemarchiv.'))
    return total,len(entries)

def target_check(target,cache):
    target=Path(gates.restore_target(str(target),str(cache)))
    mount=gates.mount_info(target)
    if mount['fstype'] not in ('ext2','ext3','ext4','btrfs','xfs','f2fs'):raise ValueError(tr('Linux-Dateisystem als Systemziel erforderlich.'))
    rows=json.loads(subprocess.check_output(['findmnt','-J','-l','-o','TARGET,FSTYPE'],text=True))['filesystems']
    signature=[(str(target),target.stat().st_dev)]
    for r in rows:
        p=Path(r['target'])
        if p==target or not p.is_relative_to(target):continue
        if r.get('fstype') not in ('ext2','ext3','ext4','btrfs','xfs','f2fs','vfat') or any(x.is_symlink() for x in (p,*p.parents)) or p.stat().st_dev in (Path('/').stat().st_dev,Path(cache).stat().st_dev):
            raise ValueError(tr('Ungeeignete Unterpartition im Ziel. Virtuelle, Netzwerk- und Arbeitsablagen vorher aushängen.'))
        signature.append((str(p),p.stat().st_dev))
    return target,tuple(sorted(signature))

def platform_check(z,target,scope):
    if scope in ('home','files'):return
    if 'files/system-inventory.json' not in z.namelist():return # Legacy archive remains supported.
    item=z.getinfo('files/system-inventory.json')
    if item.file_size>32*1024**2:raise ValueError(tr('Systeminventar zu groß.'))
    inv=json.loads(z.read(item))
    def release(text):
        return dict(line.split('=',1) for line in text.splitlines() if '=' in line)
    src=release(inv.get('os_release',''));dst=release((target/'etc/os-release').read_text())
    if any(src.get(k)!=dst.get(k) for k in ('ID','VERSION_ID')) or inv.get('architecture')!=os.uname().machine:
        raise ValueError(tr('System/Programme nur auf gleicher Distribution, Version und Architektur zurücksichern. Für andere Systeme Dateien übernehmen und Programme passend neu installieren.'))

def required_space(target,members):
    totals={}
    for _,name,size,_ in members:
        parent=target/name
        while not parent.exists():parent=parent.parent
        # Existing archive symlinks are never followed for free-space accounting.
        if parent.is_symlink():parent=parent.parent
        dev=parent.stat().st_dev
        totals.setdefault(dev,[parent,0])[1]+=size
    for parent,total in totals.values():
        if shutil.disk_usage(parent).free<total+RESERVE:raise ValueError(tr('Zu wenig freier Platz auf einer Zielpartition (konservative Prüfung).'))

def run(source,sha,target,cache,scope="all",selection=""):
    if scope not in components.SCOPES or scope=="files":raise ValueError(tr("Ungültiger Systemumfang."))
    cache=Path(gates.storage(cache));target,device=target_check(target,cache)
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as src:
        if not __import__('stat').S_ISREG(os.fstat(src.fileno()).st_mode):raise ValueError(tr('Archiv ist keine reguläre Datei.'))
        size=os.fstat(src.fileno()).st_size
        if shutil.disk_usage(cache).free<size+RESERVE:raise ValueError(tr('Externe Ablage benötigt Platz für eine geschützte Prüfkopie des ZIPs.'))
        # Unlinked root-owned snapshot: desktop users cannot mutate it after verification.
        with tempfile.TemporaryFile(dir=cache) as secure:
            digest=hashlib.sha256();copied=0
            while data:=src.read(4*1024**2):
                copied+=len(data)
                if copied>size or shutil.disk_usage(cache).free<len(data)+RESERVE:raise ValueError(tr('Archivgröße oder Speicherreserve überschritten.'))
                secure.write(data);digest.update(data)
            if copied!=size or digest.hexdigest()!=sha:raise ValueError(tr('Prüfsumme stimmt nicht. Keine Zieländerung.'))
            secure.seek(0)
            with zipfile.ZipFile(secure) as z:
                if len(z.namelist())!=len(set(z.namelist())):raise ValueError(tr('Doppelte ZIP-Einträge.'))
                meta=z.getinfo('hsm-backup.json')
                if meta.file_size>65536:raise ValueError(tr('Metadaten zu groß.'))
                if json.loads(z.read(meta)).get('scope') not in ('linux-system-tar-v1','linux-system-tar-v2'):raise ValueError(tr('Kein HTTPS-Systemarchiv.'))
                platform_check(z,target,scope);members=[]
                with z.open('files/system.tar') as contents:
                    total,count=inspect(contents,target,scope,selection,members)
                    while contents.read(4*1024**2):pass  # Verify ZIP CRC before any target write.
                if not members:raise ValueError(tr('Keine passenden Komponenten im Archiv.'))
                required_space(target,members)
                print(json.dumps({'confirm':True,'target':str(target),'files':len(members),'bytes':total,'scope':components.SCOPES[scope],'preserved':'etc/fstab, etc/crypttab'}),flush=True)
                if sys.stdin.readline().strip()!='WIEDERHERSTELLEN':raise ValueError(tr('Abgebrochen; Ziel unverändert.'))
                checked,dev=target_check(target,cache)
                if dev!=device:raise ValueError(tr('Zieldatenträger hat sich geändert.'))
                args=['tar','--extract','--file=-','--directory='+str(target),'--numeric-owner','--same-owner','--same-permissions','--acls','--xattrs','--xattrs-include=*','--delay-directory-restore']
                for name in sorted(PRESERVE):args+=['--exclude='+name,'--exclude=./'+name]
                # Verbatim NUL-separated names cannot turn into tar options.
                names=tempfile.TemporaryFile(dir=cache)
                for original,_,_,_ in members:names.write(original.encode()+b'\0')
                names.flush();names.seek(0)
                args+=['--no-recursion','--null','--verbatim-files-from','--files-from=/proc/self/fd/'+str(names.fileno())]
                with z.open('files/system.tar') as contents:
                    with tempfile.TemporaryFile(mode='w+b',dir=cache) as log:
                        p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=log,stderr=log,pass_fds=(names.fileno(),))
                        try:
                            shutil.copyfileobj(contents,p.stdin,4*1024**2);p.stdin.close();code=p.wait()
                        except Exception:
                            p.stdin.close();p.wait();raise
                        if code:
                            log.seek(0);raise ValueError(tr('TAR-Rücksicherung fehlgeschlagen; Teilstand prüfen: ')+log.read(8000).decode(errors='replace'))
                names.close();os.sync()
                print(json.dumps({'done':True,'message':tr('Systemdateien zurückgesichert. fstab/crypttab erhalten; Bootloader und Hardwareanpassungen vor dem Booten prüfen. Zusätzliche Zieldateien wurden nicht gelöscht.')}),flush=True)
if __name__=='__main__':
    try:
        if os.geteuid()!=0:raise ValueError(tr('Administratorfreigabe erforderlich.'))
        if len(sys.argv) not in (5,6):raise ValueError(tr('Archiv, SHA256, Ziel und externe Arbeitsablage erforderlich.'))
        run(*sys.argv[1:])
    except Exception as exc:
        print(json.dumps({'error':str(exc)}),flush=True);sys.exit(1)
