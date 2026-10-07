"""Keep the server awake for active guests and KVM jobs; fail closed on unknown state."""
from . import backend
from pathlib import Path
import shutil
_SERVICE=None

def local_installation_present():
    # Client bindings alone are not a configured virtualization host.
    if any(shutil.which(name) for name in ('libvirtd','virtqemud','qemu-system-x86_64','qemu-system-aarch64')):return True
    for folder in ('/etc/systemd/system','/run/systemd/system','/usr/lib/systemd/system','/lib/systemd/system'):
        for name in ('libvirtd.service','libvirtd.socket','virtqemud.service','virtqemud.socket'):
            if (Path(folder)/name).exists():return True
    if any(Path(p).exists() for p in ('/run/libvirt/libvirt-sock','/run/libvirt/libvirt-sock-ro','/run/libvirt/virtqemud-sock')):return True
    try:return any(Path('/etc/libvirt/qemu').glob('*.xml'))
    except OSError:return True # uncertain inventory must preserve sleep protection

_observed=False

def get_blockers(ctx=None):
    global _observed
    result=[]
    if _SERVICE is None:
        return [dict(source='KVM',type='error',title='KVM-Status unbekannt',reason='Modul nicht initialisiert',priority=999,url='/kvm')]
    for job in _SERVICE.active():
        result.append(dict(source='KVM',type='kvm-schedule-job' if job['action'] in ('schedule-shutdown','schedule-shutdown-all') else 'kvm-job',title='KVM-Auftrag',reason=f"#{job['id']}: {job['action']}",priority=90,url='/kvm/jobs'))
    try:
        with backend.connection() as conn:
            _observed=True
            active_managed=set()
            for dom in conn.listAllDomains():
                if dom.isActive():
                    mode=_SERVICE.sleep_mode(dom.UUIDString())
                    if mode=='managed':active_managed.add(dom.UUIDString())
                    if mode=='ignore':continue
                    result.append(dict(source='KVM',type='kvm-managed-vm' if mode=='managed' else 'kvm-vm',vm=dom.UUIDString(),title=dom.name(),reason='Wartet auf reguläres Herunterfahren durch Schlaf & Wake (pausierte VMs zuerst fortsetzen).' if mode=='managed' else 'Virtuelle Maschine ist aktiv (auch pausierte VMs behalten RAM).',priority=80,url='/kvm/vm/'+dom.UUIDString()))
            _SERVICE.clear_finished_shutdowns(active_managed)
    except Exception as exc:
        if not _observed and not local_installation_present():return result
        result.append(dict(source='KVM',type='error',title='KVM-Status nicht prüfbar',reason=str(exc),priority=999,url='/kvm'))
    return result
