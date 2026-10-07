"""GUI for downloading and restoring an HTTPS system archive from a live system."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,json,shutil,subprocess,tempfile,threading
from pathlib import Path
from gi.repository import Gtk,GLib
import backup,core,system_recovery,system_components

def open_restore(app,parent):
    d=Gtk.Dialog(title=tr('HTTPS-Systemarchiv wiederherstellen'),transient_for=parent);d.set_default_size(720,440)
    close=d.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE);box=d.get_content_area();box.set_spacing(10)
    box.add(Gtk.Label(label=tr('Vorhandenes Linux-Zielsystem separat einhängen. ZIP wird auf eine externe Linux-Platte geladen und vor Änderungen vollständig geprüft. Dafür dort mindestens zweimal Archivgröße frei halten. System/Komponenten nur im Live-System und auf gleicher Plattform; passende Zielpartitionen vorher einhängen. Einzeldateien können im laufenden System in einen neuen Ordner zurückgesichert werden. Partitionierung und Bootloader bleiben manuell.'),wrap=True))
    scope=Gtk.ComboBoxText()
    for key,label in system_components.SCOPES.items():scope.append(key,label)
    scope.set_active_id('all' if system_recovery.live() else 'files');box.add(scope)
    selection=Gtk.Entry();selection.set_placeholder_text(tr('Für Einzeldateien: z. B. home/benutzer/Dokumente'));box.add(selection)
    choice=Gtk.ComboBoxText();box.add(choice);items={};busy={'value':False}
    cache=Gtk.FileChooserButton(title=tr('Externe Arbeitsablage auswählen'),action=Gtk.FileChooserAction.SELECT_FOLDER)
    target=Gtk.FileChooserButton(title=tr('Eingehängtes Linux-Zielsystem auswählen'),action=Gtk.FileChooserAction.SELECT_FOLDER)
    box.add(Gtk.Label(label=tr('Externe Arbeitsablage (nicht das Live- oder Zielsystem)')));box.add(cache)
    box.add(Gtk.Label(label=tr('Linux-Zielsystem; bei Einzeldateien übergeordneten Zielordner wählen')));box.add(target)
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
    def done(text):
        busy['value']=False;close.set_sensitive(True);start.set_sensitive(bool(items));update(text);return False
    def load():
        try:
            rows=backup.call('list')['backups']
            def fill():
                for row in rows:
                    items[row['id']]=row;choice.append(row['id'],row['created']+' · '+row['name'])
                if rows:choice.set_active(0)
                start.set_sensitive(bool(rows));update(tr('Systemstand wählen. Das Archivformat wird vor Rücksicherung geprüft.'))
            GLib.idle_add(fill)
        except Exception as exc:GLib.idle_add(update,str(exc))
    def launch(_):
        item=items.get(choice.get_active_id());dest=cache.get_filename();root=target.get_filename()
        if not item or not dest or not root:update(tr('Stand, externe Arbeitsablage und Ziel auswählen.'));return
        selected_scope=scope.get_active_id();selected_path=selection.get_text().strip().strip('/')
        try:
            dest=system_recovery.storage(dest)
            if selected_scope=='files':system_components.selected(selected_path,'files',selected_path)
            else:system_recovery.restore_target(root,dest)
            if shutil.disk_usage(dest).free<2*int(item['bytes'])+1024**3:raise ValueError(tr('Externe Arbeitsablage benötigt zweimal Archivgröße plus 1 GiB Reserve.'))
        except Exception as exc:update(str(exc));return
        busy['value']=True;start.set_sensitive(False);close.set_sensitive(False)
        def worker():
            try:
                cfg=core.validate(core.load())
                if not cfg['SERVER_URL'].startswith('https://'):raise ValueError(tr('Rücksicherung benötigt HTTPS.'))
                folder=Path(tempfile.mkdtemp(prefix='System-Restore-',dir=dest));path=folder/'system.zip';h=hashlib.sha256();count=0
                with backup.call('download',query='&id='+item['id'],binary=True) as response,path.open('xb') as out:
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
                p=subprocess.Popen(['pkexec','/usr/bin/python3','/usr/lib/heimserver-manager-client/system_restore.py',str(path),item['sha256'],root,dest,selected_scope],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                result=None
                for line in p.stdout:
                    try:msg=json.loads(line)
                    except ValueError:GLib.idle_add(update,line.strip());continue
                    if msg.get('confirm'):
                        event=threading.Event();answer=[];GLib.idle_add(confirm,msg,event,answer);event.wait()
                        p.stdin.write('WIEDERHERSTELLEN\n' if answer else 'ABBRECHEN\n');p.stdin.flush()
                        GLib.idle_add(update,tr('Systemdateien werden zurückgesichert …') if answer else tr('Abbrechen …'))
                    if msg.get('error'):result=msg['error']
                    if msg.get('done'):result=msg['message']
                code=p.wait();p.stdin.close()
                if code:raise ValueError(result or tr('Rücksicherung fehlgeschlagen; möglichen Teilstand prüfen.'))
                if not result:raise ValueError(tr('Kein bestätigtes Abschlussergebnis erhalten.'))
                message=result+tr('\nHeruntergeladenes Archiv bleibt erhalten: ')+str(path)
            except Exception as exc:message=str(exc)
            GLib.idle_add(done,message)
        threading.Thread(target=worker,daemon=True).start()
    start.connect('clicked',launch);d.connect('delete-event',lambda *_:busy['value'])
    threading.Thread(target=load,daemon=True).start();d.show_all()
    while True:
        d.run()
        if not busy['value']:break
    d.destroy()
