"""Build a generic desktop client, deriving shell logic from the current installer."""
import ast,shlex,shutil,subprocess,tempfile
from pathlib import Path
VERSION='0.4.17'

def legacy_parts(source):
    tree=ast.parse(source.read_text())
    register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
    view=next(n for n in register.body if isinstance(n,ast.FunctionDef) and n.name=='clients_install')
    node=next(n.value for n in view.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='lines' for t in n.targets))
    lines=eval(compile(ast.Expression(node),str(source),'eval'),{'__builtins__':{'str':str},'shlex':shlex,'server_url':'','recover_url':'','token':'','name':'Client','mac':'','mode':'without_server'})
    def section(start):
        index=next(i for i,line in enumerate(lines) if line.startswith(start))+1
        end=lines.index('EOF',index)
        return '\n'.join(lines[index:end])+'\n'
    main=section('cat > "$APPDIR/server-manager-client" ')
    main=main.replace('  auto) auto_start ;;','  mode) case "${2:-}" in with_server|without_server|wake_on_access) set_mode "$2" ;; *) exit 2 ;; esac ;;\n  auto) auto_start ;;')
    units={n:section('cat > "$SYSDIR/'+n+'" ') for n in ['server-manager-client.service','server-manager-client-heartbeat.service','server-manager-client-heartbeat.timer']}
    units={n:s.replace('%h/.local/bin/server-manager-client-heartbeat','/usr/lib/heimserver-manager-client/heartbeat.sh').replace('%h/.local/bin/server-manager-client','/usr/lib/heimserver-manager-client/agent.sh') for n,s in units.items()}
    heartbeat=section('cat > "$APPDIR/server-manager-client-heartbeat" ')
    def bind(text):
        identity='X-HSM-Device: $(/usr/bin/python3 /usr/lib/heimserver-manager-client/device_identity.py device)'
        user='X-HSM-User: $(/usr/bin/python3 /usr/lib/heimserver-manager-client/device_identity.py user)'
        text=text.replace('import json,sys;', 'import json,sys,socket;').replace('d.update(version=', 'd.update(hostname=socket.gethostname(),version=')
        return text.replace('-H "Authorization: Bearer $TOKEN"','-H "Authorization: Bearer $TOKEN" -H "'+identity+'" -H "'+user+'"')
    return bind(main),bind(heartbeat),units

def recovery_archive(root):
    """Portable recovery tools only; never include host configuration or profiles."""
    import io, zipfile
    root = Path(root)
    migration = (root/'tools/backup/migration.sh').read_text().replace('V20 Full System Migration','System sichern & wiederherstellen').replace('V20 benötigt','Systemsicherung benötigt').replace('V20-Komponentenbackup','Systemkomponentenbackup')
    files = {
        'system-migration.sh': (migration.encode(), 0o755),
        'system-recovery.sh': ((root/'client_agent/desktop/system-recovery.sh').read_bytes(), 0o755),
        'client_i18n.py': ((root/'client_agent/desktop/client_i18n.py').read_bytes(), 0o644),
        'client_en.json': ((root/'client_agent/desktop/client_en.json').read_bytes(), 0o644),
        'system_recovery.py': ((root/'client_agent/desktop/system_recovery.py').read_bytes(), 0o644),
        'ANLEITUNG.txt': ((root/'docs/CLIENT_SYSTEM_RECOVERY.txt').read_bytes(), 0o644),
        'LICENSE': ((root/'LICENSE').read_bytes(), 0o644),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, (data, mode) in files.items():
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (0o100000 | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return output.getvalue(), 'System_Wiederherstellung_Linux_' + VERSION + '.zip'

def build(root,output):
    root=Path(root);output=Path(output)
    if output.exists():raise ValueError('Ausgabepaket existiert bereits.')
    main,heartbeat,units=legacy_parts(root/'modules/heimnetz_clients.py')
    with tempfile.TemporaryDirectory(prefix='hsm-client-build-') as temp:
        stage=Path(temp)
        def write(rel,text,mode=0o644):
            p=stage/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);p.chmod(mode)
        write('usr/lib/heimserver-manager-client/client_version.py', 'VERSION = '+repr(VERSION)+'\n')
        migration=(root/'tools/backup/migration.sh').read_text().replace('V20 Full System Migration','System sichern & wiederherstellen').replace('V20 benötigt','Systemsicherung benötigt').replace('V20-Komponentenbackup','Systemkomponentenbackup')
        write('usr/lib/heimserver-manager-client/system-migration.sh',migration,0o755)
        write('usr/lib/heimserver-manager-client/system-recovery.sh',(root/'client_agent/desktop/system-recovery.sh').read_text(),0o755)
        write('usr/lib/heimserver-manager-client/system_recovery.py',(root/'client_agent/desktop/system_recovery.py').read_text())
        for name in ['offline_smb.py','offline_lifecycle.py','offline_systemd.py','offline_mount_admin.py','offline_mounts.py','offline.py','offline_ui.py','client_i18n.py','client_en.json','device_identity.py','incremental.py','system_components.py','system_files.py','core.py','gui.py','backup.py','connection.py','extras_ui.py','https_admin.py','system_recovery_ui.py','system_stream.py','system_https.py','system_restore.py','system_restore_ui.py','system_recovery.py']:
            write('usr/lib/heimserver-manager-client/'+name,(root/'client_agent/desktop'/name).read_text())
        for name in ('offline','connecting','online'):
            target=stage/'usr/lib/heimserver-manager-client/icons'/(name+'.png');target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(root/'client_agent/icons'/(name+'.png'),target);target.chmod(0o644)
        write('usr/lib/heimserver-manager-client/agent.sh',main,0o755)
        write('usr/lib/heimserver-manager-client/heartbeat.sh',heartbeat,0o755)
        for name,text in units.items():write('usr/lib/heimserver-manager-client/units/'+name,text)
        write('usr/bin/heimserver-manager-client','#!/bin/sh\nexec /usr/bin/python3 /usr/lib/heimserver-manager-client/gui.py "$@"\n',0o755)
        entry='[Desktop Entry]\nType=Application\nName=Heimserver Manager Client\nComment=Server availability, wake-up and client settings\nComment[de]=Serverbedarf, Aufwecken und Client-Einstellungen\nExec=heimserver-manager-client\nIcon=network-server\nTerminal=false\nCategories=Network;\n'
        write('usr/share/applications/heimserver-manager-client.desktop',entry)
        autostart=entry.replace('Exec=heimserver-manager-client','Exec=heimserver-manager-client --background --autostart')+'TryExec=heimserver-manager-client\n'
        write('usr/lib/heimserver-manager-client/autostart.desktop',autostart)
        write('etc/xdg/autostart/heimserver-manager-client.desktop',autostart)
        write('usr/share/doc/heimserver-manager-client/HTTPS_SYSTEM_BACKUP.txt',(root/'docs/HTTPS_SYSTEM_BACKUP.txt').read_text())
        write('usr/share/doc/heimserver-manager-client/SYSTEM_RECOVERY.txt',(root/'docs/CLIENT_SYSTEM_RECOVERY.txt').read_text())
        write('usr/share/doc/heimserver-manager-client/README.txt',(root/'client_agent/desktop/README.txt').read_text())
        write('usr/share/doc/heimserver-manager-client/copyright',(root/'LICENSE').read_text())
        write('DEBIAN/control',f'Package: heimserver-manager-client\nVersion: {VERSION}\nSection: net\nPriority: optional\nArchitecture: all\nMaintainer: Heimserver Manager project\nDepends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1, curl, bash, systemd, wakeonlan, openssl, ca-certificates, pkexec, python3-smbc, libsecret-tools, rsync, acl, gnupg, xterm\nDescription: Desktop client for Heimserver Manager\n User-session agent, GTK settings and notification-area indicator.\n')
        # Do not inherit the build host's umask (or TemporaryDirectory's 0700).
        # All package directories must be traversable by desktop users.
        stage.chmod(0o755)
        for directory in stage.rglob('*'):
            if directory.is_dir():directory.chmod(0o755)
        output.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(output)],check=True,capture_output=True)
    return output

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();print(build(args.root,args.output))
