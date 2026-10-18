from system_recovery_ui import configure_scroll,fit_window,install_scroll_style
"""GUI for downloading and restoring an HTTPS system archive from a live system."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,json,shutil,subprocess,tempfile,threading,pwd,os
from pathlib import Path
from gi.repository import Gtk,GLib
import backup,core,system_recovery,system_components

def open_restore(app,parent,selected_id=None):
    d=Gtk.Dialog(title=tr('HTTPS-Systemarchiv wiederherstellen'),transient_for=parent);fit_window(d,760,900)
    close=d.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE)
    scroll=Gtk.ScrolledWindow();configure_scroll(scroll);scroll.set_vexpand(True);d.get_content_area().add(scroll)
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=10);scroll.add(box)
    box.add(Gtk.Label(label=tr('Vorhandenes Linux-Zielsystem separat einhängen. ZIP wird auf eine externe Linux-Platte geladen und vor Änderungen vollständig geprüft. Dafür dort mindestens zweimal Archivgröße frei halten. System/Komponenten nur im Live-System und auf gleicher Plattform; passende Zielpartitionen vorher einhängen. Einzeldateien können im laufenden System in einen neuen Ordner zurückgesichert werden. Partitionierung und Bootloader bleiben manuell.'),wrap=True))
    scope=Gtk.ComboBoxText()
    for key,label in system_components.SCOPES.items():scope.append(key,label)
    scope.append('migration',tr('Migration auf andere Distribution / Programme nachinstallieren'))
    box.add(Gtk.Label(label=tr('Migration: Home im Live-System übernehmen. Programme anschließend im gestarteten Zielsystem installieren (Ziel /). Zusätzlicher Platz für das entpackte System erforderlich. Zielbenutzer für Home-Abgleich abmelden.'),wrap=True))
    scope.set_active_id('all' if system_recovery.live() else 'migration');box.add(scope)
    selection=Gtk.Entry();selection.set_placeholder_text(tr('Für Einzeldateien: z. B. home/benutzer/Dokumente'));box.add(selection)
    source_user=Gtk.Entry();source_user.set_placeholder_text(tr('Migration: Benutzername aus der Sicherung'));box.add(source_user)
    source_user.set_text(pwd.getpwuid(os.getuid()).pw_name)
    target_user=Gtk.Entry();target_user.set_text(pwd.getpwuid(os.getuid()).pw_name);target_user.set_placeholder_text(tr('Migration: vorhandener Zielbenutzer'));box.add(target_user)
    prepared=Gtk.Entry();prepared.set_placeholder_text(tr('Vorbereitete Migration: Arbeitsverzeichnis für Fortsetzung (optional)'));box.add(prepared)
    resume=Gtk.Button(label=tr('Vorbereitete Migration fortsetzen (ohne erneuten Download)'));box.add(resume)
    choice=Gtk.ComboBoxText();box.add(choice);items={};busy={'value':False}
    box.add(Gtk.Label(label=tr('PC-System und persönliche Daten getrennt wählen. Gemeinsame Systemstände sind für Administratoren oder ausdrücklich freigegebene Benutzer sichtbar. Persönliche Stände enthalten ausschließlich das Home des jeweiligen Benutzers; erst System, dann gewünschte persönliche Stände wiederherstellen.'),wrap=True))
    def selected_component(_):
        item=items.get(choice.get_active_id(),{})
        scope.remove_all()
        for key,label in system_components.SCOPES.items():
            if item.get('component')=='personal' and key not in ('home','files'):continue
            scope.append(key,tr('Persönliche Dateien und Einstellungen') if item.get('component')=='personal' and key=='home' else label)
        scope.append('migration',tr('Persönliche Daten auf diesem PC übernehmen') if item.get('component')=='personal' else tr('Migration auf andere Distribution / Programme nachinstallieren'))
        scope.set_active_id('all' if system_recovery.live() else 'migration')
        if item.get('component')=='personal':
            scope.set_active_id('home' if system_recovery.live() else 'migration')
            if item.get('personal_user'):source_user.set_text(item['personal_user'])
            if item.get('personal_home'):selection.set_text(item['personal_home'].lstrip('/'))
        elif item.get('component')=='system' and not system_recovery.live():scope.set_active_id('migration')
    choice.connect('changed',selected_component)
    cache=Gtk.FileChooserButton(title=tr('Arbeitsablage auswählen'),action=Gtk.FileChooserAction.SELECT_FOLDER)
    target=Gtk.FileChooserButton(title=tr('Eingehängtes Linux-Zielsystem auswählen'),action=Gtk.FileChooserAction.SELECT_FOLDER)
    box.add(Gtk.Label(label=tr('Arbeitsablage: lokal oder auf Linux-Datenplatte; ausreichend Platz erforderlich')));box.add(cache)
    box.add(Gtk.Label(label=tr('Linux-Zielsystem; bei Einzeldateien übergeordneten Zielordner wählen')));box.add(target)
    running=Gtk.CheckButton(label=tr('Auf diesem laufenden PC wiederherstellen (Migration)'));running.set_active(not system_recovery.live());running.set_sensitive(not system_recovery.live());box.add(running)
    def scope_changed(_):running.set_sensitive(scope.get_active_id()=='migration' and not system_recovery.live())
    scope.connect('changed',scope_changed);scope_changed(None)
    status=Gtk.Label(label=tr('Sicherungsstände laden …'),wrap=True,selectable=True);box.add(status)
    start=Gtk.Button(label=tr('Herunterladen und Rücksicherung prüfen'));start.set_sensitive(False);box.add(start)
    def update(text):status.set_text(text);return False
    def confirm(plan,event,answer):
        q=Gtk.Dialog(title=tr('Ziel wird überschrieben'),transient_for=d,modal=True)
        q.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Wiederherstellen'),Gtk.ResponseType.OK)
        a=q.get_content_area();a.add(Gtk.Label(label=tr('Umfang: ')+plan.get('scope',tr('Vollständig'))+tr('\nZiel: ')+plan['target']+'\n'+str(plan['files'])+tr(' Einträge · ')+str(plan['bytes']//1024**2)+tr(' MiB\nSystemdateien und Benutzer werden überschrieben. fstab/crypttab bleiben erhalten. Zusätzliche Zieldateien werden nicht gelöscht. Bootloader vor Neustart prüfen.\nZum Bestätigen WIEDERHERSTELLEN eingeben.'),wrap=True))
        e=Gtk.Entry();a.add(e);q.show_all()
        if q.run()==Gtk.ResponseType.OK and e.get_text()=='WIEDERHERSTELLEN':answer.append(True)
        q.destroy();event.set();return False
    def migration_prompt(context,prompt,event,answer):
        q=Gtk.Dialog(title=tr('Systemmigration – Auswahl'),transient_for=d,modal=True)
        fit_window(q,760,900);q.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Weiter'),Gtk.ResponseType.OK)
        area=q.get_content_area();scroll=Gtk.ScrolledWindow();configure_scroll(scroll);scroll.set_vexpand(True)
        view=Gtk.TextView(editable=False,wrap_mode=Gtk.WrapMode.WORD_CHAR);view.get_buffer().set_text(context);scroll.add(view);area.pack_start(scroll,True,True,0)
        area.add(Gtk.Label(label=prompt,wrap=True));entry=Gtk.Entry();area.add(entry);q.show_all()
        if q.run()==Gtk.ResponseType.OK:answer.append(entry.get_text())
        q.destroy();event.set();return False
    def execute(command,selected_scope):
        p=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        result=None;transcript=''
        for line in p.stdout:
            transcript=(transcript+line)[-8000:]
            if line.startswith('HSM_RECOVERY_PROMPT:'):
                event=threading.Event();answer=[];GLib.idle_add(migration_prompt,transcript,line.split(':',1)[1],event,answer);event.wait()
                if not answer:p.stdin.close()
                else:p.stdin.write(answer[0]+'\n');p.stdin.flush()
                continue
            try:msg=json.loads(line)
            except ValueError:GLib.idle_add(update,line.strip());continue
            if msg.get('confirm'):
                event=threading.Event();answer=[];GLib.idle_add(confirm,msg,event,answer);event.wait()
                p.stdin.write('WIEDERHERSTELLEN\n' if answer else 'ABBRECHEN\n');p.stdin.flush()
                GLib.idle_add(update,tr('Systemdateien werden zurückgesichert …') if answer else tr('Abbrechen …'))
            if msg.get('error'):result=msg['error']
            if msg.get('done'):result=msg['message']
        code=p.wait();p.stdin.close()
        if selected_scope=='migration' and not code:result=tr('Migrationslauf beendet. Den angezeigten Bericht auf ausgelassene Komponenten und Nacharbeiten prüfen.')+'\n'+transcript[-1800:]
        if code:raise ValueError(result or tr('Rücksicherung fehlgeschlagen; möglichen Teilstand prüfen.'))
        if not result:raise ValueError(tr('Kein bestätigtes Abschlussergebnis erhalten.'))
        return result
    def done(text):
        busy['value']=False;resume.set_sensitive(True);close.set_sensitive(True);start.set_sensitive(bool(items));update(text);return False
    def load():
        try:
            rows=backup.call('list')['backups']
            def fill():
                for row in rows:
                    items[row['id']]=row;choice.append(row['id'],backup.snapshot_label(row))
                if rows:
                    choice.set_active(0)
                    if selected_id in items:choice.set_active_id(selected_id)
                start.set_sensitive(bool(rows));update(tr('Systemstand wählen. Das Archivformat wird vor Rücksicherung geprüft.'))
            GLib.idle_add(fill)
        except Exception as exc:GLib.idle_add(update,str(exc))
    def launch(_):
        item=items.get(choice.get_active_id());dest=cache.get_filename();root='/' if scope.get_active_id()=='migration' and running.get_active() else target.get_filename()
        if not item or not dest or not root:update(tr('Stand, externe Arbeitsablage und Ziel auswählen.'));return
        selected_scope=scope.get_active_id();selected_path=selection.get_text().strip().strip('/')
        if item.get('component')=='personal' and selected_scope not in ('home','files','migration'):
            update(tr('Persönlichen Stand nur als Home, Einzeldateien oder persönliche Migration wiederherstellen.'));return
        migration_users=(source_user.get_text().strip(),target_user.get_text().strip())
        try:
            if selected_scope=='migration':
                from system_migration import migration_storage
                dest=migration_storage(dest)
            else:dest=system_recovery.storage(dest)
            if selected_scope=='files':system_components.selected(selected_path,'files',selected_path)
            elif selected_scope=='migration' and root=='/':
                if system_recovery.live():raise ValueError(tr('Live-System darf nicht Migrationsziel sein.'))
            else:system_recovery.restore_target(root,dest)
            if shutil.disk_usage(dest).free<2*int(item['bytes'])+1024**3:raise ValueError(tr('Externe Arbeitsablage benötigt zweimal Archivgröße plus 1 GiB Reserve.'))
        except Exception as exc:update(str(exc));return
        busy['value']=True;resume.set_sensitive(False);start.set_sensitive(False);close.set_sensitive(False)
        def worker():
            try:
                cfg=core.validate(core.load())
                if not cfg['SERVER_URL'].startswith('https://'):raise ValueError(tr('Rücksicherung benötigt HTTPS.'))
                folder=Path(tempfile.mkdtemp(prefix='System-Restore-',dir=dest));(folder/'.hsm-system-restore-work').touch(mode=0o600);path=folder/'system.zip';h=hashlib.sha256();count=0
                with backup.call('download',query=backup.download_query(item),binary=True) as response,path.open('xb') as out:
                    path.chmod(0o600)
                    for part in iter(lambda:response.read(backup.CHUNK),b''):
                        count+=len(part)
                        if count>int(item['bytes']) or shutil.disk_usage(dest).free<len(part)+1024**3:raise ValueError(tr('Downloadgröße oder Speicherreserve überschritten.'))
                        out.write(part);h.update(part)
                        GLib.idle_add(update,tr('Heruntergeladen: ')+str(count//1024**2)+' MiB')
                if count!=int(item['bytes']) or h.hexdigest()!=item['sha256']:raise ValueError(tr('Prüfsumme stimmt nicht. Ziel unverändert.'))
                if selected_scope=='files':
                    from system_files import restore as restore_files
                    message=restore_files(str(path),item['sha256'],str(Path(root)/('Systemdateien-'+item['id'][:12])),dest,selected_path,lambda text:GLib.idle_add(update,text))
                    GLib.idle_add(done,message);return
                GLib.idle_add(update,tr('Archiv und Ziel werden mit Administratorfreigabe geprüft …'))
                command=['pkexec','/usr/bin/python3','/usr/lib/heimserver-manager-client/system_restore.py',str(path),item['sha256'],root,dest,selected_scope]
                if selected_scope=='migration':command=['pkexec','/usr/bin/python3','/usr/lib/heimserver-manager-client/system_migration.py',str(path),item['sha256'],root,dest,*migration_users]
                result=execute(command,selected_scope)
                message=result+tr('\nHeruntergeladenes Archiv bleibt erhalten: ')+str(path)
            except Exception as exc:message=str(exc)
            GLib.idle_add(done,message)
        threading.Thread(target=worker,daemon=True).start()
    def continue_migration(_):
        root='/' if running.get_active() else target.get_filename();stage=prepared.get_text().strip();src_user=source_user.get_text().strip();dst_user=target_user.get_text().strip()
        if not all((root,stage,src_user,dst_user)):update(tr('Arbeitsverzeichnis, Ziel und beide Benutzernamen wählen.'));return
        busy['value']=True;resume.set_sensitive(False);start.set_sensitive(False);close.set_sensitive(False)
        def work():
            try:message=execute(['pkexec','/usr/bin/python3','/usr/lib/heimserver-manager-client/system_migration.py','--resume',stage,root,src_user,dst_user],'migration')
            except Exception as exc:message=str(exc)
            GLib.idle_add(done,message)
        threading.Thread(target=work,daemon=True).start()
    resume.connect('clicked',continue_migration)
    start.connect('clicked',launch);d.connect('delete-event',lambda *_:busy['value'])
    threading.Thread(target=load,daemon=True).start();d.show_all()
    while True:
        d.run()
        if not busy['value']:break
    d.destroy()
