"""Manager-specific HTTPS settings. Mutations use existing reviewed web-security jobs."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import html
from flask import Response
from . import manager_https as m, engine as e


def register(app, ctx, token, field, style):
    esc = lambda value: html.escape(str(value), quote=True)

    @app.route('/settings/https')
    def settings_https():
        try:
            state = m.load()
            host = state.get('hostname', m.default_hostname())
            port = state.get('port', 443)
            body = style + _ui_html("<div class='card'><h2>Manager-Zugang · HTTPS</h2><p>Privater Hostname im Heimnetz oder VPN. Eine öffentliche Domain kann später zusätzlich eingerichtet werden.</p>")
            body += _ui_html('<p>Privater Zugang: <b>') + (_ui_text('Aktiviert') if state.get('enabled') else _ui_text('Noch nicht aktiviert')) + _ui_html('</b></p>')
            if state.get('enabled'):
                url = 'https://' + host + (':' + str(port) if port != 443 else '')
                body += _ui_html("<p><a class='btn' href='") + esc(url) + "' target='_blank' rel='noopener noreferrer'>" + esc(url) + _ui_html('</a></p>')
            if state.get('enabled') and state.get('ip_address'):
                body += _ui_html('<p>Zusätzlich über IP: <a class="btn" href="') + esc(m.ip_url(state)) + '">' + esc(m.ip_url(state)) + _ui_html('</a></p>')
            body += _ui_html('<p>Erneuerung privates Zertifikat: <b>') + esc(e.service('server-manager-https-renew.timer')) + _ui_html('</b> · täglich, Erneuerung bei weniger als 30 Tagen Restlaufzeit. Öffentliche Zertifikate erneuert der Certbot-Timer.</p>')
            if state.get('public_hostname'):
                body += _ui_html('<p>Eingerichtete öffentliche Domain: <a href="https://') + esc(state['public_hostname']) + '">' + esc(state['public_hostname']) + _ui_html('</a> · Apache-Konfiguration unter <a href="/web-security">Web &amp; Sicherheit</a> prüfen/bearbeiten.</p>')
            body += _ui_html('<p><b>HTTPS erforderlich:</b> HTTP ist nur intern auf dem Server erreichbar. Für Browser und Agenten die HTTPS-Adresse verwenden. Bei bisherigen HTTP-Agenten neues Client-Profil importieren, Zertifikatvertrauen einrichten und HTTPS-Verbindung prüfen.</p></div>')
            body += _ui_html("<div class='card ws-form'><h3>Privaten HTTPS-Namen einrichten / ändern</h3><form method='post' action='/web-security/preview'>") + token() + _ui_html("<input type='hidden' name='action' value='manager_https_private'>")
            body += _ui_html('<p>Bei der Ersteinrichtung wird der kurze Rechnername vorgeschlagen: <b>') + esc(m.default_hostname()) + _ui_html('</b>. Ein bereits gespeicherter HTTPS-Name bleibt bei Updates und Änderungen des Rechnernamens erhalten.</p>')
            body += field('hostname', 'Privater HTTPS-Name (änderbar)', host) + field('port', 'HTTPS-Port', port, 'number') + field('networks', 'Zugelassene Client-Netze (CIDR, mit Leerzeichen trennen)', state.get('networks', m.DEFAULT_NETWORKS))
            body += field('ip_address', 'Zusätzlicher IP-Zugang: feste Server-IP (leer = aus)', state.get('ip_address', '')) + field('ip_port', 'Eigener HTTPS-Port für IP-Zugang', state.get('ip_port', 8443), 'number')
            body += _ui_html('<p>Domain und IP funktionieren gleichzeitig. IP-Zugang mit eigenem Port, standardmäßig 8443; an die angegebene Server-IP gebunden. Es gelten dieselben Zugangsnetze und die Manager-Anmeldung. Das private Stammzertifikat muss auf dem Client vertraut sein. Bei Änderung der Server-IP diesen Eintrag anpassen. Bestehende Websites bleiben unverändert.</p>')
            body += _ui_html('<p>Kurzer Rechnername oder vollständiger lokaler Name möglich, z. B. heimserver oder heimserver.home.arpa. Im lokalen DNS/Router auf die feste Server-IP legen. Alternativ auf jedem Client einen hosts-Eintrag setzen. Der Manager ändert weder Router noch DNS. Für globale IPv6-Adressen im Heimnetz dessen konkretes IPv6-Präfix ergänzen.</p><p><b>Name später ändern:</b> Gewünschten Namen oben eintragen, prüfen und anwenden. Das Serverzertifikat wird für diesen Namen ausgestellt; das vorhandene Stammzertifikat bleibt erhalten. Anschließend DNS-/hosts-Einträge und Lesezeichen anpassen sowie neue Client-Profile herunterladen und importieren. Der Linux-Rechnername wird dadurch nicht geändert. Bei fehlerhafter HTTPS-Konfiguration ist eine Reparatur über das Server-Terminal nötig; es gibt keinen externen HTTP-Ersatzzugang.</p><button class="btn">Einrichtung prüfen</button></form>')
            body += _ui_html('</div>')
            body += _ui_html("<div class='card'><details><summary><b>Privates Stammzertifikat und Namensauflösung auf Geräten einrichten</b></summary>")
            if (m.TLS/'root-ca.crt').exists():
                fingerprint = e.run(['openssl', 'x509', '-in', str(m.TLS/'root-ca.crt'), '-noout', '-fingerprint', '-sha256']).stdout.strip()
                body += _ui_html("<p><a class='btn' href='/settings/https/ca.crt'>Stammzertifikat herunterladen (.crt)</a></p><p>Fingerabdruck: <code>") + esc(fingerprint) + _ui_html('</code></p>')
            body += _ui_html('<p>Nur das öffentliche Stammzertifikat wird heruntergeladen. Private Schlüssel bleiben auf dem Server. Das Stammzertifikat ist hostbezogen; Zertifikaten dieses Servers nur nach Prüfung vertrauen. Der Fingerabdruck wird bei Erstinstallation auch im Terminal ausgegeben.</p>')
            body += _ui_html('<p><b>Windows:</b> CRT öffnen → Zertifikat installieren → Aktueller Benutzer → Alle Zertifikate in folgendem Speicher speichern → Vertrauenswürdige Stammzertifizierungsstellen. Danach Browser/Client-App neu öffnen. Für andere Windows-Benutzer separat importieren.</p>')
            body += _ui_html('<p><b>Debian/Mint:</b> Stammzertifikat als <code>/usr/local/share/ca-certificates/heimserver-manager.crt</code> kopieren und <code>sudo update-ca-certificates</code> ausführen. Falls ein Browser einen eigenen Zertifikatsspeicher verwendet, dort zusätzlich als Zertifizierungsstelle importieren.</p>')
            body += _ui_html('<p><b>DNS-Ersatz:</b> hosts-Datei unter Linux <code>/etc/hosts</code>, unter Windows <code>C:\\Windows\\System32\\drivers\\etc\\hosts</code>. Als Administrator ergänzen: <code>SERVER-IP ') + esc(host) + _ui_html('</code>. SERVER-IP durch die feste LAN-IP ersetzen. DNS-Einrichtung im Router gilt stattdessen für alle Geräte, die diesen DNS nutzen.</p>')
            body += _ui_html('<p>Die CA gilt zehn Jahre, das Serverzertifikat ein Jahr. Der tägliche Timer erneuert das Serverzertifikat; der CA-Wechsel benötigt erneuten Import auf den Geräten. Details und Fehler im Dienstprotokoll.</p></details></div>')
            body += _ui_html("<div class='card ws-form'><details><summary><b>Später: öffentliche Domain und Zertifikat</b></summary><p>Optional zusätzlich zum privaten Zugang. DNS und Portweiterleitung für 80/443 vorher einrichten. Ein eigenes Anmeldepasswort ist erforderlich. Router und DNS werden nicht automatisch geändert; der Manager wird über diesen Apache-VHost aus dem Internet erreichbar.</p><form method='post' action='/web-security/preview'>") + token() + _ui_html("<input type='hidden' name='action' value='manager_https_public'>")
            body += field('domain', 'Öffentliche Manager-Domain') + _ui_html("<label>Zertifikat<select name='tls'><option value='new'>Neues Let’s-Encrypt-Zertifikat</option><option value='existing'>Vorhandenes Let’s-Encrypt-Zertifikat verwenden</option></select></label>") + field('email', 'E-Mail für neues Zertifikat', '', 'email')
            body += _ui_html("<label><input type='checkbox' name='terms' value='1'> Für neues Zertifikat: <a href='https://letsencrypt.org/repository/' target='_blank' rel='noopener noreferrer'>Let’s-Encrypt-Bedingungen</a> akzeptieren</label><button class='btn'>Öffentlichen Zugang prüfen …</button></form></details></div>")
            return ctx.page(_ui_text('Manager-Zugang · HTTPS'), body, 'Einstellungen')
        except (OSError, ValueError) as exc:
            return ctx.page(_ui_text('Manager-Zugang · HTTPS'), _ui_html('<div class="card">') + esc(_ui_text(exc)) + _ui_html('</div>'), 'Einstellungen'), 400

    @app.route('/settings/https/ca.crt')
    def manager_ca_download():
        path = m.TLS/'root-ca.crt'
        if not path.is_file() or path.is_symlink(): return 'Stammzertifikat noch nicht vorhanden', 404
        return Response(path.read_bytes(), mimetype='application/x-x509-ca-cert', headers={'Content-Disposition': 'attachment; filename="heimserver-manager-ca.crt"', 'Cache-Control': 'no-store'})
