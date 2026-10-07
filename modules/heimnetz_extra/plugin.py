from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
import datetime
import html
import subprocess
from flask import request, redirect, Response
import json

from modules.heimnetz_clients import (
    diagnostic_text,
    relative_time,
    rescan_home_client,
    source_label,
)

def esc(x):
    return html.escape(str(x or ""))

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def today():
    return datetime.datetime.now().strftime("%Y-%m-%d")

def month():
    return datetime.datetime.now().strftime("%Y-%m")

def fmt_seconds(sec):
    try:
        sec = int(sec or 0)
    except Exception:
        sec = 0
    h = sec // 3600
    m = (sec % 3600) // 60
    return f"{h} h {m:02d} min" if h else f"{m} min"

def ensure_tables(con):
    cols = [r["name"] for r in con.execute("PRAGMA table_info(home_clients)").fetchall()]

    for name, definition in [
        ("ignored", "INTEGER DEFAULT 0"),
        ("infrastructure", "INTEGER DEFAULT 0"),
        ("sleep_blocker", "INTEGER DEFAULT 0"),
        ("wol_enabled", "INTEGER DEFAULT 0"),
        ("notes", "TEXT DEFAULT ''"),
        ("last_state", "TEXT DEFAULT ''"),
        ("last_state_change", "TEXT"),
    ]:
        if name not in cols:
            con.execute(f"ALTER TABLE home_clients ADD COLUMN {name} {definition}")

    con.execute("""
        CREATE TABLE IF NOT EXISTS home_client_presence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            home_client_id INTEGER NOT NULL,
            online_from TEXT NOT NULL,
            online_until TEXT,
            seconds INTEGER DEFAULT 0
        )
    """)
    con.commit()

def update_presence(ctx):
    con = ctx.db()
    try:
        ensure_tables(con)
        rows = con.execute("SELECT * FROM home_clients WHERE COALESCE(deleted,0)=0").fetchall()
        ts = now()

        for r in rows:
            cid = r["id"]
            online = int(r["is_online"] or 0) == 1
            last_state = r["last_state"] or ""

            if online and last_state != "online":
                con.execute("""
                    INSERT INTO home_client_presence(home_client_id, online_from)
                    VALUES(?,?)
                """, (cid, ts))
                con.execute("""
                    UPDATE home_clients
                       SET last_state='online',
                           last_state_change=?
                     WHERE id=?
                """, (ts, cid))

            elif not online and last_state == "online":
                open_row = con.execute("""
                    SELECT *
                      FROM home_client_presence
                     WHERE home_client_id=?
                       AND online_until IS NULL
                     ORDER BY id DESC LIMIT 1
                """, (cid,)).fetchone()

                if open_row:
                    try:
                        start = datetime.datetime.strptime(open_row["online_from"], "%Y-%m-%d %H:%M:%S")
                        end = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        seconds = max(0, int((end - start).total_seconds()))
                    except Exception:
                        seconds = 0

                    con.execute("""
                        UPDATE home_client_presence
                           SET online_until=?,
                               seconds=?
                         WHERE id=?
                    """, (ts, seconds, open_row["id"]))

                con.execute("""
                    UPDATE home_clients
                       SET last_state='offline',
                           last_state_change=?
                     WHERE id=?
                """, (ts, cid))

        con.commit()
    finally:
        con.close()

def usage_seconds(con, cid, prefix):
    rows = con.execute("""
        SELECT online_from, online_until, seconds
          FROM home_client_presence
         WHERE home_client_id=?
           AND online_from LIKE ?
    """, (cid, prefix + "%")).fetchall()

    total = 0
    now_dt = datetime.datetime.now()

    for r in rows:
        if r["online_until"]:
            total += int(r["seconds"] or 0)
        else:
            try:
                start = datetime.datetime.strptime(r["online_from"], "%Y-%m-%d %H:%M:%S")
                total += max(0, int((now_dt - start).total_seconds()))
            except Exception:
                pass

    return total

def wol(mac):
    if not mac:
        return False, "MAC fehlt"
    try:
        p = subprocess.run(["wakeonlan", mac], text=True, capture_output=True, timeout=10)
        return p.returncode == 0, (p.stdout or p.stderr or "").strip()
    except Exception as e:
        return False, str(e)

def register(app, ctx):
    @app.after_request
    def heimnetz_presence_after_request(response):
        try:
            if request.path.startswith("/heimnetz"):
                update_presence(ctx)
        except Exception:
            pass
        return response

    @app.route("/heimnetz/client/<int:cid>", methods=["GET", "POST"])
    def heimnetz_client_detail(cid):
        msg = ""

        con = ctx.db()
        try:
            ensure_tables(con)

            if request.method == "POST":
                action = request.form.get("action", "")

                if action == "save":
                    con.execute("""
                        UPDATE home_clients
                           SET display_name=?,
                               name=COALESCE(NULLIF(?,''), name),
                               hostname=?,
                               device_type=?,
                               infrastructure=?,
                               sleep_blocker=?,
                               ignored=?,
                               wol_enabled=?,
                               notes=?
                         WHERE id=?
                    """, (
                        request.form.get("display_name", "").strip(),
                        request.form.get("display_name", "").strip(),
                        request.form.get("hostname", "").strip(),
                        request.form.get("device_type", "Unbekannt").strip(),
                        1 if request.form.get("infrastructure") == "1" else 0,
                        1 if request.form.get("sleep_blocker") == "1" else 0,
                        1 if request.form.get("ignored") == "1" else 0,
                        1 if request.form.get("wol_enabled") == "1" else 0,
                        request.form.get("notes", "").strip(),
                        cid
                    ))
                    con.commit()
                    msg = "Gerät gespeichert."

                elif action == "wol":
                    r = con.execute(
                        "SELECT mac FROM home_clients WHERE id=?",
                        (cid,),
                    ).fetchone()

                    ok, out = wol(
                        r["mac"]
                        if r
                        else ""
                    )

                    msg = (
                        "WOL gesendet."
                        if ok
                        else "WOL fehlgeschlagen: " + out
                    )

                elif action == "rescan":
                    result = rescan_home_client(
                        con,
                        cid,
                        restore=True,
                    )
                    msg = result["message"]

            r = con.execute("SELECT * FROM home_clients WHERE id=?", (cid,)).fetchone()
            if not r:
                return "Gerät nicht gefunden", 404

            today_sec = usage_seconds(con, cid, today())
            month_sec = usage_seconds(con, cid, month())

            segs = con.execute("""
                SELECT *
                  FROM home_client_presence
                 WHERE home_client_id=?
                   AND online_from LIKE ?
                 ORDER BY id DESC
                 LIMIT 20
            """, (cid, today() + "%")).fetchall()

        finally:
            con.close()

        name = r["display_name"] or r["name"] or r["hostname"] or r["ipv4"] or r["ip"] or r["mac"]

        body = _ui_html("<div class='card'><h2>{}</h2>").format(esc(name))
        if msg:
            body += _ui_html("<p><b>{}</b></p>").format(esc(_ui_text(msg)))

        body += _ui_html("<p>")
        body += _ui_html("<b>Status:</b> {}<br>").format(
            _ui_text("🟢 online")
            if int(r["is_online"] or 0)
            else _ui_text("⚪ offline")
        )
        body += _ui_html("<b>Quelle:</b> {}<br>").format(
            esc(source_label(r["source"]))
        )
        body += (
            _ui_html("<b>Letzter Kontakt:</b> "
            "<span title='{}'>{}</span><br>")
        ).format(
            esc(r["last_seen"] or ""),
            esc(relative_time(r["last_seen"])),
        )
        body += _ui_html("<b>Diagnose:</b> {}<br>").format(
            esc(diagnostic_text(r))
        )
        body += _ui_html("<b>IPv4:</b> {}<br>").format(
            esc(r["ipv4"] or r["ip"] or "")
        )
        body += _ui_html("<b>IPv6:</b> {}<br>").format(
            esc(r["ipv6"] or "")
        )
        body += _ui_html("<b>MAC:</b> <code>{}</code><br>").format(
            esc(r["mac"] or "")
        )
        body += _ui_html("<b>Hersteller:</b> {}<br>").format(
            esc(r["vendor"] or _ui_text("Unbekannt"))
        )
        body += _ui_html("<b>Heute online:</b> {}<br>").format(
            fmt_seconds(today_sec)
        )
        body += _ui_html("<b>Monat online:</b> {}").format(
            fmt_seconds(month_sec)
        )
        body += _ui_html("</p></div>")

        body += _ui_html("<div class='card'><h3>Gerät bearbeiten</h3>")
        body += _ui_html("<form method='post'><input type='hidden' name='action' value='save'>")
        body += _ui_html("<table>")
        body += _ui_html("<tr><td>Name</td><td><input name='display_name' value='{}' style='width:95%'></td></tr>").format(esc(name))
        body += _ui_html("<tr><td>Hostname</td><td><input name='hostname' value='{}' style='width:95%'></td></tr>").format(esc(r["hostname"] or ""))
        body += _ui_html("<tr><td>Typ</td><td><input name='device_type' value='{}'></td></tr>").format(esc(r["device_type"] or "Unbekannt"))
        body += _ui_html("<tr><td>Infrastruktur</td><td><label><input type='checkbox' name='infrastructure' value='1' {}> Infrastrukturgerät</label><p class='muted'>Kennzeichnung für die grundlegende Netzwerktechnik, z. B. Router, Switch, Access Point, NAS oder Server. Diese Markierung setzt keinen Schlafblocker und ändert nicht die Anwesenheits-Prüfgruppe.</p></td></tr>").format("checked" if int(r["infrastructure"] or 0) else "")
        body += _ui_html("<tr><td>Schlaf &amp; Wake</td><td><label><input type='checkbox' name='sleep_blocker' value='1' {}> Als Blocker setzen</label><p class='muted'>Verhindert automatisches Schlafen, solange die Anwesenheitserkennung dieses Gerät als online meldet. Kein Client-Agent erforderlich. Offline, ignorierte und gelöschte Geräte blockieren nicht. Die Freigabe erfolgt nach der konfigurierten Offline-Frist, nicht sofort beim Ausschalten. Dauerhaft erreichbare Geräte halten den Server dauerhaft wach. Bestehende Bedarfsmeldungen eines Client-Agenten gelten unabhängig von dieser Option.</p><a href='/presence/status'>Anwesenheit und Prüfintervalle</a></td></tr>").format("checked" if int(r["sleep_blocker"] or 0) else "")
        body += _ui_html("<tr><td>Ignorieren</td><td><label><input type='checkbox' name='ignored' value='1' {}> aktiv</label></td></tr>").format("checked" if int(r["ignored"] or 0) else "")
        body += _ui_html("<tr><td>Wake-on-LAN</td><td><label><input type='checkbox' name='wol_enabled' value='1' {}> aktiv</label></td></tr>").format("checked" if int(r["wol_enabled"] or 0) else "")
        body += _ui_html("<tr><td>Notiz</td><td><textarea name='notes' style='width:95%;height:80px'>{}</textarea></td></tr>").format(esc(r["notes"] or ""))
        body += _ui_html("</table><p><button class='btn' type='submit'>Speichern</button></p></form>")

        if int(r["wol_enabled"] or 0):
            body += (
                _ui_html("<form method='post' style='display:inline-block;"
                "margin-right:8px'>"
                "<input type='hidden' name='action' value='wol'>"
                "<button class='btn' type='submit'>"
                "Wake-on-LAN senden"
                "</button>"
                "</form>")
            )

        body += (
            _ui_html("<form method='post' style='display:inline-block' "
            "onsubmit=\"return confirm('Gerät anhand der MAC-Adresse "
            "vollständig neu scannen?');\">"
            "<input type='hidden' name='action' value='rescan'>"
            "<button class='btn' type='submit'>"
            "Gerät vollständig neu scannen"
            "</button>"
            "</form>")
        )

        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Heute</h3>")
        if not segs:
            body += _ui_html("<p>Keine Onlinezeit erfasst.</p>")
        else:
            body += _ui_html("<table><tr><th>Von</th><th>Bis</th><th>Dauer</th></tr>")
            for s in segs:
                body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td></tr>").format(
                    esc(s["online_from"]),
                    esc(s["online_until"] or _ui_text("jetzt")),
                    fmt_seconds(s["seconds"])
                )
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><p><a class='btn' href='/heimnetz'>Zurück</a></p></div>")
        return ctx.page(_ui_text("Heimnetz Gerät"), body, "Heimnetz")

    @app.route("/api/heimnetz/stats")
    def api_heimnetz_stats():
        update_presence(ctx)
        con = ctx.db()
        try:
            ensure_tables(con)
            rows = con.execute("""
                SELECT *
                  FROM home_clients
                 WHERE COALESCE(deleted,0)=0
                   AND COALESCE(ignored,0)=0
            """).fetchall()

            out = []
            for r in rows:
                out.append({
                    "id": r["id"],
                    "name": r["display_name"] or r["name"] or r["hostname"] or r["ipv4"] or r["mac"],
                    "is_online": bool(r["is_online"]),
                    "infrastructure": bool(r["infrastructure"]),
                    "sleep_blocker": bool(r["sleep_blocker"]),
                    "today_seconds": usage_seconds(con, r["id"], today()),
                    "month_seconds": usage_seconds(con, r["id"], month()),
                })

            return Response(json.dumps({"ok": True, "items": out}, ensure_ascii=False, indent=2), mimetype="application/json")
        finally:
            con.close()
