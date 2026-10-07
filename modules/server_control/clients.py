
def ensure_client_agent_columns(con):
    cols = [r["name"] for r in con.execute("PRAGMA table_info(client_agents)").fetchall()]
    wanted = {
        "server_required": "INTEGER DEFAULT 0",
        "require_reason": "TEXT",
        "required_since": "TEXT",
        "last_required_seen": "TEXT",
        "mode": "TEXT DEFAULT 'auto'",
    }
    for name, ddl in wanted.items():
        if name not in cols:
            con.execute(f"ALTER TABLE client_agents ADD COLUMN {name} {ddl}")
    con.commit()
    try:
        from modules.tvheadend.blockers import sync_blockers as sync_tvheadend_blockers
        sync_tvheadend_blockers(con)
    except Exception:
        pass

def sync_client_blockers(con):
    ensure_client_agent_columns(con)

    try:
        from modules.heimnetz_clients import expire_stale_agents
        expire_stale_agents(con)
    except Exception:
        pass

    con.execute("UPDATE server_control_blockers SET active=0, updated_at=datetime('now','localtime') WHERE source='client'")

    try:
        rows = con.execute("""
            SELECT name,hostname,ip,mode,last_seen,server_required,require_reason,required_since
              FROM client_agents
             WHERE enabled=1
               AND is_online=1
               AND COALESCE(server_required,0)=1
        """).fetchall()
    except Exception:
        rows = []

    for r in rows:
        name = r["name"] or r["hostname"] or r["ip"] or "Client"
        mode = r["mode"] or "auto"
        reason = r["require_reason"] or "Client benoetigt Server"
        if mode:
            reason = reason + " (" + mode + ")"
        con.execute("""
            INSERT INTO server_control_blockers(source,name,reason,active,updated_at)
            VALUES('client',?,?,1,datetime('now','localtime'))
        """, (name, reason))

    con.commit()

def set_client_required(con, agent_id, required, reason="client"):
    ensure_client_agent_columns(con)
    if required:
        con.execute("""
            UPDATE client_agents
               SET server_required=1,
                   require_reason=?,
                   required_since=COALESCE(required_since, datetime('now','localtime')),
                   last_required_seen=datetime('now','localtime'),
                   last_seen=datetime('now','localtime')
             WHERE id=?
        """, (reason, agent_id))
    else:
        con.execute("""
            UPDATE client_agents
               SET server_required=0,
                   require_reason=NULL,
                   required_since=NULL,
                   last_required_seen=datetime('now','localtime'),
                   last_seen=datetime('now','localtime')
             WHERE id=?
        """, (agent_id,))
    con.commit()
