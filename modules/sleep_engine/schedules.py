from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
# Sleep schedule routes with weekdays, priorities and overlapping windows

DAYS = [
    ("mon", "Mo"),
    ("tue", "Di"),
    ("wed", "Mi"),
    ("thu", "Do"),
    ("fri", "Fr"),
    ("sat", "Sa"),
    ("sun", "So"),
]

def hibernate_available():
    try:
        with open("/sys/power/state", "r", encoding="utf-8", errors="replace") as f:
            states = f.read()
        with open("/sys/power/disk", "r", encoding="utf-8", errors="replace") as f:
            disk = f.read()
        return "disk" in states and ("platform" in disk or "shutdown" in disk or "reboot" in disk)
    except Exception:
        return False

def ensure_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS sleep_engine_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            enabled INTEGER DEFAULT 1,
            days TEXT DEFAULT 'mon,tue,wed,thu,fri,sat,sun',
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            action TEXT NOT NULL,
            priority INTEGER DEFAULT 100,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cols = [r["name"] for r in con.execute("PRAGMA table_info(sleep_engine_schedules)").fetchall()]
    if "days" not in cols:
        con.execute("ALTER TABLE sleep_engine_schedules ADD COLUMN days TEXT DEFAULT 'mon,tue,wed,thu,fri,sat,sun'")
    if "priority" not in cols:
        con.execute("ALTER TABLE sleep_engine_schedules ADD COLUMN priority INTEGER DEFAULT 100")
    con.commit()

def action_options():
    opts = [
        ("wake", "Wach halten"),
        ("suspend", "Suspend"),
        ("poweroff", "Aus / Poweroff"),
    ]
    if hibernate_available():
        opts.append(("hibernate", "Hibernate"))
    return opts

def day_labels(value):
    selected = set((value or "").split(","))
    labels = [label for key, label in DAYS if key in selected]
    return ", ".join(labels) if labels else "-"

def weekday_key(dt=None):
    import datetime
    dt = dt or datetime.datetime.now()
    return DAYS[dt.weekday()][0]

def minutes_of(t):
    try:
        h, m = str(t).split(":", 1)
        return int(h) * 60 + int(m)
    except Exception:
        return None

def active_now(row, now=None):
    import datetime
    now = now or datetime.datetime.now()
    days = set((row["days"] or "").split(","))
    start = minutes_of(row["start_time"])
    end = minutes_of(row["end_time"])
    cur = now.hour * 60 + now.minute
    if start is None or end is None:
        return False
    if start <= end:
        return weekday_key(now) in days and start <= cur < end
    # Weekdays identify the start day, including the following morning.
    if cur >= start:
        return weekday_key(now) in days
    if cur < end:
        return weekday_key(now - datetime.timedelta(days=1)) in days
    return False

def current_action(con, now=None):
    ensure_table(con)
    rows = con.execute("""
        SELECT *
          FROM sleep_engine_schedules
         WHERE enabled=1
         ORDER BY priority ASC, start_time DESC
    """).fetchall()
    active = [r for r in rows if active_now(r, now)]
    if not active:
        return None
    return active[0]

def register(app, ctx):
    from flask import request

    @app.route("/sleep/schedules", methods=["GET", "POST"])
    def sleep_schedules():
        con = ctx.db()
        msg = ""
        try:
            ensure_table(con)

            if request.method == "POST":
                form_action = request.form.get("form_action", "")
                sid = request.form.get("id")

                if form_action in ("add", "update"):
                    name = request.form.get("name", "").strip() or "Zeitplan"
                    selected_days = request.form.getlist("days")
                    days = ",".join([d for d, _ in DAYS if d in selected_days])
                    start_time = request.form.get("start_time", "").strip()
                    end_time = request.form.get("end_time", "").strip()
                    action = request.form.get("action", "wake").strip()
                    try:
                        priority = int(request.form.get("priority", "100") or "100")
                    except Exception:
                        priority = 100
                    allowed = [x[0] for x in action_options()]

                    if not days:
                        msg = "Mindestens ein Wochentag fehlt."
                    elif action not in allowed:
                        msg = "Aktion nicht verfügbar."
                    elif not start_time or not end_time:
                        msg = "Start und Ende fehlen."
                    elif form_action == "add":
                        con.execute("""
                            INSERT INTO sleep_engine_schedules(name,enabled,days,start_time,end_time,action,priority)
                            VALUES(?,1,?,?,?,?,?)
                        """, (name, days, start_time, end_time, action, priority))
                        con.commit()
                        msg = "Zeitplan angelegt."
                    else:
                        con.execute("""
                            UPDATE sleep_engine_schedules
                               SET name=?,
                                   days=?,
                                   start_time=?,
                                   end_time=?,
                                   action=?,
                                   priority=?,
                                   updated_at=datetime('now','localtime')
                             WHERE id=?
                        """, (name, days, start_time, end_time, action, priority, sid))
                        con.commit()
                        msg = "Zeitplan gespeichert."

                elif form_action == "delete" and sid:
                    con.execute("DELETE FROM sleep_engine_schedules WHERE id=?", (sid,))
                    con.commit()
                    msg = "Zeitplan gelöscht."

                elif form_action == "toggle" and sid:
                    con.execute("""
                        UPDATE sleep_engine_schedules
                           SET enabled=CASE WHEN enabled=1 THEN 0 ELSE 1 END,
                               updated_at=datetime('now','localtime')
                         WHERE id=?
                    """, (sid,))
                    con.commit()
                    msg = "Zeitplan umgeschaltet."

            rows = con.execute("""
                SELECT *
                  FROM sleep_engine_schedules
                 ORDER BY enabled DESC, priority ASC, start_time, end_time, name
            """).fetchall()
            current = current_action(con)
        finally:
            con.close()

        opts = action_options()

        body = _ui_html("<div class='card'><h2>Zeitpläne Schlaf & Wake</h2>")
        body += _ui_html("<p>Freigegebene VMs werden etwa fünf Minuten vor der fälligen Server-Aktion regulär heruntergefahren (Prüfung im Minutentakt). Nachlaufzeit und andere Blocker bleiben berücksichtigt. Mehrere Zeitfenster pro Tag sind möglich. Kürzere/spezifischere Regeln überlagern lange Regeln über die Priorität. Niedrigere Priorität gewinnt.</p>")
        if current:
            body += _ui_html("<p><b>Aktuell gültig:</b> {} – {} bis {} – Aktion <code>{}</code> – Priorität {}</p>").format(
                ctx.esc(current["name"]), ctx.esc(current["start_time"]), ctx.esc(current["end_time"]), ctx.esc(current["action"]), ctx.esc(current["priority"])
            )
        else:
            body += _ui_html("<p><b>Aktuell gültig:</b> keine Regel</p>")
        if msg:
            body += _ui_html("<p><b>{}</b></p>").format(ctx.esc(_ui_text(msg)))
        body += _ui_html("</div>")

        def day_checkboxes(selected_csv):
            selected = set((selected_csv or "").split(","))
            html = ""
            for key, label in DAYS:
                checked = "checked" if key in selected else ""
                html += _ui_html("<label><input type='checkbox' name='days' value='{}' {}> {}</label> ").format(ctx.esc(key), checked, ctx.esc(_ui_text(label)))
            return html

        body += _ui_html("<div class='card'><h3>Neuer Zeitplan</h3>")
        body += _ui_html("<form method='post'>")
        body += _ui_html("<input type='hidden' name='form_action' value='add'>")
        body += _ui_html("<table><tr><th>Name</th><th>Wochentage</th><th>Von</th><th>Bis</th><th>Aktion</th><th>Priorität</th><th></th></tr><tr>")
        body += _ui_html("<td><input name='name' value='Täglich wach'></td>")
        body += _ui_html("<td>{}</td>").format(day_checkboxes("mon,tue,wed,thu,fri,sat,sun"))
        body += _ui_html("<td><input name='start_time' type='time' value='08:00'></td>")
        body += _ui_html("<td><input name='end_time' type='time' value='23:00'></td>")
        body += _ui_html("<td><select name='action'>")
        for key, label in opts:
            body += _ui_html("<option value='{}'>{}</option>").format(ctx.esc(key), ctx.esc(_ui_text(label)))
        body += _ui_html("</select></td>")
        body += _ui_html("<td><input name='priority' type='number' value='100' style='width:80px'></td>")
        body += _ui_html("<td><button class='btn' type='submit'>Anlegen</button></td>")
        body += _ui_html("</tr></table></form></div>")

        body += _ui_html("<div class='card'><h3>Bestehende Zeitpläne</h3>")
        if not rows:
            body += _ui_html("<p>Keine Zeitpläne angelegt.</p>")
        else:
            body += _ui_html("<table><tr><th>Aktiv</th><th>Name</th><th>Wochentage</th><th>Von</th><th>Bis</th><th>Aktion</th><th>Priorität</th><th>Aktuell</th><th></th></tr>")
            for r in rows:
                enabled = "✅" if int(r["enabled"] or 0) == 1 else "⛔"
                now_active = "🟢" if int(r["enabled"] or 0) == 1 and active_now(r) else ""
                body += _ui_html("<tr><form method='post'>")
                body += _ui_html("<input type='hidden' name='id' value='{}'>").format(r["id"])
                body += _ui_html("<td>{}</td>").format(enabled)
                body += _ui_html("<td><input name='name' value='{}'></td>").format(ctx.esc(r["name"]))
                body += _ui_html("<td>{}<br><small>{}</small></td>").format(day_checkboxes(r["days"]), ctx.esc(day_labels(r["days"])))
                body += _ui_html("<td><input name='start_time' type='time' value='{}'></td>").format(ctx.esc(r["start_time"]))
                body += _ui_html("<td><input name='end_time' type='time' value='{}'></td>").format(ctx.esc(r["end_time"]))
                body += _ui_html("<td><select name='action'>")
                for key, label in opts:
                    selected = "selected" if r["action"] == key else ""
                    body += _ui_html("<option value='{}' {}>{}</option>").format(ctx.esc(key), selected, ctx.esc(_ui_text(label)))
                body += _ui_html("</select></td>")
                body += _ui_html("<td><input name='priority' type='number' value='{}' style='width:80px'></td>").format(ctx.esc(r["priority"]))
                body += _ui_html("<td>{}</td>").format(now_active)
                body += _ui_html("<td>")
                body += _ui_html("<button class='pill' name='form_action' value='update'>Speichern</button> ")
                body += _ui_html("<button class='pill' name='form_action' value='toggle'>Aktiv/aus</button> ")
                body += _ui_html("<button class='pill' name='form_action' value='delete' onclick=\"return confirm('Zeitplan löschen?')\">Löschen</button>")
                body += _ui_html("</td></form></tr>")
            body += _ui_html("</table>")
        body += _ui_html("</div>")

        body += _ui_html("<div class='card'><h3>Beispiel</h3><pre>Grundregel: Mo–So 08:00–23:00 Wach halten, Priorität 100\nAusnahme:   Mo–Fr 13:00–14:00 Suspend, Priorität 10</pre></div>")

        if not hibernate_available():
            body += _ui_html("<div class='card'><p class='warn'>Hibernate ist auf diesem System derzeit nicht verfügbar.</p></div>")

        body += _ui_html("<div class='card'><p><a class='btn' href='/sleep/check'>Sleep-Check</a> <a class='btn' href='/sleep/actions'>Sleep-Aktionen</a></p></div>")
        return ctx.page(_ui_text("Sleep-Zeitpläne"), body, "Schlaf & Wake")
