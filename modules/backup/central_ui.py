from ui_translation import html_literal as _ui_html, text as _ui_text
import html,json,socket,os
from urllib.parse import urlencode
from flask import request,send_file,session
from . import central
import server_settings as cfg
E=lambda v:html.escape(str(v),quote=True)

def register(app,ctx):
    @app.route('/backup/central',methods=['GET','POST'])
    def central_backup():
        msg='';code=200
        if request.method=='POST':
            try:
                if request.form.get('confirm')!='yes':raise ValueError('Umfang und SMB-Eigentümer bestätigen.')
                central.start(request.form.get('user',''));msg='Sicherung gestartet. Status mit Aktualisieren abrufen.'
            except (ValueError,OSError) as e:msg=str(e);code=400
        users=central.identities();options=''.join(_ui_html("<option value='")+E(u['user'])+"'>"+E(u['user'])+' · '+str(u['uid'])+':'+str(u['gid'])+_ui_html('</option>') for u in users)
        body=_ui_html("<div class='card'><h2>Server- und Client-Sicherungen</h2><p><a class='btn' href='/backup/external'>Externe Gesamtsicherung · inkrementell</a></p><p>Speicherziel: <code>")+E(cfg.get('system_backup_root'))+_ui_html("</code> · <a href='/settings/server-paths'>Pfad ändern</a></p><p>Server: linux-server-backup/Rechner/Sicherungsstand<br>Clients: linux-client-backup/Rechner/Benutzer/Sicherungsstand</p><p><a class='btn' href='/backup/central'>Aktualisieren</a> <a class='btn' href='/backup'>Bestehende App-Sicherungen</a> <a class='btn' href='/freigaben'>SMB-Zugriffsrechte verwalten</a></p></div>")
        if msg:body+=_ui_html("<div class='card'><p>")+E(_ui_text(msg))+_ui_html('</p></div>')
        job=central.status()
        if job:
            state=job.get('state')
            if state=='running' and not central.active():state='unterbrochen – kein vollständiger Sicherungsstand bestätigt'
            body+=_ui_html("<div class='card'><h3>Letzte Server-Sicherung</h3><p>")+E(_ui_text(state))+' · '+E(_ui_text(job.get('message','')))+_ui_html('</p><p>')+E(job.get('destination',''))+_ui_html('</p></div>')
        body+=_ui_html("<div class='card'><h2>Serverkonfiguration sichern</h2><p>Sichert /etc, /usr/local und den Server-Manager-Quellcode. Enthält Zugangsdaten und Schlüssel. Keine vollständige Systemsicherung: Datenbanken, Anwendungsdaten und VM-Datenträger weiterhin über die bestehenden App-Sicherungen sichern.</p><form method='post'><input type='hidden' name='auth_csrf' value='")+E(session.get('auth_csrf',''))+_ui_html("'><label>SMB-Eigentümer der Sicherung <select name='user'>")+options+_ui_html("</select></label><p><label><input type='checkbox' name='confirm' value='yes' required> Umfang geprüft; der ausgewählte Benutzer darf die enthaltenen Schlüssel und Zugangsdaten lesen.</label></p><button class='btn'>Serverkonfiguration jetzt sichern</button></form></div>")
        host=request.host.split(':')[0]
        body+=_ui_html("<div class='card'><h2>Client-Agent / Live-USB herunterladen</h2><p>Dasselbe Paket ist portabel nutzbar oder installiert einen Eintrag „Server-Backup – Jetzt sichern“ im Client-Anwendungsmenü. Es enthält keine Passwörter. Die SMB-Anmeldung erfolgt am Client.</p><form method='post' action='/backup/client-tool'><input type='hidden' name='auth_csrf' value='")+E(session.get('auth_csrf',''))+_ui_html("'><p><label>Ursprünglicher Clientname <input name='client' pattern='[A-Za-z0-9][A-Za-z0-9._-]{0,63}' required></label></p><p><label>Zugeordneter Serverbenutzer <select name='user'>")+options+_ui_html("</select></label></p><p><label>SMB-Freigabe <input name='share' value='")+E('//'+host+'/Backup')+_ui_html("' required size='40'></label></p><button class='btn'>USB-/Client-Paket herunterladen</button></form><p>Beim Download wird ein privater Client-/Benutzerordner in der Backupablage angelegt. Der Benutzer muss bereits Zugriff auf die SMB-Freigabe besitzen. UID/GID werden zum Vergleich mitgegeben; die optionale Angleichung ist separat im USB-Werkzeug über identity_sync.py verfügbar (Vorschau, Kollisionsprüfung, ausdrückliche Bestätigung). Sie setzt ein offline eingebundenes System mit Root und Home auf einem Dateisystem voraus. Unterordnerberechtigungen der Freigabe gelten weiterhin.</p></div>")
        body+=_ui_html("<div class='card'><h2>Wiederherstellen</h2><p>Vom Live-USB das Paket starten, SMB verbinden, Sicherungsstand prüfen und in einen neuen lokalen Linux-Ordner wiederherstellen. Die Anleitung liegt im Paket. Für einen vollständigen Systemumzug ist zusätzlich das angepasste V20-Werkzeug enthalten; dessen interaktive Schritte bleiben erforderlich.</p><p>Das Werkzeug meldet während Backup und Restore alle 30 Sekunden Aktivität über SMB. Diese blockiert geplantes Einschlafen; nach Verbindungsverlust läuft der Schutz nach drei Minuten aus. Server und Client müssen auf dieselbe Backupablage zeigen.</p></div>")
        body+=_ui_html("<div class='card'><h2>Gespeicherte Sicherungsstände</h2><p>Bis zu 200 Stände. Unvollständige Übertragungen werden nicht angeboten.</p><table><tr><th>Rechner / Benutzer</th><th>Umfang</th><th>Datum</th><th>Download</th></tr>")
        for item in central.inventory():
            body+=_ui_html('<tr><td>')+E(item['client'])+' / '+E(item['user'])+_ui_html('</td><td>')+E(item['kind'])+_ui_html('</td><td>')+E(item['created'])+_ui_html("</td><td><a href='/backup/archive?")+E(urlencode({'path':item['path']}))+_ui_html("'>Archiv</a> · <a href='/backup/archive?")+E(urlencode({'path':item['path'].rsplit('/',1)[0]+'/manifest.json'}))+_ui_html("'>Prüfsumme / Metadaten</a></td></tr>")
        body+=_ui_html('</table></div>')
        return ctx.page(_ui_text('Backup & Recovery'),body,'Daten'),code
    @app.route('/backup/client-tool',methods=['POST'])
    def client_tool():
        try:
            client=request.form.get('client','');user=request.form.get('user','');share=request.form.get('share','')
            stream=central.bundle(client,user,share)
            central.provision(client,user)
            return send_file(stream,download_name='Server-Backup.zip',as_attachment=True,mimetype='application/zip')
        except (ValueError,OSError) as e:return ctx.page(_ui_text('Backup'), _ui_html('<p>')+E(e)+_ui_html('</p>')),400

    @app.route('/backup/archive')
    def archive_download():
        from modules.downloads.files import track
        stream=None;finish=None
        try:
            value=request.args.get('path','');fd,info=central.archive_fd(value);stream=os.fdopen(fd,'rb');finish=track()
            response=send_file(stream,as_attachment=True,download_name=value.split('/')[-1],conditional=False,mimetype='application/octet-stream')
            response.content_length=info.st_size;response.direct_passthrough=False
            def close():
                try:stream.close()
                finally:finish()
            response.call_on_close(close)
            return response
        except (OSError,ValueError) as e:
            if stream:stream.close()
            if finish:finish()
            return ctx.page(_ui_text('Backup'),_ui_html('<p>Archiv nicht verfügbar: ')+E(e)+_ui_html('</p>')),404
