# -*- coding: utf-8 -*-
import os
import gzip

def restore_test(path):
    if not path or not os.path.exists(path):
        return {"ok": False, "error": "file missing", "path": path}

    try:
        if path.endswith(".gz"):
            with gzip.open(path, "rb") as f:
                while f.read(1024 * 1024):
                    pass
        else:
            with open(path, "rb") as f:
                f.read(1024 * 1024)

        return {"ok": True, "path": path, "result": "readable"}
    except Exception as e:
        return {"ok": False, "path": path, "error": str(e)}
