# -*- coding: utf-8 -*-
import json
import os
import subprocess

from pathlib import Path
HELPER = str(Path(__file__).resolve().parents[2] / "tools/helpers/server-manager-update-helper")

def run_helper(args, timeout=14400):
    cmd = [HELPER] + list(args)
    if os.geteuid() != 0:
        cmd = ["sudo", "-n"] + cmd

    try:
        p = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout
        )
        raw = (p.stdout or "") + (p.stderr or "")
        try:
            data = json.loads((p.stdout or "{}").strip().splitlines()[-1])
        except Exception:
            data = {"ok": False, "error": raw.strip() or "Keine JSON-Ausgabe"}
        return p.returncode, data, raw
    except Exception as e:
        return 999, {"ok": False, "error": str(e)}, str(e)
