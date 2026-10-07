from .base import BaseManager
from ..runner import run
class Manager(BaseManager):
 app_id='kvm';label='KVM / libvirt';kind='native';service='libvirtd.service';web_url='/kvm'
 config_files={};paths={}
 def installation_status(self):
  p=run(['dpkg-query','-W','-f=${db:Status-Status}\\n','libvirt-daemon-system','libvirt-clients'],timeout=10)
  installed=p['ok'] and p['stdout'].splitlines()==['installed','installed']
  return dict(installed=installed,state='installed' if installed else 'missing')
 def status(self):
  installation=self.installation_status();p=run(['virsh','-c','qemu:///system','list','--all'],timeout=15) if installation['installed'] else {'ok':False}
  return dict(ok=p['ok'],status='running' if p['ok'] else 'stopped',kind=self.kind,installed=installation['installed'],installation=installation)
 def info(self):return {'Virtualisierung':'QEMU/KVM über qemu:///system','Verwaltung':'Server → Virtuelle Maschinen'}
 def health(self):return self.status()
 def update_check(self):
  from ..kvm_setup import packages
  names=list(dict.fromkeys(packages()+['libvirt0','libvirt-daemon-driver-qemu','qemu-system-common']))
  results={n:self.native_apt_update_check(n,method='kvm-apt',requires_backup=True) for n in names}
  installed={n:r for n,r in results.items() if r.get('state')!='missing'}
  available=[n for n,r in installed.items() if r.get('update_available') is True]
  uncertain=[n for n,r in installed.items() if not r.get('ok') or r.get('state') in ('unknown','error')]
  state='available' if available else 'unknown' if uncertain else 'current' if installed else 'missing'
  labels={'available':'Update verfügbar','unknown':'Nicht vollständig prüfbar','current':'Aktuell','missing':'Nicht installiert'}
  def versions(field):
   core=['libvirt-daemon-system']+[n for n in names if n in ('qemu-system-x86','qemu-system-arm')]
   return ' · '.join(('libvirt' if n=='libvirt-daemon-system' else 'QEMU')+': '+str(results[n].get(field) or '—') for n in core)
  return self.native_update_result(supported=True,ok=not uncertain,state=state,label=labels[state],message='Aktualisierbare Pakete: '+', '.join(available) if available else 'Prüfung anhand des lokalen APT-Paketindex.',current_version=versions('current_version'),latest_version=versions('latest_version'),update_available=True if available else None if uncertain or not installed else False,method='kvm-apt',details={'packages':results,'package_index_refreshed':False},warnings=['Lokaler APT-Paketindex; Paketlisten bei Bedarf über die APT-Karte aktualisieren.'],safe_to_update=False,requires_backup=True)
