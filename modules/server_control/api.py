from .state import init_db, get_status, set_status
from .rtc import rtc_status

def refresh(con, ctx=None):
    init_db(con)

    from modules.blocker_api import collect_blockers
    blockers = collect_blockers(ctx)

    # Phase 5.10.6: laufende App-Manager-Jobs zentral als Server-Control-Blocker erfassen.
    try:
        from modules.app_manager.plugin import get_active_job
        job = get_active_job()
    except Exception:
        job = None

    if job:
        app_id = job.get("app_id") or "unknown"
        action = job.get("action") or job.get("type") or "job"
        detail = job.get("current_detail") or action
        path_key = job.get("current_path_key") or ""
        progress = job.get("progress_percent")

        reason = "{}".format(detail)
        if path_key:
            reason += " ({})".format(path_key)
        if progress is not None:
            reason += " {}%".format(progress)

        blockers.append({
            "source": "App Manager",
            "name": app_id,
            "reason": reason,
            "url": job.get("url"),
            "type": "app-manager-job",
            "priority": 70,
        })

    policy = {
        "may_sleep": len(blockers) == 0,
        "blocker_count": len(blockers),
        "blockers": blockers,
    }

    set_status(con, "may_sleep", "1" if policy["may_sleep"] else "0")
    set_status(con, "blocker_count", str(policy["blocker_count"]))
    return policy

def status(con, ctx=None):
    policy = refresh(con, ctx)

    try:
        from modules.tvheadend.status_provider import get_status as tv_status
        tv = tv_status(ctx)
    except Exception as e:
        tv = {"error": str(e), "next_recording": None}

    return {
        "ok": True,
        "policy": policy,
        "status": get_status(con),
        "blockers": policy["blockers"],
        "next_recording": tv.get("next_recording"),
        "tvheadend": tv,
        "rtc": rtc_status(con),
    }
