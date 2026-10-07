"""Admin-only local account editor, with separate Linux and SMB credentials."""
import html
from urllib.parse import quote
from flask import request,abort
from ui_translation import text
from modules.accounts.policy import is_admin
from . import user_admin as service
E=lambda value:html.escape(str(value),quote=True)
T=lambda value:E(text(value))
def register(app,ctx,page):
    @app.route('/freigaben/users/edit',methods=['GET','POST'])
    def shares_user_edit():
        if not is_admin():abort(403)
        name=request.form.get('username','') if request.method=='POST' else request.args.get('user','')
        try:user=service.inspect(name)
        except (ValueError,OSError,KeyError):return page(ctx,'Benutzer bearbeiten','<p>'+T('Lokaler Benutzer nicht verfügbar. Root- und Dienstkonten können hier nicht bearbeitet werden.')+'</p>'),400
        message='';status=200
        if request.method=='POST':
            reauth=app.extensions.get('server_manager_admin_reauth')
            if not reauth or not reauth(request.form.get('current_password','')):
                message='Aktuelles Administratorpasswort nicht bestätigt.';status=403
            else:
                try:
                    message=service.apply(name,request.form.get('revision',''),request.form.get('action',''),request.form.get('group',''),request.form.get('new_password',''),request.form.get('confirm_password',''),request.form.get('privileged')=='yes',selected_groups=request.form.getlist('groups'))
                except (ValueError,OSError,KeyError) as exc:
                    message=str(exc) if isinstance(exc,ValueError) else 'Änderung nicht bestätigt. Benutzer neu laden und am Server prüfen.';status=400
                try:user=service.inspect(name)
                except (ValueError,OSError,KeyError):return page(ctx,'Benutzer bearbeiten','<p>'+T('Änderung nicht bestätigt. Benutzer neu laden und am Server prüfen.')+'</p>'),400
        groups=service.local_groups()
        body='<style>.user-admin-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:24px}.user-admin-grid form{min-width:0}.user-admin-grid label{display:block;margin:8px 0}.user-admin-grid input:not([type=checkbox]),.user-admin-grid select{width:100%;box-sizing:border-box}.user-admin-grid input[type=checkbox]{width:auto}</style><div class="card"><h2>'+T('Benutzer bearbeiten')+': '+E(name)+'</h2><p><a class="btn" href="/freigaben/users">'+T('Zur Benutzerübersicht')+'</a> <a class="btn" href="/settings/users">'+T('Manager-Zugriff verwalten')+'</a></p>'
        if message:body+='<p role="status">'+T(message)+'</p>'
        body+='<dl>'
        for label,value in [('Name',user['label']),('UID / GID',str(user['uid'])+' / '+str(user['gid'])),('Home',user['home']),('Shell',user['shell']),('Primäre Gruppe',user['primary']),('Zusätzliche Gruppen',', '.join(user['groups']) or '—')]:body+='<dt>'+T(label)+'</dt><dd>'+E(value)+'</dd>'
        body+='</dl><p>'+T('Linux-Gruppen und Manager-Rollen sind unabhängig. sudo erlaubt Systemverwaltung am Rechner, erteilt aber keinen Manager-Zugang. UID, Home, Shell und primäre Gruppe werden hier nicht verändert.')+'</p></div>'
        def form(action):
            return '<form method="post"><input type="hidden" name="action" value="'+action+'"><input type="hidden" name="username" value="'+E(name)+'"><input type="hidden" name="revision" value="'+E(user['revision'])+'">'
        def auth():
            return '<label>'+T('Dein aktuelles Administratorpasswort')+'<input type="password" name="current_password" autocomplete="current-password" required maxlength="256"></label>'
        body+='<div class="card"><h3>'+T('Gruppen gezielt ändern')+'</h3><p>'+T('Haken setzen zum Hinzufügen, Haken entfernen zum Austreten. Änderungen werden erst mit „Gruppen speichern“ übernommen. Die primäre Gruppe bleibt erhalten. Neue Rechte gelten nach erneuter Anmeldung.')+'</p>'
        body+=form('set_groups')+'<div class="user-admin-grid">'
        body+='<label><input type="checkbox" checked disabled> '+E(user['primary'])+' · '+T('Primäre Gruppe')+'</label>'
        for group in groups:
            name_group=group['name']
            if name_group==user['primary']:continue
            body+='<label><input type="checkbox" name="groups" value="'+E(name_group)+'"'+(' checked' if name_group in user['groups'] else '')+'> '+E(name_group)+(' · '+T('Erweiterte Systemrechte') if name_group in service.PRIVILEGED else '')+'</label>'
        body+='</div><p><label><input type="checkbox" name="privileged" value="yes"> '+T('Bei einer Gruppe mit erweiterten Systemrechten: Ich bestätige ausdrücklich das Hinzufügen oder Entfernen dieser Rechte.')+'</label></p>'+auth()+'<button class="btn">'+T('Gruppen speichern')+'</button></form>'
        body+='</div><div class="card"><h3>'+T('Passwörter getrennt ändern')+'</h3><p>'+T('Der Manager protokolliert das neue Passwort nicht und speichert es nicht im Klartext. Linux-Passwort: Anmeldung am Rechner und für freigeschaltete Manager-Konten; ein gesperrtes Linux-Passwort kann dadurch wieder nutzbar werden. SMB-Passwort: nur Dateifreigaben, aktiviert bei Bedarf den Samba-Zugang. NFS verwendet UID/GID, kein eigenes NFS-Passwort.')+'</p>'
        body+='<div class="user-admin-grid">'
        for action,label in [('linux_password','Linux-Passwort ändern'),('smb_password','SMB-Passwort setzen / Zugang aktivieren')]:
            body+='<details><summary>'+T(label)+'</summary>'+form(action)
            for field,caption in [('new_password','Neues Passwort'),('confirm_password','Neues Passwort wiederholen')]:body+='<label>'+T(caption)+'<input type="password" name="'+field+'" autocomplete="new-password" required minlength="8" maxlength="256"></label>'
            body+=auth()+'<button class="btn">'+T(label)+'</button></form></details>'
        return page(ctx,'Benutzer bearbeiten',body+'</div></div>'),status
