# -*- coding: utf-8 -*-
from .base import BaseManager
from ..runner import sh

class Manager(BaseManager):
    app_id = 'shares_mounts'
    label = 'Mounts / Freigaben'
    kind = 'system'

    def status(self):
        fstab = sh("grep -Ev '^#|^$' /etc/fstab | grep -Ei 'nfs|cifs|smb|/SVL|/Serverspeicher' || true", timeout=5)['stdout']
        units = sh("systemctl list-units --all --type=mount --type=automount --no-pager 2>/dev/null | grep -Ei 'SVL|Serverspeicher|mnt|automount|nfs|cifs' || true", timeout=8)['stdout']
        failed = sh("systemctl --failed --no-pager | grep -Ei 'mount|automount|nfs|cifs|smb' || true", timeout=8)['stdout']
        cycles = sh("journalctl -b -p warning --no-pager | grep -Ei 'ordering cycle|mount|automount|network-online' | tail -30 || true", timeout=8)['stdout']
        ok = not bool(failed.strip())
        return {"id": self.app_id, "label": self.label, "kind": self.kind, "ok": ok, "warnings": ["failed mounts"] if not ok else [], "fstab": fstab, "units": units, "failed": failed, "ordering_cycles": cycles}

    def info(self):
        return self.status()

    def health(self):
        return self.status()
