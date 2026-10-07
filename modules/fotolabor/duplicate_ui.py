"""Native duplicate-search views; no deletion endpoint."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import json
from flask import request, Response
from .duplicates import groups
from .service import unpack


def register(app, ctx, service, token):
    esc = lambda value: ctx.esc(str(value))

    def selected():
        value = request.args.get('job')
        return service.query("SELECT * FROM fotolabor_jobs WHERE mode='duplicates' " + ('AND id=?' if value else 'ORDER BY id DESC LIMIT 1'), (int(value),) if value else ())

    @app.route('/fotolabor/duplicates')
    def fotolabor_duplicates():
        try:
            jobs = selected()
            offset = max(0, int(request.args.get('offset', 0)))
        except ValueError:
            return 'Ungültige Auftragsnummer oder Seite.', 400
        busy = bool(service.query("SELECT id FROM fotolabor_jobs WHERE state IN ('queued','running') LIMIT 1"))
        csrf = esc(token())
        disabled = 'disabled' if busy else ''
        body = _ui_html("<div class='card'><h2>Duplikatsuche</h2><p><a class='btn' href='/fotolabor?job=")
        prior = service.query("SELECT id FROM fotolabor_jobs WHERE mode!='duplicates' ORDER BY id DESC LIMIT 1")
        body += str(prior[0]['id']) if prior else ''
        body += _ui_html("'>Zur Bildprüfung</a></p><p>Findet in allen erfassten Bildformaten Dateien mit gleicher Größe und identischem SHA-256-Inhalt, unabhängig von Name und Ordner. Ähnlich aussehende Bilder oder unterschiedliche Formate werden nicht verglichen. Keine Dateien werden gelöscht. Ein Inhaltsvergleich bestätigt keine Bildintegrität.</p>")
        body += f'{_ui_html("<form method='post' action='/fotolabor/start'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn' name='mode' value='duplicates' ")}{disabled}{_ui_html('>Duplikatsuche starten</button></form>')}'
        if busy:
            body += _ui_html('<p>Während eines Fotolabor-Auftrags kann keine weitere Suche starten. Der zentrale Schlafblocker schützt laufende Aufträge.</p>')
        history = service.query("SELECT id FROM fotolabor_jobs WHERE mode='duplicates' ORDER BY id DESC LIMIT 20")
        body += _ui_html('<p>Suchverlauf: ') + ' '.join(f'{_ui_html("<a href='?job=")}{h['id']}{_ui_html("'>#")}{h['id']}{_ui_html('</a>')}' for h in history) + _ui_html('</p>')
        if jobs:
            j = jobs[0]; job = j['id']
            labels = {'running':'Läuft','queued':'Wartet','cancelled':'Pausiert','interrupted':'Unterbrochen','failed':'Fehlgeschlagen','completed':'Abgeschlossen'}
            body += f'{_ui_html('<h3>Suche #')}{job}{': '}{esc(_ui_text(labels.get(j['state'], _ui_text(j['state']))))}{_ui_html('</h3><p>Start: ')}{esc(j['started'])}{_ui_html(' · Ende: ')}{esc(j['finished'] or '–')}{_ui_html(' · Bearbeitet: ')}{j['checked']}{' / '}{j['total']}{_ui_html("</p><progress style='width:100%' max='")}{max(1, j['total'])}{_ui_html("' value='")}{j['checked']}{_ui_html("'></progress><p>")}{esc(unpack(j['current']) if j['current'] else '')}{_ui_html('</p><p>')}{esc(_ui_text(j['error']))}{_ui_html('</p>')}'
            if j['state'] in ('running','queued'):
                body += f'{_ui_html("<form method='post' action='/fotolabor/cancel'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn'>Suche pausieren</button></form><script>setTimeout(()=>location.reload(),10000)</script>")}'
            elif j['state'] in ('cancelled','interrupted','failed'):
                body += f'{_ui_html("<form method='post' action='/fotolabor/resume/")}{job}{_ui_html("'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn' ")}{disabled}{_ui_html('>Suche fortsetzen</button></form>')}'
            if j['state'] == 'completed':
                body += f'{_ui_html("<p><a class='btn' href='/fotolabor/duplicates/")}{job}{_ui_html(".txt'>Alle Duplikatgruppen als Text herunterladen</a></p>")}'
            else:
                body += _ui_html('<p>Vorläufige Ergebnisse; die Suche ist noch nicht abgeschlossen.</p>')
            stats = service.query('''SELECT COUNT(*) n,COALESCE(SUM(copies-1),0) extra FROM
                (SELECT COUNT(*) copies FROM fotolabor_hashes WHERE job_id=? GROUP BY digest,bytes HAVING COUNT(*)>1)''',(job,))[0]
            body += f'{_ui_html('<p>')}{stats['n']}{_ui_html(' Gruppen · ')}{stats['extra']}{_ui_html(' zusätzliche Dateipfade. Hardlinks werden eigens ausgewiesen; tatsächlicher freigebbarer Speicher hängt vom Dateisystem ab.</p>')}'
            for g in groups(service, job, offset):
                body += f'{_ui_html('<h3>')}{g['copies']}{_ui_html(' Pfade · ')}{g['bytes']}{_ui_html(' Bytes je Datei · ')}{g['physical']}{_ui_html(' unterschiedliche Dateiobjekte</h3><ul>')}'
                for r in service.query('SELECT path FROM fotolabor_hashes WHERE job_id=? AND digest=? AND bytes=? ORDER BY path LIMIT 100',(job,g['digest'],g['bytes'])):
                    body += _ui_html('<li style="overflow-wrap:anywhere">') + esc(service.root / unpack(r['path'])) + _ui_html('</li>')
                body += _ui_html('</ul>')
                if g['copies'] > 100:
                    body += _ui_html('<p>Weitere Pfade stehen im vollständigen Textbericht.</p>')
            if offset:
                body += f'{_ui_html("<a class='btn' href='?job=")}{job}{_ui_html('&offset=')}{max(0, offset - 50)}{_ui_html("'>Zurück</a> ")}'
            if offset+50 < stats['n']:
                body += f'{_ui_html("<a class='btn' href='?job=")}{job}{_ui_html('&offset=')}{offset + 50}{_ui_html("'>Weitere Gruppen</a>")}'
            failures = service.query("SELECT path,reason FROM fotolabor_files WHERE job_id=? AND status='uncheckable' ORDER BY path LIMIT 100",(job,))
            count = service.query("SELECT count(*) n FROM fotolabor_files WHERE job_id=? AND status='uncheckable'",(job,))[0]['n']
            body += f'{_ui_html('<h3>Nicht vergleichbar: ')}{count}{_ui_html(' (erste 100)</h3>')}'
            for r in failures:
                body += _ui_html('<p>') + esc(service.root / unpack(r['path'])) + ': ' + esc(_ui_text(r['reason'])) + _ui_html('</p>')
        return ctx.page(_ui_text('Fotolabor – Duplikatsuche'), body+_ui_html('</div>'), 'Fotolabor')

    @app.route('/fotolabor/duplicates/<int:job>.txt')
    def fotolabor_duplicates_download(job):
        rows = service.query("SELECT * FROM fotolabor_jobs WHERE id=? AND mode='duplicates'",(job,))
        if not rows:
            return 'Suche nicht gefunden.',404
        if rows[0]['state'] != 'completed':
            return 'Bericht nach Abschluss verfügbar.',409
        def content():
            yield f"Fotolabor – exakte Duplikate\nSuche #{job} · Abschluss {rows[0]['finished']}\nSHA-256 und Dateigröße; keine Löschfreigabe, keine Integritätsprüfung.\nPfade sind JSON-Zeichenfolgen. Hardlinks belegen nicht nochmals dieselben Daten.\n\n"
            offset=0
            while True:
                batch=groups(service,job,offset)
                if not batch: break
                for g in batch:
                    yield f"Gruppe {g['digest']} · {g['bytes']} Bytes · {g['copies']} Pfade · {g['physical']} Dateiobjekte\n"
                    last=''
                    while True:
                        members=service.query('SELECT path FROM fotolabor_hashes WHERE job_id=? AND digest=? AND bytes=? AND path>? ORDER BY path LIMIT 500',(job,g['digest'],g['bytes'],last))
                        if not members: break
                        for m in members:
                            last=m['path']
                            yield json.dumps(str(service.root/unpack(last)),ensure_ascii=True)+'\n'
                    yield '\n'
                offset+=len(batch)
        return Response(content(),content_type='text/plain; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="fotolabor-duplikate-{job}.txt"','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})
