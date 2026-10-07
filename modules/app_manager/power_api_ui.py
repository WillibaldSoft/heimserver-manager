"""Local Recovery API installation; remote hosts use the portable installer."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json,secrets
from flask import request,session,redirect
from .install_ui import esc,token
from . import install_jobs as jobs
from tools.power_api import install as engine
from tools.power_api.power_api import validate,VERSION

def card():
    try:
        state=engine.inspect();label={'missing':'Nicht installiert','managed':'Installiert','legacy':'Ältere API erkannt','unknown':'Manuell prüfen'}[state['kind']]
        info=label+(' · '+state['version'] if state['version'] else '')+' · Dienst: '+state['active']
    except Exception:info='Bestand nicht prüfbar'
    return _ui_html("<div class='card'><h3>Power &amp; Recovery API</h3><p>Server über IPMI einschalten und wieder erreichbar machen. Auf einem dauerhaft laufenden Rechner installieren.</p><p>")+esc(info)+_ui_html("</p><a class='btn' href='/apps/power_api/installer'>Installation, Update &amp; Einstellungen</a></div>")

def register(app,ctx):
    @app.get('/apps/power_api/status')
    def power_api_status():
        try:
            state=engine.inspect()
            if state['kind'] not in ('managed','legacy') or state['active']!='active':raise ValueError('Kein laufender unterstützter Recovery-Dienst auf diesem Rechner.')
            data=engine.api_status(state['config'])
            safe={k:data.get(k) for k in ('version','state_text','power','reachable','recover_active','phase','last_action','last_error','recover_count','reset_count')}
            body=_ui_html('<pre>')+esc(json.dumps(safe,ensure_ascii=False,indent=2))+_ui_html('</pre>')
        except Exception:body=_ui_html('<p>Status nicht verfügbar. Dienst, Bind-Adresse und IP-Freigaben prüfen. Es wurde keine Schaltaktion ausgelöst.</p>')
        return ctx.page(_ui_text('Recovery-Status'),_ui_html("<div class='card'><a class='btn' href='/apps/power_api/installer'>Zurück</a>")+body+_ui_html('</div>'),'Apps')

    @app.route('/apps/power_api/installer',methods=['GET','POST'])
    def power_api_setup():
        def page(body,code=200):return ctx.page(_ui_text('Power & Recovery API'),body,'Apps'),code
        try:state=engine.inspect()
        except Exception:return page(_ui_html("<div class='card'>Bestand nicht lesbar. Dienst und Dateirechte prüfen.</div>"),503)
        message=''
        if request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):return page(_ui_html('Formular abgelaufen. Bitte neu laden.'),403)
            try:
                if request.form.get('confirm')!='yes':raise ValueError('Installation/Update und angezeigte Grenzen bestätigen.')
                conf={k:request.form.get(k,'').strip() for k in ('server_name','server_ip','ipmi_host','ipmi_user','listen_host')}
                for k in ('port','wait_seconds','soft_wait_seconds','reset_wait_seconds'):conf[k]=int(request.form.get(k,''))
                conf['allowed_clients']=[v.strip() for v in request.form.get('allowed_clients','').replace('\n',',').split(',') if v.strip()]
                if not conf['allowed_clients']:raise ValueError('Mindestens einen erlaubten Client oder ein Netz angeben.')
                conf['allowed_clients']=list(dict.fromkeys(conf['allowed_clients']+['127.0.0.1/32',conf['listen_host']+'/32']))
                for k in ('allow_soft','allow_reset'):conf[k]=request.form.get(k)=='yes'
                validate(conf)
                if request.form.get('revision')!=state['revision'] or state['kind']=='unknown':raise ValueError('Bestand geändert oder nicht unterstützt. Seite neu laden.')
                password=request.form.get('password','')
                if state['kind']=='missing' and not password:raise ValueError('IPMI-Passwort fehlt.')
                if any(c in password for c in '\r\n\x00'):raise ValueError('Passwort enthält ungültige Steuerzeichen.')
                key=jobs.start(dict(app_id='power_api',label='Power & Recovery API'),conf['listen_host'],action='power_api',plan=dict(config=conf,revision=state['revision']),credentials=dict(password=password))
                return redirect('/apps/installers/jobs/'+key,303)
            except (ValueError,OSError) as exc:message=esc(str(exc))
        conf=state['config']
        body=_ui_html("<div class='card'><h2>Power &amp; Recovery API</h2><p>Installiert und verwaltet den Dienst <b>auf diesem Rechner</b>. Für einen anderen Dauerläufer dort dessen Manager öffnen oder das Installationspaket verwenden. Der Zielserver benötigt IPMI/BMC; dieser Rechner benötigt keinen OpenIPMI-Treiber.</p><p><a class='btn' href='/apps/manage'>Apps verwalten</a> <a class='btn' href='/apps/power_api/status'>Status prüfen (ohne Schaltaktion)</a> <a class='btn' href='/clients/power-api/download'>Installer für anderen Rechner herunterladen</a> <a class='btn' href='/clients/home-assistant.yaml'>Home-Assistant-YAML</a> <a class='btn' href='/settings/server-paths#field-recover_url'>Recovery-Adresse für Clients</a></p><p>Bestand: <b>")+esc(state['kind'])+_ui_html('</b> · ')+esc(state['version'] or '—')+_ui_html(' · Dienst: ')+esc(state['active'])+_ui_html(' · Verfügbar: ')+VERSION+_ui_html('</p>')
        if message:body+=_ui_html("<p class='err'>")+_ui_text(message)+_ui_html('</p>')
        if state['reason']:return page(body+_ui_html('<p>')+esc(_ui_text(state['reason']))+_ui_html('</p></div>'))
        body+=_ui_html("<p>Bekannte Altfassung 2.1-stable und Manager-Fassung 1.0 werden erkannt. Adressen, Benutzer, Passwort und Wartezeiten werden übernommen. Das Passwort wird nicht angezeigt. Vor Änderungen wird lokal eine geschützte Rücksicherung angelegt; bei Startfehlern werden die bisherigen Dateien zurückgesichert. Laufende Recovery-Aufträge sperren die Aktualisierung.</p><p><b>Änderungen gegenüber der Altfassung:</b> Quell-IP-Freigaben erforderlich; Passwort in geschützter systemd-Credential-Datei; Dienst ohne root; Aufträge im Hintergrund (202 = angenommen, Ergebnis über /status). /soft, /reset und /cycle als direkte Endpunkte entfallen. Keine Netzwerk-/Routeränderung. Beim Installieren wird kein Zielserver geschaltet.</p><p>Nur im vertrauenswürdigen LAN/VPN, keine öffentliche Portfreigabe. Zugriffe über einen Proxy müssen separat geschützt werden. Kein Nextcloud-Wake-Proxy enthalten.</p></div>")
        body+=_ui_html("<div class='card'><form method='post'>")+token()+_ui_html("<input type='hidden' name='revision' value='")+esc(state['revision'])+"'>"
        for k,label,default in [('server_name','Anzeigename des Zielservers','Server'),('server_ip','Zielserver IPv4',''),('ipmi_host','BMC / IPMI IPv4',''),('ipmi_user','BMC / IPMI Benutzer',''),('listen_host','Konkrete lokale LAN-IPv4 (0.0.0.0 durch LAN-Adresse ersetzen)','127.0.0.1'),('port','API-Port',8182),('wait_seconds','Wartezeit nach Einschalten (Sekunden)',180),('soft_wait_seconds','Wartezeit nach Soft (Sekunden)',180),('reset_wait_seconds','Wartezeit nach Reset (Sekunden)',180)]:
            body+=_ui_html("<p><label>")+esc(_ui_text(label))+_ui_html("<br><input required name='")+k+"' value='"+esc(str(conf.get(k,default)))+_ui_html("'></label></p>")
        body+=_ui_html("<p><label>Erlaubte Clients / IPv4-Netze (Komma oder neue Zeile)<br><textarea required name='allowed_clients'>")+esc('\n'.join(conf.get('allowed_clients',[])))+_ui_html("</textarea></label><br>Home Assistant, Client-PCs und ggf. Proxy angeben. Lokale Statusprüfung wird zusätzlich erlaubt. Keine automatische Freigabe des gesamten LAN.</p><p><label>IPMI-Passwort (bei Bestand leer = behalten)<br><input type='password' name='password' autocomplete='new-password'></label></p>")
        for k,label in [('allow_soft','IPMI Soft bei eingeschaltetem, nicht pingbarem Server erlauben'),('allow_reset','Einmaligen Reset nach erfolgloser Wartezeit erlauben')]:body+=_ui_html("<p><label><input type='checkbox' name='")+k+"' value='yes' "+('checked' if conf.get(k,False) else '')+"> "+esc(_ui_text(label))+_ui_html('</label></p>')
        body+=_ui_html("<p><b>Kein Ping ist kein eindeutiger Standby-Nachweis.</b> Soft kann einen laufenden Server herunterfahren; Reset kann Datenverlust verursachen. Bei der Altfassung werden diese bisherigen Optionen vorausgewählt und müssen bewusst bestätigt werden. Während einer Migration keine neuen Recovery-Aufrufe starten.</p><label><input required type='checkbox' name='confirm' value='yes'> Gezeigte Konfiguration und Änderungen bestätigen</label><p><button>Installieren / aktualisieren / Einstellungen übernehmen</button></p></form></div>")
        return page(body,400 if message else 200)
