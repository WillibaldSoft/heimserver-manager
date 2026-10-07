"""Repair outcomes and downloads in the existing Manager interface."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import os
from pathlib import Path
from flask import request,send_file,session
import secrets
from . import checks
from .service import unpack


def register(app,ctx,service):
    esc=lambda value:ctx.esc(str(value))
    @app.route('/fotolabor/repairs')
    def fotolabor_repairs():
        try: offset=max(0,int(request.args.get('offset',0)))
        except ValueError: return 'Ungültige Seite',400
        rows=service.query('SELECT rowid AS id,* FROM fotolabor_repairs ORDER BY job_id DESC,path LIMIT 100 OFFSET ?',(offset,))
        body=_ui_html("<div class='card'><h2>Automatische JPEG-Reparatur</h2><p><a class='btn' href='/fotolabor'>Zum Fotolabor</a></p><p>Der Scan wählt JPEGs mit lesbaren Bilddaten und Metadatenfehlern automatisch aus. Reparaturversuche erzeugen separate Kopien außerhalb des Bildbestands. Bis zur ausdrücklichen Übernahme bleiben Originale unverändert. Pixel, Farbprofil und Orientierung werden verglichen. Andere Metadaten können verloren gehen. Zugehörige DNGs bleiben bis zur erfolgreichen Übernahme geschützt.</p><p>Beschädigte Bilddaten werden nicht automatisch rekonstruiert. Bereits geprüfte Dateien werden beim Fortsetzen nicht erneut ausgewählt; dafür eine gezielte JPEG-Nachprüfung starten.</p>")
        if 'fotolabor_csrf' not in session:session['fotolabor_csrf']=secrets.token_urlsafe(32)
        busy=bool(service.query("SELECT id FROM fotolabor_jobs WHERE state IN ('running','queued') LIMIT 1"))
        disabled='disabled' if busy else ''
        body+=f'{_ui_html("<form method='post' action='/fotolabor/repairs/apply'><input type='hidden' name='csrf' value='")}{esc(session['fotolabor_csrf'])}{_ui_html("'><button class='btn' ")}{disabled}{_ui_html('>Geprüfte Reparaturen übernehmen</button></form><p>Dieser Button ersetzt Originale durch erneut geprüfte Reparaturkopien. Die bisherigen Originale werden vorher gesichert. Scans und Reparaturversuche übernehmen nichts automatisch.</p>')}'
        body+=f'{_ui_html("<form method='post' action='/fotolabor/repairs/mpf'><input type='hidden' name='csrf' value='")}{esc(session['fotolabor_csrf'])}{_ui_html("'><button class='btn' ")}{disabled}{_ui_html('>Fehlerhafte MPF-Vorschauen reparieren und übernehmen</button></form><p>Korrigiert eindeutig auffindbare Vorschaubild-Verweise oder entfernt verwaiste MPF-Einträge. Nur bekannte MPF-Fehler werden geprüft. Die Übernahme sichert die Originale und erhält Hauptbild, Farbprofil und Orientierung.</p>')}'
        active=service.query("SELECT * FROM fotolabor_jobs WHERE mode IN ('repair','apply_repairs','repair_mpf') ORDER BY id DESC LIMIT 1")
        if active:
            j=active[0]
            body+=f'{_ui_html('<p>Reparaturauftrag #')}{j['id']}{': '}{esc(_ui_text(j['state']))}{_ui_html(' · ')}{j['checked']}{' / '}{j['total']}{_ui_html(' bearbeitet</p>')}'
            if j['state'] in ('running','queued'):
                csrf=esc(session.get('fotolabor_csrf',''))
                body+=f'{_ui_html("<form method='post' action='/fotolabor/cancel'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn'>Reparatur pausieren</button></form><script>setTimeout(()=>location.reload(),10000)</script>")}'
            if j['state'] in ('cancelled','interrupted','failed'):
                body+=f'{_ui_html("<form method='post' action='/fotolabor/resume/")}{j['id']}{_ui_html("'><input type='hidden' name='csrf' value='")}{esc(session['fotolabor_csrf'])}{_ui_html("'><button class='btn'>Reparatur fortsetzen</button></form>")}'
            counts={r['status']:r['n'] for r in service.query('SELECT status,COUNT(*) n FROM fotolabor_repairs WHERE job_id=? GROUP BY status',(j['id'],))}
            body+=f'{_ui_html('<p>Kopien erfolgreich geprüft: ')}{counts.get('repaired', 0)}{_ui_html(' · Nicht repariert: ')}{counts.get('failed', 0)}{_ui_html('</p>')}'
        adoptions=service.query("SELECT status,COUNT(*) n FROM fotolabor_applied GROUP BY status")
        for r in adoptions:body+=f'{_ui_html('<p>Übernahme ')}{esc(_ui_text(r['status']))}{': '}{r['n']}{_ui_html('</p>')}'
        sources=service.query("SELECT id FROM fotolabor_jobs WHERE state='ready' AND mode IN ('cleanup','refresh_cleanup') ORDER BY id DESC LIMIT 5")
        for s in sources:
            body+=f'{_ui_html("<form method='post' action='/fotolabor/prepare/")}{s['id']}{_ui_html("'><input type='hidden' name='csrf' value='")}{esc(session['fotolabor_csrf'])}{_ui_html("'><button class='btn' ")}{disabled}{_ui_html('>Löschpakete aus Prüfung #')}{s['id']}{_ui_html(' vorbereiten</button></form>')}'
        body += _ui_html('<table><tr><th>Original</th><th>Status</th><th>Ergebnis</th></tr>')
        labels={'selected':'Ausgewählt','failed':'Nicht repariert','repaired':'Kopie technisch geprüft – Sichtkontrolle erforderlich'}
        for r in rows:
            body+=f'{_ui_html('<tr><td>')}{esc(service.root / unpack(r['path']))}{_ui_html('<br>Scan #')}{r['job_id']}{_ui_html('</td><td>')}{esc(_ui_text(labels.get(r['status'], r['status'])))}{_ui_html('</td><td>')}{esc(_ui_text(r['reason']))}'
            if r['status']=='repaired':body+=f'{_ui_html("<p><a class='btn' href='/fotolabor/repairs/")}{r['id']}{_ui_html("/download'>Reparierte Kopie herunterladen</a> · <a class='btn' href='/fotolabor/repairs/")}{r['id']}{_ui_html("/compare'>Original / Reparatur vergleichen</a></p>")}'
            body+=_ui_html('</td></tr>')
        body+=_ui_html('</table>')
        if not rows:body+=_ui_html('<p>Noch keine Reparaturkandidaten erfasst.</p>')
        if offset:body+=f'{_ui_html("<a href='?offset=")}{max(0, offset - 100)}{_ui_html("'>Zurück</a> ")}'
        if len(rows)==100:body+=f'{_ui_html("<a href='?offset=")}{offset + 100}{_ui_html("'>Weitere</a>")}'
        return ctx.page(_ui_text('Fotolabor – Reparaturen'),body+_ui_html('</div>'),'Fotolabor')

    @app.route('/fotolabor/repairs/<int:item>/download')
    def fotolabor_repair_download(item):
        rows=service.query("SELECT output FROM fotolabor_repairs WHERE rowid=? AND status='repaired'",(item,))
        if not rows:return 'Reparierte Kopie nicht gefunden',404
        path=Path(rows[0]['output'])
        if path.name!='repariert.jpg' or path.parent.parent!=Path(ctx.state_dir) or not path.parent.name.startswith('fotolabor-repair-'):
            return 'Ungültiger Ausgabepfad',409
        try:
            with checks.directory(path.parent) as parent,checks.opened(parent,path.name) as fd:
                handle=os.fdopen(os.dup(fd),'rb')
            response=send_file(handle,mimetype='image/jpeg',as_attachment=request.args.get('inline')!='1',download_name='repariert.jpg',max_age=0)
            response.call_on_close(handle.close)
            response.headers['Cache-Control']='private, no-store'
            return response
        except (OSError,checks.Uncheckable):return 'Kopie nicht verfügbar',404

    @app.route('/fotolabor/repairs/<int:item>/compare')
    def fotolabor_repair_compare(item):
        rows=service.query("SELECT * FROM fotolabor_repairs WHERE rowid=? AND status='repaired'",(item,))
        if not rows:return 'Reparatur nicht gefunden',404
        body=f'{_ui_html("<div class='card'><h2>Original und reparierte Kopie</h2><p>")}{esc(unpack(rows[0]['path']))}{_ui_html("</p><p>Links die aktuelle Originaldatei, rechts die gespeicherte Reparatur. Änderungen am Original nach der Reparatur können den Vergleich beeinflussen. Es wird nichts übernommen oder ersetzt.</p><div style='display:flex;flex-wrap:wrap;gap:1rem'><figure style='flex:1;min-width:250px'><figcaption>Original</figcaption><img style='max-width:100%' src='/fotolabor/repairs/")}{item}{_ui_html("/original'></figure><figure style='flex:1;min-width:250px'><figcaption>Reparierte Kopie</figcaption><img style='max-width:100%' src='/fotolabor/repairs/")}{item}{_ui_html("/download?inline=1'></figure></div><a class='btn' href='/fotolabor/repairs'>Zurück</a></div>")}'
        return ctx.page(_ui_text('Fotolabor – Bildvergleich'),body,'Fotolabor')

    @app.route('/fotolabor/repairs/<int:item>/original')
    def fotolabor_repair_original(item):
        rows=service.query('SELECT path FROM fotolabor_repairs WHERE rowid=?',(item,))
        if not rows:return 'Original nicht gefunden',404
        path=Path(unpack(rows[0]['path']))
        if path.suffix.lower() not in ('.jpg','.jpeg'):return 'Kein JPEG',409
        try:
            with checks.directory(service.root,str(path.parent)) as parent,checks.opened(parent,path.name) as fd:handle=os.fdopen(os.dup(fd),'rb')
            response=send_file(handle,mimetype='image/jpeg',as_attachment=False,download_name='original.jpg',max_age=0)
            response.call_on_close(handle.close);response.headers['Cache-Control']='private, no-store'
            return response
        except (OSError,checks.Uncheckable):return 'Original nicht verfügbar',404
