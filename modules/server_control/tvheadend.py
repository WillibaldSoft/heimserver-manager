
def sync_tvheadend_blockers(con):
    con.execute("UPDATE server_control_blockers SET active=0, updated_at=datetime('now','localtime') WHERE source='tvheadend'")
    con.commit()

def next_recording(con):
    row = con.execute('''
        SELECT source,title,wake_time,target_time,status
          FROM server_control_rtc_events
         WHERE status='planned'
         ORDER BY wake_time
         LIMIT 1
    ''').fetchone()
    return dict(row) if row else None
