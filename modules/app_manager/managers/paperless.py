from server_settings import app_literal as host_literal
# -*- coding: utf-8 -*-
from pathlib import Path
from .docker_compose import DockerComposeManager
from ..runner import sh

class Manager(DockerComposeManager):
    app_id = "paperless"
    label = "Paperless-ngx"
    compose_dir = host_literal('paperless', "/opt/paperless-ngx")
    web_url = host_literal('paperless', "http://127.0.0.1:8010")

    containers = {
        "webserver": "paperless-ngx",
        "postgres": "paperless-postgres",
        "redis": "paperless-redis",
    }

    config_files = {
        "compose": host_literal('paperless', "/opt/paperless-ngx/docker-compose.yml"),
    }

    paths = {
        "data": host_literal('paperless', "/srv/paperless/data"),
        "media": host_literal('paperless', "/srv/paperless/media"),
        "export": host_literal('paperless', "/srv/paperless/export"),
        "consume": host_literal('paperless', "/srv/scanner/output"),
    }

    database = {
        "type": "postgresql",
        "container": "paperless-postgres",
        "database": "paperless",
        "user": "paperless",
        "dump": "pg_dump -U paperless paperless",
    }

    image_container = "paperless-ngx"
    log_container = "paperless-ngx"
    image_grep = "paperless|gotenberg|tika"

    # Paperless enthält persistente Nutzdaten und PostgreSQL.
    # Vor einem Update deshalb immer vollständiges Backup verwenden.
    update_backup_profile = "full"


    def update_check(self):
        """
        Prüft ausschließlich das eigentliche Paperless-Image.

        PostgreSQL und Redis sind Compose-Abhängigkeiten und werden
        bewusst nicht durch eine reine Paperless-Versionsprüfung
        gepullt oder als Paperless-Update gewertet.
        """

        latest_ref = (
            "ghcr.io/paperless-ngx/"
            "paperless-ngx:latest"
        )

        running_r = sh(
            "docker inspect paperless-ngx "
            "--format '{{.Image}}' 2>/dev/null || true",
            timeout=10,
        )

        running_image_id = (
            running_r.get("stdout") or ""
        ).strip()

        def image_id(image):
            r = sh(
                "docker image inspect {} "
                "--format '{{{{.Id}}}}' "
                "2>/dev/null || true".format(
                    repr(image)
                ),
                timeout=20,
            )

            return (
                r.get("stdout") or ""
            ).strip()

        def image_version(image):
            if not image:
                return None

            r = sh(
                (
                    "docker image inspect {} "
                    "--format "
                    "'{{{{index .Config.Labels "
                    "\"org.opencontainers.image.version\"}}}}' "
                    "2>/dev/null || true"
                ).format(
                    repr(image)
                ),
                timeout=20,
            )

            value = (
                r.get("stdout") or ""
            ).strip()

            if not value or value == "<no value>":
                return None

            return value

        current_version = image_version(
            running_image_id
        )

        before_image_id = image_id(
            latest_ref
        )

        pull = sh(
            "docker pull --quiet {}".format(
                repr(latest_ref)
            ),
            timeout=300,
        )

        if pull.get("returncode") != 0:
            return {
                "supported": True,
                "ok": False,
                "state": "error",
                "label": "Prüfung fehlgeschlagen",
                "message": (
                    "Paperless-Image konnte nicht geprüft werden."
                ),
                "app_id": self.app_id,
                "app_label": self.label,
                "kind": self.kind,
                "method": "paperless-primary-image",
                "current_version": current_version,
                "latest_version": None,
                "update_available": None,
                "safe_to_update": False,
                "requires_backup": True,
                "details": {
                    "image_reference": latest_ref,
                    "running_image_id": running_image_id,
                    "before_image_id": before_image_id,
                    "pull_returncode": pull.get("returncode"),
                    "pull_stderr": pull.get("stderr"),
                },
            }

        latest_image_id = image_id(
            latest_ref
        )

        latest_version = image_version(
            latest_image_id
        )

        update_available = bool(
            running_image_id
            and latest_image_id
            and running_image_id != latest_image_id
        )

        if update_available:
            state = "available"
            label = "Update verfügbar"
            message = (
                "Paperless-ngx {} → {} ist verfügbar."
            ).format(
                current_version or "unbekannt",
                latest_version or "unbekannt",
            )
        else:
            state = "current"
            label = "Aktuell"
            message = (
                "Paperless-ngx {} ist aktuell."
            ).format(
                current_version or latest_version or "unbekannt"
            )

        return {
            "supported": True,
            "ok": True,
            "state": state,
            "label": label,
            "message": message,
            "app_id": self.app_id,
            "app_label": self.label,
            "kind": self.kind,
            "method": "paperless-primary-image",
            "current_version": current_version,
            "latest_version": latest_version,
            "update_available": update_available,
            "safe_to_update": update_available,
            "requires_backup": True,
            "images": [
                latest_ref,
            ],
            "image_results": [
                {
                    "image": latest_ref,
                    "before": before_image_id,
                    "after": latest_image_id,
                    "running": running_image_id,
                    "changed": (
                        before_image_id
                        and latest_image_id
                        and before_image_id != latest_image_id
                    ),
                    "update_available": update_available,
                }
            ],
            "changed_images": (
                [latest_ref]
                if update_available
                else []
            ),
            "details": {
                "running_image_id": running_image_id,
                "latest_image_id": latest_image_id,
                "image_channel": "latest",
                "image_reference": latest_ref,
                "pull_returncode": pull.get("returncode"),
            },
        }



    def extra_backup(self, workdir):
        out = Path(workdir)
        out.mkdir(parents=True, exist_ok=True)

        result = {}

        result["compose_ps"] = sh(
            host_literal('paperless', "cd /opt/paperless-ngx && docker compose ps --format json 2>/dev/null || true"),
            timeout=20
        )

        result["images"] = sh(
            host_literal('paperless', "cd /opt/paperless-ngx && docker compose images 2>/dev/null || true"),
            timeout=20
        )

        result["inspect_webserver"] = sh(
            "docker inspect paperless-ngx 2>/dev/null || true",
            timeout=20
        )

        result["inspect_postgres"] = sh(
            "docker inspect paperless-postgres 2>/dev/null || true",
            timeout=20
        )

        result["inspect_redis"] = sh(
            "docker inspect paperless-redis 2>/dev/null || true",
            timeout=20
        )

        (out / "compose-ps.jsonl").write_text(result["compose_ps"].get("stdout", ""), encoding="utf-8")
        (out / "compose-images.txt").write_text(result["images"].get("stdout", ""), encoding="utf-8")
        (out / "inspect-paperless-ngx.json").write_text(result["inspect_webserver"].get("stdout", ""), encoding="utf-8")
        (out / "inspect-paperless-postgres.json").write_text(result["inspect_postgres"].get("stdout", ""), encoding="utf-8")
        (out / "inspect-paperless-redis.json").write_text(result["inspect_redis"].get("stdout", ""), encoding="utf-8")

        return {
            "ok": True,
            "message": "Paperless Zusatzinformationen gesichert",
            "files": [
                str(out / "compose-ps.jsonl"),
                str(out / "compose-images.txt"),
                str(out / "inspect-paperless-ngx.json"),
                str(out / "inspect-paperless-postgres.json"),
                str(out / "inspect-paperless-redis.json"),
            ]
        }

    def stop_for_restore(self):
        from ..runner import sh
        compose_dir = getattr(self, "compose_dir", None) or host_literal('paperless', "/opt/paperless-ngx")
        r = sh("cd {} && docker compose stop".format(repr(compose_dir)), timeout=120)
        return {
            "ok": r.get("returncode") == 0,
            "changed": True,
            "method": "docker compose stop",
            "compose_dir": compose_dir,
            "returncode": r.get("returncode"),
            "stdout": r.get("stdout"),
            "stderr": r.get("stderr"),
        }

    def start_after_restore(self):
        from ..runner import sh
        compose_dir = getattr(self, "compose_dir", None) or host_literal('paperless', "/opt/paperless-ngx")
        r = sh("cd {} && docker compose up -d".format(repr(compose_dir)), timeout=180)
        return {
            "ok": r.get("returncode") == 0,
            "changed": True,
            "method": "docker compose up -d",
            "compose_dir": compose_dir,
            "returncode": r.get("returncode"),
            "stdout": r.get("stdout"),
            "stderr": r.get("stderr"),
        }


