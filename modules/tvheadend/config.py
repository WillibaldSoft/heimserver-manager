# -*- coding: utf-8 -*-
from pathlib import Path
import os

CONF = Path(os.environ.get("SERVER_MANAGER_CONFIG", "/etc/server-manager")) / "tvheadend.conf"

DEFAULTS = {
    "url": "http://127.0.0.1:9981",
    "username": "",
    "password": "",
    "timeout": "8",
}

def ensure_config():
    CONF.parent.mkdir(parents=True, exist_ok=True)
    if not CONF.exists():
        CONF.write_text(
            "# Tvheadend Konfiguration fuer Server Manager\n"
            "url=http://127.0.0.1:9981\n"
            "username=\n"
            "password=\n"
            "timeout=8\n",
            encoding="utf-8",
        )
        CONF.chmod(0o600)

def read_config():
    ensure_config()
    cfg = dict(DEFAULTS)
    for line in CONF.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        cfg[key.strip()] = value.strip().strip('"').strip("'")
    return cfg


def local_installation_present():
    """Installed/stopped services still need fail-closed monitoring."""
    import shutil
    import socket
    import subprocess
    if shutil.which('tvheadend'):
        return True
    for folder in ('/etc/systemd/system','/run/systemd/system','/usr/lib/systemd/system','/lib/systemd/system'):
        if (Path(folder)/'tvheadend.service').exists():return True
    # Include stopped Docker installations, not just currently listening services.
    if shutil.which('docker') and Path('/var/run/docker.sock').exists():
        try:
            result=subprocess.run(['docker','ps','--all','--format','{{.Image}} {{.Names}}'],capture_output=True,text=True,timeout=3)
            if result.returncode:return True # uncertain inventory must not remove protection
            if 'tvheadend' in result.stdout.lower():return True
        except (OSError,subprocess.TimeoutExpired):return True
    try:
        with socket.create_connection(('127.0.0.1',9981),timeout=.3):return True
    except OSError:return False


_observed_local = False

def monitoring_enabled():
    """Ignore only an untouched localhost default without installation evidence.

    Explicit endpoints/credentials always stay monitored when unreachable.
    Once observed locally, protection remains enabled until the manager restarts.
    """
    global _observed_local
    from modules.module_selection.config import tv_mode
    mode=tv_mode()
    if mode!='auto':return mode=='on'
    cfg=read_config()
    if cfg.get('url','').rstrip('/') != DEFAULTS['url'] or cfg.get('username') or cfg.get('password'):
        return True
    if _observed_local:return True
    _observed_local=local_installation_present()
    return _observed_local
