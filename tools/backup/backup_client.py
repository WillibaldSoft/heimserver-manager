#!/usr/bin/env python3
"""Portable home backup on a mounted SMB share; no account renumbering."""
import contextlib,threading,time
import argparse,datetime,hashlib,json,os,pwd,re,shutil,subprocess,sys,tarfile,uuid
from pathlib import Path, PurePosixPath
BASE=Path(__file__).resolve().parent

def identifier(s):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',s):raise ValueError('Ungültige Rechner-/Benutzerkennung.')
    return s

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def direct(path):
    p=Path(path).absolute()
    if '..' in p.parts or any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('Keine symbolischen Links oder .. im Zielpfad verwenden.')
    return p

def repository(path):
    p=direct(path)
    if not p.is_dir():raise ValueError('Backup-Freigabe ist nicht verbunden.')
    kind=subprocess.check_output(['findmnt','-n','-o','FSTYPE','--target',str(p)],text=True).strip()
    if kind not in ('cifs','smb3','fuse.gvfsd-fuse'):raise ValueError('Ziel muss eine eingebundene SMB-Freigabe sein; Abbruch verhindert Sicherung auf dem lokalen Systemlaufwerk.')
    return p

def mount(config):
    share=config['share']
    if not re.fullmatch(r'//[A-Za-z0-9.-]+/[A-Za-z0-9_ -]+',share):raise ValueError('Ungültige SMB-Adresse.')
    host,name=share[2:].split('/',1)
    if os.geteuid()!=0 and shutil.which('gio'):
        subprocess.run(['gio','mount','smb://'+host+'/'+name],check=False)
        root=Path('/run/user')/str(os.getuid())/'gvfs'
        for p in root.glob('smb-share:*'):
            if ('server='+host) in p.name and ('share='+name.lower()) in p.name.lower():return repository(p)
        raise ValueError('Freigabe nicht gefunden. Mit dem Dateimanager verbinden und --repository angeben.')
    target=Path('/mnt/server-manager-backup');target.mkdir(exist_ok=True)
    if not os.path.ismount(target):
        user=input('SMB-Benutzer: ').strip()
        if not re.fullmatch(r'[A-Za-z0-9_.@-]+',user):raise ValueError('Ungültiger SMB-Benutzer.')
        subprocess.run(['mount','-t','cifs',share,str(target),'-o','vers=3.0,nosuid,nodev,noexec,username='+user],check=True)
    return repository(target)

def mounted_below(source):
    result=[]
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        name=re.sub(r'\\([0-7]{3})',lambda m:chr(int(m[1],8)),line.split()[4])
        p=Path(name)
        if p!=source and p.is_relative_to(source):result.append('./'+str(p.relative_to(source)))
    return result

def backup(repo,config,source,kind="home"):
    source=direct(source)
    if not source.is_dir() or source==Path('/'):raise ValueError('Ein vorhandenes Benutzerverzeichnis angeben, nicht /.')
    if repo.is_relative_to(source):raise ValueError('Backupziel liegt innerhalb der Quelle.')
    user=identifier(config['user']);client=identifier(config['client'])
    base=direct(repo/'linux-client-backup'/client/user);base.mkdir(parents=True,exist_ok=True)
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
    job=base/('.partial-'+stamp);job.mkdir(mode=0o700)
    archive=job/'home.tar'
    args=['tar','--create','--file',str(archive),'--format=pax','--acls','--xattrs','--numeric-owner','--one-file-system','--exclude=./.cache','--exclude=./.local/share/Trash','--exclude=./.gvfs']
    for value in mounted_below(source):args+=['--exclude='+value]
    print('Sicherung läuft:',source,'→',base,flush=True)
    try:
        subprocess.run(args+['-C',str(source),'--','.'],check=True)
        info=source.stat()
        metadata=dict(format=1,kind=kind,client=client,user=user,source_uid=info.st_uid,source_gid=info.st_gid,server_identity=config.get('server_identity'),created=datetime.datetime.now().astimezone().isoformat(),sha256=digest(archive),archive='home.tar')
        (job/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
        verify(job)
        final=base/stamp;job.rename(final)
        print('Sicherung abgeschlossen und geprüft:',final)
        return final
    except BaseException:
        print('Sicherung unvollständig; kein gültiger Sicherungsstand:',job,file=sys.stderr)
        raise

def verify(snapshot):
    snapshot=direct(snapshot)
    mf=snapshot/'manifest.json';archive=snapshot/'home.tar'
    direct(mf);direct(archive)
    m=json.loads(mf.read_text())
    expected='system.tar' if m.get('kind')=='server-config' else 'home.tar'
    if m.get('format')!=1 or m.get('kind') not in ('home','migration','server-config') or m.get('archive')!=expected:raise ValueError('Unbekanntes Sicherungsformat.')
    archive=direct(snapshot/expected)
    if digest(archive)!=m.get('sha256'):raise ValueError('Prüfsumme stimmt nicht. Nicht wiederherstellen.')
    with tarfile.open(archive,'r:') as tf:
        links=set();names=[];hard=[]
        for member in tf:
            p=PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):raise ValueError('Unzulässiger Archiveintrag: '+member.name)
            name=str(p);names.append(name)
            if member.issym():links.add(name)
            if member.islnk():hard.append(member.linkname)
        for name in names+hard:
            p=PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or any(str(a) in links for a in p.parents) or (name in hard and str(p) in links):raise ValueError('Unsicherer Link im Archiv.')
    return m

def restore(snapshot,target,preserve=False):
    snapshot=direct(snapshot);m=verify(snapshot);target=direct(target)
    if target.exists():raise ValueError('Restore-Ziel muss neu sein. Vorhandene Benutzerdateien werden nicht überschrieben.')
    if not target.parent.is_dir():raise ValueError('Übergeordneter Restore-Ordner fehlt.')
    print('Quelle:',snapshot,'\nNeues Ziel:',target,'\nGesicherte UID/GID:',m['source_uid'],m['source_gid'])
    if preserve and os.geteuid()!=0:raise ValueError('Originale IDs/ACLs benötigen sudo.')
    if input('Wiederherstellung in diesen neuen Ordner starten? Eingabe JA: ')!='JA':return
    target.mkdir(mode=0o700)
    args=['tar','--extract','--file',str(snapshot/m['archive']),'--directory',str(target),'--delay-directory-restore','--no-overwrite-dir']
    args+=['--numeric-owner','--same-owner','--same-permissions','--acls','--xattrs'] if preserve else ['--no-same-owner','--no-same-permissions']
    subprocess.run(args,check=True)
    print('Wiederhergestellt:',target)
    if not preserve:print('Dateien gehören dem ausführenden Benutzer; Original-ACLs wurden nicht übernommen.')

@contextlib.contextmanager
def activity(base):
    base=direct(base);base.mkdir(parents=True,exist_ok=True)
    lease=base/('.active-'+uuid.uuid4().hex)
    stop=threading.Event()
    def touch():
        # The empty marker contains no secrets; exclusive creation rejects links.
        with lease.open('xb'):pass
    touch()
    def heartbeat():
        while not stop.wait(30):
            try:os.utime(lease,None,follow_symlinks=False)
            except OSError:print('Backup-Verbindung unterbrochen: Schlafschutz kann auslaufen.',file=sys.stderr)
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:yield
    finally:
        stop.set();thread.join(timeout=2)
        try:lease.unlink()
        except OSError:pass

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['backup','list','verify','restore','identity','mount','migration'])
    p.add_argument('--config',type=Path,default=BASE/'client.json');p.add_argument('--repository',type=Path)
    p.add_argument('--source',type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--target',type=Path)
    p.add_argument('--server');p.add_argument('--workdir',type=Path);p.add_argument('--live',action='store_true');p.add_argument('--local-user')
    p.add_argument('--preserve-ids',action='store_true');a=p.parse_args()
    config=json.loads(a.config.read_text())
    if a.action=='identity':
        current=pwd.getpwuid(os.getuid());print(json.dumps(dict(server=config.get('server_identity'),local=dict(user=current.pw_name,uid=current.pw_uid,gid=current.pw_gid)),ensure_ascii=False,indent=2));print('Nur Vergleich. Benutzerkonten und Gruppen bleiben unverändert.');return
    repo=repository(a.repository) if a.repository else mount(config)
    if a.action=='mount':print(repo);return
    base=direct(repo/'linux-client-backup'/identifier(config['client'])/identifier(config['user']))
    with activity(base):
        if a.server:
            if a.action in ('backup','migration'):raise ValueError('--server ist nur zum Lesen/Wiederherstellen vorhandener Server-Sicherungen vorgesehen.')
            base=direct(repo/'linux-server-backup'/identifier(a.server))
        if a.action=='migration':
            if os.geteuid()!=0:raise ValueError('Das V20-Migrationswerkzeug benötigt sudo.')
            if not a.workdir or not a.source:raise ValueError('--workdir (lokaler Arbeitsordner) und --source (ursprüngliches Home) angeben.')
            work=direct(a.workdir);source=direct(a.source)
            if not work.is_dir() or work==source or work.is_relative_to(source) or source.is_relative_to(work):raise ValueError('Getrennten vorhandenen Arbeitsordner außerhalb des Home verwenden.')
            fs=subprocess.check_output(['findmnt','-n','-o','FSTYPE','--target',str(work)],text=True).strip()
            if fs not in ('ext2','ext3','ext4','xfs','btrfs','f2fs'):raise ValueError('Arbeitsordner benötigt ein lokales Linux-Dateisystem.')
            user=identifier(a.local_user or config['user'])
            subprocess.run(['bash',str(BASE/'migration.sh'),'--live' if a.live else '--normal','--source-home',str(source),'--source-user',user,'--client-id',identifier(config['client']),'--storage-dir',str(work)],check=True)
            if input('Arbeitsordner jetzt als Migrationsarchiv auf dem Server sichern? JA: ')=='JA':backup(repo,config,work,kind='migration')
        elif a.action=='backup':
            print('Zuordnung:',config['user'],'auf Server; Quelldaten:',a.source or Path.home())
            backup(repo,config,a.source or Path.home())
        elif a.action=='list':
            for entry in sorted(base.iterdir()) if base.exists() else []:
                if not entry.name.startswith('.') and not entry.is_symlink() and (entry/'manifest.json').is_file():print(entry)
        else:
            if not a.snapshot:raise ValueError('--snapshot angeben (mit list anzeigen).')
            snapshot=direct(a.snapshot)
            if snapshot.parent!=base:raise ValueError('Sicherungsstand gehört nicht zu diesem Rechner/Benutzer.')
            if a.action=='verify':print('Geprüft:',verify(snapshot))
            elif not a.target:raise ValueError('--target für einen neuen Restore-Ordner angeben.')
            else:restore(snapshot,a.target,a.preserve_ids)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.SubprocessError,tarfile.TarError,KeyError) as e:print('Fehler:',e,file=sys.stderr);sys.exit(1)
