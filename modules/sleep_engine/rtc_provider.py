# -*- coding: utf-8 -*-
import datetime

from . import schedules

def get_rtc_candidates(ctx=None):
    if ctx is None:
        return []

    con = ctx.db()
    try:
        schedules.ensure_table(con)

        rows = con.execute("""
            SELECT *
              FROM sleep_engine_schedules
             WHERE enabled=1
               AND action IN ('wake','awake','poweroff','suspend','hibernate')
             ORDER BY start_time
        """).fetchall()

        now = datetime.datetime.now()
        candidates = []
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

        for r in rows:
            action = str(r["action"] or "").lower()

            for offset in range(-1, 8):
                day = now.date() + datetime.timedelta(days=offset)
                weekday = day.weekday()
                day_name = day_names[weekday]

                days = r["days"] or "mon,tue,wed,thu,fri,sat,sun"
                allowed_days = [x.strip() for x in days.split(",") if x.strip()]

                if allowed_days and day_name not in allowed_days:
                    continue

                if action in ("wake", "awake"):
                    rtc_time = r["start_time"]
                    title = "Zeitplan Wach"
                elif action in ("poweroff", "suspend", "hibernate"):
                    rtc_time = r["end_time"]
                    title = "Zeitplan Ende {}".format(action)
                else:
                    continue

                hh, mm = str(rtc_time).split(":")[:2]
                wake = datetime.datetime.combine(day, datetime.time(int(hh), int(mm)))
                if action in ('poweroff','suspend','hibernate') and schedules.minutes_of(r['start_time']) > schedules.minutes_of(r['end_time']):
                    wake += datetime.timedelta(days=1)

                if wake <= now:
                    continue

                candidates.append({
                    "source": "sleep_schedule",
                    "title": title,
                    "wake_time": wake.strftime("%Y-%m-%d %H:%M:%S"),
                    "target_time": wake.strftime("%Y-%m-%d %H:%M:%S"),
                    "ts": int(wake.timestamp()),
                    "priority": 50,
                })
                break

        return candidates
    finally:
        con.close()
