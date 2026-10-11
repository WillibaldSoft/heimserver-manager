"""Separate, explicit administrator-approved local UID/GID conversion."""
import json,subprocess,urllib.request,urllib.error
from gi.repository import Gtk,GLib
from client_i18n import tr
import backup,core,user_ids
HELPER='/usr/lib/heimserver-manager-client/user_ids.py'

def elevated(action,uid=0,gid=0):
    result=subprocess.run(['/usr/bin/pkexec','/usr/bin/python3',HELPER,action,str(uid),str(gid)],capture_output=True,text=True)
    if result.returncode:raise core.Error(result.stderr.strip() or tr('Administratoraktion abgebrochen.'))
    return result.stdout

def login(app):
    import extras_ui
    extras_ui.manager_login(app,on_success=lambda:check(app))

def show(app):
    if app.busy:app.message(tr('Zuerst die laufende Aktion abschließen.'));return
    d=Gtk.Dialog(title=tr('UID/GID verwalten'),transient_for=app.window,modal=True)
    d.add_button(tr('Schließen'),Gtk.ResponseType.CANCEL)
    box=d.get_content_area();box.set_border_width(12);box.set_spacing(10)
    account=backup.ACCOUNT[2]['username'] if backup.ACCOUNT else tr('Nicht angemeldet')
    box.add(Gtk.Label(label=tr('Manager-Konto: ')+account,xalign=0))
    note=Gtk.Label(label=tr('Für den Vergleich mit dem Server mit dem eigenen Linux-Benutzer anmelden. Eine vorgemerkte lokale Umstellung lässt sich unabhängig von der Manager-Anmeldung abbrechen.'),wrap=True,xalign=0);note.set_max_width_chars(70);box.add(note)
    for label,response in [(tr('Am Manager anmelden'),1),(tr('UID/GID überprüfen'),2),(tr('Vorgemerkte Umstellung abbrechen'),3)]:
        button=Gtk.Button(label=label);button.connect('clicked',lambda _,r=response:d.response(r));box.add(button)
    d.show_all();response=d.run();d.destroy()
    if response==1:login(app)
    elif response==2:check(app)
    elif response==3:cancel(app)

def check(app):
    if app.busy:app.message(tr('Zuerst die laufende Aktion abschließen.'));return
    if not backup.ACCOUNT:login(app);return
    result={}
    def load():
        url,opener,_=backup.ACCOUNT
        if url!=core.validate(core.load())['SERVER_URL'] or not url.startswith('https://'):
            backup.account_logout();result['login']=True;return tr('Server geändert. Erneut am Manager anmelden.')
        try:
            with opener.open(url+'/api/account/access',timeout=30) as response:access=json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code!=401:raise
            backup.account_logout();result['login']=True;return tr('Anmeldung abgelaufen. Erneut am Manager anmelden.')
        identity=access.get('system_identity')
        if not identity:raise core.Error(tr('Dieses Manager-Konto hat keine übernehmbare Linux-UID/GID.'))
        result.update(identity=identity,plan=user_ids.compare(identity))
        return tr('UID/GID geprüft. Noch nichts geändert.')
    app.run_action(load,on_success=lambda:login(app) if result.get('login') else comparison(app,result['identity'],result['plan']))

def comparison(app,identity,plan):
    d=Gtk.Dialog(title=tr('UID/GID überprüfen'),transient_for=app.window,modal=True)
    d.add_button(tr('Schließen'),Gtk.ResponseType.CANCEL)
    d.add_button(tr('Am Manager anmelden'),1)
    d.add_button(tr('Vorgemerkte Umstellung abbrechen'),3)
    if not plan['matches']:d.add_button(tr('Übernahme prüfen …'),Gtk.ResponseType.OK)
    box=d.get_content_area();box.set_spacing(10);box.set_border_width(12)
    text=(tr('Lokaler Benutzer: ')+plan['name']+'\n'
          +tr('Serverkonto: ')+identity['username']+'\n\n'
          +'UID: '+str(plan['old_uid'])+' → '+str(plan['uid'])+'\n'
          +'GID: '+str(plan['old_gid'])+' → '+str(plan['gid'])+'\n\n'
          +(tr('UID und primäre GID stimmen bereits mit dem Server überein.') if plan['matches'] else
            tr('UID/GID weichen ab. Du kannst die Übernahme prüfen lassen. Erst dafür ist eine Administratorfreigabe erforderlich; die Umstellung wird anschließend gesondert bestätigt.')))
    label=Gtk.Label(label=text,xalign=0,wrap=True);label.set_max_width_chars(75);box.add(label)
    d.show_all();response=d.run();d.destroy()
    if response==1:login(app);return False
    if response==3:cancel(app);return False
    if response==Gtk.ResponseType.OK and not plan['matches']:
        def preview():
            checked=json.loads(elevated('preview',identity['uid'],identity['gid']))
            if checked['old_uid']==checked['uid'] and checked['old_gid']==checked['gid']:
                return tr('UID und primäre GID stimmen bereits mit dem Server überein.')
            GLib.idle_add(review,app,identity,checked)
            return tr('UID/GID-Vorschau geladen. Noch nichts geändert.')
        app.run_action(preview)
    return False

def review(app,identity,plan):
    d=Gtk.Dialog(title=tr('Server-UID und Gruppen-ID übernehmen'),transient_for=app.window,modal=True)
    d.add_buttons(tr('Schließen'),Gtk.ResponseType.CANCEL,tr('Für nächsten Neustart vormerken'),Gtk.ResponseType.OK)
    box=d.get_content_area();box.set_spacing(10);box.set_border_width(12)
    text=(tr('Serverkonto: ')+identity['username']+'\n'+tr('Lokaler Benutzer bleibt: ')+plan['name']+'\n'
          +'UID: '+str(plan['old_uid'])+' → '+str(plan['uid'])+'\nGID: '+str(plan['old_gid'])+' → '+str(plan['gid'])+'\n'
          +tr('Lokale Dateisysteme: ')+', '.join(v['path'] for v in plan['volumes'])+'\n\n'
          +tr('Die Umstellung erfolgt beim nächsten Neustart vor der Anmeldung. Dateieigentümer und numerische ACLs werden angepasst; Name, Passwort und Client-Kopplung bleiben erhalten. Netzwerkfreigaben werden nicht verändert. Alle genannten Datenträger müssen beim Start eingehängt sein. Der Start kann länger dauern. Bei Fehlern bleibt die normale Anmeldung gesperrt, bis die Ursache im Rettungsmodus behoben ist. Vorher eine geprüfte Sicherung bereithalten.'))
    label=Gtk.Label(label=text,xalign=0,wrap=True);label.set_max_width_chars(80);box.add(label)
    consent=Gtk.CheckButton(label=tr('Ich habe eine aktuelle Sicherung und möchte UID und primäre GID umstellen.'));box.add(consent)
    d.set_response_sensitive(Gtk.ResponseType.OK,False)
    consent.connect('toggled',lambda b:d.set_response_sensitive(Gtk.ResponseType.OK,b.get_active()))
    d.show_all();accepted=d.run()==Gtk.ResponseType.OK;d.destroy()
    if accepted:
        def schedule():
            elevated('schedule',identity['uid'],identity['gid'])
            return tr('UID/GID-Umstellung vorgemerkt. Beim nächsten Neustart ausführen; bis dahin sind die bisherigen IDs aktiv.')
        app.run_action(schedule)
    return False

def cancel(app):
    import extras_ui
    if not extras_ui.confirm(app,tr('Die für den nächsten Neustart vorgemerkte UID/GID-Umstellung abbrechen? Bereits begonnene Änderungen werden nicht zurückgesetzt.')):return
    app.run_action(lambda:(elevated('cancel'),tr('Vorgemerkte UID/GID-Umstellung abgebrochen.'))[1])
