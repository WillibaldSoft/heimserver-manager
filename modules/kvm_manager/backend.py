"""Typed libvirt reads and bounded argv-only commands; never runs the V8 shell menu."""
from server_settings import get as host_setting
from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET

URI = 'qemu:///system'
VM_ROOT = Path(host_setting('vm_root'))
ISO_ROOTS = tuple(Path(p) for p in host_setting('iso_roots'))
MEDIA_ROOTS = tuple(Path(p) for p in host_setting('media_roots'))
STATES = {0:'Unbekannt',1:'Läuft',2:'Läuft',3:'Pausiert',4:'Fährt herunter',5:'Ausgeschaltet',6:'Abgestürzt',7:'Ruhezustand'}
PRESETS = {
 'linux': dict(label='Linux Desktop (Debian / LMDE / Mint / Ubuntu)', ram=4096, cpus=2, disk=40, firmware='uefi', bus='virtio', network_model='virtio', machine='q35', video='virtio'),
 'server': dict(label='Linux Server', ram=2048, cpus=2, disk=24, firmware='uefi', bus='virtio', network_model='virtio', machine='q35', video='virtio'),
 'windows11': dict(label='Windows 11 (UEFI + TPM 2.0)', ram=8192, cpus=4, disk=80, firmware='uefi', bus='sata', network_model='e1000e', machine='q35', video='vga'),
 'haos': dict(label='Home Assistant / Appliance (Disk-Import)', ram=4096, cpus=2, disk=40, firmware='uefi', bus='sata', network_model='e1000e', machine='q35', video='vga'),
 'legacy': dict(label='Windows XP / 2000 / 7 (BIOS)', ram=2048, cpus=2, disk=32, firmware='bios', bus='ide', network_model='e1000', machine='pc', video='vga'),
 'retro': dict(label='DOS / Windows 98 (BIOS)', ram=128, cpus=1, disk=4, firmware='bios', bus='ide', network_model='rtl8139', machine='pc', video='vga'),
}

class Error(ValueError):
    pass


def name(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', str(value)):
        raise Error('Name: 1–64 Zeichen, beginnend mit Buchstabe/Ziffer; erlaubt sind . _ -')
    return value


def domain_id(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        raise Error('Ungültige VM-ID.')


def number(value, low, high, label):
    if not re.fullmatch(r'[0-9]{1,9}', str(value)) or not low <= int(value) <= high:
        raise Error(f'{label}: {low} bis {high} eingeben.')
    return int(value)


def media_path(value, suffixes, roots=None):
    p = Path(value)
    if not p.is_absolute() or any(c in str(p) for c in ',\n\r\x00'):
        raise Error('Absoluter Dateipfad ohne Komma oder Steuerzeichen erforderlich.')
    try:
        resolved = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise Error('Datei nicht gefunden oder nicht zugänglich.')
    allowed = roots if roots is not None else MEDIA_ROOTS
    if not any(resolved.is_relative_to(r.resolve()) for r in allowed):
        raise Error('Datei liegt außerhalb der freigegebenen Medienverzeichnisse.')
    if not resolved.is_file() or resolved.suffix.lower() not in suffixes:
        raise Error('Nicht unterstützte Mediendatei.')
    return resolved


def command(args, timeout=60):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env={**os.environ, 'LC_ALL':'C'}, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Error(f'{args[0]}: {exc}') from exc
    if result.returncode:
        raise Error((result.stderr or result.stdout or 'Befehl fehlgeschlagen')[-6000:])
    return result.stdout


def virsh(*args):
    return command(['virsh','--connect',URI,*map(str,args)])


@contextmanager
def connection(write=False):
    try:
        import libvirt
    except ImportError as exc:
        raise Error('python3-libvirt fehlt. Bitte über die Paketverwaltung installieren.') from exc
    conn = libvirt.open(URI) if write else libvirt.openReadOnly(URI)
    if conn is None:
        raise Error('Keine Verbindung zu libvirt (qemu:///system).')
    try:
        yield conn
    finally:
        conn.close()


def domain_xml(dom, inactive=False):
    return ET.fromstring(dom.XMLDesc(2 if inactive and dom.isPersistent() else 0))


def disk_rows(root):
    rows=[]
    for node in root.findall('./devices/disk'):
        source=node.find('source'); target=node.find('target'); driver=node.find('driver')
        rows.append(dict(device=node.get('device',''), type=node.get('type',''),
            path=source.get('file',source.get('dev',source.get('name',''))) if source is not None else '',
            target=target.get('dev','') if target is not None else '',
            format=driver.get('type','') if driver is not None else '',
            readonly=node.find('readonly') is not None))
    return rows


def describe(dom, detail=False):
    info=dom.info(); root=domain_xml(dom)
    row=dict(uuid=dom.UUIDString(),name=dom.name(),state=info[0],state_label=STATES.get(info[0],'Unbekannt'),
             active=bool(dom.isActive()),persistent=bool(dom.isPersistent()),ram=info[2]//1024,cpus=info[3],
             autostart=bool(dom.autostart()) if dom.isPersistent() else False,
             firmware='UEFI' if root.find('./os/loader') is not None or root.find('os').get('firmware')=='efi' else 'BIOS',
             disks=disk_rows(root),networks=[])
    for node in root.findall('./devices/interface'):
        source=node.find('source');mac=node.find('mac')
        row['networks'].append(dict(type=node.get('type',''),source=dict(source.attrib) if source is not None else {},mac=mac.get('address','') if mac is not None else ''))
    if detail:
        row['xml']=ET.tostring(root,encoding='unicode')
        row['addresses']=[];row['address_note']='IP-Adressen aus libvirt-DHCP-Leases; Bridge-Gäste erscheinen ggf. nicht.'
        try:
            for iface in (dom.interfaceAddresses(0) if dom.isActive() else {}).values():
                row['addresses'] += [a['addr'] for a in iface.get('addrs',[])]
        except Exception:
            row['address_note']='Keine DHCP-Lease-Adressen verfügbar.'
        try:
            row['snapshots']=sorted(dom.snapshotListNames())
        except Exception:
            row['snapshots']=[]
        row['managed_save']=bool(dom.hasManagedSaveImage()) if dom.isPersistent() else False
    return row


def inventory():
    with connection() as conn:
        rows=[describe(dom) for dom in conn.listAllDomains()]
        host=conn.getInfo()
        networks=[dict(name=n.name(),active=bool(n.isActive()),autostart=bool(n.autostart())) for n in conn.listAllNetworks()]
    return dict(vms=sorted(rows,key=lambda r:r['name'].casefold()),host=dict(ram=host[1],cpus=host[2]),
                networks=networks,free_gib=round(shutil.disk_usage(VM_ROOT).free/1024**3,1) if VM_ROOT.exists() else None,
                bridges=sorted(p.parent.name for p in Path('/sys/class/net').glob('*/bridge')),
                tools={t:bool(shutil.which(t)) for t in ('virsh','virt-install','virt-clone','qemu-img','swtpm')})


def detail(uid):
    with connection() as conn:
        return describe(conn.lookupByUUIDString(domain_id(uid)),True)


def media_folder(value):
    p=Path(value)
    if not value or not p.is_absolute() or any(ord(c)<32 for c in value):raise Error('Bitte einen absoluten Serverordner auswählen.')
    try:p=p.resolve(strict=True)
    except (OSError,RuntimeError):raise Error('Ordner nicht gefunden oder nicht zugänglich.')
    if not p.is_dir():raise Error('Bitte zuerst einen Ordner, dann eine Datei auswählen.')
    return p

def browse_media(value,kind='iso'):
    root=media_folder(value)
    if kind not in ('iso','import'):raise Error('Ungültige Installationsart.')
    suffixes={'.iso'} if kind=='iso' else {'.qcow2','.raw','.img','.vmdk'}
    dirs=[];files=[];truncated=False
    try:
        with os.scandir(root) as entries:
            for index,entry in enumerate(entries):
                if index>=5000:truncated=True;break
                if entry.name.startswith('.'):continue
                try:
                    if entry.is_dir(follow_symlinks=False):dirs.append({'name':entry.name,'path':str(root/entry.name)})
                    elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in suffixes:
                        path=media_path(str(root/entry.name),suffixes,roots=(root,))
                        files.append({'name':entry.name,'path':str(path)})
                except (OSError,Error):continue
    except OSError:raise Error('Ordner kann nicht gelesen werden.')
    result=dict(folder=str(root),parent=str(root.parent),directories=sorted(dirs,key=lambda x:x['name'].lower()),files=sorted(files,key=lambda x:x['name'].lower()),truncated=truncated)
    if (root/'disk').is_file() and (root/'parts').is_file():
        try:
            info=rescuezilla_backup(str(root));info.pop('files',None);result['rescuezilla']=info
        except (Error,OSError) as exc:result['rescuezilla_note']=str(exc)
    return result

def rescuezilla_backup(value):
    """Inspect a flat Clonezilla/Rescuezilla single-disk backup without executing metadata."""
    root=media_folder(value)
    files={};total=0
    import stat
    with os.scandir(root) as entries:
        for entry in entries:
            if len(files)>=20000:raise Error('Zu viele Dateien im Sicherungsordner.')
            st=entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode):raise Error('Sicherungsordner darf nur reguläre Dateien enthalten, keine Links oder Unterordner.')
            files[entry.name]=(st.st_size,st.st_mtime_ns);total+=st.st_size
    def metadata(filename):
        if filename not in files or files[filename][0]>1024*1024:raise Error('Rescuezilla-Metadaten fehlen oder sind zu groß: '+filename)
        return (root/filename).read_text(errors='replace')
    disks=metadata('disk').split()
    if len(disks)!=1 or not re.fullmatch(r'[A-Za-z0-9_-]+',disks[0]):raise Error('Rescuezilla: derzeit nur Sicherungen einer einzelnen Festplatte unterstützt.')
    parts=metadata('parts').split()
    if not parts or any(not re.fullmatch(r'[A-Za-z0-9_-]+',part) for part in parts):raise Error('Ungültige Partitionsliste.')
    for part in parts:
        if not any(n.startswith(part+'.') and ('-ptcl-img' in n or '.dd-img' in n) for n in files) and not any(n.startswith(part+'.') and 'swap' in n for n in files):
            raise Error('Partitionsabbild fehlt: '+part)
    table=metadata(disks[0]+'-pt.parted')
    sectors=re.search(r'^Disk /dev/[^:]+: ([0-9]+)s$',table,re.M)
    sector_size=re.search(r'Sector size \(logical/physical\): ([0-9]+)B/',table)
    if not sectors or not sector_size:raise Error('Ursprüngliche Disk-Größe kann nicht sicher ermittelt werden (parted-Sektorangaben fehlen).')
    if int(sector_size[1])!=512:raise Error('Rescuezilla: native 4K-Sektoren werden noch nicht unterstützt.')
    size=int(sectors[1])*int(sector_size[1])
    if not 0<size<=16384*1024**3:raise Error('Nicht unterstützte Festplattengröße.')
    return dict(folder=str(root),disk=disks[0],minimum_gib=(size+1024**3-1)//1024**3,bytes=total,files=files)

def build_rescuezilla_media(folder,target,log):
    before=rescuezilla_backup(folder)
    log('Schreibgeschützte Sicherungskopie wird erstellt …')
    command(['mksquashfs',before['folder'],str(target),'-keep-as-directory','-noappend','-no-progress','-noD','-noF','-no-xattrs','-all-root','-processors','2'],timeout=86400)
    after=rescuezilla_backup(folder)
    if before!=after:raise Error('Sicherung wurde während des Kopierens verändert. Auftrag abgebrochen; Quelle unverändert.')
    command(['unsquashfs','-s',str(target)])
    target.chmod(0o600)


def create_media_path(data):
    roots=(media_folder(data['media_root']),) if data.get('media_root') else tuple(dict.fromkeys((*ISO_ROOTS,*MEDIA_ROOTS))) if data['kind'] in ('iso','rescuezilla') else MEDIA_ROOTS
    return media_path(data['media'],{'.iso'} if data['kind'] in ('iso','rescuezilla') else {'.qcow2','.raw','.img','.vmdk'},roots=roots)

def media_list(kind='iso'):
    """Bounded server-side discovery; the normal import path guard still applies."""
    if kind not in ('iso','import'):raise Error('Ungültige Installationsart.')
    suffixes={'.iso'} if kind=='iso' else {'.qcow2','.raw','.img','.vmdk'}
    roots=tuple(dict.fromkeys((*ISO_ROOTS,*MEDIA_ROOTS))) if kind=='iso' else MEDIA_ROOTS
    rows=set();folders=0;entries=0
    for root in roots:
        if not root.is_dir() or root.is_symlink():continue
        for folder,dirs,files in os.walk(root,followlinks=False):
            folders+=1
            if folders>2000:return sorted(rows)
            dirs[:]=sorted(d for d in dirs if not Path(folder,d).is_symlink())
            for filename in sorted(files):
                entries+=1
                if entries>20000:return sorted(rows)
                p=Path(folder,filename)
                if p.suffix.lower() not in suffixes or p.is_symlink():continue
                try:resolved=media_path(str(p),suffixes)
                except Error:continue
                rows.add(str(resolved))
                if len(rows)>=300:return sorted(rows)
    return sorted(rows)


def offline(dom):
    if dom.isActive() or dom.info()[0] != 5:
        raise Error('Diese Aktion benötigt eine vollständig ausgeschaltete VM.')
    if dom.hasManagedSaveImage():
        raise Error('Gespeicherter RAM-Zustand vorhanden. VM zuerst fortsetzen und regulär herunterfahren.')


def unique(conn, new_name, root=None):
    root=VM_ROOT if root is None else root
    name(new_name)
    if new_name in [d.name() for d in conn.listAllDomains()] or (root/new_name).exists() or (root/new_name).is_symlink():
        raise Error('VM-Name oder Zielverzeichnis existiert bereits.')


def image_info(path):
    info=json.loads(command(['qemu-img','info','--output=json',str(path)]))
    if info.get('backing-filename') or info.get('encrypted'):
        raise Error('Images mit Backing-Datei oder Verschlüsselung werden nicht automatisch verarbeitet.')
    if info.get('format') not in ('qcow2','raw','vmdk'):
        raise Error('Unterstützt werden qcow2, raw/img und VMDK.')
    return info


def inactive_image(conn, path):
    for dom in conn.listAllDomains():
        if dom.isActive() or (dom.isPersistent() and dom.hasManagedSaveImage()):
            for d in disk_rows(domain_xml(dom)):
                if d['path'] and d['type']=='file' and Path(d['path']).resolve()==path.resolve():
                    raise Error(f'Die Quelldatei gehört zur aktiven/gespeicherten VM {dom.name()}.')


def require_space(size, root=None):
    root=VM_ROOT if root is None else root
    free=shutil.disk_usage(root).free;needed=size+2*1024**3
    if free < needed:
        raise Error(f'Zu wenig Speicher am Ziel {root}: {free/1024**3:.1f} GiB frei, {needed/1024**3:.1f} GiB einschließlich Reserve benötigt.')


def config_backup(dom, folder):
    folder.mkdir(parents=True,exist_ok=True)
    dest=folder/(dom.UUIDString()+'-'+uuid.uuid4().hex+'.xml')
    dest.write_text(dom.XMLDesc(2));dest.chmod(0o600)
    return str(dest)


def prepare_create(data):
    preset=data.get('preset','linux')
    if preset not in PRESETS:raise Error('Unbekannte Vorlage.')
    p=PRESETS[preset]
    result=dict(name=name(data.get('name','')),preset=preset,target_root=str(media_folder(data['target_root'])) if data.get('target_root') else str(VM_ROOT),
      ram=number(data.get('ram',p['ram']),64,1048576,'RAM (MiB)'),
      cpus=number(data.get('cpus',p['cpus']),1,256,'vCPUs'),
      disk=number(data.get('disk',p['disk']),1,16384,'Disk (GiB)'),
      firmware=data.get('firmware',p['firmware']),network=data.get('network','bridge:br0'),
      rescuezilla_folder=data.get('rescuezilla_folder',''),kind=data.get('kind','iso'),media=data.get('media',''),media_root=data.get('media_root',''),autostart=data.get('autostart') in ('1',True))
    if result['firmware'] not in ('bios','uefi'):raise Error('Ungültige Firmware.')
    if preset=='windows11' and (result['firmware']!='uefi' or result['ram']<4096 or result['cpus']<2 or result['disk']<64):
        raise Error('Windows 11: UEFI, mindestens 4096 MiB RAM, 2 vCPUs und 64 GiB Disk.')
    if result['kind'] not in ('iso','import','rescuezilla'):raise Error('Ungültige Installationsart.')
    result['media']=str(create_media_path(result))
    if result['media_root']:result['media_root']=str(media_folder(result['media_root']))
    if result['kind']=='rescuezilla':
        backup=rescuezilla_backup(result['rescuezilla_folder'])
        result['rescuezilla_folder']=backup['folder']
        if Path(result['target_root']).resolve().is_relative_to(Path(backup['folder'])):raise Error('Zielablage darf nicht innerhalb der Quell-Sicherung liegen.')
        if result['disk']<backup['minimum_gib']:raise Error(f"Zieldisk benötigt mindestens {backup['minimum_gib']} GiB (Originalgröße).")
        if not shutil.which('mksquashfs') or not shutil.which('unsquashfs'):raise Error('squashfs-tools fehlt. KVM-Installer unter Apps verwenden, um die Abhängigkeiten zu ergänzen.')
        if result['ram']<2048:raise Error('Rescuezilla benötigt hier mindestens 2048 MiB RAM.')
        result['autostart']=False
    return result


def create_vm(data, log):
    data=prepare_create(data);p=PRESETS[data['preset']]
    with connection(True) as conn:
        target_root=media_folder(data['target_root'])
        if any(c in str(target_root) for c in ',\n\r'):raise Error('Zielordner darf keine Kommas oder Steuerzeichen enthalten.')
        unique(conn,data['name'],target_root)
        host=conn.getInfo()
        if data['ram']>host[1] or data['cpus']>host[2]:raise Error('Ressourcen überschreiten die Host-Kapazität.')
        netkind,_,netname=data['network'].partition(':')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+',netname):raise Error('Ungültiges Netzwerk.')
        if netkind=='bridge':
            if not Path('/sys/class/net',netname,'bridge').is_dir():raise Error('Bridge nicht vorhanden.')
        elif netkind=='network':
            if not conn.networkLookupByName(netname).isActive():raise Error('libvirt-Netzwerk ist nicht aktiv.')
        else:raise Error('Bridge oder libvirt-Netzwerk auswählen.')
        src=create_media_path(data)
        if data['kind']=='import':
            inactive_image(conn,src);info=image_info(src);required=info['virtual-size']
        else:required=data['disk']*1024**3
        if data['preset']=='windows11' and required < 64*1024**3:
            raise Error('Windows-11-Import benötigt eine virtuelle Disk mit mindestens 64 GiB.')
        if data['kind']=='rescuezilla':
            source_backup=rescuezilla_backup(data['rescuezilla_folder'])
            require_space(required+src.stat().st_size+source_backup['bytes']*1.05,target_root)
        require_space(required,target_root)
        directory=target_root/data['name'];directory.mkdir(mode=0o755)
        disk=directory/'disk.qcow2'
        log(f'Ziel: {directory}. VM wird ausgeschaltet angelegt.')
        if data['kind'] in ('iso','rescuezilla'):
            command(['qemu-img','create','-f','qcow2',str(disk),f"{data['disk']}G"])
            # Keep ISO inside the VM directory: libvirt never depends on inaccessible source shares.
            require_space(required+src.stat().st_size,target_root)
            iso=directory/'installation.iso';log('Installationsmedium wird kopiert …')
            command(['cp','--reflink=auto','--sparse=always','--',str(src),str(iso)],timeout=14400)
        else:
            log('Quelldisk wird als eigenständige qcow2-Kopie importiert …')
            command(['qemu-img','convert','-f',info['format'],'-O','qcow2',str(src),str(disk)],timeout=14400)
        if data['kind']=='rescuezilla':
            recovery=directory/'rescuezilla-backup.squashfs'
            build_rescuezilla_media(data['rescuezilla_folder'],recovery,log)
        disk.chmod(0o600)
        if os.geteuid()==0:
            import pwd,grp
            uid=pwd.getpwnam('libvirt-qemu').pw_uid;gid=grp.getgrnam('kvm').gr_gid
            for file in directory.iterdir():os.chown(file,uid,gid)
            os.chown(directory,uid,gid)
        args=['virt-install','--connect',URI,'--name',data['name'],'--memory',str(data['ram']),
              '--vcpus',str(data['cpus']),'--cpu','host-passthrough','--machine',p['machine'],
              '--disk',f'path={disk},format=qcow2,bus={p["bus"]},boot.order=2',
              '--network',f'{netkind}={netname},model={p["network_model"]}',
              '--osinfo','generic','--graphics','spice,listen=127.0.0.1','--video',p['video'],
              '--channel','unix,target.type=virtio,target.name=org.qemu.guest_agent.0',
              '--boot','uefi,menu=on' if data['firmware']=='uefi' else 'hd,menu=on',
              '--noautoconsole','--import','--print-xml']
        if data['kind'] in ('iso','rescuezilla'):args+=['--disk',f'path={iso},device=cdrom,bus={"ide" if p["bus"]=="ide" else "sata"},readonly=on,boot.order=1']
        if data['kind']=='rescuezilla':args+=['--disk',f'path={recovery},format=raw,bus=virtio,readonly=on,serial=rescuezilla-backup']
        if data['preset']=='windows11':args+=['--tpm','backend.type=emulator,backend.version=2.0,model=tpm-crb']
        log('libvirt-Definition wird geprüft und angelegt …')
        xml=command(args,timeout=120);ET.fromstring(xml)
        dom=conn.defineXML(xml)
        dom.setAutostart(int(data['autostart']))
        log('VM angelegt: '+dom.name()+'. Start erfolgt über die VM-Detailseite.')
        if data['kind']=='rescuezilla':log('Rescuezilla vorbereitet, noch NICHT wiederhergestellt. VM starten und Anleitung auf der VM-Detailseite befolgen. Nach Wiederherstellung VM herunterfahren und ISO auswerfen.')
        return dom.UUIDString()


def vm_action(uid, action, data, log, backup_dir):
    uid=domain_id(uid)
    with connection(True) as conn:
        dom=conn.lookupByUUIDString(uid)
        if action in ('destroy','undefine','snapshot-revert') and data.get('confirm')!=dom.name():
            raise Error('Bitte zur Bestätigung den exakten VM-Namen eingeben.')
        if action in ('start','shutdown','reboot','suspend','resume','destroy'):
            allowed={'start':(5,), 'shutdown':(1,2), 'reboot':(1,2), 'suspend':(1,2), 'resume':(3,), 'destroy':(1,2,3,4,7)}
            if dom.info()[0] not in allowed[action]:raise Error('Aktion passt nicht zum aktuellen VM-Zustand.')
            log(virsh(action,uid).strip());return uid
        if action in ('autostart-on','autostart-off'):
            dom.setAutostart(int(action=='autostart-on'));log('Autostart aktualisiert.');return uid
        offline(dom)
        if action=='resources':
            ram=number(data.get('ram'),64,conn.getInfo()[1],'RAM (MiB)');cpus=number(data.get('cpus'),1,conn.getInfo()[2],'vCPUs')
            root=domain_xml(dom,True)
            if root.find('maxMemory') is not None or root.find('vcpus') is not None or root.find('cputune') is not None or root.find('./cpu/numa') is not None:
                raise Error('Erweiterte CPU-/NUMA-/Hotplug-Konfiguration: bitte mit virt-manager bearbeiten.')
            log('XML-Sicherung: '+config_backup(dom,backup_dir))
            for tag in ('memory','currentMemory'):
                node=root.find(tag)
                if node is None:node=ET.SubElement(root,tag)
                node.text=str(ram);node.set('unit','MiB')
            node=root.find('vcpu');node.text=str(cpus);node.attrib.pop('current',None)
            topology=root.find('./cpu/topology')
            if topology is not None:root.find('cpu').remove(topology)
            conn.defineXML(ET.tostring(root,encoding='unicode'));log('Ressourcen für den nächsten Start gespeichert.')
        elif action=='rescue-detach':
            root=domain_xml(dom,True);devices=root.find('devices')
            found=[d for d in devices.findall('disk') if d.findtext('serial')=='rescuezilla-backup' and d.find('readonly') is not None]
            if len(found)!=1:raise Error('Kein eindeutig zugeordnetes Rescuezilla-Medium vorhanden.')
            log('XML-Sicherung: '+config_backup(dom,backup_dir))
            devices.remove(found[0]);conn.defineXML(ET.tostring(root,encoding='unicode'))
            log('Sicherungsmedium aus VM entfernt. Sicherungskopie auf dem Server bleibt erhalten und kann später manuell gelöscht werden.')
        elif action=='eject':
            target=data.get('target','');cdroms=[r['target'] for r in disk_rows(domain_xml(dom,True)) if r['device']=='cdrom']
            if target not in cdroms:raise Error('Unbekanntes CD/DVD-Laufwerk.')
            log('XML-Sicherung: '+config_backup(dom,backup_dir));log(virsh('change-media',uid,target,'--eject','--config').strip())
        elif action=='undefine':
            if dom.snapshotListNames():raise Error('VM besitzt Snapshots. Definition bleibt zum Schutz der Snapshot-Zuordnung erhalten.')
            log('XML-Sicherung: '+config_backup(dom,backup_dir))
            import libvirt
            flags=libvirt.VIR_DOMAIN_UNDEFINE_KEEP_NVRAM | libvirt.VIR_DOMAIN_UNDEFINE_KEEP_TPM
            dom.undefineFlags(flags);log('VM-Definition entfernt. Disks, NVRAM und TPM-Daten bleiben erhalten.');return ''
        elif action=='clone':
            new=name(data.get('name',''));unique(conn,new)
            root=domain_xml(dom,True)
            if root.findall('./devices/hostdev') or root.findall('./devices/filesystem') or root.find('./devices/tpm') is not None:
                raise Error('Klonen von VMs mit Host-Geräten, gemeinsamem Dateisystem oder TPM bitte in virt-manager vorbereiten.')
            disks=[d for d in disk_rows(root) if d['device']=='disk']
            if not disks or any(d['type']!='file' or d['readonly'] for d in disks):raise Error('Klonen benötigt normale, beschreibbare Image-Dateien.')
            size=0
            for d in disks:
                source=media_path(d['path'],{'.qcow2','.raw','.img','.vmdk'});inactive_image(conn,source);size+=image_info(source)['virtual-size']
            require_space(size);directory=VM_ROOT/new;directory.mkdir(mode=0o755)
            args=['virt-clone','--connect',URI,'--original',dom.name(),'--name',new]
            for i,d in enumerate(disks):args+=['--file',str(directory/f'disk-{i}.{d["format"] or "img"}')]
            log('Disks werden kopiert; neue UUID und MAC-Adressen werden erzeugt …')
            log(command(args,timeout=14400));clone=conn.lookupByName(new);clone.setAutostart(0)
            log('Klon bleibt ausgeschaltet. Gast-Hostname, feste IP und Gast-Identitäten vor gemeinsamem Betrieb anpassen.')
            return clone.UUIDString()
        elif action=='export':
            target=data.get('target');disks=[d for d in disk_rows(domain_xml(dom,True)) if d['device']=='disk' and d['target']==target and d['type']=='file']
            if len(disks)!=1:raise Error('Exportierbare Disk auswählen.')
            src=media_path(disks[0]['path'],{'.qcow2','.raw','.img','.vmdk'});inactive_image(conn,src);info=image_info(src)
            fmt=data.get('format','qcow2')
            if fmt not in ('qcow2','raw'):raise Error('Exportformat qcow2 oder raw wählen.')
            require_space(info['virtual-size']);folder=VM_ROOT/'exports'
            if folder.is_symlink():raise Error('Exportverzeichnis darf kein Symlink sein.')
            folder.mkdir(exist_ok=True)
            dest=folder/(uid+'-'+uuid.uuid4().hex+'.'+fmt)
            log('Disk-Export nach '+str(dest));command(['qemu-img','convert','-f',info['format'],'-O',fmt,str(src),str(dest)],timeout=14400)
            log('Export abgeschlossen: '+str(dest))
        else:raise Error('Unbekannte Aktion.')
        return uid
