from server_settings import app_literal as host_literal
# -*- coding: utf-8 -*-
from .base import BaseManager
from ..runner import sh

class Manager(BaseManager):
    app_id = 'oscam'
    label = 'OSCam'
    kind = 'native'
    service = 'oscam.service'
    web_url = 'http://127.0.0.1:8888'

    config_files = {
        "oscam.conf": host_literal('oscam', "/var/lib/oscam/config/oscam.conf"),
        "oscam.server": host_literal('oscam', "/var/lib/oscam/config/oscam.server"),
        "oscam.user": host_literal('oscam', "/var/lib/oscam/config/oscam.user"),
        "oscam.dvbapi": host_literal('oscam', "/var/lib/oscam/config/oscam.dvbapi"),
    }

    paths = {
        "config": host_literal('oscam', "/var/lib/oscam/config"),
        "logs": host_literal('oscam', "/var/log/oscam"),
    }

    def info(self):
        version = sh('command -v oscam >/dev/null 2>&1 && oscam -V 2>&1 | head -120 || true', timeout=8)['stdout']
        git = sh('for d in /opt/oscam /usr/local/src/oscam /opt/oscam/oscam-svn; do test -d "$d/.git" && cd "$d" && echo "$d" && git rev-parse --short HEAD && git status --short && break; done', timeout=8)['stdout']
        readers = sh("ls -l /dev/serial/by-id 2>/dev/null | grep -Ei 'smart|reader|ftdi|usb' || true", timeout=5)['stdout']
        return {"version": version, "git": git, "usb_readers": readers}

    def health(self):
        d = self.status()
        log = sh("journalctl -u oscam -n 300 --no-pager 2>/dev/null | grep -Ei 'error|failed|timeout|resync|ifsd|atr|reader|card' | tail -40 || true", timeout=8)['stdout']
        d['diagnostics'] = log
        return d



    def extra_backup(self, workdir):
        """
        Sichert den vollständigen produktiven OSCam-Zustand zusätzlich
        zum generischen App-Manager-Backup.

        Enthalten sind insbesondere die installierte Binary, der
        systemd-Service, die tatsächlich verwendete Konfiguration und
        die lokale Build-Konfiguration.
        """

        from pathlib import Path
        import hashlib
        import json
        import shutil
        import stat

        root = Path(workdir) / "oscam"
        root.mkdir(parents=True, exist_ok=True)

        files_dir = root / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        binary = Path("/usr/local/bin/oscam")
        service_file = Path("/etc/systemd/system/oscam.service")
        config_dir = Path(host_literal('oscam', "/var/lib/oscam/config"))
        build_config = Path(host_literal('oscam', "/opt/oscam/config.h"))
        repo = host_literal('oscam', "/opt/oscam")

        manifest = {
            "app_id": self.app_id,
            "label": self.label,
            "binary": None,
            "service": None,
            "config": None,
            "build_config": None,
            "version": None,
            "git": {},
        }

        def file_info(source, target):
            st = source.stat()

            h = hashlib.sha256()

            with source.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)

            return {
                "source": str(source),
                "backup": str(target.relative_to(root)),
                "size": st.st_size,
                "mode": stat.S_IMODE(st.st_mode),
                "uid": st.st_uid,
                "gid": st.st_gid,
                "sha256": h.hexdigest(),
            }

        # Produktive Binary
        if binary.is_file():
            target = files_dir / "oscam.binary"
            shutil.copy2(binary, target)
            manifest["binary"] = file_info(binary, target)

        # systemd Unit
        if service_file.is_file():
            target = files_dir / "oscam.service"
            shutil.copy2(service_file, target)
            manifest["service"] = file_info(service_file, target)

        # Tatsächlich vom Dienst verwendete Konfiguration.
        #
        # Der kopierte Verzeichnisbaum dient der einfachen Einsicht.
        # Für eine exakte Wiederherstellung wird zusätzlich ein
        # TAR-Archiv mit numerischen UID/GID, ACLs und xattrs erzeugt.
        if config_dir.is_dir():
            target = files_dir / "config"

            if target.exists():
                shutil.rmtree(target)

            shutil.copytree(
                config_dir,
                target,
                symlinks=True,
            )

            config_archive = root / "config.tar"

            config_tar_r = sh(
                "tar --acls --xattrs --numeric-owner "
                "-cpf {} "
                "-C /var/lib/oscam config".format(
                    config_archive
                ),
                timeout=60,
            )

            config_tar_ok = bool(
                config_tar_r.get("ok")
                and config_archive.is_file()
            )

            manifest["config"] = {
                "source": str(config_dir),
                "backup": str(target.relative_to(root)),
                "archive": str(
                    config_archive.relative_to(root)
                ),
                "archive_ok": config_tar_ok,
                "archive_size": (
                    config_archive.stat().st_size
                    if config_archive.is_file()
                    else 0
                ),
                "restore": (
                    "tar --acls --xattrs --numeric-owner "
                    "-xpf config.tar -C /var/lib/oscam"
                ),
            }

            if not config_tar_ok:
                manifest["config"]["archive_error"] = (
                    (config_tar_r.get("stdout") or "")
                    + "\n"
                    + (config_tar_r.get("stderr") or "")
                ).strip()

        # Lokale Build-Konfiguration, insbesondere SMARGO
        if build_config.is_file():
            target = files_dir / "config.h"
            shutil.copy2(build_config, target)
            manifest["build_config"] = file_info(
                build_config,
                target,
            )

        # Installierte Versionsinformationen
        version_r = sh(
            "/usr/local/bin/oscam -V 2>&1",
            timeout=15,
        )

        version_text = (
            (version_r.get("stdout") or "")
            + "\n"
            + (version_r.get("stderr") or "")
        ).strip()

        (root / "oscam-version.txt").write_text(
            version_text + "\n",
            encoding="utf-8",
        )

        manifest["version"] = version_text

        # Git-Zustand dokumentieren.
        git_commands = {
            "head": (
                host_literal('oscam', "sudo -n -u oscam "
                "git -C {} rev-parse HEAD 2>/dev/null || true")
            ).format(repo),
            "status": (
                host_literal('oscam', "sudo -n -u oscam "
                "git -C {} status --short 2>/dev/null || true")
            ).format(repo),
            "origin_master": (
                host_literal('oscam', "sudo -n -u oscam "
                "git -C {} rev-parse origin/master "
                "2>/dev/null || true")
            ).format(repo),
            "origin_oscam_gitlab": (
                host_literal('oscam', "sudo -n -u oscam "
                "git -C {} rev-parse origin/oscam-gitlab "
                "2>/dev/null || true")
            ).format(repo),
        }

        for name, command in git_commands.items():
            r = sh(command, timeout=15)
            manifest["git"][name] = (
                r.get("stdout") or ""
            ).strip()

        # Zusätzliche Diagnoseinformationen.
        service_r = sh(
            "systemctl status oscam.service "
            "--no-pager 2>&1 || true",
            timeout=15,
        )

        (root / "service-status.txt").write_text(
            (service_r.get("stdout") or "")
            + (service_r.get("stderr") or ""),
            encoding="utf-8",
        )

        manifest_path = root / "manifest.json"

        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        if manifest["binary"] is None:
            return {
                "ok": False,
                "message": (
                    "OSCam-Binary konnte nicht gesichert werden."
                ),
                "path": str(root),
                "manifest": str(manifest_path),
            }

        if (
            manifest["config"] is None
            or not manifest["config"].get("archive_ok")
        ):
            return {
                "ok": False,
                "message": (
                    "OSCam-Konfiguration konnte nicht vollständig "
                    "mit Metadaten gesichert werden."
                ),
                "path": str(root),
                "manifest": str(manifest_path),
            }

        return {
            "ok": True,
            "message": (
                "OSCam-Binary, Konfiguration, systemd-Service und "
                "Build-Konfiguration wurden gesichert."
            ),
            "path": str(root),
            "manifest": str(manifest_path),
        }

    def update_plan(self):
        """
        Liefert den sicheren OSCam-EMU-Updateplan.

        Produktiver Zielzweig ist origin/master des oscam-emu-Repositories.
        Gebaut wird grundsätzlich in einem separaten Worktree.
        """

        check = self.update_check()

        details = check.get("details") or {}

        return {
            "supported": True,
            "ok": bool(check.get("ok")),
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "method": "oscam-emu-build",
            "state": check.get("state"),
            "update_available": check.get("update_available"),
            "current_version": check.get("current_version"),
            "latest_version": check.get("latest_version"),
            "requires_backup": True,
            "safe_to_update": bool(
                check.get("ok")
                and check.get("update_available") is True
            ),
            "warnings": list(check.get("warnings") or []),
            "details": {
                "repo": details.get("repo"),
                "upstream": details.get("upstream"),
                "base_upstream": details.get("base_upstream"),
                "latest_commit": details.get("latest_commit"),
                "base_commit": details.get("base_commit"),
                "behind": details.get("behind"),
                "build_target": "libusb",
                "smargo_required": True,
            },
            "steps": [
                {
                    "id": "source_precheck",
                    "label": "OSCam-Quellstand und Zielrevision prüfen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "worktree_prepare",
                    "label": "Separaten OSCam-EMU-Worktree vorbereiten",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "build_config",
                    "label": "SMARGO-Buildkonfiguration aktivieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "build",
                    "label": "OSCam-EMU mit libusb kompilieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "binary_sanity",
                    "label": "Neue OSCam-Binary und Features prüfen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "binary_backup",
                    "label": "Installierte OSCam-Binary sichern",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "binary_install",
                    "label": "Neue OSCam-Binary installieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "service_restart",
                    "label": "OSCam-Dienst neu starten",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "service_verify",
                    "label": "OSCam-Version und Dienst prüfen",
                    "required": True,
                    "automatic": True,
                },
            ],
        }


    def update_execute(self, session=None):
        """
        Führt das OSCam-EMU-Update aus.

        Simulation und Echtlauf verwenden denselben Updateplan.
        Im Echtlauf ist ein zuvor validiertes Pre-Update-Backup
        zwingend erforderlich.

        Bei einem Fehler nach produktiver Änderung wird automatisch
        auf genau dieses validierte Backup zurückgerollt.
        """

        from pathlib import Path
        import hashlib
        import os
        import shutil
        import time

        session = session if isinstance(session, dict) else {}
        simulate = bool(session.get("simulate", True))

        plan = self.update_plan()

        result = {
            "supported": True,
            "ok": False,
            "simulate": simulate,
            "mode": "simulation" if simulate else "execute",
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "current_version": plan.get("current_version"),
            "latest_version": plan.get("latest_version"),
            "message": "",
            "steps": [],
            "rollback": None,
        }

        if not plan.get("ok"):
            result["message"] = (
                "OSCam-Updateprüfung ist fehlgeschlagen."
            )
            return result

        if not plan.get("update_available"):
            result["ok"] = True
            result["message"] = (
                "Kein OSCam-Update erforderlich."
            )
            return result

        details = plan.get("details") or {}

        repo = (
            details.get("repo")
            or host_literal('oscam', "/opt/oscam")
        )

        upstream = (
            details.get("upstream")
            or "origin/master"
        )

        target_commit = str(
            details.get("latest_commit") or ""
        ).strip()

        worktree = Path(
            host_literal('oscam', "/opt/oscam-build")
        )

        installed_binary = Path(
            "/usr/local/bin/oscam"
        )

        # ------------------------------------------------------------
        # Gemeinsame Schritt-Hilfe
        # ------------------------------------------------------------

        def add_step(
            order,
            step_id,
            label,
            status,
            *,
            changed=False,
            message="",
            command="",
            output="",
            returncode=None,
            **extra
        ):
            step = {
                "order": order,
                "id": step_id,
                "label": label,
                "status": status,
                "changed": bool(changed),
                "message": message,
                "command": command,
                "output": output,
                "returncode": returncode,
            }

            if extra:
                step.update(extra)

            result["steps"].append(step)
            return step

        labels = {
            x.get("id"): x.get("label")
            for x in (plan.get("steps") or [])
        }

        # ------------------------------------------------------------
        # Simulation unverändert
        # ------------------------------------------------------------

        if simulate:
            commands = {
                "source_precheck": (
                    host_literal('oscam', "sudo -n -u oscam git -C {} fetch --prune")
                ).format(repo),

                "worktree_prepare": (
                    host_literal('oscam', "sudo -n -u oscam git -C {} worktree add "
                    "{} {}")
                ).format(
                    repo,
                    worktree,
                    upstream,
                ),

                "build_config": (
                    host_literal('oscam', "sudo -n -u oscam {0}/config.sh "
                    "--enable CARDREADER_SMARGO && "
                    "sudo -n -u oscam {0}/config.sh "
                    "--show-enabled card_readers")
                ).format(worktree),

                "build": (
                    host_literal('oscam', "sudo -n -u oscam make -C {} clean && "
                    "sudo -n -u oscam make -C {} libusb")
                ).format(
                    worktree,
                    worktree,
                ),

                "binary_sanity": (
                    "Neue Distribution/oscam-* Binary auswählen und "
                    "Version, libusb, WEBIF, DVBAPI, EMU, SoftCam.Key, "
                    "SMARGO und Smartreader prüfen."
                ),

                "binary_backup": (
                    "Validiertes Pre-Update-Backup verwenden."
                ),

                "binary_install": (
                    "Geprüfte OSCam-Binary atomar nach "
                    "/usr/local/bin/oscam installieren."
                ),

                "service_restart": (
                    "systemctl restart oscam.service"
                ),

                "service_verify": (
                    "Installierte Version, oscam.service und WebIF prüfen."
                ),
            }

            for order, definition in enumerate(
                plan.get("steps") or [],
                start=1,
            ):
                step_id = definition.get("id")

                add_step(
                    order,
                    step_id,
                    definition.get("label"),
                    "simulated",
                    changed=False,
                    message=(
                        "Simulation: {}"
                    ).format(
                        definition.get("label") or step_id
                    ),
                    command=commands.get(step_id, ""),
                    output="",
                    returncode=0,
                )

            result["ok"] = True
            result["message"] = (
                "OSCam-EMU-Update erfolgreich simuliert."
            )
            return result

        # ------------------------------------------------------------
        # Ab hier Echtlauf
        # ------------------------------------------------------------

        changed_productive = False

        def fail(
            message,
            *,
            rollback=False,
        ):
            result["ok"] = False
            result["message"] = message

            if rollback and changed_productive:
                try:
                    rb = self.update_rollback(
                        session=session,
                        restore_config=True,
                        simulate=False,
                    )
                except Exception as e:
                    rb = {
                        "ok": False,
                        "message": (
                            "OSCam-Rollback löste eine Ausnahme aus."
                        ),
                        "error": str(e),
                    }

                result["rollback"] = rb

                if rb.get("ok"):
                    result["message"] += (
                        " Automatischer Rollback war erfolgreich."
                    )
                else:
                    result["message"] += (
                        " Automatischer Rollback ist fehlgeschlagen."
                    )

            return result

        # ------------------------------------------------------------
        # Zwingendes validiertes Pre-Update-Backup
        # ------------------------------------------------------------

        backup_check = session.get("backup_check") or {}

        if backup_check.get("ok") is not True:
            return fail(
                "OSCam-Echtupdate abgebrochen: "
                "kein validiertes Pre-Update-Backup."
            )

        validated = backup_check.get("backup") or {}
        backup = validated.get("backup") or {}

        backup_dir_raw = str(
            backup.get("work_dir") or ""
        ).strip()

        if (
            backup.get("app_id") != self.app_id
            or not backup_dir_raw
            or not Path(backup_dir_raw).is_dir()
        ):
            return fail(
                "OSCam-Echtupdate abgebrochen: "
                "validiertes Backup ist ungültig."
            )

        # ------------------------------------------------------------
        # 1. Source Precheck
        # ------------------------------------------------------------

        fetch_cmd = (
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} fetch --prune")
        ).format(repo)

        fetch_r = sh(
            fetch_cmd,
            timeout=180,
        )

        fetch_output = (
            (fetch_r.get("stdout") or "")
            + "\n"
            + (fetch_r.get("stderr") or "")
        ).strip()

        add_step(
            1,
            "source_precheck",
            labels.get("source_precheck"),
            "executed" if fetch_r.get("ok") else "failed",
            changed=False,
            message=(
                "OSCam-Upstream aktualisiert."
                if fetch_r.get("ok")
                else "OSCam-Upstream konnte nicht aktualisiert werden."
            ),
            command=fetch_cmd,
            output=fetch_output,
            returncode=fetch_r.get("returncode"),
        )

        if not fetch_r.get("ok"):
            return fail(
                "OSCam-Update beim Source-Precheck fehlgeschlagen."
            )

        actual_target_r = sh(
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} rev-parse '{}^{{}}'").format(
                repo,
                upstream,
            ),
            timeout=30,
        )

        actual_target = (
            actual_target_r.get("stdout") or ""
        ).strip()

        if not actual_target:
            return fail(
                "OSCam-Zielrevision konnte nicht bestimmt werden."
            )

        # Nach dem Prepare darf sich der Remote-Zielstand nicht
        # unbemerkt ändern.
        if (
            target_commit
            and actual_target != target_commit
        ):
            return fail(
                "OSCam-Upstream hat sich seit dem Update-Plan geändert. "
                "Bitte Update erneut vorbereiten."
            )

        target_commit = actual_target

        # ------------------------------------------------------------
        # 2. Worktree frisch erzeugen
        # ------------------------------------------------------------

        # Alten Server-Manager-Testworktree kontrolliert entfernen.
        sh(
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} worktree remove --force {} "
            "2>/dev/null || true").format(
                repo,
                worktree,
            ),
            timeout=60,
        )

        if worktree.exists():
            try:
                shutil.rmtree(worktree)
            except Exception as e:
                return fail(
                    "Alter OSCam-Update-Worktree konnte "
                    "nicht entfernt werden: {}".format(e)
                )

        sh(
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} worktree prune").format(repo),
            timeout=30,
        )

        worktree_cmd = (
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} worktree add --detach {} {}")
        ).format(
            repo,
            worktree,
            target_commit,
        )

        worktree_r = sh(
            worktree_cmd,
            timeout=120,
        )

        worktree_output = (
            (worktree_r.get("stdout") or "")
            + "\n"
            + (worktree_r.get("stderr") or "")
        ).strip()

        worktree_ok = bool(
            worktree_r.get("ok")
            and worktree.is_dir()
        )

        add_step(
            2,
            "worktree_prepare",
            labels.get("worktree_prepare"),
            "executed" if worktree_ok else "failed",
            changed=False,
            message=(
                "Separater OSCam-EMU-Worktree vorbereitet."
                if worktree_ok
                else "OSCam-Update-Worktree konnte nicht "
                     "vorbereitet werden."
            ),
            command=worktree_cmd,
            output=worktree_output,
            returncode=worktree_r.get("returncode"),
            target_commit=target_commit,
        )

        if not worktree_ok:
            return fail(
                "OSCam-Update beim Worktree-Setup fehlgeschlagen."
            )

        # ------------------------------------------------------------
        # 3. SMARGO aktivieren
        # ------------------------------------------------------------

        config_h = worktree / "config.h"
        config_sh = worktree / "config.sh"

        if not config_h.is_file():
            return fail(
                "OSCam config.h fehlt im Update-Worktree."
            )

        if not config_sh.is_file():
            return fail(
                "OSCam config.sh fehlt im Update-Worktree."
            )

        # OSCam verwaltet seine effektive Build-Konfiguration über
        # config.sh. Eine direkte Änderung von config.h reicht nicht,
        # weil make vor dem Build config.mak über config.sh erzeugt.
        enable_cmd = (
            host_literal('oscam', "sudo -n -u oscam {} "
            "--enable CARDREADER_SMARGO")
        ).format(config_sh)

        enable_r = sh(
            enable_cmd,
            timeout=30,
        )

        verify_cmd = (
            host_literal('oscam', "sudo -n -u oscam {} "
            "--show-enabled card_readers")
        ).format(config_sh)

        verify_r = sh(
            verify_cmd,
            timeout=30,
        )

        enabled_output = (
            (verify_r.get("stdout") or "")
            + "\n"
            + (verify_r.get("stderr") or "")
        ).strip()

        enabled_readers = [
            line.strip()
            for line in enabled_output.splitlines()
            if line.strip()
        ]

        config_text = config_h.read_text(
            encoding="utf-8"
        )

        config_h_smargo = (
            "#define CARDREADER_SMARGO 1"
            in [
                line.strip()
                for line in config_text.splitlines()
            ]
        )

        config_ok = bool(
            enable_r.get("ok")
            and verify_r.get("ok")
            and "CARDREADER_SMARGO" in enabled_readers
            and config_h_smargo
        )

        command_output = (
            ((enable_r.get("stdout") or "")
             + "\n"
             + (enable_r.get("stderr") or "")
             + "\n"
             + enabled_output)
        ).strip()

        add_step(
            3,
            "build_config",
            labels.get("build_config"),
            "executed" if config_ok else "failed",
            changed=False,
            message=(
                "SMARGO wurde über OSCam config.sh aktiviert "
                "und verifiziert."
                if config_ok
                else "SMARGO konnte über OSCam config.sh "
                     "nicht sicher aktiviert werden."
            ),
            command=(
                "{} && {}"
            ).format(
                enable_cmd,
                verify_cmd,
            ),
            output=command_output,
            returncode=0 if config_ok else 1,
            enabled_readers=enabled_readers,
            config_h_smargo=config_h_smargo,
        )

        if not config_ok:
            return fail(
                "OSCam-SMARGO-Buildkonfiguration fehlgeschlagen."
            )

        # ------------------------------------------------------------
        # 4. Build
        # ------------------------------------------------------------

        build_cmd = (
            host_literal('oscam', "sudo -n -u oscam make -C {} clean && "
            "sudo -n -u oscam make -C {} libusb")
        ).format(
            worktree,
            worktree,
        )

        build_r = sh(
            build_cmd,
            timeout=1800,
        )

        build_output = (
            (build_r.get("stdout") or "")
            + "\n"
            + (build_r.get("stderr") or "")
        ).strip()

        add_step(
            4,
            "build",
            labels.get("build"),
            "executed" if build_r.get("ok") else "failed",
            changed=False,
            message=(
                "OSCam-EMU erfolgreich kompiliert."
                if build_r.get("ok")
                else "OSCam-EMU-Build fehlgeschlagen."
            ),
            command=build_cmd,
            output=build_output,
            returncode=build_r.get("returncode"),
        )

        if not build_r.get("ok"):
            return fail(
                "OSCam-Update beim Kompilieren fehlgeschlagen."
            )

        # ------------------------------------------------------------
        # 5. Binary exakt auswählen + Feature-Sanity
        # ------------------------------------------------------------

        distribution = worktree / "Distribution"

        candidates = sorted(
            [
                p
                for p in distribution.glob("oscam-*")
                if (
                    p.is_file()
                    and os.access(p, os.X_OK)
                    and not p.name.endswith(".debug")
                    and not p.name.startswith("list_smargo")
                )
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not candidates:
            return fail(
                "OSCam-Build erzeugte keine geeignete "
                "Distribution/oscam-* Binary."
            )

        new_binary = candidates[0]

        sanity_r = sh(
            "{} -V 2>&1".format(new_binary),
            timeout=30,
        )

        sanity_text = (
            (sanity_r.get("stdout") or "")
            + "\n"
            + (sanity_r.get("stderr") or "")
        ).strip()

        required_features = [
            (
                "Compiler",
                "Compiler:",
                "libusb",
            ),
            (
                "WEBIF",
                "Web interface support:",
                "yes",
            ),
            (
                "DVBAPI",
                "DVB API support:",
                "yes",
            ),
            (
                "EMU",
                "Emulator support:",
                "yes",
            ),
            (
                "SoftCam",
                "Built-in SoftCam.Key:",
                "yes",
            ),
            (
                "SMARGO",
                "cardreader_smargo:",
                "yes",
            ),
            (
                "SMARTREADER",
                "cardreader_smartreader:",
                "yes",
            ),
        ]

        feature_results = {}

        lines = sanity_text.splitlines()

        for name, prefix, expected in required_features:
            matched = None

            for line in lines:
                if line.strip().startswith(prefix):
                    matched = line.strip()
                    break

            feature_results[name] = {
                "ok": bool(
                    matched
                    and expected.lower()
                    in matched.lower()
                ),
                "line": matched,
            }

        sanity_ok = bool(
            sanity_r.get("ok")
            and all(
                x.get("ok")
                for x in feature_results.values()
            )
        )

        new_version = None

        for line in lines:
            raw = line.strip()

            if raw.startswith("Version:"):
                new_version = (
                    raw.split(":", 1)[1].strip()
                )
                break

        if not new_version:
            sanity_ok = False

        add_step(
            5,
            "binary_sanity",
            labels.get("binary_sanity"),
            "executed" if sanity_ok else "failed",
            changed=False,
            message=(
                "Neue OSCam-Binary und erforderliche Features "
                "wurden erfolgreich geprüft."
                if sanity_ok
                else "Neue OSCam-Binary erfüllt nicht alle "
                     "erforderlichen Feature-Prüfungen."
            ),
            command="{} -V".format(new_binary),
            output=sanity_text,
            returncode=sanity_r.get("returncode"),
            binary=str(new_binary),
            version=new_version,
            features=feature_results,
        )

        if not sanity_ok:
            return fail(
                "OSCam-Binary-Sanity-Check fehlgeschlagen."
            )

        # ------------------------------------------------------------
        # 6. Backup bereits vom Execution Gate bestätigt
        # ------------------------------------------------------------

        add_step(
            6,
            "binary_backup",
            labels.get("binary_backup"),
            "executed",
            changed=False,
            message=(
                "Validiertes Pre-Update-Backup vorhanden."
            ),
            backup_run_id=validated.get("run_id"),
            backup_dir=backup_dir_raw,
            returncode=0,
        )

        # ------------------------------------------------------------
        # 7. Dienst stoppen + Binary atomar installieren
        # ------------------------------------------------------------

        stop_r = sh(
            "systemctl stop oscam.service",
            timeout=60,
        )

        if not stop_r.get("ok"):
            add_step(
                7,
                "binary_install",
                labels.get("binary_install"),
                "failed",
                changed=False,
                message=(
                    "OSCam-Dienst konnte vor Binary-Austausch "
                    "nicht gestoppt werden."
                ),
                output=(
                    (stop_r.get("stdout") or "")
                    + (stop_r.get("stderr") or "")
                ),
                returncode=stop_r.get("returncode"),
            )

            return fail(
                "OSCam-Update vor Binary-Installation abgebrochen."
            )

        temp_binary = installed_binary.with_name(
            ".oscam.server-manager-update.tmp"
        )

        # Wichtig:
        # binary_replaced wird unmittelbar nach os.replace() gesetzt.
        # Damit bleibt bekannt, dass der produktive Zustand bereits
        # verändert wurde, selbst wenn ein nachfolgendes fsync()
        # oder eine andere Abschlussoperation fehlschlägt.
        binary_replaced = False

        try:
            if temp_binary.exists():
                temp_binary.unlink()

            shutil.copyfile(
                new_binary,
                temp_binary,
            )

            os.chmod(
                temp_binary,
                0o755,
            )

            os.chown(
                temp_binary,
                0,
                0,
            )

            with temp_binary.open("rb") as f:
                os.fsync(f.fileno())

            os.replace(
                temp_binary,
                installed_binary,
            )

            binary_replaced = True

            dir_fd = os.open(
                str(installed_binary.parent),
                os.O_DIRECTORY,
            )

            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

            install_ok = True
            install_error = ""

        except Exception as e:
            install_ok = False
            install_error = str(e)

            try:
                if temp_binary.exists():
                    temp_binary.unlink()
            except Exception:
                pass

        changed_productive = binary_replaced

        # Nach einem erfolgreichen Austausch muss die produktive
        # Binary byte-identisch mit dem geprüften Build-Artefakt sein.
        source_sha256 = None
        installed_sha256 = None
        install_hash_ok = False

        if install_ok:
            def _sha256(path):
                h = hashlib.sha256()

                with Path(path).open("rb") as f:
                    for chunk in iter(
                        lambda: f.read(1024 * 1024),
                        b"",
                    ):
                        h.update(chunk)

                return h.hexdigest()

            try:
                source_sha256 = _sha256(new_binary)
                installed_sha256 = _sha256(installed_binary)

                install_hash_ok = bool(
                    source_sha256
                    and source_sha256 == installed_sha256
                )

                if not install_hash_ok:
                    install_ok = False
                    install_error = (
                        "SHA256 der installierten OSCam-Binary "
                        "stimmt nicht mit dem Build-Artefakt überein."
                    )

            except Exception as e:
                install_ok = False
                install_error = (
                    "SHA256-Prüfung der installierten "
                    "OSCam-Binary fehlgeschlagen: {}"
                ).format(e)

        add_step(
            7,
            "binary_install",
            labels.get("binary_install"),
            "executed" if install_ok else "failed",
            changed=install_ok,
            message=(
                "Neue OSCam-Binary atomar installiert."
                if install_ok
                else "OSCam-Binary konnte nicht installiert werden."
            ),
            command=(
                "{} -> /usr/local/bin/oscam"
            ).format(new_binary),
            output=install_error,
            returncode=0 if install_ok else 1,
            binary=str(new_binary),
            version=new_version,
            source_sha256=source_sha256,
            installed_sha256=installed_sha256,
            hash_ok=install_hash_ok,
            binary_replaced=binary_replaced,
        )

        if not install_ok:
            if binary_replaced:
                return fail(
                    "OSCam-Binary wurde ausgetauscht, "
                    "die Installationsprüfung ist jedoch "
                    "fehlgeschlagen.",
                    rollback=True,
                )

            # Produktive Binary wurde noch nicht verändert.
            # Den zuvor gestoppten Dienst mit dem alten Stand
            # wieder starten.
            sh(
                "systemctl start oscam.service",
                timeout=60,
            )

            return fail(
                "OSCam-Binary-Installation fehlgeschlagen."
            )

        # ------------------------------------------------------------
        # 8. Dienst starten
        # ------------------------------------------------------------

        start_r = sh(
            "systemctl start oscam.service",
            timeout=60,
        )

        add_step(
            8,
            "service_restart",
            labels.get("service_restart"),
            "executed" if start_r.get("ok") else "failed",
            changed=True,
            message=(
                "OSCam-Dienst mit neuer Binary gestartet."
                if start_r.get("ok")
                else "OSCam-Dienst konnte mit neuer Binary "
                     "nicht gestartet werden."
            ),
            command="systemctl start oscam.service",
            output=(
                (start_r.get("stdout") or "")
                + (start_r.get("stderr") or "")
            ),
            returncode=start_r.get("returncode"),
        )

        if not start_r.get("ok"):
            return fail(
                "OSCam-Dienststart nach Update fehlgeschlagen.",
                rollback=True,
            )

        # Etwas Startzeit geben, update_verify() übernimmt danach
        # das eigentliche Stabilitätsfenster.
        time.sleep(3)

        # ------------------------------------------------------------
        # 9. Verify
        # ------------------------------------------------------------

        verify = self.update_verify()

        installed_version = (
            verify.get("current_version")
            if isinstance(verify, dict)
            else None
        )

        version_matches_candidate = bool(
            new_version
            and installed_version == new_version
        )

        verify_ok = bool(
            isinstance(verify, dict)
            and verify.get("ok")
            and version_matches_candidate
        )

        add_step(
            9,
            "service_verify",
            labels.get("service_verify"),
            "executed" if verify_ok else "failed",
            changed=False,
            message=(
                "OSCam-Update erfolgreich verifiziert."
                if verify_ok
                else "OSCam-Update-Verifikation fehlgeschlagen."
            ),
            current_version=installed_version,
            expected_version=new_version,
            version_matches=version_matches_candidate,
            verify=verify,
            returncode=0 if verify_ok else 1,
        )

        if not verify_ok:
            return fail(
                "OSCam-Update wurde installiert, "
                "aber die Verifikation ist fehlgeschlagen.",
                rollback=True,
            )

        result["ok"] = True
        result["current_version"] = installed_version
        result["latest_version"] = new_version
        result["message"] = (
            "OSCam-EMU wurde erfolgreich auf {} aktualisiert."
        ).format(
            installed_version
        )

        return result

    def update_rollback(
        self,
        session=None,
        restore_config=True,
        simulate=True,
    ):
        """
        Prüft und plant den Rückweg auf das vom aktuellen Update-Run
        validierte Pre-Update-Backup.

        Es wird ausdrücklich kein beliebiger oder lediglich letzter
        Backup-Run verwendet. Zulässig ist ausschließlich das Backup
        aus session["backup_check"].

        In dieser Entwicklungsphase ist nur die Simulation freigegeben.
        """

        from pathlib import Path
        import hashlib
        import json
        import os
        import shutil
        import time

        session = session if isinstance(session, dict) else {}

        result = {
            "supported": True,
            "ok": False,
            "simulate": bool(simulate),
            "mode": (
                "simulation"
                if simulate
                else "execute"
            ),
            "app_id": self.app_id,
            "label": self.label,
            "restore_config": bool(restore_config),
            "backup_run_id": None,
            "backup_dir": None,
            "manifest": None,
            "checks": [],
            "steps": [],
            "errors": [],
            "warnings": [],
        }

        def add_check(name, ok, message, **details):
            item = {
                "name": name,
                "ok": bool(ok),
                "message": message,
            }

            if details:
                item["details"] = details

            result["checks"].append(item)

            if not ok:
                result["errors"].append(message)

            return bool(ok)

        def sha256_file(path):
            h = hashlib.sha256()

            with path.open("rb") as f:
                for chunk in iter(
                    lambda: f.read(1024 * 1024),
                    b"",
                ):
                    h.update(chunk)

            return h.hexdigest()

        # ------------------------------------------------------------
        # Ausschließlich das vom Update-Gate validierte Backup nehmen.
        # ------------------------------------------------------------

        backup_check = session.get("backup_check") or {}

        add_check(
            "backup_check_valid",
            backup_check.get("ok") is True,
            (
                "Pre-Update-Backup wurde vom Backup-Check validiert."
                if backup_check.get("ok") is True
                else "Kein validiertes Pre-Update-Backup in der Session."
            ),
        )

        validated = backup_check.get("backup") or {}

        result["backup_run_id"] = validated.get("run_id")

        backup = validated.get("backup") or {}

        backup_dir_raw = str(
            backup.get("work_dir") or ""
        ).strip()

        backup_dir = (
            Path(backup_dir_raw)
            if backup_dir_raw
            else None
        )

        result["backup_dir"] = (
            str(backup_dir)
            if backup_dir
            else None
        )

        add_check(
            "backup_directory",
            bool(
                backup_dir
                and backup_dir.is_dir()
            ),
            (
                "Validiertes Backup-Verzeichnis ist vorhanden."
                if backup_dir and backup_dir.is_dir()
                else "Validiertes Backup-Verzeichnis fehlt."
            ),
            path=str(backup_dir or ""),
        )

        if not backup_dir or not backup_dir.is_dir():
            result["message"] = (
                "OSCam-Rollback nicht möglich: "
                "Backup-Verzeichnis fehlt."
            )
            return result

        # Sicherstellen, dass wirklich ein OSCam-Backup referenziert wird.
        add_check(
            "backup_app_id",
            backup.get("app_id") == self.app_id,
            (
                "Backup gehört zu OSCam."
                if backup.get("app_id") == self.app_id
                else "Validiertes Backup gehört nicht zu OSCam."
            ),
            backup_app_id=backup.get("app_id"),
        )

        extra_root = (
            backup_dir
            / "extra"
            / "oscam"
        )

        manifest_path = extra_root / "manifest.json"

        result["manifest"] = str(manifest_path)

        add_check(
            "manifest_exists",
            manifest_path.is_file(),
            (
                "OSCam-Rollback-Manifest ist vorhanden."
                if manifest_path.is_file()
                else "OSCam-Rollback-Manifest fehlt."
            ),
            path=str(manifest_path),
        )

        if not manifest_path.is_file():
            result["message"] = (
                "OSCam-Rollback nicht möglich: Manifest fehlt."
            )
            return result

        try:
            manifest = json.loads(
                manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as e:
            add_check(
                "manifest_readable",
                False,
                "OSCam-Rollback-Manifest ist ungültig.",
                error=str(e),
            )

            result["message"] = (
                "OSCam-Rollback nicht möglich: "
                "Manifest konnte nicht gelesen werden."
            )
            return result

        add_check(
            "manifest_readable",
            True,
            "OSCam-Rollback-Manifest konnte gelesen werden.",
        )

        add_check(
            "manifest_app_id",
            manifest.get("app_id") == self.app_id,
            (
                "Manifest gehört zu OSCam."
                if manifest.get("app_id") == self.app_id
                else "Manifest gehört nicht zu OSCam."
            ),
            manifest_app_id=manifest.get("app_id"),
        )

        # ------------------------------------------------------------
        # Binary prüfen.
        # ------------------------------------------------------------

        binary_meta = manifest.get("binary") or {}
        binary_rel = str(
            binary_meta.get("backup") or ""
        ).strip()

        binary_backup = (
            extra_root / binary_rel
            if binary_rel
            else None
        )

        binary_exists = bool(
            binary_backup
            and binary_backup.is_file()
        )

        add_check(
            "binary_exists",
            binary_exists,
            (
                "Gesicherte OSCam-Binary ist vorhanden."
                if binary_exists
                else "Gesicherte OSCam-Binary fehlt."
            ),
            path=str(binary_backup or ""),
        )

        if binary_exists:
            actual_sha = sha256_file(binary_backup)
            expected_sha = str(
                binary_meta.get("sha256") or ""
            ).strip()

            add_check(
                "binary_sha256",
                bool(
                    expected_sha
                    and actual_sha == expected_sha
                ),
                (
                    "SHA256 der gesicherten OSCam-Binary stimmt."
                    if expected_sha
                    and actual_sha == expected_sha
                    else "SHA256 der gesicherten OSCam-Binary stimmt nicht."
                ),
                expected=expected_sha,
                actual=actual_sha,
            )

            add_check(
                "binary_metadata",
                all(
                    key in binary_meta
                    for key in (
                        "mode",
                        "uid",
                        "gid",
                    )
                ),
                (
                    "Binary-Metadaten für Restore sind vorhanden."
                    if all(
                        key in binary_meta
                        for key in (
                            "mode",
                            "uid",
                            "gid",
                        )
                    )
                    else "Binary-Metadaten für Restore fehlen."
                ),
                mode=binary_meta.get("mode"),
                uid=binary_meta.get("uid"),
                gid=binary_meta.get("gid"),
            )

        # ------------------------------------------------------------
        # systemd Unit prüfen.
        # ------------------------------------------------------------

        service_meta = manifest.get("service") or {}
        service_rel = str(
            service_meta.get("backup") or ""
        ).strip()

        service_backup = (
            extra_root / service_rel
            if service_rel
            else None
        )

        service_exists = bool(
            service_backup
            and service_backup.is_file()
        )

        add_check(
            "service_exists",
            service_exists,
            (
                "Gesicherte OSCam-systemd-Unit ist vorhanden."
                if service_exists
                else "Gesicherte OSCam-systemd-Unit fehlt."
            ),
            path=str(service_backup or ""),
        )

        if service_exists:
            actual_sha = sha256_file(service_backup)
            expected_sha = str(
                service_meta.get("sha256") or ""
            ).strip()

            add_check(
                "service_sha256",
                bool(
                    expected_sha
                    and actual_sha == expected_sha
                ),
                (
                    "SHA256 der systemd-Unit stimmt."
                    if expected_sha
                    and actual_sha == expected_sha
                    else "SHA256 der systemd-Unit stimmt nicht."
                ),
                expected=expected_sha,
                actual=actual_sha,
            )

        # ------------------------------------------------------------
        # Build-Konfiguration prüfen.
        # ------------------------------------------------------------

        build_meta = manifest.get("build_config") or {}
        build_rel = str(
            build_meta.get("backup") or ""
        ).strip()

        build_backup = (
            extra_root / build_rel
            if build_rel
            else None
        )

        build_exists = bool(
            build_backup
            and build_backup.is_file()
        )

        add_check(
            "build_config_exists",
            build_exists,
            (
                "Gesicherte OSCam-Buildkonfiguration ist vorhanden."
                if build_exists
                else "Gesicherte OSCam-Buildkonfiguration fehlt."
            ),
            path=str(build_backup or ""),
        )

        if build_exists:
            actual_sha = sha256_file(build_backup)
            expected_sha = str(
                build_meta.get("sha256") or ""
            ).strip()

            add_check(
                "build_config_sha256",
                bool(
                    expected_sha
                    and actual_sha == expected_sha
                ),
                (
                    "SHA256 der Buildkonfiguration stimmt."
                    if expected_sha
                    and actual_sha == expected_sha
                    else "SHA256 der Buildkonfiguration stimmt nicht."
                ),
                expected=expected_sha,
                actual=actual_sha,
            )

        # ------------------------------------------------------------
        # Vollständige Konfiguration prüfen.
        # ------------------------------------------------------------

        config_meta = manifest.get("config") or {}

        config_rel = str(
            config_meta.get("archive") or ""
        ).strip()

        config_archive = (
            extra_root / config_rel
            if config_rel
            else None
        )

        config_exists = bool(
            config_archive
            and config_archive.is_file()
        )

        if restore_config:
            add_check(
                "config_archive",
                bool(
                    config_meta.get("archive_ok")
                    and config_exists
                ),
                (
                    "Metadata-erhaltendes config.tar ist vorhanden."
                    if (
                        config_meta.get("archive_ok")
                        and config_exists
                    )
                    else "Metadata-erhaltendes config.tar fehlt oder ist ungültig."
                ),
                path=str(config_archive or ""),
                archive_ok=config_meta.get("archive_ok"),
            )

        else:
            result["warnings"].append(
                "Konfigurations-Restore wurde für diesen "
                "Rollback ausdrücklich deaktiviert."
            )

        # ------------------------------------------------------------
        # Geplanter Rückspielpfad.
        # ------------------------------------------------------------

        planned = [
            {
                "order": 1,
                "id": "rollback_precheck",
                "label": "Validiertes OSCam-Backup prüfen",
                "status": "simulated",
                "changed": False,
                "message": (
                    "Manifest, Binary und Prüfsummen wurden geprüft."
                ),
            },
            {
                "order": 2,
                "id": "rollback_stop",
                "label": "OSCam-Dienst stoppen",
                "status": "simulated",
                "changed": False,
                "command": (
                    "systemctl stop oscam.service"
                ),
            },
            {
                "order": 3,
                "id": "rollback_binary",
                "label": "Gesicherte OSCam-Binary wiederherstellen",
                "status": "simulated",
                "changed": False,
                "source": str(binary_backup or ""),
                "target": "/usr/local/bin/oscam",
                "mode": binary_meta.get("mode"),
                "uid": binary_meta.get("uid"),
                "gid": binary_meta.get("gid"),
            },
        ]

        order = 4

        if restore_config:
            planned.append({
                "order": order,
                "id": "rollback_config",
                "label": "OSCam-Konfiguration wiederherstellen",
                "status": "simulated",
                "changed": False,
                "source": str(config_archive or ""),
                "target": host_literal('oscam', "/var/lib/oscam/config"),
                "command": (
                    "tar --acls --xattrs --numeric-owner "
                    "-xpf {} -C /var/lib/oscam"
                ).format(config_archive or ""),
            })
            order += 1

        planned.extend([
            {
                "order": order,
                "id": "rollback_service",
                "label": "OSCam-systemd-Unit wiederherstellen",
                "status": "simulated",
                "changed": False,
                "source": str(service_backup or ""),
                "target": "/etc/systemd/system/oscam.service",
            },
            {
                "order": order + 1,
                "id": "rollback_build_config",
                "label": "OSCam-Buildkonfiguration wiederherstellen",
                "status": "simulated",
                "changed": False,
                "source": str(build_backup or ""),
                "target": host_literal('oscam', "/opt/oscam/config.h"),
            },
            {
                "order": order + 2,
                "id": "rollback_daemon_reload",
                "label": "systemd-Konfiguration neu laden",
                "status": "simulated",
                "changed": False,
                "command": "systemctl daemon-reload",
            },
            {
                "order": order + 3,
                "id": "rollback_start",
                "label": "OSCam-Dienst starten",
                "status": "simulated",
                "changed": False,
                "command": "systemctl start oscam.service",
            },
            {
                "order": order + 4,
                "id": "rollback_verify",
                "label": "Wiederhergestellten OSCam-Zustand prüfen",
                "status": "simulated",
                "changed": False,
                "message": (
                    "Binary-Version, Dienst, WebIF und "
                    "Restart-Stabilität würden geprüft."
                ),
            },
        ])

        result["steps"] = planned

        result["ok"] = (
            len(result["errors"]) == 0
        )

        if simulate:
            if result["ok"]:
                result["message"] = (
                    "OSCam-Rollback ist vollständig vorbereitet "
                    "und wurde erfolgreich simuliert."
                )
            else:
                result["message"] = (
                    "OSCam-Rollback kann mit diesem Backup "
                    "nicht sicher durchgeführt werden."
                )

            return result

        # ------------------------------------------------------------
        # Ab hier echter Rollback.
        # Nur möglich, wenn ALLE Prüfungen zuvor erfolgreich waren.
        # ------------------------------------------------------------

        if not result["ok"]:
            result["message"] = (
                "OSCam-Rollback wurde wegen fehlgeschlagener "
                "Backup-Prüfungen nicht ausgeführt."
            )
            return result

        result["steps"] = []

        def add_exec_step(
            order,
            step_id,
            label,
            ok,
            changed=False,
            message="",
            **details
        ):
            step = {
                "order": order,
                "id": step_id,
                "label": label,
                "status": "executed" if ok else "failed",
                "changed": bool(changed),
                "message": message,
            }

            if details:
                step.update(details)

            result["steps"].append(step)

            if not ok:
                result["errors"].append(
                    "{}: {}".format(
                        label,
                        message or "fehlgeschlagen",
                    )
                )

            return bool(ok)

        def copy_atomic(
            source,
            target,
            *,
            mode=None,
            uid=None,
            gid=None,
        ):
            source = Path(source)
            target = Path(target)

            tmp = target.with_name(
                ".{}.server-manager-rollback.tmp".format(
                    target.name
                )
            )

            try:
                if tmp.exists():
                    tmp.unlink()

                shutil.copyfile(source, tmp)

                if mode is not None:
                    os.chmod(tmp, int(mode))

                if uid is not None and gid is not None:
                    os.chown(
                        tmp,
                        int(uid),
                        int(gid),
                    )

                with tmp.open("rb") as f:
                    os.fsync(f.fileno())

                os.replace(tmp, target)

                dir_fd = os.open(
                    str(target.parent),
                    os.O_DIRECTORY,
                )

                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)

                return {
                    "ok": True,
                    "target": str(target),
                }

            except Exception as e:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except Exception:
                    pass

                return {
                    "ok": False,
                    "target": str(target),
                    "error": str(e),
                }

        expected_version = None

        version_text = str(
            manifest.get("version") or ""
        )

        for line in version_text.splitlines():
            if line.strip().startswith("Version:"):
                expected_version = (
                    line.split(":", 1)[1].strip()
                )
                break

        # ------------------------------------------------------------
        # 1. Dienst stoppen
        # ------------------------------------------------------------

        stop_r = sh(
            "systemctl stop oscam.service",
            timeout=60,
        )

        if not add_exec_step(
            1,
            "rollback_stop",
            "OSCam-Dienst stoppen",
            bool(stop_r.get("ok")),
            changed=bool(stop_r.get("ok")),
            message=(
                "OSCam-Dienst gestoppt."
                if stop_r.get("ok")
                else "OSCam-Dienst konnte nicht gestoppt werden."
            ),
            returncode=stop_r.get("returncode"),
            output=(
                (stop_r.get("stdout") or "")
                + (stop_r.get("stderr") or "")
            ),
        ):
            result["ok"] = False
            result["message"] = (
                "OSCam-Rollback bereits beim Stoppen "
                "des Dienstes abgebrochen."
            )
            return result

        # ------------------------------------------------------------
        # 2. Binary atomar wiederherstellen
        # ------------------------------------------------------------

        binary_restore = copy_atomic(
            binary_backup,
            "/usr/local/bin/oscam",
            mode=binary_meta.get("mode"),
            uid=binary_meta.get("uid"),
            gid=binary_meta.get("gid"),
        )

        binary_restore_ok = bool(
            binary_restore.get("ok")
        )

        if binary_restore_ok:
            restored_sha = sha256_file(
                Path("/usr/local/bin/oscam")
            )

            binary_restore_ok = (
                restored_sha
                == str(binary_meta.get("sha256") or "")
            )
        else:
            restored_sha = None

        if not add_exec_step(
            2,
            "rollback_binary",
            "Gesicherte OSCam-Binary wiederherstellen",
            binary_restore_ok,
            changed=True,
            message=(
                "OSCam-Binary wurde atomar wiederhergestellt "
                "und per SHA256 geprüft."
                if binary_restore_ok
                else "OSCam-Binary konnte nicht sicher "
                     "wiederhergestellt werden."
            ),
            expected_sha256=binary_meta.get("sha256"),
            actual_sha256=restored_sha,
            error=binary_restore.get("error"),
        ):
            # Dienst wenigstens mit dem aktuell vorhandenen Zustand
            # wieder zu starten versuchen.
            sh(
                "systemctl start oscam.service",
                timeout=60,
            )

            result["ok"] = False
            result["message"] = (
                "OSCam-Rollback bei Binary-Restore fehlgeschlagen."
            )
            return result

        # ------------------------------------------------------------
        # 3. Konfiguration metadata-erhaltend wiederherstellen
        # ------------------------------------------------------------

        order = 3

        if restore_config:
            config_parent = Path("/var/lib/oscam")

            stage_root = (
                config_parent
                / ".server-manager-oscam-rollback-stage"
            )

            old_config = (
                config_parent
                / ".server-manager-oscam-config-old"
            )

            config_ok = False
            config_error = ""

            try:
                if stage_root.exists():
                    shutil.rmtree(stage_root)

                if old_config.exists():
                    shutil.rmtree(old_config)

                stage_root.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                extract_r = sh(
                    "tar --acls --xattrs --numeric-owner "
                    "-xpf {} -C {}".format(
                        config_archive,
                        stage_root,
                    ),
                    timeout=120,
                )

                staged_config = stage_root / "config"

                if (
                    not extract_r.get("ok")
                    or not staged_config.is_dir()
                ):
                    raise RuntimeError(
                        "config.tar konnte nicht vollständig "
                        "entpackt werden: {}".format(
                            (
                                (extract_r.get("stdout") or "")
                                + "\n"
                                + (extract_r.get("stderr") or "")
                            ).strip()
                        )
                    )

                current_config = (
                    config_parent / "config"
                )

                if current_config.exists():
                    os.replace(
                        current_config,
                        old_config,
                    )

                try:
                    os.replace(
                        staged_config,
                        current_config,
                    )
                except Exception:
                    if old_config.exists():
                        os.replace(
                            old_config,
                            current_config,
                        )
                    raise

                if old_config.exists():
                    shutil.rmtree(old_config)

                if stage_root.exists():
                    shutil.rmtree(stage_root)

                # Nach erfolgreichem Swap dürfen keine
                # temporären Rollback-Verzeichnisse zurückbleiben.
                leftovers = []

                if stage_root.exists():
                    leftovers.append(str(stage_root))

                if old_config.exists():
                    leftovers.append(str(old_config))

                if leftovers:
                    raise RuntimeError(
                        "Temporäre Rollback-Verzeichnisse "
                        "wurden nicht vollständig entfernt: {}"
                        .format(", ".join(leftovers))
                    )

                if not current_config.is_dir():
                    raise RuntimeError(
                        "Produktives OSCam-config-Verzeichnis "
                        "fehlt nach dem Restore."
                    )

                config_ok = True

            except Exception as e:
                config_error = str(e)

                # Falls nach einem teilweise fehlgeschlagenen Swap
                # kein config-Verzeichnis existiert, alten Zustand
                # wieder einsetzen.
                #
                # Ein Fehler bei dieser Notfall-Wiederherstellung darf
                # nicht verschluckt werden. Sonst könnte der Rollback
                # lediglich den ursprünglichen Fehler melden, obwohl
                # zusätzlich kein produktives config-Verzeichnis mehr
                # vorhanden ist.
                emergency_restore_error = None

                try:
                    current_config = (
                        config_parent / "config"
                    )

                    if (
                        not current_config.exists()
                        and old_config.exists()
                    ):
                        os.replace(
                            old_config,
                            current_config,
                        )
                except Exception as restore_e:
                    emergency_restore_error = str(restore_e)

                cleanup_error = None

                try:
                    if stage_root.exists():
                        shutil.rmtree(stage_root)
                except Exception as cleanup_e:
                    cleanup_error = str(cleanup_e)

                if emergency_restore_error:
                    config_error += (
                        " | KRITISCH: Wiederherstellung des "
                        "vorherigen config-Verzeichnisses "
                        "fehlgeschlagen: {}"
                    ).format(
                        emergency_restore_error
                    )

                if cleanup_error:
                    config_error += (
                        " | Bereinigung des Stage-Verzeichnisses "
                        "fehlgeschlagen: {}"
                    ).format(
                        cleanup_error
                    )

            if not add_exec_step(
                order,
                "rollback_config",
                "OSCam-Konfiguration wiederherstellen",
                config_ok,
                changed=True,
                message=(
                    "OSCam-Konfiguration einschließlich "
                    "UID/GID, Modi, ACLs und xattrs "
                    "wiederhergestellt."
                    if config_ok
                    else "OSCam-Konfiguration konnte nicht "
                         "vollständig wiederhergestellt werden."
                ),
                error=config_error or None,
            ):
                sh(
                    "systemctl start oscam.service",
                    timeout=60,
                )

                result["ok"] = False
                result["message"] = (
                    "OSCam-Rollback beim "
                    "Konfigurations-Restore fehlgeschlagen."
                )
                return result

            order += 1

        # ------------------------------------------------------------
        # 4. systemd Unit atomar zurückspielen
        # ------------------------------------------------------------

        service_restore = copy_atomic(
            service_backup,
            "/etc/systemd/system/oscam.service",
            mode=service_meta.get("mode"),
            uid=service_meta.get("uid"),
            gid=service_meta.get("gid"),
        )

        service_restore_ok = bool(
            service_restore.get("ok")
        )

        if service_restore_ok:
            restored_service_sha = sha256_file(
                Path(
                    "/etc/systemd/system/oscam.service"
                )
            )

            service_restore_ok = (
                restored_service_sha
                == str(service_meta.get("sha256") or "")
            )
        else:
            restored_service_sha = None

        if not add_exec_step(
            order,
            "rollback_service",
            "OSCam-systemd-Unit wiederherstellen",
            service_restore_ok,
            changed=True,
            message=(
                "OSCam-systemd-Unit wiederhergestellt."
                if service_restore_ok
                else "OSCam-systemd-Unit konnte nicht "
                     "wiederhergestellt werden."
            ),
            expected_sha256=service_meta.get("sha256"),
            actual_sha256=restored_service_sha,
            error=service_restore.get("error"),
        ):
            sh(
                "systemctl daemon-reload",
                timeout=30,
            )
            sh(
                "systemctl start oscam.service",
                timeout=60,
            )

            result["ok"] = False
            result["message"] = (
                "OSCam-Rollback beim systemd-Restore "
                "fehlgeschlagen."
            )
            return result

        order += 1

        # ------------------------------------------------------------
        # 5. Build-Konfiguration atomar zurückspielen
        # ------------------------------------------------------------

        build_restore = copy_atomic(
            build_backup,
            host_literal('oscam', "/opt/oscam/config.h"),
            mode=build_meta.get("mode"),
            uid=build_meta.get("uid"),
            gid=build_meta.get("gid"),
        )

        build_restore_ok = bool(
            build_restore.get("ok")
        )

        if build_restore_ok:
            restored_build_sha = sha256_file(
                Path(
                    host_literal('oscam', "/opt/oscam/config.h")
                )
            )

            build_restore_ok = (
                restored_build_sha
                == str(build_meta.get("sha256") or "")
            )
        else:
            restored_build_sha = None

        if not add_exec_step(
            order,
            "rollback_build_config",
            "OSCam-Buildkonfiguration wiederherstellen",
            build_restore_ok,
            changed=True,
            message=(
                "OSCam-Buildkonfiguration wiederhergestellt."
                if build_restore_ok
                else "OSCam-Buildkonfiguration konnte "
                     "nicht wiederhergestellt werden."
            ),
            expected_sha256=build_meta.get("sha256"),
            actual_sha256=restored_build_sha,
            error=build_restore.get("error"),
        ):
            sh(
                "systemctl daemon-reload",
                timeout=30,
            )
            sh(
                "systemctl start oscam.service",
                timeout=60,
            )

            result["ok"] = False
            result["message"] = (
                "OSCam-Rollback beim Restore der "
                "Buildkonfiguration fehlgeschlagen."
            )
            return result

        order += 1

        # ------------------------------------------------------------
        # 6. systemd reload
        # ------------------------------------------------------------

        reload_r = sh(
            "systemctl daemon-reload",
            timeout=30,
        )

        if not add_exec_step(
            order,
            "rollback_daemon_reload",
            "systemd-Konfiguration neu laden",
            bool(reload_r.get("ok")),
            changed=False,
            message=(
                "systemd-Konfiguration neu geladen."
                if reload_r.get("ok")
                else "systemd daemon-reload fehlgeschlagen."
            ),
            returncode=reload_r.get("returncode"),
            output=(
                (reload_r.get("stdout") or "")
                + (reload_r.get("stderr") or "")
            ),
        ):
            result["ok"] = False
            result["message"] = (
                "OSCam-Rollback bei daemon-reload "
                "fehlgeschlagen."
            )
            return result

        order += 1

        # ------------------------------------------------------------
        # 7. OSCam starten
        # ------------------------------------------------------------

        start_r = sh(
            "systemctl start oscam.service",
            timeout=60,
        )

        if not add_exec_step(
            order,
            "rollback_start",
            "OSCam-Dienst starten",
            bool(start_r.get("ok")),
            changed=bool(start_r.get("ok")),
            message=(
                "OSCam-Dienst gestartet."
                if start_r.get("ok")
                else "OSCam-Dienst konnte nicht gestartet werden."
            ),
            returncode=start_r.get("returncode"),
            output=(
                (start_r.get("stdout") or "")
                + (start_r.get("stderr") or "")
            ),
        ):
            result["ok"] = False
            result["message"] = (
                "OSCam-Rollback abgeschlossen, "
                "Dienststart jedoch fehlgeschlagen."
            )
            return result

        order += 1

        # OSCam benötigt kurz Zeit für Reader und WebIF.
        time.sleep(4)

        # ------------------------------------------------------------
        # 8. Exakte Version + normale OSCam-Verifikation
        # ------------------------------------------------------------

        restored_version_r = sh(
            "/usr/local/bin/oscam -V 2>&1",
            timeout=15,
        )

        restored_version = None

        restored_version_text = (
            (restored_version_r.get("stdout") or "")
            + "\n"
            + (restored_version_r.get("stderr") or "")
        )

        for line in restored_version_text.splitlines():
            if line.strip().startswith("Version:"):
                restored_version = (
                    line.split(":", 1)[1].strip()
                )
                break

        version_matches = bool(
            expected_version
            and restored_version == expected_version
        )

        verify = self.update_verify()

        verify_ok = bool(
            version_matches
            and verify.get("ok")
        )

        add_exec_step(
            order,
            "rollback_verify",
            "Wiederhergestellten OSCam-Zustand prüfen",
            verify_ok,
            changed=False,
            message=(
                "OSCam-Rollback erfolgreich verifiziert."
                if verify_ok
                else "OSCam-Rollback konnte nicht vollständig "
                     "verifiziert werden."
            ),
            expected_version=expected_version,
            restored_version=restored_version,
            version_matches=version_matches,
            verify=verify,
        )

        result["verify"] = verify
        result["expected_version"] = expected_version
        result["restored_version"] = restored_version

        result["ok"] = verify_ok

        if verify_ok:
            result["message"] = (
                "OSCam wurde vollständig auf den validierten "
                "Pre-Update-Zustand zurückgesetzt."
            )
        else:
            result["message"] = (
                "OSCam-Dateien wurden zurückgespielt, "
                "die abschließende Verifikation ist jedoch "
                "fehlgeschlagen."
            )

        return result

    def update_verify(self):
        """
        Verifiziert den aktuell installierten OSCam-Zustand.

        Diese Prüfung ist sowohl nach einer Simulation als auch nach
        einer späteren produktiven Update-Ausführung sicher nutzbar.
        """

        binary = "/usr/local/bin/oscam"
        service = "oscam.service"
        web_url = self.web_url

        version_r = sh(
            "{} -V 2>&1".format(binary),
            timeout=15,
        )

        version_output = (
            (version_r.get("stdout") or "")
            + "\n"
            + (version_r.get("stderr") or "")
        ).strip()

        installed_version = None

        for line in version_output.splitlines():
            raw = line.strip()

            if raw.startswith("Version:"):
                installed_version = (
                    raw.split(":", 1)[1].strip()
                )
                break

        attempts = []

        restart_start = None
        restart_end = None

        for attempt in range(1, 4):
            service_r = sh(
                "systemctl is-active {}".format(service),
                timeout=10,
            )

            service_state = (
                service_r.get("stdout") or ""
            ).strip()

            service_ok = service_state == "active"

            restart_r = sh(
                "systemctl show {} "
                "-p NRestarts --value".format(service),
                timeout=10,
            )

            restart_text = (
                restart_r.get("stdout") or ""
            ).strip()

            try:
                restart_count = int(restart_text)
            except Exception:
                restart_count = None

            if restart_start is None:
                restart_start = restart_count

            restart_end = restart_count

            web_r = sh(
                "curl -sS -o /dev/null "
                "-w '%{{http_code}}' "
                "--connect-timeout 3 "
                "--max-time 5 "
                "{}".format(web_url),
                timeout=10,
            )

            web_http = (
                web_r.get("stdout") or ""
            ).strip()

            web_ok = (
                bool(web_r.get("ok"))
                and web_http.isdigit()
                and 200 <= int(web_http) < 500
            )

            attempts.append({
                "attempt": attempt,
                "service_active": service_state,
                "service_ok": service_ok,
                "web_http": web_http,
                "web_ok": web_ok,
                "restart_count": restart_count,
            })

        service_ok = bool(
            attempts
            and all(
                item["service_ok"]
                for item in attempts
            )
        )

        web_ok = bool(
            attempts
            and all(
                item["web_ok"]
                for item in attempts
            )
        )

        restart_stable = (
            restart_start is not None
            and restart_end is not None
            and restart_start == restart_end
        )

        version_ok = bool(installed_version)

        ok = bool(
            version_ok
            and service_ok
            and web_ok
            and restart_stable
        )

        if ok:
            message = (
                "OSCam-Verifikation erfolgreich: "
                "Binary, Dienst und WebIF sind stabil."
            )
        else:
            message = (
                "OSCam-Verifikation meldet einen "
                "instabilen Zustand."
            )

        return {
            "supported": True,
            "ok": ok,
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "message": message,
            "current_version": installed_version,
            "version_ok": version_ok,
            "service_ok": service_ok,
            "web_ok": web_ok,
            "restart_stable": restart_stable,
            "restart_start": restart_start,
            "restart_end": restart_end,
            "attempts": attempts,
        }

    def update_check(self):
        """
        Prüft die tatsächlich installierte OSCam-Binary gegen den
        oscam-gitlab-Upstream.

        Die installierte Binary ist die maßgebliche Quelle für die
        aktuelle Revision. Das lokale Git-Working-Tree darf lokale
        Build-Anpassungen enthalten und wird nicht als installierter
        Stand interpretiert.
        """

        repo = host_literal('oscam', "/opt/oscam")
        binary = "/usr/local/bin/oscam"
        upstream = "origin/master"
        base_upstream = "origin/oscam-gitlab"

        version_r = sh(
            "{} -V 2>&1".format(binary),
            timeout=15,
        )

        version_output = (
            (version_r.get("stdout") or "")
            + "\n"
            + (version_r.get("stderr") or "")
        ).strip()

        installed_version = None
        installed_revision = None
        installed_commit = None

        for line in version_output.splitlines():
            raw = line.strip()

            if not raw.startswith("Version:"):
                continue

            installed_version = raw.split(":", 1)[1].strip()

            # Beispiel:
            # 2.26.02-11945-802@6c8324e0
            if "@" in installed_version:
                left, installed_commit = installed_version.rsplit("@", 1)

                parts = left.split("-")

                if len(parts) >= 2:
                    candidate = parts[-2]

                    if candidate.isdigit():
                        installed_revision = candidate

            break

        if not installed_version:
            return self.native_update_result(
                supported=True,
                ok=False,
                state="error",
                label="Prüfung fehlgeschlagen",
                message="Installierte OSCam-Version konnte nicht gelesen werden.",
                current_version=None,
                latest_version=None,
                update_available=None,
                method="oscam-binary-git",
                details={
                    "binary": binary,
                    "version_output": version_output,
                },
                safe_to_update=False,
                requires_backup=True,
            )

        fetch_r = sh(
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} fetch --prune 2>&1").format(repo),
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
                message="OSCam-Upstream konnte nicht aktualisiert werden.",
                current_version=installed_version,
                latest_version=None,
                update_available=None,
                method="oscam-binary-git",
                details={
                    "repo": repo,
                    "binary": binary,
                    "installed_revision": installed_revision,
                    "installed_commit": installed_commit,
                    "fetch_output": fetch_output,
                },
                safe_to_update=False,
                requires_backup=True,
            )

        latest_tag_r = sh(
            host_literal('oscam', "sudo -n -u oscam sh -c "
            "\"git -C {} tag -l | "
            "grep -E '^[0-9]+$' | "
            "sort -n | tail -1\"").format(repo),
            timeout=15,
        )

        latest_revision = (
            latest_tag_r.get("stdout") or ""
        ).strip()

        latest_commit_r = sh(
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} rev-parse '{}^{{}}' 2>/dev/null || true").format(
                repo,
                upstream,
            ),
            timeout=15,
        )

        latest_commit = (
            latest_commit_r.get("stdout") or ""
        ).strip()

        base_commit_r = sh(
            host_literal('oscam', "sudo -n -u oscam "
            "git -C {} rev-parse '{}^{{}}' 2>/dev/null || true").format(
                repo,
                base_upstream,
            ),
            timeout=15,
        )

        base_commit = (
            base_commit_r.get("stdout") or ""
        ).strip()

        behind = None

        # Die installierte Binary enthält den Commit des zugrunde
        # liegenden OSCam-Basiszweigs, nicht den zusätzlichen
        # OSCam-EMU-Mergecommit. Deshalb wird der Commit-Rückstand
        # gegen origin/oscam-gitlab bestimmt.
        #
        # Ein Vergleich direkt gegen origin/master würde zusätzlich
        # EMU- und Merge-Commits zählen und einen irreführenden
        # Rückstand ergeben.
        if installed_commit and base_commit:
            counts_r = sh(
                host_literal('oscam', "sudo -n -u oscam "
                "git -C {} rev-list --left-right --count "
                "{}...{} 2>/dev/null || true").format(
                    repo,
                    installed_commit,
                    base_upstream,
                ),
                timeout=20,
            )

            counts_text = (
                counts_r.get("stdout") or ""
            ).strip()

            try:
                parts = counts_text.replace("\t", " ").split()

                if len(parts) >= 2:
                    behind = int(parts[1])
            except Exception:
                behind = None

        update_available = None

        if (
            installed_revision
            and latest_revision
            and installed_revision.isdigit()
            and latest_revision.isdigit()
        ):
            update_available = (
                int(latest_revision)
                > int(installed_revision)
            )

        elif behind is not None:
            update_available = behind > 0

        if update_available is True:
            state = "available"
            label = "Update verfügbar"
            message = (
                "OSCam Revision {} → {} ist verfügbar."
            ).format(
                installed_revision or installed_version,
                latest_revision or latest_commit[:8],
            )

        elif update_available is False:
            state = "current"
            label = "Aktuell"
            message = (
                "OSCam {} ist aktuell."
            ).format(installed_version)

        else:
            state = "unknown"
            label = "Unbekannt"
            message = (
                "OSCam-Version erkannt, Upstream-Vergleich aber "
                "nicht eindeutig möglich."
            )

        return self.native_update_result(
            supported=True,
            ok=True,
            state=state,
            label=label,
            message=message,
            current_version=installed_version,
            latest_version=(
                latest_revision
                if latest_revision
                else latest_commit[:8] or None
            ),
            update_available=update_available,
            method="oscam-binary-git",
            details={
                "repo": repo,
                "binary": binary,
                "upstream": upstream,
                "base_upstream": base_upstream,
                "installed_revision": installed_revision,
                "installed_commit": installed_commit,
                "latest_revision": latest_revision,
                "latest_commit": latest_commit,
                "base_commit": base_commit,
                "behind": behind,
                "fetch_output": fetch_output,
            },
            warnings=[],
            safe_to_update=False,
            requires_backup=True,
        )
