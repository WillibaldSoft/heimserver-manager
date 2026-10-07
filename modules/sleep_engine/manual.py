"""Manual host sleep: request graceful VM shutdown immediately and wait in background."""
import json,threading,time
from . import policy,actions
from modules.kvm_manager.sleep_control import managed_blocker,prepare
_LOCK=threading.Lock()
_ACTIVE=False

def active():return _ACTIVE

def state(con):
    try:return json.loads(policy.get_setting(con,'manual_shutdown_status','{}'))
    except ValueError:return {}

def save(ctx,status,message,action):
    con=ctx.db()
    try:
        policy.set_setting(con,'manual_shutdown_status',json.dumps(dict(state=status,message=message,action=action),ensure_ascii=False))
        policy.record_action(con,action,'manual',status!='failed',status,message)
    finally:con.close()

def initialize(ctx):
    con=ctx.db()
    try:previous=state(con)
    finally:con.close()
    if previous.get('state')=='running':save(ctx,'interrupted','Manager neu gestartet; manuelle Server-Aktion abgebrochen. VM-Zustand prüfen.',previous.get('action','poweroff'))

def can_start(decision,force=False):
    rows=decision.get('blockers',[])
    if force:return not any(b.get('source')=='KVM' and not managed_blocker(b) for b in rows)
    return bool(decision.get('may_sleep')) or bool(rows) and all(managed_blocker(b) for b in rows)

def start(ctx,action,evaluate,force=False):
    global _ACTIVE
    if action not in ('poweroff','suspend','hibernate'):raise ValueError('Ungültige Server-Aktion.')
    with _LOCK:
        if _ACTIVE:raise ValueError('Eine manuelle Server-Aktion läuft bereits.')
        _ACTIVE=True
    try:
        save(ctx,'running','VMs werden sofort regulär heruntergefahren. Server wartet höchstens fünf Minuten auf Freigabe; kein hartes Ausschalten.',action)
        threading.Thread(target=worker,args=(ctx,action,evaluate,force),name='server-manager-manual-sleep',daemon=True).start()
    except Exception:
        _ACTIVE=False;raise
    return {'ok':True,'result':'VM-Herunterfahren gestartet; Server-Aktion wird im Hintergrund nach Freigabe ausgeführt.'}

def worker(ctx,action,evaluate,force):
    global _ACTIVE
    deadline=time.monotonic()+300;submitted=False
    try:
        while time.monotonic()<deadline:
            con=ctx.db()
            try:decision=evaluate(con,ctx)
            finally:con.close()
            rows=decision.get('blockers',[])
            # Explicit force never bypasses KVM protection or a libvirt state error.
            protected=[b for b in rows if b.get('source')=='KVM']
            if not protected and (force or decision.get('may_sleep')):
                result=actions.run_systemctl(action)
                save(ctx,'completed' if result.get('ok') else 'failed',json.dumps(result,ensure_ascii=False),action)
                return
            if not can_start(decision,force):
                save(ctx,'failed','Server-Aktion abgebrochen: andere Blocker oder unklarer VM-Zustand. Server bleibt an.',action);return
            if not submitted:
                candidate=dict(decision,blockers=protected) if force else decision
                submitted=prepare(candidate,manual=True) is not None
            time.sleep(2)
        save(ctx,'failed','Nach fünf Minuten keine Freigabe: Server bleibt an. VM-Zustände und Blocker prüfen; kein hartes Ausschalten.',action)
    except Exception as exc:save(ctx,'failed','Server-Aktion abgebrochen: '+str(exc),action)
    finally:
        with _LOCK:_ACTIVE=False
