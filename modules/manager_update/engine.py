"""Local DEB staging and verification; installation is an independent app job."""
import hashlib,os,re,secrets,shutil,subprocess,time
from pathlib import Path
import server_settings as cfg
from version import VERSION
from tools.platform_check import require as require_platform
ROOT=cfg.STATE_DIR/'manager-updates'
LIMIT=256*1024**2

def installation_problem():
    try:
        result=subprocess.run(['/usr/bin/dpkg-query','-W','-f=${Status}','server-manager'],capture_output=True,text=True,timeout=10)
    except (OSError,subprocess.TimeoutExpired):
        return 'Paketstatus nicht prüfbar. Kein Update gestartet.'
    if result.returncode==0 and result.stdout.strip()=='install ok installed':return ''
    if result.stdout.strip() in ('','install ok not-installed','deinstall ok config-files'):
        return 'Diese Installation wird nicht als DEB verwaltet. Der DEB-Updater kann sie nicht überschreiben. Für die Umstellung ist eine gesicherte Migration nötig; eine Git-Installation weiterhin über ihren Quellstand aktualisieren.'
    return 'Die DEB-Installation ist unvollständig. Zuerst den Paketstatus und das letzte Installationsprotokoll prüfen; kein weiteres Update gestartet.'

def require_package_installation():
    problem=installation_problem()
    if problem:raise ValueError(problem)


def folder(key):
    if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Ungültiges Updatepaket.')
    return ROOT/key

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def inspect(path):
    def field(name):
        result=subprocess.run(['/usr/bin/dpkg-deb','-f',str(path),name],capture_output=True,text=True,timeout=30)
        if result.returncode:raise ValueError('Keine gültige Debian-Paketdatei.')
        return result.stdout.strip()
    package=field('Package');version=field('Version');arch=field('Architecture')
    if package!='server-manager':raise ValueError('Nur das Paket server-manager ist erlaubt.')
    target=field('X-Heimserver-Target');require_platform(target)
    native=subprocess.check_output(['/usr/bin/dpkg','--print-architecture'],text=True,timeout=10).strip()
    if arch not in ('all',native):raise ValueError('Das Paket passt nicht zur Architektur dieses Servers.')
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+:~\-]{0,99}',version):raise ValueError('Ungültige Paketversion.')
    if subprocess.run(['/usr/bin/dpkg','--compare-versions',version,'ge',VERSION],timeout=10).returncode:
        raise ValueError('Ältere Versionen werden nicht über die Weboberfläche installiert.')
    return dict(package=package,version=version,architecture=arch,target=target,sha256=digest(path),size=path.stat().st_size)

def stage(stream,name):
    require_package_installation()
    if not name.lower().endswith('.deb'):raise ValueError('Bitte eine .deb-Datei auswählen.')
    ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Discard abandoned previews after a day; used packages and backups remain.
    for pending in ROOT.iterdir():
        if re.fullmatch('[a-f0-9]{32}',pending.name) and pending.is_dir() and not pending.is_symlink() and not (pending/'claimed').exists() and time.time()-pending.stat().st_mtime>86400:
            shutil.rmtree(pending)
    if shutil.disk_usage(ROOT).free<LIMIT*2:raise ValueError('Zu wenig freier Speicher für den Upload.')
    key=secrets.token_hex(16);dest=folder(key);dest.mkdir(mode=0o700)
    try:
        path=dest/'manager.deb';total=0
        with path.open('xb') as output:
            os.chmod(path,0o600)
            while True:
                chunk=stream.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>LIMIT:raise ValueError('Das Paket überschreitet 256 MiB.')
                output.write(chunk)
            output.flush();os.fsync(output.fileno())
        info=inspect(path);info.update(key=key,created=time.time())
        cfg.atomic(dest/'package.json',info)
        return info
    except BaseException:
        shutil.rmtree(dest);raise

def validate(plan):
    require_package_installation()
    if not isinstance(plan,dict):raise ValueError('Bitte das Paket erneut hochladen.')
    path=folder(plan.get('key',''))/'manager.deb'
    if time.time()-plan.get('created',0)>3600:raise ValueError('Update-Vorschau abgelaufen. Bitte erneut hochladen.')
    info=inspect(path)
    if any(info[k]!=plan.get(k) for k in info):raise ValueError('Das Updatepaket wurde verändert. Bitte erneut hochladen.')
    return path

def execute(plan):
    path=validate(plan)
    # The copied worker has no application imports and survives package replacement.
    worker=path.parent/'update-worker.py'
    shutil.copyfile(Path(__file__).with_name('worker.py'),worker);os.chmod(worker,0o600)
    shutil.copyfile(Path(__file__).resolve().parents[2]/'tools/platform_check.py',path.parent/'platform_check.py')
    env=dict(os.environ,SERVER_MANAGER_CODE=str(Path(__file__).resolve().parents[2]))
    result=subprocess.run(['/usr/bin/python3',str(worker),str(path),plan['sha256'],plan['version']],env=env)
    if result.returncode:raise ValueError('Manager-Update fehlgeschlagen. Updateprotokoll und Sicherung prüfen.')


def claim(plan):
    path=validate(plan)
    try:
        with (path.parent/'claimed').open('x') as marker:marker.write(str(time.time()))
    except FileExistsError:raise ValueError('Dieses Paket wurde bereits für ein Update verwendet. Bitte erneut hochladen.') from None
