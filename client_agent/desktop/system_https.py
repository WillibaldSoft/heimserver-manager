"""Complete logical system snapshots, deduplicated HTTPS transport, bounded memory."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,subprocess,threading,zipfile
import backup,core
from incremental import Stream
HELP=tr('''LINUX-SYSTEMSICHERUNG ÜBER HTTPS
Jeder Stand ist ein vollständiges logisches ZIP mit system.tar. Der Server speichert
identische 4-MiB-Blöcke nur einmal pro Konto/Agentenprofil. Folgeläufe lesen die
Quellen erneut, übertragen aber nur neue Blöcke. Einfügungen können nachfolgende
Blockgrenzen verschieben und zusätzliche Übertragungen verursachen.

Gesichert: Systemdateien, installierte native Programme, APT-Quellen/Schlüssel,
Flatpak/Snap-Dateien, alle Benutzer-Homes einschließlich AppImages, pip/pipx/npm,
Desktop-Einstellungen, UID/GID, ACLs/xattrs, lokale Programme, systemd-Units samt
Aktivierungslinks, Cron, Drucker/Udev und weitere Konfigurationen. Zusätzliche
lokale Datenträger müssen ausdrücklich ausgewählt werden. Netzwerkprofile mit
Zugangsdaten nur nach Auswahl. Das Backup enthält vertrauliche Systemdaten!

system-inventory.json dokumentiert Pakete, Quellen der Flatpak-Anwendungen,
Benutzerinventare, Mounts, Partitionsinformationen und Erfassungsfehler.
Programme werden beim vollständigen Systemrestore als gesicherte Dateien samt
Paketdatenbank wiederhergestellt; keine erneute Installation aus dem Internet.

Vollständige Rücksicherung aus Live-USB in vorbereitetes Linux-Ziel. Zielpartitionen
vorher einhängen. Verteilung darf geändert werden; /etc/fstab und /etc/crypttab
bleiben vom Ziel erhalten. Bootloader/Partitionierung separat einrichten.
Kein sektorweises Festplattenabbild und keine automatische Migration zwischen
Distributionen. Zusätzliche Dateien auf dem Ziel werden nicht gelöscht.
Laufende Datenbanken, VMs und Container vorher geordnet beenden; Dateikopie einer
laufenden Anwendung ist nicht automatisch konsistent. Server-Blöcke nicht manuell
löschen: mehrere Sicherungsstände können dieselben Blöcke verwenden.
''')
def create(progress=lambda text:None,options=None):
    options=options or {};cfg=core.validate(core.load())
    if backup.ACCOUNT and not backup.ACCOUNT[2].get('backup'):raise core.Error(tr('Nur Lesen: neue Systemsicherung nicht freigegeben.'))
    if not cfg['SERVER_URL'].startswith('https://'):raise core.Error(tr('Systemsicherung benötigt HTTPS mit gültigem Zertifikat.'))
    if 'system-cas-v1' not in backup.call('list').get('capabilities',[]):raise core.Error(tr('Manager benötigt die Erweiterung für inkrementelle Systemsicherungen.'))
    helper='/usr/lib/heimserver-manager-client/system_stream.py';choice=json.dumps(options)
    progress(tr('System- und Softwareinventar erfassen (Administratorfreigabe) …'))
    result=subprocess.run(['pkexec','/usr/bin/python3',helper,'inventory',choice],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode:raise core.Error(tr('Inventar konnte nicht erfasst werden: ')+result.stderr.decode(errors='replace')[-3000:])
    inventory=json.loads(result.stdout)
    sid=backup.call('cas-begin',dict(name='Linux-System · inkrementell'))['id']
    process=subprocess.Popen(['pkexec','/usr/bin/python3',helper,'backup',choice],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    errors=[]
    def drain():
        for line in iter(process.stderr.readline,b''):
            errors.append(line.decode(errors='replace').strip());del errors[:-20]
    reader=threading.Thread(target=drain,daemon=True);reader.start();stream=Stream(sid,progress)
    try:
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED,allowZip64=True) as archive:
            entry=zipfile.ZipInfo('files/system.tar',(1980,1,1,0,0,0))
            with archive.open(entry,'w',force_zip64=True) as out:
                for chunk in iter(lambda:process.stdout.read(backup.CHUNK),b''):out.write(chunk)
            code=process.wait();reader.join()
            if code:raise core.Error(tr('Systemdateien geändert oder nicht lesbar; Sicherung nicht freigegeben. ')+ '\n'.join(errors))
            for name,value in [('files/ANLEITUNG.txt',HELP),('files/system-inventory.json',json.dumps(inventory,sort_keys=True)),('hsm-backup.json',json.dumps(dict(format='client-zip-v1',scope='linux-system-tar-v2')))]:
                archive.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),value)
        progress(tr('Sicherungsstand am Server prüfen …'));stream.finish()
        failed=sum(1 for x in inventory['commands'].values() if x['status']=='failed')+sum(1 for user in inventory.get('users',{}).values() for x in user.values() if x['status']=='failed')
        return tr('Systemstand abgeschlossen. Neu: ')+str(stream.sent//1024**2)+tr(' MiB; wiederverwendet: ')+str(stream.reused//1024**2)+tr(' MiB. Inventarfehler: ')+str(failed)+tr(' (Details in system-inventory.json).')
    finally:
        stream.buffer.clear();process.stdout.close()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:pass
        reader.join(timeout=5)
