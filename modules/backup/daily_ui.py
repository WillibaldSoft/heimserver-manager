from ui_translation import html_literal as _ui_html, text as _ui_text
import datetime,html,secrets
from flask import request,session,redirect
from . import daily
E=lambda v:html.escape(str(v),quote=True)
def register(app,ctx):
 @app.route('/backup/daily',methods=['GET','POST'])
 def daily_page():
  message='';code=200
  if request.method=='POST':
   if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):return 'Formular abgelaufen.',403
   try:
    daily.configure(request.form.get('enabled')=='1',request.form.get('time','09:15'));return redirect('/backup/daily',303)
   except (ValueError,OSError) as exc:message=str(exc);code=400
  conf=daily.settings();info=daily.state();token=session.setdefault('auth_csrf',secrets.token_urlsafe(32))
  body=_ui_html("<div class='card'><h2>Tägliche Sicherungskette</h2><p>OSCam → Nextcloud Config → Nextcloud Apps/Core → Nextcloud DB → Server Manager. Die Schritte laufen nacheinander.</p>")
  body+=_ui_html('<p>Der erste Dateistand ist vollständig; danach sparen Hardlinks für unveränderte Dateien Platz. Datenbanken werden vollständig gesichert. Nextcloud ist während seiner drei Schritte im Wartungsmodus. Benutzerdateien bleiben im bisherigen separaten Datenbackup.</p>')
  body+=_ui_html('<p>Ziel: <code>')+E(daily.root())+_ui_html('</code>. Keine automatische Löschung alter Stände. Backup-Datenträger und freier Platz müssen verfügbar sein.</p>')
  body+=_ui_html('<p>Ausführung bei laufendem Manager ab Serverzeit; im Schlaf wird nicht aufgeweckt. Bei späterem Start wird der aktuelle Tag nachgeholt. Laufende App-Aufträge werden abgewartet.</p>')
  if message:body+=_ui_html('<p>')+E(_ui_text(message))+_ui_html('</p>')
  body+=_ui_html("<form method='post'><input type='hidden' name='auth_csrf' value='")+E(token)+_ui_html("'><label><input type='checkbox' name='enabled' value='1'")+(' checked' if conf.get('enabled') else '')+_ui_html("> Aktiv</label> <label>Täglich ab <input type='time' name='time' value='")+E(conf.get('time','09:15'))+_ui_html("' required></label> <button>Speichern</button></form>")
  body+=_ui_html('<p>Frühestens ab: ')+E(conf.get('start_date',_ui_text('nach Aktivierung ab morgen')))+_ui_html('</p><h3>Letzter Lauf</h3><p>Status: ')+E(_ui_text(info.get('state','Noch nicht gelaufen')))+' · '+E(info.get('current',''))+_ui_html('</p>')
  if info.get('error') and info.get('state')=='failed':body+=_ui_html('<p>')+E(_ui_text(info['error']))+_ui_html('</p>')
  for key,result in info.get('steps',{}).items():body+=_ui_html('<p>')+E(daily.LABELS.get(key,key))+': '+(_ui_text('OK') if result['ok'] else 'Fehler: '+E(_ui_text(result.get('error',''))))+(_ui_html('</p>'))
  body+=_ui_html("<p><a href='/backup'>Zurück</a></p></div>")
  return ctx.page(_ui_text('Tägliche Sicherungskette'),body,'Backup'),code
 daily.start(app)
