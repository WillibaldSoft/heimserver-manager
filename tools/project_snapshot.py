#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import subprocess
import datetime
from pathlib import Path

PROJECT = Path("/opt/server-manager")
DB = Path("/var/lib/server-manager/server-manager.sqlite3")
SNAPSHOTS = PROJECT / "snapshots"
STAMP = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def sh(cmd):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as e:
        return "unbekannt: " + str(e)

def git(args):
    return sh(["git", "-C", str(PROJECT)] + args)

def db_rows(sql):
    if not DB.exists():
        return []
    con = sqlite3.connect(f"file:{DB}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()

def db_schema():
    if not DB.exists():
        return "-- DB nicht gefunden\n"
    rows = db_rows("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name")
    out = []
    for r in rows:
        out.append(f"-- {r['type']}: {r['name']}")
        out.append(r["sql"].rstrip() + ";")
        out.append("")
    return "\n".join(out)

def modules():
    base = PROJECT / "modules"
    if not base.exists():
        return []
    return sorted(str(p.relative_to(PROJECT)) for p in base.glob("**/*.py") if "__pycache__" not in str(p))

def migrations():
    try:
        return db_rows("SELECT id,name,applied_at,checksum FROM schema_migrations ORDER BY id")
    except Exception:
        return []

def tables():
    try:
        return db_rows("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    except Exception:
        return []

def config_files():
    cfg = Path("/etc/server-manager")
    if not cfg.exists():
        return []
    return sorted(str(p) for p in cfg.glob("*") if p.is_file())

def render_state():
    branch = git(["branch", "--show-current"])
    commit = git(["rev-parse", "--short", "HEAD"])
    status = git(["status", "--porcelain"])
    clean = "sauber" if not status else "Änderungen vorhanden"

    mig_lines = [
        f"- `{r['id']:04d}` `{r['name']}` `{r['applied_at']}` `{r['checksum'] or ''}`"
        for r in migrations()
    ] or ["- keine Migrationen registriert"]

    module_lines = [f"- `{m}`" for m in modules()] or ["- keine Module gefunden"]
    table_lines = [f"- `{r['name']}`" for r in tables()] or ["- keine Tabellen gefunden"]
    config_lines = [f"- `{c}`" for c in config_files()] or ["- keine Konfigurationsdateien gefunden"]

    return f"""# Server Manager Projektstand

Stand: {STAMP}

## Git

| Feld | Wert |
|---|---|
| Branch | `{branch}` |
| Commit | `{commit}` |
| Arbeitsbaum | `{clean}` |

## Enthaltene Hauptfunktionen

- Core / WebUI
- Plugin-Loader
- Heimnetz
- Client-Agent
- Server-Control
- Blocker-API
- Sleep-Engine
- Sleep-Zeitpläne
- Sleep-Runtime
- TV / Tvheadend
- Tvheadend Blocker-Provider
- Tvheadend Status-Provider
- RTC-Aufnahmen

## Heimnetz

- IPv4-Anzeige
- IPv6-Anzeige
- Gerätetypen
- Benennung von Geräten
- Offline-Erkennung beim Scan
- Soft-Delete
- Übernahme als Client-Agent

## Client-Agent

- Token
- Installer-Download
- Bedarf setzen
- Bedarf löschen
- Server-Control-Blocker
- Modi: automatisch, verbunden, nur freigeben, deaktiviert

## Server-Control

- zentrale Schlafentscheidung
- Blocker-API statt direkter Modul-Synchronisation
- aktive Blocker aus Modulen
- RTC-Anzeige
- Tvheadend-Status-Provider

## Blocker-API

Aktive Provider:

- `modules.tvheadend.blocker_provider`
- `modules.heimnetz_client_blocker_provider`

## TV / Tvheadend

- API-Anbindung über `/etc/server-manager/tvheadend.conf`
- Streams
- laufende Aufnahmen
- kommende Aufnahmen
- Blocker für Streams und Aufnahmen
- Aufnahme-Vorlauf
- RTC-Planung
- Status-Provider

## Sleep-Engine

- Runtime läuft mit Webdienst
- Zeitpläne
- Dry-Run
- Automatik-Schalter
- Ausführungs-Schalter
- Aktionen: Wach, Suspend, Hibernate, Poweroff

## Migrationen

{chr(10).join(mig_lines)}

## Module

{chr(10).join(module_lines)}

## Datenbanktabellen

{chr(10).join(table_lines)}

## Konfigurationsdateien

{chr(10).join(config_lines)}

## Entwicklungsregel

Keine manuellen Funktionsänderungen ohne:

1. `python3 -m py_compile`
2. Funktionstest
3. Git-Commit
4. Migrationseintrag bei DB-Änderungen
5. Snapshot mit `tools/project_snapshot.py`
"""

def main():
    if not PROJECT.exists():
        raise SystemExit("Projekt nicht gefunden: " + str(PROJECT))
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    state = render_state()
    (PROJECT / "PROJECT_STATE.md").write_text(state, encoding="utf-8")
    (SNAPSHOTS / f"project_{STAMP}.md").write_text(state, encoding="utf-8")
    (SNAPSHOTS / f"schema_{STAMP}.sql").write_text(db_schema(), encoding="utf-8")
    print("Projekt-Snapshot erstellt.")
    print("PROJECT_STATE.md")
    print(SNAPSHOTS / f"project_{STAMP}.md")
    print(SNAPSHOTS / f"schema_{STAMP}.sql")

if __name__ == "__main__":
    main()
