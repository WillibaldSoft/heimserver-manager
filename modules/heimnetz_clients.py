from ui_translation import html_literal as _ui_html, text as _ui_text
from server_settings import get as host_setting
# -*- coding: utf-8 -*-
import ipaddress
import re
import secrets
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import request, redirect, Response, g

from modules.vendor_resolver import (
    reload_vendor_cache,
    vendor_from_mac,
    vendor_resolver_status,
)

LAN_INTERFACE = "br0"
LAN_IPV4_NETWORK = ipaddress.ip_network(host_setting("lan_network"))

from modules.module_selection.config import network_enabled, network_values

def lan_interface():return network_values(LAN_IPV4_NETWORK)[0]
def lan_network():return network_values(LAN_IPV4_NETWORK)[1]

def server_wol_mac():
    """Use explicit WoL identity or the configured LAN interface, never a random NIC."""
    from pathlib import Path
    value=host_setting('server_wol_mac') or ''
    if not value:
        interface=lan_interface()
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}',interface or ''):return ''
        try:value=(Path('/sys/class/net')/interface/'address').read_text().strip()
        except OSError:return ''
    value=value.lower()
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',value) or int(value[:2],16)&1 or value=='00:00:00:00:00:00':return ''
    return value


CLIENT_TIMEOUT_SECONDS = 180

DEVICE_TYPES = [
    "Unbekannt",
    "PC",
    "VM",
    "Server",
    "Laptop",
    "Notebook",
    "Drucker",
    "Fritzbox",
    "Router",
    "Repeater",
    "Switch",
    "Access Point",
    "Telefon",
    "Multimedia",
    "Smartphone",
    "Tablet",
    "Linux-TV",
    "Kodi",
    "Home Assistant",
    "NAS",
    "IoT",
    "IP-Kamera",
    "Sonstiges",
]



def _parse_local_timestamp(value):
    import datetime

    value = str(value or "").strip()

    if not value:
        return None

    try:
        return datetime.datetime.strptime(
            value,
            "%Y-%m-%d %H:%M:%S",
        )
    except Exception:
        return None


def relative_time(value):
    import datetime

    timestamp = _parse_local_timestamp(value)

    if timestamp is None:
        return "nie"

    seconds = max(
        0,
        int(
            (
                datetime.datetime.now() - timestamp
            ).total_seconds()
        ),
    )

    if seconds < 10:
        return "gerade eben"

    if seconds < 60:
        return "vor {} Sekunden".format(seconds)

    minutes = seconds // 60

    if minutes < 60:
        return "vor {} Minute{}".format(
            minutes,
            "" if minutes == 1 else "n",
        )

    hours = minutes // 60

    if hours < 24:
        return "vor {} Stunde{}".format(
            hours,
            "" if hours == 1 else "n",
        )

    days = hours // 24

    return "vor {} Tag{}".format(
        days,
        "" if days == 1 else "en",
    )


def source_label(source):
    labels = {
        "client-agent": "Client-Agent",
        "client-agent-timeout": "Heartbeat-Timeout",
        "ip-neigh": "Netzwerkscan",
        "manual": "Manuell",
        "ping": "Ping",
        "neighbor": "Neighbor",
        "ping-neighbor": "Ping + Neighbor",
        "network-timeout": "Netzwerk-Timeout",
        "presence-ping": "Presence-Ping (älterer Nachweis)",
        "presence-mac": "Ping + MAC-Abgleich",
        "presence-mac-mismatch": "Abweichende MAC an dieser IP",
    }

    source = str(source or "").strip()

    return labels.get(
        source,
        source or "Unbekannt",
    )


def diagnostic_text(row):
    if 'probe_error' in row.keys() and row['probe_error'] == 'IP erreichbar, MAC-Zuordnung nicht eindeutig bestätigt':
        return '⚠ IP erreichbar; Identität derzeit unbestätigt. Letzter bestätigter Kontakt: '+relative_time(row['last_seen'])
    source = str(row["source"] or "")
    online = int(row["is_online"] or 0) == 1
    device_type = str(row["device_type"] or "")
    age = relative_time(row["last_seen"])

    if source == "client-agent":
        if online:
            return "✓ Heartbeat aktiv"
        return "⚠ Client-Agent nicht aktiv"

    if source == "client-agent-timeout":
        return "⚠ Heartbeat ausgeblieben – letzter Kontakt {}".format(
            age
        )

    if source == "network-timeout":
        return "⚠ Keine Netzwerkantwort – letzter Kontakt {}".format(
            age
        )

    if source == "presence-mac-mismatch":
        return "⚠ IP antwortet mit anderer MAC; diese Gerätezuordnung ist unbestätigt"
    if source == "presence-mac":
        return "✓ IP-Antwort und gespeicherte MAC stimmen überein" if online else "Letzter Nachweis: IP und MAC abgeglichen"
    if source == "presence-ping":
        return "Älterer IP-Nachweis ohne MAC-Abgleich"

    if source in ("ip-neigh", "ping", "neighbor", "ping-neighbor"):
        if online:
            if source == "ping-neighbor":
                evidence = "Ping und Neighbor bestätigt"
            elif source == "ping":
                evidence = "Ping bestätigt"
            elif source == "neighbor":
                evidence = "Neighbor bestätigt"
            else:
                evidence = "Netzwerk erreichbar"

            if device_type == "Drucker":
                return "✓ {} / Stand-by möglich".format(evidence)

            return "✓ {}".format(evidence)

        return "⚠ Keine aktive Netzwerkantwort"

    if online:
        return "✓ Online"

    return "⚠ Offline"

def safe_name(x):
    return re.sub(r'[^A-Za-z0-9._-]+', "_", str(x or "Client")).strip("_") or "Client"


def new_token():
    return secrets.token_urlsafe(32)


def json_response(data, code=200):
    import json
    return Response(json.dumps(data, ensure_ascii=False, indent=2), status=code, mimetype="application/json")


def init_tables(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS home_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            display_name TEXT,
            hostname TEXT,
            ip TEXT,
            ipv4 TEXT,
            ipv6 TEXT,
            mac TEXT UNIQUE,
            device_type TEXT DEFAULT 'Unbekannt',
            vendor TEXT,
            is_online INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0,
            notes TEXT,
            last_seen TEXT,
            first_seen TEXT DEFAULT (datetime('now','localtime')),
            source TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS client_agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            home_client_id INTEGER,
            name TEXT,
            hostname TEXT,
            ip TEXT,
            mac TEXT,
            token TEXT UNIQUE,
            mode TEXT DEFAULT 'auto',
            version TEXT,
            enabled INTEGER DEFAULT 1,
            is_online INTEGER DEFAULT 0,
            server_required INTEGER DEFAULT 0,
            require_reason TEXT,
            required_since TEXT,
            last_required_seen TEXT,
            last_seen TEXT,
            online_since TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS heimnetz_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    con.execute("""
        INSERT OR IGNORE INTO heimnetz_settings(key, value)
        VALUES('network_offline_timeout_seconds', '180')
    """)

    home_cols = [r["name"] for r in con.execute("PRAGMA table_info(home_clients)").fetchall()]
    wanted_home = {
        "sleep_blocker": "INTEGER DEFAULT 0",
        "display_name": "TEXT",
        "ipv4": "TEXT",
        "ipv6": "TEXT",
        "deleted": "INTEGER DEFAULT 0",
        "notes": "TEXT",
        "device_type": "TEXT DEFAULT 'Unbekannt'",
        "vendor": "TEXT",
        "source": "TEXT",
        "candidate_ipv4": "TEXT",
        "candidate_ipv4_seen_count": "INTEGER DEFAULT 0",
        "candidate_ipv4_last_seen": "TEXT",
    }
    for k, v in wanted_home.items():
        if k not in home_cols:
            con.execute(f"ALTER TABLE home_clients ADD COLUMN {k} {v}")

    con.execute("""
        UPDATE home_clients
           SET ipv4 = COALESCE(ipv4, CASE WHEN ip NOT LIKE '%:%' THEN ip ELSE NULL END),
               ipv6 = COALESCE(ipv6, CASE WHEN ip LIKE '%:%' THEN ip ELSE NULL END),
               display_name = COALESCE(NULLIF(display_name,''), name),
               device_type = COALESCE(NULLIF(device_type,''), 'Unbekannt'),
               deleted = COALESCE(deleted,0)
    """)

    client_cols = [r["name"] for r in con.execute("PRAGMA table_info(client_agents)").fetchall()]
    wanted_client = {
        "home_client_id": "INTEGER",
        "server_required": "INTEGER DEFAULT 0",
        "require_reason": "TEXT",
        "required_since": "TEXT",
        "last_required_seen": "TEXT",
        "mode": "TEXT DEFAULT 'auto'",
        "online_since": "TEXT",
        "last_seen": "TEXT",
        "is_online": "INTEGER DEFAULT 0",
        "version": "TEXT",
        "ip": "TEXT",
    }
    for k, v in wanted_client.items():
        if k not in client_cols:
            con.execute(f"ALTER TABLE client_agents ADD COLUMN {k} {v}")

    con.commit()





NETWORK_OFFLINE_TIMEOUT_DEFAULT = 180
NETWORK_OFFLINE_TIMEOUT_MIN = 30
NETWORK_OFFLINE_TIMEOUT_MAX = 3600


def get_heimnetz_setting(con, key, default=""):
    row = con.execute(
        "SELECT value FROM heimnetz_settings WHERE key=?",
        (str(key),),
    ).fetchone()

    if not row:
        return default

    return row["value"]


def set_heimnetz_setting(con, key, value):
    con.execute("""
        INSERT INTO heimnetz_settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value=excluded.value
    """, (
        str(key),
        str(value),
    ))


def get_network_offline_timeout(con):
    raw = get_heimnetz_setting(
        con,
        "network_offline_timeout_seconds",
        str(NETWORK_OFFLINE_TIMEOUT_DEFAULT),
    )

    try:
        timeout = int(raw)
    except (TypeError, ValueError):
        timeout = NETWORK_OFFLINE_TIMEOUT_DEFAULT

    return max(
        NETWORK_OFFLINE_TIMEOUT_MIN,
        min(NETWORK_OFFLINE_TIMEOUT_MAX, timeout),
    )


def _presence_interval_for_scan_class(con, scan_class):
    scan_class = str(scan_class or "standard").strip()

    mapping = {
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

    key, default = mapping.get(
        scan_class,
        mapping["standard"],
    )

    row = con.execute("""
        SELECT value
          FROM heimnetz_settings
         WHERE key=?
    """, (key,)).fetchone()

    try:
        interval = int(
            row["value"]
            if row
            else default
        )
    except (TypeError, ValueError):
        interval = default

    return max(30, min(86400, interval))


def network_offline_timeout_for_class(
    con,
    scan_class,
    configured_minimum=None,
):
    """
    Die Offline-Frist muss deutlich größer als das Prüfintervall sein.

    Dadurch kann ein Gerät nicht zwischen zwei regulären Prüfungen
    allein durch den Timeout offline werden.
    """
    if configured_minimum is None:
        configured_minimum = get_network_offline_timeout(con)

    try:
        configured_minimum = int(configured_minimum)
    except (TypeError, ValueError):
        configured_minimum = 180

    interval = _presence_interval_for_scan_class(
        con,
        scan_class,
    )

    return max(
        configured_minimum,
        interval * 2 + 60,
    )


def expire_stale_network_devices(con, timeout_seconds=None):
    """
    Setzt normale Netzwerkgeräte erst nach einer zur Scan-Klasse
    passenden Frist offline.

    Client-Agent-Geräte werden hier grundsätzlich nicht verändert.
    """
    rows = con.execute("""
        SELECT
            h.id,
            h.last_seen,
            COALESCE(
                NULLIF(h.scan_class,''),
                'standard'
            ) AS scan_class
          FROM home_clients h
         WHERE COALESCE(h.deleted,0)=0
           AND COALESCE(h.ignored,0)=0
           AND COALESCE(h.is_online,0)=1
           AND COALESCE(h.always_online,0)=0
           AND NOT EXISTS (
                SELECT 1
                  FROM client_agents a
                 WHERE a.home_client_id=h.id
                   AND COALESCE(a.enabled,1)=1
           )
    """).fetchall()

    expired = 0

    for row in rows:
        if timeout_seconds is None:
            timeout = network_offline_timeout_for_class(
                con,
                row["scan_class"],
            )
        else:
            timeout = max(
                1,
                int(timeout_seconds),
            )

        stale = con.execute("""
            SELECT CASE
                WHEN ? IS NULL THEN 1
                WHEN ? < datetime(
                    'now',
                    'localtime',
                    printf('-%d seconds', ?)
                ) THEN 1
                ELSE 0
            END AS stale
        """, (
            row["last_seen"],
            row["last_seen"],
            timeout,
        )).fetchone()["stale"]

        if int(stale or 0) != 1:
            continue

        cursor = con.execute("""
            UPDATE home_clients
               SET is_online=0,
                   source='network-timeout'
             WHERE id=?
               AND COALESCE(is_online,0)=1
        """, (
            row["id"],
        ))

        expired += int(cursor.rowcount or 0)

    con.commit()
    return expired


def _valid_lan_address(address):
    """Nur Adressen des echten Heimnetz-Interfaces zulassen."""
    try:
        ip = ipaddress.ip_address(str(address or "").split("%", 1)[0])
    except ValueError:
        return False

    if ip.version == 4:
        return ip in lan_network()

    # IPv6 wird bereits durch `dev br0` auf das echte LAN begrenzt.
    # Multicast und nicht spezifizierte Adressen sind keine Clients.
    return not (
        ip.is_multicast
        or ip.is_unspecified
        or ip.is_loopback
    )



def _ping_ipv4(address):
    if not network_enabled():return False
    """Kurzer aktiver Erreichbarkeitstest für bekannte LAN-Geräte."""
    if not _valid_lan_address(address):
        return False

    try:
        result = subprocess.run(
            [
                "ping",
                "-4",
                "-n",
                "-c",
                "1",
                "-W",
                "1",
                str(address),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _parallel_ping_ipv4(addresses, max_workers):
    online = set()

    addresses = sorted({
        str(address).strip()
        for address in addresses
        if str(address or "").strip()
    })

    if not addresses:
        return online

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ping_ipv4, address): address
            for address in addresses
        }

        for future in as_completed(futures):
            address = futures[future]

            try:
                if future.result():
                    online.add(address)
            except Exception:
                pass

    return online


def _current_ipv4_neighbor_candidates():
    """
    Liefert aktuelle IPv4-Nachbarn, die bei einem Fehlnegativtreffer
    nochmals geprüft werden sollen.

    STALE wird ebenfalls aufgenommen, aber nicht als Online-Nachweis
    verwendet. Erst der erfolgreiche Wiederholungs-Ping zählt.
    """
    candidates = set()

    try:
        result = subprocess.run(
            [
                "ip",
                "-4",
                "neigh",
                "show",
                "dev",
                lan_interface(),
            ],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return candidates

    for line in (result.stdout or "").splitlines():
        parts = line.split()

        if not parts:
            continue

        address = parts[0].strip()
        state = parts[-1].strip().upper()

        if state in ("FAILED", "INCOMPLETE"):
            continue

        if _valid_lan_address(address):
            candidates.add(address)

    return candidates


def probe_known_ipv4(con):
    if not network_enabled():return set()
    """
    Aktiver IPv4-Scan des gesamten Heimnetzes mit Wiederholungsprüfung.

    Erster Durchlauf:
        gesamtes LAN parallel scannen, damit neue Geräte erkannt werden.

    Zweiter Durchlauf:
        bekannte Geräte und aktuelle Neighbor-Kandidaten mit geringerer
        Parallelität erneut prüfen. Das fängt temporäre Fehlnegative des
        großen parallelen Sweeps ab.
    """
    all_addresses = {
        str(address)
        for address in lan_network().hosts()
    }

    known_addresses = set()

    rows = con.execute("""
        SELECT DISTINCT COALESCE(NULLIF(ipv4,''), ip) AS address
          FROM home_clients
         WHERE COALESCE(deleted,0)=0
           AND COALESCE(ignored,0)=0
           AND COALESCE(NULLIF(ipv4,''), ip) IS NOT NULL
           AND COALESCE(NULLIF(ipv4,''), ip) NOT LIKE '%:%'
    """).fetchall()

    for row in rows:
        address = str(row["address"] or "").strip()

        if address and _valid_lan_address(address):
            known_addresses.add(address)
            all_addresses.add(address)

    # Schneller vollständiger Suchlauf für bekannte und neue Geräte.
    online = _parallel_ping_ipv4(
        all_addresses,
        max_workers=32,
    )

    # Wiederholung nur für sinnvolle Kandidaten. Dadurch werden Geräte wie
    # langsame IoT-Komponenten nicht wegen eines einzelnen Fehlers offline.
    retry_candidates = (
        known_addresses
        | _current_ipv4_neighbor_candidates()
    ) - online

    online.update(
        _parallel_ping_ipv4(
            retry_candidates,
            max_workers=8,
        )
    )

    return online


def _scan_neigh_family(family_flag, active_ipv4=None):
    rows = []
    active_ipv4 = active_ipv4 or set()

    try:
        result = subprocess.run(
            [
                "ip",
                family_flag,
                "neigh",
                "show",
                "dev",
                lan_interface(),
            ],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return rows

    if result.returncode != 0:
        return rows

    for line in (result.stdout or "").splitlines():
        parts = line.split()

        if not parts:
            continue

        address = parts[0].strip()
        state = parts[-1].strip().upper()

        if state in ("FAILED", "INCOMPLETE"):
            continue

        if not _valid_lan_address(address):
            continue

        actively_reachable = False
        neighbor_reachable = state in (
            "REACHABLE",
            "DELAY",
            "PROBE",
            "PERMANENT",
            "NOARP",
        )

        if ":" not in address:
            actively_reachable = address in active_ipv4

            if not actively_reachable and not neighbor_reachable:
                continue

        mac = ""

        if "lladdr" in parts:
            index = parts.index("lladdr")

            if index + 1 < len(parts):
                mac = parts[index + 1].lower()

        if not mac:
            continue

        family = "ipv6" if ":" in address else "ipv4"

        if family == "ipv4":
            if actively_reachable and neighbor_reachable:
                status_source = "ping-neighbor"
            elif actively_reachable:
                status_source = "ping"
            else:
                status_source = "neighbor"

            # Dynamische IPv4-Neighbor-Zustände allein sind kein sicherer
            # Online-Nachweis. Der aktive Ping muss erfolgreich sein.
            online_ok = actively_reachable
        else:
            status_source = "neighbor"

            # IPv6-only gilt nur bei einem aktuell belastbaren NDP-Zustand
            # als online. STALE darf lediglich Adressen ergänzen.
            online_ok = neighbor_reachable

        rows.append({
            "ip": address,
            "ipv4": address if family == "ipv4" else None,
            "ipv6": address if family == "ipv6" else None,
            "mac": mac,
            "state": state,
            "family": family,
            "interface": lan_interface(),
            "ping_ok": actively_reachable,
            "neighbor_ok": neighbor_reachable,
            "online_ok": online_ok,
            "source": status_source,
        })

    return rows




def _is_real_lan_row(row):
    """Docker-/Container-Adressen niemals wieder als Heimnetzgerät aktivieren."""
    addresses = [
        row["ipv4"] if "ipv4" in row.keys() else None,
        row["ip"] if "ip" in row.keys() else None,
    ]

    for value in addresses:
        value = str(value or "").strip()

        if not value or ":" in value:
            continue

        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue

        return address in lan_network()

    ipv6 = str(
        row["ipv6"]
        if "ipv6" in row.keys()
        else ""
    ).strip()

    return bool(ipv6)


def _source_priority(source):
    priorities = {
        "ping-neighbor": 30,
        "ping": 20,
        "neighbor": 10,
    }

    return priorities.get(
        str(source or ""),
        0,
    )


def rescan_home_client(con, home_client_id, restore=True):
    """
    Gerät anhand seiner MAC-Adresse gezielt neu erkennen.

    Der Einzel-Neuscan ergänzt Stammdaten und Adressen. Eine fehlende
    Antwort verändert den vorhandenen Online-/Offline-Status nicht.
    Diese Entscheidung gehört ausschließlich dem Presence-Scheduler.
    """
    row = con.execute(
        "SELECT * FROM home_clients WHERE id=?",
        (home_client_id,),
    ).fetchone()

    if not row:
        return {
            "ok": False,
            "message": "Gerät nicht gefunden.",
        }

    if not _is_real_lan_row(row):
        return {
            "ok": False,
            "message": (
                f"Das Gerät gehört nicht zum konfigurierten Heimnetz {lan_network()}."
            ),
        }

    mac = str(row["mac"] or "").strip().lower()

    if not mac:
        return {
            "ok": False,
            "message": "Neuscan nicht möglich: MAC-Adresse fehlt.",
        }

    detected_vendor = vendor_from_mac(mac)

    if restore:
        con.execute("""
            UPDATE home_clients
               SET deleted=0,
                   ignored=0
             WHERE id=?
        """, (home_client_id,))

    known_ipv4 = str(
        row["ipv4"]
        or (
            row["ip"]
            if row["ip"] and ":" not in row["ip"]
            else ""
        )
        or ""
    ).strip()

    active_ipv4 = set()

    if known_ipv4 and _ping_ipv4(known_ipv4):
        active_ipv4.add(known_ipv4)

    scan_rows = scan_neigh(
        active_ipv4,
        prime_ipv6=True,
    )

    matches = [
        item
        for item in scan_rows
        if str(item.get("mac") or "").lower() == mac
    ]

    ipv4 = ""
    ipv6 = ""
    source = ""
    positively_reached = False

    for item in matches:
        if item.get("ipv4"):
            ipv4 = item["ipv4"]

        if item.get("ipv6"):
            ipv6 = item["ipv6"]

        if _source_priority(
            item.get("source")
        ) > _source_priority(source):
            source = item.get("source") or source

        if bool(item.get("online_ok")):
            positively_reached = True

    if positively_reached:
        con.execute("""
            UPDATE home_clients
               SET deleted=0,
                   ignored=0,
                   ip=COALESCE(NULLIF(?,''), ip),
                   ipv4=COALESCE(NULLIF(?,''), ipv4),
                   ipv6=COALESCE(NULLIF(?,''), ipv6),
                   vendor=COALESCE(
                       NULLIF(vendor,''),
                       NULLIF(?, '')
                   )
             WHERE id=?
        """, (
            ipv4 or ipv6,
            ipv4,
            ipv6,
            detected_vendor,
            home_client_id,
        ))

        message = (
            "Gerätedaten wurden neu erkannt. "
            "Der Presence-Status wurde nicht verändert."
        )

        if restore:
            message = (
                "Gerät wurde wiederhergestellt und die Gerätedaten "
                "wurden neu erkannt. Der Presence-Status wurde nicht "
                "verändert."
            )

        if not ipv6:
            message += " Eine aktuelle IPv6-Adresse wurde nicht gefunden."

    else:
        con.execute("""
            UPDATE home_clients
               SET deleted=0,
                   ignored=0,
                   vendor=COALESCE(
                       NULLIF(vendor,''),
                       NULLIF(?, '')
                   )
             WHERE id=?
        """, (
            detected_vendor,
            home_client_id,
        ))

        message = (
            "Der Neuscan lieferte keine bestätigte Antwort. "
            "Der bisherige Presence-Status wurde nicht verändert."
        )

        if restore:
            message = (
                "Gerät wurde wiederhergestellt. Der Neuscan lieferte "
                "keine bestätigte Antwort; der bisherige Presence-Status "
                "wurde nicht verändert."
            )

    con.commit()

    updated = con.execute(
        "SELECT * FROM home_clients WHERE id=?",
        (home_client_id,),
    ).fetchone()

    return {
        "ok": True,
        "online": bool(updated["is_online"]),
        "ipv4": updated["ipv4"] or "",
        "ipv6": updated["ipv6"] or "",
        "source": updated["source"] or "",
        "message": message,
    }


def restore_home_client(con, home_client_id):
    row = con.execute(
        "SELECT * FROM home_clients WHERE id=?",
        (home_client_id,),
    ).fetchone()

    if not row:
        return False, "Gerät nicht gefunden."

    if not _is_real_lan_row(row):
        return False, "Container-/Docker-Geräte werden nicht wiederhergestellt."

    con.execute("""
        UPDATE home_clients
           SET deleted=0,
               ignored=0,
               is_online=0,
               source='manual-restore'
         WHERE id=?
    """, (home_client_id,))

    con.commit()
    return True, "Gerät wurde wieder zum Scan freigegeben."

def set_home_client_online(
    con,
    home_client_id,
    online,
    source,
    ip=None,
    mac=None,
    last_seen=None,
):
    if not home_client_id:
        return

    if online:
        con.execute("""
            UPDATE home_clients
               SET is_online=1,
                   last_seen=COALESCE(
                       NULLIF(?, ''),
                       datetime('now','localtime')
                   ),
                   source=?,
                   ip=COALESCE(NULLIF(?,''), ip),
                   ipv4=COALESCE(NULLIF(?,''), ipv4),
                   mac=COALESCE(NULLIF(?,''), mac)
             WHERE id=?
               AND COALESCE(deleted,0)=0
        """, (
            last_seen or "",
            source,
            ip or "",
            ip or "",
            mac or "",
            home_client_id,
        ))
    else:
        con.execute("""
            UPDATE home_clients
               SET is_online=0,
                   last_seen=COALESCE(
                       NULLIF(?, ''),
                       last_seen
                   ),
                   source=?
             WHERE id=?
        """, (
            last_seen or "",
            source,
            home_client_id,
        ))


def expire_stale_agents(con, timeout_seconds=CLIENT_TIMEOUT_SECONDS):
    rows = con.execute("""
        SELECT id, home_client_id, last_seen
          FROM client_agents
         WHERE enabled=1
           AND is_online=1
           AND (
                last_seen IS NULL
                OR last_seen < datetime(
                    'now',
                    'localtime',
                    printf('-%d seconds', ?)
                )
           )
    """, (int(timeout_seconds),)).fetchall()

    for row in rows:
        con.execute("""
            UPDATE client_agents
               SET is_online=0,
                   online_since=NULL,
                   server_required=0,
                   require_reason=NULL,
                   required_since=NULL
             WHERE id=?
        """, (row["id"],))

        set_home_client_online(
            con,
            row["home_client_id"],
            False,
            "client-agent-timeout",
            last_seen=row["last_seen"],
        )

    con.commit()
    return len(rows)


def sync_online_agents_to_home(con):
    rows = con.execute("""
        SELECT home_client_id, ip, mac
          FROM client_agents
         WHERE enabled=1
           AND is_online=1
           AND home_client_id IS NOT NULL
           AND last_seen IS NOT NULL
           AND last_seen >= datetime(
               'now',
               'localtime',
               printf('-%d seconds', ?)
           )
    """, (CLIENT_TIMEOUT_SECONDS,)).fetchall()

    for row in rows:
        set_home_client_online(
            con,
            row["home_client_id"],
            True,
            "client-agent",
            ip=row["ip"],
            mac=row["mac"],
        )

    con.commit()
    return len(rows)


def sync_agent_states_to_home(con):
    """
    Für verknüpfte Client-Agenten ist ausschließlich der Heartbeat
    maßgeblich. ARP/ip-neigh darf diese Geräte nicht wieder online setzen.
    """

    rows = con.execute("""
        SELECT
            id,
            home_client_id,
            ip,
            mac,
            is_online,
            enabled,
            last_seen
          FROM client_agents
         WHERE home_client_id IS NOT NULL
    """).fetchall()

    fresh_count = 0
    offline_count = 0

    for row in rows:
        fresh = (
            int(row["enabled"] or 0) == 1
            and int(row["is_online"] or 0) == 1
            and row["last_seen"] is not None
            and con.execute("""
                SELECT CASE
                    WHEN ? >= datetime(
                        'now',
                        'localtime',
                        printf('-%d seconds', ?)
                    )
                    THEN 1
                    ELSE 0
                END AS fresh
            """, (
                row["last_seen"],
                CLIENT_TIMEOUT_SECONDS,
            )).fetchone()["fresh"] == 1
        )

        if fresh:
            set_home_client_online(
                con,
                row["home_client_id"],
                True,
                "client-agent",
                ip=row["ip"],
                mac=row["mac"],
                last_seen=row["last_seen"],
            )
            fresh_count += 1
        else:
            set_home_client_online(
                con,
                row["home_client_id"],
                False,
                "client-agent-timeout",
                last_seen=row["last_seen"],
            )
            offline_count += 1

    con.commit()

    return {
        "online": fresh_count,
        "offline": offline_count,
    }


def prime_ipv6_neighbors():
    """
    IPv6-Nachbartabelle auf br0 aktiv anregen.

    Nicht jedes Gerät beantwortet den All-Nodes-Multicast. Bereits bekannte
    oder antwortende IPv6-Geräte erscheinen danach in `ip -6 neigh`.
    """
    try:
        subprocess.run(
            [
                "ping",
                "-6",
                "-n",
                "-I",
                lan_interface(),
                "-c",
                "1",
                "-W",
                "1",
                "ff02::1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
    except Exception:
        pass

def _ipv6_preference(address):
    """Bevorzugt global > ULA/private > Link-Local."""
    try:
        value = ipaddress.ip_address(str(address or "").split("%", 1)[0])
    except ValueError:
        return 0

    if value.version != 6:
        return 0

    if value.is_global:
        return 30

    if value.is_private and not value.is_link_local:
        return 20

    if value.is_link_local:
        return 10

    return 1


def _ipv4_candidate_score(row):
    """
    Bewertet mehrere IPv4-Adressen derselben MAC.

    Reihenfolge:
    1. aktiver Ping erfolgreich
    2. belastbarer Neighbor-Zustand
    3. Qualität des Neighbor-Zustands

    Damit gewinnt eine tatsächlich antwortende Geräteadresse gegenüber
    alten, per Proxy-ARP sichtbaren oder nur gecachten Neighbor-Einträgen.
    """
    state = str(row.get("state") or "").strip().upper()

    state_scores = {
        "PERMANENT": 60,
        "REACHABLE": 50,
        "DELAY": 40,
        "PROBE": 30,
        "NOARP": 20,
        "STALE": 10,
    }

    return (
        1 if bool(row.get("ping_ok")) else 0,
        1 if bool(row.get("neighbor_ok")) else 0,
        state_scores.get(state, 0),
    )


def _merge_scan_rows_by_mac(rows):
    """
    Führt IPv4- und IPv6-Nachbarn derselben MAC zu genau einem Gerät
    zusammen.

    Bei mehreren IPv4-Adressen derselben MAC wird nicht mehr die zuerst
    gelieferte Adresse übernommen. Stattdessen gewinnt der Kandidat mit
    dem belastbarsten Nachweis, insbesondere ein erfolgreicher Ping.
    """
    merged = {}

    for row in rows:
        mac = str(row.get("mac") or "").strip().lower()

        if not mac:
            continue

        item = merged.setdefault(
            mac,
            {
                "ip": None,
                "ipv4": None,
                "ipv6": None,
                "mac": mac,
                "state": "",
                "family": "",
                "interface": lan_interface(),
                "ping_ok": False,
                "neighbor_ok": False,
                "online_ok": False,
                "source": "",
                "states": [],
                "ipv4_candidates": [],
                "_ipv4_score": None,
                "_ipv4_row": None,
            },
        )

        state = str(row.get("state") or "").upper()

        if state and state not in item["states"]:
            item["states"].append(state)

        ipv4 = row.get("ipv4")
        ipv6 = row.get("ipv6")

        if ipv4:
            candidate = {
                "address": ipv4,
                "state": state,
                "ping_ok": bool(row.get("ping_ok")),
                "neighbor_ok": bool(row.get("neighbor_ok")),
                "online_ok": bool(row.get("online_ok")),
                "source": row.get("source") or "",
            }

            item["ipv4_candidates"].append(candidate)

            score = _ipv4_candidate_score(row)

            if (
                item["_ipv4_score"] is None
                or score > item["_ipv4_score"]
                or (
                    score == item["_ipv4_score"]
                    and str(ipv4) < str(item["ipv4"] or ipv4)
                )
            ):
                item["_ipv4_score"] = score
                item["_ipv4_row"] = row
                item["ipv4"] = ipv4

        if ipv6:
            if (
                not item["ipv6"]
                or _ipv6_preference(ipv6)
                > _ipv6_preference(item["ipv6"])
            ):
                item["ipv6"] = ipv6

        # Allgemeine Erreichbarkeit weiterhin über alle Adressen derselben
        # MAC zusammenführen.
        item["ping_ok"] = (
            item["ping_ok"]
            or bool(row.get("ping_ok"))
        )
        item["neighbor_ok"] = (
            item["neighbor_ok"]
            or bool(row.get("neighbor_ok"))
        )
        item["online_ok"] = (
            item["online_ok"]
            or bool(row.get("online_ok"))
        )

        if not item["state"] or state == "REACHABLE":
            item["state"] = state

    output = []

    for item in merged.values():
        selected_ipv4_row = item.pop("_ipv4_row", None)
        item.pop("_ipv4_score", None)

        # Quelle, Zustand und IPv4-Erreichbarkeit müssen zum tatsächlich
        # ausgewählten IPv4-Kandidaten gehören. Ein erfolgreicher Ping
        # einer anderen Adresse darf nicht auf die Haupt-IP übertragen
        # werden.
        if selected_ipv4_row is not None:
            item["state"] = str(
                selected_ipv4_row.get("state") or ""
            ).upper()
            item["source"] = (
                selected_ipv4_row.get("source")
                or "neighbor"
            )
            item["ping_ok"] = bool(
                selected_ipv4_row.get("ping_ok")
            )
            item["neighbor_ok"] = bool(
                selected_ipv4_row.get("neighbor_ok")
            )
            item["online_ok"] = bool(
                selected_ipv4_row.get("online_ok")
            )

        item["ip"] = item["ipv4"] or item["ipv6"]

        if item["ipv4"]:
            item["family"] = "ipv4"
        else:
            item["family"] = "ipv6"

        if not item["source"]:
            if item["ping_ok"] and item["neighbor_ok"]:
                item["source"] = "ping-neighbor"
            elif item["ping_ok"]:
                item["source"] = "ping"
            else:
                item["source"] = "neighbor"

        # Ohne belastbaren Nachweis der ausgewählten Adresse wird das Gerät
        # nicht als aktuell erkannt übernommen.
        if item["online_ok"]:
            output.append(item)

    return sorted(
        output,
        key=lambda item: (
            item.get("ipv4") or "999.999.999.999",
            item.get("ipv6") or "",
            item["mac"],
        ),
    )


def scan_neigh(active_ipv4=None, prime_ipv6=False):
    active_ipv4 = active_ipv4 or set()

    if prime_ipv6:
        prime_ipv6_neighbors()

    rows = (
        _scan_neigh_family("-4", active_ipv4)
        + _scan_neigh_family("-6")
    )

    return _merge_scan_rows_by_mac(rows)



IP_CHANGE_CONFIRMATIONS = 2


def _existing_value(row, key, default=None):
    if row is None:
        return default

    try:
        if key not in row.keys():
            return default
    except Exception:
        return default

    return row[key]


def choose_safe_discovered_ipv4(existing, discovered_ipv4):
    """
    Verhindert, dass Discovery eine funktionierende Haupt-IP durch einen
    vorübergehenden oder zusätzlichen Neighbor-Eintrag ersetzt.

    Eine abweichende neue IP wird erst übernommen, wenn:
    - die bisherige IP nicht mehr antwortet und
    - dieselbe Kandidaten-IP in mindestens zwei Discovery-Läufen erschien.
    """
    discovered_ipv4 = str(
        discovered_ipv4 or ""
    ).strip()

    current_ipv4 = str(
        _existing_value(existing, "ipv4", "")
        or _existing_value(existing, "ip", "")
        or ""
    ).strip()

    candidate_ipv4 = str(
        _existing_value(existing, "candidate_ipv4", "")
        or ""
    ).strip()

    try:
        candidate_count = int(
            _existing_value(
                existing,
                "candidate_ipv4_seen_count",
                0,
            ) or 0
        )
    except (TypeError, ValueError):
        candidate_count = 0

    if not discovered_ipv4:
        return {
            "ipv4": current_ipv4 or None,
            "candidate_ipv4": candidate_ipv4 or None,
            "candidate_count": candidate_count,
            "candidate_seen": None,
            "promoted": False,
        }

    if not current_ipv4:
        return {
            "ipv4": discovered_ipv4,
            "candidate_ipv4": None,
            "candidate_count": 0,
            "candidate_seen": None,
            "promoted": True,
        }

    if discovered_ipv4 == current_ipv4:
        return {
            "ipv4": current_ipv4,
            "candidate_ipv4": None,
            "candidate_count": 0,
            "candidate_seen": None,
            "promoted": False,
        }

    # Solange die bisherige Haupt-IP erreichbar ist, bleibt sie
    # kanonisch. Eine zusätzliche Adresse derselben MAC ist dann kein
    # Wechselkandidat.
    if _ping_ipv4(current_ipv4):
        return {
            "ipv4": current_ipv4,
            "candidate_ipv4": None,
            "candidate_count": 0,
            "candidate_seen": None,
            "promoted": False,
            "alternate_ignored": True,
        }

    if candidate_ipv4 == discovered_ipv4:
        candidate_count += 1
    else:
        candidate_ipv4 = discovered_ipv4
        candidate_count = 1

    if candidate_count >= IP_CHANGE_CONFIRMATIONS:
        return {
            "ipv4": discovered_ipv4,
            "candidate_ipv4": None,
            "candidate_count": 0,
            "candidate_seen": None,
            "promoted": True,
        }

    return {
        "ipv4": current_ipv4,
        "candidate_ipv4": candidate_ipv4,
        "candidate_count": candidate_count,
        "candidate_seen": "now",
        "promoted": False,
    }



def presence_discovery_scan(ctx):
    if not network_enabled():return
    con = ctx.db()

    try:
        init_tables(con)
        expire_stale_agents(con)

        active_ipv4 = probe_known_ipv4(con)

        # Discovery ergänzt Geräte und Adressen. Der Offline-Status wird
        # ausschließlich durch die Presence-Timeoutlogik entschieden.
        for item in scan_neigh(active_ipv4):
            ipv4 = item["ipv4"]
            ipv6 = item["ipv6"]
            mac = item["mac"]
            status_source = item.get("source") or "neighbor"
            detected_vendor = vendor_from_mac(mac)

            existing = con.execute("""
                SELECT *
                  FROM home_clients
                 WHERE lower(mac)=lower(?)
                 LIMIT 1
            """, (mac,)).fetchone()

            # Gelöschte Geräte bleiben unverändert.
            if existing and int(existing["deleted"] or 0) == 1:
                continue

            old_name = existing["name"] if existing else ""
            old_display = (
                existing["display_name"]
                if existing
                else ""
            )
            old_host = (
                existing["hostname"]
                if existing
                else ""
            )

            ip_decision = choose_safe_discovered_ipv4(
                existing,
                ipv4,
            )

            preferred_ipv4 = ip_decision["ipv4"]
            candidate_ipv4 = ip_decision["candidate_ipv4"]
            candidate_count = ip_decision["candidate_count"]
            alternate_ignored = bool(
                ip_decision.get("alternate_ignored")
            )

            preferred_ip = preferred_ipv4 or ipv6

            # Eine zusätzliche IP derselben MAC darf nicht die Statusquelle
            # oder letzte Kontaktzeit der weiterhin erreichbaren Haupt-IP
            # überschreiben.
            preserve_status = bool(
                existing
                and alternate_ignored
            )

            name = (
                old_display
                or old_name
                or old_host
                or preferred_ipv4
                or ipv6
                or mac
            )
            hostname = old_host or ""

            con.execute("""
                INSERT INTO home_clients(
                    name,
                    display_name,
                    hostname,
                    ip,
                    ipv4,
                    ipv6,
                    mac,
                    device_type,
                    vendor,
                    is_online,
                    deleted,
                    last_seen,
                    source,
                    candidate_ipv4,
                    candidate_ipv4_seen_count,
                    candidate_ipv4_last_seen
                )
                VALUES(
                    ?,?,?,?,?,?,?,
                    'Unbekannt',
                    ?,
                    1,
                    0,
                    datetime('now','localtime'),
                    ?,
                    ?,
                    ?,
                    CASE
                        WHEN ? IS NULL THEN NULL
                        ELSE datetime('now','localtime')
                    END
                )
                ON CONFLICT(mac) DO UPDATE SET
                    ip=COALESCE(
                        excluded.ip,
                        home_clients.ip
                    ),
                    ipv4=COALESCE(
                        excluded.ipv4,
                        home_clients.ipv4
                    ),
                    ipv6=COALESCE(
                        excluded.ipv6,
                        home_clients.ipv6
                    ),
                    name=COALESCE(
                        NULLIF(home_clients.name,''),
                        excluded.name
                    ),
                    display_name=COALESCE(
                        NULLIF(home_clients.display_name,''),
                        excluded.display_name
                    ),
                    hostname=home_clients.hostname,
                    device_type=COALESCE(
                        NULLIF(home_clients.device_type,''),
                        'Unbekannt'
                    ),
                    vendor=COALESCE(
                        NULLIF(home_clients.vendor,''),
                        excluded.vendor
                    ),
                    is_online=CASE
                        WHEN COALESCE(home_clients.deleted,0)=1
                        THEN 0
                        WHEN ?=1
                        THEN home_clients.is_online
                        ELSE 1
                    END,
                    last_seen=CASE
                        WHEN COALESCE(home_clients.deleted,0)=1
                        THEN home_clients.last_seen
                        WHEN ?=1
                        THEN home_clients.last_seen
                        ELSE datetime('now','localtime')
                    END,
                    source=CASE
                        WHEN ?=1
                        THEN home_clients.source
                        ELSE excluded.source
                    END,
                    candidate_ipv4=excluded.candidate_ipv4,
                    candidate_ipv4_seen_count=
                        excluded.candidate_ipv4_seen_count,
                    candidate_ipv4_last_seen=
                        excluded.candidate_ipv4_last_seen
            """, (
                name,
                name,
                hostname,
                preferred_ip,
                preferred_ipv4,
                ipv6,
                mac,
                detected_vendor,
                status_source,
                candidate_ipv4,
                candidate_count,
                candidate_ipv4,
                1 if preserve_status else 0,
                1 if preserve_status else 0,
                1 if preserve_status else 0,
            ))

        # Discovery erkennt und ergänzt Geräte. Online-/Offline-
        # Entscheidungen trifft ausschließlich der Presence-Scheduler.
        # Agent-Heartbeat hat weiterhin Vorrang vor Discovery-Daten.
        sync_agent_states_to_home(con)

        con.commit()

    finally:
        con.close()


def agent_by_token(ctx):
    token = request.headers.get("X-Server-Manager-Token","") or request.headers.get("Authorization","").replace("Bearer ","")
    token = token.strip()
    if not token:
        return None
    con = ctx.db()
    try:
        init_tables(con)
        agent=con.execute("SELECT * FROM client_agents WHERE token=? AND enabled=1", (token,)).fetchone()
        from modules.heimnetz_extra.client_bindings import authorized
        return agent if agent and authorized(con,agent) else None
    finally:
        con.close()


def home_assistant_yaml():
    import json
    from urllib.parse import urlsplit
    raw=host_setting('recover_url') or ''
    url=urlsplit(raw)
    if url.scheme in ('http','https') and url.hostname and not url.username and not url.password and url.path.endswith('/recover') and not url.query and not url.fragment:
        base=raw[:-len('/recover')]
    else:
        base='http://RECOVERY-SERVER:8182'
    quote=lambda path:json.dumps(base+path,ensure_ascii=False)
    return ("# In vorhandene rest_command: / rest: Abschnitte einfügen; nicht doppelt anlegen.\n"
            "# RECOVERY-SERVER bei Bedarf durch IP oder Hostnamen des Recovery-Dienstes ersetzen.\n"
            "rest_command:\n"
            "  debian_server_power_on:\n"
            "    url: "+quote('/poweron')+"\n"
            "    method: GET\n"
            "    timeout: 20\n\n"
            "  debian_server_recover:\n"
            "    url: "+quote('/recover')+"\n"
            "    method: GET\n"
            "    timeout: 40\n\n"
            "rest:\n"
            "  - resource: "+quote('/status')+"\n"
            "    method: GET\n"
            "    scan_interval: 30\n"
            "    timeout: 20\n"
            "    sensor:\n"
            "      - name: Debian Server IPMI Status\n"
            "        unique_id: debian_server_ipmi_status\n"
            '        value_template: "{{ value_json.state_text }}"\n'
            "        json_attributes:\n"+
            ''.join('          - '+key+'\n' for key in ('state','power','reachable','ipmi_status','recover_active','phase','last_action','last_error','recover_count','reset_count','version')))


def home_assistant_help_box():
    import html
    return _ui_html("""<div class='card'><details><summary><b>Home Assistant: Server einschalten, Recovery und Status</b></summary>
<p>Optionale Anbindung eines <b>separaten Power-/Recovery-Dienstes</b>. Der normale Client-Agent sendet Anwesenheit und Schlafbedarf; er installiert keine IPMI-API auf Port 8182. Den Dienst unter <a href="/apps/power_api/installer">Apps → Power &amp; Recovery API</a> installieren oder aktualisieren. Im Betrieb muss er laufen, die Endpunkte <code>/poweron</code>, <code>/recover</code> und <code>/status</code> bereitstellen und von Home Assistant erreichbar sein. Er sollte auf einem Rechner laufen, der auch bei ausgeschaltetem Zielserver erreichbar bleibt. IPMI-Funktionen benötigen passende Hardware und eine eingerichtete Verbindung.</p>
<ol>
<li><b>Adresse prüfen:</b> Das Beispiel übernimmt die konfigurierte Recovery-URL aus <a href='/settings/server-paths'>Server &amp; Modulpfade</a>. Steht dort RECOVERY-SERVER, in allen drei URLs durch die Adresse des Rechners mit dem Recovery-Dienst ersetzen. Port und Protokoll müssen zur Installation passen. Die Adresse gehört zum Recovery-Dienst, nicht zwingend zum gesteuerten Server. Zuerst nur <code>/status</code> aufrufen: Die Antwort muss JSON mit <code>state_text</code> enthalten.</li>
<li><b>Datei sichern und öffnen:</b> In Home Assistant <code>configuration.yaml</code> bearbeiten; bei Home Assistant OS üblicherweise <code>/config/configuration.yaml</code>, beispielsweise mit File editor oder Studio Code Server. Bei Container/Core den eingebundenen Konfigurationsordner verwenden.</li>
<li><b>YAML zusammenführen:</b> Fehlen <code>rest_command:</code> und <code>rest:</code>, den vollständigen Block unten einfügen. Sind sie schon vorhanden, nur die zwei Befehle bzw. den neuen Listeneintrag unter den jeweiligen Abschnitt ergänzen. Beide Hauptschlüssel stehen ohne Einrückung und dürfen nicht doppelt vorkommen. <code>sensor:</code> gehört in diesem Beispiel unter den REST-Eintrag, nicht als zusätzlicher Hauptabschnitt. Leerzeichen statt Tabs verwenden.</li>
<li><b>Bei ausgelagerten Dateien:</b> Für <code>rest_command: !include rest_commands.yaml</code> die beiden Befehle ohne die äußere Zeile <code>rest_command:</code> in diese Datei setzen und zwei Leerzeichen weniger einrücken. Für <code>rest: !include rest.yaml</code> entsprechend den Eintrag ab <code>- resource:</code> ohne äußere <code>rest:</code>-Zeile verwenden und zwei Leerzeichen weniger einrücken. Vorhandene Inhalte erhalten.</li>
<li><b>Prüfen und übernehmen:</b> In Home Assistant unter Entwicklerwerkzeuge → YAML die Konfiguration prüfen. Nur bei erfolgreicher Prüfung Home Assistant neu starten. Unter Entwicklerwerkzeuge → Zustände den Sensor suchen; er heißt normalerweise <code>sensor.debian_server_ipmi_status</code>. Seine Attribute zeigen Fehler, Recovery-Phase und Zähler. Bei mehreren Servern Namen, <code>unique_id</code> und Befehlsnamen je Server eindeutig vergeben.</li>
<li><b>Bewusst bedienen:</b> Unter Entwicklerwerkzeuge → Aktionen sind <code>rest_command.debian_server_power_on</code> und <code>rest_command.debian_server_recover</code> verfügbar; auch in Automationen oder Skripten nutzbar. Einschalten steuert den Zielserver. Recovery kann je nach installiertem Dienst einen Reset auslösen; nicht als regelmäßige Statusprüfung verwenden. Nur der Sensor fragt automatisch alle 30 Sekunden ab. Ein Aufruf-Timeout bedeutet nicht, dass der Dienst seine Arbeit beendet hat; zunächst Status prüfen.</li>
</ol>
<p>Diese Vorlage setzt einen ohne zusätzliche Anmeldung erreichbaren Dienst im vertrauenswürdigen LAN/VPN voraus. Bei eingerichteter API-Anmeldung die passenden Header/Authentifizierung in Home Assistant ergänzen, Zugangsdaten über <code>!secret</code> hinterlegen. Die Steuerendpunkte nicht ungeschützt ins Internet freigeben.</p>
<p><a class='btn' href='/clients/power-api'>Power-/Recovery-Dienst installieren …</a> <a class='btn' href='/clients/home-assistant.yaml'>YAML herunterladen</a></p><pre>""")+html.escape(home_assistant_yaml())+_ui_html("""</pre>
<p>Home-Assistant-Dokumentation: <a href='https://www.home-assistant.io/integrations/rest_command/' target='_blank' rel='noopener noreferrer'>REST-Befehle</a> · <a href='https://www.home-assistant.io/integrations/rest/' target='_blank' rel='noopener noreferrer'>REST-Sensoren</a></p>
</details></div>""")


def client_agent_help_box():
    return _ui_html("""
<div class='card'><details>
<summary><b>Einrichtung &amp; Bedienung: Linux (.deb / .sh) und Windows (.exe)</b></summary>
<p>Für neue Clients <a href="/clients/setup">Persönliche Einrichtung</a> öffnen und mit dem eigenen Manager-Benutzer anmelden. Dort Linux-DEB oder Windows-EXE und das persönliche JSON-Profil herunterladen. Der Eintrag wird bei Aktivierung automatisch angelegt; pro Rechner und Benutzer ein eigenes Profil verwenden.</p>
<h3>Linux-Desktop · DEB</h3>
<ol>
<li><b>Linux (.deb)</b> herunterladen und mit der Paketverwaltung installieren. Alternativ im Downloadordner: <code>sudo apt install ./DATEINAME.deb</code> (DATEINAME durch den Namen der heruntergeladenen DEB ersetzen).</li>
<li><b>Heimserver Manager Client</b> im Startmenü als normaler Benutzer öffnen.</li>
<li>Unter <b>Persönliche Einrichtung</b> das eigene JSON-Profil herunterladen und in der App <b>Profil importieren</b> wählen.</li>
<li>Angaben prüfen, <b>Speichern</b> und <b>Agent aktivieren / übernehmen</b> wählen.</li>
</ol>
<p><b>Bisheriger Skript-Client:</b> Unter demselben Linux-Benutzer werden die vorhandenen Einstellungen automatisch geladen. Normalerweise ist kein JSON-Import nötig. Bei der Übernahme werden die bisherigen Benutzerdienste gesichert; derselbe Heartbeat-Timer wird weiterverwendet.</p>
<p>Das Statussymbol startet bei grafischer Anmeldung mit vorhandener Konfiguration automatisch. Fenster schließen beendet den Agenten nicht. <b>Agent deaktivieren</b> deaktiviert auch den Symbol-Autostart. Die Sichtbarkeit des Symbols hängt von der Desktopumgebung ab.</p>
<h3>Windows 10 / 11 · EXE (experimentell)</h3>
<ol>
<li><b>Windows (.exe)</b> herunterladen und als normaler Windows-Benutzer öffnen. Voraussetzung: .NET Framework 4.8 oder neuer.</li>
<li>Unter <b>Persönliche Einrichtung</b> das eigene JSON-Profil herunterladen und in der App <b>Profil importieren (.json)</b> wählen.</li>
<li>Angaben prüfen und <b>Statussymbol bei Windows-Anmeldung starten</b> nach Wunsch aktiviert lassen.</li>
<li><b>Agent aktivieren</b> wählen. Mit gewähltem Autostart wird die App für diesen Benutzer installiert; alternativ <b>Für Benutzer installieren</b> verwenden. Ein Startmenüeintrag wird angelegt, Administratorrechte sind nicht erforderlich.</li>
</ol>
<p>Fenster schließen lässt Agent und Statussymbol weiterlaufen. <b>Agent und Statussymbol beenden</b> beendet unter Windows auch den Heartbeat. Einstellungen werden benutzergebunden verschlüsselt gespeichert. Linux-Skriptdateien werden unter Windows nicht automatisch übernommen; hierfür das JSON-Profil verwenden.</p>
<p>Erste Windows-Version: Protokoll und Fensteraufbau unter Linux/Mono geprüft; echter Windows-Start, Verschlüsselung, Startmenü und Autostart müssen auf Windows noch geprüft werden.</p>
<h3>Linux ohne Desktop-App · Shell-Skript (.sh)</h3>
<p><b>1. Installer herunterladen:</b> Nur für bestehende Altprofile: unter <b>Altprofil-Downloads</b> beim gewünschten Client das Shell-Skript herunterladen.</p>
<p><b>2. Auf dem Linux-Client im Terminal ausführen (ohne sudo):</b> Danach öffnet sich das Menü. Benötigt: Bash, curl und Python 3.</p>
<pre>chmod +x Hostname.sh
./Hostname.sh</pre>
<p><b>3. Client-Menü starten:</b></p>
<pre>~/.local/bin/server-manager-client</pre>
<p><b>4. Autostart prüfen:</b></p>
<pre>systemctl --user status server-manager-client.service
systemctl --user enable server-manager-client.service
systemctl --user start server-manager-client.service</pre>
<p><b>Konfiguration:</b></p>
<pre>~/.local/bin/server-manager-client config</pre>
<p>Server-Adresse, Name, Token, MAC und Wake-Einstellungen lassen sich direkt ändern. Mit Enter bleibt ein Wert erhalten. Für Installation ohne Menü: <code>bash Hostname.sh --no-menu</code>.</p>
<table>
<tr><th>Datei</th><th>Funktion</th></tr>
<tr><td><code>~/.local/bin/server-manager-client</code></td><td>Client-Menü / Agent</td></tr>
<tr><td><code>~/.config/server-manager-client/config</code></td><td>Client-Konfiguration</td></tr>
<tr><td><code>~/.config/systemd/user/server-manager-client.service</code></td><td>Autostart</td></tr>
</table>

<h3>Wer gibt den Modus vor?</h3>
<p><b>Der Client-Agent sendet seinen gespeicherten Modus etwa alle 60 Sekunden an den Manager.</b> Dieser übernimmt ihn und den gemeldeten Serverbedarf. Den Modus deshalb im Agenten ändern und speichern. Die Auswahl im Manager ist eine Vorgabe für das heruntergeladene Profil; spätere Änderungen werden nicht automatisch an einen eingerichteten Agenten verteilt.</p>
<ul>
<li><b>Mit Server starten:</b> beim Start wecken und regelmäßig Serverbedarf melden.</li>
<li><b>Ohne Server starten:</b> kein automatisches Wecken und kein dauerhafter Schlafblocker.</li>
<li><b>Nur auf ausdrücklichen Aufruf wecken:</b> Wecken über die Agenten-Schaltflächen; kein dauerhafter Schlafblocker.</li>
</ul>
<p><b>Server benötigt / Server freigeben</b> sind einmalige Meldungen. Der nächste Heartbeat setzt den Bedarf wieder gemäß Betriebsmodus. <b>Zugriff vorbereiten</b> weckt und wartet; es überwacht keine Dateizugriffe und bindet keine Freigaben ein.</p>
<p><b>Persönliche Dateien:</b> JSON-Profil und individuelles Shell-Skript enthalten den Agenten-Token. Nur auf dem zugehörigen Client speichern und nicht weitergeben. DEB und EXE enthalten keine persönlichen Zugangsdaten.</p>
<h3>Optional: Power-/Recovery-Dienst bereitstellen</h3>
<p>Einen anderen Server über seine IPMI-Schnittstelle einschalten und den Status an Home Assistant melden. Installer für einen dauerhaft erreichbaren Debian-Rechner; Adressen, Zugangsdaten, Port und erlaubte Clients werden bei der Einrichtung abgefragt.</p>
<a class='btn' href='/clients/power-api'>Installationspaket &amp; Anleitung</a>
""") + home_assistant_help_box() + _ui_html("</details></div>")


def device_type_select(ctx, current):
    current = current or "Unbekannt"
    html = _ui_html("<select name='device_type'>")
    for t in DEVICE_TYPES:
        sel = "selected" if t == current else ""
        html += f'{_ui_html("<option value='")}{ctx.esc(t)}{_ui_html("' ")}{sel}{_ui_html('>')}{ctx.esc(t)}{_ui_html('</option>')}'
    html += _ui_html("</select>")
    return html


def register(app, ctx):
    from modules.heimnetz_extra.client_bindings import register as register_bindings
    register_bindings(app,ctx,init_tables,server_wol_mac)
    # Dependent modules require these tables on the very first startup.
    con = ctx.db()
    try:
        init_tables(con)
        con.commit()
    finally:
        con.close()

    @app.route('/clients/power-api')
    def client_power_api_setup():
        return redirect('/apps/power_api/installer',303)

    @app.route('/clients/power-api/download')
    def client_power_api_download():
        import io,zipfile
        from pathlib import Path
        from flask import send_file
        folder=Path(__file__).resolve().parents[1]/'tools/power_api';stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for name in ('power_api.py','install.py','README.txt'):
                archive.writestr('Power-Recovery-API/'+name,(folder/name).read_bytes())
        stream.seek(0)
        result=send_file(stream,mimetype='application/zip',as_attachment=True,download_name='Power-Recovery-API-Installer.zip')
        result.headers['Cache-Control']='no-store'
        return result

    @app.route('/clients/home-assistant.yaml')
    def client_home_assistant_yaml():
        return Response(home_assistant_yaml(),mimetype='text/yaml',headers={'Content-Disposition':'attachment; filename="home-assistant-server-recovery.yaml"','Cache-Control':'no-store'})

    @app.route("/api/clients/status")
    def api_clients_status():
        agent = agent_by_token(ctx)
        if not agent:
            return json_response({"ok": False, "error": "unauthorized"}, 401)
        return json_response({
            "ok": True,
            "id": agent["id"],
            "name": agent["name"],
            "mode": agent["mode"],
            "server_required": bool(agent["server_required"]),
            "is_online": bool(agent["is_online"]),
            "last_seen": agent["last_seen"],
        })

    @app.route("/api/clients/heartbeat", methods=["POST"])
    def api_clients_heartbeat():
        agent = agent_by_token(ctx)
        if not agent:
            return json_response({"ok": False, "error": "unauthorized"}, 401)

        data = request.get_json(silent=True) or {}
        version = data.get("version") or request.form.get("version") or ""
        client = agent["name"] if getattr(g,"bound_client",False) else (data.get("client") or request.form.get("client") or agent["name"])
        mac = data.get("mac") or request.form.get("mac") or agent["mac"] or ""
        mode = data.get("mode") or request.form.get("mode") or agent["mode"] or "auto"
        required = data.get("server_required")
        reason = data.get("reason") or request.form.get("reason") or agent["require_reason"] or ""

        if isinstance(required, str):
            required = required.strip().lower() in ("1", "true", "yes", "ja", "on")
        elif required is None:
            required = bool(agent["server_required"])
        else:
            required = bool(required)

        con = ctx.db()
        try:
            init_tables(con)
            con.execute("""
                UPDATE client_agents
                   SET is_online=1,
                       last_seen=datetime('now','localtime'),
                       online_since=COALESCE(online_since, datetime('now','localtime')),
                       ip=?,
                       name=COALESCE(NULLIF(?,''), name),
                       mac=COALESCE(NULLIF(?,''), mac),
                       mode=COALESCE(NULLIF(?,''), mode),
                       version=COALESCE(NULLIF(?,''), version),
                       server_required=?,
                       require_reason=CASE WHEN ?=1 THEN COALESCE(NULLIF(?,''), require_reason, 'heartbeat') ELSE NULL END,
                       required_since=CASE WHEN ?=1 THEN COALESCE(required_since, datetime('now','localtime')) ELSE NULL END,
                       last_required_seen=CASE WHEN ?=1 THEN datetime('now','localtime') ELSE last_required_seen END
                 WHERE id=?
            """, (
                request.remote_addr,
                client,
                mac,
                mode,
                version,
                1 if required else 0,
                1 if required else 0,
                reason,
                1 if required else 0,
                1 if required else 0,
                agent["id"],
            ))
            if getattr(g,'bound_client',False):
                from modules.heimnetz_extra.client_bindings import reported_hostname
                reported_hostname(con,agent,data)
            current = con.execute("""
                SELECT home_client_id, ip, mac
                  FROM client_agents
                 WHERE id=?
            """, (agent["id"],)).fetchone()

            if current and current["home_client_id"]:
                set_home_client_online(
                    con,
                    current["home_client_id"],
                    True,
                    "client-agent",
                    ip=current["ip"],
                    mac=current["mac"],
                )

            con.commit()
        finally:
            con.close()

        from modules.module_selection.config import network_enabled
        return json_response({"ok": True, "heartbeat": True, "server_required": required, "sleep_blocker_enabled": network_enabled()})

    @app.route("/api/clients/need-server", methods=["POST"])
    def api_clients_need_server():
        agent = agent_by_token(ctx)
        if not agent:
            return json_response({"ok": False, "error": "unauthorized"}, 401)

        data = request.get_json(silent=True) or {}
        reason = data.get("reason") or request.form.get("reason") or "client"
        version = data.get("version") or request.form.get("version") or ""
        client = agent["name"] if getattr(g,"bound_client",False) else (data.get("client") or request.form.get("client") or agent["name"])
        mac = data.get("mac") or request.form.get("mac") or agent["mac"] or ""

        con = ctx.db()
        try:
            init_tables(con)
            con.execute("""
                UPDATE client_agents
                   SET is_online=1,
                       server_required=1,
                       require_reason=?,
                       required_since=COALESCE(required_since, datetime('now','localtime')),
                       last_required_seen=datetime('now','localtime'),
                       last_seen=datetime('now','localtime'),
                       online_since=COALESCE(online_since, datetime('now','localtime')),
                       ip=?,
                       name=COALESCE(NULLIF(?,''), name),
                       mac=COALESCE(NULLIF(?,''), mac),
                       version=COALESCE(NULLIF(?,''), version)
                 WHERE id=?
            """, (reason, request.remote_addr, client, mac, version, agent["id"]))
            con.commit()
        finally:
            con.close()

        return json_response({"ok": True, "server_required": True, "reason": reason})

    @app.route("/api/clients/release-server", methods=["POST"])
    def api_clients_release_server():
        agent = agent_by_token(ctx)
        if not agent:
            return json_response({"ok": False, "error": "unauthorized"}, 401)

        con = ctx.db()
        try:
            init_tables(con)
            con.execute("""
                UPDATE client_agents
                   SET server_required=0,
                       require_reason=NULL,
                       required_since=NULL,
                       last_required_seen=datetime('now','localtime'),
                       last_seen=datetime('now','localtime')
                 WHERE id=?
            """, (agent["id"],))
            con.commit()
        finally:
            con.close()

        return json_response({"ok": True, "server_required": False})

    @app.route("/heimnetz")
    def heimnetz():
        # Die Seite zeigt ausschließlich den von der zentralen
        # Presence Engine gepflegten Datenbankstatus. Kein Netzwerkscan
        # mehr bei Browseraufrufen.
        con = ctx.db()
        try:
            rows = con.execute("""
                SELECT *
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=0
                 ORDER BY is_online DESC,
                          COALESCE(NULLIF(display_name,''), name, hostname, ipv4, ipv6) COLLATE NOCASE
            """).fetchall()
        finally:
            con.close()

        body = _ui_html("<div class='card'><h2>Heimnetz</h2>")
        body += (
            f'{_ui_html('<p>Geräteverwaltung für <code>')}{ctx.esc(lan_interface())}{_ui_html('</code> und das LAN <code>')}{lan_network()}{_ui_html("</code>. Automatische Überwachung, Online-/Offline-Status und Discovery werden zentral vom <a href='/presence/status'>Presence Manager</a> gesteuert. Docker- und virtuelle Netze werden ignoriert.</p>")}'
        )
        body += (
            _ui_html("<p>"
            "<a class='btn' href='/heimnetz'>Anzeige aktualisieren</a> "
            "<a class='btn' href='/presence/status'>Presence</a> "
            "<a class='btn' href='/clients'>Clients</a> "
            "<a class='btn' href='/heimnetz/settings'>Geräteverwaltung</a>"
            "</p></div>")
        )

        body += _ui_html("""<style>
.home-devices{width:100%;min-width:1180px;table-layout:fixed}
.home-devices th,.home-devices td{vertical-align:top;overflow-wrap:break-word}
.home-devices input,.home-devices select{width:100%}
.home-devices label{display:block;margin-bottom:8px}
.home-devices .device-meta{display:block;color:#cbd5e1;margin-top:6px}
.home-devices code{white-space:normal;overflow-wrap:anywhere}
.home-device-actions{display:flex;flex-wrap:wrap;gap:6px}
.home-device-actions form{margin:0}
.home-device-actions .pill{display:inline-flex;align-items:center;margin:0}
@media(max-width:700px){.home-devices{min-width:0;table-layout:auto}}
</style><div class='card'><table class='home-devices'>
<colgroup><col style='width:9%'><col style='width:20%'><col style='width:18%'><col style='width:21%'><col style='width:17%'><col style='width:15%'></colgroup>
<thead><tr><th>Status</th><th>Gerät</th><th>Identifikation</th><th>Adressen</th><th>Anwesenheit</th><th>Aktionen</th></tr></thead><tbody>""")

        address_macs = {}
        for device in rows:
            address = device['ipv4'] or device['ip']
            mac = str(device['mac'] or '').strip().lower()
            if address and mac:address_macs.setdefault(address, set()).add(mac)
        duplicates = {address for address, macs in address_macs.items() if len(macs)>1}
        if duplicates:
            body += _ui_html("<tr><td colspan='6'><b>Mehrfach gespeicherte IP-Adressen</b><p>Eine IP kann früher zu anderen Geräten gehört haben. Die Einträge bleiben getrennt nach MAC erhalten. Mehrere Einträge allein belegen keinen aktuellen IP-Konflikt.</p></td></tr>")
        for r in rows:
            status = "🟢 online" if int(r["is_online"] or 0) else "⚪ offline"
            if r['probe_error'] == 'IP erreichbar, MAC-Zuordnung nicht eindeutig bestätigt':
                status = '🟡 Zuordnung unbestätigt'
            display = r["display_name"] or r["name"] or r["hostname"] or r["ipv4"] or r["ipv6"] or r["mac"]
            fid = "home-device-" + str(r["id"])
            select = device_type_select(ctx, r["device_type"]).replace("<select ", f'{_ui_html("<select form='")}{fid}{_ui_html("' ")}', 1)
            body += f'{_ui_html('<tr><td>')}{ctx.esc(_ui_text(status))}{_ui_html('</td>')}'
            body += f'{_ui_html("<td><label>Name<input form='")}{fid}{_ui_html("' name='display_name' value='")}{ctx.esc(display)}{_ui_html("'></label><label>Typ")}{select}{_ui_html('</label></td>')}'
            body += f'{_ui_html("<td><label>Hostname<input form='")}{fid}{_ui_html("' name='hostname' value='")}{ctx.esc(r['hostname'] or '')}{_ui_html("'></label><span class='device-meta'>Hersteller: ")}{ctx.esc(r['vendor'] or _ui_text('Unbekannt'))}{_ui_html('</span></td>')}'
            body += _ui_html("<td>")
            for label, value in (("IPv4", r["ipv4"] or r["ip"]), ("IPv6", r["ipv6"]), ("MAC", r["mac"])):
                body += f'{_ui_html('<div><b>')}{_ui_text(label)}{_ui_html(':</b> <code>')}{ctx.esc(value or '—')}{_ui_html('</code></div>')}'
            if (r['ipv4'] or r['ip']) in duplicates:
                body += _ui_html("<span class='device-meta'>⚠ IP bei mehreren MAC-Adressen gespeichert</span>")
            if r['source'] == 'presence-mac-mismatch':
                body += _ui_html("<span class='device-meta'>Alte oder abweichende Zuordnung – aktuell nicht bestätigt</span>")
            body += _ui_html("</td><td>")
            body += f'{_ui_html('<div>')}{ctx.esc(source_label(r['source']))}{_ui_html('</div>')}'
            body += f'{_ui_html("<div title='")}{ctx.esc(r['last_seen'] or '')}{_ui_html("'>")}{ctx.esc(relative_time(r['last_seen']))}{_ui_html('</div>')}'
            body += f'{_ui_html("<span class='device-meta'>")}{ctx.esc(diagnostic_text(r))}{_ui_html('</span></td>')}'
            body += _ui_html("<td><div class='home-device-actions'>")
            body += f'{_ui_html("<form id='")}{fid}{_ui_html("' method='post' action='/heimnetz/update'><input type='hidden' name='id' value='")}{r['id']}{_ui_html("'><button class='pill' type='submit'>Speichern</button></form>")}'
            body += f'{_ui_html("<a class='pill' href='/heimnetz/client/")}{r['id']}{_ui_html("'>Details</a>")}'
            body += f'{_ui_html("<form method='post' action='/clients/create-from-home'><input type='hidden' name='home_id' value='")}{r['id']}{_ui_html("'><button class='pill' type='submit'>Als Client</button></form>")}'
            body += f'{_ui_html('<form method=\'post\' action=\'/heimnetz/delete\' onsubmit="return confirm(\'Gerät löschen?\')"><input type=\'hidden\' name=\'id\' value=\'')}{r['id']}{_ui_html("'><button class='pill' type='submit'>Löschen</button></form>")}'
            body += _ui_html("</div></td></tr>")

        body += _ui_html("</tbody></table></div>")
        return ctx.page(_ui_text("Heimnetz"), body, "Heimnetz")

    @app.route("/heimnetz/settings", methods=["GET", "POST"])
    def heimnetz_settings():
        msg = ""

        con = ctx.db()

        try:
            init_tables(con)

            if request.method == "POST":
                action = request.form.get("action", "")
                home_id = request.form.get("id")

                if action == "reload-vendors":
                    status = reload_vendor_cache()

                    if status.get("error"):
                        msg = (
                            "Herstellerdaten wurden mit Warnung neu geladen: "
                            + str(status["error"])
                        )
                    else:
                        msg = (
                            "{} IEEE-Hersteller und {} lokale Overrides "
                            "wurden geladen."
                        ).format(
                            status.get("vendors", 0),
                            status.get("overrides", 0),
                        )

                elif action == "restore":
                    ok, msg = restore_home_client(
                        con,
                        home_id,
                    )

                elif action == "rescan":
                    result = rescan_home_client(
                        con,
                        home_id,
                        restore=True,
                    )
                    msg = result["message"]

                elif action == "restore-all":
                    rows = con.execute("""
                        SELECT *
                          FROM home_clients
                         WHERE COALESCE(deleted,0)=1
                         ORDER BY id
                    """).fetchall()

                    restored = 0

                    for row in rows:
                        if not _is_real_lan_row(row):
                            continue

                        ok, _ = restore_home_client(
                            con,
                            row["id"],
                        )

                        if ok:
                            restored += 1

                    msg = "{} LAN-Geräte wurden wieder freigegeben.".format(
                        restored
                    )

                elif action == "purge-device":
                    row = con.execute("""
                        SELECT *
                          FROM home_clients
                         WHERE id=?
                           AND COALESCE(deleted,0)=1
                    """, (home_id,)).fetchone()

                    if not row:
                        msg = "Gelöschtes Gerät nicht gefunden."
                    else:
                        agent = con.execute("""
                            SELECT id
                              FROM client_agents
                             WHERE home_client_id=?
                             LIMIT 1
                        """, (home_id,)).fetchone()

                        if agent:
                            msg = (
                                "Gerät ist noch mit einem Client-Agent "
                                "verknüpft und wurde nicht endgültig gelöscht."
                            )
                        else:
                            name = (
                                row["display_name"]
                                or row["name"]
                                or row["hostname"]
                                or row["ipv4"]
                                or row["ip"]
                                or row["mac"]
                                or "Gerät"
                            )

                            con.execute("""
                                DELETE FROM home_client_presence
                                 WHERE home_client_id=?
                            """, (home_id,))

                            con.execute("""
                                DELETE FROM home_clients
                                 WHERE id=?
                                   AND COALESCE(deleted,0)=1
                            """, (home_id,))

                            con.commit()
                            msg = "{} wurde endgültig gelöscht.".format(name)

                elif action == "purge-docker":
                    cursor = con.execute("""
                        DELETE FROM home_clients
                         WHERE COALESCE(deleted,0)=1
                           AND (
                                COALESCE(ipv4,'') LIKE '172.17.%'
                                OR COALESCE(ipv4,'') LIKE '172.18.%'
                                OR COALESCE(ipv4,'') LIKE '172.19.%'
                                OR COALESCE(ipv4,'') LIKE '172.20.%'
                                OR COALESCE(ip,'') LIKE '172.17.%'
                                OR COALESCE(ip,'') LIKE '172.18.%'
                                OR COALESCE(ip,'') LIKE '172.19.%'
                                OR COALESCE(ip,'') LIKE '172.20.%'
                           )
                    """)

                    con.commit()

                    msg = (
                        "{} alte Docker-/Container-Einträge "
                        "wurden endgültig entfernt."
                    ).format(
                        cursor.rowcount
                    )

            rows = con.execute("""
                SELECT *
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=1
                 ORDER BY
                       CASE
                           WHEN COALESCE(ipv4,ip,'') LIKE '172.%'
                           THEN 1
                           ELSE 0
                       END,
                       COALESCE(
                           NULLIF(display_name,''),
                           name,
                           hostname,
                           ipv4,
                           ip
                       ) COLLATE NOCASE
            """).fetchall()

        finally:
            con.close()

        lan_rows = [
            row
            for row in rows
            if _is_real_lan_row(row)
        ]

        docker_rows = [
            row
            for row in rows
            if not _is_real_lan_row(row)
        ]

        body = _ui_html("<div class='card'><h2>Heimnetz-Einstellungen</h2>")

        if msg:
            body += _ui_html("<p><b>{}</b></p>").format(
                ctx.esc(_ui_text(msg))
            )

        body += (
            _ui_html("<p>Gelöschte Geräte bleiben gespeichert. Sie können einzeln "
            "wiederhergestellt oder anhand ihrer MAC-Adresse vollständig "
            "neu erkannt werden.</p>")
        )

        body += (
            _ui_html("<p>"
            "<a class='btn' href='/heimnetz'>Zurück zum Heimnetz</a>"
            "</p>")
        )

        vendor_status = vendor_resolver_status()

        body += _ui_html("</div>")

        body += (
            _ui_html("<div class='card'>"
            "<h3>Automatische Netzwerküberwachung</h3>"
            "<p>Prüfintervalle, Discovery und Online-/Offline-Fristen "
            "werden ausschließlich vom Presence Manager gesteuert.</p>"
            "<p><a class='btn' href='/presence/settings'>"
            "Presence-Einstellungen öffnen"
            "</a> "
            "<a class='btn' href='/presence/status'>"
            "Presence-Status öffnen"
            "</a></p>"
            "</div>")
        )

        body += _ui_html("<div class='card'><h3>Herstellerdaten</h3>")
        body += (
            _ui_html("<table>"
            "<tr><td>IEEE-Datenbank</td><td><code>{}</code></td></tr>"
            "<tr><td>Geladene Hersteller</td><td>{}</td></tr>"
            "<tr><td>Lokale Overrides</td><td>{}</td></tr>"
            "<tr><td>Override-Datei</td><td><code>{}</code></td></tr>"
            "</table>")
        ).format(
            ctx.esc(vendor_status.get("source") or "nicht gefunden"),
            ctx.esc(vendor_status.get("vendors", 0)),
            ctx.esc(vendor_status.get("overrides", 0)),
            ctx.esc(vendor_status.get("override_path") or ""),
        )

        if vendor_status.get("error"):
            body += _ui_html("<p class='warn'>{}</p>").format(
                ctx.esc(_ui_text(vendor_status["error"]))
            )

        body += (
            _ui_html("<form method='post'>"
            "<input type='hidden' name='action' value='reload-vendors'>"
            "<button class='btn' type='submit'>"
            "Herstellerdaten neu laden"
            "</button>"
            "</form>")
        )
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Gelöschte LAN-Geräte</h3>")

        if not lan_rows:
            body += _ui_html("<p>Keine gelöschten LAN-Geräte vorhanden.</p>")
        else:
            body += (
                _ui_html("<table>"
                "<tr>"
                "<th>Name</th>"
                "<th>IPv4</th>"
                "<th>IPv6</th>"
                "<th>MAC</th>"
                "<th>Typ</th>"
                "<th>Letzter Kontakt</th>"
                "<th>Aktion</th>"
                "</tr>")
            )

            for row in lan_rows:
                name = (
                    row["display_name"]
                    or row["name"]
                    or row["hostname"]
                    or row["ipv4"]
                    or row["ip"]
                    or row["mac"]
                )

                body += _ui_html("<tr>")
                body += _ui_html("<td><b>{}</b></td>").format(
                    ctx.esc(name)
                )
                body += _ui_html("<td><code>{}</code></td>").format(
                    ctx.esc(row["ipv4"] or row["ip"] or "")
                )
                body += _ui_html("<td><code>{}</code></td>").format(
                    ctx.esc(row["ipv6"] or "")
                )
                body += _ui_html("<td><code>{}</code></td>").format(
                    ctx.esc(row["mac"] or "")
                )
                body += _ui_html("<td>{}</td>").format(
                    ctx.esc(row["device_type"] or _ui_text("Unbekannt"))
                )
                body += _ui_html("<td>{}</td>").format(
                    ctx.esc(relative_time(row["last_seen"]))
                )

                body += _ui_html("<td>")

                body += (
                    _ui_html("<form method='post' style='display:inline-block;"
                    "margin-right:5px'>"
                    "<input type='hidden' name='action' value='restore'>"
                    "<input type='hidden' name='id' value='{}'>"
                    "<button class='btn' type='submit'>"
                    "Wiederherstellen"
                    "</button>"
                    "</form>")
                ).format(row["id"])

                body += (
                    _ui_html("<form method='post' style='display:inline-block'>"
                    "<input type='hidden' name='action' value='rescan'>"
                    "<input type='hidden' name='id' value='{}'>"
                    "<button class='btn' type='submit'>"
                    "Wiederherstellen und neu scannen"
                    "</button>"
                    "</form>")
                ).format(row["id"])

                body += (
                    _ui_html("<form method='post' style='display:inline-block;"
                    "margin-left:5px' "
                    "onsubmit=\"return confirm('Dieses Gerät endgültig "
                    "löschen? Namen, Notizen und Verlauf gehen verloren.');\">"
                    "<input type='hidden' name='action' "
                    "value='purge-device'>"
                    "<input type='hidden' name='id' value='{}'>"
                    "<button class='btn' type='submit'>"
                    "Endgültig löschen"
                    "</button>"
                    "</form>")
                ).format(row["id"])

                body += _ui_html("</td></tr>")

            body += _ui_html("</table>")

            body += (
                _ui_html("<p style='margin-top:14px'>"
                "<form method='post' style='display:inline-block;"
                "margin-right:8px'>"
                "<input type='hidden' name='action' value='restore-all'>"
                "<button class='btn' type='submit'>"
                "Alle LAN-Geräte wieder freigeben"
                "</button>"
                "</form>"
                "<a class='btn' href='/presence/status'>"
                "Discovery im Presence Manager"
                "</a>"
                "</p>")
            )

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Alte Docker-/Container-Einträge</h3>")

        body += _ui_html("<p>Gespeichert: <b>{}</b></p>").format(
            len(docker_rows)
        )

        if docker_rows:
            body += (
                _ui_html("<form method='post' "
                "onsubmit=\"return confirm('Alte gelöschte Docker- und "
                "Container-Einträge endgültig aus der Datenbank entfernen?');\">"
                "<input type='hidden' name='action' value='purge-docker'>"
                "<button class='btn' type='submit'>"
                "Alte Docker-Einträge endgültig entfernen"
                "</button>"
                "</form>")
            )
        else:
            body += _ui_html("<p>Keine alten Container-Einträge vorhanden.</p>")

        body += _ui_html("</div>")

        return ctx.page(
            _ui_text("Heimnetz Einstellungen"),
            body,
            "Heimnetz",
        )


    @app.route("/heimnetz/update", methods=["POST"])
    def heimnetz_update():
        hid = request.form.get("id")
        display_name = request.form.get("display_name", "").strip()
        hostname = request.form.get("hostname", "").strip()
        device_type = request.form.get("device_type", "Unbekannt").strip()
        if device_type not in DEVICE_TYPES:
            device_type = "Unbekannt"

        con = ctx.db()
        try:
            init_tables(con)
            con.execute("""
                UPDATE home_clients
                   SET display_name=?,
                       name=COALESCE(NULLIF(?,''), name),
                       hostname=?,
                       device_type=?
                 WHERE id=?
            """, (display_name, display_name, hostname, device_type, hid))
            con.commit()
        finally:
            con.close()
        return redirect("/heimnetz")

    @app.route("/heimnetz/delete", methods=["POST"])
    def heimnetz_delete():
        hid = request.form.get("id")
        con = ctx.db()
        try:
            init_tables(con)
            con.execute("""
                UPDATE home_clients
                   SET deleted=1,
                       is_online=0
                 WHERE id=?
            """, (hid,))
            con.commit()
        finally:
            con.close()
        return redirect("/heimnetz")

    @app.route("/clients/create-from-home", methods=["POST"])
    def clients_create_from_home():
        home_id = request.form.get("home_id")
        con = ctx.db()
        try:
            init_tables(con)
            h = con.execute("SELECT * FROM home_clients WHERE id=? AND COALESCE(deleted,0)=0", (home_id,)).fetchone()
            if not h:
                return "Heimnetzgerät nicht gefunden", 404
            existing = con.execute("SELECT id FROM client_agents WHERE mac=? LIMIT 1", (h["mac"],)).fetchone()
            if not existing:
                name = h["display_name"] or h["name"] or h["hostname"] or h["ipv4"] or h["ip"] or h["mac"]
                con.execute("""
                    INSERT INTO client_agents(home_client_id,name,hostname,ip,mac,token,mode,enabled)
                    VALUES(?,?,?,?,?,?, 'auto', 1)
                """, (h["id"], name, h["hostname"], h["ipv4"] or h["ip"], h["mac"], new_token()))
                con.commit()
        finally:
            con.close()
        return redirect("/clients")

    @app.route("/clients", methods=["GET", "POST"])
    def clients():
        con = ctx.db()
        msg = ""
        try:
            init_tables(con)

            if request.method == "POST":
                action = request.form.get("action")
                cid = request.form.get("id")
                if action == "mode":
                    mode = request.form.get("mode") or "auto"
                    con.execute("UPDATE client_agents SET mode=? WHERE id=?", (mode, cid))
                    con.commit()
                    msg = "Modus gespeichert."
                elif action == "renew":
                    con.execute("UPDATE client_agents SET token=? WHERE id=?", (new_token(), cid))
                    con.commit()
                    msg = "Token erneuert."
                elif action == "delete":
                    con.execute("DELETE FROM client_agents WHERE id=?", (cid,))
                    con.commit()
                    msg = "Client gelöscht."
                elif action == "toggle":
                    con.execute("UPDATE client_agents SET enabled=CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?", (cid,))
                    con.commit()
                    msg = "Status geändert."

            from modules.heimnetz_extra.client_bindings import schema
            schema(con)
            bindings={r['agent_id']:r for r in con.execute('SELECT * FROM client_bindings')}
            rows = con.execute("SELECT * FROM client_agents ORDER BY enabled DESC,is_online DESC,name COLLATE NOCASE").fetchall()
        finally:
            con.close()

        body = _ui_html("<div class='card'><h2>Clients</h2><p>Client-Agenten mit eigenem Modus und Schlafblocker. Für neue Clients die persönliche Einrichtung unten verwenden. Jede Benutzer-Geräte-Kombination erhält einen eigenen Eintrag; Freigeben betrifft nur diesen. Alte JSON-Profile bleiben ungekoppelt nutzbar. MAC-Adressen sind Zuordnungshilfen, keine Anmeldedaten.</p>")
        if msg:
            body += f'{_ui_html('<p><b>')}{ctx.esc(_ui_text(msg))}{_ui_html('</b></p>')}'
        body += _ui_html("<p><a class='btn' href='/heimnetz'>Aus Heimnetz übernehmen</a></p></div>")
        body += _ui_html("<div class='card'><h3>Client-App herunterladen</h3><p><a class='btn' href='/clients/setup'>Persönliche Einrichtung mit Anmeldung</a></p><p>Programme und persönliches JSON-Profil werden zentral über <code>/clients/setup</code> heruntergeladen. Diesen Link auf dem jeweiligen Client öffnen und mit dessen Manager-Benutzer anmelden. Bei neuer Einrichtung entsteht der Geräteeintrag automatisch.</p><a class='btn' href='/clients/recovery/download'>Systemwiederherstellung für Live-USB herunterladen</a><p>Portables ZIP mit Skripten und Anleitung für ein gestartetes Linux-Live-System; kein bootfähiges ISO. Vollständige Rücksicherung benötigt ein vorbereitetes Linux-Zielsystem und Administratorrechte. Enthält keine Zugangsdaten.</p></div>")
        body += client_agent_help_box()

        body += _ui_html("<div class='card'><table><tr><th>Status</th><th>Name</th><th>Modus</th><th>Server benötigt</th><th>IP</th><th>MAC</th><th>Letzter Kontakt</th><th>Aktion</th></tr>")
        address_macs = {}
        for device in rows:
            address = device['ip']
            mac = str(device['mac'] or '').strip().lower()
            if address and mac:address_macs.setdefault(address, set()).add(mac)
        duplicates = {address for address, macs in address_macs.items() if len(macs)>1}
        if duplicates:
            body += _ui_html("<tr><td colspan='6'><b>Mehrfach gespeicherte IP-Adressen</b><p>Eine IP kann früher zu anderen Geräten gehört haben. Die Einträge bleiben getrennt nach MAC erhalten. Mehrere Einträge allein belegen keinen aktuellen IP-Konflikt.</p></td></tr>")
        for r in rows:
            status = "🟢 online" if int(r["is_online"] or 0) else "⚪ offline"
            if int(r["enabled"] or 0) != 1:
                status = "⛔ deaktiviert"
            name = r["name"] or r["hostname"] or "Client"
            binding=bindings.get(r['id'])
            binding_note=('Gekoppelt · Hostname: '+(r['hostname'] or 'Noch nicht übermittelt')) if binding else 'Nicht gekoppelt (Altprofil)'
            safe = safe_name(name)
            required = "ja" if int(r["server_required"] or 0) else "nein"
            agent_note = "⚠ Agent noch nie verbunden" if not (r["last_seen"] or "") else "✓ Letzter Kontakt: " + str(r["last_seen"])

            body += _ui_html("<tr>")
            body += f'{_ui_html('<td>')}{ctx.esc(_ui_text(status))}{_ui_html('</td><td>')}{ctx.esc(name)}{_ui_html('<br><small>')}{ctx.esc(binding_note)}{_ui_html('</small></td>')}'
            body += f'{_ui_html("<td><form method='post'><input type='hidden' name='action' value='mode'><input type='hidden' name='id' value='")}{r['id']}{_ui_html("'><select name='mode'>")}'
            for m, label in [("auto", "Automatisch nach Bedarf"), ("connected", "Server verbunden"), ("release-only", "Nur freigeben"), ("disabled", "Server nicht benötigt")]:
                stored_mode={"with_server":"connected","without_server":"disabled","wake_on_access":"auto"}.get(r["mode"],r["mode"] or "auto")
                sel = "selected" if stored_mode == m else ""
                body += f'{_ui_html("<option value='")}{m}{_ui_html("' ")}{sel}{_ui_html('>')}{_ui_text(label)}{_ui_html('</option>')}'
            body += _ui_html("</select><button class='pill' type='submit'>OK</button></form></td>")
            body += f'{_ui_html('<td>')}{ctx.esc(required)}{_ui_html('<br><small>')}{ctx.esc(r['require_reason'] or '')}{_ui_html('</small><br><small>')}{ctx.esc(agent_note)}{_ui_html('</small></td>')}'
            body += f'{_ui_html('<td>')}{ctx.esc(r['ip'] or '')}{_ui_html('</td><td><code>')}{ctx.esc(r['mac'] or '')}{_ui_html('</code></td><td>')}{ctx.esc(r['last_seen'] or '-')}{_ui_html('</td>')}'
            body += _ui_html("<td>")
            if not binding:
                body += f'{_ui_html("<details><summary>Altprofil-Downloads</summary><a class='btn' href='/clients/desktop/profile/")}{r['id']}{_ui_html("'>Altes JSON-Profil</a> <a class='btn' href='/clients/install/")}{r['id']}{_ui_html("'>")}{ctx.esc(safe)}{_ui_html('.sh</a><p>Nur für bestehende ungekoppelte Skript-Clients. Neue Clients über die persönliche Einrichtung anmelden.</p></details>')}'
            body += f'{_ui_html("<form method='post' style='display:inline'><input type='hidden' name='action' value='renew'><input type='hidden' name='id' value='")}{r['id']}{_ui_html("'><button class='pill' type='submit'>Token neu</button></form> ")}'
            body += f'{_ui_html("<form method='post' style='display:inline'><input type='hidden' name='action' value='toggle'><input type='hidden' name='id' value='")}{r['id']}{_ui_html("'><button class='pill' type='submit'>Aktiv</button></form> ")}'
            body += f'{_ui_html('<form method=\'post\' style=\'display:inline\' onsubmit="return confirm(\'Client löschen?\')"><input type=\'hidden\' name=\'action\' value=\'delete\'><input type=\'hidden\' name=\'id\' value=\'')}{r['id']}{_ui_html("'><button class='pill' type='submit'>Löschen</button></form>")}'
            body += _ui_html("</td></tr>")
        body += _ui_html("</table></div>")
        return ctx.page(_ui_text("Clients"), body, "Clients")

    @app.route('/clients/desktop/download')
    def clients_desktop_deb():
        import tempfile
        from pathlib import Path
        from client_agent.desktop.build import build,VERSION as CLIENT_VERSION
        try:
            with tempfile.TemporaryDirectory(prefix='client-deb-') as folder:
                filename='Heimserver_Manager_Client_'+CLIENT_VERSION+'_all.deb'
                path=build(Path(__file__).resolve().parents[1],Path(folder)/filename)
                response=Response(path.read_bytes(),mimetype='application/vnd.debian.binary-package')
                response.headers['Content-Disposition']='attachment; filename="'+filename+'"'
                response.headers['Cache-Control']='no-store'
                return response
        except Exception:
            return ctx.page(_ui_text('Client-DEB'),_ui_html("<div class='card'><p>Client-Paket konnte nicht erstellt werden. dpkg-deb und den Paketquellbestand prüfen.</p><a href='/clients'>Zurück zu Client-Agenten</a></div>"),'Clients'),500

    @app.route('/clients/recovery/download')
    def clients_recovery_download():
        from pathlib import Path
        from client_agent.desktop.build import recovery_archive
        try:
            data, filename = recovery_archive(Path(__file__).resolve().parents[1])
        except (OSError, ValueError):
            return ctx.page(_ui_text('Systemwiederherstellung'), _ui_html("<div class='card'><p>Live-USB-Paket konnte nicht erstellt werden. Paketquellbestand prüfen.</p><a href='/clients'>Zurück zu Client-Agenten</a></div>"), 'Clients'), 503
        response = Response(data, mimetype='application/zip')
        response.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.route('/clients/windows/download')
    def clients_windows_exe():
        from client_agent.windows.download import executable
        try:
            data, filename = executable()
        except (OSError, ValueError):
            return ctx.page(_ui_text('Windows-Client'), _ui_html("<div class='card'><p>Windows-Paket fehlt oder seine Prüfsumme stimmt nicht. Manager-Paketbestand prüfen.</p><a href='/clients'>Zurück zu Client-Agenten</a></div>"), 'Clients'), 503
        response = Response(data, mimetype='application/octet-stream')
        response.headers['Content-Disposition'] = 'attachment; filename="' + filename + '"'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.route('/clients/desktop/profile/<int:cid>')
    def clients_desktop_profile(cid):
        import json
        con=ctx.db()
        try:
            init_tables(con)
            row=con.execute('SELECT * FROM client_agents WHERE id=?',(cid,)).fetchone()
        finally:con.close()
        if not row:return 'Client nicht gefunden',404
        mode={'auto':'with_server','connected':'with_server','release-only':'without_server','disabled':'without_server'}.get(row['mode'],row['mode'])
        if mode not in ('with_server','without_server','wake_on_access'):mode='without_server'
        recover=host_setting('recover_url') or ''
        server_mac=server_wol_mac()
        config=dict(SERVER_URL=request.url_root.rstrip('/'),TOKEN=row['token'],CLIENT_NAME=row['name'] or row['hostname'] or 'Client',CLIENT_MAC=row['mac'] or '',CLIENT_MODE=mode,IPMI_RECOVER_URL=recover,WAKE_METHOD=('both' if server_mac else 'recover') if recover else ('wol' if server_mac else 'none'),SERVER_MAC=server_mac,WAKE_TIMEOUT='40')
        profile=dict(format='heimserver-manager-client',version=1,config=config)
        try:
            import hashlib,ssl,ipaddress
            from modules.web_security import manager_https as mh
            state=mh.load()
            if state.get('enabled') and (mh.TLS/'root-ca.crt').is_file():
                pem=(mh.TLS/'root-ca.crt').read_text()
                try:ip=str(ipaddress.ip_address(request.host.split(':')[0]))
                except ValueError:ip=''
                if not request.is_secure:config['SERVER_URL']=mh.public_url(state)
                ip=state.get('ip_address') or ip
                profile['https']=dict(hostname=state['hostname'],port=state['port'],ip=ip,ca_pem=pem,sha256=hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest())
        except (OSError,ValueError,KeyError):pass
        response=Response(json.dumps(profile,ensure_ascii=False),mimetype='application/json')
        response.headers['Content-Disposition']='attachment; filename="'+safe_name(config['CLIENT_NAME'])+'-client.json"'
        response.headers['Cache-Control']='no-store';response.headers['Pragma']='no-cache'
        return response

    @app.route("/clients/install/<int:cid>")
    def clients_install(cid):
        con = ctx.db()
        try:
            init_tables(con)
            r = con.execute("SELECT * FROM client_agents WHERE id=?", (cid,)).fetchone()
        finally:
            con.close()

        if not r:
            return "Client nicht gefunden", 404

        server_url = request.url_root.rstrip("/")
        recover_url = host_setting("recover_url")
        name = r["name"] or r["hostname"] or "Client"
        mac = r["mac"] or ""
        token = r["token"]
        mode = r["mode"] or "auto"
        safe = safe_name(name)

        lines = [
            "#!/bin/bash",
            'set -euo pipefail',
            'umask 077',
            'if [ "${EUID:-$(id -u)}" -eq 0 ]; then',
            '  echo "Bitte als normaler Desktop-Benutzer ohne sudo ausführen." >&2',
            '  exit 1',
            'fi',
            'case "${1:-}" in',
            '  --help|-h) echo "Installation: bash DATEI.sh [--no-menu]; danach: ~/.local/bin/server-manager-client config"; exit 0 ;;',
            '  ""|--no-menu) ;;',
            '  *) echo "Unbekannte Option: $1 (Hilfe: --help)" >&2; exit 2 ;;',
            'esac',
            'for dependency in curl python3; do',
            '  command -v "$dependency" >/dev/null || { echo "Bitte zuerst $dependency installieren." >&2; exit 1; }',
            'done',
            'APPDIR="$HOME/.local/bin"',
            'CFGDIR="$HOME/.config/server-manager-client"',
            'SYSDIR="$HOME/.config/systemd/user"',
            'mkdir -p "$APPDIR" "$CFGDIR" "$SYSDIR"',
            '',
            '# Bestehende Client-Konfiguration erhalten.',
            'if [ -f "$CFGDIR/config" ]; then',
            '  # shellcheck disable=SC1091',
            '  source "$CFGDIR/config" || true',
            'fi',
            f"DEFAULT_SERVER_URL={shlex.quote(str(server_url))}",
            f'IPMI_RECOVER_URL="${{IPMI_RECOVER_URL:-{recover_url}}}"',
            f"TOKEN={shlex.quote(str(token))}",
            f"CLIENT_NAME={shlex.quote(str(name))}",
            f"CLIENT_MAC={shlex.quote(str(mac))}",
            f"DEFAULT_CLIENT_MODE={shlex.quote(str(mode))}",
            'CLIENT_MODE="${CLIENT_MODE:-$DEFAULT_CLIENT_MODE}"',
            'SERVER_URL="${SERVER_URL:-$DEFAULT_SERVER_URL}"',
            'WAKE_METHOD="${WAKE_METHOD:-recover}"',
            'SERVER_MAC="${SERVER_MAC:-}"',
            'WAKE_TIMEOUT="${WAKE_TIMEOUT:-40}"',
            'CFG="$CFGDIR/config"',
            'save_config(){',
            '  local tmp key',
            '  tmp=$(mktemp "${CFG}.XXXXXX") || return 1',
            '  if ! (',
            '    for key in SERVER_URL IPMI_RECOVER_URL TOKEN CLIENT_NAME CLIENT_MAC CLIENT_MODE WAKE_METHOD SERVER_MAC WAKE_TIMEOUT; do',
            '      printf \'%s=%q\\n\' "$key" "${!key}"',
            '    done',
            '  ) > "$tmp"; then',
            '    rm -f "$tmp"; return 1',
            '  fi',
            '  chmod 600 "$tmp"',
            '  mv -f -- "$tmp" "$CFG"',
            '}',
            'save_config',
            '',
            'cat > "$APPDIR/server-manager-client" <<\'EOF\'',
            '#!/bin/bash',
            'set -euo pipefail',
            'CFG="$HOME/.config/server-manager-client/config"',
            'source "$CFG"',
            'WAKE_METHOD="${WAKE_METHOD:-recover}"',
            'SERVER_MAC="${SERVER_MAC:-}"',
            'WAKE_TIMEOUT="${WAKE_TIMEOUT:-40}"',
            'IPMI_RECOVER_URL="${IPMI_RECOVER_URL:-}"',
            'require_terminal(){',
            '  if [ ! -t 0 ]; then',
            '    echo "Das Menü benötigt ein Terminal. Aufruf: ~/.local/bin/server-manager-client config" >&2',
            '    return 1',
            '  fi',
            '}',
            'edit_config(){',
            '  local key="$1" value',
            '  read -r -p "$2 [Enter = unverändert]: " value || return 0',
            '  [ -n "$value" ] || return 0',
            '  case "$key" in',
            '    SERVER_URL|IPMI_RECOVER_URL)',
            '      if ! python3 -c \'import sys,urllib.parse; u=urllib.parse.urlsplit(sys.argv[1]); assert u.scheme in ("http","https") and u.hostname and not any(c.isspace() for c in sys.argv[1]); assert u.port is None or 1 <= u.port <= 65535\' "$value" 2>/dev/null; then',
            '        echo "Ungültige HTTP(S)-Adresse."; return 0',
            '      fi ;;',
            '    WAKE_METHOD) case "$value" in recover|wol|both|none) ;; *) echo "Erlaubt: recover, wol, both, none"; return 0 ;; esac ;;',
            '    SERVER_MAC|CLIENT_MAC) [[ "$value" =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]] || { echo "MAC im Format aa:bb:cc:dd:ee:ff eingeben."; return 0; } ;;',
            '    WAKE_TIMEOUT) [[ "$value" =~ ^[1-9][0-9]{0,2}$ ]] && ((10#$value <= 300)) || { echo "Timeout: 1 bis 300 Sekunden."; return 0; } ;;',
            '  esac',
            '  printf -v "$key" \'%s\' "$value"',
            '  save_config',
            '  echo "Gespeichert."',
            '}',
            '',
            'save_config(){',
            '  local tmp key',
            '  tmp=$(mktemp "${CFG}.XXXXXX") || return 1',
            '  if ! (',
            '    for key in SERVER_URL IPMI_RECOVER_URL TOKEN CLIENT_NAME CLIENT_MAC CLIENT_MODE WAKE_METHOD SERVER_MAC WAKE_TIMEOUT; do',
            '      printf \'%s=%q\\n\' "$key" "${!key}"',
            '    done',
            '  ) > "$tmp"; then',
            '    rm -f "$tmp"; return 1',
            '  fi',
            '  chmod 600 "$tmp"',
            '  mv -f -- "$tmp" "$CFG"',
            '}',
            '',
            'api_post(){',
            '  curl -fsS --max-time 15 \\',
            '    -H "Authorization: Bearer $TOKEN" \\',
            '    -H "Content-Type: application/json" \\',
            '    -X POST "$@"',
            '}',
            '',
            'need(){',
            '  local reason="${1:-auto}"',
            '  local payload',
            '  payload=$(python3 -c \'import json,sys; print(json.dumps(dict(zip(("reason","client","mac","mode","version"),sys.argv[1:]))))\' "$reason" "$CLIENT_NAME" "$CLIENT_MAC" "$CLIENT_MODE" "0.12")',
            '  api_post -d "$payload" "$SERVER_URL/api/clients/need-server" >/dev/null',
            '}',
            '',
            'release(){',
            '  curl -fsS --max-time 15 -H "Authorization: Bearer $TOKEN" -X POST "$SERVER_URL/api/clients/release-server" >/dev/null || true',
            '}',
            '',
            'waitsrv(){',
            '  for i in {1..120}; do',
            '    curl -fsS --max-time 3 "$SERVER_URL/api/health" >/dev/null 2>&1 && return 0',
            '    sleep 5',
            '  done',
            '  return 1',
            '}',
            '',
            'wake_recover(){',
            '  [ -n "${IPMI_RECOVER_URL:-}" ] || return 0',
            '  curl -fsS --max-time "${WAKE_TIMEOUT:-40}" "$IPMI_RECOVER_URL" >/dev/null || true',
            '}',
            '',
            'wake_wol(){',
            '  [ -n "${SERVER_MAC:-}" ] || { echo "SERVER_MAC ist nicht gesetzt."; return 0; }',
            '  if command -v wakeonlan >/dev/null 2>&1; then',
            '    wakeonlan "$SERVER_MAC" >/dev/null || true',
            '  elif command -v etherwake >/dev/null 2>&1; then',
            '    etherwake "$SERVER_MAC" >/dev/null || true',
            '  else',
            '    echo "Wake-on-LAN Werkzeug fehlt: wakeonlan oder etherwake installieren."',
            '  fi',
            '}',
            '',
            'wake_server(){',
            '  case "${WAKE_METHOD:-recover}" in',
            '    recover) wake_recover ;;',
            '    wol) wake_wol ;;',
            '    both) wake_recover; wake_wol ;;',
            '    none) : ;;',
            '    *) wake_recover ;;',
            '  esac',
            '}',
            '',
            'enable_heartbeat(){ systemctl --user enable --now server-manager-client-heartbeat.timer >/dev/null 2>&1 || true; }',
            'disable_heartbeat(){ systemctl --user disable --now server-manager-client-heartbeat.timer >/dev/null 2>&1 || true; }',
            '',
            'set_mode(){',
            '  CLIENT_MODE="$1"',
            '  save_config',
            '  case "$CLIENT_MODE" in',
            '    with_server) enable_heartbeat; echo "Modus gespeichert: Client start mit Server" ;;',
            '    without_server) release; enable_heartbeat; echo "Modus gespeichert: Client ohne Server" ;;',
            '    wake_on_access) release; enable_heartbeat; echo "Modus gespeichert: Client start ohne Wecken / Wake-on-access" ;;',
            '  esac',
            '}',
            '',
            'auto_start(){',
            '  case "${CLIENT_MODE:-without_server}" in',
            '    with_server)',
            '      wake_server',
            '      waitsrv || true',
            '      need "auto" || true',
            '      enable_heartbeat',
            '      ;;',
            '    without_server)',
            '      release || true',
            '      enable_heartbeat',
            '      ;;',
            '    wake_on_access)',
            '      enable_heartbeat',
            '      ;;',
            '    connected|auto)',
            '      # Kompatibilität mit älteren Manager-Modi.',
            '      CLIENT_MODE="with_server"; save_config',
            '      wake_server; waitsrv || true; need "auto" || true; enable_heartbeat',
            '      ;;',
            '    release-only|disabled)',
            '      CLIENT_MODE="without_server"; save_config',
            '      release || true; enable_heartbeat',
            '      ;;',
            '  esac',
            '}',
            '',
            'status(){',
            '  echo "Server Manager Client"',
            '  echo "Server:      $SERVER_URL"',
            '  echo "Client:      $CLIENT_NAME"',
            '  echo "Modus:       $CLIENT_MODE"',
            '  echo "Wake:        $WAKE_METHOD"',
            '  echo "Recover URL: $IPMI_RECOVER_URL"',
            '  echo "Server MAC:  ${SERVER_MAC:-nicht gesetzt}"',
            '  echo',
            '  curl -fsS --max-time 5 -H "Authorization: Bearer $TOKEN" "$SERVER_URL/api/health" || true',
            '  echo',
            '}',
            '',
            'config_menu(){',
            '  require_terminal || return 1',
            '  while true; do',
            '    if [ -t 1 ] && [ -n "${TERM:-}" ]; then clear 2>/dev/null || true; fi',
            '    echo "Client config"',
            '    echo "============="',
            '    echo "1) Wake-Methode setzen       aktuell: $WAKE_METHOD"',
            '    echo "2) IPMI-Recover-URL setzen   aktuell: $IPMI_RECOVER_URL"',
            '    echo "3) Server-MAC fuer WoL setzen aktuell: ${SERVER_MAC:-nicht gesetzt}"',
            '    echo "4) Wake-Timeout setzen       aktuell: ${WAKE_TIMEOUT:-40}"',
            '    echo "5) Config anzeigen (Token verborgen)"',
            '    echo "6) Server-Adresse ändern   aktuell: $SERVER_URL"',
            '    echo "7) Client-Name ändern      aktuell: $CLIENT_NAME"',
            '    echo "8) Token ändern"',
            '    echo "9) Client-MAC ändern       aktuell: $CLIENT_MAC"',
            '    echo "0) Zurueck"',
            '    read -rp "Auswahl: " c || return 0',
            '    case "$c" in',
            '      1) edit_config WAKE_METHOD "Wake-Methode (recover/wol/both/none)" ;;',
            '      2) edit_config IPMI_RECOVER_URL "IPMI-Recover-URL" ;;',
            '      3) edit_config SERVER_MAC "Server-MAC" ;;',
            '      4) edit_config WAKE_TIMEOUT "Wake-Timeout Sekunden" ;;',
            '      5) sed \'/^TOKEN=/d\' "$CFG"; echo "TOKEN=(verborgen)" ;;',
            '      6) edit_config SERVER_URL "Server-Adresse (http://host:port)" ;;',
            '      7) edit_config CLIENT_NAME "Client-Name" ;;',
            '      8) read -r -s -p "Neuer Token (Enter = unverändert): " value || return 0; echo; if [ -n "$value" ]; then TOKEN="$value"; save_config; fi ;;',
            '      9) edit_config CLIENT_MAC "Client-MAC" ;;',
            '      0) return ;;',
            '    esac',
            '  done',
            '}',
            '',
            'menu(){',
            '  require_terminal || return 1',
            '  while true; do',
            '    if [ -t 1 ] && [ -n "${TERM:-}" ]; then clear 2>/dev/null || true; fi',
            '    echo "Server Manager Client"',
            '    echo "=========================="',
            '    echo "Modus: $CLIENT_MODE"',
            '    echo "Wake:  $WAKE_METHOD"',
            '    echo',
            '    echo "1) Modus: Client start mit Server"',
            '    echo "2) Modus: Client ohne Server"',
            '    echo "3) Modus: Client start ohne Wecken / Wake-on-access"',
            '    echo "4) Einmalig: Server wecken"',
            '    echo "5) Einmalig: Server benoetigt"',
            '    echo "6) Server freigeben"',
            '    echo "7) Status"',
            '    echo "8) Client config"',
            '    echo "0) Ende"',
            '    read -rp "Auswahl: " c || return 0',
            '    case "$c" in',
            '      1) set_mode with_server; wake_server; waitsrv || true; need auto || true ;;',
            '      2) set_mode without_server ;;',
            '      3) set_mode wake_on_access ;;',
            '      4) wake_server; waitsrv || true ;;',
            '      5) need manual || true ;;',
            '      6) release; echo "Server freigegeben." ;;',
            '      7) status ;;',
            '      8) config_menu ;;',
            '      0) exit 0 ;;',
            '    esac',
            '    read -rp "Enter..." || return 0',
            '  done',
            '}',
            '',
            'case "${1:-menu}" in',
            '  auto) auto_start ;;',
            '  need) need "${2:-manual}" ;;',
            '  release) release ;;',
            '  wake) wake_server; waitsrv || true ;;',
            '  connect) set_mode with_server; wake_server; waitsrv || true; need auto || true ;;',
            '  access) wake_server; waitsrv || true ;;',
            '  status) status ;;',
            '  config) config_menu ;;',
            '  menu|*) menu ;;',
            'esac',
            'EOF',
            'chmod +x "$APPDIR/server-manager-client"',
            '',
            'cat > "$APPDIR/server-manager-client-heartbeat" <<\'EOF\'',
            '#!/bin/bash',
            'set -euo pipefail',
            'source "$HOME/.config/server-manager-client/config"',
            'required=false',
            'reason="$CLIENT_MODE"',
            'case "$CLIENT_MODE" in',
            '  with_server) required=true; reason="auto" ;;',
            '  without_server) required=false; reason="without_server" ;;',
            '  wake_on_access) required=false; reason="wake_on_access" ;;',
            '  connected) required=true; reason="auto" ;;',
            '  auto|release-only|disabled) required=false; reason="$CLIENT_MODE" ;;',
            'esac',
            'curl -fsS --max-time 10 \\',
            '  -H "Authorization: Bearer $TOKEN" \\',
            '  -H "Content-Type: application/json" \\',
            '  -X POST \\',
            '  -d "$(python3 -c \'import json,sys; d=dict(zip(("client","mac","mode","reason"),sys.argv[1:5])); d.update(version="0.12",server_required=sys.argv[5]=="true"); print(json.dumps(d))\' "$CLIENT_NAME" "$CLIENT_MAC" "$CLIENT_MODE" "$reason" "$required")" \\',
            '  "$SERVER_URL/api/clients/heartbeat" >/dev/null || true',
            'EOF',
            'chmod +x "$APPDIR/server-manager-client-heartbeat"',
            '',
            'cat > "$SYSDIR/server-manager-client.service" <<\'EOF\'',
            '[Unit]',
            'Description=Server Manager Client Autostart',
            'After=network-online.target',
            'Wants=network-online.target',
            '[Service]',
            'Type=oneshot',
            'ExecStart=%h/.local/bin/server-manager-client auto',
            '[Install]',
            'WantedBy=default.target',
            'EOF',
            '',
            'cat > "$SYSDIR/server-manager-client-heartbeat.service" <<\'EOF\'',
            '[Unit]',
            'Description=Server Manager Client Heartbeat',
            '[Service]',
            'Type=oneshot',
            'ExecStart=%h/.local/bin/server-manager-client-heartbeat',
            'EOF',
            '',
            'cat > "$SYSDIR/server-manager-client-heartbeat.timer" <<\'EOF\'',
            '[Unit]',
            'Description=Server Manager Client Heartbeat Timer',
            '[Timer]',
            'OnBootSec=30',
            'OnUnitActiveSec=60',
            'AccuracySec=10',
            'Unit=server-manager-client-heartbeat.service',
            '[Install]',
            'WantedBy=timers.target',
            'EOF',
            '',
            'if ! systemctl --user daemon-reload; then',
            '  echo "Hinweis: Keine systemd-Benutzersitzung. Manuelle Konfiguration ist möglich; Autostart nach Anmeldung erneut installieren." >&2',
            'fi',
            'systemctl --user enable server-manager-client.service >/dev/null 2>&1 || true',
            'systemctl --user enable --now server-manager-client-heartbeat.timer >/dev/null 2>&1 || true',
            'echo "Installiert: Server Manager Client"',
            'echo "Start: ~/.local/bin/server-manager-client"',
            'echo "Config: ~/.config/server-manager-client/config"',
            'echo "Einrichtung: ~/.local/bin/server-manager-client config"',
            'if [ "${1:-}" != "--no-menu" ] && [ -t 0 ]; then',
            '  "$APPDIR/server-manager-client" menu',
            'fi',
        ]
        script = "\n".join(lines) + "\n"
        return Response(script, mimetype="text/x-shellscript", headers={"Content-Disposition": f'attachment; filename="{safe}.sh"'})
