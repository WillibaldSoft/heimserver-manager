"""External backup settings, inventory and persistent job status."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html,secrets
from pathlib import Path
from flask import request,session,redirect
from . import external as e
from . import selection
E=lambda value:html.escape(str(value or ''),quote=True)

def source_summary(paths,details):
    groups={}
    for row in details:
        if not row['exists']:continue
        label=row['label']
        if 'Fotolabor' in label:group='Fotolabor-Rücksicherungen'
        elif label.startswith(('App-','App-Sicherung:')) or label=='backup_root':group='Anwendungsbackups und Snapshots'
        elif label.startswith('Tagesbackup:') or 'Tägliche' in label:group='Tägliche Sicherungskette'
        elif label.startswith('VM-'):group='Virtuelle Maschinen'
        elif label.startswith(('Server-Sicherungen','Client-Sicherungen')):group='Server- und Client-Sicherungen'
        elif label.startswith('Zentrale') or label=='system_backup_root':group='Zentrale Backupablage'
        elif any(x in label for x in ('Rücksicherung','Reparatur','Systemreparaturen')):group='Konfigurationen und Reparaturen'
        else:group='Weitere Sicherungen'
        groups.setdefault(group,[]).append(row)
    body=_ui_html("<div class='card'><h3>Enthaltene Backupordner</h3><p><b>")+str(len(paths))+_ui_html(" Quellordner insgesamt.</b> Alle Unterordner werden mitgesichert; überlappende Ablagen nur einmal. Details bei Bedarf aufklappen.</p>")
    for group,rows in groups.items():
        body+=_ui_html('<details><summary><b>')+E(group)+_ui_html('</b> · ')+str(len(rows))+_ui_html(' Ablagen</summary><ul>')
        body+=''.join(_ui_html('<li>')+E(_ui_text(r['label']))+_ui_html(': <code>')+E(r['path'])+_ui_html('</code></li>') for r in rows[:50])+_ui_html('</ul>')
        if len(rows)>50:body+=_ui_html('<p>Weitere ')+str(len(rows)-50)+_ui_html(' Ablagen dieses Bereichs sind ebenfalls enthalten. Anzeige auf 50 Beispiele begrenzt.</p>')
        body+=_ui_html('</details>')
    absent=[r for r in details if not r['exists']]
    if absent:
        body+=_ui_html('<details><summary>Hinweise zu nicht vorhandenen Ablagen · ')+str(len(absent))+_ui_html('</summary><p>Alte Überwachungspfade und noch nicht angelegte optionale Ordner sind keine bestätigten Backups. Aktuelle Sicherungen können in den Bereichen oben enthalten sein.</p><ul>')
        body+=''.join(_ui_html('<li>')+E(_ui_text(r['label']))+': '+E(r['path'])+' — '+E(_ui_text(r['state']))+_ui_html('</li>') for r in absent[:50])+_ui_html('</ul>')
        if len(absent)>50:body+=_ui_html('<p>')+str(len(absent)-50)+_ui_html(' weitere Hinweise; Anzeige auf 50 begrenzt.</p>')
        body+=_ui_html('</details>')
    return body

def selection_form(conf,token,running):
    options,errors=selection.catalog(conf);selected=selection.chosen(conf,options)
    body=_ui_html("<div class='card'><h3>Backupordner und Freigaben auswählen</h3><p>Häkchen setzen und Auswahl speichern. Größenprüfung und Kopierlauf verwenden ausschließlich die gespeicherte Auswahl. Bestehende Einstellungen übernehmen zunächst alle Backupordner; Freigabedaten sind zunächst abgewählt.</p><form method='post'>")+token+_ui_html("<input type='hidden' name='action' value='selection'><fieldset")+(' disabled' if running else '')+">"
    for group in ('Backupordner','Backupbereich','SMB-Freigabe','NFS-Freigabe'):
        rows=[r for r in options if r['kind']==group]
        if not rows:continue
        body+=_ui_html('<details><summary><b>')+E(group)+_ui_html('</b> · ')+str(len(rows))+_ui_html(' auswählbar</summary>')
        for row in rows:
            checked=row['id'] in selected
            # Previously selected unavailable rows remain deselectable.
            body+=_ui_html("<p><label><input type='checkbox' name='source' value='")+E(row['id'])+"'"+(' checked' if checked else '')+(' disabled' if not row['available'] and not checked else '')+_ui_html("> <b>")+E(_ui_text(row['label']))+_ui_html('</b></label><br><small>')
            body+=E(row['paths'][0]) if len(row['paths'])==1 else str(len(row['paths']))+' Ablagen gemeinsam auswählen'
            if row['reason']:body+=' · '+E(row['reason'])
            body+=_ui_html('</small></p>')
        body+=_ui_html('</details>')
    unknown=selected-{r['id'] for r in options}
    if unknown:body+=_ui_html("<p class='warn'>")+str(len(unknown))+_ui_html(" zuvor ausgewählte Quellen sind nicht mehr verfügbar. Erneutes Speichern entfernt diese veralteten Zuordnungen.</p>")
    for error in errors:body+=_ui_html("<p class='warn'>")+E(_ui_text(error))+_ui_html('</p>')
    body+=_ui_html("<p><button class='btn'>Auswahl speichern</button></p></fieldset></form><p>SMB/NFS: Gesichert wird der lokale Ordnerinhalt, nicht über das Netzwerkprotokoll. Gleiche oder ineinander liegende Ordner werden einmal kopiert. Ein ausgewählter Hauptordner enthält immer alle Unterordner – auch wenn deren einzelne Freigabe nicht angehakt ist. Zum Einschränken den Hauptordner abwählen und die gewünschten Unterordner wählen.</p><p>Freigabedaten können während der Nutzung verändert werden. Schreibzugriffe der Clients für den Kopierlauf beenden; Datenbanken und laufende Anwendungen weiterhin mit ihren Backupfunktionen sichern. Freigaberechte und Einstellungen werden nicht verändert.</p></div>")
    return body

def register(app,ctx):
    from . import external_restore_ui
    external_restore_ui.register(app,ctx)
    @app.before_request
    def protect_external_copy():
        # Avoid changes to backup repositories while a confirmed copy is made.
        if request.method in ('POST','PUT','PATCH','DELETE') and request.path not in ('/login','/logout','/backup/external') and e.active():
            return ctx.page(_ui_text('Externe Sicherung läuft'),_ui_html("<div class='card'><p>Während der externen Gesamtsicherung sind Änderungen im Manager gesperrt. Lesen und Statusabrufe bleiben möglich.</p><a href='/backup/external'>Sicherungsstatus öffnen</a></div>"),'Backup'),409

    @app.route('/backup/external',methods=['GET','POST'])
    def external_backup():
        message='';code=200
        if request.method=='POST':
            if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):return 'Formular abgelaufen. Bitte neu laden.',403
            try:
                if request.form.get('action')=='save':
                    e.save({'uuid':request.form.get('uuid',''),'unmount':request.form.get('unmount')=='1','extra':request.form.get('extra','')})
                elif request.form.get('action')=='selection':selection.save_selection(request.form.getlist('source'))
                elif request.form.get('action')=='measure':e.start_measure()
                elif request.form.get('action')=='start':
                    if request.form.get('confirm')!='1':raise ValueError('Sicherungsumfang bitte bestätigen.')
                    e.start(ctx)
                else:raise ValueError('Unbekannte Aktion.')
                return redirect('/backup/external',303)
            except (ValueError,OSError) as exc:message=str(exc);code=400
        conf=e.settings();info=e.status();running=info.get('state') in ('queued','running')
        token="<input type='hidden' name='auth_csrf' value='"+E(session.setdefault('auth_csrf',secrets.token_urlsafe(32)))+"'>"
        body=_ui_html("<div class='card'><h2>Externe Gesamtsicherung</h2><p>Ausgewählte Backups und lokale SMB-/NFS-Freigabedaten auf eine weitere Festplatte kopieren. Beim ersten Lauf vollständig; danach nur neue oder geänderte Dateien. Unveränderte Dateien teilen sich über Hardlinks den Speicherplatz mit älteren Ständen.</p><p>Jeder datierte Stand enthält die beim Lauf vorhandenen Quellen. Alte externe Stände werden nicht gelöscht. Es werden keine neuen Anwendungs-Backups und kein startfähiges Serverabbild erzeugt.</p><a class='btn' href='/backup'>Backup &amp; Recovery</a> <a class='btn' href='/backup/external'>Aktualisieren</a></div>")
        if message:body+=_ui_html("<div class='card'><p class='err'>")+E(_ui_text(message))+_ui_html('</p></div>')
        size=e.size_status()
        if not size and not running:
            e.start_measure();size=e.size_status()
        body+=_ui_html("<div class='card'><h3>Größe der externen Sicherung</h3>")
        if size.get('state')=='completed' and size.get('config_key')==e.config_key(conf):
            body+=_ui_html('<p><b>Gesamter Datenumfang: ')+E(e.human_size(size.get('total_bytes')))+_ui_html("</b></p><p>Neue/geänderte Dateien für den nächsten Lauf: <b>")+E(e.human_size(size.get('additional_bytes')))+_ui_html("</b></p><p>Freier Zielplatz: ")+E(e.human_size(size.get('free_bytes')))+_ui_html("</p><p>")+E(size.get('target_note'))+_ui_html("</p>")
            if size.get('free_bytes') is not None and size['free_bytes']<size['additional_bytes']+size['reserve_bytes']:body+=_ui_html("<p class='err'>Freier Platz reicht einschließlich Sicherheitsreserve nicht aus.</p>")
            body+=_ui_html('<details><summary>Größe je Quellordner (erste 100; Gesamtgröße umfasst alle)</summary><ul>')+''.join(_ui_html('<li>')+E(r['path'])+': '+E(e.human_size(r['bytes']))+_ui_html('</li>') for r in size.get('rows',[])[:100])+_ui_html('</ul></details>')
            import datetime
            body+=_ui_html('<p>Ermittelt: ')+E(datetime.datetime.fromtimestamp(size['finished']).strftime('%d.%m.%Y %H:%M'))+_ui_html('</p>')
            if size.get('config_key')!=e.config_key(conf):body+=_ui_html("<p class='warn'>Sicherungseinstellungen geändert; Größenprüfung erneut starten.</p>")
        else:body+=_ui_html('<p>')+E(_ui_text('Auswahl geändert: Größe bitte neu ermitteln.') if size.get('state')=='completed' else _ui_text(size.get('message','Noch nicht ermittelt')))+_ui_html('</p>')
        body+=_ui_html("<p>Unveränderte Hardlinks werden je Quellordner einmal gezählt. Die Dateigröße ist nicht die exakte spätere Plattenbelegung: Dateisystem, sparse Dateien und Metadaten können abweichen. Momentaufnahme; vor dem Kopieren wird der Platz erneut geprüft.</p><form method='post'>")+token+_ui_html("<input type='hidden' name='action' value='measure'><button class='btn'")+(' disabled' if running or size.get('state')=='running' else '')+_ui_html(">Größe neu ermitteln (ohne Kopieren)</button></form></div>")
        if info:
            labels={'queued':'Wartet','running':'Läuft','completed':'Abgeschlossen','failed':'Fehlgeschlagen','interrupted':'Unterbrochen'}
            body+=_ui_html("<div class='card'><h3>Letzter Lauf</h3><p><b>")+E(_ui_text(labels.get(info.get('state'),_ui_text(info.get('state')))))+_ui_html("</b> · ")+E(_ui_text(info.get('message')))+_ui_html('</p><p>Ziel: ')+E(info.get('destination',_ui_text('Noch nicht angelegt')))+_ui_html('</p>')
            body+=_ui_html('<p>Datenumfang dieses Laufs: ')+E(e.human_size(info.get('total_bytes')))+_ui_html(' · Neue/geänderte Dateien: ')+E(e.human_size(info.get('estimated_bytes')))+_ui_html('</p>')
            if info.get('unmounted'):body+=_ui_html('<p>Zielfestplatte wurde ausgehängt und kann getrennt werden.</p>')
            if info.get('unmount_error'):body+=_ui_html('<p class="warn">')+E(info['unmount_error'])+_ui_html('</p>')
            if not running:body+=_ui_html('<p>Vor dem Abziehen unter Speicher prüfen, ob die Platte ausgehängt ist.</p>')
            for name in ('copy.log','verify.log'):
                log=e.ROOT/name
                if log.is_file():
                    with log.open('rb') as f:f.seek(max(0,log.stat().st_size-16000));text=f.read().decode(errors='replace')
                    if text:body+=_ui_html('<details><summary>')+E(name)+_ui_html(' (letzte 16 KB)</summary><pre>')+E(text)+_ui_html('</pre></details>')
            body+=_ui_html('</div>')
        options='';seen=False
        try:
            for d in e.devices():
                try:e.select_device(d['uuid'])
                except ValueError:continue
                selected=d['uuid']==conf.get('uuid');seen|=selected
                label=(d['label'] or 'Ohne Label')+' · '+d['device']+' · '+str(round(d['size']/1024**3,1))+' GiB · '+d['fstype']+' · UUID '+d['uuid']+' · '+(', '.join(d['mounts']) or 'nicht eingehängt')
                options+=_ui_html("<option value='")+E(d['uuid'])+"'"+(' selected' if selected else '')+'>'+E(_ui_text(label))+_ui_html('</option>')
        except (ValueError,OSError) as exc:body+=_ui_html("<div class='card'>Datenträgerprüfung: ")+E(_ui_text(exc))+_ui_html('</div>')
        if conf.get('uuid') and not seen:options=_ui_html("<option selected value='")+E(conf['uuid'])+_ui_html("'>Gespeichertes Ziel nicht verfügbar · ")+E(conf['uuid'])+_ui_html('</option>')+options
        disabled=' disabled' if running else ''
        body+=_ui_html("<div class='card'><h3>Zielfestplatte</h3><form method='post'>")+token+"<fieldset"+disabled+_ui_html("><input type='hidden' name='action' value='save'><label>Dateisystem <select name='uuid' required><option value=''>Bitte wählen</option>")+options+_ui_html("</select></label><p>Linux-Dateisystem (ext4, XFS oder Btrfs) für Rechte, ACLs und Hardlinks erforderlich. Keine Formatierung. Die UUID bleibt auch bei geänderter Gerätenummer maßgeblich. Quelle und Ziel dürfen nicht auf demselben Dateisystem liegen.</p><p>Eine nicht eingehängte Platte wird nur für den Lauf unter /mnt/server-manager-external/UUID eingebunden. Kein fstab-Eintrag. Bei bereits eingehängter Platte wird der vorhandene Mount verwendet.</p><label><input type='checkbox' name='unmount' value='1'")+(' checked' if conf.get('unmount',True) else '')+_ui_html("> Nach dem Lauf automatisch aushängen, wenn dieser Auftrag die Platte eingehängt hat</label><details><summary>Weitere Backupordner</summary><p>Für eigene, nicht automatisch erfasste Sicherungen: ein absoluter Ordnerpfad pro Zeile.</p><textarea name='extra' rows='4' style='width:100%'>")+E('\n'.join(conf.get('extra',[])))+_ui_html("</textarea></details><button class='btn'>Ziel speichern</button></fieldset></form></div>")
        body+=selection_form(conf,token,running)
        body+=_ui_html("<div class='card'><h3>Rücksicherung</h3><p>Aus einem abgeschlossenen externen Stand gezielt Backupordner oder Freigabedaten in einen neuen Ordner zurückholen.</p><a class='btn' href='/backup/external/restore'>Sicherungsstand und Inhalte auswählen</a></div>")
        try:
            paths,details=e.inventory_details(conf)
            body+=source_summary(paths,details)
            body+=_ui_html("<p>Der Auftrag läuft unabhängig vom Webdienst, verhindert geplantes Einschlafen und prüft anschließend Inhalte und Rechte. Währenddessen sind Änderungen im Manager gesperrt. Externe Client-Backups und manuelle Änderungen an den Quellordnern vorher beenden. Bereits unvollständige Backups werden durch das Kopieren nicht repariert.</p><p>Die externe Platte enthält sensible Sicherungen mit möglichen Passwörtern und Schlüsseln. Sicher aufbewahren; keine zusätzliche Verschlüsselung durch diesen Kopierlauf. Nicht bestätigte Läufe bleiben als .partial-Ordner erhalten.</p><form method='post'>")+token+_ui_html("<input type='hidden' name='action' value='start'><label><input type='checkbox' name='confirm' value='1' required")+disabled+_ui_html("> Quellen und Ziel geprüft; derzeit schreibt kein anderes Backup-Werkzeug in diese Ordner.</label><p><button class='btn'")+(' disabled' if running or not conf.get('uuid') else '')+_ui_html(">Neue Sicherungen extern übernehmen</button></p></form></div>")
        except (ValueError,OSError) as exc:body+=_ui_html("<div class='card'><p class='err'>")+E(_ui_text(exc))+_ui_html('</p></div>')
        if running or size.get('state')=='running':body+=_ui_html("<script>setTimeout(()=>location.reload(),5000)</script>")
        return ctx.page(_ui_text('Externe Gesamtsicherung'),body,'Backup'),code
