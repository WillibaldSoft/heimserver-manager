"""German share wizard, review/apply flow, and client downloads."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json,secrets,time,socket,html
from urllib.parse import quote,urlencode
from contextlib import closing
from flask import request,redirect,session,Response
from . import configuration as c, helpers as h, downloads, accounts, browser

STYLE="""<style>.share-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}.share-form label{display:block;font-weight:600;margin:16px 0 5px}.share-form input:not([type=checkbox]):not([type=hidden]),.share-form select{display:block;box-sizing:border-box;width:100%;max-width:720px;padding:11px;margin-top:6px;border:1px solid #526075;border-radius:8px;background:#111c2c;color:#edf2fa}.share-form input[type=checkbox]{width:auto}.share-help{color:#b8c6da;font-size:.94em;margin:6px 0 14px;max-width:800px}.share-tabs{display:flex;gap:9px;flex-wrap:wrap}.share-table{overflow:auto}.share-table td{vertical-align:top}.share-badge{display:inline-block;border:1px solid #63768f;border-radius:20px;padding:3px 10px;font-size:.85em}.share-error{border-left:4px solid #f28c8c;padding:14px;background:#351e29}.share-ok{border-left:4px solid #7bd4a4;padding:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.share-form button{margin-top:16px}.share-row-path{max-width:400px;overflow-wrap:anywhere}.share-step{color:#a9c8ff;font-weight:600}.share-table>table.share-matrix{width:max-content;min-width:100%;table-layout:auto;border-collapse:separate;border-spacing:0}.share-matrix th,.share-matrix td{min-width:150px;white-space:nowrap;overflow-wrap:normal;word-break:normal}.share-matrix th:first-child,.share-matrix td:first-child{min-width:200px;position:sticky;left:0;background:#1f2937;z-index:1;border-right:1px solid #526075}.share-matrix thead th:first-child{z-index:2}</style>"""

def token():
    if 'shares_csrf' not in session:session['shares_csrf']=secrets.token_urlsafe(32)
    return "<input type='hidden' name='csrf' value='"+h.esc(session['shares_csrf'])+"'>"

def select(name,label,options,current):
    return _ui_html('<label>')+h.esc(_ui_text(label))+_ui_html("<select name='")+name+"'>"+''.join(_ui_html("<option value='")+h.esc(k)+"'"+(' selected' if k==current else '')+'>'+h.esc(v)+_ui_html('</option>') for k,v in options)+_ui_html('</select></label>')

def field(name,label,value='',hint='',required=False):
    return _ui_html('<label>')+h.esc(_ui_text(label))+_ui_html("<input name='")+name+"' value='"+h.esc(value)+"'"+(' required' if required else '')+_ui_html("></label>")+(_ui_html("<p class='share-help'>")+h.esc(_ui_text(hint))+_ui_html('</p>') if hint else '')

def check(name,label,on=False):return _ui_html("<label><input type='checkbox' name='")+name+"' value='1'"+(' checked' if on else '')+'> '+h.esc(_ui_text(label))+_ui_html('</label>')

def page(ctx,title,body):
    nav=_ui_html("<div class='card share-tabs'><a class='btn' href='/freigaben'>Übersicht</a><a class='btn' href='/freigaben/users'>Benutzer</a><a class='btn' href='/freigaben/rechte'>Benutzerrechte</a><a class='btn' href='/freigaben/groups'>Gruppen</a><a class='btn' href='/freigaben/domain'>Domäne (optional)</a><a class='btn' href='/freigaben/new'>Neue Freigabe</a><a class='btn' href='/freigaben/downloads'>Client-Dateien</a><a class='btn' href='/freigaben/diagnose'>Diagnose</a><a class='btn' href='/apps/shares_mounts/installer'>SMB/NFS installieren / prüfen</a></div>")
    return ctx.page(title,STYLE+nav+body,'Freigaben')

def register(app,ctx):
    browser.register(app)
    with closing(ctx.db()) as con:
        con.execute('CREATE TABLE IF NOT EXISTS shares_plans (id TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,state TEXT NOT NULL DEFAULT \'preview\',result TEXT NOT NULL DEFAULT \'\')');con.commit()
    with closing(ctx.db()) as con:
        con.execute("UPDATE shares_plans SET state='interrupted',result='Server Manager während der Änderung beendet. Konfiguration und Sicherung unter backups/shares prüfen.' WHERE state='applying'")
        con.commit()
    def owner():
        if 'shares_owner' not in session:session['shares_owner']=secrets.token_urlsafe(32)
        return session['shares_owner']
    def save(plan):
        key=secrets.token_urlsafe(24)
        with closing(ctx.db()) as con:
            con.execute('DELETE FROM shares_plans WHERE created<?',(time.time()-86400,))
            con.execute('INSERT INTO shares_plans(id,owner,payload,created) VALUES(?,?,?,?)',(key,owner(),json.dumps(plan),time.time()));con.commit()
        return key
    from .access_ui import register as register_access
    register_access(app,ctx,save)
    def load(key):
        with closing(ctx.db()) as con:row=con.execute('SELECT * FROM shares_plans WHERE id=? AND owner=?',(key,owner())).fetchone()
        if not row:raise ValueError('Vorschau nicht gefunden. Bitte neu erstellen.')
        return dict(row)
    def error(exc,code=400):return page(ctx,_ui_html('Freigaben'),_ui_html("<div class='card share-error'><h2>Bitte Eingabe prüfen</h2><p>")+h.esc(_ui_text(exc))+_ui_html("</p><a class='btn' href='/freigaben'>Zur Übersicht</a></div>")),code
    def prepare(data):return c.build_smb(data) if data.get('protocol')=='smb' else c.build_nfs(data)
    def summary():
        smb=c.smb_shares();nfs=c.nfs_exports()
        body=_ui_html("<div class='card'><h2>Dateien im Netzwerk freigeben</h2><p><a class='btn' href='/freigaben/rechte'>Wer hat Zugriff? Benutzerrechte anzeigen und ändern</a></p><p>Ordner auswählen, Zugriff festlegen und die Änderung prüfen.</p><div class='share-tabs'><a class='btn' href='/freigaben/new?protocol=smb'>+ SMB-Freigabe</a><a class='btn' href='/freigaben/new?protocol=nfs'>+ NFS-Freigabe</a></div></div>")
        body+=_ui_html("<div class='share-grid'><div class='card'><h3>SMB · Windows, macOS und Linux</h3><p>Anmeldung mit Benutzer und Passwort; auch mit Domänenkonten.</p><b>")+str(len(smb))+_ui_html(" Freigaben</b></div><div class='card'><h3>NFS · Linux und Unix</h3><p>Zugriff für bestimmte Geräte oder Netze. Benutzerrechte beruhen bei sec=sys auf UID/GID.</p><b>")+str(len(nfs))+_ui_html(" Freigaben</b></div></div>")
        body+=_ui_html("<div class='card'><label>Freigabe suchen <input type='search' id='share-search' placeholder='Name oder Ordner'></label></div>")
        for kind,rows in [('SMB',smb),('NFS',nfs)]:
            body+=_ui_html("<div class='card'><h3>")+kind+_ui_html("-Freigaben</h3><div class='share-table'><table><tr><th>Freigabe / Ordner</th><th>Zugriff</th><th>Aktionen</th></tr>")
            for row in rows:
                proto=kind.lower();key=row['name'] if proto=='smb' else row['id'];url='/freigaben/edit?'+urlencode(dict(protocol=proto,key=key))
                if proto=='smb':
                    cfg=row['config'];label=('Gemischte Rechte' if cfg.get('write list') or cfg.get('admin users') else ('Lesen und Schreiben' if cfg.get('read only', 'no' if cfg.get('writable','').lower()=='yes' else 'yes').lower()=='no' else 'Nur Lesen'))
                    who=cfg.get('valid users') or ('Gastzugriff' if cfg.get('guest ok','no').lower()=='yes' else 'Authentifizierte Benutzer mit Ordnerrechten')
                else:
                    simple=c.nfs_simple(row);label=('Lesen und Schreiben' if simple['access']=='write' else 'Nur Lesen') if simple else 'Erweiterte Optionen';who=row['clients']
                    if 'rwx' in row['clients']:label+=' · ungültige Option rwx – bitte bearbeiten'
                body+=_ui_html("<tr class='share-row'><td class='share-row-path'><b>")+h.esc(row.get('name') or row['path'])+_ui_html('</b><br><code>')+h.esc(row['path'])+_ui_html("</code></td><td><span class='share-badge'>")+h.esc(_ui_text(label))+_ui_html('</span><br>')+h.esc(who)+_ui_html("</td><td><a class='btn' href='")+h.esc(url)+_ui_html("'>Bearbeiten</a> <a class='btn' href='/freigaben/rechte?")+h.esc(urlencode(dict(protocol=proto,key=key)))+_ui_html("'>Benutzerrechte</a> <a class='btn' href='/freigaben/downloads?")+h.esc(urlencode(dict(protocol=proto,key=key)))+_ui_html("'>Client-Datei</a></td></tr>")
            if not rows:body+=_ui_html("<tr><td colspan='3'>Noch keine Freigaben. Über „Neue Freigabe“ anlegen.</td></tr>")
            body+=_ui_html('</table></div></div>')
        body+=_ui_html("<script>document.getElementById('share-search').addEventListener('input',e=>document.querySelectorAll('.share-row').forEach(r=>r.hidden=!r.textContent.toLocaleLowerCase().includes(e.target.value.toLocaleLowerCase())));</script>")
        return page(ctx,_ui_html('Freigaben'),body)
    @app.route('/freigaben',strict_slashes=False)
    @app.route('/shares',strict_slashes=False)
    @app.route('/freigaben/server',strict_slashes=False)
    def share_overview():
        try:return summary()
        except Exception as exc:return error(exc,503)
    @app.route('/freigaben/share/<path:name>')
    def share_compat(name):return redirect('/freigaben/edit?'+urlencode(dict(protocol='smb',key=name)))
    @app.route('/freigaben/new',methods=['GET','POST'])
    @app.route('/freigaben/edit',methods=['GET','POST'])
    def share_editor():
        protocol=request.values.get('protocol','smb')
        if protocol not in ('smb','nfs'):return error('Unbekanntes Freigabeprotokoll.')
        key=request.values.get('key','');message='';row=None
        try:
            if key:row=c.smb_one(key) if protocol=='smb' else c.nfs_one(key)
            if request.method=='POST':
                data=request.form.to_dict();data['original']=key
                return redirect('/freigaben/review/'+save(prepare(data)),303)
        except Exception as exc:
            if request.method!='POST':return error(exc)
            message=_ui_html("<div class='card share-error'>")+h.esc(_ui_text(exc))+_ui_html('</div>')
        values=request.form.to_dict() if request.method=='POST' else {}
        cfg=row['config'] if row and protocol=='smb' else {};simple=c.nfs_simple(row) if row and protocol=='nfs' else None
        def val(name,default=''):
            if request.method=='POST' and name in ('create_dir','browseable','guest','root_squash','replace_advanced'):return values.get(name,'')
            return values.get(name,default)
        body=_ui_text(message)+_ui_html("<div class='card'><p class='share-step'>1 · Angaben &nbsp; → &nbsp; 2 · Prüfen &nbsp; → &nbsp; 3 · Anwenden</p><h2>")+(_ui_text('Freigabe bearbeiten') if row else 'Neue '+protocol.upper()+'-Freigabe')+_ui_html("</h2><form method='post' class='share-form'>")+token()+_ui_html("<input type='hidden' name='protocol' value='")+protocol+_ui_html("'><input type='hidden' name='key' value='")+h.esc(key)+"'>"
        if protocol=='smb':
            body+=field('name','Name im Netzwerk',val('name',row['name'] if row else ''),'Unter diesem Namen erscheint der Ordner auf anderen Geräten.',True)
            if row:body+=_ui_html("<p class='share-help'>Der Netzwerkname bleibt beim Bearbeiten erhalten.</p>")
        body+=field('path','Ordner auf dem Server',val('path',row['path'] if row else ''),'Vollständiger Pfad, zum Beispiel /srv/freigaben/familie.',True)
        body+=_ui_html(browser.HTML)
        body+=check('create_dir','Ordner neu anlegen, falls er noch nicht existiert',val('create_dir')=='1')
        if protocol=='smb':
            body+=field('comment','Kurze Beschreibung',val('comment',cfg.get('comment','')))
            body+=select('access','Was darf geändert werden?',([('keep',_ui_text('Bisherige Rechte unverändert übernehmen'))] if row else [])+[('read',_ui_text('Nur Lesen – ansehen und kopieren')),('write',_ui_text('Lesen und Schreiben – auch ändern und löschen'))],val('access','keep' if row else 'read'))
            body+=_ui_html("<p class='share-help'>Die Auswahl Lesen/Schreiben ersetzt bisherige Ausnahmen für Schreib-, Lese- und Adminlisten. Für reine Pfad-/Beschreibungsänderungen „Bisherige Rechte“ verwenden. Bestehende Ordnerrechte bleiben erhalten.</p>")
            body+=field('valid_users','Wer darf zugreifen?',val('valid_users',cfg.get('valid users','')),'Benutzernamen oder @Gruppen mit Leerzeichen trennen, z. B. exampleuser @foto. Domänengruppen mit Leerzeichen in doppelte Anführungszeichen setzen.')
            local=' · '.join(u['name'] for u in accounts.users())+' | Gruppen: '+' · '.join('@'+g['name'] for g in accounts.groups())
            body+=_ui_html("<p class='share-help'>Vorhanden: ")+h.esc(local)+_ui_html(". <a href='/freigaben/users' target='_blank' rel='noopener'>Benutzer anlegen / verwalten</a> · <a href='/freigaben/groups' target='_blank' rel='noopener'>Gruppe anlegen</a></p>")
            body+=_ui_html("<details><summary>Benutzer oder Gruppe mit einem Klick hinzufügen</summary><div class='share-tabs'>")+''.join(_ui_html("<button class='btn principal-add' type='button' data-principal='")+h.esc(name)+"'>"+h.esc(name)+_ui_html("</button>") for name in [u['name'] for u in accounts.users()]+['@'+g['name'] for g in accounts.groups()])+_ui_html("</div></details><script>document.querySelectorAll('.principal-add').forEach(b=>b.addEventListener('click',()=>{const input=document.querySelector('input[name=valid_users]');let name=b.dataset.principal;if(name.includes(' '))name=String.fromCharCode(34)+name+String.fromCharCode(34);input.value=(input.value.trim()+' '+name).trim();}));</script>")

            body+=check('browseable','In der Netzwerkübersicht anzeigen',val('browseable','1' if cfg.get('browseable','yes').lower()!='no' else '')=='1')
            body+=_ui_html("<details><summary>Weitere Optionen</summary>")+check('guest','Zugriff ohne Anmeldung erlauben',val('guest','1' if cfg.get('guest ok','no').lower()=='yes' else '')=='1')
            body+=field('force_group','Gemeinsame Linux-Gruppe (optional)',val('force_group',cfg.get('force group','')),'Neue Dateien werden dieser Gruppe zugeordnet. Vorhandene Dateien werden nicht umgestellt.')+_ui_html('</details>')
        else:
            if row and simple is None:body+=_ui_html("<p class='share-error'>Bisherige erweiterte NFS-Optionen: <code>")+h.esc(row['clients'])+_ui_html("</code>. Diese Optionen, einschließlich eventueller Kerberos-Einstellungen, werden durch die einfache Auswahl ersetzt.</p>")+check('replace_advanced','Bisherige erweiterten NFS-Optionen ausdrücklich ersetzen',val('replace_advanced')=='1')
            body+=field('hosts','Welche Geräte dürfen zugreifen?',val('hosts',simple['hosts'] if simple else ''),'IP-Adressen oder Netze mit Leerzeichen trennen. Beispiel: 192.0.2.25 oder 192.0.2.0/24.',True)
            body+=select('folder_group','Gemeinsame Linux-Gruppe bei neuem Ordner',[('',_ui_text('Gruppe auswählen'))]+[(g['name'],g['name']+' · GID '+str(g['gid'])) for g in accounts.groups()],val('folder_group',''))
            body+=_ui_html("<p><a href='/freigaben/users' target='_blank' rel='noopener'>Linux-/NFS-Benutzer anlegen</a> · <a href='/freigaben/groups' target='_blank' rel='noopener'>Gruppe anlegen</a> · Nach dem Anlegen diese Seite neu laden.</p><details><summary>Vorhandene NFS-Identitäten (UID/GID)</summary>")+''.join(_ui_html('<p>')+h.esc(u['name'])+_ui_html(' · UID ')+str(u['uid'])+' · GID '+str(u['gid'])+_ui_html('</p>') for u in accounts.users())+_ui_html('</details>')
            body+=select('access','Zugriffsrecht',[('read',_ui_text('Nur Lesen')),('write',_ui_text('Lesen und Schreiben'))],val('access',simple['access'] if simple else 'read'))
            body+=check('root_squash','Administratorzugriff vom Client auf normalen Benutzer begrenzen (empfohlen)',val('root_squash','1' if not simple or simple['root_squash'] else '')=='1')
            body+=_ui_html("<p class='share-help'>NFS verwendet hier die numerischen Benutzer-/Gruppenkennungen der Clients. Dieselben UID/GID und passende Ordnerrechte sind für Schreibzugriff nötig. Neue Ordner erhalten keine pauschalen Schreibrechte.</p>")
        body+=_ui_html("<button class='btn' name='operation' value='save'>Änderung prüfen</button></form></div>")
        if row:
            body+=_ui_html("<details class='card'><summary>Freigabe entfernen</summary><p>Entfernt nur den Netzwerkzugriff. Ordner und Dateien bleiben erhalten.</p><form method='post'>")+token()+_ui_html("<input type='hidden' name='protocol' value='")+protocol+_ui_html("'><input type='hidden' name='key' value='")+h.esc(key)+_ui_html("'><button class='btn' name='operation' value='delete'>Entfernen prüfen</button></form></details>")
        return page(ctx,_ui_html('Freigabe bearbeiten'),body)
    @app.route('/freigaben/review/<key>',methods=['GET','POST'])
    def share_review(key):
        try:
            row=load(key);plan=json.loads(row['payload'])
            if request.method=='POST':
                if request.form.get('confirm')!='ja':raise ValueError('Zum Anwenden bitte das Bestätigungsfeld markieren.')
                with closing(ctx.db()) as con:
                    cursor=con.execute("UPDATE shares_plans SET state='applying' WHERE id=? AND owner=? AND state='preview'",(key,owner()));con.commit()
                    if cursor.rowcount!=1:raise ValueError('Diese Änderung wurde bereits bearbeitet.')
                try:result=c.apply(plan,request.form.get('sudo_password',''));state='completed';message='Änderung aktiviert. Sicherung: '+result['backup']
                except Exception as exc:state='failed';message=str(exc)
                with closing(ctx.db()) as con:con.execute('UPDATE shares_plans SET state=?,result=? WHERE id=?',(state,message,key));con.commit()
                return redirect('/freigaben/review/'+key,303)
            body=_ui_html("<div class='card'><p class='share-step'>2 · Prüfen → 3 · Anwenden</p><h2>")+h.esc(plan['title'])+_ui_html('</h2>')
            if row['state']!='preview':body+=_ui_html("<p class='")+('share-ok' if row['state']=='completed' else 'share-error')+"'>"+h.esc(row['result'] or _ui_text('Die Änderung wird angewendet. Bitte kurz warten und Seite neu laden.'))+_ui_html("</p><a class='btn' href='/freigaben'>Zu den Freigaben</a>")
            else:
                summary=list(plan.get('rights_summary',[]))
                for source,item in plan['files'].items():
                    if plan['kind']=='smb':
                        before={n:c.config(item['before'][a:b]) for n,a,b in c.sections(item['before'] or '')}
                        for name,a,b in c.sections(item['after'] or ''):
                            if name.lower() in c.SPECIAL:continue
                            after=c.config(item['after'][a:b]);old=before.get(name,{})
                            labels={'path':'Ordner','comment':'Beschreibung','read only':'Nur Lesen','valid users':'Erlaubte Benutzer/Gruppen','browseable':'Im Netzwerk sichtbar','guest ok':'Ohne Anmeldung','force group':'Gemeinsame Gruppe','write list':'Schreib-Ausnahmen','admin users':'Admin-Ausnahmen'}
                            for key,label in labels.items():
                                if old.get(key)!=after.get(key):summary.append((label,after.get(key) or 'Nicht festgelegt'))
                    else:
                        for line in (item['after'] or '').splitlines():
                            if line and line not in (item['before'] or '').splitlines():summary.append(('Neue NFS-Regel',line))
                if summary:body+=_ui_html('<table>')+''.join(_ui_html('<tr><th>')+h.esc(k)+_ui_html('</th><td>')+h.esc(v)+_ui_html('</td></tr>') for k,v in summary)+_ui_html('</table>')
                body+=_ui_html("<p>Diese Änderung betrifft ausschließlich die unten aufgeführten Freigabeneinstellungen. Ordnerinhalte werden nicht verschoben oder gelöscht.</p>")
                if plan['mkdir']:body+=_ui_html('<p>Neuen Ordner anlegen: <code>')+h.esc(plan['mkdir'])+_ui_html('</code></p>')
                body+=_ui_html("<details><summary>Konfigurationsänderung anzeigen</summary><pre>")+h.esc(c.preview(plan)+(('\nOrdner-ACL vorher:\n'+plan['acl_change']['before']+'\nOrdner-ACL nachher:\n'+plan['acl_change']['after']) if plan.get('acl_change') else ''))+_ui_html("</pre></details><form method='post' class='share-form'>")+token()+_ui_html("<label><input type='checkbox' name='confirm' value='ja' required> Diese Änderung anwenden</label>")
                import os
                if os.geteuid()!=0:body+=_ui_html("<label>Sudo-Passwort<input type='password' name='sudo_password' autocomplete='current-password'></label><p>Wird nur für diese Aktion verwendet.</p>")
                body+=_ui_html("<button class='btn'>Jetzt anwenden</button> <a class='btn' href='/freigaben'>Abbrechen</a></form><p class='share-help'>Vorherige Konfiguration wird gesichert. Bei Prüf- oder Ladefehlern erfolgt eine Rücknahme. Vorschau ist 15 Minuten gültig.</p>")
            return page(ctx,_ui_html('Änderung prüfen'),body+_ui_html('</div>'))
        except Exception as exc:return error(exc)
    @app.route('/freigaben/downloads')
    def share_downloads():
        protocol=request.args.get('protocol','smb');key=request.args.get('key','')
        try:server=downloads.host(request.args.get('server',''))
        except ValueError as exc:return error(exc)
        body=_ui_html("<div class='card'><h2>Freigaben auf einem Client verbinden</h2><p>Die Dateien fragen Zugangsdaten erst auf dem Zielgerät ab. Sie enthalten keine Passwörter.</p><p><a class='btn' href='/freigaben/client-script'>Vollständiger Linux-Mount-Manager</a> <a class='btn' href='/freigaben/domain'>Domänenbeitritt vorbereiten</a></p></div>")
        try:
            rows=([c.smb_one(key)] if protocol=='smb' else [c.nfs_one(key)]) if key else c.smb_shares()+c.nfs_exports()
            for row in rows:
                proto='smb' if 'name' in row else 'nfs';identity=row.get('name',row.get('id'))
                body+=_ui_html("<div class='card'><h3>")+h.esc(row.get('name') or row['path'])+' · '+proto.upper()+_ui_html("</h3><form class='share-form' action='/freigaben/download'><input type='hidden' name='protocol' value='")+proto+_ui_html("'><input type='hidden' name='key' value='")+h.esc(identity)+"'>"+field('server','Serveradresse',server,'Falls der Name nicht auflösbar ist, die IP-Adresse des Servers eintragen.',True)
                body+=select('platform','Client-System',([('windows',_ui_text('Windows – Netzlaufwerk verbinden')),('linux',_ui_text('Linux-Desktop – im Dateimanager öffnen'))] if proto=='smb' else [('linux',_ui_text('Linux – temporär einhängen'))]),'linux' if proto=='nfs' else 'windows')
                body+=_ui_html("<button class='btn'>Datei herunterladen</button></form><p class='share-help'>Windows: PowerShell-Datei unter dem normalen Benutzer ausführen. SMB unter Linux: bash Freigabe-verbinden.sh in der Desktop-Sitzung. NFS: bash NFS-verbinden.sh; benötigt sudo und nfs-common.</p></div>")
            return page(ctx,_ui_html('Client-Dateien'),body)
        except Exception as exc:return error(exc)
    @app.route('/freigaben/download')
    def share_download():
        try:
            proto=request.args.get('protocol');row=c.smb_one(request.args['key']) if proto=='smb' else c.nfs_one(request.args['key'])
            name,text=downloads.client_file(proto,row,request.args.get('platform'),request.args.get('server'))
            return Response(text,mimetype='application/octet-stream',headers={'Content-Disposition':'attachment; filename="'+name+'"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        except Exception as exc:return error(exc)
