"""Unprivileged GTK front end; privileged script retains all safety checks."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import re
import json,subprocess,threading
from pathlib import Path
from gi.repository import Gtk,GLib

PREFIX='HSM_RECOVERY_PROMPT:'
def open_dialog(app):
    dialog=Gtk.Dialog(title=tr('System sichern & wiederherstellen'),transient_for=app.window)
    dialog.set_default_size(780,580)
    close=dialog.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE)
    page=Gtk.ScrolledWindow();page.set_vexpand(True);dialog.get_content_area().pack_start(page,True,True,0)
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);page.add(box)
    note=Gtk.Label(label=tr('HTTPS: direkt zum Manager sichern, ohne Ordnerauswahl, SMB oder NFS. USB/NFS: separater Assistent für eine bereits eingehängte Ablage. Kein Festplattenabbild; Partitionierung und Bootloader bleiben separat.'),wrap=True);box.add(note)
    full=Gtk.CheckButton(label=tr('Vollständiges Linux-System statt nur eigener Home-Daten sichern'));full.set_active(True);box.add(full)
    box.add(Gtk.Label(label=tr('Standard: gemeinsamer PC-Systemstand und getrennte persönliche Daten. Zusätzliche Datenplatten und Serverfreigaben nur im ausdrücklich neu gesicherten Systemstand nach Auswahl.'),wrap=True))
    refresh=Gtk.CheckButton(label=tr('Gemeinsamen PC-Systemstand neu sichern (Freigabe erforderlich)'));box.add(refresh)
    box.add(Gtk.Label(label=tr('Ein vorhandener PC-Systemstand wird wiederverwendet. Persönliche Daten bleiben pro Benutzer getrennt und werden inkrementell gesichert. Nach System- oder Programmänderungen den gemeinsamen Stand ausdrücklich neu sichern. Andere Benutzer müssen ihr Home selbst sichern.'),wrap=True))
    login=Gtk.Button(label=tr('Am Manager anmelden / Konto wechseln'));box.add(login)
    def sign_in(_):
        import extras_ui
        extras_ui.manager_login(app,on_success=lambda:append(tr('Anmeldung übernommen. Sicherungsstatus erneut prüfen.')+'\n'))
    login.connect('clicked',sign_in)
    status_button=Gtk.Button(label=tr('Sicherungsstatus dieses PCs prüfen'));box.add(status_button)
    cancel_system=Gtk.Button(label=tr('Unvollständige PC-Systemübertragung verwerfen (Freigabe erforderlich)'));box.add(cancel_system)
    source=Gtk.Entry();source.set_text('/');source.set_placeholder_text(tr('Linux-Quellsystem: / oder eingehängtes Offline-System'));box.add(Gtk.Label(label=tr('Linux-Quellsystem (Standard: laufender Client)')));box.add(source)
    extra=Gtk.Entry();extra.set_placeholder_text(tr('Zusätzliche Datenplatten oder Serverfreigaben: Mountpunkte getrennt durch ; (optional)'))
    box.add(extra)
    volumes=Gtk.Button(label=tr('Zusätzliche Datenplatten / Serverfreigaben auswählen'));box.add(volumes)
    def choose_volumes(_):
        try:
            import system_stream
            root=system_stream.source_root({'source_root':source.get_text().strip() or '/'})
            rows=system_stream.relative_mounts(root,system_stream.mounts())
            selected={p.strip() for p in extra.get_text().split(';') if p.strip()}
            q=Gtk.Dialog(title=tr('Zusätzliche Datenplatten und Serverfreigaben'),transient_for=dialog,modal=True)
            q.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Übernehmen'),Gtk.ResponseType.OK)
            choices=[]
            for row in rows:
                if row.get('fstype') not in system_stream.BACKUP_FILESYSTEMS:continue
                name=row['target'];check=Gtk.CheckButton(label=name+' · '+row['fstype'])
                automatic=name in system_stream.SYSTEM_MOUNTS and row['fstype'] in system_stream.FILESYSTEMS
                check.set_active(name in selected or automatic)
                check.set_sensitive(not automatic);q.get_content_area().add(check);choices.append((name,check,automatic))
            q.show_all()
            if q.run()==Gtk.ResponseType.OK:extra.set_text('; '.join(name for name,check,automatic in choices if check.get_active() and not automatic))
            q.destroy()
        except Exception as exc:append(str(exc)+'\n')
    volumes.connect('clicked',choose_volumes)
    private=Gtk.CheckButton(label=tr('Netzwerkprofile einschließlich Zugangsdaten mitsichern'));box.add(private)
    box.add(Gtk.Label(label=tr('HTTPS: vorhandenen Systemstand prüfen, danach eigene persönliche Daten sichern. Neue Systemstände erfordern Administratorrechte im Manager oder die Benutzerfreigabe für Systemsicherungen. Datenbanken/VMs/Container vorher geordnet stoppen.'),wrap=True))
    scroll=Gtk.ScrolledWindow();scroll.set_vexpand(True);scroll.set_size_request(-1,150)
    view=Gtk.TextView(editable=False,wrap_mode=Gtk.WrapMode.WORD_CHAR);scroll.add(view);box.pack_start(scroll,True,True,0)
    meter=Gtk.ProgressBar(show_text=True);meter.set_text(tr('Sicherungsumfang noch nicht ermittelt'));box.add(meter)
    start=Gtk.Button(label=tr('USB/NFS-Assistent – lokale oder eingehängte Ablage'));box.add(start)
    state={'busy':False}
    cancel=Gtk.Button(label=tr('Sicherung abbrechen'));cancel.set_sensitive(False);box.add(cancel)
    def cancel_backup(_):
        import backup
        if backup.request_cancel():append(tr('Abbruch angefordert. Laufenden Abschnitt beenden und unvollständigen Stand aufräumen …')+'\n');cancel.set_sensitive(False)
    cancel.connect('clicked',cancel_backup)
    def cancel_state():
        import backup
        job=backup.CURRENT_BACKUP
        cancel.set_sensitive(job is not None and not job.event.is_set())
        return dialog.get_visible()
    GLib.timeout_add(250,cancel_state)
    def append(text):
        if text.startswith(tr('Sicherungsumfang ermitteln …')):meter.set_fraction(0);meter.set_text(tr('Sicherungsumfang ermitteln …'))
        if text.startswith(tr('Fortschritt nach Umfang (ca.): ')) or text.startswith(tr('Sicherung erfolgreich abgeschlossen: 100 %')):
            match=re.search(r'(\d+) %',text)
            if match:meter.set_fraction(int(match.group(1))/100);meter.set_text(text.strip())
        if text.startswith(tr('Sicherungsstand am Server prüfen …')):meter.set_text(tr('Sicherungsstand am Server prüfen …'))
        if text.startswith(tr('Serverprüfung: ')):meter.set_text(text.strip())
        buf=view.get_buffer();buf.insert(buf.get_end_iter(),text)
        view.scroll_to_iter(buf.get_end_iter(),0,False,0,0)
        return False
    def ask(prompt,event,result):
        choose=any(word in prompt for word in ('Sicherungsablage auf','Sicherungsordner mit','Eingehängtes installiertes Zielsystem'))
        if choose:
            picker=Gtk.FileChooserDialog(title=prompt,parent=dialog,action=Gtk.FileChooserAction.SELECT_FOLDER)
            picker.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Ordner auswählen'),Gtk.ResponseType.OK)
            picker.set_local_only(True)
            # Expose already mounted POSIX USB/NFS volumes as convenient shortcuts.
            try:
                data=json.loads(subprocess.check_output(['findmnt','-J','-l','-o','TARGET,FSTYPE'],text=True,timeout=5))
                for row in data.get('filesystems',[]):
                    target=row.get('target','')
                    if target!='/' and row.get('fstype') in ('ext2','ext3','ext4','btrfs','xfs','f2fs','nfs','nfs4') and Path(target).is_dir():
                        try:picker.add_shortcut_folder(target)
                        except GLib.Error:pass
            except (OSError,ValueError,subprocess.SubprocessError):pass
            if picker.run()==Gtk.ResponseType.OK:result.append(picker.get_filename())
            picker.destroy()
        else:
            picker=Gtk.Dialog(title=tr('Systemassistent – Auswahl'),transient_for=dialog,modal=True)
            picker.set_default_size(650,200)
            picker.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Weiter'),Gtk.ResponseType.OK)
            area=picker.get_content_area();area.set_spacing(8)
            buf=view.get_buffer();context=buf.get_text(buf.get_start_iter(),buf.get_end_iter(),False)[-2200:]
            area.add(Gtk.Label(label=context,wrap=True,selectable=True))
            area.add(Gtk.Label(label=prompt,wrap=True));entry=Gtk.Entry();area.add(entry)
            entry.set_activates_default(True);picker.set_default_response(Gtk.ResponseType.OK)
            picker.show_all()
            if picker.run()==Gtk.ResponseType.OK:result.append(entry.get_text())
            picker.destroy()
        event.set();return False
    def finish(text):
        append(text+'\n');state['busy']=False;cancel.set_sensitive(False);login.set_sensitive(True);close.set_sensitive(True);start.set_sensitive(True);server.set_sensitive(True);restore.set_sensitive(True);return False
    def run():
        try:
            process=subprocess.Popen(['pkexec','/bin/bash','/usr/lib/heimserver-manager-client/system-recovery.sh','--gui'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            cancelled=False
            for line in process.stdout:
                if line.startswith(PREFIX):
                    event=threading.Event();answer=[]
                    GLib.idle_add(ask,line[len(PREFIX):].rstrip(),event,answer);event.wait()
                    if not answer:
                        process.stdin.close();cancelled=True
                    elif not cancelled:
                        process.stdin.write(answer[0]+'\n');process.stdin.flush()
                else:GLib.idle_add(append,line)
            code=process.wait()
            text=tr('Abgebrochen. Mögliche Teilergebnisse im Protokoll prüfen.') if cancelled else (tr('Ablauf beendet. Berichte auf ausgelassene Bestandteile prüfen.') if code==0 else tr('Fehlgeschlagen (Code ')+str(code)+tr('). Protokoll oben prüfen.'))
        except Exception as exc:text=tr('Systemassistent: ')+str(exc)
        GLib.idle_add(finish,text)
    def launch(_):
        question=Gtk.MessageDialog(transient_for=dialog,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('USB/NFS-Assistent öffnen?'))
        question.format_secondary_text(tr('Dieser Ablauf verlangt einen eingehängten Sicherungsordner. Für direkte Übertragung zum Manager abbrechen und die HTTPS-Schaltfläche wählen.'))
        accepted=question.run()==Gtk.ResponseType.OK;question.destroy()
        if not accepted:return
        state['busy']=True;login.set_sensitive(False);close.set_sensitive(False);start.set_sensitive(False);server.set_sensitive(False);restore.set_sensitive(False)
        threading.Thread(target=run,daemon=True).start()
    server=Gtk.Button(label=tr('Diesen Linux-Client direkt auf den Server sichern (HTTPS)'))
    box.pack_start(server,False,False,0)
    box.reorder_child(server,1)
    def server_start(_):
        if app.busy or state['busy']:return
        meter.set_fraction(0);meter.set_text(tr('Sicherungsumfang noch nicht ermittelt'))
        if not full.get_active():
            import extras_ui,backup
            if extras_ui.confirm(app,tr('Nur eigene Home-Daten auf den Server sichern? Eingebundene Laufwerke und Serverfreigaben bleiben ausgeschlossen. Dies ist eine Dateisicherung, keine Systemsicherung.')):
                state['busy']=True;login.set_sensitive(False);close.set_sensitive(False);start.set_sensitive(False);server.set_sensitive(False);restore.set_sensitive(False)
                def home_task():
                    try:text=backup.create(Path.home(),lambda value:GLib.idle_add(append,value+'\n'))
                    except Exception as exc:text=str(exc)
                    GLib.idle_add(finish,text)
                threading.Thread(target=home_task,daemon=True).start()
            return
        question=Gtk.MessageDialog(transient_for=dialog,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('Linux-System über HTTPS sichern?'))
        question.format_secondary_text(tr('PC-Systemstand prüfen und wiederverwenden; nur eigene persönliche Daten separat sichern. Andere Benutzer-Homes bleiben ausgeschlossen. Neue Systemstände benötigen Administratorrechte oder eine ausdrückliche Benutzerfreigabe. Zusätzliche Datenträger werden nur beim neuen Systemstand berücksichtigt. Kein lokales Zwischenarchiv. System und persönliche Daten werden getrennt wiederhergestellt.')+'\n\n'+tr('Zusätzlich ausgewählt: ')+(extra.get_text().strip() or tr('Keine')))
        accepted=question.run()==Gtk.ResponseType.OK;question.destroy()
        if not accepted:return
        append(tr('HTTPS-Sicherung: Verbindung zum Manager prüfen; kein lokaler Zielordner erforderlich.\n'))
        options={'source_root':source.get_text().strip() or '/','extra_mounts':[p.strip() for p in extra.get_text().split(';') if p.strip()],'network_profiles':private.get_active(),'refresh_system':refresh.get_active()}
        state['busy']=True;login.set_sensitive(False);close.set_sensitive(False);start.set_sensitive(False);server.set_sensitive(False);restore.set_sensitive(False)
        def confirm_exclusions(rows):
            event=threading.Event();answer=[]
            def show():
                question=Gtk.Dialog(title=tr('Nicht lesbare Sicherungsquellen'),transient_for=dialog,modal=True)
                question.add_button(tr('Abbrechen'),Gtk.ResponseType.CANCEL)
                question.add_button(tr('Aufgelistete Pfade nicht sichern'),Gtk.ResponseType.OK)
                question.set_default_response(Gtk.ResponseType.CANCEL);question.set_default_size(720,420)
                content=question.get_content_area()
                label=Gtk.Label(label=tr('Diese Dateien und Ordner einschließlich ihrer Inhalte fehlen in dieser Sicherung. Nur für diesen Lauf ausschließen und fortfahren?'));label.set_line_wrap(True);content.add(label)
                scroll=Gtk.ScrolledWindow();scroll.set_vexpand(True)
                report=Gtk.TextView();report.set_editable(False);report.get_buffer().set_text('\n\n'.join(r['path']+'\n'+r['reason'] for r in rows));scroll.add(report);content.add(scroll)
                question.show_all();answer.append(question.run()==Gtk.ResponseType.OK);question.destroy();event.set();return False
            GLib.idle_add(show)
            while not event.wait(.2):
                import backup
                backup.check_cancel()
            return bool(answer and answer[0])
        def confirm_interrupted(row):
            event=threading.Event();answer=[]
            def show():
                question=Gtk.MessageDialog(transient_for=dialog,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('Unvollständige Sicherung zurücklegen und neu starten?'))
                question.format_secondary_text(str(row.get('name',''))+'\n'+str(row['created'])+'\n'+str(row['id'])+'\n\n'+tr('Nur bestätigen, wenn der vorherige Lauf beendet ist. Eine zur Anmeldung pausierte Sicherung nicht ersetzen. Fertige Stände und übertragene Datenblöcke bleiben erhalten; Dateien werden neu eingelesen.'))
                question.set_default_response(Gtk.ResponseType.CANCEL)
                answer.append(question.run()==Gtk.ResponseType.OK);question.destroy();event.set();return False
            GLib.idle_add(show)
            while not event.wait(.2):
                import backup
                backup.check_cancel()
            return bool(answer and answer[0])
        def task():
            try:
                from system_https import create
                text=create(lambda value:GLib.idle_add(append,value+'\n'),options=options,confirm_exclusions=confirm_exclusions,confirm_interrupted=confirm_interrupted)
            except Exception as exc:text=str(exc)
            GLib.idle_add(finish,text);GLib.idle_add(server.set_sensitive,True)
        threading.Thread(target=task,daemon=True).start()
    def check_pc(_):
        if state['busy']:return
        def run_check():
            try:
                import backup
                value=backup.call('pc-status')
                text=tr('Gemeinsamer Systemstand: ')+(value['system']['created'] if value.get('system') else tr('Noch keiner'))+'\n'+tr('Eigene persönliche Sicherung: ')+(value['personal']['created'] if value.get('personal') else tr('Noch keine'))
            except Exception as exc:text=str(exc)
            GLib.idle_add(append,text+'\n')
        threading.Thread(target=run_check,daemon=True).start()
    status_button.connect('clicked',check_pc)
    def discard_system(_):
        if state['busy']:return
        import extras_ui
        if not extras_ui.confirm(app,tr('Nur die unvollständige gemeinsame Systemübertragung dieses PCs verwerfen? Laufende Sicherungen vorher beenden. Fertige Stände bleiben erhalten.')):return
        def discard():
            try:
                import backup
                value=backup.call('pc-status')
                backup.call('cancel',{},query='&pc='+value['device_id'])
                text=tr('Unvollständige PC-Systemübertragung verworfen.')
            except Exception as exc:text=str(exc)
            GLib.idle_add(append,text+'\n')
        threading.Thread(target=discard,daemon=True).start()
    cancel_system.connect('clicked',discard_system)
    def scope_changed(*_):
        enabled=full.get_active()
        for widget in (source,extra,volumes,private,refresh):widget.set_sensitive(enabled)
        server.set_label(tr('Diesen Linux-Client direkt auf den Server sichern (HTTPS)') if enabled else tr('Eigene Home-Daten auf den Server sichern (HTTPS)'))
    full.connect('toggled',scope_changed);scope_changed()
    restore=Gtk.Button(label=tr('Systemstand / Komponenten / einzelne Dateien wiederherstellen'))
    box.pack_start(restore,False,False,0)
    def restore_start(_):
        from system_restore_ui import open_restore
        open_restore(app,dialog)
    restore.connect('clicked',restore_start)
    server.connect('clicked',server_start)
    start.connect('clicked',launch)
    dialog.connect('delete-event',lambda *_:state['busy'])
    dialog.show_all()
    while True:
        response=dialog.run()
        if not state['busy']:break
    dialog.destroy()
