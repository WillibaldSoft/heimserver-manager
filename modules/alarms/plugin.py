"""Central alarm settings and delivery preview."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import datetime,html,secrets
from flask import request,session,redirect
from . import engine as e,sources
E=lambda value:html.escape(str(value),quote=True)
def register(app,ctx):
    e.initialize(ctx)
    @app.route('/alarme',methods=['GET','POST'])
    def alarms():
        message=session.pop('alarm_message','');code=200
        if request.method=='POST':
            if not secrets.compare_digest(request.form.get('auth_csrf',''),session.get('auth_csrf','!')):return 'Formular abgelaufen.',403
            try:
                action=request.form.get('action')
                if action=='save':e.save(ctx,request.form);message='Alarm-Einstellungen gespeichert.'
                elif action=='preview':message=e.check(ctx,send=False)
                elif action=='send':message=e.check(ctx,send=True)
                elif action=='test':
                    success=e.publish(e.config(ctx),'Heimserver Manager · Test','Die ntfy-Verbindung funktioniert.')
                    message='Testmeldung gesendet.' if success else 'Testmeldung nicht gesendet. Aktivierung, Topic, Token und Erreichbarkeit prüfen.'
                else:raise ValueError('Unbekannte Aktion.')
                session['alarm_message']=message
                return redirect('/alarme',303)
            except ValueError as exc:message=str(exc);code=400
        cfg=e.config(ctx);rows,state=e.status(ctx)
        rows=[r for r in rows if r['source'] in cfg['sources']]
        token=session.setdefault('auth_csrf',secrets.token_urlsafe(32))
        hidden="<input type='hidden' name='auth_csrf' value='"+E(token)+"'>"
        def checkbox(name,label,on):return _ui_html("<label style='display:block;margin:10px 0'><input type='checkbox' name='")+name+"' value='1'"+(' checked' if on else '')+'> '+E(_ui_text(label))+_ui_html('</label>')
        def field(name,label,value,kind='text'):return _ui_html("<label style='display:block;margin:10px 0'>")+E(_ui_text(label))+_ui_html("<br><input type='")+kind+"' name='"+name+"' value='"+E(value)+_ui_html("' style='max-width:95%;width:450px'></label>")
        body=_ui_html("<div class='card'><h2>Alarme · ntfy</h2><p>Wichtige Warnungen aus ausgewählten Modulen an einem Ort. Prüfrhythmus und tägliche Erinnerung sind unten einstellbar. Es gilt die lokale Serverzeit. Im Schlafzustand findet keine Prüfung statt.</p>")
        if message:body+=_ui_html('<p><b>')+E(_ui_text(message))+_ui_html('</b></p>')
        body+=_ui_html('<p>Automatische Prüfung: <b>')+(_ui_text('Aktiv') if cfg['automatic'] else _ui_text('Aus'))+_ui_html('</b> · ntfy-Versand: <b>')+(_ui_text('Aktiv') if cfg['enabled'] else _ui_text('Aus'))+_ui_html('</b></p>')
        if state.get('checked'):body+=_ui_html('<p>Letzte Prüfung: ')+E(datetime.datetime.fromtimestamp(float(state['checked'])).strftime('%d.%m.%Y %H:%M:%S'))+' · '+E(state.get('summary',''))+_ui_html('</p>')
        body+=_ui_html("<form method='post'>")+hidden
        for value,label in [('preview','Jetzt prüfen (ohne Versand)'),('send','Prüfen und fällige Alarme senden'),('test','ntfy-Testmeldung senden')]:body+=_ui_html("<button class='btn' name='action' value='")+value+"'>"+_ui_text(label)+_ui_html('</button> ')
        body+=_ui_html('</form><p>Test und manuelle Prüfung verwenden die bereits gespeicherten Einstellungen.</p></div>')
        body+=_ui_html("<div class='card'><h3>Aktuelle Warnungen</h3>")
        if not rows:body+=_ui_html('<p>Keine gespeicherten Warnungen für die ausgewählten Quellen. Bei Bedarf zuerst prüfen.</p>')
        else:
            body+=_ui_html('<table><tr><th>Modul</th><th>Stufe</th><th>Meldung</th><th>Letzter Versand</th></tr>')
            for row in rows:
                stamp=datetime.datetime.fromtimestamp(row['last_sent']).strftime('%d.%m. %H:%M') if row['last_sent'] else 'Noch nicht gesendet'
                body+=_ui_html('<tr><td>')+E(_ui_text(sources.LABELS[row['source']]))+_ui_html('</td><td>')+E(row['level'])+_ui_html('</td><td>')+E(row['text'])+_ui_html('</td><td>')+E(stamp)+_ui_html('</td></tr>')
            body+=_ui_html('</table>')
        body+=_ui_html("</div><div class='card'><h3>Versand & Überwachung</h3><form method='post'>")+hidden
        body+=checkbox('ntfy_enabled','ntfy-Versand erlauben',cfg['enabled'])+checkbox('alarms_automatic','Automatisch prüfen und fällige Alarme senden',cfg['automatic'])
        body+=field('ntfy_url','ntfy-Server',cfg['url'])+field('ntfy_topic','Topic',cfg['topic'])+field('ntfy_token','Token (leer lassen = vorhandenen Token behalten)','',kind='password')
        body+=_ui_html('<p>Token hinterlegt: ')+(_ui_text('Ja') if cfg['token'] else _ui_text('Nein'))+_ui_html('</p>')+checkbox('clear_token','Gespeicherten Token entfernen',False)
        body+=checkbox('alarms_details','Details mitsenden (kann lokale Pfade, Dienstnamen oder Domains enthalten)',cfg['details'])
        body+=_ui_html('<p>Speicheralarme enthalten immer Gerät, Mount-Namen und Mountpunkte zur eindeutigen Zuordnung. Andere Quellen senden ohne Details nur eine allgemeine Modulwarnung. Der Topic-Name und ein hinterlegter Token werden nur an den konfigurierten ntfy-Server übertragen.</p>')
        body+=field('alarms_interval_minutes','Prüfintervall in Minuten (1–1440)',cfg['interval'],kind='number')
        body+=checkbox('alarms_daily_enabled','Bestehende Alarme einmal täglich erneut senden',cfg['daily'])
        body+=field('alarms_daily_time','Tägliche Erinnerung um (Serverzeit)',cfg['daily_time'],kind='time')
        body+=_ui_html('<p>Unveränderte Warnungen werden zur gewählten Uhrzeit erneut gesendet, unabhängig vom Prüfintervall (bis zu 30 Sekunden Verzögerung). Nach einer Unterbrechung wird die heutige Erinnerung bei der nächsten Prüfung nachgeholt. Neue Warnungen werden bei der nächsten Prüfung gesendet. Bei Versandfehlern frühestens nach fünf Minuten erneut versuchen.</p><h3>Alarmquellen</h3>')
        for key,label in sources.LABELS.items():body+=checkbox('alarms_source_'+key,label,key in cfg['sources'])
        body+=_ui_html('<p>Sicherungen: als erforderlich markierte Backup-Überwachungen und letzter zentraler Backupfehler. DynDNS: Anbieterfehler oder veraltete Prüfung. Zertifikate: ab 30 Tagen Restlaufzeit, kritisch ab 7 Tagen. Virtuelle Maschinen: abgestürzte VMs, libvirt-Verbindungsfehler, neuester fehlgeschlagener/unterbrochener Auftrag je VM und Aktion der letzten sieben Tage sowie VMs, die fünf Minuten nach der Herunterfahr-Anfrage noch aktiv sind. Auch abgebrochene manuelle Server-Aktionen werden gemeldet. Ein erfolgreicher Folgeauftrag derselben Aktion löst den Auftragsalarm auf.</p>')
        from modules.storage_monitor.helpers import setting
        body+=field('disk_warn_percent','Speicherwarnung ab Belegung (%)',setting(ctx,'disk_warn_percent','90'),'number')+field('temp_warn_c','SMART-Temperaturwarnung (°C)',setting(ctx,'temp_warn_c','55'),'number')
        body+=_ui_html('<h3>Zu überwachende Dienste</h3><p>Nur Dienste auswählen, die auf diesem Server dauerhaft laufen sollen. Gilt bei aktivierter Alarmquelle Systemdienste.</p>')
        for key,label in sources.SERVICES.items():body+=checkbox('alarms_service_'+key,label,key in cfg['services'])
        body+=_ui_html("<button class='btn' name='action' value='save'>Speichern</button></form></div>")
        return ctx.page(_ui_text('Alarme'),body,'Alarme'),code
    e.start(app,ctx)
