"""Portable offline VM bundles. Uploaded XML is restricted before libvirt sees it.

Disks travel as compressed RAW, never as uploaded qcow2 with external file references.
No archive member is extracted by tarfile; names, lengths and hashes are checked.
"""
from pathlib import Path
import copy
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import uuid
import xml.etree.ElementTree as ET
from server_settings import get as host_setting
from . import backend as b

GiB=1024**3
MAX_TOTAL=16*1024*GiB
MAX_UPLOAD=1024*GiB
RESERVE=2*GiB
TPM_ROOT=Path('/var/lib/libvirt/swtpm')
# Only these virtual-hardware elements survive. Host file/socket references are
# handled separately; unknown devices/features fail closed instead of disappearing.
ATTRS={
 'domain':'type','name':'','uuid':'','title':'','description':'',
 'memory':'unit dumpCore','currentMemory':'unit','vcpu':'placement current',
 'os':'firmware','type':'arch machine','firmware':'','feature':'policy name enabled',
 'loader':'readonly secure type format','nvram':'template templateFormat format',
 'boot':'dev order','bootmenu':'enable timeout','smbios':'mode',
 'features':'','acpi':'','apic':'eoi','pae':'','hap':'state','vmport':'state','smm':'state',
 'hyperv':'mode','relaxed':'state','vapic':'state','spinlocks':'state retries',
 'vpindex':'state','runtime':'state','synic':'state','stimer':'state','direct':'state',
 'reset':'state','vendor_id':'state value','frequencies':'state','reenlightenment':'state',
 'tlbflush':'state','ipi':'state','evmcs':'state','kvm':'','hidden':'state',
 'cpu':'mode match check migratable','model':'name type fallback vendor_id heads primary ram vram vgamem',
 'vendor':'','topology':'sockets dies clusters cores threads','cache':'level mode',
 'clock':'offset adjustment basis','timer':'name tickpolicy present track frequency mode',
 'on_poweroff':'','on_reboot':'','on_crash':'','pm':'','suspend-to-mem':'enabled','suspend-to-disk':'enabled',
 'devices':'','disk':'type device','driver':'name type cache io discard detect_zeroes error_policy',
 'source':'file bridge network','target':'dev bus type port name chassis index hotplug',
 'readonly':'','serial':'type','console':'type','channel':'type',
 'controller':'type index model ports','master':'startport',
 'address':'type domain bus slot function multifunction controller target unit port',
 'interface':'type','mac':'address','link':'state','input':'type bus',
 'graphics':'type port autoport listen passwd keymap','listen':'type address','image':'compression',
 'sound':'model','audio':'id type','video':'','acceleration':'accel2d accel3d',
 'redirdev':'bus type','watchdog':'model action','memballoon':'model autodeflate freePageReporting',
 'rng':'model','backend':'model type version persistent_state','rate':'bytes period',
 'tpm':'model','alias':'name',
}


def root():
    path=Path(host_setting('system_backup_root'))/'kvm'
    if path.is_symlink():raise b.Error('KVM-Sicherungsordner darf kein Symlink sein.')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    return path


def bundle(jid):
    legacy=root()/f'vm-backup-{int(jid)}.tar.gz'
    matches=list(root().glob(f'*--job-{int(jid)}.tar.gz'))
    if len(matches)>1 or (matches and legacy.exists()):raise b.Error('Backup-Datei nicht eindeutig.')
    return matches[0] if matches else legacy


def archive_name(name,jid):
    from datetime import datetime
    safe=re.sub(r'[^A-Za-z0-9_.-]+','_',name).strip('._-')[:100] or 'VM'
    return f'{safe}_{datetime.now():%Y-%m-%d_%H-%M-%S}--job-{int(jid)}.tar.gz'

def upload(jid):return root()/f'upload-{int(jid)}.part'

def space(path,size):
    if size<0 or size>MAX_TOTAL or shutil.disk_usage(path).free<size+RESERVE:
        raise b.Error('Zu wenig freier Speicher: benötigte Größe plus 2 GiB Reserve erforderlich.')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(4*1024*1024):h.update(chunk)
    return h.hexdigest()


def xml_read(data):
    if len(data)>1024*1024 or b'<!' in data:raise b.Error('Ungültige oder zu große VM-XML.')
    try:node=ET.fromstring(data)
    except ET.ParseError as exc:raise b.Error('VM-XML kann nicht gelesen werden.') from exc
    if node.tag!='domain':raise b.Error('VM-Definition fehlt.')
    return node


def firmware(value):
    p=Path(value or '')
    roots=[Path('/usr/share/OVMF'),Path('/usr/share/ovmf'),Path('/usr/share/qemu'),Path('/usr/share/AAVMF')]
    if not p.is_absolute() or p.suffix.lower() not in ('.fd','.bin') or not p.is_file() or not any(p.resolve().is_relative_to(r.resolve()) for r in roots):
        raise b.Error('Passende lokale UEFI-Firmware fehlt oder liegt außerhalb der System-Firmwareordner: '+str(p))
    return str(p)


def restricted_xml(original, directory, new_name, new_uuid, network=None):
    """Keep supported hardware layout, replace EVERY external resource reference."""
    r=copy.deepcopy(original)
    for tag in ('metadata','seclabel'):
        for n in r.findall(tag):r.remove(n)
    devices=r.find('devices')
    if devices is None:raise b.Error('VM-Geräte fehlen.')
    for n in devices.findall('emulator'):devices.remove(n) # let libvirt select installed emulator
    # Libvirt emits an empty backingStore to mark the end of a disk chain.
    # Only this empty marker is harmless; real backing stores remain rejected.
    for disk in devices.findall('disk'):
        for node in disk.findall('backingStore'):
            if not node.attrib and not len(node) and not (node.text or '').strip():
                disk.remove(node)
    for n in r.iter():
        if n.tag not in ATTRS or set(n.attrib)-set(ATTRS[n.tag].split()):
            raise b.Error('Nicht unterstützte VM-Konfiguration: '+n.tag+'. Bitte gesondert mit virt-manager sichern.')
        if len(n.attrib)>20 or any(len(v)>4096 for v in n.attrib.values()):raise b.Error('Ungültige XML-Attribute.')
    if r.get('type') not in ('kvm','qemu') or r.findtext('./os/type')!='hvm':raise b.Error('Nur QEMU/KVM-HVM-Gäste werden unterstützt.')
    for tag in ('name','uuid'):
        n=r.find(tag)
        if n is None:raise b.Error('VM-Name oder UUID fehlt.')
        n.text=new_name if tag=='name' else new_uuid
    osnode=r.find('os')
    loader=osnode.find('loader');nv=osnode.find('nvram')
    if loader is not None:
        if loader.get('type')!='pflash' or loader.get('format','raw')!='raw':raise b.Error('Nur UEFI-pflash im RAW-Format unterstützt.')
        loader.text=firmware(loader.text)
        if nv is None:raise b.Error('UEFI ohne bestehenden NVRAM-Speicher wird nicht gesichert.')
    if nv is not None:
        if nv.get('format','raw')!='raw' or len(nv):raise b.Error('Nur dateibasierter RAW-NVRAM unterstützt.')
        if nv.get('template'):nv.set('template',firmware(nv.get('template')))
        nv.text=str(directory/'nvram.fd')
    disks=devices.findall('disk')
    if not 1<=len(disks)<=32:raise b.Error('Eine bis 32 lokale Festplatten/CD-Laufwerke werden unterstützt.')
    count=0
    for n in disks:
        if n.get('type')!='file' or n.get('device') not in ('disk','cdrom'):raise b.Error('Nur lokale Image-Dateien und CD-Laufwerke werden unterstützt.')
        for src in n.findall('source'):n.remove(src)
        driver=n.find('driver')
        if driver is None:driver=ET.SubElement(n,'driver')
        driver.set('name','qemu');driver.set('type','raw')
        if n.get('device')=='disk':
            ET.SubElement(n,'source',file=str(directory/f'disk-{count}.raw'));count+=1
    if not count:raise b.Error('Keine lokale VM-Festplatte gefunden.')
    for n in devices.findall('interface'):
        if n.get('type') not in ('bridge','network'):raise b.Error('Nur Bridge- und libvirt-Netzwerke werden unterstützt.')
        s=n.find('source')
        if s is None or set(s.attrib)!={n.get('type')}:raise b.Error('Unbekannte Netzwerkkonfiguration.')
        kind,value=(network.split(':',1) if network else (n.get('type'),s.get(n.get('type'))))
        if kind not in ('bridge','network') or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',value or ''):raise b.Error('Ungültiges Netzwerk.')
        n.set('type',kind);s.attrib={kind:value}
        for mac in n.findall('mac'):n.remove(mac)
        ET.SubElement(n,'mac',address='52:54:00:'+':'.join(f'{v:02x}' for v in os.urandom(3)))
    for n in devices.findall('graphics'):
        if n.get('type') not in ('spice','vnc'):raise b.Error('Nur SPICE/VNC-Grafik unterstützt.')
        n.attrib={'type':n.get('type'),'autoport':'yes','listen':'127.0.0.1'}
        for child in list(n):n.remove(child)
        ET.SubElement(n,'listen',type='address',address='127.0.0.1')
    for tag in ('serial','console','channel'):
        for n in devices.findall(tag):
            allowed=('pty',) if tag!='channel' else ('unix','spicevmc')
            if n.get('type') not in allowed:raise b.Error('Nicht unterstützte serielle/Agent-Verbindung.')
            for src in n.findall('source'):n.remove(src)
    for n in devices.findall('rng/backend'):
        if n.get('model')!='random' or (n.text or '').strip() not in ('/dev/random','/dev/urandom'):raise b.Error('Nicht unterstützte Zufallsquelle.')
        n.text='/dev/urandom'
    for n in devices.findall('audio'):
        if n.get('type') not in ('none','spice'):raise b.Error('Host-Audiogerät wird nicht gesichert.')
    for n in devices.findall('redirdev'):
        if n.get('type')!='spicevmc':raise b.Error('Nur SPICE-USB-Umleitung unterstützt.')
    for n in devices.findall('input'):
        if n.get('type') not in ('tablet','mouse','keyboard'):raise b.Error('Host-Eingabegerät wird nicht gesichert.')
    for n in devices.findall('tpm'):
        back=n.find('backend')
        if back is None or back.get('type')!='emulator' or back.get('version')!='2.0' or len(back):raise b.Error('Nur unverschlüsseltes emuliertes TPM 2.0 unterstützt.')
    # Contextual path whitelist: even a known tag moved under a different device
    # must never be able to inject an arbitrary file/socket/firmware reference.
    allowed_sources={id(n) for n in devices.findall('disk/source')+devices.findall('interface/source')}
    for n in r.iter('source'):
        if id(n) not in allowed_sources:raise b.Error('Unzulässige zusätzliche Datenquelle.')
    for tag,expected in [('loader',osnode.findall('loader')),('nvram',osnode.findall('nvram')),('backend',devices.findall('rng/backend')+devices.findall('tpm/backend'))]:
        if {id(n) for n in r.iter(tag)}!={id(n) for n in expected}:raise b.Error('Unzulässige eingebettete Ressource.')
    return r


def tpm_files(uid):
    folder=TPM_ROOT/b.domain_id(uid)
    if folder.is_symlink() or not folder.is_dir():raise b.Error('TPM-Zustand fehlt; vollständige Sicherung nicht möglich.')
    rows=[]
    for p in folder.rglob('*'):
        if p.is_symlink() or not (p.is_file() or p.is_dir()):raise b.Error('Unbekannte TPM-Zustandsdatei.')
        if p.is_file():
            rel=p.relative_to(folder).as_posix()
            if not re.fullmatch(r'tpm2/[A-Za-z0-9_.-]+',rel) or p.stat().st_size>64*1024*1024:raise b.Error('Nicht unterstütztes TPM-Zustandsformat.')
            rows.append((rel,p))
    if not any(rel=='tpm2/tpm2-00.permall' for rel,p in rows):raise b.Error('Persistenter TPM-2.0-Zustand fehlt.')
    return rows


def create(uid,jid,log):
    destination=bundle(jid)
    if destination.exists():raise b.Error('Backup-Zieldatei existiert bereits.')
    with b.connection() as conn:
        dom=conn.lookupByUUIDString(b.domain_id(uid));b.offline(dom)
        if not dom.isPersistent():raise b.Error('Persistente VM erforderlich.')
        destination=root()/archive_name(dom.name(),jid)
        if destination.exists():raise b.Error('Backup-Zieldatei existiert bereits.')
        original=dom.XMLDesc(2).encode();r=xml_read(original)
        restricted_xml(r,Path('/restore'), 'Restore',str(uuid.uuid4()))
        sources=[];total=0
        for d in b.disk_rows(r):
            if d['device']!='disk':continue
            p=Path(d['path'])
            if not p.is_absolute() or not p.is_file():raise b.Error('Lokale Disk-Datei fehlt.')
            b.inactive_image(conn,p)
            info=b.image_info(p)
            if info.get('format-specific',{}).get('data',{}).get('data-file'):raise b.Error('Externe qcow2-Datendateien werden nicht unterstützt.')
            total+=int(info['virtual-size']);sources.append((p,info))
        extras=[]
        nv=r.find('./os/nvram')
        if nv is not None:
            p=Path(nv.text or '')
            if not p.is_absolute() or not p.is_file() or p.stat().st_size>64*1024*1024:raise b.Error('NVRAM fehlt oder ist ungültig.')
            extras.append(('nvram.fd',p))
        if r.find('./devices/tpm') is not None:extras += [('tpm/'+rel,p) for rel,p in tpm_files(uid)]
        stamps={p:(p.stat().st_size,p.stat().st_mtime_ns) for p in [x[0] for x in sources]+[x[1] for x in extras]}
        # Conservative upper bound includes raw working copies and incompressible archive.
        space(root(),2*total+sum(p.stat().st_size for _,p in extras)+16*1024*1024)
        temp_archive=destination.with_suffix('.partial')
        try:
            with tempfile.TemporaryDirectory(prefix='.build-',dir=root()) as tmp:
                folder=Path(tmp);(folder/'domain.xml').write_bytes(original)
                files=['domain.xml']
                for i,(p,info) in enumerate(sources):
                    b.offline(dom);log(f'Festplatte {i+1}/{len(sources)} wird gesichert …')
                    dst=folder/f'disk-{i}.raw'
                    b.command(['qemu-img','convert','-f',info['format'],'-O','raw',str(p),str(dst)],timeout=86400)
                    files.append(dst.name)
                for rel,p in extras:
                    dst=folder/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst);files.append(rel)
                manifest={'format':'heimserver-vm-backup','version':1,'name':dom.name(),'uuid':uid,'files':[]}
                log('Prüfsummen berechnen und Download-Paket komprimieren …')
                for rel in files:
                    p=folder/rel;manifest['files'].append({'name':rel,'size':p.stat().st_size,'sha256':digest(p)})
                encoded=json.dumps(manifest,ensure_ascii=False).encode()
                with temp_archive.open('xb') as out:
                    os.chmod(temp_archive,0o600)
                    with tarfile.open(fileobj=out,mode='w:gz',compresslevel=1,format=tarfile.GNU_FORMAT) as archive:
                        m=tarfile.TarInfo('manifest.json');m.size=len(encoded);m.mode=0o600;archive.addfile(m,io.BytesIO(encoded))
                        for rel in files:
                            p=folder/rel;m=tarfile.TarInfo(rel);m.size=p.stat().st_size;m.mode=0o600
                            with p.open('rb') as f:archive.addfile(m,f)
                b.offline(dom)
                if dom.XMLDesc(2).encode()!=original or any((p.stat().st_size,p.stat().st_mtime_ns)!=stamp for p,stamp in stamps.items()):raise b.Error('VM-Konfiguration oder Quelldaten wurden während der Sicherung verändert. Backup verworfen.')
                os.replace(temp_archive,destination)
        finally:temp_archive.unlink(missing_ok=True)
    log('Backup bereit zum Herunterladen. Enthält aktuellen Disk-Zustand, XML, ggf. NVRAM und TPM 2.0. ISO-Medien und Snapshot-Historie sind nicht enthalten.')
    return uid


def safe_member(name):
    return bool(re.fullmatch(r'(domain\.xml|nvram\.fd|disk-(?:[0-9]|[12][0-9]|3[01])\.raw|tpm/tpm2/[A-Za-z0-9_.-]+)',name)) and '..' not in name


def unpack(archive_path,folder,log):
    # Read only plain USTAR/GNU regular-file headers, never PAX/GNU extension records whose declared
    # lengths tarfile would allocate before our own size checks could run.
    with gzip.open(archive_path,'rb') as stream:
        def header():
            block=stream.read(512)
            if len(block)!=512:raise b.Error('Archiv ist abgeschnitten.')
            if block==bytes(512):return None
            try:m=tarfile.TarInfo.frombuf(block,'utf-8','strict')
            except (tarfile.TarError,UnicodeError,ValueError) as exc:raise b.Error('Ungültiger Archivkopf.') from exc
            if m.type not in (tarfile.REGTYPE,tarfile.AREGTYPE) or m.size<0:raise b.Error('Nur normale USTAR/GNU-Dateien sind erlaubt.')
            return m
        first=header()
        if first is None or first.name!='manifest.json' or not 0<first.size<=65536:raise b.Error('Kein Heimserver-VM-Backup (Manifest fehlt).')
        try:manifest=json.loads(stream.read(first.size))
        except (ValueError,UnicodeError) as exc:raise b.Error('Ungültiges Manifest.') from exc
        stream.read((-first.size)%512)
        if not isinstance(manifest,dict) or manifest.get('format')!='heimserver-vm-backup' or manifest.get('version')!=1:raise b.Error('Nicht unterstütztes Backup-Format.')
        rows=manifest.get('files',[])
        if not isinstance(rows,list) or not 2<=len(rows)<=128:raise b.Error('Ungültige Dateiliste.')
        expected={};total=0
        for row in rows:
            if not isinstance(row,dict):raise b.Error('Ungültiger Manifest-Eintrag.')
            name=row.get('name','');size=row.get('size');sha=row.get('sha256','')
            if not isinstance(name,str) or not safe_member(name) or name in expected or type(size)!=int or size<0 or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):raise b.Error('Ungültiger Manifest-Eintrag.')
            if not name.startswith('disk-') and size>64*1024*1024:raise b.Error('Metadaten sind zu groß.')
            if name=='domain.xml' and size>1024*1024:raise b.Error('VM-XML ist zu groß.')
            total+=size;expected[name]=row
        if 'domain.xml' not in expected or 'disk-0.raw' not in expected:raise b.Error('VM-Konfiguration oder Festplatte fehlt.')
        space(folder,total)
        seen=set()
        while True:
            member=header()
            if member is None:break
            row=expected.get(member.name)
            if not row or member.name in seen or member.size!=row['size']:raise b.Error('Unzulässiger oder doppelter Archiv-Eintrag.')
            seen.add(member.name);dst=folder/member.name;dst.parent.mkdir(parents=True,exist_ok=True)
            log('Prüfen / entpacken: '+member.name)
            h=hashlib.sha256();length=0
            with dst.open('xb') as out:
                while length<member.size:
                    chunk=stream.read(min(4*1024*1024,member.size-length))
                    if not chunk:raise b.Error('Archiv ist abgeschnitten.')
                    length+=len(chunk);h.update(chunk)
                    if chunk.count(0)==len(chunk):out.seek(len(chunk),1)
                    else:out.write(chunk)
                out.truncate(length)
            dst.chmod(0o600);stream.read((-member.size)%512)
            if h.hexdigest()!=row['sha256']:raise b.Error('Prüfsumme stimmt nicht: '+member.name)
        if seen!=set(expected):raise b.Error('Backup ist unvollständig.')
        tail=stream.read(10241)
        if len(tail)>10240 or any(tail):raise b.Error('Unerwartete Daten nach Archivende.')
    return manifest


def restore(data,jid,log):
    new_name=b.name(data.get('name',''));source=upload(jid);new_uid=str(uuid.uuid4())
    b.VM_ROOT.mkdir(parents=True,exist_ok=True)
    with b.connection(True) as conn:
        b.unique(conn,new_name)
        with tempfile.TemporaryDirectory(prefix='.restore-',dir=b.VM_ROOT) as tmp:
            staging=Path(tmp);unpack(source,staging,log)
            original=xml_read((staging/'domain.xml').read_bytes())
            directory=b.VM_ROOT/new_name
            r=restricted_xml(original,directory,new_name,new_uid,data.get('network') or None)
            expected={'domain.xml'}|{f'disk-{i}.raw' for i,d in enumerate([d for d in b.disk_rows(r) if d['device']=='disk'])}
            if r.find('./os/nvram') is not None:expected.add('nvram.fd')
            tpm=r.find('./devices/tpm') is not None
            present={p.relative_to(staging).as_posix() for p in staging.rglob('*') if p.is_file()}
            if {p for p in present if not p.startswith('tpm/')}!=expected:raise b.Error('Dateien passen nicht zur VM-Konfiguration.')
            if tpm!=('tpm/tpm2/tpm2-00.permall' in present) or (not tpm and any(p.startswith('tpm/') for p in present)):raise b.Error('TPM-Zustand unvollständig oder unerwartet.')
            for n in r.findall('./devices/interface'):
                kind=n.get('type');value=n.find('source').get(kind)
                if kind=='bridge':
                    if not Path('/sys/class/net',value,'bridge').is_dir():raise b.Error('Bridge fehlt: '+value+'. Netzwerk im Wiederherstellungsformular auswählen.')
                elif not conn.networkLookupByName(value).isActive():raise b.Error('libvirt-Netzwerk ist nicht aktiv: '+value)
            # No disk probing: restored disks explicitly use RAW and cannot redirect qemu to host files.
            import pwd,grp
            q_uid=pwd.getpwnam('libvirt-qemu').pw_uid;q_gid=grp.getgrnam('kvm').gr_gid
            tpm_dest=TPM_ROOT/new_uid;made_vm=False;made_tpm=False;defined=None
            try:
                b.unique(conn,new_name);directory.mkdir(mode=0o750);made_vm=True
                for rel in sorted(expected):
                    shutil.move(str(staging/rel),str(directory/rel));os.chown(directory/rel,q_uid,q_gid)
                os.chown(directory,q_uid,q_gid)
                if tpm:
                    if tpm_dest.exists() or tpm_dest.is_symlink():raise b.Error('TPM-Ziel existiert bereits.')
                    t_uid=pwd.getpwnam('tss').pw_uid;t_gid=grp.getgrnam('tss').gr_gid
                    tpm_dest.mkdir(mode=0o700);made_tpm=True
                    shutil.move(str(staging/'tpm'/'tpm2'),str(tpm_dest/'tpm2'))
                    for p in [tpm_dest,*tpm_dest.rglob('*')]:os.chown(p,t_uid,t_gid);p.chmod(0o700 if p.is_dir() else 0o600)
                import libvirt
                log('VM-Definition mit neuer UUID/MAC prüfen und ausgeschaltet anlegen …')
                defined=conn.defineXMLFlags(ET.tostring(r,encoding='unicode'),libvirt.VIR_DOMAIN_DEFINE_VALIDATE)
                defined.setAutostart(0)
            except Exception:
                if defined is not None:
                    # Definition exists: leave its files intact for inspection, never delete a possibly live VM.
                    log('Definition wurde angelegt; Teilergebnis unter '+str(directory)+' prüfen.')
                else:
                    if made_vm:shutil.rmtree(directory)
                    if made_tpm:shutil.rmtree(tpm_dest)
                raise
    log('Wiederhergestellt und ausgeschaltet. Autostart ist aus. Gast-IP, Hostname und Netzwerkkonfiguration vor dem Start prüfen; ursprüngliche VM nicht gleichzeitig mit identischen Gast-Identitäten betreiben.')
    return new_uid


def rescue_export_file(jid):
    matches=list(root().glob(f'*--rescue-job-{int(jid)}.img'))+list(root().glob(f'*--rescue-job-{int(jid)}.qcow2'))
    if len(matches)!=1 or matches[0].is_symlink() or not matches[0].is_file():
        raise b.Error('Abgeschlossenes Export-Abbild nicht gefunden.')
    return matches[0]


def export_rescuezilla(uid,jid,data,log):
    fmt=data.get('format','raw')
    if fmt not in ('raw','qcow2'):raise b.Error('RAW (.img) oder QCOW2 auswählen.')
    with b.connection() as conn:
        dom=conn.lookupByUUIDString(b.domain_id(uid));b.offline(dom)
        if not dom.isPersistent():raise b.Error('Persistente VM erforderlich.')
        original=dom.XMLDesc(2)
        tree=ET.fromstring(original)
        matches=[d for d in tree.findall('./devices/disk') if d.get('device')=='disk' and d.find('target') is not None and d.find('target').get('dev')==data.get('target')]
        if len(matches)!=1:raise b.Error('Systemfestplatte auswählen.')
        disk=matches[0];source=disk.find('source')
        if disk.get('type')!='file' or disk.find('readonly') is not None or disk.find('shareable') is not None or source is None or disk.find('encryption') is not None:
            raise b.Error('Nur lokale, nicht gemeinsam genutzte, beschreibbare Disk-Dateien werden exportiert.')
        src=Path(source.get('file',''))
        if not src.is_absolute() or src.is_symlink() or not src.is_file():raise b.Error('Lokale Disk-Datei fehlt oder ist ein Link.')
        src=src.resolve();b.inactive_image(conn,src);info=b.image_info(src)
        if info.get('format-specific',{}).get('data',{}).get('data-file'):raise b.Error('Externe qcow2-Datendateien werden nicht unterstützt.')
        size=int(info['virtual-size']);space(root(),size)
        before=src.stat();stamp=(before.st_ino,before.st_size,before.st_mtime_ns)
        basename=archive_name(dom.name(),jid).split('--job-')[0]
        dest=root()/(basename+f'--rescue-job-{int(jid)}.'+('img' if fmt=='raw' else 'qcow2'))
        partial=dest.with_suffix(dest.suffix+'.partial')
        if dest.exists() or dest.is_symlink() or partial.exists() or partial.is_symlink():raise b.Error('Exportziel existiert bereits.')
        try:
            # Reserve a private output before qemu-img writes it.
            fd=os.open(partial,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            log(f'Systemfestplatte {data.get("target")} wird exportiert ({size/GiB:.1f} GiB virtuell). VM ausgeschaltet lassen.')
            args=['qemu-img','convert','-f',info['format'],'-O',fmt]
            if fmt=='qcow2':args+=['-c']
            b.command(args+[str(src),str(partial)],timeout=86400)
            b.offline(dom)
            after=src.stat()
            if original!=dom.XMLDesc(2) or stamp!=(after.st_ino,after.st_size,after.st_mtime_ns):raise b.Error('VM oder Quelle während des Exports verändert; Export verworfen.')
            log('Export wird mit der Quelldisk verglichen …')
            b.command(['qemu-img','compare','-f',info['format'],'-F',fmt,str(src),str(partial)],timeout=86400)
            b.offline(dom);after=src.stat()
            if original!=dom.XMLDesc(2) or stamp!=(after.st_ino,after.st_size,after.st_mtime_ns):raise b.Error('VM oder Quelle während der Prüfung verändert; Export verworfen.')
            partial.chmod(0o600);os.replace(partial,dest)
            log('Export geprüft: '+dest.name+'. Download unter Aufträge oder auf der VM-Seite. Rescuezilla auf dem Ziel-PC starten und Abbild wiederherstellen. Zielfestplatte wird überschrieben; Hardware-Bootfähigkeit separat prüfen.')
        finally:partial.unlink(missing_ok=True)
    return uid
