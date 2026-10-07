"""Qwen model installation inside the Open WebUI app module."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
from urllib.error import URLError
from urllib.parse import urlencode
from flask import request, session, redirect
from .install_ui import esc, token
from . import qwen_models as models

BASE = '/apps/open_webui/models'


def gb(size):
    return f'{size/10**9:.1f} GB'


def state_label(local, remote):
    if not local:
        return 'Nicht installiert'
    digest = local.get('digest','').removeprefix('sha256:')
    if not digest or not remote.get('digest'):
        return 'Installiert · Versionsstand nicht prüfbar'
    return 'Installiert · aktuell' if digest.startswith(remote['digest']) else 'Update verfügbar'


def register(app, ctx):
    def page(body):
        return ctx.page(_ui_text('Open WebUI · Qwen-Modelle'),_ui_html("<div class='card'><a class='btn' href='/apps/open_webui'>Zur Open-WebUI-App</a> <a class='btn' href='")+BASE+_ui_html("'>Qwen-Modelle</a></div>")+body,'Apps')
    def error(exc,code=400):
        return page(_ui_html("<div class='card'><p>")+esc(_ui_text(exc))+_ui_html("</p></div>")),code

    @app.before_request
    def qwen_csrf():
        if request.path.startswith(BASE) and request.method=='POST':
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('app_install_csrf','!')):
                return error('Formular abgelaufen. Bitte Seite neu laden.',403)

    @app.route(BASE)
    def qwen_catalog():
        body=_ui_html("<div class='card'><h2>Qwen-Modelle für Open WebUI</h2><p>Modelle direkt in Ollama auf diesem Server herunterladen und installieren. Neue Modellnamen werden zusätzlich installiert; bei gleichem Namen wird der vorhandene Tag aktualisiert. Laufende Chats können das bisher geladene Modell bis zum nächsten Laden weiterverwenden.</p>")
        installed={};connected=False
        try:
            installed={m['name']:m for m in models.local_models()};connected=True
            body+=_ui_html('<p>✅ Lokales Ollama erreichbar · ')+str(len(installed))+_ui_html(' Modelle installiert</p>')
        except (OSError,ValueError,URLError):
            body+=_ui_html('<p>❌ Lokales Ollama nicht erreichbar (127.0.0.1:11434). Dienst prüfen; Installation derzeit nicht möglich.</p>')
        body+=_ui_html('<p>Nach der Installation die Modellauswahl in Open WebUI neu laden. Open WebUI muss mit diesem Ollama verbunden sein; die Verbindung wird hier nicht umgestellt.</p></div>')
        try:
            running=models.active()
            if running:
                body+=_ui_html("<div class='card'><a class='btn' href='")+BASE+_ui_html('/jobs/')+esc(running['id'])+_ui_html("'>Laufender Download: ")+esc(running['model'])+_ui_html('</a></div>')
        except (OSError,ValueError):
            running=None
        body+=_ui_html("<div class='card'><h3>Verfügbare Modelle</h3>")
        try:
            families=models.families()
            family=request.args.get('family','qwen3.5' if 'qwen3.5' in families else families[0])
            if family not in families:
                raise models.Invalid('Modellfamilie nicht im offiziellen Katalog gefunden.')
            extended=request.args.get('variants')=='all'
            body+=_ui_html("<form method='get'><label>Modellfamilie <select name='family'>")
            for name in families:
                body+=_ui_html("<option value='")+esc(name)+"'"+(' selected' if name==family else '')+'>'+esc(name)+_ui_html('</option>')
            body+=_ui_html("</select></label> <label><input type='checkbox' name='variants' value='all'")+(' checked' if extended else '')+_ui_html("> Alle Quantisierungen anzeigen</label> <button class='btn'>Katalog laden / aktualisieren</button></form>")
            body+=_ui_html("<p><a target='_blank' rel='noopener noreferrer' href='https://ollama.com/library/")+esc(family)+_ui_html("/tags'>Offizielle Modellvarianten ↗</a> · Cloud- und MLX-Varianten werden hier nicht installiert.</p><p>Die Downloadgröße ist kein RAM-/VRAM-Bedarf. Große Varianten benötigen entsprechend mehr Arbeitsspeicher; die Laufzeit-Kompatibilität prüft Ollama beim Laden.</p>")
            rows=models.catalog(family)
            shown=[r for r in rows if extended or '-' not in r['name'].split(':')[1] or r['name'] in installed]
            if not shown:
                shown=rows
            body+=_ui_html("<table><thead><tr><th>Modell / Variante</th><th>Downloadgröße</th><th>Versionsstand</th><th>Aktion</th></tr></thead><tbody>")
            for row in shown:
                current=installed.get(row['name']);label=_ui_text(state_label(current,row))
                action='Auf neue Version aktualisieren' if label=='Update verfügbar' else 'Erneut prüfen & laden' if current else 'Herunterladen & installieren'
                body+=_ui_html('<tr><td><code>')+esc(row['name'])+_ui_html('</code></td><td>')+esc(row['size'])+_ui_html('</td><td>')+esc(_ui_text(label))+_ui_html('</td><td>')
                if connected and not running:
                    body+=_ui_html("<form method='post' action='")+BASE+"/install'>"+token()+_ui_html("<input type='hidden' name='model' value='")+esc(row['name'])+_ui_html("'><button class='btn'>")+action+_ui_html('</button></form>')
                else:
                    body+=_ui_html('Ollama/Downloadstatus prüfen')
                body+=_ui_html('</td></tr>')
            body+=_ui_html('</tbody></table><p>Verglichen wird die Modell-Prüfsumme des veröffentlichten Tags mit der lokalen Installation. Unterschiedliche Größen sind eigenständige Varianten.</p>')
        except (OSError,ValueError,URLError) as exc:
            body+=_ui_html('<p>Katalog nicht verfügbar: ')+esc(str(exc)[:300])+_ui_html('. Vorhandene Modelle bleiben nutzbar.</p>')
        body+=_ui_html("</div><div class='card'><h3>Installierte Qwen-Modelle</h3><ul>")
        own=[m for n,m in installed.items() if n.startswith('qwen')]
        body+=''.join(_ui_html('<li><code>')+esc(m['name'])+_ui_html('</code> · ')+gb(m.get('size',0))+_ui_html(" <a class='btn' href='")+BASE+'/remove?'+esc(urlencode({'model':m['name']}))+_ui_html("'>Deinstallieren</a></li>") for m in own) or _ui_html('<li>Keine Qwen-Modelle gefunden.</li>')
        body+=_ui_html('</ul></div>')
        try:
            recent=models.recent()
            if recent:
                body+=_ui_html("<div class='card'><h3>Letzte Downloads</h3><ul>")+''.join(_ui_html("<li><a href='")+BASE+_ui_html('/jobs/')+esc(j['id'])+"'>"+esc(j['model'])+_ui_html('</a> · ')+esc(_ui_text(j['state']))+_ui_html('</li>') for j in recent)+_ui_html('</ul></div>')
        except (OSError,ValueError):
            pass
        return page(body)

    @app.route(BASE+'/install',methods=['POST'])
    def qwen_install():
        try:
            key=models.start(request.form.get('model',''))
            return redirect(BASE+'/jobs/'+key,303)
        except (OSError,ValueError,URLError) as exc:
            return error(str(exc)[:400])

    @app.route(BASE+'/remove', methods=['GET', 'POST'])
    def qwen_remove():
        name=request.form.get('model','') if request.method=='POST' else request.args.get('model','')
        try:
            if request.method=='POST':
                if request.form.get('confirm')!='remove':
                    raise models.Invalid('Bitte die Entfernung ausdrücklich bestätigen.')
                models.remove(name, request.form.get('digest',''))
                return page(_ui_html("<div class='card'><h2>Modell deinstalliert</h2><p><code>")+esc(name)+_ui_html("</code> wurde aus Ollama entfernt. Die Modellauswahl in Open WebUI bitte neu laden.</p></div>"))
            current=next((m for m in models.local_models() if m.get('name')==name and m.get('name','').startswith('qwen')),None)
            if current is None:
                return error('Installiertes Qwen-Modell nicht gefunden.',404)
            if models.active():
                return error('Während eines Modelldownloads ist keine Deinstallation möglich.',409)
            body=_ui_html("<div class='card'><h2>Qwen-Modell deinstallieren</h2><p>Ausgewähltes Modell: <b>")+esc(name)+_ui_html("</b> · ")+gb(current.get('size',0))+_ui_html("</p><p>Dieser Modellname wird aus dem lokalen Ollama entfernt und steht danach nicht mehr für neue Chats zur Verfügung. Open-WebUI-Chats und andere Modellnamen werden nicht gelöscht. Gemeinsam verwendete Modelldaten können erhalten bleiben; der freigegebene Speicher kann deshalb kleiner sein.</p><form method='post'>")+token()
            body+=_ui_html("<input type='hidden' name='model' value='")+esc(name)+_ui_html("'><input type='hidden' name='digest' value='")+esc(current.get('digest',''))+_ui_html("'><label><input type='checkbox' name='confirm' value='remove' required> Dieses Modell entfernen</label> <button class='btn'>Jetzt deinstallieren</button> <a class='btn' href='")+BASE+_ui_html("'>Abbrechen</a></form></div>")
            return page(body)
        except (OSError,ValueError,URLError) as exc:
            return error('Deinstallation nicht bestätigt: '+str(exc)[:400]+'. Bitte Modellübersicht prüfen.')

    @app.route(BASE+'/jobs/<key>')
    def qwen_job(key):
        try:
            job=models.load(key)
        except (OSError,ValueError):
            return error('Downloadauftrag nicht gefunden.',404)
        labels={'queued':'Wartet','running':'Download läuft','completed':'Installiert','failed':'Fehlgeschlagen','interrupted':'Unterbrochen'}
        body=_ui_html("<div class='card'><h2>")+esc(job['model'])+_ui_html('</h2><p><b>')+esc(_ui_text(labels.get(job['state'],_ui_text(job['state']))))+_ui_html('</b></p><p>')+esc(_ui_text(job['message']))+_ui_html('</p>')
        if job.get('percent') is not None:
            body+="<progress max='100' value='"+str(float(job['percent']))+"'></progress> "+esc(job['percent'])+' % (aktueller Downloadabschnitt)'
        if job.get('total'):
            body+=_ui_html('<p>')+gb(job.get('completed',0))+' / '+gb(job['total'])+_ui_html('</p>')
        if job['state'] in ('failed','interrupted'):
            body+=_ui_html("<form method='post' action='")+BASE+"/install'>"+token()+_ui_html("<input type='hidden' name='model' value='")+esc(job['model'])+_ui_html("'><button class='btn'>Erneut versuchen</button></form>")
        body+=_ui_html('</div>')
        if job['state'] not in models.TERMINAL:
            body+=_ui_html('<script>setTimeout(()=>location.reload(),4000)</script>')
        return page(body)
