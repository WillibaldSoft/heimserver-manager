"""Standalone worker copied outside the installation before replacing the package."""
import contextlib,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,time,urllib.request
from pathlib import Path

def run(package,sha,version):
    package=Path(package)
    with package.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=sha:raise ValueError('Paket-Prüfsumme stimmt nicht mehr.')
    from platform_check import require as require_platform
    target=subprocess.check_output(['/usr/bin/dpkg-deb','-f',str(package),'X-Heimserver-Target'],text=True,timeout=30).strip()
    require_platform(target)
    code=Path(os.environ.get('SERVER_MANAGER_CODE','/opt/server-manager'))
    config=Path(os.environ.get('SERVER_MANAGER_CONFIG','/etc/server-manager'))
    db=Path(os.environ.get('SERVER_MANAGER_DB','/var/lib/server-manager/server-manager.sqlite3'))
    backup=package.parent/'before-update';backup.mkdir(mode=0o700)
    needed=sum(p.stat().st_size for root in (code,config) if root.exists() for p in root.rglob('*') if p.is_file() and not p.is_symlink())
    if shutil.disk_usage(backup).free<needed+(db.stat().st_size if db.exists() else 0)+512*1024**2:
        raise ValueError('Nicht genügend Speicher für die Sicherung vor dem Update.')
    print('Sicherung vor dem Update:',backup,flush=True)
    excluded=[]
    for root,label in ((code,'program'),(config,'config')):
        if package.parent.parent.is_relative_to(root):excluded.append(str(Path(label)/package.parent.parent.relative_to(root)))
    with tarfile.open(backup/'program-config.tar.gz','w:gz') as archive:
        def select(info):
            if any(info.name==prefix or info.name.startswith(prefix+'/') for prefix in excluded):return None
            return None if any(p in ('.git','__pycache__','dist') for p in Path(info.name).parts) else info
        archive.add(code,arcname='program',filter=select)
        if config.exists():archive.add(config,arcname='config',filter=select)
    if db.exists():
        with contextlib.closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as source,contextlib.closing(sqlite3.connect(backup/'manager.sqlite3')) as target:source.backup(target)
    print('Sicherung abgeschlossen. Installation startet; die Weboberfläche wird kurz unterbrochen.',flush=True)
    env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',APT_LISTCHANGES_FRONTEND='none',NEEDRESTART_MODE='l',TERM='dumb')
    cmd=['/usr/bin/apt-get','-o','DPkg::Lock::Timeout=60','-o','Dpkg::Options::=--force-confold','--no-remove','--yes','--reinstall','install',str(package)]
    result=subprocess.run(cmd,stdin=subprocess.DEVNULL,env=env)
    if result.returncode:raise ValueError('APT fehlgeschlagen. Änderungen können teilweise erfolgt sein; keine automatische Rücknahme.')
    installed=subprocess.check_output(['/usr/bin/dpkg-query','-W','-f=${Status} ${Version}','server-manager'],text=True,timeout=15).strip()
    if installed!='install ok installed '+version:raise ValueError('Die Zielversion ist nicht vollständig installiert: '+installed)
    port=int(os.environ.get('SERVER_MANAGER_PORT','9877'))
    for _ in range(30):
        if subprocess.run(['/usr/bin/systemctl','is-active','--quiet','server-manager.service']).returncode==0:
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/api/health',timeout=2) as response:
                    if response.status==200 and json.loads(response.read()).get('version')==version:break
            except OSError:pass
        time.sleep(2)
    else:raise ValueError('Das Paket ist installiert, aber der Manager bestätigt die neue Laufzeitversion noch nicht. Dienstprotokoll prüfen.')
    print('Manager-Update abgeschlossen. Installiert:',version,flush=True)
    return 0

if __name__=='__main__':
    try:raise SystemExit(run(*sys.argv[1:]))
    except Exception as exc:print('Updatefehler:',exc,flush=True);raise SystemExit(1)
