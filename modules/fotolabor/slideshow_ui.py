"""Folder browser and persistent download history inside the Fotolabor module."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json
from flask import request,redirect,jsonify,send_file
from . import slideshow,blocker_provider

STATES={'queued':'Wartet','running':'Läuft','completed':'Fertig','cancelled':'Abgebrochen','failed':'Fehlgeschlagen','interrupted':'Unterbrochen'}
PHASES={'inventory':'Bilder erfassen','copy':'Bilder kopieren','package':'Paket erstellen','verify':'Paket prüfen','finished':'Abgeschlossen'}
STYLE="""<style>.show-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}.show-input{display:block;box-sizing:border-box;width:100%;max-width:600px;margin:6px 0 16px;padding:10px;background:#111827;color:#eee;border:1px solid #526075;border-radius:7px}.show-folders{max-height:420px;overflow:auto;border:1px solid #526075;border-radius:8px;padding:8px}.show-folder{display:flex;align-items:center;gap:10px;padding:6px}.show-folder button{white-space:normal;overflow-wrap:anywhere;text-align:left}.show-selected li{margin:8px 0;overflow-wrap:anywhere}.show-muted{opacity:.8}.show-state{font-weight:bold}#folder-path{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"""


def register(app,ctx,base,token,protected):
    service=slideshow.Service(base);app.extensions['fotolabor_slideshows']=service
    blocker_provider._SHOW=service
    e=lambda x:ctx.esc(str(x if x is not None else ''))
    def page(body):return ctx.page(_ui_text('Fotolabor – Fotoshow'),STYLE+body,'Fotolabor')
    def error(exc,status=400):
        return page(_ui_html("<div class='card'><h2>Fotoshow konnte nicht erstellt werden</h2><p class='err'>")+e(_ui_text(exc))+_ui_html("</p><a class='btn' href='/fotolabor/fotoshow'>Zur Fotoshow</a></div>")),status
    def job_html(row):
        jid=row['id'];selection=json.loads(row['options']);active=row['state'] in ('queued','running')
        body=f'{_ui_html("<div class='card' id='show-")}{jid}{_ui_html("'><h3>#")}{jid}{_ui_html(' · ')}{e(selection['filename'])}{_ui_html("</h3><p><span class='show-state'>")}{e(STATES[row['state']])}{_ui_html('</span> · ')}{e(PHASES[row['phase']])}{_ui_html(' · ')}{e(row['started'])}{_ui_html('</p>')}'
        body+=_ui_html('<p>Ordner: ')+e(' · '.join(v or 'Gesamtes Fotolabor' for v in selection['folders']))+_ui_html('</p>')
        body+=f'{_ui_html('<p>')}{e(selection['delay'])}{_ui_html(' Sekunden pro Bild · ')}{(_ui_text('Mit Unterordnern') if selection['recursive'] else _ui_text('Ohne Unterordner'))}{_ui_html(' · ')}{(_ui_text('Zufällig') if selection['random'] else _ui_text('Nach Pfad sortiert'))}{_ui_html(' · ')}{(_ui_text('Eingepasst') if selection['fit'] else _ui_text('Originalgröße'))}{_ui_html('</p>')}'
        body+=f'{_ui_html('<p>')}{row['copied']}{' / '}{row['total']}{_ui_html(' Bilder kopiert · Quelldaten ')}{row['bytes'] / 1024 ** 2:.1f}{_ui_html(' MiB</p>')}'
        if active:
            if row['phase']=='copy':body+=f"<progress value='{row['copied']}' max='{max(row['total'],1)}' style='width:100%'></progress>"
            else:body+="<progress style='width:100%'></progress>"
            body+=f'{_ui_html('<p>')}{e(row['current'])}{_ui_html("</p><form method='post' action='/fotolabor/fotoshow/")}{jid}{_ui_html("/cancel'><input type='hidden' name='csrf' value='")}{e(token())}{_ui_html("'><button class='btn' ")}{('disabled' if row['cancel'] else '')}{_ui_html('>')}{(_ui_text('Abbruch angefordert …') if row['cancel'] else _ui_text('Erstellung abbrechen'))}{_ui_html('</button></form>')}'
        if row['error']:body+=_ui_html("<p class='err'>")+e(_ui_text(row['error']))+_ui_html('</p>')
        if row['state']=='completed':
            body+=f'{_ui_html("<p><a class='btn' href='/fotolabor/fotoshow/")}{jid}{_ui_html("/download'>Fotoshow herunterladen (")}{row['output_bytes'] / 1024 ** 2:.1f}{_ui_html(' MiB)</a></p><details><summary>SHA-256-Prüfsumme</summary><pre>')}{e(row['sha256'])}{_ui_html('</pre></details>')}'
        return body+_ui_html('</div>')
    @app.route('/api/fotolabor/fotoshow/folders')
    def fotoshow_folders():
        try:return jsonify(slideshow.folders(service.root,request.args.get('path',''),int(request.args.get('offset','0'))))
        except (OSError,ValueError) as exc:return jsonify(error=str(exc)),400
    @app.route('/fotolabor/fotoshow',methods=['GET','POST'])
    def fotoshow_page():
        if request.method=='POST':
            if not protected():return error('Formular abgelaufen. Bitte Seite neu laden.',403)
            try:
                data=dict(request.form);data['folders']=json.loads(request.form.get('folders','[]'))
                jid=service.start(data)
            except (OSError,ValueError,TypeError) as exc:return error(exc)
            return redirect('/fotolabor/fotoshow/'+str(jid),303)
        body=_ui_html("<div class='card'><h2>Fotoshow erstellen</h2><p><a class='btn' href='/fotolabor'>Fotolabor</a> <a class='btn' href='/fotolabor/fotoshow/history'>Meine Fotoshows</a></p><p>Ausgewählte JPG-/JPEG-Bilder als portable Linux-Fotoshow (.run) zusammenstellen. Die Originale werden nur gelesen.</p></div>")
        body+=f'{_ui_html("<form method='post' id='show-form'><input type='hidden' name='csrf' value='")}{e(token())}{_ui_html("'><input type='hidden' name='folders' id='selected-folders' value='[]'><div class='show-grid'><div class='card'><h3>1. Ordner auswählen</h3><p>Basis: <code>")}{e(service.root)}{_ui_html("</code></p><p id='folder-path'>Ordner werden geladen …</p><p><button class='btn' id='folder-up' type='button'>Eine Ebene höher</button> <button class='btn' id='folder-add' type='button'>Diesen Ordner auswählen</button></p><p id='folder-info'></p><div class='show-folders' id='folder-list'></div><p id='folder-error' class='err' role='alert'></p><noscript>Für die klickbare Ordnerauswahl bitte JavaScript aktivieren.</noscript></div><div class='card'><h3>Ausgewählte Ordner</h3><p>Mehrere Ordner lassen sich kombinieren. Überlappende Auswahlen erzeugen keine doppelten Bilder.</p><ul class='show-selected' id='folder-selection'></ul><label><input type='checkbox' name='recursive' value='1' checked> Unterordner einbeziehen</label></div></div>")}'
        body+=_ui_html("<div class='card'><h3>2. Wiedergabe und Dateiname</h3><div class='show-grid'><label>Dateiname<input class='show-input' name='filename' value='Fotoshow' maxlength='120' required placeholder='Urlaub-2026.run'></label><label>Sekunden pro Bild<input class='show-input' name='delay' type='number' min='0.1' max='3600' step='0.01' value='5' required></label></div><p><label><input type='checkbox' name='random' value='1'> Zufällige Reihenfolge</label></p><p><label><input type='checkbox' name='fit' value='1' checked> An Bildschirm anpassen, ohne Verzerrung</label></p><p class='show-muted'>Ohne Zufallsmodus werden Bilder nach ihrem relativen Pfad sortiert. Es werden ausschließlich JPG/JPEG aufgenommen; symbolische Links werden nicht verfolgt. Bilder werden beim Kopieren auf JPEG-Dateianfang geprüft, nicht vollständig dekodiert.</p><button class='btn' id='show-submit' disabled>Fotoshow im Hintergrund erstellen</button><p id='selection-hint'>Bitte mindestens einen Ordner auswählen.</p></div></form>")
        body+=_ui_html("<div class='card'><h3>3. Herunterladen und starten</h3><p>Nach Abschluss steht die .run-Datei zum Download bereit. Im Download-Dialog wählst du deinen lokalen Zielordner.</p><pre>bash Fotoshow.run</pre><p>Auf dem Wiedergaberechner: Linux mit grafischer Sitzung und <code>feh</code>. Falls feh fehlt, unter Debian/Mint/Ubuntu einmal <code>sudo apt install feh</code> ausführen. Pfeiltasten wechseln das Bild; Escape beendet die Show. Die Bilder werden temporär entpackt und bei normalem Ende entfernt.</p><p>Pakete bleiben auf dem Server unter <code>")+e(service.output)+_ui_html("</code> gespeichert. Die Bilddateien und ihre relativen Quellpfade sind im Paket enthalten.</p></div>")
        body+=_ui_html(BROWSER_JS)
        if service.active():body=_ui_html("<div class='card'><p>Eine Fotoshow wird erstellt. <a href='/fotolabor/fotoshow/history'>Fortschritt öffnen</a></p></div>")+body
        return page(body)
    @app.route('/fotolabor/fotoshow/history')
    def fotoshow_history():
        rows=service.jobs();body=_ui_html("<div class='card'><h2>Meine Fotoshows</h2><a class='btn' href='/fotolabor/fotoshow'>Neue Fotoshow</a> <a class='btn' href='/fotolabor'>Fotolabor</a></div>")
        body+=''.join(job_html(row) for row in rows) if rows else _ui_html("<div class='card'><p>Noch keine Fotoshows erstellt.</p></div>")
        if any(r['state'] in ('queued','running') for r in rows):body+=_ui_html("<script>setTimeout(()=>location.reload(),3000)</script>")
        return page(body)
    @app.route('/fotolabor/fotoshow/<int:jid>')
    def fotoshow_job(jid):
        try:row=service.get(jid)
        except ValueError as exc:return error(exc,404)
        body=_ui_html("<div class='card'><a class='btn' href='/fotolabor/fotoshow'>Neue Fotoshow</a> <a class='btn' href='/fotolabor/fotoshow/history'>Alle Fotoshows</a></div>")+job_html(row)
        if row['state'] in ('queued','running'):body+=_ui_html("<script>setTimeout(()=>location.reload(),2500)</script>")
        return page(body)
    @app.route('/fotolabor/fotoshow/<int:jid>/cancel',methods=['POST'])
    def fotoshow_cancel(jid):
        if not protected():return error('Formular abgelaufen.',403)
        try:service.get(jid);service.cancel(jid)
        except ValueError as exc:return error(exc,404)
        return redirect('/fotolabor/fotoshow/'+str(jid),303)
    @app.route('/fotolabor/fotoshow/<int:jid>/download')
    def fotoshow_download(jid):
        try:row,path=service.download(jid)
        except ValueError as exc:return error(exc,404)
        result=send_file(path,as_attachment=True,download_name=json.loads(row['options'])['filename'],mimetype='application/octet-stream',conditional=True)
        result.headers['Cache-Control']='private, no-store';result.headers['X-Content-Type-Options']='nosniff'
        return result


BROWSER_JS=r"""<script>
(()=>{
const chosen=new Set();let current='',parent='',busy=false;
const el=id=>document.getElementById(id);
function selections(){
 el('selected-folders').value=JSON.stringify([...chosen]);el('folder-selection').replaceChildren();
 for(const path of chosen){const li=document.createElement('li');li.append(document.createTextNode(path||'Gesamtes Fotolabor'));const button=document.createElement('button');button.type='button';button.className='pill';button.textContent='Entfernen';button.addEventListener('click',()=>{chosen.delete(path);selections();});li.append(' ',button);el('folder-selection').append(li);}
 el('show-submit').disabled=!chosen.size;el('selection-hint').textContent=chosen.size?chosen.size+' Ordner ausgewählt.':'';
 for(const input of el('folder-list').querySelectorAll('input[type=checkbox]'))input.checked=chosen.has(input.value);
}
async function browse(path,offset=0){
 if(busy)return;busy=true;el('folder-error').textContent='';
 try{
  const response=await fetch('/api/fotolabor/fotoshow/folders?'+new URLSearchParams({path,offset}));const data=await response.json();if(!response.ok)throw Error(data.error||'Ordner nicht lesbar');
  current=data.path;parent=data.parent;el('folder-path').textContent=current||'Gesamtes Fotolabor';el('folder-up').disabled=!current;
  el('folder-info').textContent=data.jpegs+' JPG/JPEG direkt in diesem Ordner · '+data.total+' Unterordner';
  if(!offset)el('folder-list').replaceChildren();else el('folder-more')?.remove();
  for(const row of data.children){const wrap=document.createElement('div');wrap.className='show-folder';const check=document.createElement('input');check.type='checkbox';check.value=row.path;check.checked=chosen.has(row.path);check.setAttribute('aria-label',row.name+' auswählen');check.addEventListener('change',()=>{if(check.checked)chosen.add(row.path);else chosen.delete(row.path);selections();});const button=document.createElement('button');button.type='button';button.className='btn';button.textContent='📁 '+row.name;button.addEventListener('click',()=>browse(row.path));wrap.append(check,button);el('folder-list').append(wrap);}
  if(data.next_offset!==null){const more=document.createElement('button');more.id='folder-more';more.type='button';more.className='btn';more.textContent='Weitere Ordner laden';more.addEventListener('click',()=>browse(current,data.next_offset));el('folder-list').append(more);}
 }catch(error){el('folder-error').textContent=error.message;}finally{busy=false;}
}
el('folder-up').addEventListener('click',()=>browse(parent));el('folder-add').addEventListener('click',()=>{if(!busy){chosen.add(current);selections();}});
el('show-form').addEventListener('submit',event=>{if(!chosen.size){event.preventDefault();return;}el('show-submit').disabled=true;el('show-submit').textContent='Auftrag wird gestartet …';});
browse('');selections();
})();
</script>"""
