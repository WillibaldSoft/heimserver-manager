# -*- coding: utf-8 -*-
import threading
import time
import json
import datetime

from modules import rtc_planner

from . import policy, actions
from . import schedules
from modules.kvm_manager.sleep_control import managed_blocker, prepare as prepare_kvm

_STARTED = False

def _mark_keepawake_now(con, reason="runtime-start"):
    now_s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    policy.set_setting(con, "last_keepawake_seen", now_s)
    _log(con, "keepawake", True, reason, now_s)
    return now_s


def _log(con, action, allowed, result, details=""):
    policy.record_action(con, "runtime", action, allowed, result, details)

def execute_scheduled(con, action, decision, execute_enabled, ctx=None):
    # Called only after auto-enabled and grace checks. Dry-run never touches guests.
    if not execute_enabled:
        _log(con, action, decision['may_sleep'], 'dry-run')
        return
    prepare_kvm(decision)
    decision = policy.evaluate(con, ctx)
    if not decision['may_sleep']:
        _log(con, action, False, 'blocked', json.dumps(decision['blockers'], ensure_ascii=False))
        return
    result = actions.run_systemctl(action)
    _log(con, action, True, result.get('result', result.get('ok')), json.dumps(result, ensure_ascii=False))

def upcoming_shutdown(con, now=None):
    """Predict the earliest eligible sleep tick within five minutes, including wake/grace."""
    now=now or datetime.datetime.now()
    grace=max(0,int(policy.get_setting(con,'grace_minutes','45') or '45'))
    last=policy.get_setting(con,'last_keepawake_seen','')
    try:last=datetime.datetime.strptime(last,'%Y-%m-%d %H:%M:%S') if last else None
    except ValueError:return None  # ambiguous timing must not stop guests early
    for minute in range(6):
        when=now+datetime.timedelta(minutes=minute)
        row=schedules.current_action(con,when)
        if not row:continue
        if row['action']=='wake':last=when;continue
        if row['action'] not in ('suspend','hibernate','poweroff'):continue
        if last and when<last+datetime.timedelta(minutes=grace):continue
        return when,row['action']
    return None

def prepare_early(con,decision,auto_enabled,execute_enabled):
    if not auto_enabled or not execute_enabled:return
    if any(not managed_blocker(b) for b in decision.get('blockers',[])):return
    upcoming=upcoming_shutdown(con)
    if upcoming:
        jid=prepare_kvm(decision)
        if jid is not None:_log(con,'vm-shutdown',True,'VM-Vorlauf','Server-Aktion '+upcoming[1]+' frühestens '+upcoming[0].strftime('%H:%M:%S')+'; KVM-Auftrag '+str(jid))

def _loop(ctx, interval=60):
    first_run = True

    while True:
        try:
            con = ctx.db()
            try:
                schedules.ensure_table(con)

                if first_run:
                    _mark_keepawake_now(con, "runtime-start-grace")
                    first_run = False

                auto_enabled = policy.get_setting(con, "auto_enabled", "0") == "1"
                execute_enabled = policy.get_setting(con, "execute_enabled", "0") == "1"

                current = schedules.current_action(con)
                decision = policy.evaluate(con, ctx)
                from . import manual
                if manual.active():
                    time.sleep(2)
                    continue
                prepare_early(con,decision,auto_enabled,execute_enabled)

                rtc_enabled = policy.get_setting(con, "rtc_enabled", "1") == "1"
                rtc_execute = policy.get_setting(con, "rtc_execute", "0") == "1"

                if rtc_enabled:
                    try:
                        rtc_result = rtc_planner.sync(ctx, dry_run=not rtc_execute)
                        _log(
                            con,
                            "rtc-sync",
                            True,
                            rtc_result.get("reason", "ok"),
                            json.dumps(rtc_result, ensure_ascii=False)
                        )
                    except Exception as e:
                        _log(con, "rtc-sync", False, "error", str(e))




                if not current:
                    _log(con, "none", True, "no schedule")
                else:
                    action = current["action"]

                    grace_minutes = int(policy.get_setting(con, "grace_minutes", "45") or "45")

                    if any(not managed_blocker(b) for b in decision["blockers"]) or action == "wake":
                        policy.set_setting(
                            con,
                            "last_keepawake_seen",
                            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )

                    last_keep = policy.get_setting(con, "last_keepawake_seen", "")
                    grace_active = False

                    if last_keep:
                        try:
                            last_dt = datetime.datetime.strptime(last_keep, "%Y-%m-%d %H:%M:%S")
                            until_dt = last_dt + datetime.timedelta(minutes=grace_minutes)
                            grace_active = datetime.datetime.now() < until_dt
                        except Exception:
                            grace_active = False

                    if action == "wake":
                        _log(con, "wake", True, "keep awake")

                    elif action in ("suspend", "hibernate", "poweroff"):
                        if not auto_enabled:
                            _log(con, action, False, "auto disabled")
                        elif grace_active:
                            _log(
                                con,
                                action,
                                False,
                                "grace active",
                                "Nachlaufzeit {} min seit {}".format(grace_minutes, last_keep)
                            )
                        else:
                            execute_scheduled(con, action, decision, execute_enabled, ctx)

                    else:
                        _log(con, action, False, "unknown action")
            finally:
                con.close()

        except Exception as e:
            try:
                con = ctx.db()
                _log(con, "runtime-error", False, str(e))
                con.close()
            except Exception:
                pass

        time.sleep(interval)

def start(ctx):
    from tools.platform_check import mint_desktop
    if mint_desktop():return False  # Experimental desktop profile: no background power/RTC actions.
    global _STARTED
    if _STARTED:
        return False
    _STARTED = True
    t = threading.Thread(target=_loop, args=(ctx,), daemon=True)
    t.start()
    return True
