"""Administrator approval of OS users; personal non-admin landing page."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html
from flask import request,session,g,redirect
from . import policy,system
from .store import ROLES
E=lambda v:html.escape(str(v),quote=True)
def register(app,users,accounts,shell,csrf_input,valid_csrf,reauth):
    def link(url,label):return _ui_html("<a href='")+E(url)+"'>"+E(_ui_text(label))+_ui_html("</a>")
    @app.route('/settings/users',methods=['GET','POST'],endpoint='auth_users')
    def manage():
        message='';status=200
        if request.method=='POST':
            if not valid_csrf():return shell('Manager-Benutzer','Formular abgelaufen.'),403
            if not reauth(request.form.get('current_password','')):return shell('Manager-Benutzer','Aktuelles Administratorpasswort nicht bestätigt.'),403
            try:
                users.change(request.form.get('username',''),request.form.get('role',''),request.form.getlist('modules'),request.form.get('enabled')=='yes',request.form.get('revision',''),accounts.read()['username'],request.form.get('action')=='remove')
                message='Manager-Rechte gespeichert. Bisherige Sitzungen dieses Kontos sind abgemeldet. Das Linux-Konto und seine Dateirechte wurden nicht geändert.'
            except (ValueError,OSError) as exc:message=str(exc);status=400
        try:data=users.read();candidates=system.candidates()
        except (ValueError,OSError):return shell('Manager-Benutzer','Benutzerkonfiguration nicht lesbar. Über den Notfallzugang und Server-Terminal prüfen.'),503
        reserved=accounts.read()['username'];by_name={x['name']:x for x in candidates if x['name']!=reserved}
        body=_ui_html("<p>")+link('/','Übersicht')+' · '+link('/settings/access','Eigener Zugang')+_ui_html("</p><p>Lokale Debian-/Mint-Konten gezielt für diesen Manager freischalten. Anmeldung mit Linux-Passwort über PAM; keine Passwortkopie. Linux-Gruppen und sudo verleihen keine Manager-Rechte.</p><p><b>Notfallzugang:</b> ")+E(reserved)+_ui_html(" bleibt unabhängig erhalten. Root- und Dienstkonten werden nicht angeboten.</p>")
        body+=_ui_html('<p>PAM: ')+(_ui_text('Bereit') if system.ready() else _ui_text('Nicht eingerichtet – Paketinstallation/Serverdienst prüfen. Systemanmeldung bleibt gesperrt.'))+_ui_html('</p>')
        body+=_ui_html('<p>Benutzer erhalten nur ausgewählte Ansichten und beschriebene Aktionen. „Nur Lesen“ kann keine Änderungen ausführen. Installationen, Server-Backups, Freigaben-/Systemverwaltung, Zugangsdaten und fremde Client-Profile bleiben Administratoren vorbehalten.</p>')
        body+=_ui_html('<p>Client-Agenten behalten ihre eigenen Tokens und Sicherungsrechte. Diese separat unter Client-Agenten sperren; eine Manager-Kontosperre widerruft keine bereits ausgegebenen Agenten-Tokens.</p>')
        if message:body+=_ui_html('<p role="status">')+E(_ui_text(message))+_ui_html('</p>')
        for name in sorted(set(by_name)|set(data['users'])):
            row=data['users'].get(name,{});candidate=by_name.get(name)
            body+=_ui_html("<details><summary><b>")+E(name)+_ui_html("</b> · ")+E(ROLES.get(row.get('role'),_ui_text('Noch nicht freigegeben')))+' · '+(_ui_text('Aktiv') if row.get('enabled') else _ui_text('Kein Manager-Zugang'))+_ui_html('</summary>')
            body+=_ui_html('<p>UID: ')+E(candidate['uid'] if candidate else row.get('uid','?'))+(' · '+E(_ui_text(candidate['label'])) if candidate else _ui_text(' · Linux-Konto nicht mehr verfügbar'))+_ui_html('</p>')
            if candidate:
                from urllib.parse import quote
                body+='<p>'+link('/freigaben/users/edit?user='+quote(name,safe=''),'Linux-Gruppen und Passwörter bearbeiten')+'</p>'
            if row and candidate and row['uid']!=candidate['uid']:body+=_ui_html('<p>UID geändert: Anmeldung ist gesperrt. Erneutes Speichern ordnet ausdrücklich das aktuelle Konto zu.</p>')
            body+=_ui_html("<form method='post'>")+csrf_input()+_ui_html("<input type='hidden' name='revision' value='")+E(data['revision'])+_ui_html("'><input type='hidden' name='username' value='")+E(name)+"'>"
            if candidate:
                body+=_ui_html("<label><input style='width:auto' type='checkbox' name='enabled' value='yes' ")+('checked' if row.get('enabled') else '')+_ui_html("> Zugang freigeben</label><label>Rolle <select name='role'>")
                for key,label in ROLES.items():body+=_ui_html("<option value='")+key+"' "+('selected' if row.get('role','user')==key else '')+'>'+_ui_text(label)+_ui_html('</option>')
                body+=_ui_html('</select></label><p>Administratoren haben vollständigen Zugriff. Für Benutzer und Nur-Lesen-Konten folgende Bereiche wählen:</p>')
                for key,(label,url,note) in policy.SCOPES.items():
                    body+=_ui_html("<p><label><input style='width:auto' type='checkbox' name='modules' value='")+key+"' "+('checked' if key in row.get('modules',[]) else '')+"> "+E(_ui_text(label))+_ui_html("</label><br><small>")+E(_ui_text(note))+_ui_html('</small></p>')
            body+=_ui_html("<label>Dein aktuelles Administratorpasswort<input type='password' name='current_password' autocomplete='current-password' required maxlength='256'></label>")
            if candidate:body+=_ui_html("<button name='action' value='save'>Rechte speichern</button> ")
            if row:body+=_ui_html("<button name='action' value='remove'>Nur Manager-Zugang entfernen</button>")
            body+=_ui_html('</form></details><hr>')
        if not by_name and not data['users']:body+=_ui_html('<p>Keine lokalen interaktiven Benutzer gefunden (UID 1000 bis UID_MAX, höchstens 60000, mit Login-Shell).</p>')
        return shell('Manager-Benutzer',body),status

    @app.route('/account',endpoint='auth_account')
    def personal():
        p=g.auth_principal
        body=_ui_html('<p>Angemeldet als <b>')+E(p['name'])+_ui_html('</b> · ')+E(ROLES[p['role']])+_ui_html('</p><p>')+link('/settings/access','Mein Zugang')+_ui_html('</p>')
        if p['role']=='admin':body+=_ui_html('<p>')+link('/','Gesamte Verwaltung')+' · '+link('/settings/users','Manager-Benutzer')+_ui_html('</p>')
        else:
            body+=_ui_html('<h2>Freigegebene Bereiche</h2>')
            for key in p.get('modules',[]):
                label,url,note=policy.SCOPES[key];body+=_ui_html('<p>')+link(url,label)+_ui_html('<br><small>')+E(_ui_text(note))+_ui_html('</small></p>')
            if not p.get('modules'):body+=_ui_html('<p>Noch keine Bereiche freigegeben. Bitte den Manager-Administrator kontaktieren.</p>')
        body+=_ui_html("<form action='/logout' method='post'>")+csrf_input()+_ui_html("<button>Abmelden</button></form>")
        return shell('Mein Heimserver',body)

    @app.route('/account/client',endpoint='auth_client_tools')
    def client_tools():
        body=_ui_html('<p>')+link('/account','Mein Bereich')+_ui_html('</p><p>Client ab Version 0.3.4: „Am Manager anmelden / eigene Sicherungen“ wählen und mit dem freigegebenen Linux-Konto anmelden. Eigene Konto-Sicherungen sind von bisherigen Agenten-Sicherungen getrennt. Nur Lesen erlaubt Rücksicherung; Benutzer dürfen zusätzlich sichern. Server-Sicherungen benötigen eine Administratoranmeldung. Das JSON-Profil richtet weiterhin Serveradresse, HTTPS und Agentenfunktionen ein.</p>')
        for url,label in [('/clients/desktop/download','Linux-Client (DEB)'),('/clients/windows/download','Windows-Client (EXE)'),('/clients/recovery/download','Live-USB-Werkzeuge')]:body+=_ui_html('<p>')+link(url,label)+_ui_html('</p>')
        return shell('Eigene Client-Sicherungen',body)

    @app.route('/account/server',endpoint='auth_server_readonly')
    def server_readonly():
        from modules.server import helper
        body=_ui_html('<p>')+link('/account','Mein Bereich')+_ui_html('</p><table><tr><th>Dienst</th><th>Status</th><th>Autostart</th></tr>')
        for row in helper.service_rows():body+=_ui_html('<tr><td>')+E(row.get('unit',''))+_ui_html('</td><td>')+E(row.get('active',row.get('active_state',_ui_text(row.get('state','')))) )+_ui_html('</td><td>')+E(row.get('enabled',''))+_ui_html('</td></tr>')
        return shell('Serverstatus',body+_ui_html('</table><p>Dienstaktionen, Protokolle und Konfigurationen sind nur für Administratoren sichtbar.</p>'))
