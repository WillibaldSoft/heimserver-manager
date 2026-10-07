"""Upgrade known local curl timers to the scoped authentication client once."""
from pathlib import Path
import os
import re
import shlex
import subprocess
from urllib.parse import urlsplit,parse_qs


def migrate(program_root,config_dir,unit_dir=Path('/etc/systemd/system'),reload_units=True):
    root=Path(program_root);config=Path(config_dir);units=Path(unit_dir)
    changes=[]
    paths=sorted(units.glob('server-manager-appbackup-*.service'))
    paths.append(units/'server-manager-app-update-check.service')
    for path in paths:
        if not path.is_file() or path.is_symlink():continue
        old=path.read_text();lines=old.splitlines(keepends=True);new=[];changed=False
        for line in lines:
            if not line.startswith('ExecStart=/usr/bin/curl '):new.append(line);continue
            args=shlex.split(line[len('ExecStart='):]);url=urlsplit(args[-1])
            if url.scheme!='http' or url.hostname!='127.0.0.1' or url.username or url.password or url.query or url.fragment:
                raise ValueError('Unerwarteter Timer-Aufruf: '+path.name)
            if args[1:4]!=['-fsS','-X','POST']:raise ValueError('Unerwartete Timer-Optionen: '+path.name)
            if url.path=='/apps/update-check/run-all' and len(args)==5:
                action='update-check'
            else:
                match=re.fullmatch(r'/apps/([a-z0-9_]+)/backup',url.path)
                if not match or len(args)!=7 or args[4]!='-d':raise ValueError('Unbekannter Timer-Endpunkt: '+path.name)
                query=parse_qs(args[5]);profile=query.get('profile',[''])[0]
                if set(query)!={'profile'} or not re.fullmatch(r'[a-z0-9_-]+',profile):raise ValueError('Ungültiges Backup-Profil: '+path.name)
                action='backup --app '+match[1]+' --profile '+profile
            # systemd quoting is independent of shell quoting; paths cannot contain controls.
            def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
            new.append('Environment='+quote('SERVER_MANAGER_CONFIG='+str(config))+'\n')
            new.append('ExecStart=/usr/bin/python3 '+quote(root/'tools/authenticated_request.py')+' '+action+' --port '+str(url.port or 80)+'\n')
            changed=True
        if changed:changes.append((path,old,''.join(new)))
    if not changes:return []
    backup=config/'auth-unit-backups';backup.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        for path,old,new in changes:
            saved=backup/path.name
            if not saved.exists():
                saved.write_text(old);saved.chmod(0o600)
            temp=path.with_name('.'+path.name+'.auth-tmp')
            temp.write_text(new);temp.chmod(path.stat().st_mode&0o777);os.replace(temp,path)
        if reload_units:subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
    except Exception:
        for path,old,new in changes:path.write_text(old)
        if reload_units:subprocess.run(['systemctl','daemon-reload'],check=False,timeout=30)
        raise
    return [p.name for p,_,_ in changes]
