#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import glob
import sqlite3
import subprocess
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "project_context.txt"

DB = ROOT / "server-manager.sqlite3"

if "SERVER_MANAGER_DB" in os.environ:
    DB = Path(os.environ["SERVER_MANAGER_DB"])

if not DB.exists():
    alt = Path("/var/lib/server-manager/server-manager.sqlite3")
    if alt.exists():
        DB = alt


def run(cmd):
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=ROOT
        )
        return r.stdout.strip()
    except Exception as e:
        return str(e)


lines = []

lines.append("=" * 70)
lines.append("Server Manager - Projektkontext")
lines.append("=" * 70)
lines.append("")
lines.append("Erstellt:")
lines.append(str(datetime.datetime.now()))
lines.append("")
lines.append("Projekt:")
lines.append(str(ROOT))
lines.append("")

############################################################

lines.append("=" * 70)
lines.append("Git")
lines.append("=" * 70)
lines.append("")

lines.append("Branch:")
lines.append(run(["git", "branch", "--show-current"]))
lines.append("")

lines.append("Commit:")
lines.append(run(["git", "rev-parse", "--short", "HEAD"]))
lines.append("")

lines.append("Status:")
lines.append(run(["git", "status", "--short"]))
lines.append("")

lines.append("Letzte Commits:")
lines.append(run(["git", "log", "--oneline", "-10"]))
lines.append("")

############################################################

lines.append("=" * 70)
lines.append("Module")
lines.append("=" * 70)
lines.append("")

mods = []

moddir = ROOT / "modules"

if moddir.exists():
    for m in sorted(moddir.iterdir()):
        if (m / "plugin.py").exists():
            mods.append(m.name)

for m in mods:
    lines.append("✓ " + m)

lines.append("")

############################################################

lines.append("=" * 70)
lines.append("Snapshots")
lines.append("=" * 70)
lines.append("")

snaps = sorted(
    glob.glob(str(ROOT / "snapshots" / "project_*.md"))
)

if snaps:
    lines.append("Neuester Snapshot:")
    lines.append(os.path.basename(snaps[-1]))
    lines.append("")

############################################################

lines.append("=" * 70)
lines.append("Migrationen")
lines.append("=" * 70)
lines.append("")

if DB.exists():
    try:
        con = sqlite3.connect(DB)
        cur = con.cursor()

        cur.execute("""
            SELECT version,name
            FROM schema_migrations
            ORDER BY version
        """)

        for r in cur.fetchall():
            lines.append("{} {}".format(r[0], r[1]))

        lines.append("")

############################################################

        lines.append("=" * 70)
        lines.append("Registrierte Module")
        lines.append("=" * 70)
        lines.append("")

        cur.execute("""
            SELECT module,status
            FROM module_registry
            ORDER BY module
        """)

        for r in cur.fetchall():
            lines.append("{}   {}".format(r[1], r[0]))

        lines.append("")

############################################################

        lines.append("=" * 70)
        lines.append("Datenbanktabellen")
        lines.append("=" * 70)
        lines.append("")

        cur.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """)

        for r in cur.fetchall():
            lines.append(r[0])

        con.close()

    except Exception as e:
        lines.append(str(e))

############################################################

lines.append("")
lines.append("=" * 70)
lines.append("Systemd")
lines.append("=" * 70)
lines.append("")

lines.append(run([
    "systemctl",
    "list-units",
    "--type=service",
    "--all"
]))

############################################################

lines.append("")
lines.append("=" * 70)
lines.append("Python")
lines.append("=" * 70)
lines.append("")

lines.append(sys.version)

############################################################

lines.append("")
lines.append("=" * 70)
lines.append("Projektstatus")
lines.append("=" * 70)
lines.append("")

ps = ROOT / "PROJECT_STATE.md"

if ps.exists():
    lines.append(ps.read_text(errors="ignore"))

############################################################

lines.append("")
lines.append("=" * 70)
lines.append("Hinweis für ChatGPT")
lines.append("=" * 70)
lines.append("")

lines.append("""
Dies ist der aktuelle Entwicklungsstand des
Server Manager.

Bitte ausschließlich auf Basis
dieses Projektes weiterentwickeln.

Projektarchitektur:

modules/<modul>/plugin.py

Python 3
Flask
SQLite

V11 ist abgelöst.

Neue Entwicklungen ausschließlich
für Manager.
""")

OUT.write_text("\n".join(lines), encoding="utf-8")

print("Projektkontext geschrieben:")
print(OUT)
