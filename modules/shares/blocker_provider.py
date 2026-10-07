"""Prevent scheduled host sleep during share validation, activation and rollback."""
from .configuration import _ACTIVE

def get_blockers(ctx=None):
    if not _ACTIVE.is_set():return []
    return [dict(source='Freigaben',type='share-change',title='Freigaben werden geändert',reason='Konfiguration prüfen, aktivieren oder wiederherstellen',priority=90,url='/freigaben')]
