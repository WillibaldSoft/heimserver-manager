"""Host-local choices; disabling discovery also disables its sleep blockers."""
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import subprocess
import time
import server_settings as host

FILE=host.CONFIG_DIR/'modules.json'
DEFAULTS={'configured':False,'network':True,'tv':'auto','interface':'','cidr':''}

def load():
    data=dict(DEFAULTS)
    try:saved=json.loads(FILE.read_text())
    except FileNotFoundError:return data
    if not isinstance(saved,dict):raise ValueError('Ungültige Modulauswahl.')
    data.update(saved)
    if type(data['network']) is not bool or data['tv'] not in ('auto','on','off'):raise ValueError('Ungültige Modulauswahl.')
    return data

def revision():
    try:return hashlib.sha256(FILE.read_bytes()).hexdigest()
    except FileNotFoundError:return 'new'

def network_enabled():return load()['network']
def tv_mode():return load()['tv']
def tv_visible():
    from modules.tvheadend.config import monitoring_enabled
    return monitoring_enabled()

def valid_interface(value):
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}',value) or value in ('.','..','lo') or value.startswith(('docker','veth','virbr','br-','tun','tap','vnet')):raise ValueError('Eine LAN-Schnittstelle oder LAN-Bridge auswählen; keine Docker-/VM-Schnittstelle.')
    if not Path('/sys/class/net',value).exists():raise ValueError('LAN-Schnittstelle existiert nicht.')
    return value

def valid_network(value):
    net=ipaddress.ip_network(value,strict=True)
    if net.version!=4 or net.prefixlen<20 or net.is_loopback or net.is_multicast or net.is_unspecified:raise ValueError('IPv4-LAN mit höchstens 4096 Adressen (/20 oder kleiner) angeben.')
    return str(net)

_detected=(0,None)
def detect_lan():
    global _detected
    now=time.monotonic()
    if now-_detected[0]<10:return _detected[1]
    result=None
    try:
        routes=json.loads(subprocess.check_output(['ip','-j','-4','route','show','default'],timeout=3,text=True))
        devices={r['dev'] for r in routes if r.get('dev')}
        if len(devices)==1:
            interface=valid_interface(devices.pop())
            records=json.loads(subprocess.check_output(['ip','-j','-4','address','show','dev',interface,'scope','global'],timeout=3,text=True))
            nets={valid_network(str(ipaddress.ip_interface(a['local']+'/'+str(a['prefixlen'])).network)) for r in records for a in r.get('addr_info',[]) if a.get('family')=='inet'}
            if len(nets)==1:result={'interface':interface,'cidr':nets.pop()}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
    _detected=(now,result);return result

def network_values(fallback_network=None):
    data=load();detected=detect_lan() or {}
    interface=data['interface'] or detected.get('interface','')
    explicit=host.read(host.CONFIG).get('lan_network')
    cidr=data['cidr'] or (str(fallback_network or explicit) if explicit else detected.get('cidr',''))
    if not interface or not cidr:raise ValueError('LAN nicht eindeutig erkannt. Unter Einstellungen → Modulauswahl Schnittstelle und IPv4-Netz festlegen.')
    return interface,ipaddress.ip_network(cidr,strict=True)

def save(data,expected):
    if expected!=revision():raise ValueError('Modulauswahl wurde zwischenzeitlich geändert. Seite neu laden.')
    if data.get('tv') not in ('auto','on','off') or type(data.get('network')) is not bool:raise ValueError('Ungültige Modulauswahl.')
    interface=str(data.get('interface','')).strip();cidr=str(data.get('cidr','')).strip()
    if interface:valid_interface(interface)
    if cidr:cidr=valid_network(cidr)
    if data['network'] and not (interface and cidr) and not detect_lan():raise ValueError('Kein eindeutiges LAN erkannt. Schnittstelle und IPv4-Netz angeben.')
    host.atomic(FILE,dict(configured=True,network=data['network'],tv=data['tv'],interface=interface,cidr=cidr))

def visible_groups(groups):
    data=load();out=[]
    for label,url,children in groups:
        if url=='/tv' and not tv_visible():continue
        if url=='/heimnetz' and not data['network']:continue
        out.append((label,url,children))
    return out
