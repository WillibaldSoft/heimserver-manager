"""Explicit local-account operations; passwords only travel through stdin."""
import hashlib,json,threading,re
from pathlib import Path
from . import accounts
from .helpers import sudo_run,sudo_input
PASSWD=Path('/etc/passwd')
GROUP=Path('/etc/group')
LOCK=threading.Lock()
PRIVILEGED={'sudo','admin','wheel','docker','lxd','incus-admin','disk','shadow','adm','systemd-journal','libvirt','kvm'}

def local_groups():
    result=[]
    for line in GROUP.read_text().splitlines():
        fields=line.split(':')
        if len(fields)!=4 or not fields[2].isdigit() or int(fields[2])==0:continue
        result.append(dict(name=fields[0],gid=int(fields[2]),members=fields[3].split(',') if fields[3] else []))
    return sorted(result,key=lambda x:x['name'])

def inspect(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}\$?',str(name)):raise ValueError('Ungültiger lokaler Benutzername.')
    fields=next((line.split(':') for line in PASSWD.read_text().splitlines() if line.split(':',1)[0]==name),None)
    if not fields or len(fields)!=7 or not fields[2].isdigit() or not 1000<=int(fields[2])<60000 or name=='nobody':
        raise ValueError('Nur vorhandene lokale Benutzer mit UID 1000 bis 59999 können hier bearbeitet werden.')
    resolved=accounts.pwd.getpwnam(name)
    if resolved.pw_uid!=int(fields[2]) or resolved.pw_gid!=int(fields[3]):raise ValueError('Die lokale Benutzerkennung ist nicht eindeutig. Bitte am Server prüfen.')
    groups=local_groups();members=[g['name'] for g in groups if name in g['members'] and g['gid']!=int(fields[3])]
    primary=accounts.grp.getgrgid(int(fields[3])).gr_name
    result=dict(name=name,uid=int(fields[2]),gid=int(fields[3]),label=fields[4].split(',')[0],home=fields[5],shell=fields[6],primary=primary,groups=members)
    result['group_catalog']=[(g['name'],g['gid']) for g in groups]
    result['revision']=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
    return result

def apply(name,revision,action,group='',new_password='',confirmation='',acknowledged=False,selected_groups=None):
    with LOCK:
        user=inspect(name)
        if not revision or revision!=user['revision']:raise ValueError('Benutzer oder Gruppen wurden inzwischen geändert. Bitte neu laden.')
        if action=='set_groups':
            available={g['name'] for g in local_groups() if g['name']!=user['primary']}
            if not isinstance(selected_groups,list) or any(not isinstance(g,str) or g not in available for g in selected_groups):
                raise ValueError('Ungültige Gruppenauswahl. Bitte neu laden.')
            wanted=set(selected_groups);current=set(user['groups']) & available
            added=wanted-current;removed=current-wanted
            if (added|removed) & PRIVILEGED and not acknowledged:
                raise ValueError('Die besonderen Rechte dieser Gruppe bitte ausdrücklich bestätigen.')
            if not added and not removed:return 'Die gewünschte Gruppenzuordnung besteht bereits.'
            for group in sorted(added)+sorted(removed):
                command=['usermod','-aG',group,name] if group in added else ['gpasswd','-d',name,group]
                result=sudo_run(command,timeout=20)
                if not result.get('ok') or (group in inspect(name)['groups'])!=(group in added):
                    raise ValueError('Gruppenänderung fehlgeschlagen. Mitgliedschaften neu laden und Dienstrechte am Server prüfen; Teiländerungen sind möglich.')
            return 'Gruppen gespeichert. Neue Rechte gelten nach erneuter Anmeldung.'
        if action in ('add_group','remove_group'):
            available={g['name'] for g in local_groups()}
            if group not in available or group==user['primary']:raise ValueError('Bitte eine vorhandene zusätzliche Gruppe wählen. Die primäre Gruppe bleibt erhalten.')
            if group in PRIVILEGED and not acknowledged:raise ValueError('Die besonderen Rechte dieser Gruppe bitte ausdrücklich bestätigen.')
            current=group in user['groups']
            if (action=='add_group')==current:return 'Die gewünschte Gruppenzuordnung besteht bereits.'
            command=['usermod','-aG',group,name] if action=='add_group' else ['gpasswd','-d',name,group]
            result=sudo_run(command,timeout=20)
            if not result.get('ok'):raise ValueError('Gruppenänderung fehlgeschlagen. Mitgliedschaften neu laden und Dienstrechte am Server prüfen; Teiländerungen sind möglich.')
            if (group in inspect(name)['groups'])!=(action=='add_group'):raise ValueError('Gruppenänderung konnte nicht bestätigt werden. Bitte neu laden.')
            return 'Gruppe geändert. Andere Mitgliedschaften bleiben erhalten. Für laufende Benutzersitzungen ist eine erneute Anmeldung nötig.'
        if action not in ('linux_password','smb_password'):raise ValueError('Unbekannte Benutzeraktion.')
        if not isinstance(new_password,str) or not 8<=len(new_password)<=256 or any(c in new_password for c in ('\n','\r','\0')):
            raise ValueError('Neues Passwort: 8 bis 256 Zeichen, ohne Zeilenumbrüche.')
        if new_password!=confirmation:raise ValueError('Die neuen Passwörter stimmen nicht überein.')
        # Never return subprocess output: PAM or external tools may echo sensitive input.
        try:
            if action=='linux_password':result=sudo_input(['chpasswd'],name+':'+new_password+'\n')
            else:result=sudo_input(['smbpasswd','-s','-a',name],new_password+'\n'+new_password+'\n')
        except Exception:raise ValueError('Passwortänderung nicht bestätigt. Dienstrechte und Passwortvorgaben am Server prüfen.') from None
        if not result.get('ok'):raise ValueError('Passwortänderung nicht bestätigt. Dienstrechte und Passwortvorgaben am Server prüfen.')
        if action=='linux_password':return 'Linux-Passwort geändert. SMB-Passwort unverändert. Bestehende Manager-Sitzungen dieses Linux-Kontos werden ungültig.'
        return 'SMB-Passwort gesetzt; SMB-Zugang aktiviert. Linux-Passwort unverändert. SMB-Client erneut verbinden.'
