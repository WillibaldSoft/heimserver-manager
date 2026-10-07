from .engine import busy

def get_blockers(ctx=None):
    if not busy():return []
    return [dict(source='DynDNS',type='dyndns-update',title='DynDNS-Aktion läuft',reason='IP-/DNS-Prüfung oder Anbieteraktualisierung',priority=70,url='/dyndns')]
