from ui_translation import html_literal as _ui_html, text as _ui_text
import hashlib,io,json,secrets,sqlite3,tempfile,time
from pathlib import Path
from flask import request,session,redirect,send_file
from . import pihole_transfer as t,install_jobs as jobs,install_catalog as c

def register(app,ctx,token):
 @app.route('/apps/pihole/installer/transfer/backup/<key>')
 def before_import_download(key):
  try:
   info=jobs.load(key)
   if info.get('action')!='pihole_import' or info.get('app_id')!='pihole':raise ValueError('Kein Pi-hole-Importauftrag.')
   folder=jobs.job_path(key)/'before-import';files=list(folder.glob('*.zip'))
   if len(files)!=1 or files[0].is_symlink():raise ValueError('Rücksicherung noch nicht verfügbar.')
   response=send_file(files[0],as_attachment=True,download_name='Pi-hole-vor-Import-'+key[:8]+'.zip');response.headers['Cache-Control']='no-store';return response
  except (ValueError,OSError):return 'Rücksicherung nicht verfügbar.',404

 @app.route('/apps/pihole/installer/transfer',methods=['GET','POST'])
 def transfer():
  from .install_ui import esc
  body=_ui_html("<div class='card'><h2>Pi-hole · Einstellungen &amp; Listen übertragen</h2><p>Exportdatei auf dem anderen Pi-hole importieren. Keine automatische Synchronisation und keine Verbindung zu anderen Geräten. Native v6- und vom Manager angelegte Docker-Installationen werden unterstützt.</p><a class='btn' href='/apps/pihole'>Zur App</a></div>")
  code=200
  try:
   if request.method=='POST':
    if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return 'Formular abgelaufen.',403
    action=request.form.get('action','')
    if jobs.active():raise ValueError('Laufenden App-Auftrag zuerst abschließen lassen.')
    if action=='export':
     kind=request.form.get('kind','lists')
     if kind=='teleporter' and request.form.get('full_confirm')!='1':raise ValueError('Vollständigen Export einschließlich Zugang und Netzwerkeinstellungen bestätigen.')
     with tempfile.TemporaryDirectory() as tmp:
      data=t.export(t.target(),Path(tmp)).read_bytes()
     if kind in ('allow','deny'):data=t.fritz_export(data,kind);name='Pi-hole-'+kind+'-Domains.txt';mime='text/plain'
     elif kind=='lists':data=t.selected_zip(data,['lists']);name='Pi-hole-Nur-Listen-'+time.strftime('%Y-%m-%d_%H-%M-%S')+'.zip';mime='application/zip'
     elif kind=='teleporter':name='Pi-hole-Teleporter-'+time.strftime('%Y-%m-%d_%H-%M-%S')+'.zip';mime='application/zip'
     else:raise ValueError('Unbekanntes Exportformat.')
     response=send_file(io.BytesIO(data),as_attachment=True,download_name=name,mimetype=mime);response.headers['Cache-Control']='no-store';return response
    if action=='start':
     plan=session.get('pihole_transfer_plan')
     if not plan or time.time()-plan['created']>900:raise ValueError('Vorschau abgelaufen. Datei erneut hochladen.')
     if request.form.get('confirm')!='1':raise ValueError('Import bitte bestätigen.')
     plan=dict(plan)
     if plan['mode']=='teleporter':plan['keys']=request.form.getlist('part')
     t.validate(plan)
     key=jobs.start(c.recipe('pihole'),'127.0.0.1',action='pihole_import',plan=plan)
     session.pop('pihole_transfer_plan',None);return redirect('/apps/installers/jobs/'+key,303)
    if action!='preview':raise ValueError('Ungültige Aktion.')
    upload=request.files.get('file')
    if not upload:raise ValueError('Datei auswählen.')
    data=upload.stream.read(t.LIMIT+1)
    if len(data)>t.LIMIT:raise ValueError('Datei größer als 50 MiB.')
    mode=request.form.get('mode','teleporter')
    if mode=='teleporter':parts=t.inspect(data)
    elif mode in ('allow','deny'):values=t.domains(data.decode('utf-8-sig'));parts=[]
    else:raise ValueError('Ungültiger Importtyp.')
    where=t.target();t.ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    old=session.pop('pihole_transfer_plan',None)
    if old and __import__('re').fullmatch('[a-f0-9]{32}',old.get('upload','')):(t.ROOT/(old['upload']+'.upload')).unlink(missing_ok=True)
    key=secrets.token_hex(16);path=t.ROOT/(key+'.upload')
    with path.open('xb') as f:__import__('os').chmod(path,0o600);f.write(data)
    plan=dict(upload=key,digest=hashlib.sha256(data).hexdigest(),mode=mode,target=where,created=time.time());session['pihole_transfer_plan']=plan
    body+=_ui_html("<div class='card'><h3>Import prüfen</h3><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='start'>")
    if mode=='teleporter':
     labels={'lists':'Listen, genaue Domains, Regex, Gruppen und Clients (ersetzt den entsprechenden Bestand)','config':'Einstellungen (kann Webzugang, Passwort, DNS und DHCP ändern)','leases':'DHCP-Leases (nur für passende Netze)'}
     for part in parts:body+=_ui_html("<p><label><input type='checkbox' name='part' value='")+part+"'"+(' checked' if part=='lists' else '')+"> "+_ui_text(labels[part])+_ui_html('</label></p>')
     body+=_ui_html('<p>Für die Übernahme auf einen anderen Server zunächst nur Listen wählen. Bei Docker haben Umgebungsvariablen Vorrang vor importierten Einstellungen. Nur vertrauenswürdige eigene Teleporter-Dateien verwenden.</p>')
    else:body+=_ui_html('<p>')+str(len(values))+_ui_html(' genaue Domains werden zur ')+(_ui_text('Erlaubnisliste') if mode=='allow' else _ui_text('Sperrliste'))+_ui_html(' hinzugefügt. Bestehende Einträge werden nicht gelöscht. Zuordnung erfolgt nach Pi-hole-Standard, ohne FRITZ!Box-Zugangsprofile.</p>')
    body+=_ui_html("<p>Vorher wird eine Teleporter-Rücksicherung beim Auftrag abgelegt. Import und Neustart können DNS kurz unterbrechen. Bei Fehlern sind Teiländerungen möglich; keine automatische Rücknahme.</p><label><input type='checkbox' name='confirm' value='1' required> Importumfang und Ziel dieses Servers geprüft.</label><p><button class='btn'>Auswahl importieren</button></p></form></div>")
   else:
    t.target()
    previous=[]
    if jobs.JOBS.is_dir():
     for folder in jobs.JOBS.iterdir():
      if not folder.is_dir():continue
      try:info=json.loads((folder/'status.json').read_text())
      except (OSError,ValueError):continue
      if info.get('action')=='pihole_import':previous.append(info)
    if previous:
     body+=_ui_html("<div class='card'><h3>Letzte Importe und Rücksicherungen</h3>")
     for info in sorted(previous,key=lambda x:x.get('created',0),reverse=True)[:5]:
      key=info['id'];body+=_ui_html("<p><a href='/apps/installers/jobs/")+esc(key)+"'>"+esc(_ui_text(info.get('state')))+_ui_html(" · Auftrag</a> · <a href='/apps/pihole/installer/transfer/backup/")+esc(key)+_ui_html("'>Sicherung vor Import herunterladen</a></p>")
     body+=_ui_html('</div>')
    body+=_ui_html("<div class='card'><h3>Für ein anderes Pi-hole exportieren</h3><p><b>Empfohlen: Nur Listen.</b> Enthält abonnierte Listen, Domainregeln, Gruppen und Clients. Keine Webports, Passwörter, DNS-/DHCP-Einstellungen oder DHCP-Leases. Auch beim Import über die Pi-hole-Webseite bleiben diese Einstellungen erhalten, weil sie im ZIP fehlen. Gruppen und Clients können gerätespezifische Angaben enthalten.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='export'><input type='hidden' name='kind' value='lists'><button class='btn'>Nur Listen als ZIP herunterladen</button></form><details><summary>Vollständiger Export für Sicherung / Migration</summary><p>Enthält auch Zugangsinformationen und Netzwerkeinstellungen. Beim Import auf einem anderen Server können Webzugang, DNS und DHCP verändert werden. Keine langfristige Anfragehistorie. Geschützt aufbewahren und nur über LAN/VPN oder HTTPS übertragen.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='export'><input type='hidden' name='kind' value='teleporter'><label><input type='checkbox' name='full_confirm' value='1' required> Vollständige Konfiguration mit Zugang und Netzwerk bewusst exportieren.</label><p><button class='btn'>Vollständiges Teleporter-ZIP herunterladen</button></p></form></details></div>")
    body+=_ui_html("<div class='card'><h3>Importieren</h3><form method='post' enctype='multipart/form-data'>")+token()+_ui_html("<input type='hidden' name='action' value='preview'><label>Format <select name='mode'><option value='teleporter'>Pi-hole v6 · Teleporter-ZIP</option><option value='deny'>Textliste · gesperrte Domains hinzufügen</option><option value='allow'>Textliste · erlaubte Domains hinzufügen</option></select></label><p><input type='file' name='file' accept='.zip,.txt' required></p><p>ZIP maximal 50 MiB; Text: eine genaue Domain pro Zeile, höchstens 500. Keine URLs, Regex oder Platzhalter.</p><button class='btn'>Datei prüfen</button></form></div>")
    body+=_ui_html("<div class='card'><details><summary>Optional: Listen für FRITZ!Box</summary><p>Nur aktivierte genaue Domains aus der eigenen Erlaubnis-/Sperrliste. Keine abonnierte Gravity-Gesamtliste, Regex oder Gruppen-/Clientregeln. Gruppenbezogene Domains werden global exportiert; vor Übernahme prüfen. Höchstens 500 Einträge, keine stille Kürzung.</p>")
    for kind,label in [('deny','Gesperrte Domains'),('allow','Erlaubte Domains')]:body+=_ui_html("<form method='post'>")+token()+_ui_html("<input type='hidden' name='action' value='export'><input type='hidden' name='kind' value='")+kind+_ui_html("'><button class='btn'>")+_ui_text(label)+_ui_html(" als Text herunterladen</button></form>")
    body+=_ui_html("<p>FRITZ!Box: Internet → Filter → Listen. Domains manuell übernehmen und dem gewünschten Zugangsprofil zuordnen. Erlaubnislisten in der FRITZ!Box sind keine Pi-hole-Ausnahmen: Bei aktivem Erlaubnisfilter wird alles andere gesperrt. Bedienung hängt von FRITZ!OS ab; kein direkter Routerimport oder Zugriff auf Router-Zugangsdaten. Für den Rückweg Domains aus der FRITZ!Box in eine Textdatei kopieren und oben importieren.</p><a target='_blank' rel='noopener' href='https://fritz.com/de-at/apps/knowledge-base/fritz-box-dsl-fiber-7-90/3395_Filterlisten-fur-Internetseiten-in-FRITZ-Box-erstellen'>FRITZ!-Anleitung</a></details></div>")
  except (ValueError,OSError,sqlite3.Error) as exc:body+=_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html('</p></div>');code=400
  return ctx.page(_ui_text('Pi-hole · Übertragen'),body,'Apps'),code
