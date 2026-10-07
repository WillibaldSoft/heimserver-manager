"""Logical system restore scopes. No shell commands originate in backup metadata."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import fnmatch
SCOPES={
 'all':tr('Vollständiges Linux-System einschließlich zusätzlicher Daten'),
 'home':tr('Alle Benutzerdateien und Home-Einstellungen'),
 'software':tr('Native Programme, Paketquellen und Zusatzsoftware'),
 'desktop':tr('Desktop-Einstellungen und Benutzerprogramme'),
 'identity':tr('Benutzer, Gruppen, UID/GID und sudo-Regeln'),
 'units':tr('Systemdienste und Aktivierungszustand'),
 'cron':tr('Geplante Aufgaben (Cron)'),
 'config':tr('Systemkonfiguration, Drucker und Geräte-Regeln'),
 'network':tr('Netzwerkprofile und Namensauflösung'),
 'files':tr('Einzelne Datei oder Ordner (in neuen Benutzerordner)')}
PREFIXES={
 'home':['home','root'],
 'software':['usr','opt','bin','sbin','lib','lib64','var/lib/dpkg','var/lib/apt','var/lib/flatpak','var/lib/snapd','var/snap','snap','etc/apt'],
 'desktop':['etc/skel'],
 'identity':['etc/passwd','etc/shadow','etc/group','etc/gshadow','etc/subuid','etc/subgid','etc/sudoers','etc/sudoers.d'],
 'units':['etc/systemd','etc/init.d','etc/rc0.d','etc/rc1.d','etc/rc2.d','etc/rc3.d','etc/rc4.d','etc/rc5.d','etc/rc6.d'],
 'cron':['etc/crontab','etc/cron.d','etc/cron.daily','etc/cron.hourly','etc/cron.weekly','etc/cron.monthly','var/spool/cron'],
 'config':['etc'],
 'network':['etc/NetworkManager','etc/systemd/network','etc/network','etc/netplan','etc/hostname','etc/hosts','etc/resolv.conf','etc/nsswitch.conf']}
def selected(name,scope='all',path=''):
    if scope not in SCOPES:raise ValueError(tr('Ungültiger Rücksicherungsumfang.'))
    if scope=='all':return True
    if scope=='files':
        if not path or path.startswith('/') or '\\' in path or any(x in ('','..','.') for x in path.split('/')):raise ValueError(tr('Relativen Dateipfad im Systemarchiv angeben, z. B. home/benutzer/Dokumente.'))
        return name==path or name.startswith(path+'/')
    if any(name==p or name.startswith(p+'/') for p in PREFIXES[scope]):return True
    if scope in ('software','desktop'):
        return any(fnmatch.fnmatchcase(name,p) for p in ['home/*/.local/*','home/*/.var/app/*','home/*/.config/*','home/*/.themes/*','home/*/.icons/*','home/*/Applications/*','home/*/*.AppImage'])
    return False
