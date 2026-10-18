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
from system_recovery_ui import configure_scroll,fit_window,install_scroll_style
try:
    from client_version import VERSION
except ImportError:
    VERSION=tr('Entwicklungsstand')
import extras_ui,connection,offline_ui,offline_lifecycle,user_ids_ui

LABELS={'SERVER_URL':tr('Manager-Adresse (http:// oder https://)'),'TOKEN':tr('Agenten-Token'),'CLIENT_NAME':tr('Client-Name'),'CLIENT_MAC':tr('Client-MAC (optional)'),'IPMI_RECOVER_URL':tr('Recovery-Adresse (optional)'),'SERVER_MAC':tr('Server-MAC für Wake-on-LAN'),'WAKE_TIMEOUT':tr('Recovery-Timeout (1–300 Sekunden)')}
MODES={'without_server':tr('Ohne Server starten'),'with_server':tr('Mit Server starten / Server benötigt'),'wake_on_access':tr('Nur auf ausdrücklichen Aufruf wecken')}
WAKE={'none':tr('Nicht wecken'),'wol':tr('Wake-on-LAN'),'recover':tr('Recovery-Dienst'),'both':tr('Recovery und Wake-on-LAN')}
class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.heimservermanager.Client',flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.window=None;self.entries={};self.busy=False;self.polling=False;self.indicator=None;self.connecting=False;self.connected=False
    def do_startup(self):
        Gtk.Application.do_startup(self);install_scroll_style();self.hold()
        import offline
        offline.resume()
        self.make_window();self.make_tray();
        import backup
        backup.REAUTH_HANDLER=lambda username,message,job:extras_ui.reauthenticate(self,username,message,job)
        self.offline_lifecycle=offline_lifecycle.Monitor(self);GLib.timeout_add_seconds(15,self.refresh);self.refresh()
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
        self.window=Gtk.ApplicationWindow(application=self,title=tr('Heimserver Manager Client · ')+VERSION);fit_window(self.window,760,520)
        self.window.connect('delete-event',self.close_window)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10,margin=16);self.window.add(outer)
        self.state=Gtk.Label(label=tr('Status wird geprüft …'),xalign=0);self.state.set_line_wrap(True);outer.pack_start(self.state,False,False,0)
        self.notice=Gtk.Label(label=tr('Dienst arbeitet nach Aktivierung in deiner Benutzersitzung. Fenster schließen beendet den Agenten nicht.'),xalign=0,yalign=0)
        self.notice.set_line_wrap(True);self.notice.set_selectable(True);self.notice.set_max_width_chars(80)
        notice_scroll=Gtk.ScrolledWindow();configure_scroll(notice_scroll)
        notice_scroll.set_min_content_height(90);notice_scroll.set_max_content_height(120)
        notice_scroll.set_propagate_natural_height(False);notice_scroll.set_size_request(-1,110)
        notice_scroll.add(self.notice);outer.pack_start(notice_scroll,False,False,0)
        actions=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,max_children_per_line=3);outer.pack_start(actions,False,False,0)
        for label,action in [(tr('Server wecken'),'wake'),(tr('Server benötigt'),'need'),(tr('Server freigeben'),'release'),(tr('Wecken und verbinden'),'connect'),(tr('Zugriff vorbereiten'),'access')]:
            button=Gtk.Button(label=label);button.connect('clicked',lambda _,a=action:self.release_server() if a=='release' else self.run_action(lambda:core.action(a),connecting=True));actions.add(button)
        note=Gtk.Label(label=tr('„Server freigeben“ pausiert den Serverbedarf und Offline-Abgleich bis zum nächsten Client-Start oder einer manuellen Umschaltung. „Zugriff vorbereiten“ weckt und wartet auf den Server. Dateizugriff wird nicht automatisch überwacht.'),xalign=0);note.set_line_wrap(True);outer.pack_start(note,False,False,0)
        scroll=Gtk.ScrolledWindow();configure_scroll(scroll)
        scroll.set_min_content_height(280);scroll.set_max_content_height(500);scroll.set_propagate_natural_height(True)
        setup=Gtk.Expander(label=tr('Anmeldung & Einrichtung'));setup.set_expanded(not core.CONFIG.exists());setup.add(scroll)
        setup_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);scroll.add(setup_box)
        grid=Gtk.Grid(column_spacing=12,row_spacing=8);setup_box.pack_start(grid,False,False,0)
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
        GLib.timeout_add_seconds(60,offline_ui.tick,self)
        setup_buttons=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,max_children_per_line=2);setup_box.pack_start(setup_buttons,False,False,0)
        for label,callback in [(tr('Profil importieren'),self.import_profile),(tr('Privates HTTPS'),lambda:extras_ui.https(self)),(tr('Am Manager anmelden'),lambda:extras_ui.manager_login(self)),(tr('Benutzer & Gerät koppeln'),lambda:extras_ui.pair_device(self)),(tr('UID/GID verwalten'),lambda:user_ids_ui.show(self)),(tr('Speichern'),self.save),(tr('Bestehende Einstellungen laden'),self.reload),(tr('Agent aktivieren / übernehmen'),self.enable),(tr('Agent deaktivieren'),self.disable)]:
            btn=Gtk.Button(label=label);btn.connect('clicked',lambda _,cb=callback:cb());setup_buttons.add(btn)
        for label,callback in [(tr('Offline-Dateien'),lambda:offline_ui.show(self)),(tr('Eigene Backups / Wiederherstellung'),lambda:extras_ui.backups(self)),(tr('Server-Backup (Administrator)'),lambda:extras_ui.server(self)),(tr('Protokoll'),self.show_logs),(tr('Aktualisieren'),lambda:self.refresh())]:
            btn=Gtk.Button(label=label);btn.connect('clicked',lambda _,cb=callback:cb());buttons.add(btn)
        outer.pack_start(setup,False,False,0)
        footer=Gtk.Box(spacing=6)
        footer.pack_start(Gtk.Label(label=tr('Software herunterladen:'),xalign=0),False,False,0)
        self.download_link=Gtk.LinkButton.new_with_label('https://Server:8443/clients/setup','https://Server:8443/clients/setup')
        self.download_link.set_halign(Gtk.Align.START)
        footer.pack_start(self.download_link,False,False,0)
        outer.pack_end(footer,False,False,0)
        def update_download_link(*_):
            from urllib.parse import urlsplit,urlunsplit
            raw=self.entries['SERVER_URL'].get_text().strip()
            try:
                url=urlsplit(raw)
                valid=url.scheme in ('http','https') and bool(url.hostname) and url.port != 0 and not url.username and not url.password
                target=urlunsplit((url.scheme,url.netloc,url.path.rstrip('/')+'/clients/setup','','')) if valid else ''
            except ValueError:target=''
            self.download_link.set_uri(target or 'https://Server:8443/clients/setup')
            self.download_link.set_label(target or 'https://Server:8443/clients/setup')
            self.download_link.set_sensitive(bool(target))
            self.download_link.set_tooltip_text(target or tr('Zuerst die Manager-Adresse eintragen.'))
        self.entries['SERVER_URL'].connect('changed',update_download_link)
        update_download_link()
        def resize_setup(*_):
            fit_window(self.window,760,900 if setup.get_expanded() else 520)
            display=self.window.get_display();monitor=display.get_monitor_at_window(self.window.get_window()) if self.window.get_window() else display.get_primary_monitor()
            area=monitor.get_workarea() if monitor else None
            self.window.resize(min(760,area.width-40) if area else 760,min(900 if setup.get_expanded() else 520,area.height-60) if area else 520)
        setup.connect('notify::expanded',resize_setup)
        progress_seen=[False]
        def show_sync_progress():
            import json,offline
            try:
                data=json.loads((offline.ROOT/'progress.json').read_text())
                if data.get('state')=='running' and not self.busy:
                    os.kill(int(data['pid']),0)
                    self.notice.set_text(data.get('folder','')+' · '+data.get('detail',''));progress_seen[0]=True
                elif data.get('state') in ('finished','failed') and progress_seen[0] and not self.busy:
                    self.notice.set_text(data.get('folder','')+' · '+data.get('detail',''));progress_seen[0]=False
            except (OSError,ValueError,KeyError):pass
            return True
        GLib.timeout_add_seconds(1,show_sync_progress)
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
        try:
            previous=core.load()['CLIENT_MODE'];values=self.values();core.save(values)
            if previous!=values['CLIENT_MODE']:
                import offline
                offline.resume()
            self.notice.set_text(tr('Gespeichert. Der nächste Heartbeat verwendet die Einstellungen. „Mit Server starten“ weckt bei der nächsten Anmeldung; jetzt bei Bedarf „Wecken und verbinden“ wählen.'));return True
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
    def release_server(self):
        # Releasing must remain available while an automatic sync owns busy.
        if getattr(self,'releasing',False):return
        self.releasing=True
        def done(message):
            self.releasing=False;self.notice.set_text(message);self.refresh();return False
        def worker():
            try:message=core.action('release')
            except Exception as exc:message=str(exc)
            GLib.idle_add(done,message)
        threading.Thread(target=worker,daemon=True).start()

    def run_action(self,fn,connecting=False,on_success=None):
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
            self.refresh()
            if not error and on_success:on_success()
            return False
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
            dialog=Gtk.Dialog(title=tr('Agenten-Protokoll'),transient_for=self.window);dialog.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE);fit_window(dialog,760,900)
            scroll=Gtk.ScrolledWindow();configure_scroll(scroll);view=Gtk.TextView(editable=False,monospace=True);view.get_buffer().set_text(text);scroll.add(view);dialog.get_content_area().pack_start(scroll,True,True,0);dialog.show_all();dialog.run();dialog.destroy();return False
        def worker():
            try:text=core.logs()
            except Exception:text=tr('Protokoll nicht verfügbar.')
            GLib.idle_add(show,text)
        threading.Thread(target=worker,daemon=True).start()
    def make_tray(self):
        if Indicator is None:self.notice.set_text(tr('Statussymbol nicht verfügbar. Das Fenster bleibt als Bedienoberfläche nutzbar.'));return
        self.indicator=Indicator.Indicator.new('heimserver-manager-client',str(core.LIB/'icons/offline.png'),Indicator.IndicatorCategory.APPLICATION_STATUS)
        menu=Gtk.Menu()
        for label,fn in [(tr('Öffnen / Einstellungen'),self.do_activate),(tr('Server wecken'),lambda:self.run_action(lambda:core.action('wake'),connecting=True)),(tr('Server benötigt'),lambda:self.run_action(lambda:core.action('need'),connecting=True)),(tr('Server freigeben'),self.release_server),(tr('Statussymbol beenden (Agent läuft weiter)'),self.quit)]:
            item=Gtk.MenuItem(label=label);item.connect('activate',lambda _,cb=fn:cb());menu.append(item)
        self.offline_menu_item=Gtk.MenuItem(label=tr('Offline-Dateien'))
        submenu=Gtk.Menu();self.offline_menu_item.set_submenu(submenu);menu.insert(self.offline_menu_item,4)
        now=Gtk.MenuItem(label=tr('Jetzt synchronisieren'));now.connect('activate',lambda _:self.sync_offline_now());submenu.append(now)
        submenu.append(Gtk.SeparatorMenuItem());self.offline_modes={};self.updating_offline_menu=False
        for mode,label in [('interval','Alle 10 Minuten'),('startup','Nach Client-Start'),('manual','Nur manuell')]:
            item=Gtk.CheckMenuItem(label=tr(label));item.set_draw_as_radio(True)
            item.connect('activate',self.offline_schedule_selected,mode);submenu.append(item);self.offline_modes[mode]=item
        menu.show_all();self.update_offline_menu();GLib.timeout_add_seconds(2,self.update_offline_menu)
        self.indicator.set_menu(menu);self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
    def update_offline_menu(self):
        import offline
        try:
            mode=offline.schedule_mode();self.offline_menu_item.set_visible(mode is not None)
            self.updating_offline_menu=True
            for key,item in self.offline_modes.items():item.set_active(key==mode)
        except Exception:self.offline_menu_item.hide()
        finally:self.updating_offline_menu=False
        return True
    def offline_schedule_selected(self,item,mode):
        if self.updating_offline_menu:return
        import offline
        try:self.notice.set_text(offline.set_schedule(mode))
        except Exception as exc:self.message(str(exc),True)
        self.update_offline_menu()
    def sync_offline_now(self):
        import offline
        self.run_action(lambda:offline.sync_many([r['id'] for r in offline.config()],lambda value:GLib.idle_add(self.notice.set_text,value)))
    def close_window(self,*args):
        if self.indicator:self.window.hide();return True
        self.quit();return False

if __name__=='__main__':
    if os.geteuid()==0:raise SystemExit(tr('Bitte als normaler Desktop-Benutzer ohne sudo starten.'))
    raise SystemExit(App().run(sys.argv))
