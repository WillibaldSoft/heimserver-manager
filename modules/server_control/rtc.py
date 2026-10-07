
def plan_rtc_wakeup(con, source, title, wake_time, target_time):
    con.execute('''
        INSERT INTO server_control_rtc_events(source,title,wake_time,target_time,status)
        VALUES(?,?,?,?,'planned')
    ''', (source, title, wake_time, target_time))
    con.commit()

def rtc_status(con):
    rows = con.execute('''
        SELECT id,source,title,wake_time,target_time,status,created_at
          FROM server_control_rtc_events
         ORDER BY wake_time DESC
         LIMIT 20
    ''').fetchall()
    return [dict(r) for r in rows]
