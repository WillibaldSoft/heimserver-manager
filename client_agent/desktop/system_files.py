"""Unprivileged selective file restore from a system ZIP, never to existing targets."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,json,os,shutil,tarfile,tempfile,zipfile
from pathlib import Path
from system_restore import normalized,inspect,RESERVE
import system_components

def restore(source,sha,target,cache,selection,progress=lambda s:None):
    target=Path(target).absolute();cache=Path(cache)
    system_components.selected(selection,'files',selection)
    if target.exists() or '..' in target.parts or not target.parent.is_dir() or any(p.is_symlink() for p in target.parents):raise ValueError(tr('Neuen Zielordner ohne symbolische Links wählen.'))
    size=Path(source).stat().st_size
    if shutil.disk_usage(cache).free<size+RESERVE:raise ValueError(tr('Externe Arbeitsablage benötigt Platz für die Prüfkopie.'))
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as src,tempfile.TemporaryFile(dir=cache) as secure:
        h=hashlib.sha256();count=0
        for data in iter(lambda:src.read(4*1024**2),b''):
            count+=len(data)
            if count>size or shutil.disk_usage(cache).free<len(data)+RESERVE:raise ValueError(tr('Speicherreserve überschritten.'))
            secure.write(data);h.update(data)
        if count!=size or h.hexdigest()!=sha:raise ValueError(tr('Prüfsumme stimmt nicht.'))
        secure.seek(0)
        with zipfile.ZipFile(secure) as z:
            if len(z.namelist())!=len(set(z.namelist())):raise ValueError(tr('Doppelte ZIP-Einträge.'))
            if z.getinfo('hsm-backup.json').file_size>65536 or json.loads(z.read('hsm-backup.json')).get('scope') not in ('linux-system-tar-v1','linux-system-tar-v2'):raise ValueError(tr('Kein Systemarchiv.'))
            members=[]
            with z.open('files/system.tar') as f:
                total,_=inspect(f,target,'files',selection,members)
                while f.read(4*1024**2):pass
            if not members:raise ValueError(tr('Auswahl nicht im Systemarchiv gefunden.'))
            if shutil.disk_usage(target.parent).free<total+RESERVE:raise ValueError(tr('Zu wenig freier Zielplatz.'))
            target.mkdir(mode=0o700);restored=0;skipped=0
            with z.open('files/system.tar') as f,tarfile.open(fileobj=f,mode='r|') as tar:
                for member in tar:
                    name=normalized(member.name)
                    if not system_components.selected(name,'files',selection):continue
                    if not (member.isfile() or member.isdir()):skipped+=1;continue
                    path=target/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    if member.isdir():path.mkdir(mode=0o700,exist_ok=True);continue
                    with tar.extractfile(member) as contents,path.open('xb') as out:
                        for data in iter(lambda:contents.read(4*1024**2),b''):
                            if shutil.disk_usage(target.parent).free<len(data)+RESERVE:raise ValueError(tr('Zielspeicherreserve erreicht; Teilstand bleibt im neuen Ordner.'))
                            out.write(data)
                    os.chmod(path,member.mode&0o700 or 0o600);os.utime(path,(member.mtime,member.mtime));restored+=1
                    progress(tr('Dateien zurückgesichert: ')+str(restored))
            return tr('Dateien im neuen Ordner: ')+str(target)+tr('. Wiederhergestellt: ')+str(restored)+tr('. Links/Spezialdateien ausgelassen: ')+str(skipped)+tr('. Keine Systemrechte übernommen.')
