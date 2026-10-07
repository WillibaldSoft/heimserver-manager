from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
from flask import request, redirect, send_file, session
import re, secrets
import os, json
from pathlib import Path

from .helpers import esc, CLIENT_SCRIPT, json_response, run, sudo_run, is_path_safe
from .status import status
from .samba import list_all_shares, write_share, delete_share, import_legacy_share
from .nfs import list_exports, upsert_export, delete_export
from .accounts import users, groups, user_groups, create_user, create_group, delete_group, set_user_groups, set_samba_password
from .acl import get_acl, apply_acl
from .permissions import right_from_samba, build_lists, options, explain_html
from .diagnostics import diagnostics


def _page(ctx, title, body, current='Freigaben'):
    from .workflow import token, page
    body=re.sub(r"(<form\b[^>]*method=[\"']post[\"'][^>]*>)", lambda m:m.group(1)+token(), body, flags=re.I)
    if os.geteuid()==0:body=re.sub(r"<input\b[^>]*name=[\"']sudo_password[\"'][^>]*>",'',body)
    return page(ctx,title,body)

def _sudo_field():
    if os.geteuid()==0:return ""
    return _ui_html("<p><b>Sudo-Passwort</b> <input name='sudo_password' type='password' autocomplete='current-password'> <small>wird nur für diese Aktion verwendet, nicht gespeichert.</small></p>")

def _checkbox(name, checked=False, label='aktiv'):
    return _ui_html("<label><input type='checkbox' name='%s' value='1'%s> %s</label>") % (esc(name), ' checked' if checked else '', esc(_ui_text(label)))

def _share_by_name(name):
    for s in list_all_shares():
        if s['name'] == name:
            return s
    return None

def register(app, ctx):
    from .workflow import register as register_workflow
    from .domain import register as register_domain
    @app.before_request
    def shares_csrf_guard():
        if (request.path.startswith('/freigaben') or request.path.startswith('/api/freigaben')) and request.method not in ('GET','HEAD','OPTIONS'):
            supplied=request.form.get('csrf','')
            if not supplied or not secrets.compare_digest(supplied,session.get('shares_csrf','')):
                return _page(ctx,'Formular abgelaufen',_ui_html("<div class='card'><p>Bitte Seite neu laden und die Aktion erneut ausführen.</p></div>")),403
    register_workflow(app,ctx)
    register_domain(app,ctx)
    from .user_admin_ui import register as register_user_admin
    register_user_admin(app,ctx,_page)
    @app.route('/freigaben/users', methods=['GET','POST'], strict_slashes=False)
    def shares_users():
        msg=''
        if request.method == 'POST':
            action=request.form.get('action','')
            sudo_password=request.form.get('sudo_password','')
            try:
                if action == 'create_user':
                    res=create_user(request.form.get('username','').strip(), request.form.get('password',''), request.form.get('full_name',''), request.form.get('shell','/bin/bash'), request.form.get('home')=='1', request.form.getlist('groups'), request.form.get('samba')=='1', sudo_password=sudo_password,uid=request.form.get('uid',''),primary_group=request.form.get('primary_group',''))
                    msg='Benutzer angelegt.' if res.get('ok') else 'Fehler: '+str(res)
                else:
                    msg='Bitte die neue Benutzer-Bearbeitungsseite verwenden.'
            except Exception as e: msg='Fehler: '+str(e)
        us=users(); gs=groups()
        body=_ui_html('<div class="card"><h2>Benutzer & Gruppenzuordnung</h2><p>Linux-Benutzer, Samba-Zugang und Gruppenmitgliedschaften verwalten. NFS verwendet dieselben Linux-Konten: UID und GID müssen auf Server und Client übereinstimmen. Für reine NFS-Konten Samba deaktivieren; kein Passwort nötig.</p>')
        if msg: body+=_ui_html('<p><b>%s</b></p>') % esc(_ui_text(msg))
        body+=_ui_html('</div>')
        body+=_ui_html('<div class="card"><details><summary>Benutzer anlegen</summary><form method="post"><input type="hidden" name="action" value="create_user"><table>')
        body+=_ui_html('<tr><td>Benutzername</td><td><input name="username" required></td></tr><tr><td>Name</td><td><input name="full_name"></td></tr><tr><td>Passwort</td><td><input name="password" type="password"></td></tr><tr><td>Shell</td><td><select name="shell"><option>/usr/sbin/nologin</option><option>/bin/bash</option></select></td></tr>')
        body+=_ui_html('<tr><td>UID (optional, für NFS)</td><td><input name="uid" type="number" min="1000" max="59999" placeholder="Automatisch"></td></tr><tr><td>Primäre Gruppe</td><td><select name="primary_group"><option value="">Automatisch</option>')+''.join(_ui_html('<option value="')+esc(g['name'])+'">'+esc(g['name'])+' · GID '+str(g['gid'])+_ui_html('</option>') for g in gs)+_ui_html('</select> <a href="/freigaben/groups" target="_blank" rel="noopener">Neue Gruppe anlegen</a></td></tr>')
        body+=_ui_html('<tr><td>Optionen</td><td>%s %s</td></tr>') % (_checkbox('home', False, 'Homeverzeichnis erzeugen'), _checkbox('samba', True, 'Samba-Benutzer aktivieren'))
        body+=_ui_html('<tr><td>Gruppen</td><td>')
        for g in gs: body+=_ui_html('<label><input type="checkbox" name="groups" value="%s"> %s</label> ') % (esc(g['name']), esc(g['name']))
        body+=_ui_html('</td></tr></table>')+_sudo_field()+_ui_html("<p><button class='btn'>Benutzer anlegen</button></p></form></details></div>")
        body+=_ui_html('<div class="card"><h3>Vorhandene Benutzer</h3><p>Gruppen einschließlich sudo sowie Linux- und SMB-Passwörter über „Benutzer bearbeiten“ verwalten. Änderungen benötigen dein aktuelles Manager-Administratorpasswort.</p><table><tr><th>Benutzer · UID/GID</th><th>Home / Shell</th><th>Gruppen</th><th>Aktion</th></tr>')
        from urllib.parse import quote
        for u in us:
            body+='<tr><td><b>'+esc(u['name'])+'</b><br>'+str(u['uid'])+' / '+str(u['gid'])+'</td><td>'+esc(u['home'])+'<br>'+esc(u['shell'])+'</td><td>'+esc(', '.join(user_groups(u['name'])))+'</td><td><a class="btn" href="/freigaben/users/edit?user='+quote(u['name'],safe='')+'">'+esc(_ui_text('Benutzer bearbeiten'))+'</a></td></tr>'
        body+='</table></div>'
        return _page(ctx, 'Benutzer & Gruppen', body)

    @app.route('/freigaben/groups', methods=['GET','POST'], strict_slashes=False)
    def shares_groups():
        msg=''
        if request.method == 'POST':
            sudo_password=request.form.get('sudo_password','')
            action=request.form.get('action','')
            name=request.form.get('groupname','').strip()
            if action == 'create_group':
                try:
                    res=create_group(name, password=sudo_password,gid=request.form.get('gid',''));msg='Gruppe angelegt.' if res.get('ok') else 'Fehler: '+str(res)
                except ValueError as exc:msg='Fehler: '+str(exc)
            elif action == 'delete_group': res=delete_group(name, password=sudo_password); msg='Gruppe gelöscht.' if res.get('ok') else 'Fehler: '+str(res)
        body=_ui_html('<div class="card"><h2>Gruppen</h2>')
        if msg: body+=_ui_html('<p><b>%s</b></p>') % esc(_ui_text(msg))
        body+=_ui_html('<form method="post"><input type="hidden" name="action" value="create_group">Neue Gruppe: <input name="groupname" required> GID (optional): <input name="gid" type="number" min="1000" max="59999" placeholder="Automatisch"> <input name="sudo_password" type="password" placeholder="sudo"> <button class="btn">Anlegen</button></form></div>')
        body+=_ui_html('<div class="card"><table><tr><th>Gruppe</th><th>GID</th><th>Mitglieder</th><th>Aktion</th></tr>')
        for g in groups():
            body+=_ui_html('<tr><td>%s</td><td>%s</td><td>%s</td><td><form method="post" onsubmit="return confirm(\'Gruppe löschen?\')"><input type="hidden" name="action" value="delete_group"><input type="hidden" name="groupname" value="%s"><input name="sudo_password" type="password" placeholder="sudo" style="width:90px"><button class="pill">Löschen</button></form></td></tr>') % (esc(g['name']), g['gid'], esc(', '.join(g['members'])), esc(g['name']))
        body+=_ui_html('</table></div>')
        return _page(ctx, 'Gruppen', body)

    @app.route('/freigaben/client-script', strict_slashes=False)
    def client_script():
        return send_file(CLIENT_SCRIPT, mimetype='text/x-shellscript', as_attachment=True, download_name='client-mount-manager-v2.3.4.sh')

    @app.route('/freigaben/diagnose', strict_slashes=False)
    def shares_diagnose():
        path=request.args.get('path','')
        d=diagnostics(path)
        body=_ui_html('<div class="card"><h2>Freigaben Diagnose</h2><p>Samba: <code>%s</code> NFS: <code>%s</code></p>') % (esc(d['smbd']), esc(d['nfs']))
        body+=_ui_html('<form><p>ACL-Pfad prüfen: <input name="path" value="%s" style="width:60%%"> <button class="btn">Prüfen</button></p></form></div>') % esc(path)
        body+=_ui_html('<div class="card"><h3>testparm</h3><pre>%s</pre></div>') % esc(d['testparm'].get('out') or d['testparm'].get('err') or '')
        body+=_ui_html('<div class="card"><h3>exportfs -v</h3><pre>%s</pre></div>') % esc(d['exportfs'].get('out') or d['exportfs'].get('err') or '')
        if 'getfacl' in d: body+=_ui_html('<div class="card"><h3>getfacl</h3><pre>%s</pre></div>') % esc(d['getfacl'].get('out') or d['getfacl'].get('err') or '')
        return _page(ctx, 'Freigaben Diagnose', body)

    @app.route('/api/freigaben/status')
    def api_status():
        return json_response(ctx, status())
