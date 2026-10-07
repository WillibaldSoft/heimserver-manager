# -*- coding: utf-8 -*-
from pathlib import Path
import json
import shlex
import time
from .base import BaseManager
from ..runner import sh
from ..settings import bool_setting

class DockerComposeManager(BaseManager):
    kind = "docker-compose"
    compose_dir = None
    web_url = None
    containers = {}
    paths = {}
    config_files = {}
    image_container = None
    log_container = None
    image_grep = None

    def _running_image_version(self):
        """
        Ermittelt die Version des tatsächlich laufenden Docker-Images.

        Verwendet bewusst die unveränderliche .Image-ID des laufenden
        Containers und nicht einen beweglichen Tag wie :latest.
        """

        container = getattr(
            self,
            "image_container",
            None,
        )

        if not container:
            containers = (
                getattr(self, "containers", {})
                or {}
            )

            if len(containers) == 1:
                container = next(
                    iter(containers.values())
                )

        result = {
            "value": None,
            "source": "running-image",
            "container": container,
            "image_id": None,
            "image_reference": None,
            "ok": False,
        }

        if not container:
            return result

        image_id_r = sh(
            (
                "docker inspect "
                "--format '{{{{.Image}}}}' {} "
                "2>/dev/null || true"
            ).format(repr(container)),
            timeout=15,
        )

        image_id = (
            image_id_r.get("stdout") or ""
        ).strip()

        reference_r = sh(
            (
                "docker inspect "
                "--format '{{{{.Config.Image}}}}' {} "
                "2>/dev/null || true"
            ).format(repr(container)),
            timeout=15,
        )

        image_reference = (
            reference_r.get("stdout") or ""
        ).strip()

        result["image_id"] = image_id or None
        result["image_reference"] = (
            image_reference or None
        )

        if not image_id:
            return result

        version_r = sh(
            (
                "docker image inspect {} "
                "--format "
                "'{{{{index .Config.Labels "
                "\"org.opencontainers.image.version\"}}}}' "
                "2>/dev/null || true"
            ).format(repr(image_id)),
            timeout=20,
        )

        version = (
            version_r.get("stdout") or ""
        ).strip()

        if version and version != "<no value>":
            result["value"] = version
            result["ok"] = True

        return result


    def status(self):
        """
        Ergänzt den Basisstatus bei Docker-Compose-Apps um die
        tatsächlich laufende Image-Version.
        """

        data = super().status()

        try:
            data["version"] = (
                self._running_image_version()
            )
        except Exception as e:
            data["version"] = {
                "value": None,
                "source": "running-image",
                "ok": False,
                "error": str(e),
            }

        return data


    def _container(self, name):
        return sh(
            "docker inspect -f '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' "
            + name + " 2>/dev/null || true",
            timeout=8
        )["stdout"]

    def _path_status(self, path):
        exists = sh(f"test -e {path!r} && echo yes || echo no", timeout=5)["stdout"]
        writable = sh(f"test -w {path!r} && echo yes || echo no", timeout=5)["stdout"]
        size = sh(f"du -sh {path!r} 2>/dev/null | awk '{{print $1}}' || true", timeout=15)["stdout"]
        return {"path": path, "exists": exists == "yes", "writable": writable == "yes", "size": size}

    def _file_status(self, path):
        exists = sh(f"test -f {path!r} && echo yes || echo no", timeout=5)["stdout"]
        readable = sh(f"test -r {path!r} && echo yes || echo no", timeout=5)["stdout"]
        meta = sh(f"stat -c '%U:%G %a %s bytes' {path!r} 2>/dev/null || true", timeout=5)["stdout"]
        return {"path": path, "exists": exists == "yes", "readable": readable == "yes", "meta": meta}

    def _compose_ps_structured(self):
        raw = self._compose_status().get("ps", "")
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"raw": line})
        return rows

    def info(self):
        grep = self.image_grep or self.app_id
        return {
            "compose": self._compose_status(),
            "compose_ps": self._compose_ps_structured(),
            "web": self._web_check(),
            "images": sh(
                "docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -Ei %r || true" % grep,
                timeout=8
            )["stdout"],
            "config_files": {k: self._file_status(v) for k, v in self.config_files.items()},
        }

    def health(self):
        d = self.status()
        d["compose_ps"] = self._compose_ps_structured()
        d["containers"] = {k: self._container(v) for k, v in self.containers.items()}
        d["paths"] = {k: self._path_status(v) for k, v in self.paths.items()}
        d["config_files"] = {k: self._file_status(v) for k, v in self.config_files.items()}
        if self.log_container:
            d["recent_logs"] = sh(f"docker logs --tail 40 {self.log_container} 2>&1 || true", timeout=12)["stdout"]
        return d



    def _pinned_update_tags(self):
        """
        Erkennt gepinnte Image-/Versions-Tags aus .env,
        wenn sie im docker-compose.yml verwendet werden.

        Beispiel:
        IMMICH_VERSION=v2
        image: ghcr.io/immich-app/immich-server:${IMMICH_VERSION:-release}
        """

        result = {
            "blocked": False,
            "pins": [],
            "warnings": [],
        }

        compose_dir = Path(self.compose_dir) if self.compose_dir else None
        if not compose_dir:
            return result

        compose_file = compose_dir / "docker-compose.yml"
        env_file = compose_dir / ".env"

        if not compose_file.exists() or not env_file.exists():
            return result

        try:
            compose_text = compose_file.read_text(encoding="utf-8", errors="ignore")
            env_text = env_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return result

        allowed_floating = {
            "",
            "release",
            "latest",
            "stable",
            "main",
        }

        for line in env_text.splitlines():
            raw = line.strip()

            if not raw or raw.startswith("#") or "=" not in raw:
                continue

            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            key_upper = key.upper()

            looks_like_tag = (
                key_upper.endswith("_VERSION")
                or key_upper.endswith("_TAG")
                or key_upper in ("VERSION", "IMAGE_TAG", "TAG")
            )

            if not looks_like_tag:
                continue

            used_in_compose = (
                "${" + key in compose_text
                or "$" + key in compose_text
            )

            if not used_in_compose:
                continue

            if value.lower() in allowed_floating:
                continue

            result["pins"].append({
                "key": key,
                "value": value,
            })

        if result["pins"]:
            result["blocked"] = True

            for pin in result["pins"]:
                result["warnings"].append(
                    "Compose verwendet gepinnten Tag: {}={}".format(
                        pin["key"],
                        pin["value"],
                    )
                )

            result["warnings"].append(
                "Automatisches Update wird nicht durchgeführt. Version/Tag zuerst bewusst in .env anpassen."
            )

        return result



    def _build_update_guard(self, pinned=None):
        """
        Einheitliche Update-Schutzbewertung.
        """

        pinned = pinned or []

        guard = {
            "blocked": False,
            "reason": None,
            "severity": "info",
            "message": "",
            "details": [],
            "recommendation": "",
        }

        if pinned:
            guard.update({
                "blocked": True,
                "reason": "pinned_version",
                "severity": "warning",
                "message": "Compose verwendet eine feste Versionsangabe.",
                "details": pinned,

                "config_file": str(Path(self.compose_dir) / ".env"),

                "edit_hint":
                    "Version/Tag in der Compose-Konfiguration bewusst anpassen.",

                "recommendation":
                    "Version/Tag prüfen und Update-Plan erneut erstellen.",
            })
        return guard


    def extra_backup(self, workdir):
        """
        Sichert Docker-Metadaten für Restore-Prüfung und Diagnose.

        Die Restore-Readiness verwendet insbesondere die vollständigen
        Container-Inspect-Daten, um Mounts und Netzwerke mit dem
        aktuellen Zustand vergleichen zu können.
        """

        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

        containers = getattr(self, "containers", {}) or {}

        result = {
            "ok": True,
            "message": "",
            "workdir": str(workdir),
            "containers": {},
            "files": [],
            "errors": [],
        }

        for key, container in containers.items():

            entry = {
                "key": key,
                "container": container,
                "inspect": None,
                "image_reference": None,
                "image_id": None,
                "image_inspect": None,
                "ok": True,
                "errors": [],
            }

            # --------------------------------------------------------
            # Container inspect
            # --------------------------------------------------------

            inspect_file = (
                workdir /
                "inspect-{}.json".format(container)
            )

            inspect_cmd = (
                "docker inspect {}"
            ).format(repr(container))

            inspect_r = sh(
                inspect_cmd,
                timeout=30,
            )

            inspect_output = (
                inspect_r.get("stdout") or ""
            ).strip()

            if (
                inspect_r.get("returncode") == 0
                and inspect_output
            ):
                inspect_file.write_text(
                    inspect_output + "\n",
                    encoding="utf-8",
                )

                entry["inspect"] = str(inspect_file)
                result["files"].append(str(inspect_file))

            else:
                entry["ok"] = False
                entry["errors"].append(
                    "docker inspect fehlgeschlagen"
                )

            # --------------------------------------------------------
            # Image-Referenz und tatsächlich laufende Image-ID
            # getrennt bestimmen.
            #
            # .Config.Image kann z.B. ":latest" sein und damit bereits
            # auf ein neueres, gepulltes Image zeigen.
            #
            # .Image ist dagegen die unveränderliche Image-ID, mit der
            # der aktuell laufende Container tatsächlich erstellt wurde.
            # --------------------------------------------------------

            image_reference_cmd = (
                "docker inspect "
                "--format '{{{{.Config.Image}}}}' {}"
            ).format(repr(container))

            image_reference_r = sh(
                image_reference_cmd,
                timeout=20,
            )

            image_reference = (
                image_reference_r.get("stdout") or ""
            ).strip()

            image_id_cmd = (
                "docker inspect "
                "--format '{{{{.Image}}}}' {}"
            ).format(repr(container))

            image_id_r = sh(
                image_id_cmd,
                timeout=20,
            )

            image_id = (
                image_id_r.get("stdout") or ""
            ).strip()

            if (
                image_reference_r.get("returncode") == 0
                and image_reference
            ):
                entry["image_reference"] = image_reference
            else:
                entry["ok"] = False
                entry["errors"].append(
                    "Container-Image-Referenz konnte "
                    "nicht ermittelt werden"
                )

            if (
                image_id_r.get("returncode") == 0
                and image_id
            ):
                entry["image_id"] = image_id
            else:
                entry["ok"] = False
                entry["errors"].append(
                    "Laufende Container-Image-ID konnte "
                    "nicht ermittelt werden"
                )

            # --------------------------------------------------------
            # Image inspect MUSS über die tatsächliche Image-ID laufen.
            # --------------------------------------------------------

            if image_id:

                image_file = (
                    workdir /
                    "image-inspect-{}.json".format(container)
                )

                image_inspect_cmd = (
                    "docker image inspect {}"
                ).format(repr(image_id))

                image_inspect_r = sh(
                    image_inspect_cmd,
                    timeout=30,
                )

                image_inspect_output = (
                    image_inspect_r.get("stdout") or ""
                ).strip()

                if (
                    image_inspect_r.get("returncode") == 0
                    and image_inspect_output
                ):
                    image_file.write_text(
                        image_inspect_output + "\n",
                        encoding="utf-8",
                    )

                    entry["image_inspect"] = str(image_file)
                    result["files"].append(str(image_file))

                else:
                    entry["ok"] = False
                    entry["errors"].append(
                        "docker image inspect fehlgeschlagen"
                    )

            result["containers"][key] = entry

            if not entry["ok"]:
                result["ok"] = False

                for error in entry["errors"]:
                    result["errors"].append(
                        "{}: {}".format(container, error)
                    )

        if result["ok"]:
            result["message"] = (
                "Docker-Container- und Image-Metadaten gesichert."
            )
        else:
            result["message"] = (
                "Docker-Metadaten konnten nicht vollständig "
                "gesichert werden."
            )

        return result


    def update_plan(self):
        """Liefert den geplanten Docker-Compose-Updateablauf."""

        uc = self.update_check()
        pinned = self._pinned_update_tags()

        guard = self._build_update_guard(
            pinned.get("pins") or []
        )

        if not uc.get("supported"):
            return {
                "supported": False,
                "message": uc.get("message"),
            }

        return {
            "supported": True,
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "update_available": uc.get("update_available"),
            "state": uc.get("state"),
            "requires_backup": True,
            "safe_to_update": False if pinned.get("blocked") else False,
            "auto_update_blocked": bool(pinned.get("blocked")),
            "pinned_update_tags": pinned.get("pins") or [],
            "update_guard": guard,
            "warnings": pinned.get("warnings") or [],
            "steps": [
                {
                    "id": "backup",
                    "label": "Backup erstellen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "compose_pull",
                    "label": "Docker Images aktualisieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "compose_up",
                    "label": "Container neu starten",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "health",
                    "label": "Health-Check durchführen",
                    "required": True,
                    "automatic": True,
                },
            ],
        }



    def update_execute(self, session=None):
        """Docker-Compose Update-Ausführung.

        Phase 5.14.7:
        - Standard bleibt Simulation
        - echte Ausführung nur mit update_execution_enabled=True
        - führt docker compose pull und docker compose up -d aus
        - Backup bleibt Aufgabe der Update-Engine / Prepare-Phase
        """
        plan = self.update_plan()

        if not plan.get("supported"):
            return {
                "supported": False,
                "ok": False,
                "app_id": self.app_id,
                "label": self.label,
                "message": plan.get("message") or "Update nicht unterstützt",
                "steps": [],
            }

        real_enabled = bool_setting("update_execution_enabled", False)
        simulate = True

        if isinstance(session, dict):
            simulate = bool(session.get("simulate", True))

        # Update Guard:
        # Gepinnte Versionen blockieren automatische Updates,
        # erlauben aber bewusst bestätigte manuelle Updates.
        update_guard = plan.get("update_guard") or {}

        guard_override = False

        if isinstance(session, dict):
            guard_override = bool(session.get("update_guard_override", False))

        if (
            (not simulate)
            and update_guard.get("blocked")
            and not guard_override
        ):
            return {
                "supported": True,
                "ok": False,
                "mode": "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "compose_dir": self.compose_dir,
                "update_available": plan.get("update_available"),
                "state": plan.get("state"),
                "message": "Update durch Update Guard blockiert.",
                "update_guard": update_guard,
                "warnings": plan.get("warnings") or [],
                "steps": [{
                    "order": 1,
                    "id": "update_guard",
                    "label": "Update Guard",
                    "status": "blocked",
                    "changed": False,
                    "message": update_guard.get("message", ""),
                }],
            }

        if simulate or not real_enabled:
            steps = []
            for idx, step in enumerate(plan.get("steps") or [], start=1):
                steps.append({
                    "order": idx,
                    "id": step.get("id"),
                    "label": step.get("label"),
                    "status": "simulated",
                    "changed": False,
                    "message": "Simulation: Schritt würde ausgeführt",
                })

            return {
                "supported": True,
                "ok": True,
                "mode": "simulate",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "compose_dir": self.compose_dir,
                "update_available": plan.get("update_available"),
                "state": plan.get("state"),
                "message": "Docker-Compose Update simuliert. Es wurden keine Änderungen vorgenommen.",
                "steps": steps,
            }

        steps = []
        ok = True

        def add_step(order, step_id, label, status, changed, message, command="", output="", returncode=None):
            nonlocal ok
            if status == "failed":
                ok = False
            steps.append({
                "order": order,
                "id": step_id,
                "label": label,
                "status": status,
                "changed": changed,
                "message": message,
                "command": command,
                "returncode": returncode,
                "output": (output or "")[-12000:],
            })

        compose_dir = self.compose_dir


        # Live Status an Update Engine zurückmelden
        def update_live(action, step, state="executing"):
            if isinstance(session, dict):
                session["state"] = state
                session["current_step"] = step
                session["current_action"] = action

                try:
                    from ..update_engine import _write_json
                    run_dir = session.get("run_dir")

                    if run_dir:
                        _write_json(
                            Path(run_dir) / "session.json",
                            session
                        )

                except Exception:
                    pass


        update_live(
            "compose_pull",
            5
        )

        pull_cmd = "cd {} && docker compose pull 2>&1".format(repr(compose_dir))
        r = sh(pull_cmd, timeout=1800)
        pull_output = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
        pull_rc = r.get("returncode")

        add_step(
            1,
            "compose_pull",
            "Docker Images aktualisieren",
            "executed" if pull_rc == 0 else "failed",
            pull_rc == 0,
            "docker compose pull abgeschlossen" if pull_rc == 0 else "docker compose pull fehlgeschlagen",
            pull_cmd,
            pull_output,
            pull_rc,
        )

        if ok:

            update_live(
                "compose_up",
                6
            )

            up_cmd = "cd {} && docker compose up -d 2>&1".format(repr(compose_dir))
            r = sh(up_cmd, timeout=900)
            up_output = ((r.get("stdout") or "") + "\n" + (r.get("stderr") or "")).strip()
            up_rc = r.get("returncode")

            add_step(
                2,
                "compose_up",
                "Container neu starten",
                "executed" if up_rc == 0 else "failed",
                up_rc == 0,
                "docker compose up -d abgeschlossen" if up_rc == 0 else "docker compose up -d fehlgeschlagen",
                up_cmd,
                up_output,
                up_rc,
            )

        return {
            "supported": True,
            "ok": ok,
            "mode": "execute",
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "compose_dir": compose_dir,
            "update_available": plan.get("update_available"),
            "state": plan.get("state"),
            "message": "Docker-Compose Update ausgeführt." if ok else "Docker-Compose Update fehlgeschlagen.",
            "steps": steps,
        }


    def update_rollback(
        self,
        session=None,
        simulate=True,
    ):
        """
        Prüft und plant den Rollback eines Docker-Compose-Updates.

        Verwendet ausschließlich das an den aktuellen Update-Lauf
        gebundene und validierte Pre-Update-Backup.

        In dieser Phase ist nur die Simulation freigegeben.
        """

        from pathlib import Path
        import json

        session = session if isinstance(session, dict) else {}

        result = {
            "supported": True,
            "ok": False,
            "simulate": bool(simulate),
            "mode": "simulation" if simulate else "execute",
            "app_id": self.app_id,
            "label": self.label,
            "backup_run_id": None,
            "backup_dir": None,
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

        # ------------------------------------------------------------
        # Gebundenes Pre-Update-Backup
        # ------------------------------------------------------------

        backup_check = session.get("backup_check") or {}

        add_check(
            "backup_check_valid",
            backup_check.get("ok") is True,
            (
                "Pre-Update-Backup wurde validiert."
                if backup_check.get("ok") is True
                else "Kein validiertes Pre-Update-Backup vorhanden."
            ),
        )

        validated = backup_check.get("backup") or {}
        backup = validated.get("backup") or {}

        result["backup_run_id"] = validated.get("run_id")

        backup_dir_raw = str(
            backup.get("work_dir") or ""
        ).strip()

        result["backup_dir"] = backup_dir_raw or None

        backup_dir = (
            Path(backup_dir_raw)
            if backup_dir_raw
            else None
        )

        add_check(
            "backup_directory",
            bool(
                backup_dir
                and backup_dir.is_dir()
            ),
            (
                "Gebundenes Backup-Verzeichnis ist vorhanden."
                if backup_dir and backup_dir.is_dir()
                else "Gebundenes Backup-Verzeichnis fehlt."
            ),
            path=backup_dir_raw,
        )

        if not backup_dir or not backup_dir.is_dir():
            result["message"] = (
                "Docker-Compose-Rollback kann nicht vorbereitet werden."
            )
            return result

        # ------------------------------------------------------------
        # Backup muss zur App gehören
        # ------------------------------------------------------------

        manifest_file = backup_dir / "manifest.json"
        result_file = backup_dir / "result.json"
        extra_file = backup_dir / "extra-backup.json"

        manifest = {}
        backup_result = {}
        extra = {}

        try:
            manifest = json.loads(
                manifest_file.read_text(encoding="utf-8")
            )
            manifest_ok = True
        except Exception as e:
            manifest_ok = False
            result["errors"].append(
                "Backup-Manifest nicht lesbar: {}".format(e)
            )

        add_check(
            "manifest",
            manifest_ok,
            (
                "Backup-Manifest ist lesbar."
                if manifest_ok
                else "Backup-Manifest ist nicht lesbar."
            ),
        )

        if manifest_ok:
            add_check(
                "manifest_app_id",
                manifest.get("app_id") == self.app_id,
                (
                    "Backup gehört zur richtigen App."
                    if manifest.get("app_id") == self.app_id
                    else "Backup gehört nicht zur aktuellen App."
                ),
                manifest_app_id=manifest.get("app_id"),
            )

        try:
            backup_result = json.loads(
                result_file.read_text(encoding="utf-8")
            )
            backup_result_ok = True
        except Exception as e:
            backup_result_ok = False
            result["errors"].append(
                "Backup-result.json nicht lesbar: {}".format(e)
            )

        add_check(
            "backup_result",
            backup_result_ok,
            (
                "Backup-result.json ist lesbar."
                if backup_result_ok
                else "Backup-result.json ist nicht lesbar."
            ),
        )

        try:
            extra = json.loads(
                extra_file.read_text(encoding="utf-8")
            )
            extra_ok = bool(extra.get("ok"))
        except Exception as e:
            extra_ok = False
            result["errors"].append(
                "Docker-Backup-Metadaten nicht lesbar: {}".format(e)
            )

        add_check(
            "docker_metadata",
            extra_ok,
            (
                "Docker-Metadaten sind vorhanden."
                if extra_ok
                else "Docker-Metadaten fehlen oder sind ungültig."
            ),
        )

        # ------------------------------------------------------------
        # Config/Data prüfen
        # ------------------------------------------------------------

        backup_steps = backup_result.get("steps") or {}

        config_files = backup_steps.get("config_files") or {}
        data_paths = backup_steps.get("paths") or {}

        config_ok = bool(config_files) and all(
            item.get("ok")
            and Path(item.get("target") or "").exists()
            for item in config_files.values()
        )

        data_ok = bool(data_paths) and all(
            item.get("ok")
            and Path(item.get("target") or "").exists()
            for item in data_paths.values()
        )

        add_check(
            "config_backup",
            config_ok,
            (
                "Gesicherte Compose-/Konfigurationsdateien sind vorhanden."
                if config_ok
                else "Gesicherte Konfigurationsdateien sind unvollständig."
            ),
            count=len(config_files),
        )

        add_check(
            "data_backup",
            data_ok,
            (
                "Gesicherte persistente Datenpfade sind vorhanden."
                if data_ok
                else "Gesicherte persistente Datenpfade sind unvollständig."
            ),
            count=len(data_paths),
        )

        # ------------------------------------------------------------
        # Alte Container-/Image-Zustände prüfen
        # ------------------------------------------------------------

        containers_meta = extra.get("containers") or {}
        image_restore = []

        all_images_ok = bool(containers_meta)

        for key, entry in containers_meta.items():
            container = entry.get("container")
            image_tag = entry.get("image_reference")
            backed_up_image_id = entry.get("image_id")

            inspect_raw = entry.get("image_inspect")
            image_inspect = (
                Path(inspect_raw)
                if inspect_raw
                else None
            )

            image_id = None
            repo_digests = []

            try:
                raw = json.loads(
                    image_inspect.read_text(encoding="utf-8")
                )

                if isinstance(raw, list):
                    raw = raw[0] if raw else {}

                image_id = raw.get("Id")
                repo_digests = raw.get("RepoDigests") or []

                if (
                    backed_up_image_id
                    and image_id != backed_up_image_id
                ):
                    all_images_ok = False

            except Exception:
                all_images_ok = False

            local_ok = False

            if image_id:
                local_r = sh(
                    "docker image inspect {} "
                    "--format '{{{{.Id}}}}' "
                    "2>/dev/null".format(
                        repr(image_id)
                    ),
                    timeout=20,
                )

                local_ok = (
                    local_r.get("returncode") == 0
                    and (
                        local_r.get("stdout") or ""
                    ).strip() == image_id
                )

            if not (
                container
                and image_tag
                and image_id
                and local_ok
            ):
                all_images_ok = False

            rollback_tag = (
                "server-manager-rollback/"
                "{}-{}".format(
                    self.app_id,
                    key,
                )
            )

            image_restore.append({
                "key": key,
                "container": container,
                "image_tag": image_tag,
                "image_id": image_id,
                "repo_digests": repo_digests,
                "local_image_available": local_ok,
                "rollback_tag": rollback_tag,
                "protect_command": (
                    "docker tag {} {}".format(
                        repr(image_id),
                        repr(rollback_tag),
                    )
                    if image_id
                    else ""
                ),
                "restore_tag_command": (
                    "docker tag {} {}".format(
                        repr(image_id),
                        repr(image_tag),
                    )
                    if image_id and image_tag
                    else ""
                ),
            })

        add_check(
            "rollback_images",
            all_images_ok,
            (
                "Alle gesicherten Docker-Images sind lokal verfügbar."
                if all_images_ok
                else "Mindestens ein gesichertes Docker-Image "
                     "ist lokal nicht verfügbar."
            ),
            images=image_restore,
        )

        # ------------------------------------------------------------
        # Plan
        # ------------------------------------------------------------

        order = 1

        planned = []

        planned.append({
            "order": order,
            "id": "rollback_precheck",
            "label": "Gebundenes Pre-Update-Backup prüfen",
            "status": "simulated",
            "changed": False,
        })
        order += 1

        for image in image_restore:
            planned.append({
                "order": order,
                "id": "rollback_image_protect",
                "label": (
                    "Altes Docker-Image lokal schützen: {}"
                    .format(image.get("container"))
                ),
                "status": "simulated",
                "changed": False,
                "image_id": image.get("image_id"),
                "rollback_tag": image.get("rollback_tag"),
                "command": image.get("protect_command"),
            })
            order += 1

        planned.append({
            "order": order,
            "id": "rollback_stop",
            "label": "Compose-Anwendung stoppen",
            "status": "simulated",
            "changed": False,
            "command": (
                "cd {} && docker compose down"
            ).format(repr(self.compose_dir)),
        })
        order += 1

        planned.append({
            "order": order,
            "id": "rollback_config",
            "label": "Compose-Konfiguration wiederherstellen",
            "status": "simulated",
            "changed": False,
            "files": config_files,
        })
        order += 1

        planned.append({
            "order": order,
            "id": "rollback_data",
            "label": "Persistente Daten wiederherstellen",
            "status": "simulated",
            "changed": False,
            "paths": data_paths,
        })
        order += 1

        for image in image_restore:
            planned.append({
                "order": order,
                "id": "rollback_image_restore",
                "label": (
                    "Gesichertes Docker-Image wieder auf Compose-Tag setzen: {}"
                    .format(image.get("container"))
                ),
                "status": "simulated",
                "changed": False,
                "image_id": image.get("image_id"),
                "image_tag": image.get("image_tag"),
                "command": image.get("restore_tag_command"),
            })
            order += 1

        planned.append({
            "order": order,
            "id": "rollback_start",
            "label": "Compose-Anwendung starten",
            "status": "simulated",
            "changed": False,
            "command": (
                "cd {} && docker compose up -d"
            ).format(repr(self.compose_dir)),
        })
        order += 1

        planned.append({
            "order": order,
            "id": "rollback_verify",
            "label": "Wiederhergestellte Anwendung prüfen",
            "status": "simulated",
            "changed": False,
        })

        result["steps"] = planned
        result["images"] = image_restore

        result["ok"] = (
            len(result["errors"]) == 0
            and all_images_ok
            and config_ok
            and data_ok
        )

        if not simulate:
            # --------------------------------------------------------
            # Echtlauf nur nach vollständig erfolgreicher Validierung.
            # --------------------------------------------------------

            if not result["ok"]:
                result["message"] = (
                    "Docker-Compose-Update-Rollback wurde nicht "
                    "ausgeführt, weil die Vorprüfung fehlgeschlagen ist."
                )
                return result

            executed_steps = []

            def run_step(
                step_id,
                label,
                command,
                timeout=300,
            ):
                step = {
                    "order": len(executed_steps) + 1,
                    "id": step_id,
                    "label": label,
                    "command": command,
                    "status": "running",
                    "changed": False,
                }

                executed_steps.append(step)

                r = sh(
                    command,
                    timeout=timeout,
                )

                step["returncode"] = r.get("returncode")
                step["stdout"] = r.get("stdout")
                step["stderr"] = r.get("stderr")

                if r.get("ok"):
                    step["status"] = "executed"
                    step["changed"] = True
                    return True

                step["status"] = "failed"
                step["changed"] = False

                result["errors"].append(
                    "{} fehlgeschlagen.".format(label)
                )

                return False

            application_stopped = False

            def emergency_start(reason):
                """
                Wenn der Stack nach erfolgreichem compose down noch
                gestoppt ist, wird vor dem Abbruch genau ein
                Wiederanlauf versucht.

                Dieser Recovery-Versuch ersetzt keinen erfolgreichen
                Rollback. Er soll lediglich verhindern, dass ein
                Folgefehler die Anwendung unnötig offline lässt.
                """

                nonlocal application_stopped

                recovery = {
                    "attempted": False,
                    "ok": None,
                    "reason": reason,
                    "command": None,
                    "returncode": None,
                    "stdout": "",
                    "stderr": "",
                }

                if not application_stopped:
                    return recovery

                recovery["attempted"] = True

                cmd = (
                    "cd {} && docker compose up -d"
                ).format(repr(self.compose_dir))

                recovery["command"] = cmd

                r = sh(
                    cmd,
                    timeout=300,
                )

                recovery["returncode"] = r.get("returncode")
                recovery["stdout"] = r.get("stdout")
                recovery["stderr"] = r.get("stderr")
                recovery["ok"] = bool(r.get("ok"))

                executed_steps.append({
                    "order": len(executed_steps) + 1,
                    "id": "rollback_emergency_start",
                    "label": (
                        "Notfall-Wiederanlauf der "
                        "Compose-Anwendung"
                    ),
                    "command": cmd,
                    "status": (
                        "executed"
                        if recovery["ok"]
                        else "failed"
                    ),
                    "changed": bool(recovery["ok"]),
                    "message": (
                        "Compose-Anwendung nach Rollback-Fehler "
                        "wieder gestartet."
                        if recovery["ok"]
                        else "Compose-Anwendung konnte nach "
                             "Rollback-Fehler nicht wieder "
                             "gestartet werden."
                    ),
                    "reason": reason,
                    "returncode": recovery["returncode"],
                    "stdout": recovery["stdout"],
                    "stderr": recovery["stderr"],
                })

                if recovery["ok"]:
                    application_stopped = False

                result["recovery"] = recovery

                if not recovery["ok"]:
                    result["errors"].append(
                        "KRITISCH: Notfall-Wiederanlauf der "
                        "Compose-Anwendung fehlgeschlagen."
                    )

                return recovery

            # --------------------------------------------------------
            # 1. Alte Images unter eigenem Rollback-Tag schützen.
            # --------------------------------------------------------

            for image in image_restore:
                if not run_step(
                    "rollback_image_protect",
                    (
                        "Altes Docker-Image schützen: {}"
                        .format(image.get("container"))
                    ),
                    image.get("protect_command") or "",
                    timeout=60,
                ):
                    result["steps"] = executed_steps
                    result["ok"] = False
                    result["message"] = (
                        "Docker-Compose-Update-Rollback beim "
                        "Schützen des alten Images abgebrochen."
                    )
                    return result

            # --------------------------------------------------------
            # 2. Anwendung stoppen.
            # --------------------------------------------------------

            stop_cmd = (
                "cd {} && docker compose down"
            ).format(repr(self.compose_dir))

            if not run_step(
                "rollback_stop",
                "Compose-Anwendung stoppen",
                stop_cmd,
                timeout=180,
            ):
                result["steps"] = executed_steps
                result["ok"] = False
                result["message"] = (
                    "Docker-Compose-Update-Rollback beim "
                    "Stoppen der Anwendung abgebrochen."
                )
                return result

            application_stopped = True

            # --------------------------------------------------------
            # 3. Konfiguration wiederherstellen.
            # --------------------------------------------------------

            for key, item in config_files.items():
                src = str(item.get("target") or "").strip()
                dst = str(item.get("source") or "").strip()

                if not src or not dst:
                    result["errors"].append(
                        "Ungültiger Config-Restore-Pfad: {}"
                        .format(key)
                    )
                    result["steps"] = executed_steps
                    result["ok"] = False
                    result["message"] = (
                        "Docker-Compose-Update-Rollback wegen "
                        "ungültigem Config-Pfad abgebrochen."
                    )

                    emergency_start(
                        "Ungültiger Config-Restore-Pfad"
                    )

                    result["steps"] = executed_steps
                    return result

                cmd = "cp -a {} {}".format(
                    repr(src),
                    repr(dst),
                )

                if not run_step(
                    "rollback_config",
                    (
                        "Konfiguration wiederherstellen: {}"
                        .format(key)
                    ),
                    cmd,
                    timeout=120,
                ):
                    result["steps"] = executed_steps
                    result["ok"] = False
                    result["message"] = (
                        "Docker-Compose-Update-Rollback beim "
                        "Wiederherstellen der Konfiguration "
                        "abgebrochen."
                    )

                    emergency_start(
                        "Konfigurations-Restore fehlgeschlagen"
                    )

                    result["steps"] = executed_steps
                    return result

            # --------------------------------------------------------
            # 4. Persistente Daten wiederherstellen.
            # --------------------------------------------------------

            for key, item in data_paths.items():
                src = str(item.get("target") or "").rstrip("/")
                dst = str(item.get("source") or "").rstrip("/")

                if not src or not dst:
                    result["errors"].append(
                        "Ungültiger Daten-Restore-Pfad: {}"
                        .format(key)
                    )
                    result["steps"] = executed_steps
                    result["ok"] = False
                    result["message"] = (
                        "Docker-Compose-Update-Rollback wegen "
                        "ungültigem Datenpfad abgebrochen."
                    )

                    emergency_start(
                        "Ungültiger Daten-Restore-Pfad"
                    )

                    result["steps"] = executed_steps
                    return result

                cmd = (
                    "rsync -aHAX --numeric-ids --delete "
                    "{} {}"
                ).format(
                    repr(src + "/"),
                    repr(dst + "/"),
                )

                if not run_step(
                    "rollback_data",
                    (
                        "Persistente Daten wiederherstellen: {}"
                        .format(key)
                    ),
                    cmd,
                    timeout=3600,
                ):
                    result["steps"] = executed_steps
                    result["ok"] = False
                    result["message"] = (
                        "Docker-Compose-Update-Rollback beim "
                        "Wiederherstellen der Daten abgebrochen."
                    )

                    emergency_start(
                        "Daten-Restore fehlgeschlagen"
                    )

                    result["steps"] = executed_steps
                    return result

            # --------------------------------------------------------
            # 5. Gesicherte Images wieder auf Compose-Tags setzen.
            # --------------------------------------------------------

            for image in image_restore:
                if not run_step(
                    "rollback_image_restore",
                    (
                        "Docker-Image wiederherstellen: {}"
                        .format(image.get("container"))
                    ),
                    image.get("restore_tag_command") or "",
                    timeout=60,
                ):
                    result["steps"] = executed_steps
                    result["ok"] = False
                    result["message"] = (
                        "Docker-Compose-Update-Rollback beim "
                        "Wiederherstellen des Image-Tags "
                        "abgebrochen."
                    )

                    emergency_start(
                        "Docker-Image-Tag-Restore fehlgeschlagen"
                    )

                    result["steps"] = executed_steps
                    return result

            # --------------------------------------------------------
            # 6. Anwendung wieder starten.
            # --------------------------------------------------------

            start_cmd = (
                "cd {} && docker compose up -d"
            ).format(repr(self.compose_dir))

            if not run_step(
                "rollback_start",
                "Compose-Anwendung starten",
                start_cmd,
                timeout=300,
            ):
                result["ok"] = False
                result["message"] = (
                    "Docker-Compose-Update-Rollback beim "
                    "Starten der Anwendung abgebrochen."
                )

                emergency_start(
                    "Normaler Compose-Start nach Rollback "
                    "fehlgeschlagen"
                )

                result["steps"] = executed_steps
                return result

            application_stopped = False

            # --------------------------------------------------------
            # 7. Tatsächlich laufende Image-IDs verifizieren.
            # --------------------------------------------------------

            verify_ok = True
            verify_details = []

            for image in image_restore:
                container = image.get("container")
                expected_id = image.get("image_id")

                verify_r = sh(
                    (
                        "docker inspect "
                        "--format '{{{{.Image}}}}' {}"
                    ).format(repr(container)),
                    timeout=30,
                )

                actual_id = (
                    verify_r.get("stdout") or ""
                ).strip()

                image_ok = bool(
                    verify_r.get("ok")
                    and expected_id
                    and actual_id == expected_id
                )

                verify_details.append({
                    "container": container,
                    "expected_image_id": expected_id,
                    "actual_image_id": actual_id,
                    "ok": image_ok,
                })

                if not image_ok:
                    verify_ok = False

            verify_step = {
                "order": len(executed_steps) + 1,
                "id": "rollback_image_verify",
                "label": (
                    "Laufende Docker-Images gegen "
                    "Pre-Update-Backup prüfen"
                ),
                "status": (
                    "executed"
                    if verify_ok
                    else "failed"
                ),
                "changed": False,
                "containers": verify_details,
            }

            executed_steps.append(verify_step)

            if not verify_ok:
                result["steps"] = executed_steps
                result["ok"] = False
                result["errors"].append(
                    "Mindestens ein Container läuft nach dem "
                    "Rollback nicht mit der gesicherten Image-ID."
                )
                result["message"] = (
                    "Docker-Compose-Update-Rollback wurde "
                    "ausgeführt, die Image-Verifikation ist "
                    "jedoch fehlgeschlagen."
                )
                return result

            # --------------------------------------------------------
            # 8. Manager-Health prüfen.
            # --------------------------------------------------------

            health = self._wait_for_compose_health(
                timeout=90,
                interval=3,
            )

            health_ok = bool(
                isinstance(health, dict)
                and health.get("ok") is True
            )

            executed_steps.append({
                "order": len(executed_steps) + 1,
                "id": "rollback_verify",
                "label": (
                    "Wiederhergestellte Anwendung "
                    "auf Betriebsbereitschaft prüfen"
                ),
                "status": (
                    "executed"
                    if health_ok
                    else "failed"
                ),
                "changed": False,
                "health": health,
            })

            result["steps"] = executed_steps
            result["ok"] = health_ok

            if not health_ok:
                result["errors"].append(
                    "Anwendung wurde nach Docker-Compose-Rollback "
                    "nicht rechtzeitig betriebsbereit."
                )
                result["message"] = (
                    "Docker-Compose-Update-Rollback wurde "
                    "ausgeführt, die Anwendung erreichte jedoch "
                    "nicht rechtzeitig den betriebsbereiten Zustand."
                )
                return result

            result["message"] = (
                "Docker-Compose-Update-Rollback wurde "
                "erfolgreich ausgeführt und verifiziert."
            )

            return result

        result["message"] = (
            "Docker-Compose-Update-Rollback vollständig "
            "validiert und simuliert."
            if result["ok"]
            else "Docker-Compose-Update-Rollback kann mit "
                 "diesem Backup nicht sicher durchgeführt werden."
        )

        return result



    def _wait_for_compose_health(
        self,
        timeout=90,
        interval=3,
    ):
        """
        Wartet nach einem Docker-Compose-Neustart auf echte
        Betriebsbereitschaft.

        Bedingungen:
          - alle definierten Container laufen
          - vorhandene Docker-Healthchecks melden healthy
          - konfigurierte Web/API ist erreichbar

        Container ohne Docker-Healthcheck werden akzeptiert,
        sobald ihr State 'running' ist.
        """

        started = time.monotonic()
        attempts = 0
        last = {}

        while True:
            attempts += 1

            container_results = []
            containers_ok = True

            for key, container in (
                getattr(self, "containers", {}) or {}
            ).items():

                r = sh(
                    (
                        "docker inspect "
                        "--format "
                        "'{{{{.State.Status}}}}|"
                        "{{{{if .State.Health}}}}"
                        "{{{{.State.Health.Status}}}}"
                        "{{{{else}}}}no-health"
                        "{{{{end}}}}' {}"
                    ).format(repr(container)),
                    timeout=15,
                )

                raw = (
                    r.get("stdout") or ""
                ).strip()

                state = ""
                health = ""

                if "|" in raw:
                    state, health = raw.split("|", 1)

                running = (
                    r.get("ok") is True
                    and state == "running"
                )

                health_ok = health in (
                    "healthy",
                    "no-health",
                )

                container_ok = (
                    running
                    and health_ok
                )

                if not container_ok:
                    containers_ok = False

                container_results.append({
                    "key": key,
                    "container": container,
                    "state": state,
                    "health": health,
                    "ok": container_ok,
                })

            web = self._web_check()

            web_ok = (
                not web.get("configured")
                or web.get("ok") is True
            )

            ready = (
                containers_ok
                and web_ok
            )

            elapsed = round(
                time.monotonic() - started,
                2,
            )

            last = {
                "ok": ready,
                "attempts": attempts,
                "elapsed_seconds": elapsed,
                "timeout_seconds": timeout,
                "interval_seconds": interval,
                "containers": container_results,
                "web": web,
            }

            if ready:
                last["message"] = (
                    "Anwendung ist betriebsbereit."
                )
                return last

            if elapsed >= timeout:
                last["message"] = (
                    "Timeout beim Warten auf Betriebsbereitschaft "
                    "nach Rollback."
                )
                return last

            time.sleep(interval)


    def update_verify(self):
        """
        Wartet nach einem Docker-Compose-Update auf echte
        Betriebsbereitschaft.

        Ein erfolgreich gestarteter Container allein reicht nicht:
        vorhandene Docker-Healthchecks müssen healthy sein und eine
        konfigurierte Web/API muss erreichbar sein.
        """
        try:
            h = self._wait_for_compose_health(
                timeout=90,
                interval=3,
            )

            ok = bool(
                isinstance(h, dict)
                and h.get("ok") is True
            )

            return {
                "supported": True,
                "ok": ok,
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": (
                    "Anwendung ist nach Update betriebsbereit."
                    if ok
                    else
                    "Anwendung wurde nach Update nicht rechtzeitig "
                    "betriebsbereit."
                ),
                "health": h,
            }

        except Exception as e:
            return {
                "supported": True,
                "ok": False,
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": (
                    "Healthcheck nach Update fehlgeschlagen: {}"
                    .format(e)
                ),
                "error": str(e),
            }



    def update_check(self):
        """
        Docker Compose Update-Prüfung über Pull-Vergleich.

        Registry-Digests werden bewusst nicht als Entscheidung verwendet,
        da Multiarch Images (GHCR/Docker Hub) bei :latest falsche Updates
        melden können.
        """

        compose_dir = getattr(self, "compose_dir", None)

        if not compose_dir or not Path(compose_dir).exists():
            return {
                "supported": True,
                "ok": False,
                "state": "missing",
                "label": "Compose-Verzeichnis fehlt",
                "message": "Update-Prüfung nicht möglich",
                "method": "docker-compose-pull-compare",
                "update_available": None,
                "safe_to_update": False,
                "requires_backup": True,
            }


        def get_images():

            r = sh(
                "cd {} && docker compose config --images 2>/dev/null || true".format(
                    repr(compose_dir)
                ),
                timeout=30,
            )

            return [
                x.strip()
                for x in (r.get("stdout") or "").splitlines()
                if x.strip()
            ]


        def image_id(image):

            r = sh(
                "docker image inspect {} --format '{{{{.Id}}}}' 2>/dev/null || true".format(
                    repr(image)
                ),
                timeout=20,
            )

            return (r.get("stdout") or "").strip()


        def image_version(image):

            image = str(image or "").strip()

            if not image:
                return None

            r = sh(
                (
                    "docker image inspect {} "
                    "--format "
                    "'{{{{index .Config.Labels "
                    "\"org.opencontainers.image.version\"}}}}' "
                    "2>/dev/null || true"
                ).format(repr(image)),
                timeout=20,
            )

            version = (
                r.get("stdout") or ""
            ).strip()

            if not version or version == "<no value>":
                return None

            return version


        images = get_images()


        before = {}

        for img in images:
            before[img] = image_id(img)


        # Tatsächlich laufende Version unabhängig vom beweglichen
        # Compose-Tag bestimmen.
        runtime_version = self._running_image_version()

        current_version = (
            runtime_version.get("value")
            if isinstance(runtime_version, dict)
            else None
        )

        runtime_image_reference = (
            runtime_version.get("image_reference")
            if isinstance(runtime_version, dict)
            else None
        )


        pull = sh(
            "cd {} && docker compose pull --quiet".format(
                repr(compose_dir)
            ),
            timeout=300,
        )


        after = {}

        for img in images:
            after[img] = image_id(img)


        # Die verfügbare Version wird aus dem nach dem Pull
        # vorhandenen Image des primären laufenden Containers
        # gelesen.
        latest_image = None

        if (
            runtime_image_reference
            and runtime_image_reference in after
        ):
            latest_image = after.get(
                runtime_image_reference
            )

        # Fallback für Compose-Projekte mit genau einem Image.
        if not latest_image and len(images) == 1:
            latest_image = after.get(images[0])

        latest_version = image_version(
            latest_image
        )

        # Wenn das Image kein OCI-Versionslabel besitzt, aber kein
        # Update erkannt wurde, ist die tatsächlich laufende Version
        # der beste bekannte Versionsstand.
        if (
            not latest_version
            and current_version
            and all(
                before.get(img) == after.get(img)
                for img in images
            )
        ):
            latest_version = current_version


        changed = []
        results = []


        for img in images:

            old = before.get(img, "")
            new = after.get(img, "")

            different = bool(old and new and old != new)

            if different:
                changed.append(img)

            results.append({
                "image": img,
                "before": old,
                "after": new,
                "changed": different,
            })


        if changed:

            state = "available"
            label = "Update verfügbar"
            update_available = True
            message = "{} neues Image(s) verfügbar".format(
                len(changed)
            )

        else:

            state = "current"
            label = "Aktuell"
            update_available = False
            message = "Keine neuen Images verfügbar"


        return {
            "supported": True,
            "ok": True,
            "state": state,
            "label": label,
            "message": message,
            "app_id": self.app_id,
            "app_label": self.label,
            "kind": self.kind,
            "method": "docker-compose-pull-compare",
            "compose_dir": compose_dir,
            "images": images,
            "image_results": results,
            "changed_images": changed,
            "current_version": current_version,
            "latest_version": latest_version,
            "version_details": {
                "runtime": runtime_version,
                "latest_image_id": latest_image,
            },
            "update_available": update_available,
            "safe_to_update": False,
            "requires_backup": True,
        }

