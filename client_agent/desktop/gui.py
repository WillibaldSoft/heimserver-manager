#!/usr/bin/python3
"""GTK desktop and notification-area UI for the existing user-session agent."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import os,sys,threading
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gio,GLib
try:
    gi.require_version('AyatanaAppIndicator3','0.1')
    from gi.repository import AyatanaAppIndicator3 as Indicator
except (ImportError,ValueError):Indicator=None
import core
try:
    from client_version import VERSION
except ImportError:
    VERSION=tr('Entwicklungsstand')
import extras_ui,connection

LABELS={'SERVER_URL':tr('Manager-Adresse (http:// oder https://)'),'TOKEN':tr('Agenten-Token'),'CLIENT_NAME':tr('Client-Name'),'CLIENT_MAC':tr('Client-MAC (optional)'),'IPMI_RECOVER_URL':tr('Recovery-Adresse (optional)'),'SERVER_MAC':tr('Server-MAC für Wake-on-LAN'),'WAKE_TIMEOUT':tr('Recovery-Timeout (1–300 Sekunden)')}
MODES={'without_server':tr('Ohne Server starten'),'with_server':tr('Mit Server starten / Server benötigt'),'wake_on_access':tr('Nur auf ausdrücklichen Aufruf wecken')}
WAKE={'none':tr('Nicht wecken'),'wol':tr('Wake-on-LAN'),'recover':tr('Recovery-Dienst'),'both':tr('Recovery und Wake-on-LAN')}
class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.heimservermanager.Client',flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window=None;self.entries={};self.busy=False;self.polling=False;self.indicator=None;self.connecting=False;self.connected=False
    def do_startup(self):
        Gtk.Application.do_startup(self);self.hold()
        self.make_window();self.make_tray();GLib.timeout_add_seconds(15,self.refresh);self.refresh()
    def do_command_line(self,command):
        args=command.get_arguments()
        if '--autostart' in args and not core.CONFIG.exists():self.quit();return 0
        if '--background' not in args or not core.CONFIG.exists() or self.indicator is None:self.window.show_all();self.window.present()
        return 0
    def do_activate(self):self.window.show_all();self.window.present()
    def message(self,text,error=False):
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO,buttons=Gtk.ButtonsType.OK,text=text)
        dialog.run();dialog.destroy()
    def make_window(self):
        self.window=Gtk.ApplicationWindow(application=self,title=tr('Heimserver Manager Client · ')+VERSION);self.window.set_default_size(680,700)
        self.window.connect('delete-event',self.close_window)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin=16);self.window.add(outer)
        outer.pack_start(Gtk.Label(label=tr('Heimserver Manager Client · Version ')+VERSION,xalign=0),False,False,0)
        self.state=Gtk.Label(label=tr('Status wird geprüft …'),xalign=0);self.state.set_line_wrap(True);outer.pack_start(self.state,False,False,0)
        self.notice=Gtk.Label(label=tr('Dienst arbeitet nach Aktivierung in deiner Benutzersitzung. Fenster schließen beendet den Agenten nicht.'),xalign=0);self.notice.set_line_wrap(True);outer.pack_start(self.notice,False,False,0)
        actions=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,max_children_per_line=3);outer.pack_start(actions,False,False,0)
        for label,action in [(tr('Server wecken'),'wake'),(tr('Server benötigt'),'need'),(tr('Server freigeben'),'release'),(tr('Wecken und verbinden'),'connect'),(tr('Zugriff vorbereiten'),'access')]:
            button=Gtk.Button(label=label);button.connect('clicked',lambda _,a=action:self.run_action(lambda:core.action(a),connecting=True));actions.add(button)
        note=Gtk.Label(label=tr('„Zugriff vorbereiten“ weckt und wartet auf den Server. Wie im bisherigen Skript wird kein Dateizugriff automatisch überwacht. Einmalige Bedarf/Freigabe-Aktionen werden beim nächsten Heartbeat wieder vom gewählten Modus bestimmt.'),xalign=0);note.set_line_wrap(True);outer.pack_start(note,False,False,0)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);outer.pack_start(scroll,True,True,0)
        grid=Gtk.Grid(column_spacing=12,row_spacing=8);scroll.add(grid)
        for i,key in enumerate(core.KEYS):
            label=Gtk.Label(label=LABELS.get(key,tr('Betriebsmodus') if key=='CLIENT_MODE' else tr('Weckmethode')),xalign=0);grid.attach(label,0,i,1,1)
            if key in ('CLIENT_MODE','WAKE_METHOD'):
                field=Gtk.ComboBoxText()
                for value,text in (MODES if key=='CLIENT_MODE' else WAKE).items():field.append(value,text)
            else:
                field=Gtk.Entry();field.set_hexpand(True)
                if key in ('TOKEN','IPMI_RECOVER_URL'):field.set_visibility(False);field.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            self.entries[key]=field;grid.attach(field,1,i,1,1)
        row=len(core.KEYS)
        grid.attach(Gtk.Label(label=tr('Hostname dieses Rechners'),xalign=0),0,row,1,1)
        hostbox=Gtk.Box(spacing=6);self.hostname_entry=Gtk.Entry();self.hostname_entry.set_text(core.hostname());hostbox.pack_start(self.hostname_entry,True,True,0)
        change=Gtk.Button(label=tr('Ändern …'));change.connect('clicked',lambda _:self.change_hostname());hostbox.pack_start(change,False,False,0);grid.attach(hostbox,1,row,1,1)
        buttons=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,max_children_per_line=3);outer.pack_start(buttons,False,False,0)
        for label,callback in [(tr('Am Manager anmelden / eigene Sicherungen'),lambda:extras_ui.manager_login(self)),(tr('Eigene Backups / Wiederherstellung'),lambda:extras_ui.backups(self)),(tr('Privates HTTPS'),lambda:extras_ui.https(self)),(tr('Server-Backup (Administrator)'),lambda:extras_ui.server(self)),(tr('Speichern'),self.save),(tr('Profil importieren'),self.import_profile),(tr('Bestehende Einstellungen laden'),self.reload),(tr('Agent aktivieren / übernehmen'),self.enable),(tr('Agent deaktivieren'),self.disable),(tr('Protokoll'),self.show_logs),(tr('Aktualisieren'),lambda:self.refresh())]:
            btn=Gtk.Button(label=label);btn.connect('clicked',lambda _,cb=callback:cb());buttons.add(btn)
        try:self.fill(core.load())
        except Exception:self.fill(core.DEFAULTS);self.notice.set_text(tr('Bestehende Konfiguration konnte nicht gelesen werden. JSON-Profil importieren; bisherige Dateien bleiben unverändert.'))
    def change_hostname(self):
        value=self.hostname_entry.get_text()
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.WARNING,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('System-Hostname ändern? Administratorfreigabe erforderlich. Andere Geräte, DNS und Freigaben können noch den alten Namen verwenden. Keine Änderung an IP, Benutzerkonto oder Gerätekennung. Laufende Sicherungen zuerst abschließen.'));yes=dialog.run()==Gtk.ResponseType.OK;dialog.destroy()
        if yes:self.run_action(lambda:core.rename_host(value))
    def fill(self,values):
        for key,entry in self.entries.items():
            if isinstance(entry,Gtk.ComboBoxText):entry.set_active_id(values.get(key,core.DEFAULTS[key]))
            else:entry.set_text(values.get(key,''))
    def values(self):return {k:(e.get_active_id() if isinstance(e,Gtk.ComboBoxText) else e.get_text()) for k,e in self.entries.items()}
    def save(self):
        try:core.save(self.values());self.notice.set_text(tr('Gespeichert. Der nächste Heartbeat verwendet die Einstellungen. „Mit Server starten“ weckt bei der nächsten Anmeldung; jetzt bei Bedarf „Wecken und verbinden“ wählen.'));return True
        except Exception as exc:self.message(str(exc),True);return False
    def reload(self):
        try:self.fill(core.load());self.notice.set_text(tr('Bestehende Konfiguration geladen; noch nichts geändert.'))
        except Exception as exc:self.message(str(exc),True)
    def import_profile(self):
        dialog=Gtk.FileChooserDialog(title=tr('Client-Profil aus dem Manager importieren'),parent=self.window,action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Öffnen'),Gtk.ResponseType.OK)
        filt=Gtk.FileFilter();filt.set_name(tr('Client-Profil (.json)'));filt.add_pattern('*.json');dialog.add_filter(filt)
        if dialog.run()==Gtk.ResponseType.OK:
            try:self.fill(core.read_profile(dialog.get_filename()));connection.import_profile(dialog.get_filename());self.notice.set_text(tr('Profil geladen. Angaben prüfen, ggf. privates HTTPS einrichten, speichern und Agent aktivieren. Einrichtungscode gilt 15 Minuten. Das Profil enthält deinen Token; geschützt aufbewahren.'))
            except Exception as exc:self.message(str(exc),True)
        dialog.destroy()
    def enable(self):
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('Agent für diesen Benutzer aktivieren? Vorhandene Agenten-Units werden gesichert und durch die Paketversion ersetzt. Es wird derselbe Heartbeat-Timer verwendet. Statussymbol startet künftig bei deiner Anmeldung.'))
        yes=dialog.run()==Gtk.ResponseType.OK;dialog.destroy()
        if yes and self.save():self.run_action(core.install_user)
    def disable(self):self.run_action(core.deactivate)
    def tray_state(self):
        name='connecting' if self.connecting else ('online' if self.connected else 'offline')
        if self.indicator:self.indicator.set_icon_full(str(core.LIB/'icons'/(name+'.png')),{'connecting':tr('Verbindung wird hergestellt …'),'online':tr('Verbunden · Agenten-Anmeldung bestätigt'),'offline':tr('Keine bestätigte Agenten-Verbindung')}[name])
    def run_action(self,fn,connecting=False):
        if self.busy:self.notice.set_text(tr('Eine Aktion läuft bereits. Bitte warten.'));return
        self.connecting=connecting;self.tray_state()
        self.busy=True;self.notice.set_text(tr('Aktion läuft … Aufwecken kann mehrere Minuten dauern.'))
        def worker():
            try:result=fn();error=False
            except Exception as exc:result=str(exc);error=True
            GLib.idle_add(done,result,error)
        def done(result,error):
            self.busy=False;self.connecting=False;self.tray_state();self.notice.set_text(result)
            if not error and fn==core.install_user:self.fill(core.load())
            if error:self.message(result,True)
            self.refresh();return False
        threading.Thread(target=worker,daemon=True).start()
    def refresh(self):
        if self.polling:return True
        self.polling=True
        def worker():
            try:state=core.status()
            except Exception:state={'online':False,'service':False,'message':tr('Konfiguration prüfen')}
            GLib.idle_add(done,state)
        def done(state):
            self.polling=False;self.state.set_text(state['message']+' · Heartbeat: '+(tr('aktiv') if state['service'] else tr('inaktiv')))
            self.connected=state.get('connected',False);self.tray_state()
            return False
        threading.Thread(target=worker,daemon=True).start();return True
    def show_logs(self):
        def show(text):
            dialog=Gtk.Dialog(title=tr('Agenten-Protokoll'),transient_for=self.window);dialog.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE);dialog.set_default_size(720,400)
            scroll=Gtk.ScrolledWindow();view=Gtk.TextView(editable=False,monospace=True);view.get_buffer().set_text(text);scroll.add(view);dialog.get_content_area().pack_start(scroll,True,True,0);dialog.show_all();dialog.run();dialog.destroy();return False
        def worker():
            try:text=core.logs()
            except Exception:text=tr('Protokoll nicht verfügbar.')
            GLib.idle_add(show,text)
        threading.Thread(target=worker,daemon=True).start()
    def make_tray(self):
        if Indicator is None:self.notice.set_text(tr('Statussymbol nicht verfügbar. Das Fenster bleibt als Bedienoberfläche nutzbar.'));return
        self.indicator=Indicator.Indicator.new('heimserver-manager-client',str(core.LIB/'icons/offline.png'),Indicator.IndicatorCategory.APPLICATION_STATUS)
        menu=Gtk.Menu()
        for label,fn in [(tr('Öffnen / Einstellungen'),self.do_activate),(tr('Server wecken'),lambda:self.run_action(lambda:core.action('wake'),connecting=True)),(tr('Server benötigt'),lambda:self.run_action(lambda:core.action('need'),connecting=True)),(tr('Server freigeben'),lambda:self.run_action(lambda:core.action('release'),connecting=True)),(tr('Statussymbol beenden (Agent läuft weiter)'),self.quit)]:
            item=Gtk.MenuItem(label=label);item.connect('activate',lambda _,cb=fn:cb());menu.append(item)
        menu.show_all();self.indicator.set_menu(menu);self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
    def close_window(self,*args):
        if self.indicator:self.window.hide();return True
        self.quit();return False

if __name__=='__main__':
    if os.geteuid()==0:raise SystemExit(tr('Bitte als normaler Desktop-Benutzer ohne sudo starten.'))
    raise SystemExit(App().run(sys.argv))
