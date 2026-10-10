from pathlib import Path
import hashlib,json,subprocess,tempfile
from gi.repository import Gtk,GLib
import core,offline,offline_mounts,offline_smb
from client_i18n import tr
from extras_ui import folder,confirm

def show(app):
    d=Gtk.Dialog(title=tr('Offline-Dateien'),transient_for=app.window);d.set_default_size(700,560);d.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE)
    scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.set_min_content_height(480)
    d.get_content_area().pack_start(scroll,True,True,0)
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);scroll.add(box)
    box.add(Gtk.Label(label=tr('Freigegebene Serverordner als eigene lokale Kopie. Konflikte bleiben auf beiden Geräten erhalten und werden gemeldet. Kein Backup-Ersatz. Maximal 5000 Dateien; keine feste Dateigrößengrenze; keine Links oder leeren Ordner.'),wrap=True))
    box.add(Gtk.Label(label=tr('Mehrere Ordner anhaken; darunter einen einzelnen Ordner bearbeiten.'),wrap=True))
    checks=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3);box.add(checks);marked=set()
    choice=Gtk.ComboBoxText();box.add(choice);items={}
    def rebuild_checks():
        for child in checks.get_children():checks.remove(child)
        for gid,row in items.items():
            b=Gtk.CheckButton(label=row['name']);b.set_active(gid in marked)
            def toggled(widget,key=gid):
                if widget.get_active():marked.add(key)
                else:marked.discard(key)
            b.connect('toggled',toggled);checks.add(b)
        checks.show_all()
    def selected_ids():return [gid for gid in items if gid in marked]

    box.add(Gtk.Label(label=tr('Bestehender Netzwerk-Mount (optional, nur Zuordnung)'),wrap=True))
    mount_choice=Gtk.ComboBoxText();box.add(mount_choice);mount_rows={};refreshing_mounts=False
    box.add(Gtk.Label(label=tr('Lesen über HTTPS; mit zusätzlicher SMB-Anmeldung auch Zurückschreiben. Die Offline-Kopie liegt außerhalb des Netzwerk-Mounts.'),wrap=True))
    def refresh_mounts(saved=None):
        nonlocal refreshing_mounts
        refreshing_mounts=True
        mount_choice.remove_all();mount_rows.clear();mount_choice.append('',tr('Keine Mount-Zuordnung'))
        try:found=offline_mounts.discover()
        except OSError as exc:app.message(str(exc),True);found=[]
        if saved and not any(r['target']==saved['target'] for r in found):found.append(dict(saved,active=False))
        for row in found:
            mount_rows[row['target']]=row
            mount_choice.append(row['target'],row['target']+' ← '+row['source']+('' if row.get('active') else ' ('+tr('nicht eingehängt')+')'))
        mount_choice.set_active_id(saved['target'] if saved else '')
        refreshing_mounts=False
    path=Gtk.Entry();path.set_placeholder_text(tr('Eigener lokaler Offline-Ordner'));box.add(path)
    def mount_selected(*_):
        if refreshing_mounts:return
        mount=mount_rows.get(mount_choice.get_active_id())
        if not mount:return
        try:
            destination=offline_mounts.suggested_destination(choice.get_active_id() or '', '',source_mount=mount)
            path.set_text(str(destination))
        except (OSError,ValueError) as exc:app.message(str(exc),True)
    mount_choice.connect('changed',mount_selected)
    write=Gtk.CheckButton(label=tr('Beide Richtungen synchronisieren'));box.add(write)
    startup=Gtk.CheckButton(label=tr('Bei Benutzeranmeldung / Client-Start synchronisieren'));box.add(startup)
    shutdown=Gtk.CheckButton(label=tr('Vor dem Ausschalten synchronisieren (Server offline: sofort ausschalten)'));box.add(shutdown)
    box.add(Gtk.Label(label=tr('Ausschalt-Abgleich: maximal 60 Sekunden, begrenzt durch die Wartezeit des Betriebssystems. Der Server wird dabei nicht geweckt. Einstellungen bleiben jederzeit änderbar.'),wrap=True))
    def smb_login(forget=False):
        gid=choice.get_active_id();meta=items.get(gid,{}).get('smb')
        if not meta:app.message(tr('Für diesen Ordner ist kein SMB-Schreibzugriff freigegeben.'),True);return
        if forget:
            try:offline_smb.password(meta,forget=True);write.set_active(False)
            except Exception as exc:app.message(str(exc),True)
            return
        dialog=Gtk.Dialog(title=tr('SMB-Anmeldung für beide Richtungen'),transient_for=d)
        dialog.add_buttons(tr('Abbrechen'),Gtk.ResponseType.CANCEL,tr('Prüfen und speichern'),Gtk.ResponseType.OK)
        area=dialog.get_content_area();area.add(Gtk.Label(label=meta['user']+' · '+meta['share']))
        area.add(Gtk.Label(label=tr('Passwort nur im lokalen Schlüsselbund speichern. Lesen erfolgt über HTTPS, Zurückschreiben über SMB.'),wrap=True))
        entry=Gtk.Entry();entry.set_visibility(False);entry.set_input_purpose(Gtk.InputPurpose.PASSWORD);area.add(entry);dialog.show_all()
        accepted=dialog.run()==Gtk.ResponseType.OK;secret=entry.get_text();entry.set_text('');dialog.destroy()
        if not accepted:return
        def task():
            offline_smb.Writer(meta,secret=secret);offline_smb.password(meta,secret)
            GLib.idle_add(write.set_active,True);return tr('SMB-Anmeldung gespeichert. Einstellungen mit Speichern übernehmen.')
        app.run_action(task)
    for label,fn in [('SMB-Anmeldung einrichten / ändern',lambda:smb_login()),('SMB-Anmeldung entfernen',lambda:smb_login(True))]:
        b=Gtk.Button(label=tr(label));b.connect('clicked',lambda _,f=fn:f());box.add(b)
    delete=Gtk.CheckButton(label=tr('Löschungen übernehmen (mit Rückholablage)'));box.add(delete)
    wake=Gtk.CheckButton(label=tr('Server vor dem Abgleich wecken'));box.add(wake)
    box.add(Gtk.Label(label=tr('Intervall in Minuten: 0 = nur manuell. Automatik läuft bei geöffnetem Client / Statussymbol.'),wrap=True))
    interval=Gtk.SpinButton.new_with_range(0,1440,5);box.add(interval)
    box.add(Gtk.Label(label=tr('Lokales Speicherlimit einschließlich Rückholablage (GiB)')))
    limit=Gtk.SpinButton.new_with_range(1,10000,1);limit.set_value(10);box.add(limit)
    box.add(Gtk.Label(label=tr('Ausschließen: relative Dateien / Ordner, durch Komma getrennt')))
    exclude=Gtk.Entry();box.add(exclude)
    status=Gtk.Label(wrap=True);box.add(status)
    automatic=Gtk.Label(wrap=True);box.add(automatic)
    def automatic_status():
        import offline_lifecycle
        monitor=getattr(app,'offline_lifecycle',None)
        text=(monitor.error or tr('Verfügbare Ausschalt-Wartezeit (Sekunden): ')+str(int(monitor.seconds))) if monitor else ''
        try:
            last=json.loads(offline_lifecycle.STATUS.read_text())
            text+='\n'+tr('Letzter automatischer Abgleich: ')+last.get('time','')+' · '+tr({'pending':'Ausstehend','running':'Läuft','ok':'Abgeschlossen','offline':'Server offline'}.get(last.get('status'),last.get('status','')))+'\n'+last.get('detail','')
        except (OSError,ValueError):pass
        automatic.set_text(text)
    automatic_status()
    def selected(*_):
        gid=choice.get_active_id();old=next((r for r in offline.config() if r['id']==gid),{})
        refresh_mounts(old.get('source_mount'))
        path.set_text(old.get('local',str(Path.home()/'Offline-Dateien'/hashlib.sha256(gid.encode()).hexdigest()[:16]) if gid else ''))
        for widget,key in ((write,'write'),(delete,'delete'),(wake,'wake'),(startup,'sync_startup'),(shutdown,'sync_shutdown')):widget.set_active(old.get(key,False))
        exclude.set_text(old.get('exclude',''))
        write.set_sensitive(bool(items.get(gid,{}).get('write') or items.get(gid,{}).get('smb')));interval.set_value(old.get('interval',0));limit.set_value(old.get('limit_gib',10))
    choice.connect('changed',selected)
    def load():
        def work():
            rows=offline.call('list')['folders']
            roots={r['id']:r for r in rows}
            rows += [dict(v,name=v.get('name',v['id']),write=roots.get(v['id'].split('.',1)[0],{}).get('write',False),smb=roots.get(v['id'].split('.',1)[0],{}).get('smb')) for v in offline.config() if v['id'] not in roots]
            def done():
                choice.remove_all();items.clear()
                for r in rows:items[r['id']]=r;choice.append(r['id'],r['name'])
                rebuild_checks()
                if rows:choice.set_active(0)
                status.set_text(tr('Keine Ordner freigegeben.') if not rows else tr('Freigaben geladen.'))
            GLib.idle_add(done);return tr('Freigaben geladen.')
        app.run_action(work)
    def prepare_local(value):
        p=offline_mounts.validate_local(value,mount_rows.get(mount_choice.get_active_id()))
        if p==Path.home() or len(p.parts)<3:raise core.Error(tr('Eigenen Unterordner auswählen.'))
        try:
            p.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryFile(dir=p):pass
        except PermissionError:
            if not confirm(app,tr('Lokalen Offline-Ordner mit Administratorfreigabe anlegen oder übernehmen? Nur dieser Ordner erhält deinen Benutzer als Eigentümer und Schreibrechte; enthaltene Dateien bleiben unverändert.')+'\n'+str(p)):
                raise core.Error(tr('Vorgang abgebrochen.'))
            result=subprocess.run(['/usr/bin/pkexec','/usr/bin/python3','/usr/lib/heimserver-manager-client/offline_mount_admin.py','prepare-folder',str(p),str(p)],capture_output=True,text=True)
            if result.returncode:raise core.Error(result.stderr.strip() or tr('Vorgang abgebrochen.'))
            with tempfile.TemporaryFile(dir=p):pass
        return p
    def create_local():
        try:
            p=prepare_local(path.get_text());path.set_text(str(p));status.set_text(tr('Lokaler Offline-Ordner ist bereit.'))
        except Exception as exc:app.message(str(exc),True)
    create_button=Gtk.Button(label=tr('Lokalen Ordner anlegen / übernehmen'))
    create_button.connect('clicked',lambda _:create_local());box.add(create_button)
    def save():
        gid=choice.get_active_id()
        if not gid:raise core.Error(tr('Zuerst eine Freigabe auswählen.'))
        source_mount=mount_rows.get(mount_choice.get_active_id())
        p=offline_mounts.validate_local(path.get_text(),source_mount)
        if p==Path.home() or len(p.parts)<3:raise core.Error(tr('Eigenen Unterordner auswählen.'))
        rows=offline.config()
        for r in rows:
            other=Path(r['local'])
            if r['id']!=gid and (p==other or p in other.parents or other in p.parents):raise core.Error('Overlapping local folders')
        prepare_local(str(p));offline.local_scan(p,[x.strip().strip('/') for x in exclude.get_text().split(',') if x.strip()])
        row=dict(id=gid,name=items[gid]['name'],local=str(p),write=bool(write.get_active() and (items[gid].get('write') or items[gid].get('smb'))),sync_startup=startup.get_active(),sync_shutdown=shutdown.get_active(),delete=delete.get_active(),wake=wake.get_active(),interval=interval.get_value_as_int(),limit_gib=limit.get_value_as_int(),exclude=exclude.get_text())
        if source_mount:row['source_mount']=source_mount
        offline.save_config([r for r in rows if r['id']!=gid]+[row]);return row
    def store():
        try:
            save();status.set_text(tr('Gespeichert.'))
            if getattr(app,'offline_lifecycle',None):app.offline_lifecycle.tick()
            automatic_status()
        except Exception as e:app.message(str(e),True)
    def start():
        try:row=save()
        except Exception as e:app.message(str(e),True);return
        def work():
            result=offline.sync(row,lambda value:GLib.idle_add(status.set_text,value))
            GLib.idle_add(status.set_text,result);return result
        app.run_action(work)
    def browse_server():
        gid=choice.get_active_id()
        if not gid:app.message(tr('Zuerst eine Freigabe auswählen.'));return
        browser=Gtk.Dialog(title=tr('Server-Unterordner auswählen'),transient_for=d)
        browser.set_default_size(600,400);browser.add_button(tr('Schließen'),Gtk.ResponseType.CLOSE)
        area=browser.get_content_area();label=Gtk.Label(wrap=True);area.add(label)
        folders=Gtk.ComboBoxText();area.add(folders);state={};alive=[True]
        def load_folder(target):
            def work():
                data=offline.call('browse',target)
                def done():
                    if not alive[0]:return
                    state.clear();state.update(data);folders.remove_all()
                    for row in data['folders']:folders.append(row['id'],row['name'])
                    if data['folders']:folders.set_active(0)
                    label.set_text(data.get('current_name') or items[gid]['name'])
                GLib.idle_add(done);return tr('Unterordner geladen.')
            app.run_action(work)
        def open_child():
            target=folders.get_active_id()
            if target:load_folder(target)
        def choose_current():
            target=state.get('current')
            if not target:return
            name=state.get('current_name') or items[gid]['name']
            if target not in items:
                items[target]=dict(id=target,name=name,write=items[gid].get('write',False),smb=items[gid].get('smb'));choice.append(target,name)
            marked.add(target);rebuild_checks();choice.set_active_id(target)
        for title,fn in [('Öffnen',open_child),('Eine Ebene höher',lambda:load_folder(state['parent']) if state.get('parent') else None),('Diesen Ordner zur Auswahl hinzufügen',choose_current)]:
            button=Gtk.Button(label=tr(title));button.connect('clicked',lambda _,f=fn:f());area.add(button)
        browser.show_all();load_folder(gid);browser.run();alive[0]=False;browser.destroy()
    browse_button=Gtk.Button(label=tr('Server-Unterordner auswählen'))
    browse_button.connect('clicked',lambda _:browse_server());box.add(browse_button)
    def include_all_server_folders():
        gid=choice.get_active_id()
        if not gid:app.message(tr('Zuerst eine Freigabe auswählen.'));return
        root=gid.split('.',1)[0]
        if root not in items:app.message(tr('Freigaben zuerst neu laden.'),True);return
        message=tr('Den gesamten freigegebenen Serverordner einschließlich aller lesbaren Unterordner auswählen und Ausschlüsse entfernen? Vorhandene lokale Dateien bleiben erhalten. Anschließend Einstellungen prüfen und speichern; die Synchronisation startet nicht automatisch.')
        if not confirm(app,message):return
        choice.set_active_id(root)
        exclude.set_text('')
        marked.difference_update([key for key in marked if key.split('.',1)[0]==root])
        marked.add(root);rebuild_checks()
        status.set_text(tr('Gesamter Serverordner mit allen Unterordnern ausgewählt. Zielpfad prüfen und Speichern wählen. Rechte, Speicherlimit und Dateigrenzen gelten weiterhin.'))
    all_button=Gtk.Button(label=tr('Alle Server-Unterordner aufnehmen'))
    all_button.connect('clicked',lambda _:include_all_server_folders());box.add(all_button)
    def setup_many():
        ids=selected_ids()
        if not ids:app.message(tr('Mindestens einen Ordner anhaken.'));return
        destination=folder(d,tr('Gemeinsamen lokalen Basisordner auswählen'))
        if not destination:return
        try:
            prepare_local(destination);offline.configure_many(list(items.values()),ids,destination);selected()
            status.set_text(tr('Ordner eingerichtet. Bestehende Einstellungen bleiben erhalten; neue Ordner starten nur lesend und manuell.'))
        except Exception as exc:app.message(str(exc),True)
    def start_many():
        ids=selected_ids()
        def work():
            result=offline.sync_many(ids,lambda value:GLib.idle_add(status.set_text,value))
            GLib.idle_add(status.set_text,result);return result
        app.run_action(work)
    for label,fn in [(tr('Ausgewählte Ordner einrichten'),setup_many),(tr('Ausgewählte Ordner synchronisieren'),start_many)]:
        b=Gtk.Button(label=label);b.connect('clicked',lambda _,f=fn:f());box.add(b)
    def choose():
        p=folder(d,tr('Eigener lokaler Offline-Ordner'))
        if p:path.set_text(p)
    def replace_mount(restore=False,confirmed=False):
        try:
            row=next((r for r in offline.config() if r['id']==choice.get_active_id()),{}) if restore else save()
            mount=row.get('source_mount')
            if not mount:raise core.Error(tr('Zuerst einen vorhandenen Netzwerk-Mount zuordnen.'))
        except Exception as exc:app.message(str(exc),True);return
        message=(tr('Netzwerk-Mount wiederherstellen? Die Offline-Kopie bleibt erhalten.') if restore else tr('Nach erfolgreichem Abgleich den Netzwerk-Mount durch die lokale Offline-Kopie ersetzen? Der bisherige Pfad zeigt anschließend auf lokale Dateien. Konfiguration und Dienstzustand werden gesichert. Administratorfreigabe erforderlich.'))
        if not confirmed and not confirm(app,message+'\n'+mount['target']+' → '+row['local']):return
        def work():
            if not restore:offline.sync(dict(row,_require_clean=True))
            result=subprocess.run(['/usr/bin/pkexec','/usr/bin/python3','/usr/lib/heimserver-manager-client/offline_mount_admin.py','restore' if restore else 'replace',mount['target'],row['local']],capture_output=True,text=True)
            if result.returncode:raise core.Error(result.stderr.strip() or tr('Vorgang abgebrochen.'))
            return tr('Mount-Zuordnung geändert. Lokale Dateien bleiben erhalten.')
        app.run_action(work)
    def adopt_mount():
        gid=choice.get_active_id();mount=mount_rows.get(mount_choice.get_active_id())
        try:
            if not gid:raise core.Error(tr('Zuerst eine Freigabe auswählen.'))
            if not mount:raise core.Error(tr('Zuerst einen vorhandenen Netzwerk-Mount zuordnen.'))
            old=next((r for r in offline.config() if r['id']==gid),{})
            destination=offline_mounts.suggested_destination(gid,items[gid]['name'],path.get_text().strip() or old.get('local'),mount)
        except Exception as exc:app.message(str(exc),True);return
        message=tr('Mount-Pfad für Offline-Dateien übernehmen?')+'\n\n'+tr('Gewohnter Zugriffspfad: ')+mount['target']+'\n'+tr('Lokaler Speicherordner: ')+str(destination)+'\n\n'+tr('Zuerst wird synchronisiert. Danach wird der Netzwerk-Mount mit Administratorfreigabe durch die lokale Kopie ersetzt. Der Rückwechsel bleibt möglich.')
        if not confirm(app,message):return
        path.set_text(str(destination));replace_mount(False,confirmed=True)
    for label,action in [('Mount-Pfad für Offline-Dateien übernehmen …',adopt_mount),('Netzwerk-Mount wiederherstellen …',lambda:replace_mount(True))]:
        button=Gtk.Button(label=tr(label));button.connect('clicked',lambda _,f=action:f());box.add(button)
    def remove():
        if confirm(app,tr('Abgleich entfernen? Lokale Dateien bleiben erhalten.')):
            offline.save_config([r for r in offline.config() if r['id']!=choice.get_active_id()]);selected()
    for label,fn in [(tr('Freigaben laden'),load),(tr('Ordner auswählen'),choose),(tr('Speichern'),store),(tr('Jetzt synchronisieren'),start),(tr('Abgleich entfernen'),remove)]:
        b=Gtk.Button(label=label);b.connect('clicked',lambda _,f=fn:f());box.add(b)
    for row in offline.config():
        items[row['id']]=dict(row,name=row.get('name',row['id']));choice.append(row['id'],row.get('name',row['id']))
    refresh_mounts()
    rebuild_checks()
    if items:choice.set_active(0)
    d.show_all();load();d.run();d.destroy()

def tick(app):
    if not app.busy and not getattr(getattr(app,'offline_lifecycle',None),'running',False) and not getattr(getattr(app,'offline_lifecycle',None),'shutting',False):
        try:
            row=offline.due()
            if row:app.run_action(lambda:offline.sync(row))
        except Exception:pass
    return True
