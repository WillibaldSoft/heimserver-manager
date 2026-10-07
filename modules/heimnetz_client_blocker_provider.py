# -*- coding: utf-8 -*-

from modules.heimnetz_clients import expire_stale_agents, expire_stale_network_devices

def get_blockers(ctx=None):
    from modules.module_selection.config import network_enabled
    if not network_enabled():return []
    blockers = []

    if ctx is None:
        return blockers

    con = ctx.db()

    try:
        expire_stale_agents(con)

        # Reuse the same expiry rules as the presence module.
        cols = {row["name"] for row in con.execute("PRAGMA table_info(home_clients)")}
        if "sleep_blocker" in cols and con.execute("SELECT 1 FROM home_clients WHERE sleep_blocker=1 LIMIT 1").fetchone():
            expire_stale_network_devices(con)
            for row in con.execute("""
                SELECT * FROM home_clients
                 WHERE sleep_blocker=1 AND is_online=1
                   AND COALESCE(ignored,0)=0 AND COALESCE(deleted,0)=0
            """).fetchall():
                blockers.append({
                    "source": "network-presence", "type": "client",
                    "title": row["display_name"] or row["name"] or row["hostname"] or row["ip"] or "Netzwerkgerät",
                    "reason": "Als Blocker gesetzt · Gerät online (Anwesenheit)",
                    "priority": 80, "ip": row["ip"], "mac": row["mac"],
                    "last_seen": row["last_seen"], "updated_at": row["last_seen"],
                    "url": "/heimnetz/client/" + str(row["id"]),
                })

        rows = con.execute("""
            SELECT
                name,
                hostname,
                ip,
                mac,
                mode,
                server_required,
                require_reason,
                last_seen
              FROM client_agents
             WHERE enabled=1
               AND is_online=1
               AND server_required=1
        """).fetchall()

        for row in rows:
            name = (
                row["name"]
                or row["hostname"]
                or row["ip"]
                or row["mac"]
                or "Client"
            )

            reason = (
                row["require_reason"]
                or "Client benötigt Server"
            )

            blockers.append({
                "source": "client-agent",
                "type": "client",
                "title": name,
                "reason": reason,
                "priority": 80,
                "ip": row["ip"],
                "mac": row["mac"],
                "last_seen": row["last_seen"],
            })

    finally:
        con.close()

    return blockers
