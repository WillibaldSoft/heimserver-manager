from server_settings import BASE_DIR, CONFIG_DIR, STATE_DIR
import shlex
import os
# -*- coding: utf-8 -*-
from .base import BaseManager
from ..runner import sh

class Manager(BaseManager):
    app_id = "server_manager"
    label = "Heimserver Manager"
    kind = "native/systemd"

    service = "server-manager.service"
    web_url = "http://127.0.0.1:" + os.environ.get("SERVER_MANAGER_PORT", "9877") + "/api/health"

    config_files = {
        "service": "/etc/systemd/system/server-manager.service",
    }

    paths = {
        "server_manager": str(BASE_DIR),
        "configuration": str(CONFIG_DIR),
    }

    database = {
        "type": "sqlite",
        "file": os.environ.get("SERVER_MANAGER_DB", str(STATE_DIR / "server-manager.sqlite3")),
    }

    backup_profiles = {"system": {"data": True, "path_keys": ["configuration"], "description": "Sichert Manager-Einstellungen, Dienstdefinition und konsistente SQLite-Datenbank."}}

    def status(self):
        r = sh("systemctl is-active {}".format(self.service), timeout=10)
        active = (r.get("stdout") or "").strip()

        return {
            "ok": active == "active",
            "status": "running" if active == "active" else active,
            "kind": self.kind,
            "service": {"service": self.service, "active": active},
            "web_url": self.web_url,
            "installed": self.installation_status().get("installed"),
            "installation": self.installation_status(),
        }

    def update_check(self):
        from ..catalog_updates import result,apt_check
        from version import VERSION
        checked=apt_check(self,['server-manager'])
        if checked.get('update_available') is True:return checked
        return result(self,state='manual',label='DEB-Version manuell vergleichen',current_version=VERSION,method='DEB / lokale Entwicklung',message='Keine zentrale Releasequelle für hochgeladene DEB-Pakete konfiguriert. Verfügbare Paketversion unter Einstellungen → Manager aktualisieren vergleichen; der lokale Stand bestätigt nicht die neueste Veröffentlichung.')

    def health(self):
        web = sh("curl -fsS --max-time 5 {} >/dev/null".format(self.web_url), timeout=10)
        svc = sh("systemctl is-active {}".format(self.service), timeout=10)

        return {
            "ok": web.get("returncode") == 0 and (svc.get("stdout") or "").strip() == "active",
            "service_active": (svc.get("stdout") or "").strip(),
            "web_ok": web.get("returncode") == 0,
            "web_url": self.web_url,
        }

    def info(self):
        git = sh("cd " + shlex.quote(str(BASE_DIR)) + " && git rev-parse --short HEAD 2>/dev/null || true", timeout=10)
        branch = sh("cd " + shlex.quote(str(BASE_DIR)) + " && git branch --show-current 2>/dev/null || true", timeout=10)

        return {
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "service": self.service,
            "web_url": self.web_url,
            "git_commit": (git.get("stdout") or "").strip(),
            "git_branch": (branch.get("stdout") or "").strip(),
            "backup_note": "Sichert Projektverzeichnis, systemd-Service und SQLite-Datenbank. Restore später nur manuell/freigegeben.",
        }
