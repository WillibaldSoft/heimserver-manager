"""Review and confirm selected external recovery."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets,time
from pathlib import Path
from html import escape
from flask import request,session,redirect
from . import external as e,external_restore as r

def E(value):return escape(str(value),quote=True)
def register(app,ctx):
 @app.route('/backup/external/restore',methods=['GET','POST'])
 def external_restore():
  token="<input type='hidden' name='auth_csrf' value='"+E(session.setdefault('auth_csrf',secrets.token_urlsafe(32)))+"'>"
  body=_ui_html("<div class='card'><h2>Externe Sicherung zurückholen</h2><p>1 · Sicherungsstand auswählen → 2 · Ordner und Ziel prüfen → 3 · Zurückkopieren</p><p>Nur abgeschlossene externe Sicherungen werden angeboten. Die Auswahl stammt aus diesem Sicherungsstand, unabhängig von der heutigen Backupauswahl. Die Platte muss unter Speicher eingehängt sein.</p><p>Ausgewählte Ordner werden mit Linux-Rechten in einen neuen datierten Ordner kopiert und geprüft. Vorhandene Dateien werden nicht überschrieben. Dies stellt keine Anwendungen, VMs, Freigabekonfiguration oder ein startfähiges Betriebssystem automatisch wieder her. Enthaltene App-/VM-Backups anschließend im jeweiligen Modul verwenden.</p><a class='btn' href='/backup/external'>Sicherung und Auftragsstatus</a> <a class='btn' href='/speicher'>Speicher</a></div>")
  code=200
  try:
   if request.method=='POST':
    if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):return 'Formular abgelaufen. Bitte neu laden.',403
    if e.active():raise ValueError('Externer Auftrag läuft. Abschluss abwarten.')
    if request.form.get('action')=='start':
     ident=request.form.get('plan','')
     if not secrets.compare_digest(ident,session.get('external_restore_plan','!')):raise ValueError('Prüfung abgelaufen; erneut auswählen.')
     plan=e.cfg.read(e.ROOT/('restore-plan-'+ident+'.json'))
     if time.time()-plan.get('created',0)>900 or request.form.get('confirm')!='1':raise ValueError('Rücksicherung erneut prüfen und bestätigen.')
     r.start(ctx,plan['plan']);session.pop('external_restore_plan',None)
     (e.ROOT/('restore-plan-'+ident+'.json')).unlink(missing_ok=True)
     return redirect('/backup/external',303)
    if request.form.get('action')!='preview':raise ValueError('Unbekannte Aktion.')
    plan=r.prepare(e.settings(),request.form.get('snapshot',''),request.form.getlist('source'),request.form.get('target',''))
    ident=secrets.token_hex(16);session['external_restore_plan']=ident
    e.cfg.atomic(e.ROOT/('restore-plan-'+ident+'.json'),{'created':time.time(),'plan':plan})
    body+=_ui_html("<div class='card'><h3>Rücksicherung prüfen</h3><p>Stand: ")+E(plan['snapshot'])+_ui_html('</p><p>Ziel: ')+E(plan['target'])+_ui_html("/Ruecksicherung-Datum-Uhrzeit-Kennung</p><p>")+str(len(plan['selected']))+_ui_html(' Quellordner ausgewählt. Benötigter Platz wird vor dem Kopieren geprüft.</p><details><summary>Ausgewählte Ordner anzeigen</summary><ul>')+''.join(_ui_html('<li>')+E(row['path'])+' → '+E(row['directory'])+_ui_html('</li>') for row in plan['selected'])+_ui_html("</ul></details><form method='post'>")+token+_ui_html("<input type='hidden' name='action' value='start'><input type='hidden' name='plan' value='")+ident+_ui_html("'><label><input type='checkbox' name='confirm' value='1' required> Auswahl und Ziel geprüft; externe Sicherung bleibt angeschlossen und unverändert.</label><p><button class='btn'>Auswahl zurückkopieren</button></p></form></div>")
   else:
    conf=e.settings();options=r.snapshots(conf);name=request.args.get('snapshot','')
    body+=_ui_html("<div class='card'><form method='get'><label>Sicherungsstand <select name='snapshot' required><option value=''>Bitte wählen</option>")+''.join(_ui_html("<option value='")+E(n)+"'"+(' selected' if n==name else '')+'>'+E(n)+' · '+str(count)+_ui_html(' Ordner</option>') for n,count in options)+_ui_html("</select></label> <button class='btn'>Inhalte anzeigen</button></form>")
    if not options:body+=_ui_html('<p>Keine abgeschlossenen externen Sicherungsstände gefunden.</p>')
    body+=_ui_html('</div>')
    if name:
     _,rows,_=r.snapshot(r.repository(conf),name)
     # Individual sources, with the many flat photo copies kept in one collapsible group.
     photos=[x for x in rows if Path(x['path']).name.startswith(('fotolabor-original-','fotolabor-repair-'))]
     photo_ids={x['directory'] for x in photos}
     normal=[x for x in rows if x['directory'] not in photo_ids]
     body+=_ui_html("<div class='card'><h3>Ordner auswählen</h3><form method='post'>")+token+_ui_html("<input type='hidden' name='action' value='preview'><input type='hidden' name='snapshot' value='")+E(name)+"'>"
     for label,items in [('Backupordner und Freigabedaten',normal),('Fotolabor-Rücksicherungen',photos)]:
      if not items:continue
      body+=_ui_html('<details><summary>')+_ui_text(label)+' · '+str(len(items))+_ui_html("</summary><button type='button' class='btn' onclick=\"this.parentElement.querySelectorAll('input[type=checkbox]').forEach(x=>x.checked=true)\">Alle auswählen</button> <button type='button' class='btn' onclick=\"this.parentElement.querySelectorAll('input[type=checkbox]').forEach(x=>x.checked=false)\">Alle abwählen</button>")
      for row in items:body+=_ui_html("<p><label><input type='checkbox' name='source' value='")+E(row['directory'])+"'> "+E(row['path'])+_ui_html('</label></p>')
      body+=_ui_html('</details>')
     body+=_ui_html("<p><label>Vorhandener Zielordner auf dem Server <input name='target' required placeholder='/pfad/zur/ruecksicherung'></label></p><p>Darin entsteht ein neuer Ordner. Zur Auswahl gehören jeweils alle Unterordner. Die Freigabe oder App selbst wird dadurch nicht umgestellt. UID/GID werden numerisch übernommen; auf einem anderen Server die Benutzerzuordnung vor Verwendung prüfen.</p><button class='btn'>Rücksicherung prüfen</button></form></div>")
  except (ValueError,OSError) as exc:body+=_ui_html("<div class='card'><p class='err'>")+E(_ui_text(exc))+_ui_html('</p></div>');code=400
  return ctx.page(_ui_text('Externe Rücksicherung'),body,'Backup'),code
