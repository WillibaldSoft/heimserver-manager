# -*- coding: utf-8 -*-
import subprocess


def run(cmd, timeout=8):
    try:
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return {"ok": p.returncode == 0, "returncode": p.returncode, "stdout": (p.stdout or '').strip(), "stderr": (p.stderr or '').strip(), "cmd": cmd}
    except Exception as e:
        return {"ok": False, "returncode": 99, "stdout": "", "stderr": str(e), "cmd": cmd}


def sh(command, timeout=8):
    return run(["bash", "-lc", command], timeout=timeout)
