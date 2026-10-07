# -*- coding: utf-8 -*-
from .base import BaseManager
from ..runner import sh

class Manager(BaseManager):
    app_id = "tvheadend"
    label = "Tvheadend"
    kind = "native/systemd"

    service = "tvheadend.service"
    web_url = "http://127.0.0.1:9981"

    config_files = {
        "service": "/usr/lib/systemd/system/tvheadend.service",
        "override": "/etc/systemd/system/tvheadend.service.d/override.conf",
        "defaults": "/etc/default/tvheadend",
        "tvh_config": "/etc/server-manager/tvheadend.conf",
    }

    paths = {
        "tvheadend_home_hts": "/home/hts/.hts/tvheadend",
        "tvheadend_var": "/var/lib/tvheadend",
    }

    def status(self):
        service = self._service_status()
        active = service.get("active") or "unknown"

        ps = sh("pgrep -a tvheadend || true", timeout=10)
        installation = self.installation_status()

        warnings = []

        if active != "active":
            warnings.append("Tvheadend-Dienst ist nicht aktiv")

        return {
            "ok": active == "active",
            "warnings": warnings,
            "status": "running" if active == "active" else active,
            "kind": self.kind,
            "service": service,
            "web_url": self.web_url,
            "installed": installation.get("installed"),
            "installation": installation,
            "process": (ps.get("stdout") or "").strip(),
        }

    def health(self):
        svc = sh("systemctl is-active {}".format(self.service), timeout=10)
        active = (svc.get("stdout") or "").strip()

        # 200, 401 oder 403 gelten als erreichbar, weil Tvheadend oft Auth verlangt.
        web = sh(
            "curl -s -o /dev/null -w '%{{http_code}}' --max-time 5 {}".format(self.web_url),
            timeout=10,
        )
        code = (web.get("stdout") or "").strip()

        return {
            "ok": active == "active" and code in ("200", "302", "401", "403"),
            "service_active": active,
            "web_http": code,
            "web_reachable": code in ("200", "302", "401", "403"),
            "web_url": self.web_url,
        }

    def update_plan(self):
        """Liefert den nativen APT-Updateplan für Tvheadend."""

        check = self.update_check()

        return {
            "supported": True,
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "update_available": check.get("update_available"),
            "state": check.get("state"),
            "current_version": check.get("current_version"),
            "latest_version": check.get("latest_version"),
            "requires_backup": True,
            "safe_to_update": False,
            "update_guard": {
                "blocked": False,
                "reason": None,
                "severity": "info",
                "message": "",
                "details": [],
                "recommendation": "",
            },
            "warnings": check.get("warnings") or [],
            "steps": [
                {
                    "id": "backup",
                    "label": "Tvheadend-Konfiguration sichern",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "apt_lock_check",
                    "label": "APT- und dpkg-Sperren prüfen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "apt_upgrade",
                    "label": "Tvheadend-Paket aktualisieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "service_verify",
                    "label": "Dienst und WebUI prüfen",
                    "required": True,
                    "automatic": True,
                },
            ],
        }


    def update_execute(self, session=None):
        """
        Führt ein Tvheadend-Update über APT aus.

        sudo -n verhindert blockierende Passwortabfragen.
        apt update wird absichtlich nicht automatisch ausgeführt.
        """

        session = session if isinstance(session, dict) else {}
        simulate = bool(session.get("simulate", True))

        plan = self.update_plan()
        steps = []

        def add_step(
            order,
            step_id,
            label,
            status,
            changed=False,
            message="",
            command="",
            output="",
            returncode=None,
        ):
            steps.append({
                "order": order,
                "id": step_id,
                "label": label,
                "status": status,
                "changed": bool(changed),
                "message": message,
                "command": command,
                "output": output,
                "returncode": returncode,
            })

        if not plan.get("update_available"):
            return {
                "supported": True,
                "ok": True,
                "mode": "simulation" if simulate else "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "update_available": False,
                "state": plan.get("state"),
                "message": "Kein Tvheadend-Update erforderlich.",
                "steps": [],
            }

        lock_cmd = (
            "if fuser /var/lib/dpkg/lock-frontend "
            "/var/lib/dpkg/lock "
            "/var/cache/apt/archives/lock "
            "/var/lib/apt/lists/lock >/dev/null 2>&1; "
            "then echo locked; else echo free; fi"
        )

        lock_r = sh(lock_cmd, timeout=15)
        lock_state = (lock_r.get("stdout") or "").strip()

        if lock_state != "free":
            add_step(
                1,
                "apt_lock_check",
                "APT- und dpkg-Sperren prüfen",
                "blocked",
                False,
                "APT oder dpkg wird derzeit von einem anderen Prozess verwendet.",
                lock_cmd,
                (lock_r.get("stdout") or "") + (lock_r.get("stderr") or ""),
                lock_r.get("returncode"),
            )

            return {
                "supported": True,
                "ok": False,
                "blocked": True,
                "mode": "simulation" if simulate else "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": "Tvheadend-Update wegen aktiver APT/dpkg-Sperre blockiert.",
                "steps": steps,
            }

        add_step(
            1,
            "apt_lock_check",
            "APT- und dpkg-Sperren prüfen",
            "executed",
            False,
            "Keine aktive APT/dpkg-Sperre erkannt.",
            lock_cmd,
            lock_state,
            lock_r.get("returncode"),
        )

        if simulate:
            apt_cmd = (
                "DEBIAN_FRONTEND=noninteractive "
                "sudo -n apt-get -s install --only-upgrade tvheadend"
            )
        else:
            apt_cmd = (
                "DEBIAN_FRONTEND=noninteractive "
                "sudo -n apt-get install -y --only-upgrade tvheadend"
            )

        apt_r = sh(
            apt_cmd,
            timeout=1800 if not simulate else 300,
        )

        apt_output = (
            (apt_r.get("stdout") or "")
            + "\n"
            + (apt_r.get("stderr") or "")
        ).strip()

        apt_ok = bool(apt_r.get("ok"))

        add_step(
            2,
            "apt_upgrade",
            (
                "Tvheadend-Update simulieren"
                if simulate
                else "Tvheadend-Paket aktualisieren"
            ),
            "simulated" if simulate and apt_ok else (
                "executed" if apt_ok else "failed"
            ),
            False if simulate else apt_ok,
            (
                "APT-Simulation erfolgreich."
                if simulate and apt_ok
                else (
                    "Tvheadend-Paket wurde aktualisiert."
                    if apt_ok
                    else "APT-Update ist fehlgeschlagen."
                )
            ),
            apt_cmd,
            apt_output,
            apt_r.get("returncode"),
        )

        if not apt_ok:
            sudo_problem = (
                "a password is required" in apt_output.lower()
                or "ein passwort ist erforderlich" in apt_output.lower()
                or "no tty present" in apt_output.lower()
                or "a terminal is required" in apt_output.lower()
                or "not allowed to execute" in apt_output.lower()
                or "darf" in apt_output.lower() and "nicht" in apt_output.lower()
            )

            message = (
                "APT-Ausführung durch fehlende sudo-Berechtigung blockiert."
                if sudo_problem
                else "Tvheadend-APT-Update fehlgeschlagen."
            )

            return {
                "supported": True,
                "ok": False,
                "blocked": bool(sudo_problem),
                "mode": "simulation" if simulate else "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": message,
                "steps": steps,
                "warnings": (
                    [
                        "Der Benutzer des Server Managers benötigt eine "
                        "NOPASSWD-Berechtigung für apt-get."
                    ]
                    if sudo_problem
                    else []
                ),
            }

        if simulate:
            return {
                "supported": True,
                "ok": True,
                "simulate": True,
                "mode": "simulation",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": "Tvheadend-APT-Update erfolgreich simuliert.",
                "steps": steps,
            }

        verify = self.update_verify()

        add_step(
            3,
            "service_verify",
            "Dienst und WebUI prüfen",
            "executed" if verify.get("ok") else "failed",
            False,
            verify.get("message") or "",
            "",
            "",
            0 if verify.get("ok") else 1,
        )

        return {
            "supported": True,
            "ok": bool(verify.get("ok")),
            "mode": "execute",
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "message": (
                "Tvheadend wurde aktualisiert und erfolgreich geprüft."
                if verify.get("ok")
                else "Tvheadend wurde aktualisiert, aber die Prüfung ist fehlgeschlagen."
            ),
            "steps": steps,
            "verify": verify,
        }


    def update_verify(self):
        """Prüft Version, Dienststatus und WebUI nach dem Update."""

        check = self.update_check()
        health = self.health()

        current_version = check.get("current_version")
        latest_version = check.get("latest_version")
        update_available = check.get("update_available")

        version_ok = update_available is False
        health_ok = bool(health.get("ok"))
        ok = version_ok and health_ok

        return {
            "supported": True,
            "ok": ok,
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "message": (
                "Tvheadend-Version, Dienst und WebUI sind in Ordnung."
                if ok
                else "Tvheadend-Verifikation meldet einen Fehler."
            ),
            "current_version": current_version,
            "candidate_version": latest_version,
            "update_available": update_available,
            "version_ok": version_ok,
            "health_ok": health_ok,
            "health": health,
            "update_check": check,
        }


    def update_check(self):
        """Prüft Tvheadend über den lokalen APT-Paketindex."""

        return self.native_apt_update_check(
            "tvheadend",
            method="tvheadend-apt",
            requires_backup=True,
        )


    def info(self):
        ver = sh("tvheadend --version 2>/dev/null | head -1 || true", timeout=10)
        unit = sh("systemctl show tvheadend.service -p ExecStart --value 2>/dev/null || true", timeout=10)

        return {
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "service": self.service,
            "web_url": self.web_url,
            "version": (ver.get("stdout") or "").strip(),
            "exec_start": (unit.get("stdout") or "").strip(),
            "backup_note": "Sichert Tvheadend-Konfiguration. Aufnahmen werden nicht gesichert.",
        }
