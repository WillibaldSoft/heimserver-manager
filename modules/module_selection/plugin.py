from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
from flask import request,session,redirect,jsonify
from . import config as c

def register(app,ctx):
    @app.before_request
    def selected_modules():
        path=request.path
        network=any(path==p or path.startswith(p+'/') for p in ('/heimnetz','/presence','/clients','/api/clients','/api/presence','/api/heimnetz'))
        tv=path=='/tv' or path.startswith(('/tv/','/api/tv/'))
        if (network and not c.network_enabled()) or (tv and not c.tv_visible()):
            if request.method=='GET' and not path.startswith('/api/'):return redirect('/settings/modules',303)
            return jsonify(ok=False,error='module_disabled',settings='/settings/modules'),503
    @app.route('/settings/modules',methods=['GET','POST'])
    def module_selection():
        session.setdefault('module_selection_csrf',secrets.token_urlsafe(32))
        message='';error=''
        if request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session['module_selection_csrf']):return 'Formular abgelaufen.',403
            try:
                c.save(dict(network=request.form.get('network')=='1',tv=request.form.get('tv'),interface=request.form.get('interface',''),cidr=request.form.get('cidr','')),request.form.get('revision',''))
                message='Modulauswahl gespeichert. Änderungen gelten sofort; ein bereits laufender Scan kann noch kurz auslaufen. Daten und installierte Programme bleiben erhalten.'
            except (ValueError,OSError) as exc:error=str(exc)
        d=c.load();e=lambda v:ctx.esc(str(v));detected=c.detect_lan()
        body=_ui_html("<div class='card'><h2>Module auf diesem Server auswählen</h2><p>Die zentrale Heimnetzüberwachung wird normalerweise nur auf dem Hauptserver benötigt. Die Auswahl betrifft ausschließlich diesen Rechner. DynDNS, Freigaben, Anwendungen, Sicherungen und die übrige Serververwaltung bleiben separat verfügbar.</p>")
        if message:body+=_ui_html("<p class='ok'>")+e(_ui_text(message))+_ui_html('</p>')
        if error:body+=_ui_html("<p class='err'>")+e(_ui_text(error))+_ui_html('</p>')
        body+=_ui_html("<form method='post'><input type='hidden' name='csrf' value='")+e(session['module_selection_csrf'])+_ui_html("'><input type='hidden' name='revision' value='")+e(c.revision())+_ui_html("'><h3>Heimnetz & Anwesenheit</h3><label><input type='checkbox' name='network' value='1' ")+('checked' if d['network'] else '')+_ui_html("> Geräteerkennung, Anwesenheit und Client-Agenten aktivieren</label><p>Hauptserver: aktivieren. Nebenserver: bei Bedarf abschalten. Im ausgeschalteten Zustand gibt es keine Netzwerkscans, keine Annahme von Client-Meldungen und keine Schlafblocker durch diese Geräte/Agenten. Bestehende Geräte und Einstellungen werden aufbewahrt.</p>")
        body+=_ui_html('<p>Automatisch erkannt: ')+(e(detected['interface']+' · '+detected['cidr']) if detected else _ui_text('Kein eindeutiges LAN; Werte manuell angeben.'))+_ui_html('</p>')
        try:
            interface,net=c.network_values();body+=_ui_html('<p>Aktuell verwendete Vorgabe: ')+e(interface)+' · '+e(net)+_ui_html('</p>')
        except ValueError as exc:body+=_ui_html('<p>')+e(_ui_text(exc))+_ui_html('</p>')
        body+=_ui_html("<p><label>LAN-Schnittstelle (leer = automatisch)<br><input name='interface' value='")+e(d['interface'])+_ui_html("' maxlength='15'></label></p><p><label>IPv4-Netz (leer = Serverpfade oder automatische Erkennung)<br><input name='cidr' value='")+e(d['cidr'])+_ui_html("' placeholder='z. B. 192.168.1.0/24'></label></p><h3>TV & Aufnahmen</h3><label>TV-Modul <select name='tv'>")
        for key,label in [('auto','Automatisch – nur bei installiertem oder eingerichtetem TVHeadend'),('on','Aktiv – auch bei aktuell nicht erreichbarem TVHeadend'),('off','Deaktiviert – keine TV-Blocker und keine TV-Aufwachplanung')]:body+=_ui_html("<option value='")+key+"' "+('selected' if d['tv']==key else '')+">"+_ui_text(label)+_ui_html('</option>')
        body+=_ui_html("</select></label><p>Automatisch blendet den Bereich ohne TVHeadend aus. Eine konfigurierte entfernte Instanz bleibt sichtbar und überwacht. Deaktivieren beendet die TV-Überwachung dieses Managers; laufende Aufnahmen schützen den Server dann nicht vor dem Schlafen. TVHeadend selbst wird nicht beendet oder deinstalliert.</p><button class='btn'>Modulauswahl speichern</button></form></div>")
        return ctx.page(_ui_text('Modulauswahl'),body,'Einstellungen'),400 if error else 200
