from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-

from modules.module_selection.config import network_enabled
import datetime
import json
import threading
import time
import traceback

from flask import Response, redirect, request

from modules.heimnetz_clients import (
    _parallel_ping_ipv4,
    _scan_neigh_family,
    expire_stale_agents,
    expire_stale_network_devices,
    presence_discovery_scan,
    set_home_client_online,
    sync_agent_states_to_home,
)


_STARTED = False
_START_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
_ACTION_LOCK = threading.Lock()
_WAKE_EVENT = threading.Event()

_RUNTIME = {
    "started": False,
    "thread_alive": False,
    "started_at": "",
    "last_tick_at": "",
    "last_error_at": "",
    "last_error": "",
    "tick_count": 0,
    "scan_running": False,
    "last_scan_at": "",
    "last_scan_type": "",
    "last_scan_checked": 0,
    "last_scan_online": 0,
    "last_scan_failed": 0,
    "full_scan_running": False,
    "last_full_scan_at": "",
    "last_full_scan_status": "",
    "last_full_scan_discovered": 0,
    "last_full_scan_error": "",
    "manual_job_pending": False,
    "manual_job_type": "",
    "manual_job_requested_at": "",
}


SCAN_CLASSES = (
    "infrastructure",
    "standard",
    "mobile",
    "disabled",
)


DEFAULT_SETTINGS = {
    "presence_engine_enabled": "1",
    "presence_tick_seconds": "5",
    "presence_infrastructure_interval_seconds": "120",
    "presence_standard_interval_seconds": "300",
    "presence_mobile_interval_seconds": "600",
    "presence_full_scan_interval_seconds": "3600",
    "presence_ipv6_interval_seconds": "1800",
    "presence_full_scan_on_start": "1",
    "presence_max_workers": "32",
}



PRESENCE_SETTING_LABELS = {
    "presence_engine_enabled": "Presence Engine aktiv",
    "presence_tick_seconds": "Scheduler-Takt",
    "presence_infrastructure_interval_seconds": "Infrastruktur-Prüfung",
    "presence_standard_interval_seconds": "Standardgeräte-Prüfung",
    "presence_mobile_interval_seconds": "Mobilgeräte-Prüfung",
    "presence_full_scan_interval_seconds": "Discovery-Vollscan",
    "presence_ipv6_interval_seconds": "IPv6-Aktualisierung",
    "presence_full_scan_on_start": "Vollscan beim Dienststart",
    "presence_max_workers": "Maximale parallele Prüfungen",
}


def _form_int(form, name, default, minimum, maximum):
    raw = str(form.get(name) or "").strip()

    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = int(default)

    return max(
        int(minimum),
        min(int(maximum), value),
    )


def _seconds_to_minutes(value, default):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = int(default)

    return max(
        1,
        int(round(seconds / 60)),
    )


def _setting_status_rows(settings):
    def enabled(key, default="0"):
        value = str(
            settings.get(key, default)
        ).strip().lower()

        return (
            "aktiv"
            if value in ("1", "true", "yes", "ja", "on")
            else "deaktiviert"
        )

    def seconds(key, default):
        try:
            value = int(settings.get(key, default))
        except (TypeError, ValueError):
            value = int(default)

        return "{} Sekunden".format(value)

    def minutes(key, default):
        try:
            value = int(settings.get(key, default))
        except (TypeError, ValueError):
            value = int(default)

        minute_value = max(
            1,
            int(round(value / 60)),
        )

        return "{} Minute{}".format(
            minute_value,
            "" if minute_value == 1 else "n",
        )

    return (
        (
            "Presence Engine",
            enabled("presence_engine_enabled", "1"),
        ),
        (
            "Scheduler-Takt",
            seconds("presence_tick_seconds", 5),
        ),
        (
            "Infrastruktur prüfen",
            minutes(
                "presence_infrastructure_interval_seconds",
                120,
            ),
        ),
        (
            "Standardgeräte prüfen",
            minutes(
                "presence_standard_interval_seconds",
                300,
            ),
        ),
        (
            "Mobile Geräte prüfen",
            minutes(
                "presence_mobile_interval_seconds",
                600,
            ),
        ),
        (
            "Discovery-Vollscan",
            minutes(
                "presence_full_scan_interval_seconds",
                3600,
            ),
        ),
        (
            "IPv6-Aktualisierung",
            minutes(
                "presence_ipv6_interval_seconds",
                1800,
            ),
        ),
        (
            "Vollscan beim Dienststart",
            enabled("presence_full_scan_on_start", "1"),
        ),
        (
            "Parallele Prüfungen",
            str(settings.get("presence_max_workers", "32")),
        ),
        (
            "Globale Offline-Mindestfrist",
            seconds(
                "network_offline_timeout_seconds",
                300,
            ),
        ),
    )


def _save_presence_settings(con, form):
    values = {
        "presence_engine_enabled": (
            "1"
            if form.get("presence_engine_enabled")
            else "0"
        ),
        "presence_full_scan_on_start": (
            "1"
            if form.get("presence_full_scan_on_start")
            else "0"
        ),
        "presence_tick_seconds": str(
            _form_int(
                form,
                "presence_tick_seconds",
                5,
                2,
                300,
            )
        ),
        "presence_infrastructure_interval_seconds": str(
            _form_int(
                form,
                "presence_infrastructure_interval_minutes",
                2,
                1,
                1440,
            ) * 60
        ),
        "presence_standard_interval_seconds": str(
            _form_int(
                form,
                "presence_standard_interval_minutes",
                5,
                1,
                1440,
            ) * 60
        ),
        "presence_mobile_interval_seconds": str(
            _form_int(
                form,
                "presence_mobile_interval_minutes",
                10,
                1,
                1440,
            ) * 60
        ),
        "presence_full_scan_interval_seconds": str(
            _form_int(
                form,
                "presence_full_scan_interval_minutes",
                60,
                5,
                10080,
            ) * 60
        ),
        "presence_ipv6_interval_seconds": str(
            _form_int(
                form,
                "presence_ipv6_interval_minutes",
                30,
                5,
                10080,
            ) * 60
        ),
        "presence_max_workers": str(
            _form_int(
                form,
                "presence_max_workers",
                32,
                1,
                64,
            )
        ),
        "network_offline_timeout_seconds": str(
            _form_int(
                form,
                "network_offline_timeout_seconds",
                300,
                60,
                86400,
            )
        ),
    }

    for key, value in values.items():
        con.execute("""
            INSERT INTO heimnetz_settings(
                key,
                value
            )
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value
        """, (
            key,
            value,
        ))

    con.commit()
    return values


def _restore_presence_defaults(con):
    for key, value in DEFAULT_SETTINGS.items():
        con.execute("""
            INSERT INTO heimnetz_settings(
                key,
                value
            )
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value
        """, (
            key,
            value,
        ))

    con.commit()


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _setting(con, key, default=""):
    row = con.execute(
        "SELECT value FROM heimnetz_settings WHERE key=?",
        (str(key),),
    ).fetchone()

    if not row:
        return default

    return str(row["value"] or default)


def _setting_int(con, key, default, minimum=1, maximum=86400):
    try:
        value = int(_setting(con, key, str(default)))
    except (TypeError, ValueError):
        value = int(default)

    return max(minimum, min(maximum, value))


def _setting_bool(con, key, default=False):
    if key=="presence_engine_enabled" and not network_enabled():return False
    raw = _setting(
        con,
        key,
        "1" if default else "0",
    ).strip().lower()

    return raw in (
        "1",
        "true",
        "yes",
        "ja",
        "on",
    )


def ensure_schema(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS heimnetz_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    for key, value in DEFAULT_SETTINGS.items():
        con.execute("""
            INSERT OR IGNORE INTO heimnetz_settings(key, value)
            VALUES(?, ?)
        """, (
            key,
            value,
        ))

    columns = {
        row["name"]
        for row in con.execute(
            "PRAGMA table_info(home_clients)"
        ).fetchall()
    }

    wanted = {
        "scan_class": "TEXT DEFAULT 'standard'",
        "last_probe_at": "TEXT",
        "last_probe_success": "TEXT",
        "last_ipv4_seen": "TEXT",
        "last_ipv6_seen": "TEXT",
        "next_probe_at": "TEXT",
        "probe_failures": "INTEGER DEFAULT 0",
        "probe_error": "TEXT DEFAULT ''",
        "always_online": "INTEGER DEFAULT 0",
    }

    for name, definition in wanted.items():
        if name not in columns:
            con.execute(
                f"ALTER TABLE home_clients "
                f"ADD COLUMN {name} {definition}"
            )

    con.execute("""
        CREATE TABLE IF NOT EXISTS presence_runtime (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (
                datetime('now','localtime')
            )
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS presence_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_type TEXT NOT NULL,
            scan_class TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            checked_count INTEGER DEFAULT 0,
            online_count INTEGER DEFAULT 0,
            offline_count INTEGER DEFAULT 0,
            discovered_count INTEGER DEFAULT 0,
            error TEXT,
            details TEXT
        )
    """)

    con.commit()


def suggested_scan_class(device_type):
    device_type = str(device_type or "").strip()

    if device_type in (
        "Fritzbox",
        "Router",
        "Repeater",
        "Switch",
        "Access Point",
        "Server",
        "NAS",
        "Home Assistant",
    ):
        return "infrastructure"

    if device_type in (
        "Smartphone",
        "Tablet",
        "Laptop",
        "Notebook",
    ):
        return "mobile"

    return "standard"


def migrate_scan_classes(con):
    ensure_schema(con)

    rows = con.execute("""
        SELECT id, device_type, scan_class
          FROM home_clients
         WHERE COALESCE(deleted,0)=0
    """).fetchall()

    updated = 0

    for row in rows:
        current = str(row["scan_class"] or "").strip()

        if current in SCAN_CLASSES:
            continue

        scan_class = suggested_scan_class(
            row["device_type"]
        )

        con.execute("""
            UPDATE home_clients
               SET scan_class=?
             WHERE id=?
        """, (
            scan_class,
            row["id"],
        ))

        updated += 1

    con.commit()
    return updated



def _scan_class_interval(con, scan_class):
    settings = {
        "infrastructure": (
            "presence_infrastructure_interval_seconds",
            120,
        ),
        "standard": (
            "presence_standard_interval_seconds",
            300,
        ),
        "mobile": (
            "presence_mobile_interval_seconds",
            600,
        ),
    }

    key, default = settings.get(
        scan_class,
        (
            "presence_standard_interval_seconds",
            300,
        ),
    )

    return _setting_int(
        con,
        key,
        default,
        minimum=30,
        maximum=86400,
    )


def _due_devices(con, scan_class):
    return con.execute("""
        SELECT
            h.id,
            h.display_name,
            h.name,
            h.hostname,
            h.ipv4,
            h.ip,
            h.mac,
            h.scan_class,
            h.is_online,
            h.last_seen,
            h.last_probe_at,
            h.last_probe_success,
            h.next_probe_at,
            h.probe_failures,
            h.always_online
          FROM home_clients h
         WHERE COALESCE(h.deleted,0)=0
           AND COALESCE(h.ignored,0)=0
           AND COALESCE(NULLIF(h.scan_class,''),'standard')=?
           AND COALESCE(NULLIF(h.ipv4,''),'')<>''
           AND (
                h.next_probe_at IS NULL
                OR h.next_probe_at=''
                OR h.next_probe_at <= datetime('now','localtime')
           )
           AND NOT EXISTS (
                SELECT 1
                  FROM client_agents a
                 WHERE a.home_client_id=h.id
           )
         ORDER BY h.id
    """, (scan_class,)).fetchall()


def _start_run(con, run_type, scan_class):
    cursor = con.execute("""
        INSERT INTO presence_runs(
            run_type,
            scan_class,
            started_at,
            status
        )
        VALUES(
            ?,
            ?,
            datetime('now','localtime'),
            'running'
        )
    """, (
        run_type,
        scan_class,
    ))

    con.commit()
    return cursor.lastrowid


def _finish_run(
    con,
    run_id,
    status,
    checked_count,
    online_count,
    offline_count,
    error="",
    details="",
):
    con.execute("""
        UPDATE presence_runs
           SET finished_at=datetime('now','localtime'),
               status=?,
               checked_count=?,
               online_count=?,
               offline_count=?,
               error=?,
               details=?
         WHERE id=?
    """, (
        status,
        int(checked_count),
        int(online_count),
        int(offline_count),
        str(error or ""),
        str(details or ""),
        run_id,
    ))

    con.commit()


def _schedule_next_probe(con, home_client_id, interval_seconds):
    con.execute("""
        UPDATE home_clients
           SET next_probe_at=datetime(
               'now',
               'localtime',
               printf('+%d seconds', ?)
           )
         WHERE id=?
    """, (
        int(interval_seconds),
        home_client_id,
    ))


def _probe_scan_class(con, scan_class, max_workers):
    rows = _due_devices(
        con,
        scan_class,
    )

    if not rows:
        return {
            "scan_class": scan_class,
            "checked": 0,
            "online": 0,
            "failed": 0,
        }

    interval_seconds = _scan_class_interval(
        con,
        scan_class,
    )

    run_id = _start_run(
        con,
        "known-devices",
        scan_class,
    )

    checked = len(rows)
    online_count = 0
    failed_count = 0

    addresses = {
        str(row["ipv4"]).strip()
        for row in rows
        if str(row["ipv4"] or "").strip()
    }

    try:
        reachable = _parallel_ping_ipv4(
            addresses,
            max_workers=max_workers,
        )

        # A ping proves IP reachability, not the identity of every saved device
        # that previously used that address. Read neighbors after the probes.
        observed = {}
        for neighbor in _scan_neigh_family('-4', reachable):
            address = neighbor.get('ipv4')
            mac = str(neighbor.get('mac') or '').lower()
            if address in reachable and mac:
                observed.setdefault(address, set()).add(mac)
        now_value = _now()

        for row in rows:
            address = str(
                row["ipv4"] or ""
            ).strip()

            mac = str(row['mac'] or '').strip().lower()
            identities = observed.get(address, set())
            success = address in reachable and bool(mac) and identities == {mac}
            mismatch = address in reachable and len(identities) == 1 and bool(mac) and mac not in identities
            identity_unknown = address in reachable and not success and not mismatch

            if success:
                set_home_client_online(
                    con,
                    row["id"],
                    True,
                    "presence-mac",
                    ip=address,
                    mac=row["mac"],
                    last_seen=now_value,
                )

                con.execute("""
                    UPDATE home_clients
                       SET last_probe_at=?,
                           last_probe_success=?,
                           last_ipv4_seen=?,
                           probe_failures=0,
                           probe_error=''
                     WHERE id=?
                """, (
                    now_value,
                    now_value,
                    now_value,
                    row["id"],
                ))

                online_count += 1

            else:
                error = ('IP antwortet mit anderer MAC; gespeicherte Zuordnung ist nicht bestätigt'
                         if mismatch else 'IP erreichbar, MAC-Zuordnung nicht eindeutig bestätigt'
                         if identity_unknown else 'Keine IPv4-Antwort')
                if mismatch:
                    # Invalidate the old IPv4 proof immediately, not the device,
                    # its address history, agent settings or user-defined name.
                    con.execute("UPDATE home_clients SET is_online=0,source='presence-mac-mismatch' WHERE id=?", (row['id'],))
                con.execute("""
                    UPDATE home_clients
                       SET last_probe_at=?,
                           probe_failures=
                               COALESCE(probe_failures,0)+1,
                           probe_error=?
                     WHERE id=?
                """, (
                    now_value,
                    error,
                    row["id"],
                ))

                failed_count += 1

            _schedule_next_probe(
                con,
                row["id"],
                interval_seconds,
            )

        con.commit()

        _finish_run(
            con,
            run_id,
            "ok",
            checked,
            online_count,
            failed_count,
            details=(
                "Intervall {} Sekunden"
            ).format(interval_seconds),
        )

        return {
            "scan_class": scan_class,
            "checked": checked,
            "online": online_count,
            "failed": failed_count,
        }

    except Exception as exc:
        _finish_run(
            con,
            run_id,
            "error",
            checked,
            online_count,
            failed_count,
            error=(
                "{}: {}"
            ).format(
                type(exc).__name__,
                exc,
            ),
        )

        raise


def run_due_known_device_scans(con):
    if not _setting_bool(
        con,
        "presence_engine_enabled",
        True,
    ):
        return {
            "enabled": False,
            "checked": 0,
            "online": 0,
            "failed": 0,
            "classes": [],
        }

    if not _RUN_LOCK.acquire(blocking=False):
        return {
            "enabled": True,
            "skipped": True,
            "reason": "scan already running",
            "checked": 0,
            "online": 0,
            "failed": 0,
            "classes": [],
        }

    _RUNTIME["scan_running"] = True

    try:
        max_workers = _setting_int(
            con,
            "presence_max_workers",
            32,
            minimum=1,
            maximum=64,
        )

        results = []

        for scan_class in (
            "infrastructure",
            "standard",
            "mobile",
        ):
            result = _probe_scan_class(
                con,
                scan_class,
                max_workers=max_workers,
            )
            results.append(result)

        # Agentenstatus bleibt gegenüber allen Netzwerkscans maßgeblich.
        expire_stale_agents(con)
        expire_stale_network_devices(con)
        sync_agent_states_to_home(con)

        con.commit()

        checked = sum(
            item["checked"]
            for item in results
        )
        online = sum(
            item["online"]
            for item in results
        )
        failed = sum(
            item["failed"]
            for item in results
        )

        # Leere Scheduler-Ticks dürfen das letzte echte Scanergebnis
        # nicht wieder mit Nullen überschreiben.
        if checked > 0:
            _RUNTIME["last_scan_at"] = _now()
            _RUNTIME["last_scan_type"] = "known-devices"
            _RUNTIME["last_scan_checked"] = checked
            _RUNTIME["last_scan_online"] = online
            _RUNTIME["last_scan_failed"] = failed

        return {
            "enabled": True,
            "checked": checked,
            "online": online,
            "failed": failed,
            "classes": results,
        }

    finally:
        _RUNTIME["scan_running"] = False
        _RUN_LOCK.release()



def _parse_timestamp(value):
    value = str(value or "").strip()

    if not value:
        return None

    # presence_runtime-Werte können als JSON-String gespeichert sein.
    try:
        decoded = json.loads(value)

        if isinstance(decoded, str):
            value = decoded
    except Exception:
        pass

    try:
        return datetime.datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S",
        )
    except (TypeError, ValueError):
        return None


def _runtime_value(con, key, default=""):
    row = con.execute("""
        SELECT value
          FROM presence_runtime
         WHERE key=?
    """, (str(key),)).fetchone()

    if not row:
        return default

    return row["value"]


def _full_scan_interval(con):
    return _setting_int(
        con,
        "presence_full_scan_interval_seconds",
        3600,
        minimum=300,
        maximum=604800,
    )


def _full_scan_due(con, startup=False):
    if not _setting_bool(
        con,
        "presence_engine_enabled",
        True,
    ):
        return False

    if startup and _setting_bool(
        con,
        "presence_full_scan_on_start",
        True,
    ):
        return True

    last_value = _runtime_value(
        con,
        "presence_last_full_scan_success",
        "",
    )

    last_scan = _parse_timestamp(last_value)

    if last_scan is None:
        return True

    interval = _full_scan_interval(con)

    return (
        datetime.datetime.now() - last_scan
    ).total_seconds() >= interval


def _start_discovery_run(con, reason):
    cursor = con.execute("""
        INSERT INTO presence_runs(
            run_type,
            scan_class,
            started_at,
            status,
            details
        )
        VALUES(
            'full-discovery',
            NULL,
            datetime('now','localtime'),
            'running',
            ?
        )
    """, (
        "Auslöser: {}".format(reason),
    ))

    con.commit()
    return cursor.lastrowid


def _finish_discovery_run(
    con,
    run_id,
    status,
    checked_count=0,
    online_count=0,
    discovered_count=0,
    error="",
    details="",
):
    con.execute("""
        UPDATE presence_runs
           SET finished_at=datetime('now','localtime'),
               status=?,
               checked_count=?,
               online_count=?,
               discovered_count=?,
               error=?,
               details=?
         WHERE id=?
    """, (
        str(status),
        int(checked_count),
        int(online_count),
        int(discovered_count),
        str(error or ""),
        str(details or ""),
        run_id,
    ))

    con.commit()


def run_full_discovery(ctx, reason="scheduled"):
    if not network_enabled():return {"ok":False,"skipped":True,"reason":"module disabled"}
    """
    Führt den vollständigen LAN-Discovery-Scan aus.

    Die vorhandene Heimnetzlogik übernimmt:
    - IPv4-Sweep
    - IPv4-/IPv6-Zusammenführung nach MAC
    - Herstellerermittlung
    - Aufnahme neuer Geräte
    - Aktualisierung vorhandener Geräte
    - Vorrang der Client-Agenten
    """
    if not _RUN_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "skipped": True,
            "reason": "scan already running",
        }

    _RUNTIME["full_scan_running"] = True
    run_id = None

    try:
        con = ctx.db()

        try:
            ensure_schema(con)

            before_count = con.execute("""
                SELECT COUNT(*) AS count
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=0
            """).fetchone()["count"]

            run_id = _start_discovery_run(
                con,
                reason,
            )

            interval = _full_scan_interval(con)

        finally:
            con.close()

        # Öffnet intern eine eigene DB-Verbindung. Der Presence-Manager hält
        # währenddessen bewusst keine SQLite-Verbindung offen.
        presence_discovery_scan(ctx)

        con = ctx.db()

        try:
            ensure_schema(con)

            after_count = con.execute("""
                SELECT COUNT(*) AS count
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=0
            """).fetchone()["count"]

            online_count = con.execute("""
                SELECT COUNT(*) AS count
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=0
                   AND COALESCE(is_online,0)=1
            """).fetchone()["count"]

            discovered = max(
                0,
                int(after_count) - int(before_count),
            )

            finished_at = _now()

            _set_runtime_value(
                con,
                "presence_last_full_scan_success",
                finished_at,
            )

            _finish_discovery_run(
                con,
                run_id,
                "ok",
                checked_count=after_count,
                online_count=online_count,
                discovered_count=discovered,
                details=(
                    "Auslöser: {}; Intervall: {} Sekunden"
                ).format(
                    reason,
                    interval,
                ),
            )

            _RUNTIME["last_full_scan_at"] = finished_at
            _RUNTIME["last_full_scan_status"] = "ok"
            _RUNTIME["last_full_scan_discovered"] = discovered
            _RUNTIME["last_full_scan_error"] = ""

            # Der Vollscan ist gleichzeitig der letzte Netzwerk-Scan.
            _RUNTIME["last_scan_at"] = finished_at
            _RUNTIME["last_scan_type"] = "full-discovery"
            _RUNTIME["last_scan_checked"] = int(after_count)
            _RUNTIME["last_scan_online"] = int(online_count)
            _RUNTIME["last_scan_failed"] = 0

            _record_runtime_snapshot(con)

            return {
                "ok": True,
                "reason": reason,
                "checked": int(after_count),
                "online": int(online_count),
                "discovered": discovered,
            }

        finally:
            con.close()

    except Exception as exc:
        error = "{}: {}".format(
            type(exc).__name__,
            exc,
        )

        _RUNTIME["last_full_scan_at"] = _now()
        _RUNTIME["last_full_scan_status"] = "error"
        _RUNTIME["last_full_scan_error"] = error

        try:
            con = ctx.db()

            try:
                ensure_schema(con)

                if run_id is not None:
                    _finish_discovery_run(
                        con,
                        run_id,
                        "error",
                        error=error,
                        details="Auslöser: {}".format(reason),
                    )

                _record_runtime_snapshot(con)

            finally:
                con.close()

        except Exception:
            traceback.print_exc()

        raise

    finally:
        _RUNTIME["full_scan_running"] = False
        _RUN_LOCK.release()



def _duration_seconds(started_at, finished_at):
    started = _parse_timestamp(started_at)
    finished = _parse_timestamp(finished_at)

    if started is None or finished is None:
        return None

    return max(
        0,
        int((finished - started).total_seconds()),
    )


def _format_duration(started_at, finished_at):
    seconds = _duration_seconds(
        started_at,
        finished_at,
    )

    if seconds is None:
        return "-"

    if seconds < 60:
        return "{} s".format(seconds)

    minutes, seconds = divmod(seconds, 60)

    if minutes < 60:
        return "{} min {} s".format(
            minutes,
            seconds,
        )

    hours, minutes = divmod(minutes, 60)

    return "{} h {} min".format(
        hours,
        minutes,
    )


def _next_full_scan_at(con):
    last_value = _runtime_value(
        con,
        "presence_last_full_scan_success",
        "",
    )
    last_scan = _parse_timestamp(last_value)

    if last_scan is None:
        return "sofort fällig"

    interval = _full_scan_interval(con)
    next_scan = last_scan + datetime.timedelta(
        seconds=interval,
    )

    return next_scan.strftime(
        "%Y-%m-%d %H:%M:%S",
    )


def _manual_full_scan_worker(ctx):
    try:
        run_full_discovery(
            ctx,
            reason="manual",
        )
    except Exception:
        traceback.print_exc()
    finally:
        with _ACTION_LOCK:
            _RUNTIME["manual_job_pending"] = False
            _RUNTIME["manual_job_type"] = ""


def _manual_known_scan_worker(ctx):
    con = None

    try:
        con = ctx.db()
        ensure_schema(con)

        # Alle automatisch überwachten Netzwerkgeräte sofort fällig machen.
        # Client-Agent-Geräte bleiben von Pingprüfungen ausgeschlossen.
        con.execute("""
            UPDATE home_clients
               SET next_probe_at=NULL
             WHERE COALESCE(deleted,0)=0
               AND COALESCE(ignored,0)=0
               AND COALESCE(
                    NULLIF(scan_class,''),
                    'standard'
               ) IN (
                    'infrastructure',
                    'standard',
                    'mobile'
               )
               AND NOT EXISTS (
                    SELECT 1
                      FROM client_agents a
                     WHERE a.home_client_id=home_clients.id
               )
        """)
        con.commit()

        run_due_known_device_scans(con)

    except Exception:
        traceback.print_exc()

    finally:
        if con is not None:
            con.close()

        with _ACTION_LOCK:
            _RUNTIME["manual_job_pending"] = False
            _RUNTIME["manual_job_type"] = ""


def start_manual_job(ctx, job_type):
    if not network_enabled():return False,"Heimnetz ist in der Modulauswahl deaktiviert."
    with _ACTION_LOCK:
        if (
            _RUNTIME.get("manual_job_pending")
            or _RUNTIME.get("scan_running")
            or _RUNTIME.get("full_scan_running")
            or _RUN_LOCK.locked()
        ):
            return False, "Es läuft bereits eine Presence-Prüfung."

        if job_type == "full-discovery":
            target = _manual_full_scan_worker
        elif job_type == "known-devices":
            target = _manual_known_scan_worker
        else:
            return False, "Unbekannte Aktion."

        _RUNTIME["manual_job_pending"] = True
        _RUNTIME["manual_job_type"] = job_type
        _RUNTIME["manual_job_requested_at"] = _now()

        thread = threading.Thread(
            target=target,
            args=(ctx,),
            name="server-manager-presence-manual-{}".format(
                job_type,
            ),
            daemon=True,
        )
        thread.start()

    return True, "Prüfung wurde im Hintergrund gestartet."


def _set_runtime_value(con, key, value):
    con.execute("""
        INSERT INTO presence_runtime(
            key,
            value,
            updated_at
        )
        VALUES(
            ?,
            ?,
            datetime('now','localtime')
        )
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value,
            updated_at=excluded.updated_at
    """, (
        str(key),
        str(value),
    ))


def _record_runtime_snapshot(con):
    for key, value in _RUNTIME.items():
        _set_runtime_value(
            con,
            key,
            json.dumps(
                value,
                ensure_ascii=False,
            ),
        )

    con.commit()


def engine_status(ctx):
    con = ctx.db()

    try:
        ensure_schema(con)

        settings = {
            row["key"]: row["value"]
            for row in con.execute("""
                SELECT key, value
                  FROM heimnetz_settings
                 WHERE key LIKE 'presence_%'
                 ORDER BY key
            """).fetchall()
        }

        class_counts = {
            row["scan_class"]: row["count"]
            for row in con.execute("""
                SELECT
                    COALESCE(
                        NULLIF(scan_class,''),
                        'standard'
                    ) AS scan_class,
                    COUNT(*) AS count
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=0
                 GROUP BY
                    COALESCE(
                        NULLIF(scan_class,''),
                        'standard'
                    )
                 ORDER BY scan_class
            """).fetchall()
        }

        last_runs = [
            dict(row)
            for row in con.execute("""
                SELECT *
                  FROM presence_runs
                 ORDER BY id DESC
                 LIMIT 10
            """).fetchall()
        ]

        runtime = dict(_RUNTIME)
        runtime["next_full_scan_at"] = _next_full_scan_at(
            con
        )

        return {
            "runtime": runtime,
            "settings": settings,
            "class_counts": class_counts,
            "last_runs": last_runs,
        }

    finally:
        con.close()


def _loop(ctx):
    _RUNTIME["started"] = True
    _RUNTIME["thread_alive"] = True
    _RUNTIME["started_at"] = _now()

    first_run = True

    while True:
        run_full_scan = False
        full_scan_reason = "scheduled"

        try:
            con = ctx.db()

            try:
                ensure_schema(con)

                startup_tick = first_run

                if first_run:
                    migrate_scan_classes(con)
                    first_run = False

                _RUNTIME["last_tick_at"] = _now()
                _RUNTIME["tick_count"] += 1
                _RUNTIME["last_error"] = ""

                # Bekannte und fällige Geräte gemäß Scan-Klasse prüfen.
                run_due_known_device_scans(con)

                # Nur entscheiden, ob ein Discovery-Vollscan fällig ist.
                # Der Scan selbst läuft erst nach dem Schließen dieser
                # SQLite-Verbindung.
                run_full_scan = _full_scan_due(
                    con,
                    startup=startup_tick,
                )

                if startup_tick:
                    full_scan_reason = "startup"

                _record_runtime_snapshot(con)

                tick_seconds = _setting_int(
                    con,
                    "presence_tick_seconds",
                    5,
                    minimum=2,
                    maximum=300,
                )

            finally:
                con.close()

            if run_full_scan:
                run_full_discovery(
                    ctx,
                    reason=full_scan_reason,
                )

        except Exception as exc:
            _RUNTIME["last_error_at"] = _now()
            _RUNTIME["last_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

            try:
                con = ctx.db()

                try:
                    ensure_schema(con)
                    _record_runtime_snapshot(con)
                finally:
                    con.close()

            except Exception:
                traceback.print_exc()

            tick_seconds = 10

        _WAKE_EVENT.wait(timeout=tick_seconds)
        _WAKE_EVENT.clear()

def start(ctx):
    global _STARTED

    with _START_LOCK:
        if _STARTED:
            return False

        _STARTED = True

        thread = threading.Thread(
            target=_loop,
            args=(ctx,),
            name="server-manager-presence",
            daemon=True,
        )
        thread.start()

        return True


def register(app, ctx):
    con = ctx.db()

    try:
        ensure_schema(con)
        migrate_scan_classes(con)
    finally:
        con.close()

    start(ctx)

    @app.route("/api/presence/status")
    def api_presence_status():
        return Response(
            json.dumps(
                {
                    "ok": True,
                    **engine_status(ctx),
                },
                ensure_ascii=False,
                indent=2,
            ),
            mimetype="application/json",
        )

    @app.route("/presence/actions", methods=["POST"])
    def presence_actions():
        action = str(
            request.form.get("action") or ""
        ).strip()

        mapping = {
            "full-discovery": "full-discovery",
            "known-devices": "known-devices",
        }

        job_type = mapping.get(action)

        if not job_type:
            return redirect(
                "/presence/status?msg=Unbekannte+Aktion"
            )

        ok, message = start_manual_job(
            ctx,
            job_type,
        )

        prefix = "OK: " if ok else "Hinweis: "

        from urllib.parse import quote_plus

        return redirect(
            "/presence/status?msg={}".format(
                quote_plus(prefix + message)
            )
        )

    @app.route("/presence/settings", methods=["GET", "POST"])
    def presence_settings():
        message = str(
            request.args.get("msg") or ""
        ).strip()

        con = ctx.db()

        try:
            ensure_schema(con)

            if request.method == "POST":
                action = str(
                    request.form.get("action") or "save"
                ).strip()

                if action == "restore-defaults":
                    _restore_presence_defaults(con)
                    message = "Standardwerte wurden wiederhergestellt."
                else:
                    _save_presence_settings(
                        con,
                        request.form,
                    )
                    message = "Presence-Einstellungen wurden gespeichert."

                # Der Scheduler übernimmt geänderte Werte sofort.
                _WAKE_EVENT.set()

                from urllib.parse import quote_plus

                return redirect(
                    "/presence/settings?msg={}".format(
                        quote_plus(message)
                    )
                )

            settings = {
                row["key"]: row["value"]
                for row in con.execute("""
                    SELECT key, value
                      FROM heimnetz_settings
                     WHERE key LIKE 'presence_%'
                     ORDER BY key
                """).fetchall()
            }

        finally:
            con.close()

        def checked(key, default="0"):
            value = str(
                settings.get(key, default)
            ).strip().lower()

            return (
                " checked"
                if value in (
                    "1",
                    "true",
                    "yes",
                    "ja",
                    "on",
                )
                else ""
            )

        body = _ui_html("<div class='card'><h2>Presence-Einstellungen</h2>")
        body += (
            _ui_html("<p>Hier werden die Prüfintervalle der zentralen "
            "Heimnetzüberwachung festgelegt. Änderungen werden ohne "
            "Dienstneustart übernommen.</p>")
        )

        if message:
            body += _ui_html("<p><b>{}</b></p>").format(
                ctx.esc(_ui_text(message))
            )

        body += _ui_html("</div>")

        body += (
            _ui_html("<form method='post' action='/presence/settings'>"
            "<input type='hidden' name='action' value='save'>")
        )

        body += _ui_html("<div class='card'><h3>Allgemein</h3>")

        body += (
            _ui_html("<p><label>"
            "<input type='checkbox' "
            "name='presence_engine_enabled'{}> "
            "<b>Presence Engine aktiv</b>"
            "</label><br>"
            "<small>Aktiviert die automatische Prüfung bekannter Geräte "
            "und die geplanten Discovery-Läufe.</small></p>")
        ).format(
            checked(
                "presence_engine_enabled",
                "1",
            )
        )

        body += (
            _ui_html("<p><label>"
            "<input type='checkbox' "
            "name='presence_full_scan_on_start'{}> "
            "<b>Discovery-Vollscan beim Dienststart</b>"
            "</label><br>"
            "<small>Startet nach jedem Neustart des Server-Managers "
            "einen vollständigen Netzwerkscan.</small></p>")
        ).format(
            checked(
                "presence_full_scan_on_start",
                "1",
            )
        )

        body += (
            _ui_html("<p><label><b>Scheduler-Takt</b><br>"
            "<input type='number' "
            "name='presence_tick_seconds' "
            "min='2' max='300' value='{}' "
            "style='width:100px'> Sekunden"
            "</label><br>"
            "<small>Wie oft geprüft wird, ob eine Aufgabe fällig ist. "
            "Dieser Wert erzeugt selbst noch keinen Netzwerkscan.</small>"
            "</p>")
        ).format(
            ctx.esc(
                settings.get(
                    "presence_tick_seconds",
                    "5",
                )
            )
        )

        body += (
            _ui_html("<p><label><b>Maximale parallele Prüfungen</b><br>"
            "<input type='number' "
            "name='presence_max_workers' "
            "min='1' max='64' value='{}' "
            "style='width:100px'>"
            "</label><br>"
            "<small>Anzahl gleichzeitig ausgeführter Ping-Prüfungen. "
            "Für dein Heimnetz sind 16 bis 32 sinnvoll.</small></p>")
        ).format(
            ctx.esc(
                settings.get(
                    "presence_max_workers",
                    "32",
                )
            )
        )

        body += (
            _ui_html("<p><label><b>Globale Offline-Mindestfrist</b><br>"
            "<input type='number' "
            "name='network_offline_timeout_seconds' "
            "min='60' max='86400' value='{}' "
            "style='width:110px'> Sekunden"
            "</label><br>"
            "<small>Mindestfrist ohne bestätigten Kontakt. Die effektive "
            "Frist wird je Scan-Klasse automatisch auf mindestens das "
            "Doppelte des Prüfintervalls plus 60 Sekunden erhöht.</small>"
            "</p>")
        ).format(
            ctx.esc(
                settings.get(
                    "network_offline_timeout_seconds",
                    "300",
                )
            )
        )

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Bekannte Geräte</h3>")

        for label, field, key, default, help_text in (
            (
                "Infrastruktur prüfen alle",
                "presence_infrastructure_interval_minutes",
                "presence_infrastructure_interval_seconds",
                120,
                "Router, Repeater, Server, NAS und Home Assistant.",
            ),
            (
                "Standardgeräte prüfen alle",
                "presence_standard_interval_minutes",
                "presence_standard_interval_seconds",
                300,
                "PCs, VMs, Drucker, IoT-Geräte und sonstige Geräte.",
            ),
            (
                "Mobile Geräte prüfen alle",
                "presence_mobile_interval_minutes",
                "presence_mobile_interval_seconds",
                600,
                "Smartphones, Tablets, Laptops und Notebooks.",
            ),
        ):
            body += (
                _ui_html("<p><label><b>{}</b><br>"
                "<input type='number' name='{}' "
                "min='1' max='1440' value='{}' "
                "style='width:100px'> Minuten"
                "</label><br>"
                "<small>{}</small></p>")
            ).format(
                ctx.esc(_ui_text(label)),
                ctx.esc(field),
                ctx.esc(
                    _seconds_to_minutes(
                        settings.get(key, default),
                        default,
                    )
                ),
                ctx.esc(_ui_text(help_text)),
            )

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Discovery und IPv6</h3>")

        body += (
            _ui_html("<p><label><b>Discovery-Vollscan alle</b><br>"
            "<input type='number' "
            "name='presence_full_scan_interval_minutes' "
            "min='5' max='10080' value='{}' "
            "style='width:100px'> Minuten"
            "</label><br>"
            "<small>Durchsucht das gesamte LAN nach neuen Geräten. "
            "Bekannte Geräte werden unabhängig davon über ihre jeweilige "
            "Scan-Klasse überwacht.</small></p>")
        ).format(
            ctx.esc(
                _seconds_to_minutes(
                    settings.get(
                        "presence_full_scan_interval_seconds",
                        3600,
                    ),
                    3600,
                )
            )
        )

        body += (
            _ui_html("<p><label><b>IPv6-Aktualisierung alle</b><br>"
            "<input type='number' "
            "name='presence_ipv6_interval_minutes' "
            "min='5' max='10080' value='{}' "
            "style='width:100px'> Minuten"
            "</label><br>"
            "<small>Intervall für die getrennte IPv6-Nachbarerkennung. "
            "Die vollständige zeitgesteuerte IPv6-Ausführung wird in "
            "einer folgenden Phase angebunden.</small></p>")
        ).format(
            ctx.esc(
                _seconds_to_minutes(
                    settings.get(
                        "presence_ipv6_interval_seconds",
                        1800,
                    ),
                    1800,
                )
            )
        )

        body += _ui_html("</div>")

        body += (
            _ui_html("<div class='card'>"
            "<button class='btn' type='submit'>"
            "Einstellungen speichern"
            "</button> "
            "<a class='btn' href='/presence/status'>Abbrechen</a>"
            "</div>"
            "</form>")
        )

        body += (
            _ui_html("<div class='card'><h3>Standardwerte</h3>"
            "<p>Infrastruktur: 2 Minuten, Standardgeräte: 5 Minuten, "
            "Mobilgeräte: 10 Minuten, Vollscan: 60 Minuten, "
            "IPv6: 30 Minuten.</p>"
            "<form method='post' action='/presence/settings' "
            "onsubmit=\"return confirm('Alle Presence-Einstellungen "
            "auf Standardwerte zurücksetzen?');\">"
            "<input type='hidden' name='action' "
            "value='restore-defaults'>"
            "<button class='btn' type='submit'>"
            "Standardwerte wiederherstellen"
            "</button>"
            "</form></div>")
        )

        return ctx.page(
            _ui_text("Presence-Einstellungen"),
            body,
            "Presence",
        )

    @app.route("/presence/status")
    def presence_status():
        status = engine_status(ctx)
        runtime = status["runtime"]
        settings = status["settings"]
        class_counts = status["class_counts"]

        message = str(
            request.args.get("msg") or ""
        ).strip()

        body = _ui_html("<div class='card'><h2>Presence Manager</h2>")
        body += (
            _ui_html("<p>"
            "Zentraler Hintergrunddienst für Heimnetz- und "
            "Client-Präsenz. Bekannte Geräte werden nach ihrer "
            "Scan-Klasse geprüft; neue Geräte erkennt ein getrennt "
            "geplanter Discovery-Vollscan."
            "</p>")
        )
        body += _ui_html("</div>")

        if message:
            body += (
                _ui_html("<div class='card'><p><b>{}</b></p></div>")
            ).format(
                ctx.esc(_ui_text(message))
            )

        busy = bool(
            runtime.get("scan_running")
            or runtime.get("full_scan_running")
            or runtime.get("manual_job_pending")
        )

        disabled = " disabled" if busy else ""

        body += _ui_html("<div class='card'><h3>Manuelle Aktionen</h3>")
        body += (
            _ui_html("<p>Status: <b>{}</b></p>")
        ).format(
            _ui_text("Prüfung läuft")
            if busy
            else _ui_text("bereit")
        )

        body += (
            _ui_html("<form method='post' action='/presence/actions' "
            "style='display:inline-block;margin-right:8px'>"
            "<input type='hidden' name='action' "
            "value='known-devices'>"
            "<button class='btn' type='submit'{}>"
            "Bekannte Geräte jetzt prüfen"
            "</button>"
            "</form>")
        ).format(disabled)

        body += (
            _ui_html("<form method='post' action='/presence/actions' "
            "style='display:inline-block' "
            "onsubmit=\"return confirm('Vollständigen LAN-Discovery-Scan "
            "jetzt starten?');\">"
            "<input type='hidden' name='action' "
            "value='full-discovery'>"
            "<button class='btn' type='submit'{}>"
            "Discovery-Vollscan jetzt starten"
            "</button>"
            "</form>")
        ).format(disabled)

        body += (
            _ui_html("<p><small>Die Aktionen laufen im Hintergrund. "
            "Diese Seite kann anschließend aktualisiert werden.</small></p>")
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Laufzeit</h3><table>")

        for label, key in (
            ("Gestartet", "started"),
            ("Thread aktiv", "thread_alive"),
            ("Startzeit", "started_at"),
            ("Letzter Tick", "last_tick_at"),
            ("Ticks", "tick_count"),
            ("Letzter Fehler", "last_error"),
            ("Vollscan läuft", "full_scan_running"),
            ("Letzter Vollscan", "last_full_scan_at"),
            ("Vollscan-Status", "last_full_scan_status"),
            ("Neu gefundene Geräte", "last_full_scan_discovered"),
            ("Vollscan-Fehler", "last_full_scan_error"),
            ("Nächster Vollscan", "next_full_scan_at"),
            ("Manuelle Aktion wartet", "manual_job_pending"),
            ("Manuelle Aktion", "manual_job_type"),
            ("Manuell angefordert", "manual_job_requested_at"),
            ("Letzter Scan-Typ", "last_scan_type"),
            ("Letzter Scan geprüft", "last_scan_checked"),
            ("Letzter Scan online", "last_scan_online"),
            ("Letzter Scan fehlgeschlagen", "last_scan_failed"),
        ):
            body += (
                _ui_html("<tr><td>{}</td><td><code>{}</code></td></tr>")
            ).format(
                ctx.esc(_ui_text(label)),
                ctx.esc(runtime.get(key, "")),
            )

        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Scan-Klassen</h3><table>")
        body += _ui_html("<tr><th>Klasse</th><th>Geräte</th></tr>")

        for scan_class in SCAN_CLASSES:
            body += _ui_html("<tr><td>{}</td><td>{}</td></tr>").format(
                ctx.esc(scan_class),
                ctx.esc(class_counts.get(scan_class, 0)),
            )

        body += _ui_html("</table></div>")

        body += _ui_html("<div class='card'><h3>Letzte Scanläufe</h3>")

        if not status["last_runs"]:
            body += _ui_html("<p>Noch keine Scanläufe gespeichert.</p>")
        else:
            body += (
                _ui_html("<table>"
                "<tr>"
                "<th>Typ</th>"
                "<th>Klasse</th>"
                "<th>Start</th>"
                "<th>Ende</th>"
                "<th>Dauer</th>"
                "<th>Status</th>"
                "<th>Geprüft</th>"
                "<th>Online</th>"
                "<th>Neu</th>"
                "<th>Fehler</th>"
                "</tr>")
            )

            for run in status["last_runs"]:
                body += (
                    _ui_html("<tr>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "<td>{}</td>"
                    "</tr>")
                ).format(
                    ctx.esc(run.get("run_type", "")),
                    ctx.esc(run.get("scan_class", "") or "-"),
                    ctx.esc(run.get("started_at", "")),
                    ctx.esc(run.get("finished_at", "") or "-"),
                    ctx.esc(
                        _format_duration(
                            run.get("started_at"),
                            run.get("finished_at"),
                        )
                    ),
                    ctx.esc(_ui_text(run.get("status", ""))),
                    ctx.esc(run.get("checked_count", 0)),
                    ctx.esc(run.get("online_count", 0)),
                    ctx.esc(run.get("discovered_count", 0)),
                    ctx.esc(_ui_text(run.get("error", "")) or "-"),
                )

            body += _ui_html("</table>")

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Aktuelle Einstellungen</h3>")
        body += _ui_html("<table><tr><th>Einstellung</th><th>Wert</th></tr>")

        for label, value in _setting_status_rows(settings):
            body += _ui_html("<tr><td>{}</td><td>{}</td></tr>").format(
                ctx.esc(_ui_text(label)),
                ctx.esc(value),
            )

        body += _ui_html("</table>")
        body += (
            _ui_html("<p><a class='btn' href='/presence/settings'>"
            "Einstellungen bearbeiten"
            "</a></p>")
        )
        body += _ui_html("</div>")

        body += (
            _ui_html("<div class='card'><p>"
            "<a class='btn' href='/heimnetz'>Heimnetz</a> "
            "<a class='btn' href='/presence/settings'>"
            "Presence-Einstellungen</a> "
            "<a class='btn' href='/heimnetz/settings'>"
            "Heimnetz-Einstellungen</a> "
            "<a class='btn' href='/api/presence/status'>JSON</a>"
            "</p></div>")
        )

        return ctx.page(
            _ui_text("Presence Manager"),
            body,
            "Presence",
        )
