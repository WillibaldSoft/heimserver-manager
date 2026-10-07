"""German Manager web interface; all mutations POST, CSRF protected, background jobs."""
from ui_translation import html_literal as _ui_html, text as _ui_text
from server_settings import get as host_setting
import json
from pathlib import Path
import secrets
import shlex
from flask import request,redirect,session,jsonify,Response,send_file
from . import backend,blocker_provider,backup
from .service import Service

LABELS={'rescue-export':'Systemfestplatte für Rescuezilla exportieren','rescue-detach':'Rescuezilla-Sicherungsmedium aushängen','schedule-shutdown-all':'Schlaf & Wake: VMs herunterfahren','backup':'VM sichern','restore-backup':'VM wiederherstellen','schedule-shutdown':'Schlaf & Wake: Herunterfahren','create':'VM erstellen / importieren','start':'Starten','shutdown':'Herunterfahren','reboot':'Neustarten',
'suspend':'Pausieren','resume':'Fortsetzen','destroy':'Hart ausschalten','autostart-on':'Autostart aktivieren',
'autostart-off':'Autostart deaktivieren','resources':'Ressourcen ändern','eject':'ISO auswerfen',
'undefine':'Definition entfernen','clone':'VM klonen','export':'Disk exportieren'}
JOB_STATES={'uploading':'Upload läuft','queued':'Wartet','running':'Läuft','completed':'Abgeschlossen','failed':'Fehlgeschlagen','interrupted':'Unterbrochen'}
STYLE="""<style>.kvm-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}.kvm-stat{font-size:1.8em;font-weight:700}.kvm-form label{display:block;margin:12px 0 4px}.kvm-form input,.kvm-form select{box-sizing:border-box;width:100%;max-width:650px;padding:9px}.kvm-form input:not([type=checkbox]),.kvm-form select{display:block;margin-top:5px;background:#101925;color:#e5e7eb;border:1px solid #526075;border-radius:7px}.kvm-form input[type=checkbox]{width:auto}.kvm-form input:focus,.kvm-form select:focus{outline:2px solid #77b6ec;outline-offset:1px}.kvm-actions{display:flex;gap:8px;flex-wrap:wrap}.kvm-actions form{margin:0}.kvm-muted{opacity:.75} .kvm-table{overflow-x:auto} .kvm-danger{border:1px solid #ad5252;padding:14px;border-radius:10px} .kvm-form button{margin-top:12px} .kvm-status{font-weight:600}</style>"""


def register(app,ctx):
    service=Service(ctx);app.extensions['kvm_manager']=service;blocker_provider._SERVICE=service
    e=lambda value:ctx.esc(str(value if value is not None else ''))
    def csrf():
        if 'kvm_csrf' not in session:session['kvm_csrf']=secrets.token_urlsafe(32)
        return "<input type='hidden' name='csrf' value='"+e(session['kvm_csrf'])+"'>"
    def protected():
        return bool(request.form.get('csrf') and secrets.compare_digest(request.form['csrf'],session.get('kvm_csrf','')))
    def page(title,body):
        nav=_ui_html("<div class='card'><div class='kvm-actions'><a class='btn' href='/kvm'>Virtuelle Maschinen</a><a class='btn' href='/kvm/new'>Neue VM / Import</a><a class='btn' href='/kvm/backups'>Backup & Wiederherstellung</a><a class='btn' href='/kvm/jobs'>Aufträge</a><a class='btn' href='/kvm/help'>Hilfe & Diagnose</a></div></div>")
        return ctx.page(title,STYLE+nav+body,'KVM Verwaltung')
    def error(exc,status=400):return page(_ui_text('KVM Verwaltung'),_ui_html("<div class='card'><h2>Aktion nicht möglich</h2><p class='err'>")+e(_ui_text(exc))+_ui_html("</p><p><a href='javascript:history.back()'>Zurück zur Eingabe</a></p></div>")),status
    from . import backup_ui
    backup_ui.register(app,service,csrf,page,error,e)
    def form(uid,action,label=None,extra='',danger=False):
        confirm=" onsubmit=\"return confirm('Aktion wirklich ausführen?')\"" if action in ('shutdown','reboot','destroy','undefine') else ''
        return f'{_ui_html("<form class='kvm-form' method='post' action='/kvm/vm/")}{e(uid)}{_ui_html("/action'")}{confirm}{_ui_html('>')}{csrf()}{_ui_html("<input type='hidden' name='action' value='")}{e(action)}{_ui_html("'>")}{extra}{_ui_html("<button class='btn' type='submit'>")}{e(_ui_text(label) or _ui_text(LABELS[action]))}{_ui_html('</button></form>')}'
    def field(label,key,value='',kind='text',attrs=''):
        return f'{_ui_html('<label>')}{e(_ui_text(label))}{_ui_html("<input type='")}{kind}{_ui_html("' name='")}{e(key)}{_ui_html("' value='")}{e(value)}{_ui_html("' ")}{attrs}{_ui_html('></label>')}'
    def sleep_form(uid):
        from .sleep_control import MODES
        mode=service.sleep_mode(uid)
        options=''.join(f'{_ui_html("<option value='")}{key}{_ui_html("' ")}{('selected' if key == mode else '')}{_ui_html('>')}{e(_ui_text(label))}{_ui_html('</option>')}' for key,label in MODES.items())
        return f'{_ui_html("<form class='kvm-form' method='post' action='/kvm/vm/")}{e(uid)}{_ui_html("/sleep-policy'>")}{csrf()}{_ui_html("<label>Schlafsteuerung<select name='mode'>")}{options}{_ui_html("</select></label><button class='btn'>Speichern</button></form>")}'
    @app.route('/kvm/vm/<uid>/sleep-policy',methods=['POST'])
    def kvm_sleep_policy(uid):
        if not protected():return error('Formular abgelaufen. Bitte neu laden.',403)
        try:service.set_sleep_mode(uid,request.form.get('mode',''))
        except Exception as exc:return error(exc)
        return redirect('/kvm/vm/'+backend.domain_id(uid),303)
    @app.route('/kvm',strict_slashes=False)
    def kvm_index():
        try:data=backend.inventory()
        except Exception as exc:return error(exc,503)
        rows=data['vms'];running=sum(r['active'] for r in rows)
        body=_ui_html("<div class='card'><h2>KVM Verwaltung</h2><p>VMs auf diesem Server · qemu:///system</p><div class='kvm-grid'>")
        for title,value in [('Virtuelle Maschinen',len(rows)),('Aktiv',running),('Host-RAM',f"{data['host']['ram']/1024:.1f} GiB"),('Frei unter /VM',f"{data['free_gib']} GiB")]:
            body+=f'{_ui_html("<div><div class='kvm-stat'>")}{e(value)}{_ui_html('</div><div>')}{e(_ui_text(title))}{_ui_html('</div></div>')}'
        body+=_ui_html("</div><p class='kvm-muted'>Die Schlafsteuerung ist pro VM wählbar. Laufende KVM-Aufträge verhindern weiterhin den Server-Schlaf.</p></div>")
        body+=_ui_html("<div class='card'><label>VM suchen <input id='vm-search' type='search' placeholder='Name oder Zustand …'></label> <a class='btn' href='/kvm'>Aktualisieren</a><div class='kvm-table'><table><thead><tr><th>VM</th><th>Status</th><th>Ressourcen</th><th>Netzwerk</th><th>Autostart</th><th>Schlaf & Wake</th><th>Aktionen</th></tr></thead><tbody>")
        for row in rows:
            uid=row['uuid'];network=' · '.join('/'.join(n['source'].values()) for n in row['networks'])
            body+=f'{_ui_html("<tr class='vm-row'><td><a href='/kvm/vm/")}{uid}{_ui_html("'><b>")}{e(row['name'])}{_ui_html('</b></a><br><small>')}{e(row['firmware'])}{_ui_html("</small></td><td class='kvm-status'>")}{e(_ui_text(row['state_label']))}{_ui_html('</td><td>')}{row['cpus']}{_ui_html(' vCPU · ')}{row['ram']}{_ui_html(' MiB</td><td>')}{e(network)}{_ui_html('</td><td>')}{(_ui_text('Ja') if row['autostart'] else _ui_text('Nein'))}{_ui_html('</td><td>')}{sleep_form(uid)}{_ui_html("</td><td><div class='kvm-actions'>")}'
            if row['state']==5:body+=form(uid,'start')
            elif row['state'] in (1,2):body+=form(uid,'shutdown')
            elif row['state']==3:body+=form(uid,'resume')
            body+=f'{_ui_html("<a class='btn' href='/kvm/vm/")}{uid}{_ui_html("'>Details</a></div></td></tr>")}'
        if not rows:body+=_ui_html("<tr><td colspan='7'>Noch keine virtuellen Maschinen vorhanden.</td></tr>")
        body+=_ui_html("</tbody></table></div><p id='vm-updated'></p></div><script>document.querySelector('#vm-search').addEventListener('input',ev=>{let q=ev.target.value.toLocaleLowerCase();document.querySelectorAll('.vm-row').forEach(r=>r.hidden=!r.textContent.toLocaleLowerCase().includes(q))});document.querySelector('#vm-updated').textContent='Stand: '+new Date().toLocaleTimeString('de-DE');</script>")
        jobs=service.active()
        if jobs:body+=_ui_html("<div class='card'><p>Ein Auftrag läuft. <a href='/kvm/jobs'>Fortschritt und Protokoll öffnen</a></p></div>")
        return page(_ui_text('KVM Verwaltung'),body)
    def rescuezilla_instructions():
        return _ui_html("""<div class='card'><h3>Rescuezilla: Wiederherstellung abschließen</h3><ol><li>VM starten und über virt-viewer die Konsole öffnen. Rescuezilla von der eingelegten ISO starten.</li><li>Im Terminal <b>innerhalb der VM</b> ausführen:<pre>sudo mkdir -p /mnt/backup
sudo mount -t squashfs -o ro /dev/disk/by-id/virtio-rescuezilla-backup /mnt/backup</pre></li><li>In Rescuezilla „Wiederherstellen“ wählen. Den Sicherungsordner unter /mnt/backup auswählen (Dateisystem / bereits eingehängten Ordner verwenden). Dort liegt eine vollständige Kopie des gewählten Ordners.</li><li>Als Ziel ausschließlich die neue, beschreibbare virtuelle Festplatte wählen. Das zusätzliche Sicherungslaufwerk ist schreibgeschützt. Vor dem Wiederherstellen die Rescuezilla-Abbildprüfung verwenden.</li><li>Nach erfolgreicher Wiederherstellung die VM herunterfahren, unten die Installations-ISO auswerfen und wieder starten.</li></ol><p>„Auftrag abgeschlossen“ bedeutet nur: VM und Sicherungsmedium vorbereitet. Es bestätigt keine Wiederherstellung oder Bootfähigkeit. Die Sicherungskopie bleibt als schreibgeschütztes Laufwerk erhalten und benötigt zusätzlichen Speicher. Vor parallelem Betrieb mit dem Original feste IP, Hostname und Dienste im Gast prüfen. Hardwareabhängige Treiber und Bootreparaturen können erforderlich sein.</p></div>""")
    @app.route('/kvm/vm/<uid>')
    def kvm_detail(uid):
        try:row=backend.detail(uid)
        except Exception as exc:return error(exc,404)
        uid=row['uuid'];off=row['state']==5
        body=f'{_ui_html("<div class='card'><h2>")}{e(row['name'])}{_ui_html('</h2><p><b>')}{e(_ui_text(row['state_label']))}{_ui_html('</b> · ')}{row['cpus']}{_ui_html(' vCPU · ')}{row['ram']}{_ui_html(' MiB RAM · ')}{e(row['firmware'])}{_ui_html("</p><p class='kvm-muted'>UUID: ")}{uid}{_ui_html("</p><div class='kvm-actions'>")}'
        actions={5:['start'],1:['shutdown','reboot','suspend'],2:['shutdown','reboot','suspend'],3:['resume']}.get(row['state'],[])
        for action in actions:body+=form(uid,action)
        if row['persistent']:body+=form(uid,'autostart-off' if row['autostart'] else 'autostart-on')
        body+=_ui_html("</div><p>Herunterfahren und Neustart senden eine Anfrage an das Gastbetriebssystem. Der Zustandswechsel kann etwas dauern.</p></div>")
        if any(d['readonly'] and d['path'].endswith('/rescuezilla-backup.squashfs') for d in row['disks']):
            body+=rescuezilla_instructions()
            if off:body+=_ui_html("<div class='card'><p>Nach erfolgreicher Wiederherstellung kann das Sicherungsmedium aus der VM gelöst werden. Die zusätzliche Datei bleibt auf dem Server erhalten. Danach sind normale VM-Backups wieder möglich.</p>")+form(uid,'rescue-detach')+_ui_html("</div>")
        body+=_ui_html("<div class='card'><h3>Schlaf & Wake</h3>")+sleep_form(uid)+_ui_html("<p>Server wach halten: aktive und pausierte VM blockiert. Durch Schlaf & Wake herunterfahren: etwa fünf Minuten vor der fälligen Suspend-, Hibernate- oder Aus-Aktion regulär herunterfahren. Nachlaufzeit und andere Blocker werden berücksichtigt. Bei manueller Aktion im Manager beginnt das Herunterfahren sofort. Alle ausgewählten VMs erhalten ihre Anfrage ohne Abwarten anderer Gäste; der Server wartet, bis sie aus sind. Andere Blocker und der Testbetrieb bleiben berücksichtigt. Kein hartes Ausschalten; pausierte VMs vorher fortsetzen.</p><p>Keinen Blocker melden: diese VM hält den Host nicht wach und erhält keine Herunterfahr-Anfrage von diesem Modul. Der Host darf dann mit aktiver VM schlafen oder ausschalten.</p><p>Automatisches Starten nach Host-Neustart bleibt über den separaten libvirt-Autostart steuerbar. Nach Suspend werden heruntergefahrene VMs nicht automatisch gestartet.</p><a class='btn' href='/sleep/schedules'>Zeitpläne öffnen</a></div>")
        body+=_ui_html("<div class='kvm-grid'><div class='card'><h3>Netzwerk</h3>")
        for n in row['networks']:body+=f'{_ui_html('<p>')}{e(n['type'])}{': '}{e(' / '.join(n['source'].values()))}{_ui_html('<br>MAC: <code>')}{e(n['mac'])}{_ui_html('</code></p>')}'
        body+=f'{_ui_html('<p>IP: ')}{e(', '.join(row['addresses']) or _ui_text('Nicht gemeldet'))}{_ui_html("</p><p class='kvm-muted'>")}{e(_ui_text(row['address_note']))}{_ui_html("</p></div><div class='card'><h3>Konsole</h3><p>Auf deinem Linux-Rechner mit installiertem virt-viewer:</p>")}'
        body+=f'{_ui_html('<pre>virt-viewer --connect qemu+ssh://')}{e(host_setting('kvm_ssh_user'))}{_ui_html('@')}{e(host_setting('kvm_ssh_host'))}{'/system '}{shlex.quote(uid)}{_ui_html("</pre><p>Die Verbindung nutzt SSH. Grafikports müssen nicht im Netzwerk geöffnet werden.</p><a class='btn' href='/kvm/vm/")}{uid}{_ui_html("/xml'>VM-Definition herunterladen</a></div></div>")}'
        body+=_ui_html("<div class='card'><h3>Laufwerke</h3><div class='kvm-table'><table><tr><th>Ziel</th><th>Typ</th><th>Datei / Quelle</th><th>Aktion</th></tr>")
        for d in row['disks']:
            body+=f'{_ui_html('<tr><td>')}{e(d['target'])}{_ui_html('</td><td>')}{e(d['device'])}{_ui_html(' · ')}{e(d['format'])}{_ui_html('</td><td><code>')}{e(d['path'] or 'Leer')}{_ui_html('</code></td><td>')}'
            if off and d['device']=='cdrom' and d['path']:body+=form(uid,'eject',extra=f'{_ui_html("<input type='hidden' name='target' value='")}{e(d['target'])}{_ui_html("'>")}')
            body+=_ui_html('</td></tr>')
        body+=_ui_html('</table></div></div>')
        body+=_ui_html("<div class='card'><h3>Systemfestplatte für Rescuezilla exportieren</h3><p>Erstellt eine unabhängige Kopie der ausgewählten virtuellen Festplatte für die Wiederherstellung auf echter Hardware. Die VM muss während des gesamten Exports ausgeschaltet bleiben. Keine automatische Erkennung der Systemplatte: bei mehreren Laufwerken die vollständige Systemfestplatte mit Bootpartitionen wählen.</p><p>RAW (.img) ist ein direktes Disk-Abbild; sein Download kann die gesamte virtuelle Größe übertragen. QCOW2 ist platzsparender und wird ebenfalls von Rescuezilla unterstützt. Exportziel ist die KVM-Ablage unter dem in den Einstellungen gewählten zentralen Sicherungsordner.</p>")
        if off and row['persistent'] and not row['managed_save']:
            choices=_ui_html("<label>Systemfestplatte<select name='target' required>")+''.join(_ui_html("<option value='")+e(d['target'])+"'>"+e(d['target']+' · '+d['path'])+_ui_html("</option>") for d in row['disks'] if d['device']=='disk' and d['type']=='file' and not d['readonly'])+_ui_html("</select></label><label>Abbildformat<select name='format'><option value='raw'>RAW-Festplattenabbild (.img)</option><option value='qcow2'>QCOW2 (komprimiert, ebenfalls für Rescuezilla)</option></select></label>")
            body+=form(uid,'rescue-export',extra=choices)
        else:body+=_ui_html("<p>Zum Exportieren die VM vollständig herunterfahren; gespeicherten RAM-Zustand zuerst fortsetzen und regulär beenden.</p>")
        body+=_ui_html("<p>Auf dem neuen PC einen Rescuezilla-USB-Stick starten, dieses Abbild auswählen und auf eine mindestens gleich große SSD/HDD wiederherstellen. Deren Inhalt wird überschrieben. BIOS/UEFI und Treiber müssen passen; Bootreparatur kann nötig sein. Keine startbare ISO und kein vollständiges VM-Backup: weitere Disks, UEFI-NVRAM und TPM-Zustand sind nicht enthalten. Bei BitLocker/TPM-Bindung Wiederherstellungsschlüssel bereithalten.</p>")
        for job in service.jobs(100):
            if job['action']=='rescue-export' and job['state']=='completed' and job['vm']==uid:
                body+=f'{_ui_html("<p><a class='btn' href='/kvm/rescue-exports/")}{job['id']}{_ui_html("/download'>Export herunterladen · ")}{e(job['created'])}{_ui_html('</a></p>')}'
        body+=_ui_html('</div>')
        body+=_ui_html("<div class='card'><h3>VM-Backup zum Herunterladen</h3><p>Alle lokalen Festplatten, Konfiguration und vorhandenen UEFI-/TPM-2.0-Speicher als geprüftes Paket sichern. Die VM muss vollständig ausgeschaltet sein und währenddessen ausgeschaltet bleiben. ISO-Medien und Snapshot-Historie werden nicht mitgesichert.</p>")
        if off and row['persistent'] and not row['managed_save']:body+=form(uid,'backup','Backup erstellen')
        else:body+=_ui_html("<p>Vor dem Sichern die VM regulär herunterfahren; ein gespeicherter RAM-Zustand muss zunächst fortgesetzt werden.</p>")
        body+=_ui_html("<p><a class='btn' href='/kvm/backups'>Backups herunterladen / hochladen / wiederherstellen</a></p></div>")
        if off and row['persistent']:
            body+=_ui_html("<div class='kvm-grid'><div class='card'><h3>CPU und RAM</h3><p>Änderungen gelten ab dem nächsten Start. Die bisherige XML-Konfiguration wird gesichert.</p>")
            body+=form(uid,'resources',extra=field('RAM (MiB)','ram',row['ram'],'number','min="64" required')+field('vCPUs','cpus',row['cpus'],'number','min="1" required'))+_ui_html('</div>')
            body+=_ui_html("<div class='card'><h3>Klonen</h3><p>Vollständige Disk-Kopie, neue UUID und MAC. Der Klon bleibt ausgeschaltet. Gast-Hostname und feste IP bleiben zunächst gleich.</p>")
            body+=form(uid,'clone',extra=field('Name des Klons','name','','text','required maxlength="64"'))+_ui_html('</div>')
            body+=_ui_html("<div class='card'><h3>Disk exportieren</h3><p>Eigenständiges Image für Sicherung oder Wiederherstellung unter /VM/exports. Kein vollständiges VM-Backup; XML separat herunterladen.</p>")
            select=_ui_html("<label>Laufwerk<select name='target'>")+''.join(f'{_ui_html("<option value='")}{e(d['target'])}{_ui_html("'>")}{e(d['target'])}{_ui_html(' · ')}{e(d['path'])}{_ui_html('</option>')}' for d in row['disks'] if d['device']=='disk' and d['type']=='file')+_ui_html("</select></label><label>Format<select name='format'><option>qcow2</option><option>raw</option></select></label>")
            body+=form(uid,'export',extra=select)+_ui_html('</div></div>')
        elif not off:body+=_ui_html("<div class='card'><p>CPU/RAM ändern, Klonen, Export und ISO-Auswerfen werden nach regulärem Herunterfahren verfügbar.</p></div>")
        body+=_ui_html("<div class='card'><h3>Snapshots</h3><p>")+e(', '.join(row['snapshots']) or _ui_text('Keine Snapshots vorhanden.'))+_ui_html("</p><p>Vorhandene Snapshots werden angezeigt. Verwaltung und Wiederherstellung erfolgen mit virt-manager.</p></div>")
        if row['persistent'] or row['active']:
            body+=_ui_html("<details class='card kvm-danger'><summary>Erweiterte Aktionen</summary>")
            if row['active']:
                body+=_ui_html('<p>Hartes Ausschalten entspricht dem Ziehen des Netzsteckers; ungespeicherte Daten können verloren gehen.</p>')+form(uid,'destroy',extra=field('Zur Bestätigung exakten VM-Namen eingeben','confirm','','text','required autocomplete="off"'))
            elif off and row['persistent']:
                body+=_ui_html('<p>Nur die libvirt-Definition wird entfernt. Disk-Dateien, NVRAM und TPM-Daten bleiben erhalten; die XML wird gesichert.</p>')+form(uid,'undefine',extra=field('Zur Bestätigung exakten VM-Namen eingeben','confirm','','text','required autocomplete="off"'))
            body+=_ui_html('</details>')
        return page(row['name']+' · KVM Verwaltung',body)
    @app.route('/kvm/vm/<uid>/xml')
    def kvm_xml(uid):
        try:
            uid=backend.domain_id(uid)
            with backend.connection() as conn:
                dom=conn.lookupByUUIDString(uid);xml=dom.XMLDesc(2 if dom.isPersistent() else 0)
            return Response(xml,mimetype='application/xml',headers={'Content-Disposition':f'attachment; filename="vm-{uid}.xml"','Cache-Control':'no-store'})
        except Exception as exc:return error(exc,404)
    @app.route('/kvm/vm/<uid>/action',methods=['POST'])
    def kvm_action(uid):
        if not protected():return error('Formular abgelaufen. Seite neu laden und erneut versuchen.',403)
        try:jid=service.submit(request.form.get('action',''),uid,{k:v for k,v in request.form.items() if k!='csrf'})
        except Exception as exc:return error(exc)
        return redirect('/kvm/jobs#job-'+str(jid),303)
    @app.route('/api/kvm/media')
    def kvm_media_browser():
        try:return jsonify(backend.browse_media(request.args.get('folder','/'),request.args.get('kind','iso')))
        except backend.Error as exc:return jsonify(error=str(exc)),400
    @app.route('/api/kvm/target')
    def kvm_target_browser():
        try:
            import os,shutil
            root=backend.media_folder(request.args.get('folder','/'))
            directories=[]
            with os.scandir(root) as entries:
                for index,entry in enumerate(entries):
                    if index>=5000:break
                    if not entry.name.startswith('.') and entry.is_dir(follow_symlinks=False):directories.append(dict(name=entry.name,path=str(root/entry.name)))
            return jsonify(folder=str(root),parent=str(root.parent),directories=sorted(directories,key=lambda x:x['name'].lower()),free_gib=round(shutil.disk_usage(root).free/1024**3,1))
        except (backend.Error,OSError) as exc:return jsonify(error=str(exc)),400
    @app.route('/api/kvm/rescuezilla')
    def kvm_rescuezilla_browser():
        try:
            listing=backend.browse_media(request.args.get('folder','/'),'iso')
            listing.pop('files',None)
            try:
                info=backend.rescuezilla_backup(listing['folder']);info.pop('files')
                listing['backup']=info
            except (backend.Error,OSError) as exc:listing['note']=str(exc)
            return jsonify(listing)
        except (backend.Error,OSError) as exc:return jsonify(error=str(exc)),400
    @app.route('/kvm/new',methods=['GET','POST'])
    def kvm_new():
        creation_error=''
        if request.method=='POST':
            if not protected():return error('Formular abgelaufen. Bitte Seite neu laden.',403)
            try:jid=service.submit('create','',{k:v for k,v in request.form.items() if k!='csrf'})
            except Exception as exc:creation_error=str(exc)
            else:return redirect('/kvm/jobs#job-'+str(jid),303)
        try:data=backend.inventory()
        except Exception as exc:return error(exc,503)
        body=_ui_html("<div class='card'><h2>Neue VM / Disk-Import</h2><p>Vorlagen nach KVM VM Manager V8. Neue VMs werden ausgeschaltet angelegt und können anschließend geprüft und gestartet werden.</p><form class='kvm-form' method='post'>")+csrf()
        if creation_error:body+=_ui_html("<p class='err' role='alert'>")+e(creation_error)+_ui_html(" Deine Eingaben bleiben erhalten.</p>")
        body+=_ui_html("<div id='target-fields'><h3>3. Ziel · neuen VM-Ordner und Zieldatei anlegen</h3>")
        body+=field('Zielablage: vorhandener Ordner auf dem Server','target_root',str(backend.VM_ROOT),'text',"id='target-root' required")
        body+=_ui_html("<button type='button' class='btn' id='target-check'>Zielordner öffnen / Speicher prüfen</button><label>Unterordner<select id='target-dirs'><option value=''>Zielordner zuerst öffnen …</option></select></label><button type='button' class='btn' id='target-up'>Übergeordneter Zielordner</button><p id='target-status' role='status'></p>")
        body+=field('Ziel: Name der neuen VM und ihres Ordners','name','','text','required maxlength="64" aria-describedby="vm-name-help"')
        body+=_ui_html("<p id='vm-name-help'>Nur den neuen Namen eingeben, keinen Ordnerpfad. Beispiel: <code>Server-Restore</code>. Erlaubt: A–Z, a–z, 0–9, Punkt, Unterstrich und Bindestrich; keine Leerzeichen, Umlaute oder Schrägstriche. Höchstens 64 Zeichen, erstes Zeichen Buchstabe oder Ziffer.</p>")
        body+=_ui_html("<p id='vm-target' data-root='")+e(backend.VM_ROOT)+_ui_html("'></p><p>Der Manager legt unter diesem Zielordner die neue virtuelle Festplatte <code>disk.qcow2</code> an. Ein vorhandener VM-Name oder Zielordner wird nicht überschrieben. Die Zielablage gilt nur für diese neue VM. Vorhandene VMs und der allgemeine VM-Pfad bleiben unverändert.</p></div>")

        body+=_ui_html("<label>Vorlage<select id='preset' name='preset'>")+''.join(f'{_ui_html("<option value='")}{key}{_ui_html("'>")}{e(_ui_text(p['label']))}{_ui_html('</option>')}' for key,p in backend.PRESETS.items())+_ui_html('</select></label>')
        body+=_ui_html("<label>Installations- oder Wiederherstellungsart<select name='kind' id='kind'><option value='iso'>Neuinstallation mit ISO</option><option value='import'>Vorhandene Disk als Kopie importieren (qcow2 / raw / img / VMDK)</option><option value='rescuezilla'>Rescuezilla-Sicherung in neuer VM wiederherstellen</option></select></label>")
        body+=_ui_html("<h3 id='source-media-title'>Quelle: Installations-ISO oder Disk-Datei</h3><p id='source-media-help'>Hier das vorhandene Startmedium oder die zu kopierende virtuelle Festplatte auswählen.</p>")
        body+=field('Quellordner der ISO oder fertigen Disk-Datei','media_root',str(backend.ISO_ROOTS[0]) if backend.ISO_ROOTS else '/','text',"id='media-folder' required list='media-roots'")
        body+="<datalist id='media-roots'>"+''.join("<option value='"+e(p)+"'>" for p in dict.fromkeys((*backend.ISO_ROOTS,*backend.MEDIA_ROOTS)))+_ui_html("</datalist><div class='kvm-actions'><button type='button' class='btn' id='folder-open'>Ordner öffnen</button><button type='button' class='btn' id='folder-up'>Übergeordneter Ordner</button></div><label>Unterordner auswählen<select id='media-dirs'><option value=''>Ordner zuerst öffnen …</option></select></label><p id='media-empty' role='status'></p><button type='button' class='btn' id='use-rescue' hidden>Diese Rescuezilla-Sicherung verwenden</button>")
        body+=_ui_html("<label><span id='media-label'>Datei auf dem Server auswählen</span><select id='media-picker' name='media' required><option value=''>Ordner zuerst öffnen …</option></select></label>")
        body+=_ui_html("<details id='media-manual'><summary>Dateipfad manuell eingeben</summary><label>Absoluter Dateipfad<input id='media-path' type='text' disabled placeholder='Datei innerhalb des gewählten Ordners'></label></details><p>Beliebigen vorhandenen Serverordner eingeben oder durch Unterordner navigieren. Danach ISO oder Disk auswählen. Die Auswahl gilt nur für diesen Auftrag; allgemeine Einstellungen bleiben unverändert. Die Quelldatei wird kopiert, nicht verändert.</p>")
        body+=_ui_html("""<div id='rescue-fields' hidden><h3>1. Quell-Sicherung · vorhandener Rescuezilla-Ordner</h3><p>Dies ist die vorhandene Sicherung des alten Systems. Hier den vollständigen Sicherungsordner wählen, nicht einzelne .gz.aa-Dateien. Der Manager erstellt eine neue VM und eine zusätzliche, nur lesbare Sicherungskopie. Die Wiederherstellung selbst führst du danach in Rescuezilla aus.</p><label>Quell-Sicherung: vorhandener Ordner<input id='rescue-folder' name='rescuezilla_folder' value='/' disabled></label><button type='button' class='btn' id='rescue-open'>Ordner öffnen / Sicherung prüfen</button> <button type='button' class='btn' id='rescue-up'>Übergeordneter Ordner</button><label>Unterordner<select id='rescue-dirs'><option value=''>Ordner öffnen …</option></select></label><p id='rescue-status' role='status'></p><p>Unterstützt: vollständige Sicherung einer einzelnen Festplatte im Rescuezilla-/Clonezilla-Format mit Sektorangaben. Keine automatische Verkleinerung, keine Mehrplatten-Sicherung. Firmware passend zum gesicherten System wählen. Freier Platz: gesamte Zielplatten-Größe + ISO + Sicherungskopie mit Reserve. Autostart bleibt zunächst aus.</p></div>""")
        body+=_ui_html("<div class='kvm-grid' id='vm-resources'>")+field('RAM (MiB)','ram',4096,'number','min="64" required')+field('vCPUs','cpus',2,'number','min="1" required')+field('Zieldatei disk.qcow2: Größe (GiB; bei ISO / Rescuezilla)','disk',40,'number','min="1" required')+_ui_html('</div>')
        body+=_ui_html("<label>Firmware<select name='firmware'><option value='uefi'>UEFI</option><option value='bios'>BIOS / Legacy</option></select></label><label>Netzwerk<select name='network' required>")
        for bridge in data['bridges']:body+=f'{_ui_html("<option value='bridge:")}{e(bridge)}{_ui_html("' ")}{('selected' if bridge == 'br0' else '')}{_ui_html('>Bridge: ')}{e(bridge)}{_ui_html('</option>')}'
        for n in data['networks']:
            if n['active']:body+=f'{_ui_html("<option value='network:")}{e(n['name'])}{_ui_html("'>libvirt-Netzwerk: ")}{e(n['name'])}{_ui_html('</option>')}'
        body+=_ui_html("</select></label><label><input type='checkbox' name='autostart' value='1'> Bei künftigem Host-Start automatisch starten</label><p class='kvm-muted'>Virtuelle Disk-Größe plus 2 GiB Reserve müssen frei sein. Für ISO-Installationen wird zusätzlich eine lokale ISO-Kopie angelegt. Windows 11 erhält TPM 2.0; SATA und emulierte Netzwerkkarte vereinfachen die Installation.</p><button class='btn' id='create-vm-button'>Zielordner und VM im Hintergrund anlegen</button></form></div>")
        body+=_ui_html("<details><summary>Rescuezilla: Ablauf der Wiederherstellung</summary>")+rescuezilla_instructions()+_ui_html("</details>")
        rescue_iso=host_setting('rescuezilla_iso')
        defaults=json.dumps(dict(folder=host_setting('rescuezilla_backup_root'),iso=rescue_iso,iso_folder=str(Path(rescue_iso).parent) if rescue_iso else '')).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
        body+=_ui_html("<script>const rescueDefaults=")+defaults+_ui_html(";</script>")
        presets=json.dumps(backend.PRESETS)
        body+=_ui_html("<script>const presets=")+presets+_ui_html(";document.querySelector('#preset').addEventListener('change',ev=>{const p=presets[ev.target.value];for(const k of ['ram','cpus','disk','firmware'])document.querySelector('[name='+k+']').value=p[k];if(ev.target.value==='haos'){document.querySelector('#kind').value='import';document.querySelector('#kind').dispatchEvent(new Event('change'));}});</script>")
        body+=_ui_html("""<script>(()=>{
const picker=document.getElementById('media-picker'),kind=document.getElementById('kind'),path=document.getElementById('media-path'),manual=document.getElementById('media-manual'),folder=document.getElementById('media-folder'),dirs=document.getElementById('media-dirs'),status=document.getElementById('media-empty');let parent='/',sequence=0,detectedRescue='';const useRescue=document.getElementById('use-rescue'),initialMediaFolder=folder.value;
async function openFolder(){const current=++sequence;useRescue.hidden=true;detectedRescue='';picker.replaceChildren(new Option('Bitte Datei auswählen …',''));dirs.replaceChildren(new Option('Unterordner auswählen …',''));status.textContent='Ordner wird gelesen …';try{const response=await fetch('/api/kvm/media?'+new URLSearchParams({folder:folder.value,kind:kind.value==='rescuezilla'?'iso':kind.value}));const data=await response.json();if(current!==sequence)return;if(!response.ok)throw Error(data.error||'Ordner nicht lesbar');folder.value=data.folder;parent=data.parent;for(const item of data.directories)dirs.add(new Option(item.name,item.path));for(const item of data.files)picker.add(new Option(item.name,item.path));if(kind.value==='rescuezilla'&&rescueDefaults.iso&&data.files.some(item=>item.path===rescueDefaults.iso)){picker.value=rescueDefaults.iso;path.value=picker.value;}status.textContent=data.files.length+' passende Dateien; '+data.directories.length+' Unterordner.'+(data.truncated?' Sehr großer Ordner: Anzeige begrenzt; Pfad gegebenenfalls direkt eingeben.':'');if(data.rescuezilla){detectedRescue=data.folder;useRescue.hidden=false;status.textContent='Rescuezilla-Sicherung erkannt · Zieldisk mindestens '+data.rescuezilla.minimum_gib+' GiB. Diesen Ordner als Sicherung übernehmen; die Rescuezilla-ISO wird anschließend separat ausgewählt.';}else if(data.rescuezilla_note){status.textContent='Sicherungsordner erkannt, aber nicht unterstützt: '+data.rescuezilla_note;}}catch(error){if(current===sequence)status.textContent=error.message;}}
document.getElementById('folder-open').addEventListener('click',openFolder);document.getElementById('folder-up').addEventListener('click',()=>{folder.value=parent;openFolder();});dirs.addEventListener('change',()=>{if(dirs.value){folder.value=dirs.value;openFolder();}});folder.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();openFolder();}});
folder.addEventListener('input',()=>{sequence++;useRescue.hidden=true;detectedRescue='';picker.replaceChildren(new Option('Ordner zuerst öffnen …',''));});
picker.addEventListener('change',()=>{path.value=picker.value;});manual.addEventListener('toggle',()=>{const custom=manual.open;picker.disabled=custom;picker.required=!custom;path.disabled=!custom;path.required=custom;if(custom){picker.removeAttribute('name');path.name='media';if(!path.value)path.value=picker.value;path.focus();}else{path.removeAttribute('name');picker.name='media';}});
const rescueBox=document.getElementById('rescue-fields'),rescueFolder=document.getElementById('rescue-folder'),rescueDirs=document.getElementById('rescue-dirs'),rescueStatus=document.getElementById('rescue-status');let rescueParent='/',rescueSequence=0;rescueFolder.value=rescueDefaults.folder;
async function openRescue(){const current=++rescueSequence;rescueStatus.textContent='Sicherungsordner wird geprüft …';rescueDirs.replaceChildren(new Option('Unterordner auswählen …',''));try{const response=await fetch('/api/kvm/rescuezilla?'+new URLSearchParams({folder:rescueFolder.value}));const data=await response.json();if(current!==rescueSequence)return;if(!response.ok)throw Error(data.error);rescueFolder.value=data.folder;rescueParent=data.parent;for(const item of data.directories)rescueDirs.add(new Option(item.name,item.path));if(data.backup){const b=data.backup;rescueStatus.textContent='Sicherung erkannt: '+b.disk+' · Zieldisk mindestens '+b.minimum_gib+' GiB · zusätzliche Sicherungskopie ca. '+(b.bytes/1073741824).toFixed(1)+' GiB. Vollständigkeit der Abbilder in Rescuezilla prüfen.';const disk=document.querySelector('[name=disk]');if(Number(disk.value)<b.minimum_gib)disk.value=b.minimum_gib;}else{rescueStatus.textContent='Noch kein geeigneter Sicherungsordner: '+data.note;}}catch(error){if(current===rescueSequence)rescueStatus.textContent=error.message;}}
document.getElementById('rescue-open').addEventListener('click',openRescue);document.getElementById('rescue-up').addEventListener('click',()=>{rescueFolder.value=rescueParent;openRescue();});rescueDirs.addEventListener('change',()=>{if(rescueDirs.value){rescueFolder.value=rescueDirs.value;openRescue();}});rescueFolder.addEventListener('input',()=>{rescueSequence++;rescueStatus.textContent='Ordner erneut prüfen.';});rescueFolder.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();openRescue();}});
useRescue.addEventListener('click',()=>{if(!detectedRescue)return;rescueFolder.value=detectedRescue;kind.value='rescuezilla';manual.open=false;path.value='';folder.value=initialMediaFolder;sourceChanged();openRescue();rescueBox.scrollIntoView({block:'center'});});
const targetRoot=document.getElementById('target-root'),target=document.getElementById('vm-target'),vmName=document.querySelector('[name=name]');function showTarget(){vmName.setCustomValidity(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(vmName.value)?'':'Bitte nur einen VM-Namen eingeben, z. B. Server-Restore. Kein Pfad, keine Leerzeichen oder Umlaute.');const base=(targetRoot.value.endsWith('/')?targetRoot.value.slice(0,-1):targetRoot.value);target.textContent='Zielordner (wird neu angelegt): '+base+'/'+(vmName.value||'<VM-Name>')+' · Zieldatei: disk.qcow2';}vmName.addEventListener('input',showTarget);targetRoot.addEventListener('input',showTarget);showTarget();
let targetParent='/',targetSequence=0;const targetStatus=document.getElementById('target-status'),targetDirs=document.getElementById('target-dirs');async function openTarget(){const current=++targetSequence;targetStatus.textContent='Ziel wird geprüft …';try{const response=await fetch('/api/kvm/target?'+new URLSearchParams({folder:targetRoot.value}));const data=await response.json();if(current!==targetSequence)return;if(!response.ok)throw Error(data.error);targetRoot.value=data.folder;targetParent=data.parent;targetDirs.replaceChildren(new Option('Unterordner auswählen …',''));for(const d of data.directories)targetDirs.add(new Option(d.name,d.path));targetStatus.textContent=data.free_gib+' GiB frei. Darunter wird ein neuer Ordner mit dem VM-Namen angelegt.';showTarget();}catch(error){if(current===targetSequence)targetStatus.textContent=error.message;}}document.getElementById('target-check').addEventListener('click',openTarget);document.getElementById('target-up').addEventListener('click',()=>{targetRoot.value=targetParent;openTarget();});targetDirs.addEventListener('change',()=>{if(targetDirs.value){targetRoot.value=targetDirs.value;openTarget();}});targetRoot.addEventListener('input',()=>{targetSequence++;targetStatus.textContent='Zielordner erneut prüfen.';});
function sourceChanged(){const rescue=kind.value==='rescuezilla';if(rescue&&rescueDefaults.iso_folder)folder.value=rescueDefaults.iso_folder;document.getElementById('vm-resources').before(document.getElementById('target-fields'));document.querySelector('#target-fields h3').textContent=rescue?'3. Ziel · neuen VM-Ordner und Zieldatei anlegen':'Ziel · neuen VM-Ordner und Zieldatei anlegen';document.getElementById('source-media-title').textContent=rescue?'2. Rescuezilla-Start-ISO · separates Startmedium':'Quelle: Installations-ISO oder Disk-Datei';document.getElementById('source-media-help').textContent=rescue?'Hier die Rescuezilla-ISO auswählen, mit der die neue VM startet. Die ISO enthält nicht deine Sicherung. Den Sicherungsordner wählst du unter Quell-Sicherung.':'Hier das vorhandene Startmedium oder die zu kopierende virtuelle Festplatte auswählen.';document.getElementById('create-vm-button').textContent=rescue?'Zielordner, Zieldatei und Rescuezilla-VM vorbereiten':'Zielordner und VM im Hintergrund anlegen';document.getElementById('media-label').textContent=rescue?'Rescuezilla-Start-ISO auswählen (separat zur Sicherung)':'Datei auf dem Server auswählen';if(rescue)document.getElementById('source-media-title').before(rescueBox);rescueBox.hidden=!rescue;rescueFolder.disabled=!rescue;rescueFolder.required=rescue;openFolder();}kind.addEventListener('change',sourceChanged);sourceChanged();
})();</script>""")
        if creation_error:
            saved=json.dumps({k:v for k,v in request.form.items() if k!='csrf'}).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
            body+=_ui_html("<script>(()=>{const saved=")+saved+_ui_html(";const form=document.getElementById('create-vm-button').form;for(const [key,value] of Object.entries(saved)){const input=form.elements.namedItem(key);if(input){if(input.type==='checkbox')input.checked=value==='1';else input.value=value;}}document.getElementById('kind').dispatchEvent(new Event('change'));if(saved.media){document.getElementById('media-path').value=saved.media;document.getElementById('media-manual').open=true;}form.elements.namedItem('name').dispatchEvent(new Event('input'));})();</script>")
        return page(_ui_text('Neue VM · KVM Verwaltung'),body)

    @app.route('/kvm/rescue-exports/<int:jid>/download')
    def kvm_rescue_export_download(jid):
        try:
            with service.db() as con:row=con.execute("SELECT id FROM kvm_jobs WHERE id=? AND action='rescue-export' AND state='completed'",(jid,)).fetchone()
            if not row:raise backend.Error('Abgeschlossener Export nicht gefunden.')
            path=backup.rescue_export_file(jid)
            response=send_file(path,as_attachment=True,download_name=path.name,mimetype='application/octet-stream',conditional=True)
            with service.transfer_lock:service.transfers+=1
            def finished():
                with service.transfer_lock:service.transfers-=1
            response.call_on_close(finished)
            return response
        except (backend.Error,OSError) as exc:return error(exc,404)
    @app.route('/api/kvm/jobs')
    def kvm_jobs_api():return jsonify(jobs=service.jobs())
    @app.route('/kvm/jobs')
    def kvm_jobs():
        rows=service.jobs();body=_ui_html("<div class='card'><h2>Aufträge und Protokoll</h2><p>Aufträge laufen nacheinander im Hintergrund. Diese Seite aktualisiert sich bei laufenden Aufträgen automatisch.</p></div>")
        for row in rows:
            body+=f'{_ui_html("<div class='card' id='job-")}{row['id']}{_ui_html("'><h3>#")}{row['id']}{_ui_html(' · ')}{e(_ui_text(LABELS.get(row['action'], row['action'])))}{_ui_html('</h3><p><b>')}{e(_ui_text(JOB_STATES[row['state']]))}{_ui_html('</b> · ')}{e(row['created'])}{_ui_html(' · Ende: ')}{e(row['finished'] or '–')}{_ui_html('</p><pre>')}{e(row['log'] or 'Auftrag wartet …')}{_ui_html('</pre>')}'
            if row['action']=='rescue-export' and row['state']=='completed':body+=f'{_ui_html("<a class='btn' href='/kvm/rescue-exports/")}{row['id']}{_ui_html("/download'>Rescuezilla-Abbild herunterladen</a> ")}'
            if row['action']=='backup' and row['state']=='completed':body+=f'{_ui_html("<a class='btn' href='/kvm/backups/")}{row['id']}{_ui_html("/download'>VM-Backup herunterladen</a> ")}'
            if row['result_vm']:body+=f'{_ui_html("<a class='btn' href='/kvm/vm/")}{e(row['result_vm'])}{_ui_html("'>VM öffnen</a>")}'
            body+=_ui_html('</div>')
        if not rows:body+=_ui_html("<div class='card'><p>Noch keine KVM-Aufträge.</p></div>")
        if any(r['state'] in ('queued','running','uploading') for r in rows):body+=_ui_html("<script>setTimeout(()=>location.reload(),4000)</script>")
        return page(_ui_text('KVM-Aufträge'),body)
    @app.route('/kvm/help')
    def kvm_help():
        try:
            data=backend.inventory();diag='\n'.join(f'{key}: {"vorhanden" if value else "fehlt"}' for key,value in data['tools'].items())
        except Exception as exc:diag=str(exc)
        body=_ui_html("<div class='card'><h2>Bedienung</h2><ol><li>Vorhandene VMs unter „Virtuelle Maschinen“ auswählen.</li><li>Neue VM: Vorlage und ISO oder Disk wählen; Auftrag abwarten.</li><li>Konfiguration prüfen, VM starten und Konsole über virt-viewer öffnen.</li><li>Nach der Installation herunterfahren und Installations-ISO auswerfen.</li></ol><h3>Import, Klonen und Wiederherstellung</h3><p>Ein Disk-Import erstellt eine unabhängige qcow2-Kopie. VMDK-Einzelimages sind möglich; OVA-Archive und VMX-Konfigurationen werden nicht automatisch übernommen. Die Quelle „Rescuezilla-Sicherung“ bereitet eine neue VM mit ISO und schreibgeschützter Sicherungskopie vor. Die Wiederherstellung erfolgt anschließend in Rescuezilla; raw/qcow2-Abbilder können direkt importiert werden.</p><p>Klonen kopiert Host-Konfiguration und Disks mit neuen MAC-Adressen. Gast-Benutzer, Passwörter, machine-id, Hostname und statische IP bleiben erhalten. Diese Werte vor parallelem Netzwerkbetrieb anpassen.</p><p>Automatische DHCP-/XRDP-/UEFI-Eingriffe aus früheren Installationen werden nicht auf bestehende Gast-Dateisysteme angewendet. TPM-/Passthrough-Klone, komplexe Ressourcenlayouts und Snapshot-Verwaltung bitte mit virt-manager bearbeiten.</p><h3>Sicherungen und Fehler</h3><p>Für vollständige unterstützte VM-Sicherungen einschließlich XML, Disks, UEFI und TPM 2.0: <a href='/kvm/backups'>Backup &amp; Wiederherstellung</a>. Wiederherstellung erfolgt unter neuem Namen; Details und Einschränkungen stehen dort.</p><p>Vor Konfigurationsänderungen wird die XML unter /var/lib/server-manager/kvm-xml-backups gesichert. Ein Disk-Export enthält keinen RAM-Zustand, keine NVRAM-/TPM-Daten und keine vollständige VM-Konfiguration.</p><p>Unterbrochene oder fehlgeschlagene Aufträge bleiben im Protokoll. Bereits angelegte Dateien werden erhalten. Vor einem erneuten Versuch den Zielordner und die VM-Liste prüfen.</p><h3>Schlafschutz</h3><p>Aktive VMs und laufende Aufträge melden sich im zentralen Blocker-System. Bei nicht prüfbarem KVM-Status bleibt automatischer Schlaf gesperrt.</p></div>")
        body+=_ui_html("<div class='card'><h3>Abhängigkeiten</h3><pre>")+e(diag)+_ui_html("</pre><p>Debian-Pakete: python3-libvirt, libvirt-clients, libvirt-daemon-system, qemu-utils, virtinst, ovmf; Windows 11 zusätzlich swtpm und swtpm-tools. Das Modul installiert keine Pakete beim Seitenaufruf.</p><p>Vorlagen sind Ausgangswerte. Insbesondere ältere Betriebssysteme benötigen passende Installationsmedien und ggf. zusätzliche Treiber.</p><p>Referenz: <a href='https://www.libvirt.org/manpages/virsh.html'>libvirt</a> · <a href='https://virt-manager.org/'>virt-manager / virt-install</a></p></div>")
        return page(_ui_text('KVM-Hilfe'),body)
