"""Unprivileged GTK front end; privileged script retains all safety checks."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,subprocess,threading
from pathlib import Path
from gi.repository import Gtk,GLib

PREFIX='HSM_RECOVERY_PROMPT:'
def open_dialog(app):
    dialog=Gtk.Dialog(title=tr('System sichern & wiederherstellen'),transient_for=app.window)
    dialog.set_default_size(780,580)
    close=dialog.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE)
    box=dialog.get_content_area();box.set_spacing(10)
    note=Gtk.Label(label=tr('HTTPS: direkt zum Manager sichern, ohne Ordnerauswahl, SMB oder NFS. USB/NFS: separater Assistent für eine bereits eingehängte Ablage. Kein Festplattenabbild; Partitionierung und Bootloader bleiben separat.'),wrap=True);box.add(note)
    source=Gtk.Entry();source.set_text('/');source.set_placeholder_text(tr('Linux-Quellsystem: / oder eingehängtes Offline-System'));box.add(Gtk.Label(label=tr('Linux-Quellsystem (Standard: laufender Client)')));box.add(source)
    extra=Gtk.Entry();extra.set_placeholder_text(tr('Zusätzliche lokale Mountpunkte, getrennt durch ; (optional)'))
    box.add(extra)
    private=Gtk.CheckButton(label=tr('Netzwerkprofile einschließlich Zugangsdaten mitsichern'));box.add(private)
    box.add(Gtk.Label(label=tr('HTTPS: erster Lauf vollständig, danach neue Datenblöcke. Alle Quellen werden erneut gelesen. Native Programme, Flatpak, Homes und Systeminventar enthalten. Datenbanken/VMs/Container vorher geordnet stoppen.'),wrap=True))
    scroll=Gtk.ScrolledWindow();scroll.set_vexpand(True)
    view=Gtk.TextView(editable=False,wrap_mode=Gtk.WrapMode.WORD_CHAR);scroll.add(view);box.pack_start(scroll,True,True,0)
    start=Gtk.Button(label=tr('USB/NFS-Assistent – lokale oder eingehängte Ablage'));box.add(start)
    state={'busy':False}
    def append(text):
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
        append(text+'\n');state['busy']=False;close.set_sensitive(True);start.set_sensitive(True);server.set_sensitive(True);restore.set_sensitive(True);return False
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
        state['busy']=True;close.set_sensitive(False);start.set_sensitive(False);server.set_sensitive(False);restore.set_sensitive(False)
        threading.Thread(target=run,daemon=True).start()
    server=Gtk.Button(label=tr('Diesen Linux-Client direkt auf den Server sichern (HTTPS)'))
    box.pack_start(server,False,False,0)
    box.reorder_child(server,1)
    def server_start(_):
        question=Gtk.MessageDialog(transient_for=dialog,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.OK_CANCEL,text=tr('Linux-System über HTTPS sichern?'))
        question.format_secondary_text(tr('Vollständigen logischen Systemstand einschließlich Benutzer, Rechte und ausgewählter Datenträger übertragen. Unveränderte Blöcke werden wiederverwendet. Kein SMB/NFS und kein lokales Zwischenarchiv. Nicht ausgewählte Datenlaufwerke bleiben ausgeschlossen. Anwendungen und Datenbanken vorher beenden. Rücksicherung über „Systemarchiv vom Server wiederherstellen“ im Live-System; Zielpartitionen vorher passend einhängen. Partitionierung und Bootloader bleiben manuell.'))
        accepted=question.run()==Gtk.ResponseType.OK;question.destroy()
        if not accepted:return
        append(tr('HTTPS-Sicherung: Verbindung zum Manager prüfen; kein lokaler Zielordner erforderlich.\n'))
        options={'source_root':source.get_text().strip() or '/','extra_mounts':[p.strip() for p in extra.get_text().split(';') if p.strip()],'network_profiles':private.get_active()}
        state['busy']=True;close.set_sensitive(False);start.set_sensitive(False);server.set_sensitive(False);restore.set_sensitive(False)
        def task():
            try:
                from system_https import create
                text=create(lambda value:GLib.idle_add(append,value+'\n'),options=options)
            except Exception as exc:text=str(exc)
            GLib.idle_add(finish,text);GLib.idle_add(server.set_sensitive,True)
        threading.Thread(target=task,daemon=True).start()
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
