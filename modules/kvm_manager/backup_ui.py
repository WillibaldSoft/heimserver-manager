"""Backup/download and bounded chunked upload; jobs share the KVM serialization."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json
import secrets
import threading
import time
from flask import request,session,jsonify,send_file,redirect
from . import backend as b,backup

CHUNK=4*1024*1024

def register(app,service,csrf,page,error,e):
    lock=threading.Lock()
    def protected():
        value=request.headers.get('X-KVM-CSRF','') or request.form.get('csrf','')
        return bool(value and secrets.compare_digest(value,session.get('kvm_csrf','')))
    def owned(jid):
        with service.db() as con:row=con.execute('SELECT * FROM kvm_jobs WHERE id=?',(jid,)).fetchone()
        if not row or row['state']!='uploading':raise b.Error('Upload ist nicht mehr aktiv. Bitte erneut beginnen.')
        data=json.loads(row['payload'])
        if not secrets.compare_digest(data.get('owner',''),session.get('kvm_upload_owner','!')):raise b.Error('Upload gehört zu einer anderen Sitzung.')
        return data
    def start_worker(jid):
        try:threading.Thread(target=service.run,args=(jid,),daemon=True,name=f'kvm-job-{jid}').start()
        except Exception:
            with service.db() as con:con.execute("UPDATE kvm_jobs SET state='failed',log='Worker konnte nicht gestartet werden' WHERE id=?",(jid,))
            backup.upload(jid).unlink(missing_ok=True)
            raise
    @app.route('/kvm/backups')
    def kvm_backups():
        rows=[r for r in service.jobs(100) if r['action'] in ('backup','restore-backup')]
        body=_ui_html("<div class='card'><h2>VM-Backup & Wiederherstellung</h2><p>Unten eine VM zum Sichern auswählen und vorher regulär herunterfahren. Sie muss während des gesamten Backups ausgeschaltet bleiben.</p><p>Das Paket enthält alle lokalen Festplatten im aktuellen Zustand, VM-Konfiguration und vorhandenen UEFI-/TPM-2.0-Speicher. CD/ISO-Medien, RAM-Zustände und Snapshot-Historie sind nicht enthalten. Hardware-Durchreichung, Host-Ordner, verschlüsselte TPMs und externe/verkettete Disk-Images benötigen eine gesonderte Sicherung und werden abgewiesen.</p><p>Speicherziel: <code>")+e(backup.root())+_ui_html("</code> · <a href='/settings/server-paths'>Server & Modulpfade</a>. Sicherungen enthalten auch die Daten und Zugangsdaten des Gasts; Download entsprechend geschützt aufbewahren.</p></div>")
        inv=None
        body+=_ui_html("<div class='card'><h3>Backup erstellen</h3><p>Die Sicherung läuft im Hintergrund. Nach Abschluss steht das Paket unter den Aufträgen und auf dieser Seite zum Herunterladen bereit.</p>")
        try:
            inv=b.inventory()
            if not inv['vms']:body+=_ui_html("<p>Auf diesem Server sind keine virtuellen Maschinen vorhanden.</p>")
            else:
                body+=_ui_html("<div class='kvm-table'><table><tr><th>Virtuelle Maschine</th><th>Status</th><th>Backup</th></tr>")
                for vm in inv['vms']:
                    uid=e(vm['uuid'])
                    body+=_ui_html("<tr><td><a href='/kvm/vm/")+uid+"'>"+e(vm['name'])+_ui_html("</a></td><td>")+e(vm['state_label'])+_ui_html("</td><td>")
                    if vm['state']==5 and vm['persistent']:
                        try:
                            if b.detail(vm['uuid'])['managed_save']:
                                body+=_ui_html("Gespeicherten RAM-Zustand zuerst fortsetzen und die VM regulär herunterfahren.")
                            else:
                                body+=_ui_html("<form class='kvm-form' method='post' action='/kvm/vm/")+uid+"/action'>"+csrf()+_ui_html("<input type='hidden' name='action' value='backup'><button class='btn' type='submit'>Backup erstellen</button></form>")
                        except Exception:body+=_ui_html("VM-Zustand nicht prüfbar. Bitte VM-Details prüfen.")
                    elif not vm['persistent']:body+=_ui_html("Für eine Sicherung muss die VM dauerhaft definiert sein.")
                    else:body+=_ui_html("VM zuerst regulär herunterfahren.")
                    body+=_ui_html("</td></tr>")
                body+=_ui_html("</table></div>")
        except Exception:body+=_ui_html("<p>VM-Liste nicht verfügbar. Installation und Verbindung unter <a href='/kvm/help'>Hilfe & Diagnose</a> prüfen.</p>")
        body+=_ui_html("</div>")
        body+=_ui_html("<div class='card'><h3>Gesicherte VMs herunterladen</h3>")
        completed=[row for row in rows if row['action']=='backup' and row['state']=='completed']
        if not completed:body+=_ui_html("<p>Noch keine abgeschlossene VM-Sicherung vorhanden. Nach einem erfolgreichen Backup erscheint hier der Download.</p>")
        for row in completed:
            from .plugin import JOB_STATES
            body+=_ui_html("<div class='card'><p><strong>")+e(row['vm'])+_ui_html("</strong> · <a href='/kvm/jobs#job-")+str(row['id'])+"'>Auftrag #"+str(row['id'])+_ui_html("</a> · ")+e(row['created'])+' · '+e(_ui_text(JOB_STATES.get(row['state'],_ui_text(row['state']))))+_ui_html('</p>')
            if row['action']=='backup' and row['state']=='completed':body+=_ui_html("<a class='btn' href='/kvm/backups/")+str(row['id'])+_ui_html("/download'>VM-Backup herunterladen</a>")
            body+=_ui_html('</div>')
        body+=_ui_html("<p><a class='btn' href='/kvm/jobs'>Alle Aufträge und Protokolle</a></p></div>")
        body+=_ui_html("<div class='card'><h3>Backup hochladen und wiederherstellen</h3><p>Heimserver-VM-Backup (.tar.gz) auswählen. Nach dem Upload werden Prüfsummen und Konfiguration geprüft. Eine neue, ausgeschaltete VM wird angelegt; vorhandene VMs bleiben erhalten. Neue UUID und MAC-Adressen, Autostart aus. Gast-Hostname, feste IP und Zugangsdaten bleiben im Gast erhalten. CD-Laufwerke werden leer und die Grafikkonsole nur lokal eingerichtet. Die Hardware-/Firmware-Version muss auf diesem Server verfügbar sein. Neue VM-Identitäten können Windows-Aktivierung oder einen BitLocker-Wiederherstellungsschlüssel erfordern.</p><form class='kvm-form' id='vm-upload'>")+csrf()+_ui_html("<label>Backup-Datei<input type='file' name='file' accept='.tar.gz' required></label><label>Neuer VM-Name<input name='name' required maxlength='64' pattern='[A-Za-z0-9][A-Za-z0-9_.-]{0,63}'></label><label>Netzwerk für alle Netzwerkkarten<select name='network'><option value=''>Netzwerke aus Backup beibehalten</option>")
        try:
            if inv is None:inv=b.inventory()
            for value,label in [('bridge:'+x,'Bridge: '+x) for x in inv['bridges']]+[('network:'+x['name'],'libvirt: '+x['name']) for x in inv['networks'] if x['active']]:body+=_ui_html("<option value='")+e(value)+"'>"+e(_ui_text(label))+_ui_html("</option>")
        except Exception:body+='' # installer can link here before libvirt is ready
        body+=_ui_html("</select></label><label><input type='checkbox' name='confirm' required> Als neue VM wiederherstellen; vor dem ersten Start Netzwerkkonflikte prüfen</label><button id='upload-start'>Hochladen & wiederherstellen</button> <button type='button' id='upload-cancel' hidden>Upload abbrechen</button><p id='upload-state' role='status'></p><progress id='upload-progress' max='100' value='0' hidden></progress></form><p>Upload in 4-MiB-Blöcken, bis 1 TiB. Freier Speicher wird geprüft. Browser bis Upload-Ende geöffnet lassen; danach läuft die Wiederherstellung im Hintergrund. Abgebrochene Uploads verfallen nach 30 Minuten ohne Aktivität. Ausgepackte RAW-Festplatten werden platzsparend gespeichert, benötigen aber ausreichend freien Platz für ihre vollständige Größe.</p></div>")
        body+=_ui_html('''<script>
(()=>{const f=document.querySelector('#vm-upload'),s=document.querySelector('#upload-state'),p=document.querySelector('#upload-progress'),button=document.querySelector('#upload-start'),cancel=document.querySelector('#upload-cancel');let stopped=false,id=null;
const api=async(path,body,json=false)=>{const r=await fetch('/api/kvm/backup-upload'+path,{method:'POST',headers:{'X-KVM-CSRF':f.elements.csrf.value,...(json?{'Content-Type':'application/json'}:{'Content-Type':'application/octet-stream'})},body:json?JSON.stringify(body):body});let d;try{d=await r.json()}catch(_){throw Error('Server antwortet nicht. Verbindung und Anmeldung prüfen.')}if(!r.ok)throw Error(d.error||'Anmeldung oder Auftrag prüfen.');return d;};
cancel.onclick=()=>{stopped=true;cancel.disabled=true;s.textContent='Upload wird abgebrochen …';};
f.onsubmit=async ev=>{ev.preventDefault();stopped=false;id=null;button.disabled=true;cancel.hidden=false;cancel.disabled=false;p.hidden=false;p.value=0;
try{const file=f.elements.file.files[0];const start=await api('/begin',{name:f.elements.name.value,network:f.elements.network.value,size:file.size,confirm:f.elements.confirm.checked},true);id=start.id;
for(let offset=0;offset<file.size;offset+=4194304){if(stopped)throw Error('Upload abgebrochen.');await api('/'+id+'/chunk?offset='+offset,file.slice(offset,offset+4194304));p.value=Math.min(100,100*(offset+4194304)/file.size);s.textContent='Hochgeladen: '+p.value.toFixed(1)+' %';}
if(stopped)throw Error('Upload abgebrochen.');await api('/'+id+'/finish',{},true);location.href='/kvm/jobs#job-'+id;
}catch(err){s.textContent=err.message;if(id!==null)try{await api('/'+id+'/cancel',{},true)}catch(_){}button.disabled=false;cancel.hidden=true;}}
})();</script>''')
        return page(_ui_text('VM-Backup & Wiederherstellung'),body)
    @app.route('/kvm/backups/<int:jid>/download')
    def kvm_backup_download(jid):
        try:
            with service.db() as con:row=con.execute("SELECT id FROM kvm_jobs WHERE id=? AND action='backup' AND state='completed'",(jid,)).fetchone()
            if not row:raise b.Error('Abgeschlossenes Backup nicht gefunden.')
            path=backup.bundle(jid)
            if path.is_symlink() or not path.is_file():raise b.Error('Backup-Datei fehlt.')
            response=send_file(path,as_attachment=True,download_name=path.name,mimetype='application/gzip',conditional=True)
            with service.transfer_lock:service.transfers+=1
            def finished():
                with service.transfer_lock:service.transfers-=1
            response.direct_passthrough=False;response.call_on_close(finished)
            return response
        except Exception as exc:return error(exc,404)
    @app.route('/api/kvm/backup-upload/begin',methods=['POST'])
    def kvm_upload_begin():
        if not protected():return jsonify(error='Formular abgelaufen. Bitte neu laden.'),403
        try:
            request.max_content_length=4096;data=request.get_json() or {}
            name=b.name(data.get('name',''));size=data.get('size')
            if type(size)!=int or not 0<size<=backup.MAX_UPLOAD or data.get('confirm') is not True:raise b.Error('Dateigröße oder Bestätigung ungültig.')
            network=data.get('network','')
            import re
            if not isinstance(network,str) or (network and not re.fullmatch(r'(bridge|network):[A-Za-z0-9_.-]{1,64}',network)):raise b.Error('Ungültiges Netzwerk.')
            with b.connection() as conn:b.unique(conn,name)
            backup.space(backup.root(),size)
            session.setdefault('kvm_upload_owner',secrets.token_urlsafe(32))
            payload=dict(name=name,network=network,size=size,written=0,touched=time.time(),owner=session['kvm_upload_owner'])
            service.expire_uploads()
            with lock,service.db() as con:
                con.execute('BEGIN IMMEDIATE')
                if con.execute("SELECT 1 FROM kvm_jobs WHERE state IN ('queued','running','uploading')").fetchone():raise b.Error('Ein KVM-Auftrag oder Upload läuft bereits.')
                jid=con.execute("INSERT INTO kvm_jobs(action,vm,payload,state) VALUES('restore-backup','',?,'uploading')",(json.dumps(payload),)).lastrowid
                with backup.upload(jid).open('xb'):pass
                backup.upload(jid).chmod(0o600)
            return jsonify(id=jid)
        except Exception as exc:return jsonify(error=str(exc)),400
    @app.route('/api/kvm/backup-upload/<int:jid>/<operation>',methods=['POST'])
    def kvm_upload_chunk(jid,operation):
        if not protected():return jsonify(error='Formular abgelaufen. Bitte neu laden.'),403
        try:
            with lock:
                data=owned(jid);path=backup.upload(jid)
                if operation=='cancel':
                    path.unlink(missing_ok=True)
                    with service.db() as con:con.execute("UPDATE kvm_jobs SET state='interrupted',finished=datetime('now','localtime'),log='Upload abgebrochen.' WHERE id=?",(jid,))
                elif operation=='chunk':
                    request.max_content_length=CHUNK
                    if path.is_symlink() or not path.is_file():raise b.Error('Upload-Datei fehlt.')
                    if request.args.get('offset')!=str(data['written']) or path.stat().st_size!=data['written']:raise b.Error('Upload-Position stimmt nicht. Bitte erneut beginnen.')
                    block=request.get_data(cache=False)
                    if not block or len(block)>CHUNK or data['written']+len(block)>data['size']:raise b.Error('Ungültiger Upload-Block.')
                    backup.space(path.parent,len(block))
                    with path.open('ab') as out:out.write(block)
                    data['written']+=len(block);data['touched']=time.time()
                    with service.db() as con:con.execute('UPDATE kvm_jobs SET payload=? WHERE id=?',(json.dumps(data),jid))
                elif operation=='finish':
                    if path.is_symlink() or not path.is_file() or data['written']!=data['size'] or path.stat().st_size!=data['size']:raise b.Error('Upload ist unvollständig.')
                    with service.db() as con:con.execute("UPDATE kvm_jobs SET state='queued',log='Upload vollständig; Archivprüfung und Wiederherstellung starten.' WHERE id=?",(jid,))
                    start_worker(jid)
                else:raise b.Error('Unbekannte Upload-Aktion.')
            return jsonify(ok=True)
        except Exception as exc:return jsonify(error=str(exc)),400
