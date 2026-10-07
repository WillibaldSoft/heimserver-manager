#!/usr/bin/env python3
"""Build Server_Manager.deb without root, network access or local state files."""
import argparse,ast,hashlib,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
try:from .platform_check import PROFILES
except ImportError:from platform_check import PROFILES

ROOT_FILES={'LICENSE','LICENSE_NOTICE.md','THIRD_PARTY_NOTICES.md','app.py','authentication.py','responsive_ui.py','i18n.py','ui_translation.py','server_settings.py','version.py','manager_proxy.py','config.py','presence_engine.py','README.md','CHANGELOG.md'}
SOURCE_DIRS={'modules','migrations','templates','static','tools','client_agent','docs','packaging','tests'}
EXTENSIONS={'.py','.sql','.html','.css','.js','.sh','.md','.txt','.svg','.png','.ico','.jpg','.woff','.woff2'}
HELPERS={'server-manager-update-helper','server-manager-storage-helper','server-manager-server-helper','server-manager-shares-helper'}
PACKAGING={'server-manager.pam','copyright','server-manager.service','server-manager-https-renew.service','server-manager-https-renew.timer','server-manager.env','preinst','postinst','prerm','postrm','config','templates'}

def source_files(root):
    # Explicit release inventory: never sweep local notes or credentials into a package.
    inventory=root/'packaging/source-manifest.json'
    if not inventory.is_file():raise ValueError('Release-Dateiliste fehlt: packaging/source-manifest.json')
    allowed=set(json.loads(inventory.read_text()))
    for path in sorted(root.rglob('*')):
        rel=path.relative_to(root)
        if str(rel) not in allowed:continue
        if any(part.startswith('.') or '.bak' in part or '.backup' in part or part in ('__pycache__','node_modules','backups','snapshots','dist') for part in rel.parts):continue
        if path.is_symlink() or not path.is_file() or '.bak' in path.name or '.backup' in path.name:continue
        permitted=(len(rel.parts)==1 and path.name in ROOT_FILES) or (len(rel.parts)>1 and rel.parts[0] in SOURCE_DIRS and path.suffix in EXTENSIONS)
        permitted|=str(rel.parent)=='tools/helpers' and path.name in HELPERS
        permitted|=str(rel.parent)=='packaging/debian' and path.name in PACKAGING
        permitted |= str(rel) in ('packaging/source-manifest.json','locales/en.json','locales/de.json','client_agent/desktop/client_en.json','client_agent/windows/client_en.json','docs/en/translation-manifest.json')
        permitted |= str(rel.parent)=='client_agent/windows' and (path.suffix in {'.cs','.ps1','.manifest'} or path.name in {'HeimserverManagerClient.exe','release.json'})
        permitted |= str(rel) in ('modules/fotolabor/vendor/makeself/COPYING','modules/fotolabor/vendor/makeself/copyright')
        if permitted:yield path

def validate_local_imports(root,sources):
    """Reject source manifests that omit statically imported local modules."""
    included=set(sources)
    missing=set()
    for source in sources:
        if source.suffix!='.py':continue
        parent=list(source.relative_to(root).parent.parts)
        for node in ast.walk(ast.parse(source.read_text(),filename=str(source))):
            candidates=[]
            if isinstance(node,ast.ImportFrom):
                prefix=parent[:len(parent)-node.level+1] if node.level else []
                base=prefix+(node.module.split('.') if node.module else [])
                candidates.append(base)
                candidates.extend(base+alias.name.split('.') for alias in node.names if alias.name!='*')
            elif isinstance(node,ast.Import):candidates=[alias.name.split('.') for alias in node.names]
            for parts in candidates:
                if not parts:continue
                base=root.joinpath(*parts)
                for target in (base.with_suffix('.py'),base/'__init__.py'):
                    if target.is_file() and target not in included:
                        missing.add(str(source.relative_to(root))+' -> '+str(target.relative_to(root)))
    if missing:raise ValueError('Lokale Python-Importe fehlen in der Release-Dateiliste: '+ '; '.join(sorted(missing)))

def version(root):
    tree=ast.parse((root/'version.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in node.targets):
            value=ast.literal_eval(node.value)
            if re.fullmatch(r'[0-9]+(?:\.[0-9]+)*(?:-[0-9][a-zA-Z0-9.+~]*)?',value):return value
    raise ValueError('Keine gültige Produktversion in version.py.')

def build(root,output,revision=None,target="debian13"):
    if target not in PROFILES:raise ValueError("Unbekannte Zielplattform")
    root=root.resolve();output=output.resolve()
    try:from .check_documentation import check as check_documentation
    except ImportError:from check_documentation import check as check_documentation
    check_documentation(root)
    current=version(root)
    base,_,existing_revision=current.partition('-')
    revision=revision if revision is not None else (existing_revision or '1')
    package_version=base+'-'+revision
    if package_version!=current:raise ValueError('Paketversion muss version.py entsprechen; Version und Dokumentation vor dem Build gemeinsam aktualisieren.')
    if not re.fullmatch(r'[0-9][a-zA-Z0-9.+~]*',revision):raise ValueError('Ungültige Debian-Revision.')
    if not shutil.which('dpkg-deb'):raise ValueError('dpkg-deb fehlt. Paket dpkg installieren.')
    sources=list(source_files(root))
    validate_local_imports(root,sources)
    needed=['LICENSE','LICENSE_NOTICE.md','THIRD_PARTY_NOTICES.md','packaging/debian/copyright','app.py','authentication.py','responsive_ui.py','i18n.py','ui_translation.py','server_settings.py','version.py','tools/package_first_start.py','modules/downloads/plugin.py','modules/web_security/plugin.py']
    for rel in needed:
        if root/rel not in sources:raise ValueError('Erforderlicher Quellcode fehlt: '+rel)
    epoch=int(os.environ.get('SOURCE_DATE_EPOCH','0'))
    with tempfile.TemporaryDirectory(prefix='server-manager-deb-') as temp:
        stage=Path(temp)/'package';program=stage/'opt/server-manager';program.mkdir(parents=True)
        manifest={}
        for source in sources:
            relative=source.relative_to(root);dest=program/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest);dest.chmod(0o755 if str(relative.parent)=='tools/helpers' or source.suffix=='.sh' else 0o644)
            if str(relative)=='version.py':
                dest.write_text('"""Version of this Debian package."""\nVERSION = '+repr(package_version)+'\n')
            manifest[str(relative)]=hashlib.sha256(dest.read_bytes()).hexdigest()
        marker=program/'package-target.json';marker.write_text(json.dumps({'target':target,'experimental':PROFILES[target]['experimental']},sort_keys=True)+'\n')
        manifest['package-target.json']=hashlib.sha256(marker.read_bytes()).hexdigest()
        (program/'package-manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        for source,destination_name in [('server-manager.pam','etc/pam.d/server-manager'),('server-manager-https-renew.service','usr/lib/systemd/system/server-manager-https-renew.service'),('server-manager-https-renew.timer','usr/lib/systemd/system/server-manager-https-renew.timer'),('server-manager.service','usr/lib/systemd/system/server-manager.service'),('server-manager.env','etc/server-manager/server-manager.env')]:
            dest=stage/destination_name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/'packaging/debian'/source,dest);dest.chmod(0o644)
        desktop=stage/'usr/share/applications/heimserver-manager.desktop'
        desktop.parent.mkdir(parents=True,exist_ok=True)
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Heimserver Manager\nName[en]=Home Server Manager\nComment=Heimserver im Browser verwalten\nComment[en]=Manage your home server in a browser\nExec=/usr/bin/python3 /opt/server-manager/tools/manager_desktop.py\nIcon=network-server\nTerminal=false\nCategories=System;Settings;\nKeywords=Server;Backup;Network;\n')
        port=stage/'usr/share/server-manager/desktop-port';port.parent.mkdir(parents=True,exist_ok=True);port.write_text('9877\n')
        metadata=stage/'usr/share/metainfo/heimserver-manager.metainfo.xml';metadata.parent.mkdir(parents=True,exist_ok=True)
        metadata.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
 <id>heimserver-manager</id><metadata_license>CC0-1.0</metadata_license>
 <project_license>GPL-3.0-or-later</project_license>
 <name>Heimserver Manager</name><summary>Manage your home server in a browser</summary>
 <description><p>Web administration for applications, backups, storage and networking. Removing this package preserves application data and backups.</p></description>
 <launchable type="desktop-id">heimserver-manager.desktop</launchable>
 <pkgname>server-manager</pkgname>
</component>
''')
        documentation=stage/'usr/share/doc/server-manager';documentation.mkdir(parents=True)
        for name in ('LICENSE','LICENSE_NOTICE.md','THIRD_PARTY_NOTICES.md'):
            shutil.copyfile(root/name,documentation/name)
        shutil.copyfile(root/'packaging/debian/copyright',documentation/'copyright')
        control=stage/'DEBIAN';control.mkdir()
        installed_size=sum(p.stat().st_size for p in stage.rglob('*') if p.is_file())//1024+1
        (control/'control').write_text(f'''Package: server-manager
Version: {package_version}
Section: admin
Priority: optional
Architecture: all
Maintainer: Server Manager Administrators <root@localhost>
Installed-Size: {installed_size}
X-Heimserver-Target: {target}
Depends: python3 (>= {PROFILES[target]['python']}), python3-flask, python3-werkzeug, python3-waitress, libpam0g, libpam-modules, libpam-runtime, systemd, init-system-helpers, debconf (>= 0.5) | debconf-2.0, adduser, sudo, jq, sqlite3, iproute2, iputils-ping, util-linux, curl, ca-certificates, rsync, apache2, openssl, certbot, python3-certbot-apache
Recommends: xdg-utils
Suggests: python3-pil, python3-libvirt, smartmontools, acl, cifs-utils, nfs-common, dnsutils, ethtool
Description: Server Manager web administration
 Modular server administration with authenticated web access, app installers,
 storage, networking and download management. Optional services are configured
 separately. Configuration and application data are preserved on removal.
''')
        (control/'conffiles').write_text('/etc/server-manager/server-manager.env\n/etc/pam.d/server-manager\n')
        for name in ('preinst','postinst','prerm','postrm','config','templates'):
            shutil.copyfile(root/'packaging/debian'/name,control/name);(control/name).chmod(0o644 if name=='templates' else 0o755)
        guard=(root/'packaging/platform-check.sh').read_text()
        for name in ('preinst','postinst','config'):
            script=control/name
            script.write_text(script.read_text().replace('set -eu\n','set -eu\n'+guard+f'\nheimserver_check_platform {target} /etc/os-release\n',1))
        sums=[]
        for p in sorted(stage.rglob('*')):
            if p.is_file() and not p.is_relative_to(control):sums.append(hashlib.md5(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(stage)))
        (control/'md5sums').write_text('\n'.join(sums)+'\n')
        for p in stage.rglob('*'):
            if p.is_dir():p.chmod(0o755)
            elif p.is_file() and not (p.stat().st_mode & 0o111):p.chmod(0o644)
            os.utime(p,(epoch,epoch))
        os.utime(stage,(epoch,epoch))
        output.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['dpkg-deb','--root-owner-group','--uniform-compression','-Zxz','-z6','--build',str(stage),str(output)],check=True,env={**os.environ,'SOURCE_DATE_EPOCH':str(epoch)})
    checksum=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(checksum+'  '+output.name+'\n')
    helper=root/'tools/install_deb.sh'
    if helper.is_file():
        launcher=output.parent/'install_deb.sh';shutil.copyfile(helper,launcher);launcher.chmod(0o755)
        launcher.write_text(launcher.read_text().replace('# PLATFORM_GUARD', (root/'packaging/platform-check.sh').read_text()))
    print(str(output));print('SHA256: '+checksum)
    return output

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,default=Path('dist/Server_Manager.deb'))
    parser.add_argument('--revision',default=None)
    parser.add_argument('--target',choices=PROFILES,default='debian13')
    args=parser.parse_args();build(args.source,args.output,args.revision,args.target)
if __name__=='__main__':main()
