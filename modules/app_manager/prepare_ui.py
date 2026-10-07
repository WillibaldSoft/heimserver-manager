"""Display progress for the existing prepare operation; no update execution changes."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html,json,re
from pathlib import Path
from urllib.parse import quote
from .update_engine import UPDATE_LOG_ROOT
E=lambda x:html.escape(str(x),quote=True)

def result(app_id,run_id):
    if run_id.startswith('.') or not re.fullmatch(r'[A-Za-z0-9_.-]+',run_id):raise ValueError('Ungültige Run-ID.')
    path=Path(UPDATE_LOG_ROOT)/app_id/run_id/'result.json'
    value=json.loads(path.read_text())
    if value.get('app_id')!=app_id or value.get('mode')!='prepare':raise ValueError('Kein passendes Prepare-Ergebnis.')
    return value

def latest(app_id):
    root=Path(UPDATE_LOG_ROOT)/app_id
    if not root.is_dir():return None
    for folder in sorted(root.iterdir(),key=lambda p:p.name,reverse=True):
        if not folder.is_dir():continue
        try:session=json.loads((folder/'session.json').read_text())
        except (OSError,ValueError):continue
        if session.get('mode')!='prepare':continue
        value=dict(run_id=folder.name,state=session.get('state','unknown'),started=session.get('started_at'),finished=session.get('finished_at'),action=session.get('current_action'),url='/apps/'+quote(app_id,safe='')+'/update/runs/'+quote(folder.name,safe=''))
        try:
            data=result(app_id,folder.name)
            value.update(ok=bool(data.get('ok')),url='/apps/'+quote(app_id,safe='')+'/update/prepare?run_id='+quote(folder.name,safe=''))
        except (OSError,ValueError):pass
        return value
    return None

def card(app_id):
    current=latest(app_id)
    body=_ui_html("<div class='card' id='prepare-live-status' role='status' aria-live='polite'><h3>Backup-Vorbereitung</h3>")
    if not current:body+=_ui_html('<p>Noch keine Vorbereitung vorhanden.</p>')
    else:
        state='Erfolgreich vorbereitet' if current.get('ok') else ('Fehlgeschlagen' if current.get('ok') is False else 'In Bearbeitung / Ergebnis noch nicht vorhanden')
        body+=_ui_html('<p>')+E(_ui_text(state))+' · Start: '+E(current.get('started') or '–')+_ui_html('</p>')
        if current.get('finished'):body+=_ui_html('<p>Ende: ')+E(current['finished'])+_ui_html('</p>')
        body+=_ui_html("<a class='btn' href='")+E(current['url'])+_ui_html("'>Ergebnis und Update-Freigabe prüfen</a>")
    return body+_ui_html('</div>')

def script(app_id):
    endpoint='/apps/'+quote(app_id,safe='')+'/update/prepare'
    api='/api/apps/'+quote(app_id,safe='')+'/update/prepare-status'
    return _ui_html('''<script>
(()=>{
 const endpoint=__ENDPOINT__, api=__API__;
 const form=Array.from(document.forms).find(f=>new URL(f.action).pathname===endpoint);
 if(!form)return;
 form.addEventListener('submit',async event=>{
  if(event.defaultPrevented)return;
  event.preventDefault();
  if(form.dataset.running)return;
  form.dataset.running='yes';
  const panel=document.getElementById('prepare-live-status');
  panel.replaceChildren();
  const heading=document.createElement('h3');heading.textContent='Backup wird vorbereitet';panel.append(heading);
  const detail=document.createElement('p');detail.textContent='Vorbereitung gestartet. Der Manager prüft den Update-Plan und erstellt das gebundene Backup.';panel.append(detail);
  const progress=document.createElement('progress');progress.setAttribute('aria-label','Backup-Vorbereitung läuft');panel.append(progress);
  panel.scrollIntoView({behavior:'smooth',block:'center'});
  form.querySelectorAll('button').forEach(b=>b.disabled=true);
  let stopped=false;
  const poll=async()=>{
   if(stopped)return;
   try {const response=await fetch(api,{cache:'no-store'});if(response.ok){const data=await response.json();const job=data.backup;if(job)detail.textContent=job.current_detail||job.current_action||'Backup läuft …';}}catch(e){}
   if(!stopped)setTimeout(poll,2000);
  };poll();
  try {
   const response=await fetch(endpoint,{method:'POST',body:new FormData(form),headers:{'Accept':'application/json','X-Prepare-Async':'1'}});
   const data=await response.json();stopped=true;
   if(data.url){location.assign(data.url);return;}
   throw new Error(data.error||'Ergebnis nicht verfügbar');
  }catch(e){
   stopped=true;progress.remove();
   detail.textContent='Verbindung oder Ergebnisabfrage fehlgeschlagen. Der Auftrag kann weiterlaufen. Bitte nicht erneut starten; Update-Plan oder Update-Runs öffnen und Status prüfen.';
   const link=document.createElement('a');link.href='/apps/'+__APPID__+'/update';link.textContent='Status erneut prüfen';link.className='btn';panel.append(link);
  }
 });
})();
</script>''').replace('__ENDPOINT__',json.dumps(endpoint)).replace('__API__',json.dumps(api)).replace('__APPID__',json.dumps(app_id))
