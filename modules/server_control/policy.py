
def evaluate_policy(con):
    blockers = con.execute('''
        SELECT source,name,reason
          FROM server_control_blockers
         WHERE active=1
         ORDER BY source,name
    ''').fetchall()

    may_sleep = len(blockers) == 0

    return {
        "may_sleep": may_sleep,
        "blocker_count": len(blockers),
        "blockers": [
            {
                "source": b["source"],
                "name": b["name"],
                "reason": b["reason"],
            }
            for b in blockers
        ],
    }
