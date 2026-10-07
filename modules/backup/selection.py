"""Server-side source catalog: backup repositories and configured local shares."""
import hashlib
from pathlib import Path

def key(kind,value):return kind+':'+hashlib.sha256(value.encode()).hexdigest()[:24]

def share_rows():
    from modules.shares.configuration import smb_shares,nfs_exports
    rows=[]
    for r in smb_shares():
        if r.get('config',{}).get('available','yes').lower() in ('no','false','0'):continue
        rows.append(('SMB',r['name'],r['path']))
    for r in nfs_exports():
        if r.get('path') and r.get('clients'):rows.append(('NFS',r['path'],r['path']))
    return rows

def catalog(conf):
    from . import external as e
    raw={k:v for k,v in conf.items() if k!='selection'}
    roots,_=e.inventory(raw)
    candidates=e.source_candidates(raw)
    labels={str(p):label for label,p in candidates}
    defaults=set(roots)
    # Stable areas and app/profile folders can be selected without their parent.
    roots=sorted(set(roots)|{p for label,p in candidates if p.is_dir() and not p.is_symlink() and 'aktueller Sicherungsstand' not in label},key=str)
    options=[];photos=[]
    for p in roots:
        if p.parent==e.cfg.STATE_DIR and p.name.startswith(('fotolabor-original-','fotolabor-repair-')):photos.append(p);continue
        options.append(dict(id=key('backup',str(p)),kind='Backupordner',label=labels.get(str(p),p.name),paths=[p],available=True,reason='',default=p in defaults))
    if photos:options.append(dict(id='backup:fotolabor',kind='Backupbereich',label='Fotolabor-Rücksicherungen (alle vorhandenen und künftig angelegten)',paths=photos,available=True,reason='',default=True))
    errors=[];seen=set()
    try:shares=share_rows()
    except (OSError,ValueError) as exc:shares=[];errors.append('Freigaben konnten nicht gelesen werden: '+str(exc))
    for protocol,name,path in shares:
        ident=key(protocol,name+'\0'+path)
        if ident in seen:continue
        seen.add(ident);reason=''
        try:
            if '%' in path:raise ValueError('Dynamischer SMB-Pfad: bitte konkreten Ordner ergänzen.')
            p=e.safe_source(path)
            e.disjoint([p],e.ROOT.resolve())
        except (OSError,ValueError) as exc:reason=str(exc);p=Path(path)
        options.append(dict(id=ident,kind=protocol+'-Freigabe',label=name,paths=[p],available=not reason,reason=reason))
    return options,errors

def chosen(conf,options):
    if 'selection' not in conf:return {row['id'] for row in options if row.get('default',False)}
    return set(conf['selection'])

def selected_sources(conf):
    options,errors=catalog(conf);selected=chosen(conf,options);known={row['id'] for row in options}
    if selected-known:raise ValueError('Ausgewählte Quelle nicht mehr vorhanden oder Freigabepfad geändert. Quellenauswahl prüfen und neu speichern.')
    rows=[]
    for row in options:
        if row['id'] not in selected:continue
        if not row['available']:raise ValueError(row['label']+': '+row['reason'])
        rows.extend((row['label'],path) for path in row['paths'])
    return rows

def save_selection(values):
    from . import external as e
    if e.active():raise ValueError('Externe Sicherung läuft. Auswahl danach ändern.')
    conf=e.settings();options,errors=catalog(conf);known={row['id'] for row in options}
    if set(values)-known:raise ValueError('Ungültige oder veraltete Quellenauswahl. Seite neu laden.')
    conf['selection']=sorted(set(values))
    # Validate every selected share now; a changed share never silently changes the source.
    selected_sources(conf)
    paths,_=e.inventory(conf)
    e.disjoint(paths,e.ROOT.resolve())
    conf['sources']=e.validate_sources(paths,conf.get('uuid','')) if paths else []
    e.cfg.atomic(e.CONFIG,conf)
