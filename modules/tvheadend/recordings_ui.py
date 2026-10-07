"""Completed recordings with explicit, CSRF-protected bulk deletion."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
import math
from datetime import datetime
from flask import request, session, redirect
from . import api, models
from .epg_ui import E


def completed():
    rows = {}
    for kind in ('grid_finished', 'grid_failed'):
        offset=0
        while True:
            data=api.request_json('/api/dvr/entry/'+kind, {'start':offset,'limit':1000,'sort':'start','dir':'DESC'})
            batch=api.entries(data)
            for row in batch:
                if row.get('uuid') and row.get('sched_status') not in ('scheduled', 'recording'):
                    rows[row['uuid']]=row
            offset+=len(batch)
            total=data.get('total') if isinstance(data,dict) else None
            if total is not None and offset>=int(total):break
            if total is None and len(batch)<1000:break
            if not batch or offset>=100000:raise api.TvheadendError('Aufnahmeliste unvollständig; keine Löschung freigegeben.')
    return rows


def label(row):
    item = models.normalize_recording(row)
    return str(item.get('title') or 'Ohne Titel')+' · '+str(item.get('channel') or '')


def register(app, ctx):
    @app.route('/tv/recordings/delete', methods=['POST'])
    def tv_recordings_delete():
        csrf = request.form.get('auth_csrf', '')
        if not csrf or not secrets.compare_digest(csrf, session.get('auth_csrf', '!')):
            return 'Formular abgelaufen. Aufnahmeliste erneut öffnen.', 403
        def page(body, status=200):
            return ctx.page(_ui_text('Aufnahmen löschen'), _ui_html("<div class='card'>")+body+_ui_html("<p><a class='btn' href='/tv/recordings'>Zurück zu Aufnahmen</a></p></div>"), 'TV'), status
        try:
            rows = completed()
            if request.form.get('confirm') != 'yes':
                ids = list(dict.fromkeys(request.form.getlist('recording')))
                if not ids or len(ids)>100 or any(i not in rows for i in ids):
                    return page(_ui_html('<p>Bitte 1 bis 100 abgeschlossene Aufnahmen auswählen. Die Liste hat sich möglicherweise geändert.</p>'), 400)
                token = secrets.token_urlsafe(32)
                session['tv_delete_pending'] = {'ids': ids, 'token': token}
                body = _ui_html('<h2>')+str(len(ids))+_ui_html(' Aufnahmen endgültig löschen?</h2><ul>')
                for ident in ids:body += _ui_html('<li>')+E(label(rows[ident]))+_ui_html('</li>')
                body += _ui_html('</ul><p>Die zugehörigen Aufnahmedateien werden durch Tvheadend endgültig vom Speicher gelöscht. Kein Papierkorb. Serienregeln bleiben bestehen.</p>')
                body += _ui_html("<form method='post'><input type='hidden' name='auth_csrf' value='")+E(csrf)+_ui_html("'><input type='hidden' name='token' value='")+E(token)+_ui_html("'><button class='btn' name='confirm' value='yes'>Markierte Aufnahmen endgültig löschen</button></form>")
                return page(body)
            pending = session.pop('tv_delete_pending', {})
            if not pending or not secrets.compare_digest(request.form.get('token', ''),pending.get('token','!')):
                return page(_ui_html('<p>Löschbestätigung ungültig oder bereits verwendet.</p>'), 400)
            ids = pending['ids']
            if any(i not in rows for i in ids):
                return page(_ui_html('<p>Aufnahmen haben sich geändert. Bitte erneut auswählen. Es wurde nichts gelöscht.</p>'), 409)
            results = []
            for ident in ids:
                try:
                    # Revalidate immediately before each mutation; never delete active timers.
                    if ident not in completed():
                        results.append(label(rows[ident])+': nicht mehr verfügbar; übersprungen.')
                        continue
                    api.request_json('/api/dvr/entry/remove', {'uuid': ident}, method='POST')
                    remaining = completed()
                    results.append(label(rows[ident])+(': Löschung nicht bestätigt; Tvheadend prüfen.' if ident in remaining else ': aus den gespeicherten Aufnahmen entfernt.'))
                except api.TvheadendError:
                    results.append(label(rows[ident])+': Ergebnis unklar / Fehler. Tvheadend prüfen; keine automatische Wiederholung.')
            session['tv_delete_result'] = results
            return redirect('/tv/recordings', code=303)
        except api.TvheadendError:
            return page(_ui_html('<p>Aufnahmen nicht abrufbar. Verbindung und Berechtigungen prüfen.</p>'), 502)


def render(ctx):
    body = _ui_html("<div class='card'><h2>Gespeicherte Aufnahmen</h2><p>Fertige und fehlgeschlagene Aufnahmen auswählen und gemeinsam löschen. Laufende und geplante Aufnahmen stehen unter <a href='/tv/upcoming'>Geplante Aufnahmen</a>.</p>")
    query = request.args.get('q','').strip()[:200]
    order = request.args.get('order','newest')
    if order not in ('newest','oldest'):order='newest'
    sorting = _ui_html("<label>Aufnahmealter <select name='order'>")+''.join(_ui_html("<option value='")+value+"'"+(' selected' if order==value else '')+">"+title+_ui_html("</option>") for value,title in [('newest','Neueste zuerst'),('oldest','Älteste zuerst')])+_ui_html("</select></label>")
    body += _ui_html("<form method='get'><label>Titel suchen <input type='search' name='q' value='")+E(query)+_ui_html("' placeholder='Aufnahmetitel eingeben'></label> ")+sorting+_ui_html(" <button class='btn'>Suchen</button> <a class='btn' href='/tv/recordings'>Alle Aufnahmen</a></form>")
    for message in session.pop('tv_delete_result', []):body += _ui_html('<p>')+E(_ui_text(message))+_ui_html('</p>')
    try:
        rows = completed()
    except api.TvheadendError:
        return ctx.page(_ui_text('TV Aufnahmen'),body+_ui_html('<p>Aufnahmen konnten nicht geladen werden. Verbindung prüfen.</p></div>'),'TV'),502
    rows = {ident:row for ident,row in rows.items() if query.casefold() in str(models.normalize_recording(row).get('title') or '').casefold()}
    def age_key(item):
        try:stamp=float(item[1].get('start'))
        except (ValueError,TypeError):stamp=float('nan')
        valid=math.isfinite(stamp) and stamp>0
        return (not valid, (-stamp if order=='newest' else stamp) if valid else 0, item[0])
    rows = dict(sorted(rows.items(),key=age_key))
    body += _ui_html('<p>')+str(len(rows))+_ui_html(' Aufnahmen gefunden.</p>')
    if not rows:return ctx.page(_ui_text('TV Aufnahmen'),body+_ui_html('<p>Keine passenden Aufnahmen.</p></div>'),'TV')
    csrf = session.setdefault('auth_csrf',secrets.token_urlsafe(32))
    body += _ui_html("<form method='post' action='/tv/recordings/delete'><input type='hidden' name='auth_csrf' value='")+E(csrf)+_ui_html("'><div style='overflow:auto'><table><thead><tr><th>Auswahl</th><th>Aufnahme / Sender</th><th>Beginn</th><th>Status</th></tr></thead><tbody>")
    for ident,row in rows.items():
        try:stamp=datetime.fromtimestamp(float(row.get('start',0))).strftime('%d.%m.%Y %H:%M')
        except (ValueError,TypeError,OverflowError,OSError):stamp='–'
        body += _ui_html("<tr><td><input type='checkbox' name='recording' value='")+E(ident)+"' aria-label='"+E(label(row))+_ui_html("'></td><td>")+E(label(row))+_ui_html('</td><td>')+E(stamp)+_ui_html('</td><td>')+E(_ui_text(row.get('status')) or row.get('sched_status',''))+_ui_html('</td></tr>')
    body += _ui_html("</tbody></table></div><p>Bis zu 100 Aufnahmen pro Löschvorgang. Die Liste umfasst fertige und fehlgeschlagene Aufnahmen.</p><button class='btn'>Markierte Aufnahmen löschen …</button></form></div>")
    return ctx.page(_ui_text('TV Aufnahmen'),body,'TV')
