from server_settings import app_literal as host_literal
# -*- coding: utf-8 -*-
from pathlib import Path
from .docker_compose import DockerComposeManager
from ..runner import sh

class Manager(DockerComposeManager):
    app_id = "immich"
    label = "Immich"
    compose_dir = host_literal('immich', "/opt/immich")
    web_url = "http://127.0.0.1:2283"

    containers = {
        "server": "immich_server",
        "machine_learning": "immich_machine_learning",
        "postgres": "immich_postgres",
        "redis": "immich_redis",
    }

    config_files = {
        "compose": host_literal('immich', "/opt/immich/docker-compose.yml"),
        "env": host_literal('immich', "/opt/immich/.env"),
    }

    paths = {
        "app_dir": host_literal('immich', "/opt/immich"),
    }

    database = {
        "type": "postgresql",
        "container": "immich_postgres",
        "database": "immich",
        "user": "postgres",
        "dump": "pg_dump -U postgres immich",
    }

    image_container = "immich_server"
    log_container = "immich_server"
    image_grep = "immich|postgres|redis"


    def update_check(self):
        """
        Prüft Immich über den normalen Docker-Compose-Check und ergänzt
        die tatsächlich laufende sowie die verfügbare Immich-Version.

        Für die Versionsanzeige wird ausschließlich immich_server
        ausgewertet. Updates anderer Compose-Images bleiben durch den
        generischen Docker-Compose-Check weiterhin sichtbar.
        """

        result = super().update_check()

        running_r = sh(
            "docker inspect immich_server "
            "--format '{{.Image}}' 2>/dev/null",
            timeout=10,
        )

        running_image_id = (
            running_r.get("stdout") or ""
        ).strip()

        release_ref = (
            "ghcr.io/immich-app/"
            "immich-server:release"
        )

        release_r = sh(
            "docker image inspect {} "
            "--format '{{{{.Id}}}}' 2>/dev/null".format(
                release_ref
            ),
            timeout=10,
        )

        release_image_id = (
            release_r.get("stdout") or ""
        ).strip()

        def image_version(image):
            if not image:
                return None

            r = sh(
                "docker image inspect {} "
                "--format '{{{{index .Config.Labels "
                "\"org.opencontainers.image.version\"}}}}' "
                "2>/dev/null".format(image),
                timeout=10,
            )

            value = (
                r.get("stdout") or ""
            ).strip()

            return value or None

        current_version = image_version(
            running_image_id
        )

        latest_version = image_version(
            release_image_id
        )

        details = result.get("details")

        if not isinstance(details, dict):
            details = {}

        details.update({
            "running_image_id": running_image_id,
            "release_image_id": release_image_id,
            "image_channel": "release",
            "image_reference": release_ref,
        })

        result["details"] = details
        result["current_version"] = current_version
        result["latest_version"] = latest_version

        # Das Release-Image ist bereits lokal vorhanden, aber der
        # laufende Container verwendet noch eine ältere Version.
        if (
            running_image_id
            and release_image_id
            and running_image_id != release_image_id
        ):
            result["supported"] = True
            result["ok"] = True
            result["state"] = "available"
            result["label"] = "Update verfügbar"
            result["update_available"] = True
            result["message"] = (
                "Immich {} → {} ist verfügbar."
            ).format(
                current_version or "unbekannt",
                latest_version or "unbekannt",
            )

        # Nur dann ausdrücklich auf aktuell setzen, wenn auch der
        # generische Compose-Check kein anderes Image-Update gefunden hat.
        elif (
            running_image_id
            and release_image_id
            and running_image_id == release_image_id
            and not result.get("update_available")
        ):
            result["supported"] = True
            result["ok"] = True
            result["state"] = "current"
            result["label"] = "Aktuell"
            result["update_available"] = False
            result["message"] = (
                "Immich {} ist aktuell."
            ).format(
                current_version or "unbekannt"
            )

        return result



    def extra_backup(self, workdir):
        out = Path(workdir)
        out.mkdir(parents=True, exist_ok=True)

        result = {}

        result["compose_ps"] = sh(
            host_literal('immich', "cd /opt/immich && docker compose ps --format json 2>/dev/null || true"),
            timeout=20
        )

        result["images"] = sh(
            host_literal('immich', "cd /opt/immich && docker compose images 2>/dev/null || true"),
            timeout=20
        )

        for name in ("immich_server", "immich_machine_learning", "immich_postgres", "immich_redis"):
            r = sh(f"docker inspect {name} 2>/dev/null || true", timeout=20)
            (out / f"inspect-{name}.json").write_text(r.get("stdout", ""), encoding="utf-8")
            result[f"inspect_{name}"] = {"ok": r.get("ok"), "returncode": r.get("returncode")}

        (out / "compose-ps.jsonl").write_text(result["compose_ps"].get("stdout", ""), encoding="utf-8")
        (out / "compose-images.txt").write_text(result["images"].get("stdout", ""), encoding="utf-8")

        return {
            "ok": True,
            "message": "Immich Zusatzinformationen gesichert",
            "files": [
                str(out / "compose-ps.jsonl"),
                str(out / "compose-images.txt"),
                str(out / "inspect-immich_server.json"),
                str(out / "inspect-immich_machine_learning.json"),
                str(out / "inspect-immich_postgres.json"),
                str(out / "inspect-immich_redis.json"),
            ]
        }
