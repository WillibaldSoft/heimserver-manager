"""Service inventory and mapping, with a separate reviewed proxy setup wizard."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import hashlib,json,re,shlex,socket,ssl,subprocess,time
from pathlib import Path
from urllib.parse import urlsplit
from flask import request,redirect
from . import engine as e

FILE=e.CONFIG.parent/'dyndns-targets.json'
SITES=Path('/etc/apache2/sites-enabled')
MODES={'unknown':'Noch nicht zugeordnet','direct':'Direkter Zugang','proxy':'Reverse Proxy – Domain bleibt sichtbar'}

def load():
    if not FILE.exists():return {}
    data=json.loads(FILE.read_text())
    if not isinstance(data,dict):raise e.Problem('Ungültige Zielzuordnungen.')
    return data

def revision():return hashlib.sha256(FILE.read_bytes() if FILE.exists() else b'').hexdigest()

def validate(data):
    host=e.hostname(data.get('host',''))
    service=data.get('service','').strip();target=data.get('target','').strip()
    mode=data.get('mode','unknown');scheme=data.get('scheme','https')
    if mode not in MODES or scheme not in ('http','https'):raise e.Problem('Ungültige Zugangsart.')
    if len(service)>100 or len(target)>253 or any(ord(c)<32 for c in service+target):raise e.Problem('Ungültige Dienst- oder Zielangabe.')
    if target:
        try:socket.inet_pton(socket.AF_INET6,target)
        except OSError:e.hostname(target)
    ports=[]
    for key in ('port','internal_port'):
        value=data.get(key,'').strip()
        if value and (not value.isdigit() or not 1<=int(value)<=65535):raise e.Problem('Ports müssen zwischen 1 und 65535 liegen.')
        ports.append(int(value) if value else None)
    return host,dict(service=service,target=target,mode=mode,scheme=scheme,port=ports[0],internal_port=ports[1])

def safe_url(value):
    try:
        u=urlsplit(value.split('%{',1)[0])
        if u.scheme not in ('http','https') or not u.hostname:return ''
        host=u.hostname
        if ':' in host:host='['+host+']'
        return u.scheme+'://'+host+(':'+str(u.port) if u.port else '')
    except ValueError:return ''

def apache():
    result={}
    for file in sorted(SITES.glob('*.conf')):
        try:
            text=file.read_text()
            if len(text)>1024*1024:continue
            for match in re.finditer(r'<VirtualHost\s+([^>]+)>(.*?)</VirtualHost\s*>',text,re.I|re.S):
                names=[];targets=[];root='';tls=False
                for line in match[2].splitlines():
                    try:parts=shlex.split(line,comments=True)
                    except ValueError:continue
                    if not parts:continue
                    key=parts[0].lower()
                    if key in ('servername','serveralias'):
                        for value in parts[1:]:
                            try:names.append(e.hostname(value))
                            except e.Problem:pass
                    if key=='alias' and len(parts)==3:targets.append('Lokaler Pfad '+parts[1]+' → '+parts[2])
                    if key=='documentroot' and len(parts)==2:root=parts[1]
                    if key=='sslengine' and parts[1:]==['on']:tls=True
                    if key=='proxypass' and len(parts)>=3:
                        value=safe_url(parts[2])
                        if value:targets.append('Proxy → '+value)
                    if key in ('redirect','rewriterule'):
                        for part in parts[1:]:
                            value=safe_url(part)
                            if value:targets.append('Weiterleitung → '+value)
                for name in names:
                    result.setdefault(name,[]).append(dict(source=file.name,listen=match[1],tls=tls,targets=sorted(set(targets)),root=root))
        except (OSError,UnicodeError):continue
    return result

def probe(host,port=443):
    result={'checked':time.strftime('%d.%m.%Y %H:%M:%S'),'dns':{},'tls':''}
    for kind in ('A','AAAA','CNAME'):
        try:
            r=subprocess.run(['dig','+time=2','+tries=1','+short',kind,host],capture_output=True,text=True,timeout=4)
            result['dns'][kind]=r.stdout.strip()[:1000] if r.returncode==0 else 'Abfrage fehlgeschlagen'
        except (OSError,subprocess.TimeoutExpired):result['dns'][kind]='Abfrage nicht verfügbar'
    try:
        # Resolve once, connect with bounded timeout; no HTTP request or redirects.
        r=subprocess.run(['getent','ahosts',host],capture_output=True,text=True,timeout=4)
        ip=r.stdout.split()[0]
        with socket.create_connection((ip,port),timeout=4) as raw:
            with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as conn:
                result['tls']='Zertifikat gültig für Hostname; Ablauf: '+conn.getpeercert().get('notAfter','unbekannt')
    except (OSError,ValueError,IndexError,subprocess.TimeoutExpired):result['tls']='TLS nicht bestätigt (Erreichbarkeit, Port oder Zertifikat prüfen).'
    return result

def register(app,page,token,hidden,field,select,esc):
    from modules.web_security import reverse_proxy
    reverse_proxy.register(app,page,esc)
    @app.route('/dyndns/targets',methods=['GET','POST'])
    def dyndns_targets():
        notice='';checks={}
        try:
            mappings=load();sites=apache();providers=e.load()['providers']
            hosts=sorted(set(mappings)|set(sites)|{p['host'] for p in providers})
            if request.method=='POST':
                if request.form.get('action')=='check':
                    host=e.hostname(request.form.get('host',''))
                    if host not in hosts:raise e.Problem('Host nicht in der Übersicht vorhanden.')
                    checks[host]=probe(host,mappings.get(host,{}).get('port') or 443)
                elif request.form.get('action')=='save':
                    host,data=validate(request.form)
                    with e.lock():
                        if request.form.get('revision')!=revision():raise e.Problem('Zuordnungen wurden inzwischen geändert. Seite neu laden.')
                        mappings=load();mappings[host]=data
                        e.atomic(FILE,json.dumps(mappings,ensure_ascii=False,indent=2)+'\n')
                    return redirect('/dyndns/targets?saved=1',303)
                else:raise e.Problem('Unbekannte Aktion.')
            if request.args.get('saved'):notice='Zuordnung gespeichert. DNS und Weiterleitungen wurden nicht geändert.'
            body=_ui_html("<div class='card'><h2>Ziele & Dienste</h2><p>Domain aufklappen, um Ziel und Einstellungen zu sehen.</p>")+(_ui_html('<p>')+esc(notice)+_ui_html('</p>') if notice else '')+_ui_html("<p><a class='btn' href='/dyndns/proxy'>Verbindung einrichten …</a> <a class='btn' href='/apps/nextcloud/wake'>Nextcloud bei Zugriff wecken</a></p><details><summary>Was bedeuten die Funktionen?</summary><p><b>Verbindung einrichten:</b> Proxy oder Weiterleitung vorbereiten und nach Bestätigung aktivieren.<br><b>Zuordnung bearbeiten:</b> Dienst und Ziel nur als Notiz speichern. Das ändert keine Verbindung.<br><b>Adresse & Zertifikat prüfen:</b> DNS und HTTPS vom Server aus prüfen.</p><p>Beim Reverse Proxy bleibt die Domain im Browser sichtbar. Bei einer Weiterleitung wechselt der Browser zur Zieladresse. DNS und Router werden nicht automatisch geändert.</p></details></div>")
            for host in hosts:
                from urllib.parse import urlencode
                m=mappings.get(host,{});ps=[p for p in providers if p['host']==host];configured=sites.get(host,[])
                compact=sorted(set(value for site in configured for value in site['targets']))
                headline=compact[0] if compact else ('Lokale Website' if configured else 'Keine lokale Verbindung erkannt')
                if headline.startswith('Lokaler Pfad '):headline='Lokale Website: '+headline[len('Lokaler Pfad '):].split(' →',1)[0]
                headline=headline.replace('Proxy →','Reverse Proxy →')
                if len(compact)>1:headline+=' · +'+str(len(compact)-1)+' weitere'
                body+=_ui_html("<details class='card' style='padding:10px 14px;margin:8px 0;overflow-wrap:anywhere'")+(' open' if host in checks else '')+_ui_html("><summary><b>")+esc(host)+_ui_html("</b><span class='muted'> · ")+esc(headline)+_ui_html("</span></summary>")
                if m.get('service'):body+=_ui_html("<p><b>Dienst:</b> ")+esc(m['service'])+_ui_html(" <span class='muted'>(hinterlegt)</span></p>")
                found=sorted(set(value for site in configured for value in site['targets']))
                if found:body+=_ui_html("<p><b>Erkannte Verbindung:</b><br>")+_ui_html('<br>').join(esc(('Lokale Website: '+value[len('Lokaler Pfad '):].split(' →',1)[0]) if value.startswith('Lokaler Pfad ') else value.replace('Proxy →','Reverse Proxy →')) for value in found)+_ui_html("</p>")
                elif configured:body+=_ui_html("<p><b>Erkannte Verbindung:</b> ")+(_ui_text('Lokale Website') if any(site['root'] for site in configured) else _ui_text('Ziel nicht eindeutig erkannt'))+_ui_html("</p>")
                else:body+=_ui_html("<p><b>Erkannte Verbindung:</b> Keine lokale Website gefunden.</p>")
                body+=_ui_html("<p><b>IP-Aktualisierung:</b> ")+(_ui_text('Aktiv') if any(p['enabled'] for p in ps) else _ui_text('Pausiert') if ps else _ui_text('Nicht auf diesem Server verwaltet'))+_ui_html("</p>")
                body+=_ui_html("<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0'><a class='btn' href='/dyndns/proxy?")+esc(urlencode({'host':host}))+_ui_html("'>Verbindung einrichten …</a><form method='post' style='margin:0'>")+token()+hidden('action','check')+hidden('host',host)+_ui_html("<button class='btn'>Adresse & Zertifikat prüfen</button></form></div>")
                if host in checks:
                    c=checks[host];body+=_ui_html("<details open><summary>Prüfergebnis</summary><p>")+esc(c['checked'])+_ui_html('</p><ul>')
                    for kind,value in c['dns'].items():body+=_ui_html('<li>')+kind+': '+esc(value or _ui_text('Keine Antwort / kein Eintrag'))+_ui_html('</li>')
                    body+=_ui_html('</ul><p>')+esc(c['tls'])+_ui_html('</p><p>Vom Server aus geprüft. Das bestätigt noch keinen Zugriff aus dem Internet.</p></details>')
                body+=_ui_html("<details style='margin:12px 0'><summary>Zuordnung bearbeiten</summary><p>Nur eine Notiz: Speichern ändert keine Verbindung.</p>")+form(host,m)+_ui_html("</details>")
                body+=_ui_html("<details><summary>Technische Details</summary><p><b>DynDNS-Anbieter:</b> ")+esc(', '.join(p['name']+(' (aktiv)' if p['enabled'] else ' (pausiert)') for p in ps) or _ui_text('Kein lokales Updateprofil'))+_ui_html("</p><p><b>Hinterlegte Zuordnung:</b> ")+esc(_ui_text(MODES.get(m.get('mode'),_ui_text('Noch nicht zugeordnet'))))+' · '+esc(m.get('target') or _ui_text('Kein Ziel hinterlegt'))+(':'+str(m['internal_port']) if m.get('internal_port') else '')+_ui_html("</p>")
                if m.get('port'):
                    url=m.get('scheme','https')+'://'+host+':'+str(m['port'])
                    body+=_ui_html("<p><b>Hinterlegte Adresse:</b> <a target='_blank' rel='noopener noreferrer' href='")+esc(url)+"'>"+esc(url)+_ui_html("</a> (ungeprüft)</p>")
                for site in configured:
                    body+=_ui_html("<p><b>Apache-Datei:</b> ")+esc(site['source'])+_ui_html('<br>')+esc(site['listen'])+' · '+(_ui_text('HTTPS konfiguriert') if site['tls'] else _ui_text('Keine HTTPS-Anweisung erkannt'))+(_ui_html('<br>Website-Ordner: ')+esc(site['root']) if site['root'] else '')+(_ui_html('<br>')+esc('; '.join(site['targets'])) if site['targets'] else '')+_ui_html("<br><a href='/web-security/apache/edit?")+esc(urlencode({'site':site['source']}))+_ui_html("'>Website bearbeiten …</a></p>")
                body+=_ui_html("<p>Erkennung aus aktivierten Apache-Dateien. Der geladene Laufzeitstand, externe Proxys und Routerziele werden dadurch nicht bestätigt; komplexe Regeln können fehlen.</p></details></details>")
            if not hosts:body+=_ui_html("<div class='card'><p>Noch keine Domains gefunden. Du kannst eine Verbindung einrichten oder zunächst eine Zuordnung hinterlegen.</p></div>")
            body+=_ui_html("<details class='card'><summary>Weitere Zuordnung hinterlegen</summary><p>Domain, Dienst und Ziel als Notiz speichern – auch für geplante Verbindungen. DNS und Webserver bleiben unverändert.</p>")+form('',{})+_ui_html('</details>')
            return page(_ui_text('DynDNS · Ziele & Dienste'),body)
        except (e.Problem,OSError,ValueError) as exc:return page(_ui_text('DynDNS · Ziele & Dienste'),_ui_html("<div class='card'>")+esc(str(exc))+_ui_html("</div><a href='/dyndns/targets'>Zurück</a>")),400

    def form(host,m):
        body=_ui_html("<form method='post' class='dd-form'>")+token()+hidden('action','save')+hidden('revision',revision())
        body+=field('host','Domain',host)+field('service','Dienst',m.get('service',''))
        body+=select('mode','Verbindungsart',MODES.items(),m.get('mode','unknown'))
        body+=field('target','Ziel-IP oder Hostname',m.get('target',''))+field('internal_port','Zielport',m.get('internal_port') or '',kind='number')
        body+=select('scheme','Zugangsprotokoll',[('https','HTTPS'),('http','HTTP')],m.get('scheme','https'))+field('port','Zugangsport',m.get('port') or '',kind='number',hint='Leer: TLS-Prüfung auf Port 443. Beispiel für direkten Zugang: 8123.')
        return body+_ui_html("<button>Zuordnung speichern (nur Notiz)</button></form>")
