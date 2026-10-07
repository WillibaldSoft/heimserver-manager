from server_settings import app_literal as host_literal
# -*- coding: utf-8 -*-
import time

from .base import BaseManager
from ..runner import sh

class Manager(BaseManager):
    app_id = 'nextcloud'
    label = 'Nextcloud'
    kind = 'apache/php'
    installation_mode = 'Nativ (Apache/PHP)'
    service = 'apache2.service'
    web_url = 'http://127.0.0.1/nextcloud/status.php'

    config_files = {
        'config.php': host_literal('nextcloud', '/var/www/html/nextcloud/config/config.php'),
        'apache-nextcloud.conf': '/etc/apache2/sites-available/nextcloud.conf',
    }

    paths = {
        'nextcloud_app': host_literal('nextcloud', '/var/www/html/nextcloud'),
        'nextcloud_data': host_literal('nextcloud', '/srv/nextcloud-data'),
    }

    # Pre-Update-Backup:
    # Core-/App-Code, Konfiguration und Datenbank sichern,
    # aber nicht den großen externen Nextcloud-Datenbestand.
    backup_profiles = {
        "update": {
            "id": "update",
            "label": "Update-Backup",
            "description": (
                "Sichert Nextcloud-Code, Konfiguration, "
                "Datenbank und Zusatzinformationen ohne "
                "Benutzer-Datenverzeichnis."
            ),
            "config": True,
            "data": True,
            "database": True,
            "extra": True,
            "incremental": False,
            "path_keys": [
                "nextcloud_app",
            ],
        },
    }

    update_backup_profile = "update"

    database = {
        'type': 'mariadb-local',
        'database': 'nextcloud',
        'user': 'root',
        'dump': (
            'mariadb-dump '
            '--single-transaction '
            '--quick '
            '--routines '
            '--events '
            '--triggers '
            '--default-character-set=utf8mb4 '
            'nextcloud'
        ),
    }

    def health(self):
        """
        Prüft Nextcloud auf echte Betriebsbereitschaft.

        Bedingungen:
          - Apache läuft
          - status.php ist per HTTP erreichbar
          - OCC meldet installed=true
          - Wartungsmodus ist aus
          - kein Datenbank-Upgrade ist offen
        """

        service = self._service_status()
        web = self._web_check()

        occ_cmd = (
            host_literal('nextcloud', "sudo -n -u www-data php "
            "/var/www/html/nextcloud/occ status 2>&1")
        )

        occ_r = sh(
            occ_cmd,
            timeout=30,
        )

        occ_output = (
            (occ_r.get("stdout") or "")
            + "\n"
            + (occ_r.get("stderr") or "")
        ).strip()

        occ = {
            "ok": bool(occ_r.get("ok")),
            "installed": False,
            "version": None,
            "maintenance": None,
            "needs_db_upgrade": None,
            "output": occ_output,
            "returncode": occ_r.get("returncode"),
        }

        for line in occ_output.splitlines():
            raw = line.strip()

            if raw.startswith("- installed:"):
                occ["installed"] = (
                    raw.split(":", 1)[1]
                    .strip()
                    .lower()
                    == "true"
                )

            elif raw.startswith("- versionstring:"):
                occ["version"] = (
                    raw.split(":", 1)[1]
                    .strip()
                )

            elif raw.startswith("- maintenance:"):
                occ["maintenance"] = (
                    raw.split(":", 1)[1]
                    .strip()
                    .lower()
                    == "true"
                )

            elif raw.startswith("- needsDbUpgrade:"):
                occ["needs_db_upgrade"] = (
                    raw.split(":", 1)[1]
                    .strip()
                    .lower()
                    == "true"
                )

        service_ok = (
            str(service.get("active") or "").strip()
            == "active"
        )

        web_ok = bool(
            web.get("ok") is True
        )

        occ_ok = bool(
            occ.get("ok")
            and occ.get("installed") is True
            and occ.get("maintenance") is False
            and occ.get("needs_db_upgrade") is False
        )

        ok = bool(
            service_ok
            and web_ok
            and occ_ok
        )

        warnings = []

        if not service_ok:
            warnings.append(
                "Apache ist nicht aktiv."
            )

        if not web_ok:
            warnings.append(
                "Nextcloud status.php ist nicht erreichbar."
            )

        if not occ.get("ok"):
            warnings.append(
                "OCC-Status konnte nicht gelesen werden."
            )

        if occ.get("maintenance") is True:
            warnings.append(
                "Nextcloud befindet sich im Wartungsmodus."
            )

        if occ.get("needs_db_upgrade") is True:
            warnings.append(
                "Nextcloud benötigt ein Datenbank-Upgrade."
            )

        if occ.get("ok") and not occ.get("installed"):
            warnings.append(
                "OCC meldet Nextcloud nicht als installiert."
            )

        return {
            "id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "ok": ok,
            "warnings": warnings,
            "installed": self.installation_status().get(
                "installed"
            ),
            "installation": self.installation_status(),
            "service": service,
            "web": web,
            "occ": occ,
        }


    def stop_for_restore(self):
        """
        Stoppt Apache vor einem Nextcloud-Restore.
        """

        r = sh(
            "systemctl stop apache2.service",
            timeout=120,
        )

        return {
            "ok": r.get("returncode") == 0,
            "changed": r.get("returncode") == 0,
            "method": "systemctl stop",
            "service": "apache2.service",
            "returncode": r.get("returncode"),
            "stdout": r.get("stdout"),
            "stderr": r.get("stderr"),
            "message": (
                "Apache für Nextcloud-Restore gestoppt."
                if r.get("returncode") == 0
                else
                "Apache konnte nicht gestoppt werden."
            ),
        }

    def start_after_restore(self):
        """
        Startet Apache nach einem Nextcloud-Restore.
        """

        r = sh(
            "systemctl start apache2.service",
            timeout=120,
        )

        return {
            "ok": r.get("returncode") == 0,
            "changed": r.get("returncode") == 0,
            "method": "systemctl start",
            "service": "apache2.service",
            "returncode": r.get("returncode"),
            "stdout": r.get("stdout"),
            "stderr": r.get("stderr"),
            "message": (
                "Apache nach Nextcloud-Restore gestartet."
                if r.get("returncode") == 0
                else
                "Apache konnte nicht gestartet werden."
            ),
        }

    def restore_healthcheck(self):
        """
        Verwendet die gehärtete Nextcloud-Health-Prüfung
        auch für Restore-Verifikation.
        """

        return self.health()

    def info(self):
        occ = sh(host_literal('nextcloud', 'sudo -u www-data php /var/www/html/nextcloud/occ status 2>/dev/null || true'), timeout=15)['stdout']
        php = sh('php -v 2>/dev/null | head -1 || true', timeout=5)['stdout']
        return {"occ_status": occ, "php": php}

    def update_check(self):
        """Prüft native Nextcloud-Installation über OCC."""

        occ = host_literal('nextcloud', "/var/www/html/nextcloud/occ")

        status_r = sh(
            host_literal('nextcloud', "sudo -u www-data php {} status 2>&1").format(occ),
            timeout=30,
        )

        status_text = (
            (status_r.get("stdout") or "")
            + "\n"
            + (status_r.get("stderr") or "")
        ).strip()

        current_version = None
        installed = False
        maintenance = None
        needs_db_upgrade = None

        for line in status_text.splitlines():
            raw = line.strip()

            if raw.startswith("- installed:"):
                installed = raw.split(":", 1)[1].strip().lower() == "true"

            elif raw.startswith("- versionstring:"):
                current_version = raw.split(":", 1)[1].strip()

            elif raw.startswith("- maintenance:"):
                maintenance = raw.split(":", 1)[1].strip().lower() == "true"

            elif raw.startswith("- needsDbUpgrade:"):
                needs_db_upgrade = raw.split(":", 1)[1].strip().lower() == "true"

        if not status_r.get("ok") or not installed:
            return self.native_update_result(
                supported=True,
                ok=False,
                state="error",
                label="Prüfung fehlgeschlagen",
                message="Nextcloud OCC-Status konnte nicht sicher ermittelt werden.",
                current_version=current_version,
                latest_version=None,
                update_available=None,
                method="nextcloud-occ-update-check",
                details={
                    "occ_status": status_text,
                    "maintenance": maintenance,
                    "needs_db_upgrade": needs_db_upgrade,
                },
            )

        check_r = sh(
            host_literal('nextcloud', "sudo -u www-data php {} update:check 2>&1").format(occ),
            timeout=120,
        )

        check_text = (
            (check_r.get("stdout") or "")
            + "\n"
            + (check_r.get("stderr") or "")
        ).strip()

        text_lower = check_text.lower()

        latest_version = None
        update_available = None
        state = "unknown"
        label = "Unbekannt"
        message = "Nextcloud Update-Status konnte nicht eindeutig ermittelt werden."
        ok = bool(check_r.get("ok"))

        import re

        # OCC update:check kann sowohl Nextcloud-Core- als auch App-Updates
        # melden. App-Versionen dürfen nicht als neue Nextcloud-Version
        # interpretiert werden.
        app_updates = []

        for match in re.finditer(
            r"^Update for\s+(.+?)\s+to version\s+"
            r"([0-9]+(?:\.[0-9]+){1,3})\s+is available\.$",
            check_text,
            re.IGNORECASE | re.MULTILINE,
        ):
            app_updates.append({
                "app": match.group(1).strip(),
                "version": match.group(2),
            })

        core_patterns = [
            r"Nextcloud\s+([0-9]+(?:\.[0-9]+){1,3})\s+is available",
            r"Nextcloud\s+version\s+([0-9]+(?:\.[0-9]+){1,3})\s+is available",
            r"new Nextcloud version\s+([0-9]+(?:\.[0-9]+){1,3})",
        ]

        core_version = None

        for pattern in core_patterns:
            match = re.search(pattern, check_text, re.IGNORECASE)
            if match:
                core_version = match.group(1)
                break

        if core_version:
            latest_version = core_version
            update_available = True
            state = "available"
            label = "Update verfügbar"
            message = "Nextcloud {} ist verfügbar.".format(core_version)

        elif app_updates:
            latest_version = current_version
            update_available = False
            state = "current"
            label = "Aktuell"

            app_text = ", ".join(
                "{} {}".format(item["app"], item["version"])
                for item in app_updates
            )

            message = (
                "Nextcloud Core ist aktuell. "
                "App-Updates verfügbar: {}.".format(app_text)
            )

        elif "everything up to date" in text_lower:
            latest_version = current_version
            update_available = False
            state = "current"
            label = "Aktuell"
            message = "Nextcloud ist aktuell."

        elif not check_r.get("ok"):
            state = "error"
            label = "Prüfung fehlgeschlagen"
            message = "Nextcloud update:check ist fehlgeschlagen."
            update_available = None
            ok = False

        elif (
            "update available" in text_lower
            or "is available" in text_lower
            or "new version" in text_lower
        ):
            state = "unknown"
            label = "Unklar"
            message = (
                "OCC meldet ein Update, aber keine eindeutige "
                "Nextcloud-Core-Version."
            )
            latest_version = None
            update_available = None

        return self.native_update_result(
            supported=True,
            ok=ok,
            state=state,
            label=label,
            message=message,
            current_version=current_version,
            latest_version=latest_version,
            update_available=update_available,
            method="nextcloud-occ-update-check",
            details={
                "occ_status": status_text,
                "update_check": check_text,
                "maintenance": maintenance,
                "needs_db_upgrade": needs_db_upgrade,
                "app_updates": app_updates,
            },
            warnings=[
                "Nextcloud befindet sich im Wartungsmodus."
            ] if maintenance else [],
            safe_to_update=False,
            requires_backup=True,
        )


    def update_plan(self):
        """Liefert den nativen Updateplan für Nextcloud."""

        check = self.update_check()

        return {
            "supported": True,
            "ok": bool(check.get("ok", True)),
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "method": "nextcloud-cli-updater",
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
            "errors": check.get("errors") or [],
            "steps": [
                {
                    "id": "occ_precheck",
                    "label": "Nextcloud-Status vor dem Update prüfen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "cli_updater",
                    "label": "Nextcloud CLI-Updater ausführen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "database_upgrade",
                    "label": "Datenbank-Upgrade kontrollieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "maintenance_mode",
                    "label": "Wartungsmodus kontrollieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "occ_verify",
                    "label": "Nextcloud nach dem Update verifizieren",
                    "required": True,
                    "automatic": True,
                },
            ],
        }


    def update_execute(self, session=None):
        """
        Führt ein natives Nextcloud-Core-Update mit updater.phar aus.

        Der Nextcloud-Updater läuft als www-data. sudo -n verhindert,
        dass der Webdienst durch eine Passwortabfrage hängen bleibt.
        """

        session = session if isinstance(session, dict) else {}
        simulate = bool(session.get("simulate", True))

        occ = host_literal('nextcloud', "/var/www/html/nextcloud/occ")
        updater = host_literal('nextcloud', "/var/www/html/nextcloud/updater/updater.phar")

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

        def combined_output(result):
            return (
                (result.get("stdout") or "")
                + "\n"
                + (result.get("stderr") or "")
            ).strip()

        def parse_occ_status(output):
            parsed = {
                "installed": False,
                "version": None,
                "maintenance": None,
                "needs_db_upgrade": None,
            }

            for line in output.splitlines():
                raw = line.strip()

                if raw.startswith("- installed:"):
                    parsed["installed"] = (
                        raw.split(":", 1)[1].strip().lower() == "true"
                    )

                elif raw.startswith("- versionstring:"):
                    parsed["version"] = raw.split(":", 1)[1].strip()

                elif raw.startswith("- maintenance:"):
                    parsed["maintenance"] = (
                        raw.split(":", 1)[1].strip().lower() == "true"
                    )

                elif raw.startswith("- needsDbUpgrade:"):
                    parsed["needs_db_upgrade"] = (
                        raw.split(":", 1)[1].strip().lower() == "true"
                    )

            return parsed

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
                "message": "Kein Nextcloud-Core-Update erforderlich.",
                "steps": [],
            }

        status_cmd = (
            host_literal('nextcloud', "sudo -n -u www-data php {} status 2>&1")
        ).format(occ)

        status_r = sh(status_cmd, timeout=60)
        status_output = combined_output(status_r)
        pre_status = parse_occ_status(status_output)

        precheck_ok = bool(
            status_r.get("ok")
            and pre_status.get("installed")
            and pre_status.get("maintenance") is False
            and pre_status.get("needs_db_upgrade") is False
        )

        add_step(
            1,
            "occ_precheck",
            "Nextcloud-Status vor dem Update prüfen",
            "executed" if precheck_ok else "failed",
            False,
            (
                "Nextcloud {} ist bereit für das Update.".format(
                    pre_status.get("version") or "unbekannt"
                )
                if precheck_ok
                else "Nextcloud ist vor dem Update nicht in einem sicheren Zustand."
            ),
            status_cmd,
            status_output,
            status_r.get("returncode"),
        )

        if not precheck_ok:
            return {
                "supported": True,
                "ok": False,
                "mode": "simulation" if simulate else "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": "Nextcloud-Vorprüfung fehlgeschlagen.",
                "steps": steps,
                "warnings": [
                    "Wartungsmodus, DB-Upgrade-Status und sudo-Berechtigung prüfen."
                ],
            }

        updater_cmd = (
            host_literal('nextcloud', "sudo -n -u www-data php {} --no-interaction 2>&1")
        ).format(updater)

        if simulate:
            add_step(
                2,
                "cli_updater",
                "Nextcloud CLI-Updater ausführen",
                "simulated",
                False,
                (
                    "Simulation: Nextcloud {} würde auf {} aktualisiert."
                ).format(
                    plan.get("current_version") or "unbekannt",
                    plan.get("latest_version") or "unbekannt",
                ),
                updater_cmd,
                "",
                0,
            )

            add_step(
                3,
                "database_upgrade",
                "Datenbank-Upgrade kontrollieren",
                "simulated",
                False,
                "Simulation: OCC-Datenbankstatus würde nach dem Update geprüft.",
                "",
                "",
                0,
            )

            add_step(
                4,
                "maintenance_mode",
                "Wartungsmodus kontrollieren",
                "simulated",
                False,
                "Simulation: Wartungsmodus würde kontrolliert und nötigenfalls beendet.",
                "",
                "",
                0,
            )

            add_step(
                5,
                "occ_verify",
                "Nextcloud nach dem Update verifizieren",
                "simulated",
                False,
                "Simulation: Nextcloud-Status und Erreichbarkeit würden geprüft.",
                "",
                "",
                0,
            )

            return {
                "supported": True,
                "ok": True,
                "simulate": True,
                "mode": "simulation",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "current_version": plan.get("current_version"),
                "latest_version": plan.get("latest_version"),
                "message": "Nextcloud-Core-Update erfolgreich simuliert.",
                "steps": steps,
            }

        updater_r = sh(updater_cmd, timeout=3600)
        updater_output = combined_output(updater_r)
        updater_ok = bool(updater_r.get("ok"))

        output_lower = updater_output.lower()
        sudo_problem = (
            "a password is required" in output_lower
            or "ein passwort ist erforderlich" in output_lower
            or "no tty present" in output_lower
            or "a terminal is required" in output_lower
            or "not allowed to execute" in output_lower
            or (
                "darf" in output_lower
                and "nicht" in output_lower
            )
        )

        # Bewerten, ob der Nextcloud-Updater den produktiven
        # Installationszustand bereits verändert haben kann.
        #
        # Download, Integritätsprüfung und das interne Updater-Backup
        # verändern die produktive Nextcloud-Installation noch nicht.
        # Erst die nachfolgenden Installationsschritte gelten als
        # produktive Änderung.
        if updater_ok:
            updater_changed = True

        elif sudo_problem:
            updater_changed = False

        else:
            productive_markers = (
                "replace entry points",
                "delete old files",
                "move new files in place",
            )

            preparation_failure_markers = (
                "check for expected files",
                "check for write permissions",
                "create backup",
                "downloading failed",
                "verify integrity failed",
                "there are more files than the downloaded archive",
                "extracting failed",
            )

            productive_started = any(
                marker in output_lower
                for marker in productive_markers
            )

            preparation_failed = any(
                marker in output_lower
                for marker in preparation_failure_markers
            )

            if productive_started:
                updater_changed = True
            elif preparation_failed:
                updater_changed = False
            else:
                # Unbekannter Fehlerzustand:
                # konservativ von möglicher Änderung ausgehen.
                updater_changed = True

        add_step(
            2,
            "cli_updater",
            "Nextcloud CLI-Updater ausführen",
            "executed" if updater_ok else "failed",
            updater_changed,
            (
                "Nextcloud CLI-Updater wurde erfolgreich ausgeführt."
                if updater_ok
                else (
                    "CLI-Updater durch fehlende sudo-Berechtigung blockiert."
                    if sudo_problem
                    else "Nextcloud CLI-Updater ist fehlgeschlagen."
                )
            ),
            updater_cmd,
            updater_output,
            updater_r.get("returncode"),
        )

        if not updater_ok:
            return {
                "supported": True,
                "ok": False,
                "blocked": bool(sudo_problem),
                "mode": "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": (
                    "Nextcloud-Update durch fehlende sudo-Berechtigung blockiert."
                    if sudo_problem
                    else "Nextcloud CLI-Updater fehlgeschlagen."
                ),
                "steps": steps,
                "warnings": (
                    [
                        "Der Server-Manager-Benutzer benötigt NOPASSWD-Rechte "
                        "für den Nextcloud-Updater als www-data."
                    ]
                    if sudo_problem
                    else []
                ),
            }

        post_status_r = sh(status_cmd, timeout=60)
        post_status_output = combined_output(post_status_r)
        post_status = parse_occ_status(post_status_output)

        upgrade_cmd = (
            host_literal('nextcloud', "sudo -n -u www-data php {} upgrade 2>&1")
        ).format(occ)

        if post_status.get("needs_db_upgrade"):
            upgrade_r = sh(upgrade_cmd, timeout=1800)
            upgrade_output = combined_output(upgrade_r)
            upgrade_ok = bool(upgrade_r.get("ok"))
            upgrade_changed = True
        else:
            upgrade_r = {
                "ok": True,
                "returncode": 0,
            }
            upgrade_output = post_status_output
            upgrade_ok = bool(
                post_status_r.get("ok")
                and post_status.get("needs_db_upgrade") is False
            )
            upgrade_changed = False

        add_step(
            3,
            "database_upgrade",
            "Datenbank-Upgrade kontrollieren",
            "executed" if upgrade_ok else "failed",
            upgrade_changed,
            (
                "OCC-Datenbank-Upgrade wurde abgeschlossen."
                if upgrade_changed and upgrade_ok
                else (
                    "Kein zusätzliches Datenbank-Upgrade erforderlich."
                    if upgrade_ok
                    else "OCC-Datenbank-Upgrade ist fehlgeschlagen."
                )
            ),
            upgrade_cmd if upgrade_changed else status_cmd,
            upgrade_output,
            upgrade_r.get("returncode"),
        )

        maintenance_cmd = (
            host_literal('nextcloud', "sudo -n -u www-data php {} maintenance:mode --off 2>&1")
        ).format(occ)

        current_status_r = sh(status_cmd, timeout=60)
        current_status_output = combined_output(current_status_r)
        current_status = parse_occ_status(current_status_output)

        if current_status.get("maintenance"):
            maintenance_r = sh(maintenance_cmd, timeout=120)
            maintenance_output = combined_output(maintenance_r)
            maintenance_ok = bool(maintenance_r.get("ok"))
            maintenance_changed = True
        else:
            maintenance_r = {
                "ok": True,
                "returncode": 0,
            }
            maintenance_output = current_status_output
            maintenance_ok = bool(
                current_status_r.get("ok")
                and current_status.get("maintenance") is False
            )
            maintenance_changed = False

        add_step(
            4,
            "maintenance_mode",
            "Wartungsmodus kontrollieren",
            "executed" if maintenance_ok else "failed",
            maintenance_changed,
            (
                "Wartungsmodus wurde deaktiviert."
                if maintenance_changed and maintenance_ok
                else (
                    "Wartungsmodus ist deaktiviert."
                    if maintenance_ok
                    else "Wartungsmodus konnte nicht sicher beendet werden."
                )
            ),
            maintenance_cmd if maintenance_changed else status_cmd,
            maintenance_output,
            maintenance_r.get("returncode"),
        )

        verify = self.update_verify()

        add_step(
            5,
            "occ_verify",
            "Nextcloud nach dem Update verifizieren",
            "executed" if verify.get("ok") else "failed",
            False,
            verify.get("message") or "",
            status_cmd,
            str(verify.get("details") or ""),
            0 if verify.get("ok") else 1,
        )

        all_ok = bool(
            updater_ok
            and upgrade_ok
            and maintenance_ok
            and verify.get("ok")
        )

        return {
            "supported": True,
            "ok": all_ok,
            "mode": "execute",
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "current_version": plan.get("current_version"),
            "latest_version": (
                (verify.get("details") or {}).get("version")
                or plan.get("latest_version")
            ),
            "message": (
                "Nextcloud-Core-Update wurde erfolgreich abgeschlossen."
                if all_ok
                else "Nextcloud-Core-Update benötigt eine Nachprüfung."
            ),
            "steps": steps,
            "verify": verify,
        }


    def update_verify(self):
        """
        Wartet nach einem Nextcloud-Update auf echte
        Betriebsbereitschaft.

        Kurzzeitige HTTP-/PHP-FPM-Anlaufphasen dürfen nicht sofort
        als endgültiger Updatefehler gewertet werden.
        """

        attempts = []
        timeout = 90
        interval = 3
        started = time.monotonic()

        while True:
            health = self.health()

            elapsed = round(
                time.monotonic() - started,
                2,
            )

            attempts.append({
                "attempt": len(attempts) + 1,
                "elapsed_seconds": elapsed,
                "ok": bool(health.get("ok")),
                "service_active": (
                    (health.get("service") or {})
                    .get("active")
                ),
                "http_code": (
                    (health.get("web") or {})
                    .get("http_code")
                ),
                "occ_installed": (
                    (health.get("occ") or {})
                    .get("installed")
                ),
                "maintenance": (
                    (health.get("occ") or {})
                    .get("maintenance")
                ),
                "needs_db_upgrade": (
                    (health.get("occ") or {})
                    .get("needs_db_upgrade")
                ),
            })

            if health.get("ok") is True:
                return {
                    "supported": True,
                    "ok": True,
                    "app_id": self.app_id,
                    "label": self.label,
                    "kind": self.kind,
                    "message": (
                        "Nextcloud ist nach dem Update "
                        "betriebsbereit."
                    ),
                    "details": {
                        "attempts": attempts,
                        "health": health,
                        "elapsed_seconds": elapsed,
                        "timeout_seconds": timeout,
                    },
                }

            if elapsed >= timeout:
                return {
                    "supported": True,
                    "ok": False,
                    "app_id": self.app_id,
                    "label": self.label,
                    "kind": self.kind,
                    "message": (
                        "Nextcloud wurde nach dem Update "
                        "nicht rechtzeitig betriebsbereit."
                    ),
                    "details": {
                        "attempts": attempts,
                        "health": health,
                        "elapsed_seconds": elapsed,
                        "timeout_seconds": timeout,
                    },
                }

            time.sleep(interval)



    def extra_backup(self, workdir):
        from pathlib import Path

        extra = Path(workdir)
        extra.mkdir(parents=True, exist_ok=True)

        files = []

        checks = {
            'occ-status.txt': host_literal('nextcloud', 'sudo -u www-data php /var/www/html/nextcloud/occ status 2>&1 || true'),
            'occ-app-list.txt': host_literal('nextcloud', 'sudo -u www-data php /var/www/html/nextcloud/occ app:list 2>&1 || true'),
            'occ-config-system.txt': host_literal('nextcloud', 'sudo -u www-data php /var/www/html/nextcloud/occ config:system:get trusted_domains 2>&1 || true'),
            'apache-sites.txt': 'apache2ctl -S 2>&1 || true',
            'php-modules.txt': 'php -m 2>&1 || true',
        }

        for name, cmd in checks.items():
            target = extra / name
            r = sh(cmd, timeout=30)
            target.write_text((r.get('stdout') or '') + '\n' + (r.get('stderr') or ''), encoding='utf-8')
            files.append(str(target))

        return {
            "ok": True,
            "message": "Nextcloud Zusatzinformationen gesichert",
            "files": files,
        }
