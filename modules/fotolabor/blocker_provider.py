"""Registered in the manager's central blocker API; also works when ctx is omitted."""
_SERVICE = None
_SHOW = None


def get_blockers(ctx=None):
    if _SERVICE is None:
        return [{'source': 'Fotolabor', 'type': 'error', 'title': 'Fotolabor nicht initialisiert',
                 'reason': 'Jobstatus unbekannt', 'priority': 999}]
    _SERVICE.recover()
    jobs = _SERVICE.query("SELECT id,mode,checked,total FROM fotolabor_jobs WHERE state IN ('queued','running')")
    blockers = [{'source': 'Fotolabor', 'type': 'fotolabor-job', 'title': 'Fotolabor',
             'name': 'Fotolabor', 'reason': f"{j['mode']}: {j['checked']}/{j['total']} Dateien geprüft",
             'priority': 70, 'url': '/fotolabor'} for j in jobs]

    if _SHOW is not None and _SHOW.base is _SERVICE:
        _SHOW.recover()
        blockers.extend({'source':'Fotolabor','type':'fotolabor-fotoshow','title':'Fotoshow erstellen',
                         'name':'Fotoshow','reason':f"Auftrag #{j['id']}: {j['copied']}/{j['total']} Bilder, {j['phase']}",
                         'priority':70,'url':f"/fotolabor/fotoshow/{j['id']}"} for j in _SHOW.active())
    return blockers
