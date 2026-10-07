from ui_translation import html_literal as _ui_html, text as _ui_text
from i18n import tr, language
from ui_translation import asset_url
from responsive_ui import CSS as RESPONSIVE_CSS, script as responsive_script
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Heimserver Manager Core

Core:
- klare Core-App
- Plugin-/Modul-Loader
- keine Funktionspatches in app.py mehr
- Module registrieren sich über register(app, ctx)
"""

import os
import socket
import json
import sqlite3
import importlib
from datetime import datetime
from pathlib import Path
from flask import send_file, request, redirect, Flask, Response, Request

import server_settings
server_settings.activate_pending()
from version import VERSION
BRANCH = "core-plugin-loader"
PORT = int(os.environ.get("SERVER_MANAGER_PORT", "9877"))
BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("SERVER_MANAGER_STATE", "/var/lib/server-manager"))
DB_PATH = Path(os.environ.get("SERVER_MANAGER_DB", str(STATE_DIR / "server-manager.sqlite3")))

class ManagerRequest(Request):
    """Per-request upload limits also work with Flask before 3.1 (Mint)."""
    @property
    def max_content_length(self):
        if '_manager_content_limit' in self.__dict__:
            return self._manager_content_limit
        return super().max_content_length

    @max_content_length.setter
    def max_content_length(self, value):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ValueError('Invalid request content limit')
        self._manager_content_limit = value


app = Flask(__name__)
app.request_class = ManagerRequest
from manager_proxy import configure as configure_manager_proxy
configure_manager_proxy(app, server_settings.CONFIG_DIR / "manager-https.json")
from authentication import register as register_authentication
authentication_toolbar = register_authentication(app, server_settings.CONFIG_DIR)
from tools.migrate_auth_timers import migrate as migrate_auth_timers
migrate_auth_timers(BASE_DIR, server_settings.CONFIG_DIR)

def db():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
    except Exception:
        pass
    return con

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def esc(x):
    import html
    return html.escape(str(x or ""))

def init_db():
    con = db()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        try:
            cols = [r["name"] for r in con.execute("PRAGMA table_info(meta)").fetchall()]
            if "updated_at" not in cols:
                con.execute("ALTER TABLE meta ADD COLUMN updated_at TEXT")
        except Exception:
            pass
        con.execute("""
            CREATE TABLE IF NOT EXISTS module_registry (
                name TEXT PRIMARY KEY,
                status TEXT,
                message TEXT,
                loaded_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        con.execute("""
            INSERT INTO meta(key,value,updated_at)
            VALUES('version', ?, datetime('now','localtime'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (VERSION,))
        con.execute("""
            INSERT INTO meta(key,value,updated_at)
            VALUES('branch', ?, datetime('now','localtime'))
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (BRANCH,))
        con.commit()
    finally:
        con.close()

def record_module(name, status, message=""):
    con = db()
    try:
        con.execute("""
            INSERT INTO module_registry(name,status,message,loaded_at)
            VALUES(?,?,?,datetime('now','localtime'))
            ON CONFLICT(name) DO UPDATE SET
                status=excluded.status,
                message=excluded.message,
                loaded_at=excluded.loaded_at
        """, (name, status, str(message or "")))
        con.commit()
    finally:
        con.close()

NAV_GROUPS = [
    ("Übersicht", "/", []),
    ("Freigaben & Benutzer", "/freigaben", []),
    ("Server", "/server", [("Serverstatus", "/server"), ("Speicher", "/speicher"), ("Web & Sicherheit", "/web-security"), ("Schlaf & Wake", "/sleep"), ("Zeitpläne", "/sleep/schedules"), ("Schlafblocker", "/server-control")]),
    ("Netzwerk", "/heimnetz", [("Geräteübersicht", "/heimnetz"), ("Client-Agenten", "/clients"), ("Anwesenheit", "/presence/status")]),
    ("DynDNS", "/dyndns", [("DynDNS", "/dyndns")]),
    ("Virtuelle Maschinen", "/kvm", [("Virtuelle Maschinen", "/kvm"), ("Backup & Recovery", "/kvm/backups")]),
    ("Anwendungen", "/apps", [("Meine Apps", "/apps"), ("Apps verwalten", "/apps/manage"), ("Treiber", "/apps/drivers")]),
    ("Daten", "/downloads", [ ("Downloads", "/downloads"), ("Backup & Recovery", "/backup/central"), ("Fotolabor", "/fotolabor"), ("Scanner API für Home Assistant", "/scanner")]),
    ("TV & Aufnahmen", "/tv", [("Überblick", "/tv"), ("Aufnahmen", "/tv/recordings"), ("Geplant", "/tv/upcoming"), ("Programm suchen", "/tv/epg"), ("Live-TV", "/tv/streams"), ("Aufwachen", "/tv/rtc"), ("Verbindung", "/tv/status")]),
    ("Alarme", "/alarme", []),
    ("Einstellungen", "/settings", [("Allgemein", "/settings"), ("Sprachen", "/settings/languages"), ("Server & Modulpfade", "/settings/server-paths"), ("Zugang", "/settings/access"), ("Manager-Benutzer", "/settings/users"), ("HTTPS", "/settings/https"), ("Reparaturskripte", "/settings/repairs"), ("Manager aktualisieren", "/settings/manager-update"), ("Installationsauswahl", "/settings/installation"), ("Modulauswahl", "/settings/modules"), ("Moduldiagnose", "/modules")]),
]

from modules.module_selection import config as module_choices
from modules.first_start import config as installation_choices

def active_nav_groups():
    from modules.accounts.policy import navigation as account_navigation
    return account_navigation(installation_choices.navigation(module_choices.visible_groups(NAV_GROUPS)))

def nav_items():
    return [(label, url) for label, url, _ in active_nav_groups()]

def navigation(path, account=""):
    groups=active_nav_groups()
    matches = []
    for group, home, children in groups:
        for label, url in children or [(group, home)]:
            if path == url or (url != '/' and path.startswith(url + '/')):
                matches.append((len(url), group, url))
    _, selected, selected_url = max(matches, default=(0, 'Übersicht', '/'))
    # Presence has sibling routes for status and settings.
    if path.startswith('/presence/'):
        selected, selected_url = 'Netzwerk', '/presence/status'
    if path.startswith(('/backup', '/recovery')):
        selected, selected_url = 'Daten', '/backup/central'
    if path.startswith('/updates'):
        selected, selected_url = 'Anwendungen', '/apps'
    def link(label, url, active):
        return _ui_html("<a class='btn{}' href='{}'{}>{}</a>").format(' active' if active else '', esc(url), " aria-current='page'" if active else '', esc(tr(label)))
    primary = "<nav aria-label='" + esc(tr("Hauptbereiche")) + "' class='main-nav'>" + ''.join(link(label, url, label == selected) for label, url, _ in groups) + account + '</nav>'
    children = next((children for label, _, children in groups if label == selected),[])
    secondary = ("<nav aria-label='" + esc(tr(selected)) + " – " + esc(tr("Unterseiten")) + "' class='sub-nav'>" + ''.join(link(label, url, url == selected_url) for label, url in children) + '</nav>') if children else ''
    return primary + secondary

def page(title, body, current=""):
    from modules.accounts.policy import filter_html, current as current_account
    body=filter_html(body)
    from tools.platform_check import mint_desktop
    if mint_desktop():
        body=_ui_html('<div class="card"><b>Linux Mint · experimenteller Teststand</b><p>Automatische Schlaf-/RTC-Steuerung und Debian-Treiberinstaller sind gesperrt. Optionale App-Installer sind noch nicht vollständig für Mint geprüft.</p></div>')+body
    title = {"Server Control": "Schlafblocker", "Presence": "Anwesenheit", "Presence Status": "Anwesenheit", "Clients": "Client-Agenten"}.get(title, title)
    title = tr(title)
    body = body.replace("Heimserver Manager", tr(_ui_text("Heimserver Manager")))
    links = navigation(request.path, authentication_toolbar())
    return _ui_html("""<!doctype html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {brand}</title>
<script src="{translation_asset}"></script>
<style>
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#111827;color:#e5e7eb;margin:0;padding:24px}}
a{{color:#93c5fd;text-decoration:none}}
.card{{background:#1f2937;border:1px solid #374151;border-radius:14px;padding:16px;margin:0 0 16px 0;box-shadow:0 2px 8px #0004}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}
.btn,.pill{{display:inline-block;background:#374151;color:#f9fafb;padding:8px 11px;border-radius:9px;margin:3px;border:1px solid #4b5563}}
.btn:hover,.pill:hover,.active{{background:#4b5563}}
.header-identity{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}}
.host-info{{margin-left:auto;text-align:right;max-width:65%;overflow-wrap:anywhere;font-size:.9rem;color:#cbd5e1}}
.host-name{{display:block}}
.host-info-link{{display:inline-block;margin-top:5px;text-decoration:underline;text-underline-offset:3px}}
.host-info-link:focus-visible{{outline:2px solid #93c5fd;outline-offset:4px}}
.main-nav,.sub-nav{{display:flex;flex-wrap:wrap;gap:4px}}
.main-nav .active{{background:#1d4ed8;border-color:#60a5fa}}
.sub-nav{{margin-top:12px;padding-top:12px;border-top:1px solid #4b5563}}
.sub-nav .btn{{background:transparent}}
.sub-nav .active{{background:#374151;border-color:#93c5fd}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{border-bottom:1px solid #374151;padding:8px;text-align:left;vertical-align:top}}
th{{color:#cbd5e1}}
code,pre{{background:#0b1220;border:1px solid #374151;border-radius:8px;padding:2px 5px}}
pre{{padding:12px;overflow:auto}}
.ok{{color:#86efac}} .warn{{color:#fde68a}} .err{{color:#fca5a5}}
{responsive_css}
.main-nav{{align-items:center}}
.account-menu{{position:relative;margin-left:auto;max-width:100%}}
.account-menu>summary{{cursor:pointer;list-style:none;white-space:nowrap;padding:10px 12px;border:1px solid #64748b;border-radius:9px;background:#374151;min-height:44px;box-sizing:border-box}}
.account-menu>summary::-webkit-details-marker{{display:none}}
.account-menu>summary::after{{content:' ▾'}}
.account-menu[open]>summary::after{{content:' ▴'}}
.account-menu-content{{position:absolute;right:0;top:calc(100% + 8px);z-index:1000;width:340px;max-width:calc(100vw - 64px);padding:16px;background:#1f2937;border:1px solid #64748b;border-radius:12px;box-shadow:0 6px 20px #0008}}
.account-toolbar{{display:flex;flex-wrap:wrap;gap:12px;align-items:center}}
.account-menu-content .account-notice{{margin:12px 0}}
.account-menu-content .language-selector{{margin:12px 0 0!important}}
@media(max-width:700px){{.account-menu{{grid-column:1/-1;margin-left:0}}.account-menu-content{{position:static;width:auto;max-width:100%;margin-top:8px}}}}
</style>
</head>
<body>
<a class="skip-link" href="#main-content">{skip_label}</a>
<header class="card app-header"><div class="header-identity"><a class="app-brand" href="/">{brand}</a><div class="host-info"><span class="host-name">Host: <strong>{hostname}</strong></span><a class="host-info-link" href="{info_url}">Info</a></div></div><h1>{title}</h1><details class="navigation-panel" open><summary>{menu_label}</summary><div class="navigation-content">{links}</div></details></header>
<main id="main-content" tabindex="-1">{body}</main>
{responsive_script}
</body>
</html>""").format(translation_asset=asset_url(language()),info_url=("/account" if current_account() and current_account()["role"]!="admin" else "/settings/info"),hostname=esc(socket.gethostname()), title=esc(title), brand=esc(tr(_ui_text("Heimserver Manager"))), language=language(), links=links, body=body, responsive_css=RESPONSIVE_CSS, responsive_script=responsive_script(tr("Tabelle – bei Bedarf horizontal scrollen")), menu_label=esc(tr(_ui_text("Menü & Konto"))), skip_label=esc(tr("Zum Inhalt")))

def card(title, text, links=None):
    link_html = ""
    if links:
        link_html = _ui_html("<p>") + " ".join(_ui_html("<a class='btn' href='{u}'>{l}</a>").format(u=u, l=esc(tr(l))) for l, u in links) + _ui_html("</p>")
    return _ui_html("<div class='card'><h3>{}</h3><p>{}</p>{}</div>").format(esc(tr(title)), text, link_html)

class AppContext:
    def __init__(self):
        self.version = VERSION
        self.branch = BRANCH
        self.base_dir = BASE_DIR
        self.state_dir = STATE_DIR
        self.db_path = DB_PATH
        self.db = db
        self.page = page
        self.card = card
        self.esc = esc
        self.now = now
        self.init_db = init_db
        self.Response = Response

def load_plugins():
    """
    Lädt Module aus /modules.

    Unterstützte Formen:
    1. modules/<name>.py mit register(app, ctx)
    2. modules/<package>/plugin.py mit register(app, ctx)

    app.py wird danach nicht mehr für neue Funktionen gepatcht.
    """
    ctx = AppContext()
    modules_dir = BASE_DIR / "modules"
    modules_dir.mkdir(exist_ok=True)
    loaded = []

    # Einzeldatei-Module
    for p in sorted(modules_dir.glob("*.py")):
        if p.name == "__init__.py" or p.name.startswith("_"):
            continue
        modname = "modules." + p.stem
        if not installation_choices.plugin_enabled(modname):
            record_module(modname, "disabled", "Nicht zur Installation ausgewählt")
            continue
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "register"):
                mod.register(app, ctx)
                record_module(modname, "ok", "registered")
                loaded.append(modname)
            else:
                record_module(modname, "skipped", "no register(app, ctx)")
        except Exception as e:
            record_module(modname, "error", repr(e))
            print("Plugin load failed:", modname, e)

    # Paket-Plugins
    for d in sorted([x for x in modules_dir.iterdir() if x.is_dir() and not x.name.startswith("_")]):
        plugin = d / "plugin.py"
        if not plugin.exists():
            continue
        modname = "modules." + d.name + ".plugin"
        if not installation_choices.plugin_enabled(modname):
            record_module(modname, "disabled", "Nicht zur Installation ausgewählt")
            continue
        try:
            mod = importlib.import_module(modname)
            if hasattr(mod, "register"):
                mod.register(app, ctx)
                record_module(modname, "ok", "registered")
                loaded.append(modname)
            else:
                record_module(modname, "skipped", "no register(app, ctx)")
        except Exception as e:
            record_module(modname, "error", repr(e))
            print("Plugin load failed:", modname, e)

    return loaded

@app.route("/")
def index():
    init_db()
    descriptions = {
        "Server": "Betrieb, Speicher, Schlaf- und Weckzeiten und Schlafblocker.",
        "Freigaben & Benutzer": "SMB-/NFS-Freigaben, Benutzer, Gruppen und Zugriffsrechte verwalten.",
        "DynDNS": "Hostnamen, Anbieter und automatische IP-Aktualisierungen verwalten.",
        "Virtuelle Maschinen": "Virtuelle Maschinen verwalten, sichern und wiederherstellen.",
        "Netzwerk": "Geräte im Heimnetz, Client-Agenten und Anwesenheit.",
        "Anwendungen": "Programme installieren und deinstallieren, Updates durchführen sowie Backups erstellen und wiederherstellen.",
        "TV & Aufnahmen": "Fernsehprogramm, Live-TV, Aufnahmen und Aufwachplanung.",
        "Daten": "Downloads, Sicherungen, Bilder und Scans.",
        "Alarme": "Warnungen, Überwachung und ntfy-Benachrichtigungen.",
        "Einstellungen": "Grundeinstellungen und Informationen zum Heimserver Manager.",
    }
    body = ""
    if not module_choices.load()['configured']:
        body+=_ui_html("<div class='card'><h2>Module für diesen Server auswählen</h2><p>Haupt- oder Nebenserver: Lege fest, ob hier Heimnetz/Anwesenheit und TV & Aufnahmen benötigt werden.</p><a class='btn' href='/settings/modules'>Modulauswahl öffnen</a></div>")
    body += _ui_html("<div class='grid'>")
    for label, url, children in active_nav_groups()[1:]:
        if label == "Freigaben & Benutzer":
            children = [("Übersicht", "/freigaben"), ("Benutzer", "/freigaben/users"), ("Benutzerrechte", "/freigaben/rechte"), ("Gruppen", "/freigaben/groups"), ("Domäne (optional)", "/freigaben/domain"), ("Neue Freigabe", "/freigaben/new"), ("Client-Dateien", "/freigaben/downloads"), ("Diagnose", "/freigaben/diagnose"), ("SMB/NFS installieren / prüfen", "/apps/shares_mounts/installer")]
        if label == "Alarme":
            children = [("Alarme", "/alarme")]
        body += card(label, esc(_ui_text(descriptions.get(label, "Bereich öffnen und Funktionen auswählen."))), children)
    body += _ui_html("</div>")
    return page(_ui_text("Heimserver Manager"), body, "Übersicht")


@app.route("/api/health")
def api_health():
    init_db()
    return Response(json.dumps({
        "ok": True,
        "version": VERSION,
        "time": now(),
    }, ensure_ascii=False, indent=2), mimetype="application/json")

@app.route("/modules")
def modules_page():
    init_db()
    con = db()
    try:
        rows = con.execute("SELECT * FROM module_registry ORDER BY name").fetchall()
    finally:
        con.close()
    body = _ui_html("<div class='card'><h2>Module</h2><p>Geladene Module.</p></div>")
    body += _ui_html("<div class='card'><table><tr><th>Name</th><th>Status</th><th>Meldung</th><th>Geladen</th></tr>")
    internal_helpers = {
        "modules.heimnetz_client_blocker_provider": "Client-Schlafblocker",
        "modules.rtc_planner": "RTC-Weckplanung",
        "modules.vendor_resolver": "Gerätehersteller-Erkennung",
    }
    for r in rows:
        status, message = r["status"], r["message"]
        cls = "ok" if status == "ok" else "warn" if status == "skipped" else "err"
        if (status == "skipped" and message == "no register(app, ctx)"
                and r["name"] in internal_helpers):
            status = "Intern eingebunden"
            message = (internal_helpers[r["name"]]
                       + ": Wird von anderen Modulen verwendet; keine eigene Weboberfläche.")
            cls = "ok"
        body += _ui_html("<tr><td><code>{}</code></td><td class='{}'>{}</td><td>{}</td><td>{}</td></tr>").format(
            esc(r["name"]), cls, esc(_ui_text(status)), esc(_ui_text(message)), esc(r["loaded_at"])
        )
    body += _ui_html("</table></div>")
    return page(_ui_text("Module"), body, "Einstellungen")

# /server wird vom Manager-Modul modules/server/plugin.py bereitgestellt.

@app.route("/presence")
def presence():
    return redirect("/presence/status")


@app.route("/settings/app-manager/maintenance", methods=["GET", "POST"])
def app_manager_maintenance():
    from modules.app_manager.settings import load_settings, save_settings, ensure_config, CONFIG_FILE, DEFAULT_SETTINGS
    import json
    import shutil
    from datetime import datetime
    from pathlib import Path

    msg = ""
    err = ""

    if request.method == "POST":
        try:
            action = request.form.get("action", "")

            if action == "reload":
                ensure_config()
                msg = "Konfiguration neu geladen."

            elif action == "reset":
                save_settings(dict(DEFAULT_SETTINGS))
                msg = "App-Manager-Konfiguration auf Standardwerte zurückgesetzt."

            elif action == "import":
                upload = request.files.get("config_file")
                if not upload or not upload.filename:
                    raise RuntimeError("Keine Konfigurationsdatei hochgeladen.")

                raw = upload.read().decode("utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise RuntimeError("Importdatei enthält kein JSON-Objekt.")

                backup = Path(str(CONFIG_FILE) + ".bak.import." + datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
                if CONFIG_FILE.exists():
                    shutil.copy2(CONFIG_FILE, backup)

                save_settings(data)
                msg = "Konfiguration importiert. Vorherige Datei gesichert: {}".format(backup)

        except Exception as e:
            err = str(e)

    cfg = load_settings()

    body = _ui_html("<div class='card'><h2>App-Manager Wartung</h2>")
    body += _ui_html("<p><a class='btn' href='/settings'>Zurück zu Einstellungen</a> ")
    body += _ui_html("<a class='btn' href='/settings/app-manager/tokens'>Token</a></p>")
    body += _ui_html("<p>Konfiguration: <code>{}</code></p>").format(esc(str(CONFIG_FILE)))

    if msg:
        body += _ui_html("<p class='ok'><b>{}</b></p>").format(esc(_ui_text(msg)))
    if err:
        body += _ui_html("<p class='err'><b>{}</b></p>").format(esc(_ui_text(err)))

    body += _ui_html("<h3>Export</h3>")
    body += _ui_html("<p><a class='btn' href='/settings/app-manager/maintenance/export'>Konfiguration herunterladen</a></p>")

    body += _ui_html("<h3>Import</h3>")
    body += _ui_html("<form method='post' enctype='multipart/form-data'>")
    body += _ui_html("<input type='hidden' name='action' value='import'>")
    body += _ui_html("<p><input type='file' name='config_file' accept='.json,application/json' required></p>")
    body += _ui_html("<button class='btn' type='submit'>Konfiguration importieren</button>")
    body += _ui_html("</form>")

    body += _ui_html("<h3>Neu laden</h3>")
    body += _ui_html("<form method='post'>")
    body += _ui_html("<input type='hidden' name='action' value='reload'>")
    body += _ui_html("<button class='btn' type='submit'>Konfiguration neu laden</button>")
    body += _ui_html("</form>")

    body += _ui_html("<h3>Zurücksetzen</h3>")
    body += _ui_html("<form method='post' onsubmit=\"return confirm('App-Manager-Konfiguration wirklich auf Standardwerte zurücksetzen?')\">")
    body += _ui_html("<input type='hidden' name='action' value='reset'>")
    body += _ui_html("<button class='btn err' type='submit'>Werkseinstellungen wiederherstellen</button>")
    body += _ui_html("</form>")

    body += _ui_html("<h3>Aktuelle Konfiguration</h3>")
    body += _ui_html("<details><summary>Anzeigen</summary><pre>{}</pre></details>").format(
        esc(json.dumps(cfg, ensure_ascii=False, indent=2))
    )

    body += _ui_html("</div>")
    return page(_ui_text("App-Manager Wartung"), body, "Einstellungen")


@app.route("/settings/app-manager/maintenance/export")
def app_manager_maintenance_export():
    from modules.app_manager.settings import ensure_config, CONFIG_FILE

    ensure_config()
    return send_file(
        CONFIG_FILE,
        as_attachment=True,
        download_name="app_manager.json",
        mimetype="application/json",
    )


@app.route("/settings/app-manager/tokens", methods=["GET", "POST"])
def app_manager_tokens():
    from modules.app_manager.settings import load_settings, save_settings, generate_token, CONFIG_FILE

    cfg = load_settings()
    msg = ""
    err = ""
    show = bool(request.args.get("show"))

    if request.method == "POST":
        try:
            action = request.form.get("action", "")

            if action == "save":
                data = {
                    "restore_confirm_token": request.form.get("restore_confirm_token", "").strip(),
                    "update_confirm_token": request.form.get("update_confirm_token", "").strip(),
                }
                save_settings(data)
                msg = "Token gespeichert."

            elif action == "generate_restore":
                save_settings({"restore_confirm_token": generate_token(12)})
                msg = "Restore-Token neu erzeugt."
                show = True

            elif action == "generate_update":
                save_settings({"update_confirm_token": generate_token(12)})
                msg = "Update-Token neu erzeugt."
                show = True

            elif action == "reset_defaults":
                save_settings({
                    "restore_confirm_token": "RESTORE",
                    "update_confirm_token": "UPDATE",
                })
                msg = "Token auf Standardwerte zurückgesetzt."
                show = True

            cfg = load_settings()

        except Exception as e:
            err = str(e)

    def token_value(key):
        value = str(cfg.get(key, "") or "")
        return value if show else ("*" * len(value) if value else "")

    body = _ui_html("<div class='card'><h2>App-Manager Token</h2>")
    body += _ui_html("<p><a class='btn' href='/settings'>Zurück zu Einstellungen</a></p>")
    body += _ui_html("<p>Konfiguration: <code>{}</code></p>").format(esc(str(CONFIG_FILE)))

    if msg:
        body += _ui_html("<p class='ok'><b>{}</b></p>").format(esc(_ui_text(msg)))
    if err:
        body += _ui_html("<p class='err'><b>{}</b></p>").format(esc(_ui_text(err)))

    body += _ui_html("<p>")
    if show:
        body += _ui_html("<a class='btn' href='/settings/app-manager/tokens'>Token verbergen</a>")
    else:
        body += _ui_html("<a class='btn' href='/settings/app-manager/tokens?show=1'>Token anzeigen</a>")
    body += _ui_html("</p>")

    body += _ui_html("<form method='post'>")
    body += _ui_html("<input type='hidden' name='action' value='save'>")

    body += _ui_html("<h3>Restore</h3>")
    body += _ui_html("<p>Restore-Bestätigungstoken<br>")
    body += _ui_html("<input name='restore_confirm_token' value='{}' style='width:260px'></p>").format(
        esc(token_value("restore_confirm_token"))
    )

    body += _ui_html("<h3>Update</h3>")
    body += _ui_html("<p>Update-Bestätigungstoken<br>")
    body += _ui_html("<input name='update_confirm_token' value='{}' style='width:260px'></p>").format(
        esc(token_value("update_confirm_token"))
    )

    body += _ui_html("<p><button class='btn' type='submit'>Token speichern</button></p>")
    body += _ui_html("</form>")

    body += "<hr>"

    body += _ui_html("<form method='post' style='display:inline'>")
    body += _ui_html("<input type='hidden' name='action' value='generate_restore'>")
    body += _ui_html("<button class='btn' type='submit'>Restore-Token neu erzeugen</button>")
    body += _ui_html("</form> ")

    body += _ui_html("<form method='post' style='display:inline'>")
    body += _ui_html("<input type='hidden' name='action' value='generate_update'>")
    body += _ui_html("<button class='btn' type='submit'>Update-Token neu erzeugen</button>")
    body += _ui_html("</form> ")

    body += _ui_html("<form method='post' style='display:inline' onsubmit=\"return confirm('Token wirklich auf RESTORE/UPDATE zurücksetzen?')\">")
    body += _ui_html("<input type='hidden' name='action' value='reset_defaults'>")
    body += _ui_html("<button class='btn err' type='submit'>Standard-Token wiederherstellen</button>")
    body += _ui_html("</form>")

    body += _ui_html("<h3>Hinweis</h3>")
    body += _ui_html("<p class='warn'>Token werden in <code>/etc/server-manager/app_manager.json</code> gespeichert. Zugriff auf diese Datei sollte auf root/server-manager beschränkt bleiben.</p>")

    body += _ui_html("</div>")

    return page(_ui_text("App-Manager Token"), body, "Einstellungen")


@app.route("/settings/languages")
def settings_languages():
    body = card(tr("Sprachen"), esc(tr("Englisch ist die Standardsprache. Die Auswahl gilt für diesen Browser.")) + app.extensions['manager_language_selector']())
    return page(tr("Sprachen"), body, "Einstellungen")


@app.route("/settings/info")
def settings_info():
    import json
    from pathlib import Path
    try:
        target=json.loads((Path(__file__).resolve().parent/'package-target.json').read_text())
    except (OSError,ValueError):target={}
    platform_label={'debian13':'Debian','mint22':'Mint'}.get(target.get('target'),'')
    release_label=VERSION+(' · '+platform_label if platform_label else '')
    body = _ui_html("<div class='card'><h2>Heimserver Manager</h2><p>Version: <strong>V{}</strong></p><p>Andreas Willibald</p>").format(esc(_ui_text(release_label)))
    if target.get("experimental"):body+=_ui_html("<p>Experimenteller Entwicklungsstand</p>")
    body += _ui_html("<h3>Lizenz</h3><p><strong>GNU General Public License – Version 3 oder neuer</strong><br><code>GPL-3.0-or-later</code></p>")
    body += _ui_html("<p>Eigene Projektbestandteile und Dokumentation sind freie Software unter dieser Lizenz. Fremdkomponenten behalten ihre eigenen Lizenzen; das mitgelieferte Makeself steht unter GPL-2.0-or-later.</p>")
    from pathlib import Path
    for filename, label in (("LICENSE", "Vollständiger GPL-3-Lizenztext"), ("LICENSE_NOTICE.md", "Freigabehinweis: Version 3 oder neuer"), ("THIRD_PARTY_NOTICES.md", "Hinweise zu Fremdkomponenten")):
        try:
            text = (Path(__file__).resolve().parent / filename).read_text(encoding="utf-8")
        except OSError:
            text = "Lizenzdatei fehlt in dieser Installation. Bitte das vollständige Veröffentlichungspaket verwenden."
        body += _ui_html("<details><summary>")+esc(_ui_text(label))+_ui_html("</summary><pre style='white-space:pre-wrap;overflow-wrap:anywhere'>")+esc(text)+_ui_html("</pre></details>")
    body += _ui_html("</div>")
    return page(_ui_text("Info"), body, "Einstellungen")

@app.route("/settings", methods=["GET", "POST"])
def settings():
    from modules.app_manager.settings import load_settings, save_settings, CONFIG_FILE

    msg = ""
    err = ""

    if request.method == "POST":
        try:
            data = {

                "restore_execution_enabled": bool(request.form.get("restore_execution_enabled")),
                "restore_require_token": bool(request.form.get("restore_require_token")),
                "restore_require_rollback": bool(request.form.get("restore_require_rollback")),

                "update_execution_enabled": bool(request.form.get("update_execution_enabled")),
                "update_require_token": bool(request.form.get("update_require_token")),

                "live_refresh_seconds": int(request.form.get("live_refresh_seconds", "2") or 2),
                "show_json_details": bool(request.form.get("show_json_details")),
            }

            # Token werden in 5.8c separat verwaltet.
            save_settings(data)
            msg = "App-Manager-Einstellungen gespeichert."
        except Exception as e:
            err = str(e)

    cfg = load_settings()

    def checked(key):
        return "checked" if cfg.get(key) else ""

    body = card(tr("Sprache"), esc(tr(_ui_text("Die Sprachwahl gilt für diesen Browser. Eigene Namen, Pfade und technische Protokolle bleiben unverändert."))) + app.extensions['manager_language_selector']())
    body += _ui_html("<div class='grid'>")
    body += card(_ui_text("Modulauswahl"), _ui_html("Heimnetz/Anwesenheit und TV für Haupt- oder Nebenserver auswählen."), [("Module auswählen", "/settings/modules")])
    body += card(_ui_text("Manager aktualisieren"), _ui_html("Heimserver-Manager-DEB hochladen, prüfen und als Hintergrundauftrag installieren."), [("Update öffnen", "/settings/manager-update")])
    body += card(_ui_text("Manager-Zugang · HTTPS"), _ui_html("Privater Hostname und Zertifikat; öffentliche Domain später optional einrichten."), [("HTTPS einrichten", "/settings/https")])
    body += card(_ui_text("Reparaturskripte"), _ui_html("Gezielte Reparaturen mit Vorschau, Sicherungen und Ergebnisprotokoll."), [("Reparaturskripte öffnen", "/settings/repairs")])
    body += card(_ui_text("Allgemein"), _ui_html("State: <code>{}</code><br>DB: <code>{}</code>").format(STATE_DIR, DB_PATH))
    body += card(_ui_text("Core"), _ui_html("Plugin Loader aktiv. Neue Funktionen kommen nur noch über Module."))
    body += _ui_html("</div>")

    body += _ui_html("<div class='card'><h2>App Manager</h2>")
    body += _ui_html("<p>Konfiguration: <code>{}</code></p>").format(esc(str(CONFIG_FILE)))

    if msg:
        body += _ui_html("<p class='ok'><b>{}</b></p>").format(esc(_ui_text(msg)))
    if err:
        body += _ui_html("<p class='err'><b>{}</b></p>").format(esc(_ui_text(err)))

    body += _ui_html("<form method='post'>")

    body += _ui_html("<h3>Server & Modulpfade</h3><p>Datenordner, Backup-Ziele, Netzwerk und App-Pfade zentral verwalten.</p><p><a class='btn' href='/settings/server-paths'>Server & Modulpfade öffnen</a></p>")

    body += _ui_html("<h3>Restore-Sicherheit</h3>")
    body += _ui_html("<p><label><input type='checkbox' name='restore_execution_enabled' {}> Restore-Ausführung erlauben</label></p>").format(checked("restore_execution_enabled"))
    body += _ui_html("<p><label><input type='checkbox' name='restore_require_token' {}> Restore-Bestätigungstoken erforderlich</label></p>").format(checked("restore_require_token"))
    body += _ui_html("<p><label><input type='checkbox' name='restore_require_rollback' {}> Rollback vor Restore erzwingen</label></p>").format(checked("restore_require_rollback"))
    body += _ui_html("<p>Restore-Token: <code>{}</code> <a class='btn' href='/settings/app-manager/tokens'>Token verwalten</a></p>").format(
        esc("gesetzt" if cfg.get("restore_confirm_token") else "nicht gesetzt")
    )

    body += _ui_html("<h3>Update-Sicherheit</h3>")
    body += _ui_html("<p><label><input type='checkbox' name='update_execution_enabled' {}> Update-Ausführung erlauben</label></p>").format(checked("update_execution_enabled"))
    body += _ui_html("<p><label><input type='checkbox' name='update_require_token' {}> Update-Bestätigungstoken erforderlich</label></p>").format(checked("update_require_token"))
    body += _ui_html("<p>Update-Token: <code>{}</code> <a class='btn' href='/settings/app-manager/tokens'>Token verwalten</a></p>").format(
        esc("gesetzt" if cfg.get("update_confirm_token") else "nicht gesetzt")
    )

    body += _ui_html("<h3>Live-Monitor</h3>")
    body += _ui_html("<p>Live-Aktualisierung in Sekunden<br><input name='live_refresh_seconds' value='{}' style='width:80px'></p>").format(
        esc(cfg.get("live_refresh_seconds", 2))
    )
    body += _ui_html("<p><label><input type='checkbox' name='show_json_details' {}> JSON-Details anzeigen</label></p>").format(checked("show_json_details"))

    body += _ui_html("<p><button class='btn' type='submit'>Speichern</button> ")
    body += _ui_html("<a class='btn' href='/settings'>Zurücksetzen</a> ")
    body += _ui_html("<a class='btn' href='/settings/app-manager/maintenance'>Wartung</a></p>")
    body += _ui_html("</form></div>")

    body += _ui_html("<div class='card'><h3>App-Manager Status</h3>")
    body += _ui_html("<p>Restore-Ausführung: <b class='{}'>{}</b><br>Update-Ausführung: <b class='{}'>{}</b><br>Live-Refresh: <code>{}</code> Sekunden</p>").format(
        "ok" if cfg.get("restore_execution_enabled") else "warn",
        _ui_text("aktiv") if cfg.get("restore_execution_enabled") else _ui_text("deaktiviert"),
        "ok" if cfg.get("update_execution_enabled") else "warn",
        _ui_text("aktiv") if cfg.get("update_execution_enabled") else _ui_text("deaktiviert"),
        esc(cfg.get("live_refresh_seconds", 2)),
    )
    body += _ui_html("</div>")

    return page(_ui_text("Einstellungen"), body, "Einstellungen")

init_db()
LOADED_PLUGINS = load_plugins()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT)
