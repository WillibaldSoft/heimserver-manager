"""Explicit package targets; ID_LIKE never grants installation permission."""
import re
from pathlib import Path
PROFILES={
 'debian13':{'label':'Debian 13','python':'3.13','experimental':False},
 'mint22':{'label':'Linux Mint 22.x (Ubuntu Noble), experimentell','python':'3.12','experimental':True},
}
def read_release(path=Path('/etc/os-release')):
 values={}
 for line in Path(path).read_text().splitlines():
  key,sep,value=line.partition('=')
  if sep and key in ('ID','VERSION_ID','UBUNTU_CODENAME'):
   values[key]=value.removeprefix('"').removesuffix('"').removeprefix("'").removesuffix("'")
 return values
def matches(target,values):
 if target=='debian13':return values.get('ID')=='debian' and values.get('VERSION_ID')=='13'
 if target=='mint22':return values.get('ID')=='linuxmint' and re.fullmatch(r'22(?:\.[0-9]{1,2})?',values.get('VERSION_ID','')) is not None and values.get('UBUNTU_CODENAME')=='noble'
 return False
def require(target,values=None):
 values=read_release() if values is None else values
 if not matches(target,values):raise ValueError('Installation blockiert: Paket für '+str(target or 'unbekannte Plattform')+', erkannt '+values.get('ID','unbekannt')+' '+values.get('VERSION_ID','')+'. Passendes Plattformpaket verwenden.')
 return target

def mint_desktop():
 try:return read_release().get('ID')=='linuxmint'
 except OSError:return False
