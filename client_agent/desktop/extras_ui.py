"""Desktop dialogs for own backups and explicit TLS enrolment."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,webbrowser
from pathlib import Path
from gi.repository import Gtk,GLib
import core,backup,connection

def folder(parent,title):
    d=Gtk.FileChooserDialog(title=title,parent=parent,action=Gtk.FileChooserAction.SELECT_FOLDER)
    d.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Auswählen'),Gtk.ResponseType.OK)
    value=d.get_filename() if d.run()==Gtk.ResponseType.OK else None;d.destroy();return value

def confirm(app,text):
    d=Gtk.MessageDialog(transient_for=app.window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=text)
    yes=d.run()==Gtk.ResponseType.OK;d.destroy();return yes

def manager_login(app):
    if app.busy:app.message(tr('Zuerst die laufende Aktion abschließen.'));return
    d=Gtk.Dialog(title=tr('Am Manager anmelden'),transient_for=app.window,modal=True)
    d.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Anmelden'),Gtk.ResponseType.OK)
    box=d.get_content_area();box.set_spacing(8)
    box.add(Gtk.Label(label=tr('Freigegebenes Linux-Konto verwenden. Passwort wird nicht gespeichert. Eigene Konto-Sicherungen sind getrennt von bisherigen Agenten-Sicherungen.'),wrap=True))
    user=Gtk.Entry();user.set_placeholder_text(tr('Benutzername'));box.add(user)
    password=Gtk.Entry();password.set_visibility(False);password.set_placeholder_text(tr('Linux-Passwort'));box.add(password)
    d.show_all();ok=d.run()==Gtk.ResponseType.OK
    username=user.get_text();secret=password.get_text();password.set_text('');d.destroy()
    if ok:
        def run():
            access=backup.account_login(username,secret)
            GLib.idle_add(lambda: (backups(app),False)[1])
            return tr('Angemeldet: ')+access['username']+' · '+(tr('Sichern und Wiederherstellen') if access['backup'] else tr('Nur Wiederherstellen'))
        app.run_action(run)


def pair_device(app):
    if not confirm(app,tr('Eigenes Agentenprofil für dieses Manager-Konto, Gerät und diese lokale Anmeldung erstellen? Bisherige gemeinsame Profile bleiben bestehen.')):return
    def run():
        import device_identity
        result=device_identity.pair()
        GLib.idle_add(lambda: (app.fill(core.load()),False)[1])
        return result
    app.run_action(run)

def backups(app):
    d=Gtk.Dialog(title=tr('Eigene Client-Sicherungen'),transient_for=app.window);d.set_default_size(650,400);d.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE)
    box=d.get_content_area();box.set_spacing(10)
    note=Gtk.Label(label=tr('Dateibackup ausgewählter Benutzerordner. Kein vollständiges Systemabbild. Links, eingebundene Dateisysteme und Spezialdateien werden nicht gesichert. Rücksicherung immer in einen neuen Ordner. Konto-Anmeldung: eigene Benutzerablage. Ohne Konto-Anmeldung: bisheriges Agenten-Profil.'),wrap=True);box.add(note)
    box.add(Gtk.Label(label=(tr('Manager-Konto: ')+backup.ACCOUNT[2]['username']) if backup.ACCOUNT else tr('Bisheriges Agenten-Profil (Token)'),wrap=True))
    scope=Gtk.ComboBoxText()
    scope.append('folder',tr('Ausgewählten Ordner sichern'));scope.append('home',tr('Eigenes Home einschließlich versteckter Einstellungen sichern'));scope.set_active(0);box.add(scope)
    destination=Gtk.ComboBoxText();destination.append('server',tr('Direkt auf den Server'));destination.append('usb',tr('Direkt auf USB-Festplatte'));destination.set_active(0);box.add(destination)
    choice=Gtk.ComboBoxText();box.add(choice);items={}
    box.add(Gtk.Label(label=tr('Rücksicherung: leer = gesamter Stand, sonst relativer Dateipfad oder Ordner aus der Sicherung.'),wrap=True))
    selected=Gtk.Entry();selected.set_placeholder_text(tr('z. B. Dokumente/Brief.odt oder Dokumente'));box.add(selected)
    status=Gtk.Label(label=tr('Sicherungsstände laden …'),wrap=True);box.add(status)
    def progress(text):
        def update():
            if status.get_realized():status.set_text(text)
            return False
        GLib.idle_add(update)
    def refresh():
        def load():
            data=backup.call('list')['backups']
            def done():
                choice.remove_all();items.clear()
                for row in data:items[row['id']]=row;choice.append(row['id'],row['created']+' · '+row['name']+' · '+str(row['bytes']//1024**2)+' MiB')
                if data:choice.set_active(0)
                status.set_text(str(len(data))+tr(' eigene Sicherungsstände'))
            GLib.idle_add(done);return tr('Client-Sicherungen geladen.')
        app.run_action(load)
    def logout():
        if app.busy:app.message(tr('Zuerst die laufende Aktion abschließen.'));return
        backup.account_logout();d.response(Gtk.ResponseType.CLOSE)
    def create():
        src=str(Path.home()) if scope.get_active_id()=='home' else folder(d,tr('Benutzerordner sichern'))
        dest=folder(d,tr('Zielordner auf eingehängter USB-Festplatte')) if src and destination.get_active_id()=='usb' else None
        if destination.get_active_id()=='usb' and not dest:return
        if src and confirm(app,tr('Diesen Ordner sichern: ')+str(src)+tr('\nZiel: ')+(str(dest) if dest else 'Server')+tr('\nOffene Programme vorher schließen. Es wird kein lokales Zwischenarchiv erstellt. Bei HTTP ist die Übertragung unverschlüsselt.')):
            app.run_action(lambda:backup.create(src,progress,destination=dest))
    def restore(local=False):
        item=items.get(choice.get_active_id())
        if local:
            picker=Gtk.FileChooserDialog(title=tr('ZIP-Sicherung auf USB auswählen'),parent=d,action=Gtk.FileChooserAction.OPEN)
            picker.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Öffnen'),Gtk.ResponseType.OK)
            path=picker.get_filename() if picker.run()==Gtk.ResponseType.OK else None;picker.destroy()
            if not path:return
            try:item=backup.local_item(path)
            except Exception as exc:app.message(str(exc),True);return
        if not item:app.message(tr('Zuerst einen Sicherungsstand auswählen.'));return
        parent=folder(d,tr('Übergeordneten Zielordner auswählen'))
        if not parent:return
        target=Path(parent)/('Wiederherstellung-'+item['id'][:12])
        selection=selected.get_text()
        if confirm(app,tr('In neuen Ordner wiederherstellen: ')+str(target)+'?'):
            app.run_action(lambda:backup.restore(item,target,progress,selected=selection))
    for label,fn in [(tr('Am Manager anmelden'),lambda:manager_login(app)),(tr('Manager abmelden'),logout),(tr('Benutzer & Gerät koppeln'),lambda:pair_device(app)),(tr('Sicherung starten'),create),(tr('System sichern & wiederherstellen (Linux)'),lambda:system_recovery(app)),(tr('Sicherungsstände aktualisieren'),refresh),(tr('Server-Stand wiederherstellen'),restore),(tr('USB-Stand wiederherstellen'),lambda:restore(True)),(tr('Unvollständige Übertragung verwerfen'),lambda: app.run_action(lambda: str(backup.call('cancel',{}))) if confirm(app,tr('Nur die unvollständige Übertragung dieses Clients verwerfen?')) else None)]:
        b=Gtk.Button(label=label);b.connect('clicked',lambda _,f=fn:f());box.add(b)
    d.show_all();status.set_text(tr("Server-Stände bei Bedarf aktualisieren; USB-Sicherung funktioniert auch ohne Serververbindung."));d.run();d.destroy()

def https(app):
    data=connection.load()
    if not data:app.message(tr('Zuerst privates HTTPS im Manager einrichten und ein neues JSON-Client-Profil importieren. Dieses enthält das öffentliche Stammzertifikat und den Fingerabdruck.'));return
    d=Gtk.Dialog(title=tr('Privates HTTPS einrichten'),transient_for=app.window);d.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE);d.set_default_size(650,360)
    box=d.get_content_area();box.set_spacing(10)
    box.add(Gtk.Label(label=tr('Hostname: ')+data['hostname']+'\nSHA-256: '+data['sha256']+tr('\nFingerabdruck mit Einstellungen → HTTPS-Zugang im Manager vergleichen. Import erteilt diesem Stammzertifikat Vertrauen.'),wrap=True,selectable=True))
    box.add(Gtk.Label(label=tr('Optional feste Server-IP für hosts. Leer lassen, wenn der Router den Namen bereits auflöst.'),wrap=True))
    ip=Gtk.Entry();ip.set_text(data.get('ip',''));box.add(ip)
    def apply(action):
        values=dict(data,ip=ip.get_text().strip())
        if confirm(app,(tr('Stammzertifikat vertrauen und optional Namenseintrag anlegen? Fingerabdruck geprüft?') if action=='install' else tr('Dieses vom Assistenten hinterlegte Zertifikat und den markierten Namenseintrag entfernen?'))):
            app.run_action(lambda:connection.apply(values,action))
    def test():
        def run():
            url=connection.test(data)
            def offer():
                if confirm(app,tr('HTTPS erfolgreich geprüft. Manager-Adresse auf ')+url+tr(' umstellen?')):
                    cfg=core.load();cfg['SERVER_URL']=url;core.save(cfg);app.fill(cfg)
            GLib.idle_add(offer);return tr('HTTPS mit gültigem Zertifikat erreichbar.')
        app.run_action(run)
    for label,fn in [(tr('Einrichten (Administratorfreigabe)'),lambda:apply('install')),(tr('Verbindung prüfen / HTTPS übernehmen'),test),(tr('Eigene Einrichtung entfernen'),lambda:apply('remove'))]:
        b=Gtk.Button(label=label);b.connect('clicked',lambda _,f=fn:f());box.add(b)
    d.show_all();d.run();d.destroy()

def server(app):
    if confirm(app,tr('Server-Sicherungen sind ausschließlich für den Manager-Administrator. Die geschützte Backup-Oberfläche wird im Browser geöffnet; dort mit dem Manager-Konto anmelden. Der Client speichert kein Administratorpasswort.')):
        cfg=core.validate(core.load());webbrowser.open(cfg['SERVER_URL']+'/login?reauth=1&next=/backup')


def system_recovery(app):
    from system_recovery_ui import open_dialog
    open_dialog(app)
