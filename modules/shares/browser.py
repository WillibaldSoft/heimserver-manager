"""Small data-folder picker; does not follow symlinks or expose system directories."""
from ui_translation import html_literal as _ui_html
from server_settings import get as host_setting
from pathlib import Path
from flask import request,jsonify

ROOTS=[Path(p) for p in host_setting('share_roots')]

def listing(value):
    roots=[p for p in ROOTS if p.is_dir() and not p.is_symlink()]
    if not value:return {'path':'','parent':'','folders':[{'name':str(p),'path':str(p)} for p in roots]}
    p=Path(value)
    if '..' in p.parts or not any(p==r or p.is_relative_to(r) for r in roots):raise ValueError('Bitte einen angebotenen Datenordner wählen.')
    if any(part.is_symlink() for part in [p,*p.parents]):raise ValueError('Symbolische Links werden nicht geöffnet.')
    children=[]
    for entry in sorted(p.iterdir(),key=lambda v:v.name.casefold()):
        if not entry.is_symlink() and entry.is_dir():children.append({'name':entry.name,'path':str(entry)})
    return {'path':str(p),'parent':'' if p in roots else str(p.parent),'folders':children[:500],'truncated':len(children)>500}

def register(app):
    @app.route('/api/freigaben/folders')
    def shares_folders():
        try:return jsonify(listing(request.args.get('path','')))
        except (ValueError,OSError) as exc:return jsonify(error=str(exc)),400

HTML="""<details id='share-picker'><summary>Ordner auf dem Server auswählen</summary><p id='picker-path'></p><div class='share-tabs'><button class='btn' type='button' id='picker-up'>Übergeordneter Ordner</button><button class='btn' type='button' id='picker-use'>Diesen Ordner verwenden</button></div><div id='picker-folders' style='max-height:300px;overflow:auto;margin:12px 0'></div><p id='picker-error' role='status'></p></details>
<script>(()=>{let current='',parent='',busy=false;const by=id=>document.getElementById(id);async function browse(path){if(busy)return;busy=true;by('picker-use').disabled=true;by('picker-error').textContent='';try{const r=await fetch('/api/freigaben/folders?'+new URLSearchParams({path}));const data=await r.json();if(!r.ok)throw Error(data.error);current=data.path;parent=data.parent;by('picker-path').textContent=current||'Datenbereiche';by('picker-up').disabled=!current;by('picker-folders').replaceChildren();for(const row of data.folders){const button=document.createElement('button');button.type='button';button.className='btn';button.textContent='📁 '+row.name;button.style.margin='4px';button.addEventListener('click',()=>browse(row.path));by('picker-folders').append(button);}by('picker-use').disabled=!current;if(data.truncated)by('picker-error').textContent='Erste 500 Ordner angezeigt. Weitere Pfade direkt eingeben.';}catch(e){by('picker-error').textContent=e.message;}finally{busy=false;}}by('picker-up').addEventListener('click',()=>browse(parent));by('picker-use').addEventListener('click',()=>{if(!busy&&current){document.querySelector('input[name=path]').value=current;by('share-picker').open=false;}});by('share-picker').addEventListener('toggle',()=>{if(by('share-picker').open&&!by('picker-folders').childElementCount)browse('');});})();</script>"""
