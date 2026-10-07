"""At-a-glance share/user matrix and per-principal permission editing."""
from ui_translation import html_literal as _ui_html, text as _ui_text
from urllib.parse import urlencode
from flask import request,redirect
from . import access as a,configuration as c,helpers as h,workflow as ui

COLORS={'none':'#ffb5b5','read':'#a8d9ff','write':'#a8e7bb','admin':'#ffcf85','unknown':'#d0bddf'}

def register(app,ctx,save):
    def url(protocol,key,subject=None):
        args=dict(protocol=protocol,key=key)
        if subject is not None:args['subject']=subject
        return '/freigaben/rechte'+('/aendern' if subject is not None else '')+'?'+urlencode(args)
    def badge(level):return _ui_html("<span style='color:")+COLORS.get(level,'inherit')+";white-space:nowrap'>"+h.esc(_ui_text(a.LABEL[level]))+_ui_html('</span>')
    def error(exc):return ui.page(ctx,_ui_html('Benutzerrechte'),_ui_html("<div class='card share-error'>")+h.esc(_ui_text(exc))+_ui_html("</div><a class='btn' href='/freigaben/rechte'>Rechteübersicht</a>")),400
    @app.route('/freigaben/rechte')
    def share_rights():
        try:
            shares=c.smb_shares();nfs=c.nfs_exports();cfg_error=''
            try:configs=a.effective_configs()
            except ValueError as exc:configs={};cfg_error=str(exc)
            people=a.all_subjects(shares,configs);key=request.args.get('key','');protocol=request.args.get('protocol','smb');user=request.args.get('user','')
            if user:people=[p for p in people if p['name']==user]
            body=_ui_html("<div class='card'><h2>Wer darf auf welche Freigabe zugreifen?</h2><p>Lesen, Schreiben, SMB-Admin oder kein Zugriff – pro Benutzer und Freigabe. Klicke auf ein Recht, um es zu ändern.</p><p class='share-help'>Benutzer: SMB-Regeln zusammen mit POSIX-Rechten des Hauptordners und Betretungsrechten aller übergeordneten Ordner. Die Anzeige gilt nach erfolgreicher SMB-Anmeldung. Gruppen: ausdrücklich konfigurierte SMB-Regeln, keine pauschalen Zugriffsrechte aller Mitglieder. Aktiver Gastzugriff bleibt unabhängig von Benutzerregeln möglich. Die Ordnerspalte prüft nur die POSIX-Rechte des Hauptordners. Anmeldestatus, clientabhängige Einschränkungen und Rechte einzelner Dateien werden nicht geprüft. Statische erzwungene Dateiidentitäten werden berücksichtigt. Nicht auflösbare Identitäten und zusätzliche, nicht ausgewertete Windows-ACLs erscheinen als nicht eindeutig.</p><form class='share-form' method='get'>")+ui.select('user','Benutzer / Gruppe filtern',[('','Alle Benutzer und Gruppen')]+[(p['name'],p['name']) for p in a.all_subjects(shares,configs)],user)+_ui_html("<button class='btn'>Anzeigen</button> <a class='btn' href='/freigaben/rechte'>Alle anzeigen</a></form></div>")
            if cfg_error:body+=_ui_html("<div class='card share-error'>")+h.esc(cfg_error)+_ui_html('</div>')
            cache={}
            def snap(path):
                if path not in cache:
                    try:cache[path]=a.snapshot(path)
                    except (OSError,ValueError):cache[path]=None
                return cache[path]
            if not key:
                body+=_ui_html("<div class='card'><h3>SMB · Übersicht</h3><div class='share-table'><table class='share-matrix'><thead><tr><th>Freigabe</th>")+''.join(_ui_html('<th>')+h.esc(p['name'])+_ui_html('</th>') for p in people)+_ui_html("</tr></thead><tbody>")
                for row in shares:
                    cfg=configs.get(row['name'].casefold());body+=_ui_html("<tr><th><a href='")+h.esc(url('smb',row['name']))+"'>"+h.esc(row['name'])+_ui_html('</a>')+(_ui_html(' <small>Gastzugriff</small>') if cfg and a.yes(cfg.get('guest ok','no')) else '')+_ui_html('</th>')
                    for who in people:
                        result=a.displayed_right(cfg,who,row['path'],snap)
                        body+=_ui_html("<td><a title='")+h.esc(_ui_text(result['reason']))+"' href='"+h.esc(url('smb',row['name'],who['name']))+"'>"+badge(result['level'])+_ui_html('</a></td>')
                    body+=_ui_html('</tr>')
                body+=_ui_html('</tbody></table></div><p>Gruppenspalten zeigen nur ausdrücklich konfigurierte SMB-Gruppenregeln. „Keine Gruppenfreigabe“ bedeutet keine eigene SMB-Regel; Benutzerzugriff wird separat einschließlich Gruppenmitgliedschaften berechnet.</p></div>')
                body+=_ui_html("<div class='card'><h3>NFS · Geräte und Ordnerrechte</h3><p>NFS speichert keine SMB-Benutzerliste. Entscheidend sind erlaubte Geräte, Exportoptionen und numerische UID/GID auf dem Client.</p>")
                for row in nfs:body+=_ui_html("<p><a class='btn' href='")+h.esc(url('nfs',row['id']))+"'>"+h.esc(row['path'])+_ui_html(" · Rechte anzeigen / ändern</a><br>")+h.esc(row['clients'])+_ui_html('</p>')
                body+=_ui_html('</div>')
            else:
                row=c.smb_one(key) if protocol=='smb' else c.nfs_one(key)
                cfg=configs.get(row['name'].casefold()) if protocol=='smb' else None;snapshot=snap(row['path'])
                body+=_ui_html("<div class='card'><h3>")+h.esc(row.get('name') or row['path'])+_ui_html('</h3><p><code>')+h.esc(row['path'])+_ui_html('</code></p>')
                if protocol=='smb' and cfg:
                    body+=_ui_html('<p>SMB-Obergrenze (keine Rechtevergabe): ')+(_ui_text('Nur Lesen') if a.yes(cfg.get('read only','yes')) else _ui_text('Lesen / Schreiben'))+' · Gastzugriff: '+(_ui_text('Ja') if a.yes(cfg.get('guest ok','no')) else _ui_text('Nein'))+_ui_html('</p>')
                    if cfg.get('force user') or cfg.get('force group'):body+=_ui_html("<p class='share-help'>Dateiidentität wird erzwungen: Benutzer ")+h.esc(cfg.get('force user') or _ui_text('angemeldetes Konto'))+' / Gruppe '+h.esc(cfg.get('force group') or _ui_text('Benutzergruppen'))+_ui_html('. Die Ordnerspalte berücksichtigt bei Benutzern diese erzwungene Dateiidentität.</p>')
                elif protocol=='nfs':body+=_ui_html('<p>Export: ')+h.esc(row['clients'])+_ui_html('</p><p>„Kein Zugriff“ setzt den gezielten ACL-Eintrag auf ---; weitere Gruppenrechte können bei Gruppen weiterhin Zugriff gewähren. Die Zuordnung auf NFS-Clients muss dieselbe UID/GID verwenden.</p>')
                body+=_ui_html("<div class='share-table'><table><tr><th>Benutzer / Gruppe</th><th>Benutzerzugriff / Gruppenregel · Herkunft</th><th>Hauptordner (POSIX)</th><th>Ändern</th></tr>")
                for who in people:
                    result=a.displayed_right(cfg,who,row['path'],snap) if protocol=='smb' else dict(level='unknown',reason='Kein SMB-Recht bei NFS')
                    body+=_ui_html('<tr><td><b>')+h.esc(who['name'])+_ui_html('</b><br><small>')+h.esc(_ui_text('Gruppe') if who['group'] else 'Gruppen: '+(', '.join(who['groups']) or 'keine / nicht auflösbar'))+_ui_html('</small></td><td>')+(badge(result['level']) if protocol=='smb' else _ui_text('Über Export und UID/GID'))+_ui_html('<br><small>')+h.esc(_ui_text(result['reason']))+_ui_html('</small></td><td>')+h.esc((a.smb_folder_right(cfg,snapshot,who) if protocol=='smb' and cfg else a.folder_right(snapshot,who)) if snapshot else _ui_text('Nicht prüfbar'))+_ui_html("</td><td><a class='btn' href='")+h.esc(url(protocol,key,who['name']))+_ui_html("'>Recht ändern</a></td></tr>")
                body+=_ui_html("</table></div><form class='share-form' action='/freigaben/rechte/aendern'><input type='hidden' name='protocol' value='")+h.esc(protocol)+_ui_html("'><input type='hidden' name='key' value='")+h.esc(key)+"'>"+ui.field('subject','Weiteren Benutzer / Gruppe hinzufügen','','Benutzername oder @Gruppe; auch bekannte Domänenkonten.',True)+_ui_html("<button class='btn'>Recht auswählen</button></form></div>")
            return ui.page(ctx,_ui_html('Benutzerrechte'),body)
        except Exception as exc:return error(exc)
    @app.route('/freigaben/rechte/aendern',methods=['GET','POST'])
    def share_right_edit():
        proto=request.values.get('protocol','smb');key=request.values.get('key','');name=request.values.get('subject','');message=''
        try:
            if request.method=='POST':
                try:return redirect('/freigaben/review/'+save(a.build(request.form)),303)
                except Exception as exc:message=_ui_html("<p class='share-error'>")+h.esc(_ui_text(exc))+_ui_html('</p>')
            row=c.smb_one(key) if proto=='smb' else c.nfs_one(key);who=a.subject(name)
            cfg=a.effective_configs().get(row['name'].casefold()) if proto=='smb' else None
            def checked_snapshot(path):
                try:return a.snapshot(path)
                except (OSError,ValueError):return None
            result=a.displayed_right(cfg,who,row['path'],checked_snapshot) if proto=='smb' else None
            body=_ui_html("<div class='card'><h2>")+h.esc(name)+' · '+h.esc(row.get('name') or row['path'])+_ui_html('</h2>')+_ui_text(message)
            if cfg and a.yes(cfg.get('guest ok','no')):body+=_ui_html("<p class='share-error'>Gastzugriff ist aktiv. Eine Benutzersperre verhindert keinen unabhängigen anonymen Zugriff. Gastzugriff kann in den Freigabeeinstellungen geändert werden.</p>")
            if result:body+=_ui_html('<p>Benutzerzugriff / Gruppenregel aktuell: ')+badge(result['level'])+_ui_html('<br>')+h.esc(_ui_text(result['reason']))+_ui_html('</p>')
            try:body+=_ui_html('<p>Hauptordner (POSIX): <b>')+h.esc(a.smb_folder_right(cfg,a.snapshot(row['path']),who) if cfg else a.folder_right(a.snapshot(row['path']),who))+_ui_html('</b></p>')
            except Exception:body+=_ui_html('<p>Hauptordnerrechte nicht prüfbar.</p>')
            options=([('inherit','Eigene Regel entfernen – Gruppen/Standard verwenden')] if proto=='smb' else [])+[(k,a.LABEL[k]) for k in ('none','read','write')]+([('admin','SMB-Admin – Dateizugriff als root')] if proto=='smb' else [])
            current=request.form.get('level',a.direct_rule(cfg,name) if cfg else 'read')
            body+=_ui_html("<form method='post' class='share-form'>")+ui.token()+''.join("<input type='hidden' name='"+k+"' value='"+h.esc(v)+"'>" for k,v in dict(protocol=proto,key=key,subject=name).items())
            body+=ui.select('level','Neues Recht',options,current)
            if proto=='smb':
                body+=_ui_html("<p class='share-help'>„Kein Zugriff“ sperrt dieses Konto auch bei einer Erlaubnis über Gruppen. Eine geerbte Schreib-/Adminregel kann ein persönliches Leserecht übersteuern; solche Konflikte werden vor dem Speichern angezeigt.</p>")
                body+=ui.check('folder_acl','Ordnerrechte ebenfalls anpassen (nur Hauptordner)',request.form.get('folder_acl')=='1')
                body+=ui.check('confirm_admin','Mir ist bewusst: SMB-Admin umgeht normale Dateirechte als root',request.form.get('confirm_admin')=='1')
            body+=ui.check('defaults','Ordnerrecht auch an künftig neu angelegte Inhalte vererben',request.form.get('defaults')=='1')
            body+=_ui_html("<p class='share-help'>Ordneränderungen betreffen auch andere Freigaben desselben Ordners. Bestehende Dateien und Unterordner werden nicht rekursiv geändert. Neue SMB-Rechte werden nach erneutem Verbinden des Clients zuverlässig übernommen.</p><button class='btn'>Rechteänderung prüfen</button> <a class='btn' href='")+h.esc(url(proto,key))+_ui_html("'>Zurück</a></form></div>")
            return ui.page(ctx,_ui_html('Recht ändern'),body)
        except Exception as exc:return error(exc)
