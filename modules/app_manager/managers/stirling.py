from server_settings import app_literal as host_literal
# -*- coding: utf-8 -*-
from .docker_compose import DockerComposeManager

class Manager(DockerComposeManager):
    app_id = "stirling"
    label = "Stirling PDF"
    compose_dir = host_literal('stirling', "/opt/stirling-pdf")
    web_url = "http://127.0.0.1:8085"

    # Vor einem echten Update müssen neben der Compose-Konfiguration
    # auch die persistent eingebundenen Stirling-Daten gesichert sein.
    update_backup_profile = "full"

    containers = {
        "stirling": "stirling-pdf",
    }

    config_files = {
        "compose": host_literal('stirling', "/opt/stirling-pdf/docker-compose.yml"),
        "settings": host_literal('stirling', "/opt/stirling-pdf/configs/settings.yml"),
        "custom_settings": host_literal('stirling', "/opt/stirling-pdf/configs/custom_settings.yml"),
    }

    paths = {
        "configs": host_literal('stirling', "/opt/stirling-pdf/configs"),
        "pipeline": host_literal('stirling', "/opt/stirling-pdf/pipeline"),
        "tessdata": host_literal('stirling', "/opt/stirling-pdf/tessdata"),
    }

    image_container = "stirling-pdf"
    log_container = "stirling-pdf"
    image_grep = "stirling"
