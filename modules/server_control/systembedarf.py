from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-

SOURCE_ORDER = {
    "network-presence": 25,
    "tvheadend": 10,
    "client-agent": 20,
    "client": 20,
    "backup": 30,
    "updates": 40,
    "docker": 50,
    "kvm": 60,
    "app manager": 35,
    "app-manager": 35,
    "app-manager-job": 35,
    "system": 90,
}

SOURCE_LABELS = {
    "network-presence": ("🌐", "Netzwerk / Anwesenheit"),
    "tvheadend": ("📺", "TVHeadend"),
    "client-agent": ("💻", "Clients"),
    "client": ("💻", "Clients"),
    "backup": ("💾", "Backup"),
    "updates": ("🔄", "Updates"),
    "docker": ("🐳", "Docker"),
    "kvm": ("🖥️", "KVM"),
    "app manager": ("⚙️", "App Manager"),
    "app-manager": ("⚙️", "App Manager"),
    "app-manager-job": ("⚙️", "App Manager"),
    "system": ("⚙️", "System"),
}

def _txt(v):
    return str(v or "").strip()

def normalize_source(src):
    s = _txt(src).lower()
    if s.startswith("tv"):
        return "tvheadend"
    if s in ("client-agent", "clients", "client"):
        return "client-agent"
    if s in ("app manager", "app-manager", "app-manager-job"):
        return "app-manager"
    return s or "system"

def blocker_title(b):
    return (
        _txt(b.get("title")) or
        _txt(b.get("name")) or
        _txt(b.get("type")) or
        _txt(b.get("reason")) or
        "Bedarf"
    )

def group_system_requirements(blockers):
    groups = {}

    for b in blockers or []:
        source = normalize_source(b.get("source"))
        icon, label = SOURCE_LABELS.get(source, ("⚙️", source.title()))
        g = groups.setdefault(source, {
            "source": source,
            "icon": icon,
            "label": label,
            "count": 0,
            "details": [],
            "summary": "",
        })

        title = blocker_title(b)
        reason = _txt(b.get("reason"))
        updated = _txt(b.get("updated_at"))
        url = _txt(b.get("url"))

        detail = {
            "title": title,
            "reason": reason,
            "updated_at": updated,
            "url": url,
        }

        if detail not in g["details"]:
            g["details"].append(detail)

        g["count"] += 1

    for g in groups.values():
        src = g["source"]
        cnt = len(g["details"])

        if src == "tvheadend":
            recordings = 0
            timers = 0
            streams = 0
            for d in g["details"]:
                low = (d["title"] + " " + d["reason"]).lower()
                if "aufnahme" in low or "recording" in low:
                    recordings += 1
                elif "timer" in low or "rtc" in low:
                    timers += 1
                elif "stream" in low:
                    streams += 1

            parts = []
            if recordings:
                parts.append(f"{recordings} Aufnahme{'n' if recordings != 1 else ''}")
            if timers:
                parts.append(f"{timers} Timer")
            if streams:
                parts.append(f"{streams} Stream{'s' if streams != 1 else ''}")
            if not parts:
                parts.append(f"{cnt} TV-Bedarf")
            g["summary"] = ", ".join(parts)

        elif src == "client-agent":
            g["summary"] = f"{cnt} Client{'s' if cnt != 1 else ''}"

        elif src == "network-presence":
            g["summary"] = f"{cnt} Online-Gerät{'e' if cnt != 1 else ''} als Blocker"

        elif src == "app-manager":
            g["summary"] = f"{cnt} App-Job{'s' if cnt != 1 else ''}"

        else:
            g["summary"] = f"{cnt} Eintrag{'e' if cnt != 1 else ''}"

    return sorted(
        groups.values(),
        key=lambda g: (SOURCE_ORDER.get(g["source"], 999), g["label"].lower())
    )

def render_systembedarf(ctx, blockers):
    groups = group_system_requirements(blockers)

    if not groups:
        return _ui_html("<p class='ok'><b>Kein Systembedarf.</b><br>Server darf schlafen oder ausgeschaltet werden.</p>")

    body = _ui_html("<p class='warn'><b>Server wird benötigt von:</b></p>")

    for g in groups:
        body += _ui_html("<div class='card' style='margin:10px 0'>")
        body += _ui_html("<h3>{} {}</h3>").format(ctx.esc(g["icon"]), ctx.esc(_ui_text(g["label"])))
        body += _ui_html("<p><b>{}</b></p>").format(ctx.esc(g["summary"]))

        body += _ui_html("<details><summary>Details anzeigen</summary>")
        body += _ui_html("<table><tr><th>Name</th><th>Grund</th><th>Aktualisiert</th><th>Aktion</th></tr>")
        for d in g["details"]:
            url = d.get("url") or ""
            action = "—"
            if url:
                action = _ui_html("<a class='btn' href='{}'>Öffnen</a>").format(ctx.esc(url))

            body += _ui_html("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>").format(
                ctx.esc(d.get("title")),
                ctx.esc(_ui_text(d.get("reason"))),
                ctx.esc(d.get("updated_at")),
                action,
            )
        body += _ui_html("</table></details>")
        body += _ui_html("</div>")

    return body
