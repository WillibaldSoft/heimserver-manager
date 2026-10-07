"""Scoped Apache site editing with reviewed diffs, atomic writes and rollback."""
from pathlib import Path
import difflib
import os
import re
import tempfile
from . import engine as e

MAX_BYTES=256*1024

def site_path(name):
    name=e.identifier(name)
    if not name.endswith('.conf'):raise e.Problem('Nur Apache-Website-Dateien mit Endung .conf sind bearbeitbar.')
    base=e.APACHE/'sites-available';path=base/name
    if base.is_symlink() or path.is_symlink() or not path.is_file():raise e.Problem('Keine reguläre Apache-Website-Datei gefunden.')
    if path.stat().st_size>MAX_BYTES:raise e.Problem('Website-Konfiguration ist für diesen Editor zu groß.')
    return path

def link_state(name):
    file=site_path(name);link=e.APACHE/'sites-enabled'/name
    if link.is_symlink():
        if link.resolve()!=file.resolve():raise e.Problem('Aktivierungslink verweist auf eine andere Datei.')
        return os.readlink(link)
    if link.exists():raise e.Problem('Aktivierung ist kein Website-Link; manuell prüfen.')
    return None

def read(name):
    path=site_path(name);text=path.read_text()
    return dict(name=name,content=text,base_hash=e.local_hash(path),enabled=link_state(name) is not None)

def included_files():
    result=e.run(['apache2ctl','-t','-D','DUMP_INCLUDES'])
    found=[]
    for line in (result.stdout+'\n'+result.stderr).splitlines():
        match=re.match(r'^\s*\((?:\d+|\*)\)\s+(/.+?)\s*$',line)
        if match:found.append(Path(match[1]).resolve())
    if not found:raise e.Problem('Apache-Einbindungen konnten nicht zuverlässig ermittelt werden.')
    return set(found)

def plan(action,data):
    row=read(data.get('site',''))
    if data.get('base_hash')!=row['base_hash']:raise e.Problem('Datei wurde inzwischen geändert. Editor neu öffnen.')
    content=str(data.get('content','')).replace('\r\n','\n')
    if not content.strip() or '\x00' in content or len(content.encode())>MAX_BYTES:raise e.Problem('Gültige Konfiguration mit höchstens 256 KiB eingeben.')
    enabled=data.get('enabled')
    if enabled not in ('yes','no'):raise e.Problem('Website-Status auswählen.')
    if content==row['content'] and (enabled=='yes')==row['enabled']:raise e.Problem('Keine Änderung vorhanden.')
    name=row['name'];path=site_path(name)
    # A site loaded through another Include cannot safely be disabled by its symlink.
    sources=included_files()
    link=e.APACHE/'sites-enabled'/name
    if enabled=='no':
        for source in sources:
            if source==path.resolve():continue
            text=source.read_text(errors='replace')
            for line in text.splitlines():
                m=re.match(r'^\s*Include(?:Optional)?\s+["\']?([^"\'\s]+)',line,re.I)
                if m and ('sites-available' in m[1] or name in m[1]):
                    raise e.Problem('Direkte Apache-Einbindung zuerst anpassen: '+str(source))
    snapshot={'file':row['base_hash'],'link':link_state(name),'mode':path.stat().st_mode & 0o777,
              'includes':{str(p):e.local_hash(p) for p in sorted(sources)}}
    diff=''.join(difflib.unified_diff(row['content'].splitlines(True),content.splitlines(True),fromfile=name+' (bisher)',tofile=name+' (neu)'))
    steps=['Website: '+name,'Status: '+('Aktiv' if row['enabled'] else 'Inaktiv')+' → '+('Aktiv' if enabled=='yes' else 'Inaktiv'),
           'Originaldatei und Aktivierungszustand im Auftragsordner sichern.',
           'Neue Konfiguration prüfen; bei Fehlern Originaldatei und Aktivierung wiederherstellen.',
           'Apache nach erfolgreicher Prüfung neu laden.' if enabled=='yes' or row['enabled'] else 'Die Website bleibt deaktiviert.']
    return dict(action=action,data={'site':name,'base_hash':row['base_hash'],'content':content,'enabled':enabled},snapshot=snapshot,steps=steps,diff=diff)

def write_file(path,content,mode,uid,gid):
    fd,tmp=tempfile.mkstemp(prefix='.server-manager-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
            os.fchmod(stream.fileno(),mode)
            if os.geteuid()==0:os.fchown(stream.fileno(),uid,gid)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def execute(p,folder):
    data=p['data'];name=data['site'];path=site_path(name);link=e.APACHE/'sites-enabled'/name
    original=path.read_bytes();meta=path.stat();old_link=link_state(name)
    backup=folder/'apache-site-before.conf';backup.write_bytes(original);backup.chmod(0o600)
    e.atomic(folder/'apache-site-before.json',{'site':name,'link':old_link,'mode':meta.st_mode & 0o777,'uid':meta.st_uid,'gid':meta.st_gid})
    reload_attempted=False
    try:
        write_file(path,data['content'].encode(),meta.st_mode & 0o777,meta.st_uid,meta.st_gid)
        # Validate even inactive edited sites by temporarily including them, without reload.
        if not link.is_symlink():link.symlink_to('../sites-available/'+name)
        e.run(['apache2ctl','configtest'])
        if data['enabled']=='no':link.unlink()
        e.run(['apache2ctl','configtest'])
        if data['enabled']=='no' and path.resolve() in included_files():raise e.Problem('Website wird zusätzlich über eine andere Include-Anweisung geladen.')
        if old_link is not None or data['enabled']=='yes':
            reload_attempted=True;e.run(['systemctl','reload','apache2.service'])
    except Exception as exc:
        write_file(path,original,meta.st_mode & 0o777,meta.st_uid,meta.st_gid)
        if link.is_symlink():link.unlink()
        if old_link is not None:link.symlink_to(old_link)
        if reload_attempted:
            try:e.run(['apache2ctl','configtest']);e.run(['systemctl','reload','apache2.service'])
            except Exception as rollback:raise e.Problem('Datei zurückgesetzt, Apache-Wiederherstellung fehlgeschlagen: '+str(rollback)) from exc
        raise e.Problem('Änderung verworfen; Originaldatei und Aktivierung wiederhergestellt: '+str(exc)) from exc
    return {'message':'Website '+name+' gespeichert und '+('aktiviert.' if data['enabled']=='yes' else 'deaktiviert.'),'backup':str(backup)}
