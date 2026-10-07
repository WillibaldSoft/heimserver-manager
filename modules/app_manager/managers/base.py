# -*- coding: utf-8 -*-
import shlex
from pathlib import Path

from ..runner import sh

class BaseManager:
    app_id = "base"
    label = "Base"
    kind = "generic"
    service = None
    compose_dir = None
    web_url = None

    def installation_status(self):
        """Zentrale Installationsprüfung für App-Manager-Apps."""
        checks = []

        if self.compose_dir:
            exists = sh(f"test -d {self.compose_dir!r}")["ok"]
            checks.append({
                "type": "compose_dir",
                "path": self.compose_dir,
                "ok": bool(exists),
                "reason": "Compose-Verzeichnis vorhanden" if exists else "Compose-Verzeichnis fehlt",
            })

        if self.service:
            exists = sh(f"systemctl cat {self.service} >/dev/null 2>&1", timeout=10)["ok"]
            active = sh(f"systemctl is-active {self.service} 2>/dev/null || true", timeout=10)["stdout"].strip()
            checks.append({
                "type": "systemd",
                "service": self.service,
                "ok": bool(exists),
                "active": active,
                "reason": "systemd-Dienst vorhanden" if exists else "systemd-Dienst fehlt",
            })

        if not checks:
            return {
                "installed": None,
                "state": "unknown",
                "reason": "Keine Installationsmerkmale definiert",
                "checks": [],
            }

        ok_count = sum(1 for c in checks if c.get("ok"))

        if ok_count == len(checks):
            state = "installed"
            installed = True
            reason = "Installiert"
        elif ok_count == 0:
            state = "missing"
            installed = False
            reason = "Nicht installiert"
        else:
            state = "partial"
            installed = False
            reason = "Teilweise installiert"

        return {
            "installed": installed,
            "state": state,
            "reason": reason,
            "checks": checks,
        }

    def _service_status(self):
        if not self.service:
            return {"service": None, "active": "unknown", "enabled": "unknown", "description": ""}
        active = sh(f"systemctl is-active {self.service} 2>/dev/null || true")['stdout'] or 'unknown'
        enabled = sh(f"systemctl is-enabled {self.service} 2>/dev/null || true")['stdout'] or 'unknown'
        desc = sh(f"systemctl show {self.service} -p Description --value 2>/dev/null || true")['stdout']
        return {"service": self.service, "active": active, "enabled": enabled, "description": desc}

    def _web_check(self):
        if not self.web_url:
            return {"configured": False}
        r = sh(
            f"curl -sS -L --max-time 5 -o /dev/null -w '%{{http_code}}' {self.web_url!r} 2>/dev/null || true",
            timeout=8
        )
        code = (r.get("stdout") or "").strip()
        ok = code in ("200", "204", "301", "302", "303")
        return {
            "configured": True,
            "url": self.web_url,
            "http_code": code,
            "ok": ok
        }

    def _compose_status(self):
        if not self.compose_dir:
            return {"configured": False}
        exists = sh(f"test -d {self.compose_dir!r}")['ok']
        ps = sh(f"cd {self.compose_dir!r} 2>/dev/null && docker compose ps --format json 2>/dev/null | head -20", timeout=12)
        return {"configured": True, "path": self.compose_dir, "exists": exists, "ps": ps['stdout'], "error": ps['stderr']}

    def status(self):
        svc = self._service_status()
        web = self._web_check()
        comp = self._compose_status()
        ok = True
        warnings = []
        if svc.get('service') and svc.get('active') not in ('active', 'unknown'):
            ok = False; warnings.append('Dienst nicht aktiv')
        if comp.get('configured') and not comp.get('exists'):
            ok = False; warnings.append('Compose-Verzeichnis fehlt')
        if web.get('configured') and not web.get('ok'):
            warnings.append('Web/API nicht erreichbar')
        installation = self.installation_status()
        if installation.get("state") == "missing":
            ok = False
            warnings.append(installation.get("reason") or "Nicht installiert")
        elif installation.get("state") == "partial":
            warnings.append(installation.get("reason") or "Teilweise installiert")

        return {
            "id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "ok": ok,
            "warnings": warnings,
            "installed": installation.get("installed"),
            "installation": installation,
            "service": svc,
            "web": web,
            "compose": comp,
        }

    def info(self):
        return {"id": self.app_id, "label": self.label, "kind": self.kind}

    def health(self):
        return self.status()


    def update_plan(self):
        return {
            "supported": False,
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "message": "Update-Plan für diese App noch nicht implementiert",
            "steps": [],
        }

    def update_prepare(self):
        return {
            "supported": False,
            "ok": False,
            "app_id": self.app_id,
            "label": self.label,
            "message": "Update-Vorbereitung für diese App noch nicht implementiert",
        }

    def update_execute(self, session=None):
        return {
            "supported": False,
            "ok": False,
            "app_id": self.app_id,
            "label": self.label,
            "message": "Update-Ausführung für diese App noch nicht implementiert",
        }

    def update_verify(self):
        return {
            "supported": False,
            "ok": False,
            "app_id": self.app_id,
            "label": self.label,
            "message": "Update-Verifikation für diese App noch nicht implementiert",
        }

    def native_update_result(
        self,
        *,
        supported=True,
        ok=True,
        state="unknown",
        label="Unbekannt",
        message="",
        current_version=None,
        latest_version=None,
        update_available=None,
        method="native",
        details=None,
        warnings=None,
        safe_to_update=False,
        requires_backup=True,
    ):
        """Einheitliches Ergebnisformat für native Update-Prüfungen."""
        return {
            "supported": bool(supported),
            "ok": bool(ok),
            "state": state,
            "label": label,
            "message": message,
            "app_id": self.app_id,
            "app_label": self.label,
            "kind": self.kind,
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
            "method": method,
            "details": details or {},
            "warnings": warnings or [],
            "safe_to_update": bool(safe_to_update),
            "requires_backup": bool(requires_backup),
        }


    def native_git_update_check(
        self,
        repo_candidates,
        *,
        method="native-git",
        missing_message="Kein Git-Repository erkannt",
        run_as_user=None,
    ):
        """Einheitliche Git-basierte Update-Prüfung für native Apps."""

        repo = None

        for candidate in repo_candidates or []:
            candidate_path = Path(candidate)

            if (candidate_path / ".git").is_dir():
                repo = candidate_path
                break

        if repo is None:
            return self.native_update_result(
                supported=False,
                ok=True,
                state="missing",
                label="Kein Repository",
                message=missing_message,
                current_version=None,
                latest_version=None,
                update_available=None,
                method=method,
                details={
                    "repo_candidates": list(repo_candidates or []),
                },
                safe_to_update=False,
                requires_backup=True,
            )

        repo_q = shlex.quote(str(repo))

        git_prefix = "git"

        if run_as_user:
            git_prefix = "sudo -n -u {} git".format(
                shlex.quote(str(run_as_user))
            )

        local_r = sh(
            "{} -C {} rev-parse HEAD 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=15,
        )
        local_revision = (local_r.get("stdout") or "").strip()

        local_short_r = sh(
            "{} -C {} rev-parse --short HEAD 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=15,
        )
        local_short = (local_short_r.get("stdout") or "").strip()

        branch_r = sh(
            "{} -C {} rev-parse --abbrev-ref HEAD 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=15,
        )
        branch = (branch_r.get("stdout") or "").strip()

        dirty_r = sh(
            "{} -C {} status --porcelain 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=15,
        )
        dirty_text = (dirty_r.get("stdout") or "").strip()
        dirty = bool(dirty_text)

        fetch_r = sh(
            "{} -C {} fetch --prune 2>&1".format(
                git_prefix,
                repo_q,
            ),
            timeout=120,
        )
        fetch_output = (
            (fetch_r.get("stdout") or "")
            + "\n"
            + (fetch_r.get("stderr") or "")
        ).strip()

        if not fetch_r.get("ok"):
            return self.native_update_result(
                supported=True,
                ok=False,
                state="error",
                label="Prüfung fehlgeschlagen",
                message="Git-Remote konnte nicht aktualisiert werden.",
                current_version=local_short or local_revision or None,
                latest_version=None,
                update_available=None,
                method=method,
                details={
                    "repo": str(repo),
                    "branch": branch,
                    "local_revision": local_revision,
                    "dirty": dirty,
                    "dirty_files": dirty_text,
                    "fetch_output": fetch_output,
                },
                warnings=[
                    "Lokale Änderungen vorhanden."
                ] if dirty else [],
                safe_to_update=False,
                requires_backup=True,
            )

        upstream_r = sh(
            "{} -C {} rev-parse '@{{u}}' 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=15,
        )
        upstream_revision = (upstream_r.get("stdout") or "").strip()

        upstream_short_r = sh(
            "{} -C {} rev-parse --short '@{{u}}' 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=15,
        )
        upstream_short = (upstream_short_r.get("stdout") or "").strip()

        if not upstream_revision:
            return self.native_update_result(
                supported=True,
                ok=True,
                state="unknown",
                label="Kein Upstream",
                message="Für den aktuellen Git-Branch ist kein Upstream konfiguriert.",
                current_version=local_short or local_revision or None,
                latest_version=None,
                update_available=None,
                method=method,
                details={
                    "repo": str(repo),
                    "branch": branch,
                    "local_revision": local_revision,
                    "dirty": dirty,
                    "dirty_files": dirty_text,
                },
                warnings=[
                    "Lokale Änderungen vorhanden."
                ] if dirty else [],
                safe_to_update=False,
                requires_backup=True,
            )

        counts_r = sh(
            "{} -C {} rev-list --left-right --count "
            "HEAD...'@{{u}}' 2>/dev/null || true".format(
                git_prefix,
                repo_q,
            ),
            timeout=20,
        )
        counts_text = (counts_r.get("stdout") or "").strip()

        ahead = 0
        behind = 0

        try:
            parts = counts_text.replace("\t", " ").split()

            if len(parts) >= 2:
                ahead = int(parts[0])
                behind = int(parts[1])
        except Exception:
            ahead = 0
            behind = 0

        update_available = behind > 0

        if update_available:
            state = "available"
            label = "Update verfügbar"
            message = "{} Remote-Commit(s) verfügbar.".format(behind)
        else:
            state = "current"
            label = "Aktuell"
            message = "Lokales Repository entspricht dem Upstream."

        warnings = []

        if dirty:
            warnings.append(
                "Lokale Änderungen vorhanden. Update kann Konflikte verursachen."
            )

        if ahead > 0:
            warnings.append(
                "{} lokaler Commit(s) noch nicht im Upstream.".format(ahead)
            )

        return self.native_update_result(
            supported=True,
            ok=True,
            state=state,
            label=label,
            message=message,
            current_version=local_short or local_revision or None,
            latest_version=upstream_short or upstream_revision or None,
            update_available=update_available,
            method=method,
            details={
                "repo": str(repo),
                "branch": branch,
                "local_revision": local_revision,
                "upstream_revision": upstream_revision,
                "ahead": ahead,
                "behind": behind,
                "dirty": dirty,
                "dirty_files": dirty_text,
                "fetch_output": fetch_output,
            },
            warnings=warnings,
            safe_to_update=not dirty and ahead == 0,
            requires_backup=True,
        )


    def native_apt_update_check(
        self,
        package,
        *,
        method="native-apt",
        requires_backup=True,
    ):
        """
        Einheitliche APT-basierte Update-Prüfung.

        Verwendet nur den vorhandenen lokalen APT-Paketindex.
        Führt ausdrücklich kein apt update und keine Installation aus.
        """

        package = str(package or "").strip()

        if not package:
            return self.native_update_result(
                supported=False,
                ok=False,
                state="error",
                label="Ungültiges Paket",
                message="Kein APT-Paketname angegeben.",
                update_available=None,
                method=method,
                safe_to_update=False,
                requires_backup=requires_backup,
            )

        package_q = shlex.quote(package)

        installed_r = sh(
            "LC_ALL=C dpkg-query -W "
            "-f='${{Status}}\\t${{Version}}\\n' "
            "{} 2>/dev/null || true".format(package_q),
            timeout=20,
        )

        installed_text = (installed_r.get("stdout") or "").strip()

        installed = False
        current_version = None

        if installed_text:
            parts = installed_text.split("\t", 1)

            if len(parts) == 2:
                status_text, current_version = parts
                installed = status_text.strip() == "install ok installed"

        if not installed:
            return self.native_update_result(
                supported=True,
                ok=True,
                state="missing",
                label="Nicht installiert",
                message="APT-Paket {} ist nicht installiert.".format(package),
                current_version=current_version,
                latest_version=None,
                update_available=None,
                method=method,
                details={
                    "package": package,
                    "dpkg_query": installed_text,
                },
                safe_to_update=False,
                requires_backup=requires_backup,
            )

        policy_r = sh(
            "LC_ALL=C apt-cache policy {} 2>&1".format(package_q),
            timeout=30,
        )

        policy_text = (
            (policy_r.get("stdout") or "")
            + "\n"
            + (policy_r.get("stderr") or "")
        ).strip()

        candidate_version = None

        for line in policy_text.splitlines():
            raw = line.strip()

            if raw.startswith("Candidate:"):
                candidate_version = raw.split(":", 1)[1].strip()
                break

        if not candidate_version or candidate_version == "(none)":
            return self.native_update_result(
                supported=True,
                ok=False,
                state="unknown",
                label="Kein Kandidat",
                message="APT liefert keine installierbare Kandidatenversion.",
                current_version=current_version,
                latest_version=None,
                update_available=None,
                method=method,
                details={
                    "package": package,
                    "apt_policy": policy_text,
                },
                safe_to_update=False,
                requires_backup=requires_backup,
            )

        older_r = sh(
            "dpkg --compare-versions {} lt {}".format(
                shlex.quote(current_version),
                shlex.quote(candidate_version),
            ),
            timeout=10,
        )

        equal_r = sh(
            "dpkg --compare-versions {} eq {}".format(
                shlex.quote(current_version),
                shlex.quote(candidate_version),
            ),
            timeout=10,
        )

        if older_r.get("ok"):
            state = "available"
            label = "Update verfügbar"
            update_available = True
            message = "{} kann von {} auf {} aktualisiert werden.".format(
                package,
                current_version,
                candidate_version,
            )

        elif equal_r.get("ok"):
            state = "current"
            label = "Aktuell"
            update_available = False
            message = "{} ist aktuell.".format(package)

        else:
            state = "newer"
            label = "Lokale Version neuer"
            update_available = False
            message = (
                "Die installierte Version ist neuer als der APT-Kandidat."
            )

        return self.native_update_result(
            supported=True,
            ok=True,
            state=state,
            label=label,
            message=message,
            current_version=current_version,
            latest_version=candidate_version,
            update_available=update_available,
            method=method,
            details={
                "package": package,
                "installed_version": current_version,
                "candidate_version": candidate_version,
                "apt_policy": policy_text,
                "package_index_refreshed": False,
            },
            warnings=[
                "Der vorhandene APT-Paketindex wurde verwendet; apt update wurde nicht ausgeführt."
            ],
            safe_to_update=False,
            requires_backup=requires_backup,
        )


    def update_check(self):
        from ..catalog_updates import fallback
        return fallback(self)

    def backup_check(self):
        from ..backup import backup_check
        return backup_check(self)

    def backup(self, profile="system"):
        from ..backup_engine import run_backup
        return run_backup(self, profile=profile)


    def extra_backup(self, workdir):
        return {
            "ok": True,
            "message": "Keine app-spezifischen Backup-Schritte definiert",
            "workdir": workdir,
        }

    def logs(self, lines=80):
        if self.service:
            r = sh(f"journalctl -u {self.service} -n {int(lines)} --no-pager 2>/dev/null || true", timeout=10)
            return {"ok": True, "text": r['stdout'] or r['stderr']}
        return {"ok": False, "text": "Kein systemd-Dienst definiert."}
    def stop_for_restore(self):
        return {
            "ok": True,
            "changed": False,
            "method": "noop",
            "message": "Für diese App ist kein Stop-Vorgang definiert.",
        }

    def start_after_restore(self):
        return {
            "ok": True,
            "changed": False,
            "method": "noop",
            "message": "Für diese App ist kein Start-Vorgang definiert.",
        }

    def restore_healthcheck(self):
        try:
            return self.health()
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
            }


