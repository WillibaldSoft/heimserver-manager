"""EPG recording selection; writes use fixed Tvheadend endpoints only."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import datetime
import secrets
import threading
import time
from urllib.parse import urlencode
from flask import request, session, redirect
from . import api, formatter
from .epg_ui import E

# Serializes duplicate submissions within this single-process manager.
_lock = threading.Lock()
_used = {}


def back_url(value):
    return value if value == '/tv/epg' or (value.startswith('/tv/epg?') and len(value) < 2000) else '/tv/epg'


def event_data(event_id):
    rows = api.entries(api.request_json('/api/epg/events/load', {'eventId': event_id}))
    event = next((r for r in rows if str(r.get('eventId')) == str(event_id)), None)
    if not event:
        raise ValueError('Sendung nicht mehr im EPG vorhanden. Bitte das Programm neu laden.')
    return event


def schedule(event, profile, action):
    if float(event.get('stop', 0)) <= time.time():
        raise ValueError('Diese Sendung ist bereits beendet.')
    if action not in ('once', 'series'):
        raise ValueError('Ungültige Aufnahmeauswahl.')
    if action == 'once' and event.get('dvrUuid'):
        return 'Für diese Sendung ist bereits eine Aufnahme vorhanden.'
    if action == 'series':
        if not event.get('serieslinkUri'):
            raise ValueError('Keine Serienkennung vorhanden. Bitte einmalig aufnehmen.')
        rules = api.entries(api.request_json('/api/dvr/autorec/grid', {'limit': 10000}))
        if any(r.get('enabled', True) and r.get('serieslink') == event['serieslinkUri'] and r.get('config_name') == profile for r in rules):
            return 'Für diese Serie ist bereits eine Aufnahme-Regel vorhanden.'
    endpoint = '/api/dvr/entry/create_by_event' if action == 'once' else '/api/dvr/autorec/create_by_series'
    result = api.request_json(endpoint, {'event_id': event['eventId'], 'config_uuid': profile}, method='POST')
    if not isinstance(result, dict) or not result.get('uuid'):
        raise api.TvheadendError('Keine Bestätigung')
    return 'Tvheadend hat die '+('Einzelaufnahme' if action == 'once' else 'Serienaufnahme')+' bestätigt.'


def register(app, ctx):
    @app.route('/tv/epg/record/<int:event_id>', methods=['GET', 'POST'])
    def tv_epg_record(event_id):
        back = back_url(request.values.get('back', '/tv/epg'))
        def page(body, status=200):
            return ctx.page(_ui_text('Sendung aufnehmen'), _ui_html("<div class='card'><a class='btn' href='")+E(back)+_ui_html("'>Zurück zum Programm</a> <a class='btn' href='/tv/upcoming'>Geplante Aufnahmen</a>")+body+_ui_html('</div>'), 'TV'), status
        if request.method == 'POST':
            csrf = request.form.get('auth_csrf', '')
            if not csrf or not secrets.compare_digest(csrf, session.get('auth_csrf', '!')):
                return page(_ui_html('<p>Formular abgelaufen. Bitte die Sendung erneut öffnen.</p>'), 403)
        try:
            event = event_data(event_id)
            profiles = api.entries(api.request_json('/api/dvr/config/grid', {'limit': 1000}))
            profiles = [p for p in profiles if p.get('uuid') and p.get('enabled', True)]
            if request.method == 'POST':
                profile = request.form.get('profile', '')
                if profile not in {p['uuid'] for p in profiles}:
                    raise ValueError('Aufnahmeprofil nicht verfügbar.')
                token = request.form.get('record_token', '')
                with _lock:
                    now = time.time()
                    for key in list(_used):
                        if _used[key] < now-3600: del _used[key]
                    if not token or token != session.get('tv_record_token') or token in _used or session.get('tv_record_event') != event_id:
                        raise ValueError('Auswahl bereits gesendet oder abgelaufen. Bitte geplante Aufnahmen prüfen.')
                    _used[token] = now
                    try:
                        message = schedule(event, profile, request.form.get('action'))
                    except api.TvheadendError:
                        message = 'Tvheadend hat die Anfrage nicht bestätigt. Verbindung und Aufnahmeberechtigung prüfen. Vor erneutem Senden geplante Aufnahmen bzw. Serienregeln in Tvheadend prüfen; die Anfrage könnte bereits angenommen worden sein.'
                    session['tv_record_result'] = (event_id, message)
                return redirect('/tv/epg/record/'+str(event_id)+'?'+urlencode({'back': back}), code=303)
            receipt = session.pop('tv_record_result', None)
            if receipt and receipt[0] == event_id:
                return page(_ui_html('<p>')+E(receipt[1])+_ui_html('</p>'))
            title = formatter.value(event.get('title', 'Ohne Titel'))
            stamp = lambda key: datetime.datetime.fromtimestamp(float(event[key])).strftime('%d.%m.%Y %H:%M')
            body = _ui_html('<h2>')+E(title)+_ui_html('</h2><p>')+E(event.get('channelName', ''))+' · '+E(stamp('start'))+'–'+E(stamp('stop'))+_ui_html('</p><p>')+E(formatter.value(event.get('description') or event.get('summary') or ''))+_ui_html('</p>')
            if float(event['stop']) <= time.time():return page(body+_ui_html('<p>Sendung bereits beendet.</p>'))
            if not profiles:return page(body+_ui_html('<p>Kein Aufnahmeprofil verfügbar. Aufnahmeberechtigung in Tvheadend prüfen.</p>'), 400)
            token = secrets.token_urlsafe(24)
            session['tv_record_token'] = token
            session['tv_record_event'] = event_id
            csrf = session.setdefault('auth_csrf', secrets.token_urlsafe(32))
            body += _ui_html("<form method='post'><input type='hidden' name='auth_csrf' value='")+E(csrf)+_ui_html("'><input type='hidden' name='record_token' value='")+E(token)+_ui_html("'><input type='hidden' name='back' value='")+E(back)+_ui_html("'><label>Aufnahmeprofil <select name='profile'>")
            for p in sorted(profiles, key=lambda p: str(p.get('name', ''))):
                body += _ui_html("<option value='")+E(p['uuid'])+"'>"+E(p.get('name') or _ui_text('Standard'))+_ui_html('</option>')
            body += _ui_html('</select></label><p>Speicherziel, Vor-/Nachlauf und Aufbewahrung gelten gemäß Aufnahmeprofil in Tvheadend.</p>')
            if event.get('dvrUuid'):body += _ui_html('<p>Für diese Sendung ist bereits eine Aufnahme vorhanden.</p>')
            else:body += _ui_html("<button class='btn' name='action' value='once'>1× aufnehmen</button> ")
            if event.get('serieslinkUri'):
                body += _ui_html("<button class='btn' name='action' value='series'>Serie aufnehmen</button><p>Tvheadend plant zukünftige Folgen anhand der Serienkennung des Senders.</p>")
            else:body += _ui_html("<button class='btn' disabled>Serie aufnehmen</button><p>Keine Serienkennung im EPG vorhanden. Diese Sendung kann einmalig aufgenommen werden.</p>")
            body += _ui_html('</form>')
            return page(body)
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            return page(_ui_html('<p>')+E(str(exc))+_ui_html('</p>'), 400)
        except api.TvheadendError:
            return page(_ui_html('<p>Sendung oder Aufnahmeprofile konnten nicht geladen werden. Verbindung und Aufnahmeberechtigung in Tvheadend prüfen.</p>'), 502)
