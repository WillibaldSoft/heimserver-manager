#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import subprocess
from pathlib import Path

DB = Path("/var/lib/server-manager/server-manager.sqlite3")


def git(cmd):
    try:
        return subprocess.check_output(
            ["git", "-C", "/opt/server-manager"] + cmd,
            text=True
        ).strip()
    except Exception:
        return "unbekannt"


def main():
    print("=== Server Manager Projektstatus ===")
    print()

    print("Git")
    print("  Branch :", git(["branch", "--show-current"]))
    print("  Commit :", git(["rev-parse", "--short", "HEAD"]))

    status = git(["status", "--porcelain"])
    print("  Status :", "sauber" if not status else "Änderungen vorhanden")

    print()

    if not DB.exists():
        print("Datenbank nicht gefunden:")
        print(DB)
        return

    con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row

    try:
        rows = con.execute("""
            SELECT id,name,applied_at,checksum
            FROM schema_migrations
            ORDER BY id
        """).fetchall()

        print("Migrationen")

        if not rows:
            print("  Keine Migrationen registriert.")
        else:
            for r in rows:
                print(
                    f"  {r['id']:04d}  "
                    f"{r['name']}  "
                    f"{r['applied_at']}  "
                    f"{r['checksum'] or ''}"
                )

    finally:
        con.close()


if __name__ == "__main__":
    main()
