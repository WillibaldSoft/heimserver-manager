"""One place for app installation, removal and dashboard visibility."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
from flask import request, session, redirect
from . import install_catalog as c, install_jobs as jobs, lifecycle
from .install_ui import esc, token
from .registry import current_managers, get_manager
from .visibility import hidden_apps, removed_apps, set_hidden, set_removed


def register(app, ctx):
    def page(body, code=200):
        return ctx.page(_ui_text('Apps verwalten'), _ui_html("<div class='card'><h2>Apps verwalten</h2><p><a class='btn' href='/apps'>Zur App-Übersicht</a> <a class='btn' href='/apps/installers/new'>Neue Container-App</a></p><p>Installieren fügt ein Programm hinzu. Ausblenden ändert nur die Übersicht; die App läuft weiter. Beim Deinstallieren können Daten aufbewahrt oder bei unterstützten Installationen ausdrücklich endgültig gelöscht werden.</p></div>")+body, 'Apps'), code

    @app.before_request
    def manage_csrf():
        if request.method == 'POST' and (request.path in ('/apps/manage','/apps/manage/update-check') or request.path.endswith('/uninstall') or request.path.endswith('/reinstall')):
            if not secrets.compare_digest(request.form.get('csrf', ''), session.get('app_install_csrf', '!')):
                return page(_ui_html("<div class='card'>Formular abgelaufen. Bitte neu laden.</div>"), 403)

    @app.route('/apps/manage/update-check',methods=['POST'])
    def catalog_update_check():
        from .catalog_updates import catalog_check
        key=request.form.get('app_id','')
        if key not in c.recipes() and key!='docker':return page(_ui_html('Unbekannte App.'),400)
        try:
            result=catalog_check(key)
            from .plugin import _store_update_check
            _store_update_check(key,result)
            return page(_ui_html("<div class='card'><h3>Updateprüfung: ")+esc(result.get('app_label',key))+_ui_html("</h3><p><b>")+esc(_ui_text(result.get('label','Nicht prüfbar')))+_ui_html("</b></p><p>")+esc(_ui_text(result.get('message','')))+_ui_html("</p><p>Methode: ")+esc(result.get('method','—'))+_ui_html("</p><a class='btn' href='/apps/manage'>Zurück</a></div>"))
        except Exception:return page(_ui_html('Updateprüfung fehlgeschlagen. Verbindung und Installation prüfen.'),503)

    @app.route('/apps/drivers',methods=['GET'])
    def drivers():
        from .dddvb_ui import card as dddvb_card
        from .nvidia_ui import card as nvidia_card
        body=_ui_html("<div class='card'><h2>Treiber</h2><p>Digital Devices und NVIDIA: Hardware, Versionen, Installation und Updates. Die Treiberverwaltung ist ausschließlich in diesem Reiter zusammengefasst.</p></div>")
        return ctx.page(_ui_text('Treiber'),body+dddvb_card()+nvidia_card(),'Apps')

    @app.route('/apps/manage', methods=['GET', 'POST'])
    def apps_manage():
        if request.method == 'POST':
            app_id=request.form.get('app_id','')
            action=request.form.get('action')
            if app_id in ('dddvb','nvidia') and action in ('show','hide'):
                set_hidden(app_id,action=='hide')
                return redirect({'apps':'/apps','drivers':'/apps/drivers'}.get(request.form.get('return_to'),'/apps/manage'),303)
            manager=get_manager(app_id)
            if manager is None or action not in ('show', 'hide'):
                return page(_ui_html('Unbekannte App oder Aktion.'), 400)
            if action == 'show' and lifecycle.installation(manager)['state'] != 'installed':
                return page(_ui_html('Nur vollständig installierte Apps können eingeblendet werden.'), 409)
            set_removed(manager.app_id, False)
            set_hidden(manager.app_id, action == 'hide')
            return redirect('/apps/manage', 303)
        managers = {m.app_id:m for m in current_managers()}
        profiles = c.recipes(); names = {key:m.label for key,m in managers.items()}
        names.update({key:p['label'] for key,p in profiles.items()})
        if 'nextcloud_docker' in managers and 'nextcloud' not in managers:
            names.pop('nextcloud',None)
        hidden = hidden_apps() | removed_apps()
        body = _ui_html("<div class='card'><h3>Docker Engine & Compose</h3><p>Gemeinsame Grundlage für Container-Apps. Installation, Status und geschützte Deinstallation an einem Ort.</p><a class='btn' href='/apps/docker/installer'>Installieren / deinstallieren</a></div>")
        body += _ui_html("<form method='post' action='/apps/manage/update-check'>")+token()+_ui_html("<input type='hidden' name='app_id' value='docker'><button class='btn'>Docker-Updates prüfen</button></form><p>APT-Prüfungen verwenden die vorhandenen Paketlisten. <a href='/apps/apt'>Paketlisten aktualisieren</a>. Container-Prüfungen vergleichen den konfigurierten Image-Kanal.</p>")
        body+=_ui_html("<div class='card'><a class='btn' href='/apps/drivers'>Treiber verwalten</a><p>Digital Devices und NVIDIA: Status, Installation und Updates.</p></div>")
        from .power_api_ui import card as power_api_card
        body+=power_api_card()
        body+=_ui_html("<div class='card'><h3>Nextcloud bei Zugriff wecken</h3><p>Optionaler Wake-Gateway auf einem Dauerläufer, mit Recovery und Schlafblocker.</p><a class='btn' href='/apps/nextcloud/wake'>Einrichten / verwalten</a></div>")
        running = jobs.active()
        if running:
            body += _ui_html("<div class='card'><a href='/apps/installers/jobs/")+esc(running['id'])+_ui_html("'>Laufenden App-Auftrag anzeigen</a></div>")
        body += _ui_html("<div class='card' style='overflow-x:auto'><table><tr><th>App</th><th>Installation</th><th>App-Übersicht</th><th>Aktionen</th></tr>")
        labels = {'installed':'Installiert', 'missing':'Nicht installiert', 'partial':'Teilweise installiert', 'unknown':'Nicht prüfbar', 'broken':'Fehler bei der Prüfung'}
        for key, label in names.items():
            manager = managers.get(key)
            state = lifecycle.installation(manager)['state'] if manager else 'missing'
            installed = state == 'installed'
            visibility = 'Ausgeblendet' if key in hidden else 'Eingeblendet' if installed else 'Nicht eingeblendet'
            actions = [_ui_html("<form method='post' action='/apps/manage/update-check' style='display:inline'>")+token()+_ui_html("<input type='hidden' name='app_id' value='")+esc(key)+_ui_html("'><button class='btn'>Updates prüfen</button></form>")]
            if key=='pihole':actions.append(_ui_html("<a class='btn' href='/apps/pihole/installer/native'>Native Installation</a> <a class='btn' href='/apps/pihole/installer'>Docker / Installation prüfen</a>"))
            if key=='kvm' and installed:actions.append(_ui_html("<a class='btn' href='/apps/kvm/installer'>KVM / Bridge einrichten</a>"))
            if key=='shares_mounts':actions.append(_ui_html("<a class='btn' href='/apps/shares_mounts/installer'>SMB/NFS installieren / prüfen</a>"))
            saved = lifecycle.record(key)
            if saved:
                if saved['state'] == 'removed' and state == 'missing':
                    actions.append(_ui_html("<a class='btn' href='/apps/")+esc(key)+_ui_html("/reinstall'>Wieder installieren</a>"))
                else:
                    actions.append(_ui_html('<span>Aufbewahrten Deinstallationsstand prüfen; keine automatische Neuinstallation.</span>'))
            elif state == 'missing' and key in profiles:
                actions.append(_ui_html("<a class='btn' href='/apps/")+esc(key)+_ui_html("/installer'>Installieren</a>"))
            elif state in ('partial','unknown','broken') and key in profiles:
                actions.append(_ui_html("<a class='btn' href='/apps/")+esc(key)+_ui_html("/installer'>Installation prüfen</a>"))
            if installed:
                action = 'show' if key in hidden else 'hide'
                text = 'Einblenden' if action == 'show' else 'Nur ausblenden'
                actions.append(_ui_html("<form method='post' style='display:inline'>")+token()+_ui_html("<input type='hidden' name='app_id' value='")+esc(key)+_ui_html("'><input type='hidden' name='action' value='")+action+_ui_html("'><button class='btn'>")+text+_ui_html("</button></form>"))
                actions.append(_ui_html("<a class='btn' href='/apps/")+esc(key)+_ui_html("'>Verwalten</a>"))
                if key in lifecycle.PROTECTED and not getattr(manager, 'container', None):
                    actions.append(_ui_html('<small>')+esc(_ui_text(lifecycle.PROTECTED[key]))+_ui_html('</small>'))
                else:
                    actions.append(_ui_html("<a class='btn' href='/apps/")+esc(key)+_ui_html("/uninstall'>Deinstallieren …</a>"))
            body += _ui_html('<tr><td><b>')+esc(_ui_text(label) if key in c.CATALOG or key=='server_manager' else label)+_ui_html('</b></td><td>')+esc(_ui_text(labels.get(state, _ui_text(state))))+(' · '+esc(manager.installation_mode) if manager and hasattr(manager,'installation_mode') else '')+_ui_html('</td><td>')+_ui_text(visibility)+_ui_html('</td><td>')+' '.join(actions)+_ui_html('</td></tr>')
        return page(body+_ui_html('</table></div>'))

    @app.route('/apps/<app_id>/uninstall', methods=['GET', 'POST'])
    def uninstall(app_id):
        manager = get_manager(app_id)
        if manager is None:return page(_ui_html('App nicht gefunden.'), 404)
        try:
            purge=request.values.get('mode')=='purge'
            plan = lifecycle.plan(manager,purge=purge)
            if request.method == 'POST':
                confirmed = session.pop('app_remove_plan_'+app_id, None)
                if not confirmed:raise c.Invalid('Die Vorschau ist abgelaufen oder wurde bereits abgesendet. Bitte erneut öffnen und bestätigen.')
                if confirmed != lifecycle.digest(plan):raise c.Invalid('Der Installationsstand hat sich seit der Vorschau geändert. Bitte die aktuelle Löschvorschau erneut prüfen.')
                if request.form.get('confirm') != app_id:raise c.Invalid('Die Bestätigung zum Deinstallieren wurde nicht gesetzt.')
                if purge and request.form.get('erase_name','').strip()!=app_id:raise c.Invalid('Zum endgültigen Löschen bitte die App-ID exakt eingeben.')
                if plan['blocked']:raise c.Invalid(plan['blocked'])
                key = jobs.start({'app_id':app_id, 'label':manager.label}, '127.0.0.1', action='uninstall', plan=plan)
                return redirect('/apps/installers/jobs/'+key, 303)
            body = _ui_html("<div class='card'><h3>")+esc(_ui_text(manager.label))+_ui_html(' deinstallieren</h3>')
            body+=_ui_html("<p><a class='btn' href='?mode=keep'>Daten aufbewahren</a> <a class='btn err' href='?mode=purge'>App und Daten endgültig entfernen</a></p>")
            if plan['blocked']:
                body += _ui_html('<p>')+esc(plan['blocked'])+_ui_html('</p>')
            else:
                session['app_remove_plan_'+app_id] = lifecycle.digest(plan)
                body += _ui_html('<ul>')+''.join(_ui_html('<li>')+esc(item)+_ui_html('</li>') for item in plan['items'])+_ui_html('</ul>')
                if purge:
                    body+=_ui_html('<p><strong>Unwiderruflich: Alle Dateien im genannten App-Verzeichnis werden gelöscht – auch dort gespeicherte Medien. Es wird keine Rücksicherung angelegt.</strong> Extern eingebundene Medien, andere Apps, Docker Engine, bestehende Backups und Manager-Auftragsprotokolle bleiben erhalten.</p>')
                    if plan['purge']['kept']:body+=_ui_html('<p>Zusätzlich erhalten: ')+esc('; '.join(plan['purge']['kept']))+_ui_html('</p>')
                    body+=_ui_html("<form method='post'>")+token()+_ui_html("<input type='hidden' name='mode' value='purge'><p>Zur Bestätigung App-ID <b>")+esc(app_id)+_ui_html("</b> eingeben: <input name='erase_name' required autocomplete='off'></p><label><input type='checkbox' name='confirm' value='")+esc(app_id)+_ui_html("' required> App und angezeigte Daten endgültig löschen</label><p><button class='btn err'>Unwiderruflich deinstallieren</button></p></form>")
                else:
                    body += _ui_html('<p>Die App ist anschließend nicht mehr verfügbar. Persistente Daten, Konfiguration, Datenbank-Volumes und Images bleiben erhalten. Temporäre Dateien innerhalb entfernter Container werden gelöscht. Über „Wieder installieren“ lässt sich der aufbewahrte Stand erneut einrichten.</p>')
                    body += _ui_html("<form method='post'>")+token()+_ui_html("<input type='hidden' name='mode' value='keep'><label><input type='checkbox' name='confirm' value='")+esc(app_id)+_ui_html("' required> ")+esc(_ui_text(manager.label))+_ui_html(" deinstallieren und Daten aufbewahren</label><p><button class='btn err'>Jetzt deinstallieren</button></p></form>")
            return page(body+_ui_html("<p><a class='btn' href='/apps/manage'>Zurück zu Apps verwalten</a></p></div>"))
        except (c.Invalid, lifecycle.UpdateError, OSError, ValueError) as exc:
            message=str(exc) or 'Die Deinstallation konnte nicht gestartet werden.'
            return page(_ui_html("<div class='card' role='alert' style='border-left:4px solid #fca5a5'><h3>Deinstallation nicht gestartet</h3><p>")+esc(_ui_text(message))+_ui_html("</p><a class='btn' href='/apps/")+esc(app_id)+"/uninstall?mode="+('purge' if request.values.get('mode')=='purge' else 'keep')+_ui_html("'>Vorschau erneut öffnen</a> <a class='btn' href='/apps/manage'>Apps verwalten</a></div>"),409)

    @app.route('/apps/<app_id>/reinstall', methods=['GET', 'POST'])
    def reinstall(app_id):
        manager = get_manager(app_id)
        if manager is None:return page(_ui_html('App nicht gefunden.'), 404)
        try:
            saved = lifecycle.record(app_id)
            if not saved or saved['state'] != 'removed':raise c.Invalid('Kein aufbewahrter Installationsstand vorhanden.')
            if request.method == 'POST':
                key = jobs.start({'app_id':app_id, 'label':manager.label}, '127.0.0.1', action='restore')
                return redirect('/apps/installers/jobs/'+key, 303)
            return page(_ui_html("<div class='card'><h3>")+esc(_ui_text(manager.label))+_ui_html(" wieder installieren</h3><p>Die aufbewahrte Installation mit bisherigen Daten und Einstellungen wieder einrichten. Dies ist kein Versionsupdate.</p><form method='post'>")+token()+_ui_html("<button class='btn'>Wieder installieren</button></form></div>"))
        except (c.Invalid, lifecycle.UpdateError, OSError, ValueError) as exc:return page(_ui_html('<p>')+esc(_ui_text(exc))+_ui_html('</p>'), 409)
