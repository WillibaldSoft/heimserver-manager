"""Native Manager plugin: existing page styles, SQLite context and blocker registry."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import secrets
import json
from flask import request, redirect, session, jsonify, Response
from . import checks, blocker_provider
from .service import Service, unpack

LABELS = {2: 'DNG aus JPG – JPG gesund', 3: 'DNG aus JPG – JPG fehlt',
          4: 'DNG aus JPG – JPG defekt / nicht sicher prüfbar', 5: 'RAW / andere DNGs (auch ungeklärt)'}
STATES = {'queued': 'Wartet', 'running': 'Läuft', 'completed': 'Abgeschlossen',
          'ready': 'Vorschau bereit – wartet auf Löschfreigabe',
          'failed': 'Fehlgeschlagen', 'cancelled': 'Pausiert', 'interrupted': 'Unterbrochen'}
STATUS = {'hashed': 'Prüfsumme gelesen', 'derived': 'Kopie erstellt', 'ok': 'OK', 'damaged': 'Defekt', 'uncheckable': 'Nicht prüfbar', 'pending': 'Ausstehend'}
MODES = {'raw_dng': 'RAW nach DNG', 'manual_delete': 'Manuelle Bereinigung', 'selection': 'Dateiauswahl', 'repair_mpf': 'MPF-Vorschaubilder reparieren', 'apply_repairs': 'Geprüfte Reparaturen übernehmen', 'refresh_cleanup': 'Löschpakete vorbereiten', 'repair': 'Gezielte JPEG-Reparatur', 'incremental': 'Neue/geänderte Bilder', 'checksum': 'Prüfsummenkontrolle', 'restore': 'DNG-Wiederherstellung', 'duplicates': 'Duplikatsuche', 'scan': 'Vollständige Prüfung', 'cleanup': 'Bereinigungs-Vorschau', 'recheck': 'Gezielte Nachprüfung', 'delete': 'Bestätigte Bereinigung'}
PHASES = {'repairing': 'Vorschaubild-Verweise prüfen und reparieren', 'applying': 'Originale sichern und Reparaturen übernehmen', 'restoring': 'DNG wiederherstellen', 'inventory': 'Bestand erfassen', 'selection': 'Dateien auswählen', 'checking': 'Bilddaten prüfen', 'preview': 'Vorschau / Freigabe', 'deleting': 'Freigegebene Dateien löschen', 'finished': 'Fertig'}


def register(app, ctx):
    from .host_context import context
    ctx = context(ctx, checks.ROOT)
    service = Service(ctx)
    blocker_provider._SERVICE = service
    app.extensions['fotolabor'] = service
    esc = lambda value: ctx.esc(str(value))

    def token():
        if session.get('fotolabor_root') != str(service.root):
            session.pop('fotolabor_csrf', None)
            session['fotolabor_root'] = str(service.root)
        if 'fotolabor_csrf' not in session:
            session['fotolabor_csrf'] = secrets.token_urlsafe(32)
        return session['fotolabor_csrf']

    def protected():
        supplied = request.form.get('csrf', '')
        return bool(session.get('fotolabor_root') == str(service.root) and supplied and secrets.compare_digest(supplied, session.get('fotolabor_csrf', '')))

    from .duplicate_ui import register as register_duplicates
    register_duplicates(app, ctx, service, token)
    from .repair_ui import register as register_repairs
    register_repairs(app, ctx, service)
    from .advanced_ui import register as register_advanced
    register_advanced(app, ctx, service, token, protected)
    from .slideshow_ui import register as register_slideshow
    register_slideshow(app, ctx, service, token, protected)
    from .raw_dng import register as register_raw_dng
    register_raw_dng(app, ctx, service, token, protected)
    if hasattr(ctx, 'base_dir'):
        from .scheduling import start as start_scheduler
        start_scheduler(service)

    @app.route('/fotolabor', strict_slashes=False)
    def fotolabor_index():
        try:
            selected = int(request.args['job']) if request.args.get('job') else None
        except ValueError:
            return 'Ungültige Auftragsnummer.', 400
        if selected is None and request.args.get('view') == 'checks':
            scans = service.query("SELECT id FROM fotolabor_jobs WHERE mode IN ('scan','recheck','incremental','cleanup','refresh_cleanup','delete') ORDER BY id DESC LIMIT 1")
            if scans:selected = scans[0]['id']
        summary = service.summary(selected)
        job, counts = summary['job'], summary['counts']
        token()
        if not any(request.args.get(key) for key in ('view', 'job', 'category', 'offset')):
            body = _ui_html("<div class='card'><h2>Fotolabor</h2><p>Fotoshows erstellen, doppelte Bilder finden und die Lesbarkeit deiner Bildsammlung prüfen.</p><p>Bildordner: <code>") + esc(service.root) + _ui_html("</code> · <a href='/settings/server-paths'>Ordner ändern</a></p></div>")
            body += _ui_html("<div class='grid'>")
            tasks = [
                ('Fotoshow erstellen', 'Aus einem Bilderordner ein tragbares Fotoshow-Paket erstellen, zum Anschauen oder Weitergeben.', '/fotolabor/fotoshow', 'Fotoshow erstellen', '/fotolabor/fotoshow/history', 'Meine Fotoshows'),
                ('Doppelte Bilder finden', 'Duplikate vergleichen und eine mögliche Bereinigung gezielt vorbereiten.', '/fotolabor/duplicates', 'Duplikatsuche öffnen', None, None),
                ('Bilder prüfen', 'Beschädigte oder nicht lesbare Dateien erkennen. Eine Prüfung verändert keine Bilder.', '/fotolabor?view=checks', 'Bildprüfung öffnen', None, None),
                ('Bilder reparieren', 'Vorhandene Reparaturmöglichkeiten prüfen und Ergebnisse vor der Übernahme kontrollieren.', '/fotolabor/repairs', 'Reparaturen öffnen', None, None),
                ('RAW nach DNG', 'Kamera-RAWs in zusätzliche DNG-Dateien umwandeln. Originale bleiben erhalten.', '/fotolabor/raw-dng', 'Umwandlung öffnen', None, None),
                ('Weitere Werkzeuge', 'Prüfoptionen, Prüfsummen und spezielle Wiederherstellungsfunktionen für fortgeschrittene Aufgaben.', '/fotolabor/tools', 'Werkzeuge öffnen', None, None),
            ]
            for title, description, url, label, second_url, second_label in tasks:
                body += _ui_html("<div class='card'><h3>") + esc(_ui_text(title)) + _ui_html("</h3><p>") + esc(_ui_text(description)) + _ui_html("</p><a class='btn' href='") + url + "'>" + esc(_ui_text(label)) + _ui_html("</a>")
                if second_url:body += _ui_html(" <a class='btn' href='") + second_url + "'>" + esc(_ui_text(second_label)) + _ui_html("</a>")
                body += _ui_html('</div>')
            body += _ui_html('</div>')
            if app.extensions['fotolabor_slideshows'].active():
                body += _ui_html("<div class='card'><h3>Fotoshow wird erstellt</h3><a href='/fotolabor/fotoshow/history'>Fortschritt anzeigen</a></div>")
            if job:
                body += _ui_html("<div class='card'><h3>Letzter Auftrag</h3><p>") + esc(_ui_text(MODES.get(job['mode'], _ui_text(job['mode'])))) + " · " + esc(_ui_text(STATES.get(job['state'], _ui_text(job['state'])))) + _ui_html("</p>")
                body += f'{_ui_html('<p>Auftrag #')}{job['id']}{_ui_html(' · Start ')}{esc(job['started'])}{_ui_html(' · Ende ')}{esc(job['finished'] or _ui_text('noch offen'))}{_ui_html('</p>')}'
                body += _ui_html("<p>Ergebnisse gelten für diesen Auftrag und seinen geprüften Teilbestand, nicht automatisch für alle Bilder.</p>")
                body += f'{_ui_html("<a class='btn' href='/fotolabor?job=")}{job['id']}{_ui_html("'>Ergebnis / Fortschritt öffnen</a></div>")}'
            else:
                body += _ui_html("<div class='card'><h3>Erste Schritte</h3><p>Bildordner in den Einstellungen festlegen. Danach eine Fotoshow erstellen oder mit einer Bildprüfung beginnen.</p></div>")
            body += _ui_html("<div class='card'><h3>Prüfergebnisse richtig verstehen</h3><p><b>OK:</b> Die verwendeten Prüfwerkzeuge konnten die Datei lesen. <b>Defekt:</b> Ein Fehler wurde gefunden. <b>Nicht prüfbar:</b> Es fehlt ein eindeutiges Ergebnis, etwa wegen eines nicht unterstützten Formats oder nicht lesbarer Metadaten. Das bedeutet nicht automatisch, dass das Foto verloren ist.</p><p>Löschen und das Übernehmen von Reparaturen bleiben separate, bestätigungspflichtige Schritte. Eine Prüfung ist kein Ersatz für ein Backup.</p></div>")
            return ctx.page(_ui_text('Fotolabor'), body, 'Fotolabor')
        if request.args.get('job') and job and job['mode'] == 'raw_dng':
            return redirect('/fotolabor/raw-dng?job='+str(job['id']))
        if request.args.get('job') and job and job['mode'] == 'duplicates':
            return redirect(f"/fotolabor/duplicates?job={job['id']}")
        if request.args.get('job') and job and job['mode'] in ('repair','apply_repairs'):
            return redirect('/fotolabor/repairs')
        if request.args.get('job') and job and job['mode'] == 'restore':
            return redirect('/fotolabor/restore')
        csrf = esc(token())
        body = _ui_html("<div class='card'><h2>Bildprüfung</h2><p><a class='btn' href='/fotolabor'>Fotolabor-Übersicht</a></p><p><code>") + esc(service.root) + _ui_html('</code></p>')
        body += _ui_html("<p><a class='btn' href='/fotolabor/duplicates'>Duplikatsuche öffnen</a> · <a class='btn' href='/fotolabor/repairs'>Automatische Reparaturen</a> · <a class='btn' href='/fotolabor/tools'>Prüfoptionen / Erweiterungen</a></p>")
        body += _ui_html("<p><a class='btn' href='/fotolabor/fotoshow'>🎞 Fotoshow erstellen</a> <a class='btn' href='/fotolabor/fotoshow/history'>Meine Fotoshows</a></p>")
        if app.extensions['fotolabor_slideshows'].active():
            body += _ui_html("<p>Fotoshow-Erstellung läuft. <a href='/fotolabor/fotoshow/history'>Fortschritt anzeigen</a></p>")
        body += _ui_html('<p>Prüfungen lesen die Bilddaten ohne sie zu verändern. Nicht unterstützte Formate, fehlende Prüfer und Warnungen werden niemals als OK gewertet.</p>')
        if job:
            total, checked = job['total'], job['checked']
            overall = 'Prüfung noch nicht vollständig'
            if job['state'] in ('completed', 'ready'):
                overall = 'Keine Bilder gefunden' if not total else ('Alle erfassten Bilder lesbar' if counts.get('ok', 0) == total else 'Prüfergebnisse erfordern Aufmerksamkeit')
            if job['mode'] == 'refresh_cleanup':overall = 'Gezielte Löschvorbereitung aus gespeichertem Scan; keine neue Bestandsprüfung'
            if job['mode'] == 'delete':overall = 'Löschauftrag: nur die freigegebenen DNG-Pakete, kein Gesamtscan'
            if job['mode'] == 'checksum':overall = 'Prüfsummenkontrolle – keine neue Bildintegritätsprüfung'
            body += f'{_ui_html('<h3>')}{esc(overall)}{_ui_html('</h3><p>Letzter Auftrag #')}{job['id']}{': '}{esc(STATES[job['state']])}{_ui_html(' · Start ')}{esc(job['started'])}{_ui_html(' · Ende ')}{esc(job['finished'] or '–')}{_ui_html('</p>')}'
            body += f'{_ui_html('<p>')}{esc(_ui_text(MODES.get(job['mode'], _ui_text(job['mode']))))}{_ui_html(' · ')}{esc(PHASES.get(job['phase'], job['phase']))}{_ui_html('</p>')}'
            selection = json.loads(job['selection'])
            if selection.get('folder') or selection.get('exclude'):
                body += _ui_html('<p>Teilbestand: ') + esc(selection.get('folder') or _ui_text('Alle Ordner')) + ' · Ausgeschlossen: ' + esc(', '.join(selection.get('exclude',[]))) + _ui_html('</p>')
            body += f'{_ui_html("<p><a href='/fotolabor/archive?job=")}{job['id']}{_ui_html("'>Prüfsummen und Inhaltsänderungen dieses Auftrags</a></p>")}'
            if job['mode'] == 'recheck':
                body += f'{_ui_html('<p>Teilbestand aus Prüfung #')}{job['source_job']}{_ui_html('. Die Ergebnisse des ursprünglichen Scans bleiben als eigener Stand erhalten.</p>')}'
            body += f'{_ui_html("<p id='live-counts'>Bestand: ")}{total}{_ui_html(' · geprüft: ')}{checked}{_ui_html(' · OK: ')}{counts.get('ok', 0)}{_ui_html(' · defekt: ')}{counts.get('damaged', 0)}{_ui_html(' · nicht prüfbar: ')}{counts.get('uncheckable', 0)}{_ui_html(' · Größe beim Scan: ')}{job['bytes'] / 1024 ** 3:.2f}{_ui_html(' GiB</p>')}'
            body += _ui_html('<p>') + ' · '.join(f'{esc(k)}: {v}' for k, v in summary['kinds'].items()) + _ui_html('</p>')
            body += f'{_ui_html("<progress value='")}{checked}{_ui_html("' max='")}{max(total, 1)}{_ui_html("' style='width:100%'></progress><p id='live-status'>")}{esc(job['current'])}{_ui_html('</p>')}'
            if job['error']:
                body += _ui_html("<p class='err'>") + esc(_ui_text(job['error'])) + _ui_html('</p>')
            if summary['deleted']:
                body += f'{_ui_html('<p>')}{summary['deleted']}{_ui_html(' Dateien gelöscht. Bestandszahlen beziehen sich auf den Scan vor der Bereinigung; für den aktuellen Bestand neu prüfen.</p>')}'
        else:
            body += _ui_html('<p>Noch kein Scan durchgeführt.</p>')
        active = job and job['state'] in ('queued', 'running')
        busy = bool(service.query("SELECT id FROM fotolabor_jobs WHERE state IN ('queued','running') LIMIT 1"))
        completed = [{'id': job['id'], 'finished': job['finished']}] if job and job['mode'] not in ('checksum','restore') and job['state'] in ('completed', 'ready') else service.query("SELECT id,finished FROM fotolabor_jobs WHERE mode NOT IN ('duplicates','checksum','restore','repair','apply_repairs','refresh_cleanup','repair_mpf') AND state IN ('completed','ready') ORDER BY id DESC LIMIT 1")
        if completed:
            report = completed[0]
            body += f'{_ui_html("<p><a class='btn' href='/fotolabor/reports/")}{report['id']}{_ui_html("/defekte-bilder.txt'>Defekte Bilder als Textdatei herunterladen</a> · Abgeschlossene Prüfung #")}{report['id']}{' vom '}{esc(report['finished'])}{_ui_html('</p>')}'
            body += f'{_ui_html("<p><a class='btn' href='/fotolabor/reports/")}{report['id']}{_ui_html("/nicht-pruefbar.txt'>Nicht prüfbare Bilder mit Gründen herunterladen</a></p>")}'
        else:
            body += _ui_html('<p>Nach einer abgeschlossenen Prüfung steht hier die Textdatei mit allen defekten Bildern und vollständigen Pfaden bereit.</p>')
        busy = busy or bool(app.extensions['fotolabor_slideshows'].active())
        disabled = 'disabled' if busy else ''
        body += f'{_ui_html("<form method='post' action='/fotolabor/start'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn' name='mode' value='scan' ")}{disabled}{_ui_html('>Vollständige Prüfung starten</button></form>')}'
        if active:
            body += f'{_ui_html("<form method='post' action='/fotolabor/cancel'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn'>Auftrag pausieren / Löschung stoppen</button></form><p>Der zentrale Schlaf-Blocker ist aktiv. Pause erfolgt nach dem aktuellen Dateischritt. Bereits gespeicherte Ergebnisse bleiben erhalten.</p>")}'
            body += _ui_html("""<script>setInterval(async()=>{try{let s=await(await fetch('/api/fotolabor/status'+location.search)).json();let j=s.job;if(j){let p=document.querySelector('progress');p.max=Math.max(j.total,1);p.value=j.checked;document.querySelector('#live-status').textContent='Erfasst: '+j.total+' · geprüft: '+j.checked+' · '+j.current;let c=s.counts;document.querySelector('#live-counts').textContent='Bestand: '+j.total+' · geprüft: '+j.checked+' · OK: '+(c.ok||0)+' · defekt: '+(c.damaged||0)+' · nicht prüfbar: '+(c.uncheckable||0)+' · Größe beim Scan: '+(j.bytes/1024**3).toFixed(2)+' GiB';if(!['queued','running'].includes(j.state))location.reload();}}catch(e){}},3000);</script>""")
        if job and job['state'] in ('cancelled', 'interrupted', 'failed') and job['mode'] != 'delete':
            body += f'{_ui_html("<form method='post' action='/fotolabor/resume/")}{job['id']}{_ui_html("'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn' ")}{disabled}{_ui_html('>Prüfung fortsetzen</button></form><p>Nur offene Dateien werden geprüft. Bisher mangels Decoder ungeprüfte WebP-, HEIF-, GIF- und BMP-Dateien werden nachgeholt. Fertige Ergebnisse bleiben als Befund ihres bisherigen Prüfzeitpunkts erhalten.</p>')}'
        history = service.query('SELECT id,mode,state FROM fotolabor_jobs ORDER BY id DESC LIMIT 20')
        body += _ui_html('<details><summary>Auftragsverlauf anzeigen</summary><p>') + ' '.join(f'{_ui_html("<a class='btn' href='/fotolabor?job=")}{h['id']}{_ui_html("'>#")}{h['id']}{_ui_html(' ')}{esc(_ui_text(MODES.get(h['mode'], _ui_text(h['mode']))))}{_ui_html(' · ')}{esc(_ui_text(STATES.get(h['state'], _ui_text(h['state']))))}{_ui_html('</a>')}' for h in history) + _ui_html('</p></details>')
        body += _ui_html('</div><div class="card"><details><summary>Prüfwerkzeuge und unterstützte Formate</summary><h3>Prüfwerkzeuge</h3><table><tr><th>Werkzeug</th><th>Status</th><th>Debian-13-Paket</th></tr>')
        deps = checks.dependencies()
        for name, dep in deps.items():
            body += f'{_ui_html('<tr><td>')}{esc(name)}{_ui_html('</td><td>')}{esc(dep['path'] or _ui_text('Fehlt – betroffene Bilder nicht prüfbar'))}{_ui_html('</td><td>')}{esc(dep['package'])}{_ui_html('</td></tr>')}'
        body += _ui_html('</table><p>Installation durch einen Administrator:</p><pre>sudo apt install jpeginfo pngcheck libtiff-tools libimage-exiftool-perl libraw-bin webp python3-pil libheif-examples</pre>')
        body += _ui_html('<p>GIF: alle Einzelbilder. HEIC/HEIF/AVIF: Libheif-Dekodierung. BMP: vollständiges Lesen. WebP: Strukturprüfung und vollständige Dekodierung aller Einzelbilder, auch bei Animationen. TIFF: vollständiges Lesen. DNG/RAW: ExifTool und LibRaw; nicht unterstützte Varianten bleiben „nicht prüfbar“.</p></details></div>')
        if job:
            body += _ui_html('<div class="card"><h3>Nicht prüfbar – Gründe</h3>')
            for code, number in summary['reasons'].items():
                body += f'{_ui_html('<p>')}{esc(checks.REASONS.get(code, code or _ui_text('Sonstiger Prüfgrund')))}{': '}{number}{_ui_html('</p>')}'
            body += f'{_ui_html("<h3>Gezielte Nachprüfung</h3><form method='post' action='/fotolabor/start'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><input type='hidden' name='mode' value='recheck'><input type='hidden' name='source_job' value='")}{job['id']}{_ui_html("'>")}'
            body += _ui_html('<label>Dateityp <select name="kind"><option value="">Alle</option>') + ''.join(f'{_ui_html('<option value="')}{esc(ext)}{_ui_html('">')}{esc(ext)}{_ui_html('</option>')}' for ext in sorted(checks.IMAGES)) + _ui_html('</select></label> ')
            body += _ui_html('<label>Status <select name="status"><option value="">Alle</option>') + ''.join(f'{_ui_html('<option value="')}{k}{_ui_html('">')}{esc(v)}{_ui_html('</option>')}' for k, v in STATUS.items()) + _ui_html('</select></label> ')
            body += _ui_html('<label>Fehlergrund <select name="reason"><option value="">Alle</option>') + ''.join(f'{_ui_html('<option value="')}{k}{_ui_html('">')}{esc(v)}{_ui_html('</option>')}' for k, v in checks.REASONS.items()) + _ui_html('</select></label> ')
            body += f'{_ui_html("<button class='btn' ")}{disabled}{_ui_html('>Auswahl erneut prüfen</button></form><p>Filter werden kombiniert. Nachprüfungen löschen keine Dateien.</p></div>')}'
        body += _ui_html('<div class="card"><details') + (' open' if request.args.get('category') or (job and job['state'] == 'ready') else '') + _ui_html('><summary>Spezialfall: aus JPEG erzeugte DNG-Dateien bereinigen</summary><h3>DNG aus JPEG</h3><p>Nur der explizite XMP-HistoryParameters-Eintrag <code>') + checks.HISTORY + _ui_html('</code> bestätigt die Herkunft.</p>')
        if job:
            pending_dng = service.query("SELECT COUNT(*) n FROM fotolabor_files WHERE job_id=? AND kind='.dng' AND status='pending'", (job['id'],))[0]['n']
            body += f'{_ui_html('<p><strong>Noch ')}{pending_dng}{_ui_html(' DNGs ohne aktuelles Prüfergebnis.</strong> Offene DNGs werden vor anderen Bildformaten geprüft. Die Kategorien zeigen nur bereits zugeordnete Dateien; 0 ist während der Prüfung kein endgültiges Ergebnis.</p>')}'
        for cat, label in LABELS.items():
            body += f'{_ui_html("<p><a href='/fotolabor?category=")}{cat}{_ui_html('&job=')}{(job['id'] if job else '')}{_ui_html("'>")}{cat}{_ui_html(') ')}{esc(_ui_text(label))}{_ui_html('</a>: ')}{summary['categories'].get(str(cat), 0)}{_ui_html('</p>')}'
        body += _ui_html('<p>Hauptmerkmal ist der exakt gleiche Dateistamm im selben Ordner. JPEG-Herkunft muss ausdrücklich belegt, das JPEG vollständig lesbar und die Auflösung passend sein. Abweichende Aufnahmezeit, Kamerahersteller oder Modell werden als Hinweise angezeigt und sperren die Zuordnung nicht. Bei fehlendem, beschädigtem oder ungeprüftem JPEG bleiben DNG und XMP erhalten.</p>')
        body += _ui_html('<h3>Sichere DNGs + zugehörige XMP löschen</h3><p>Schritt 1: Eine vollständige Prüfung erstellt nur die Vorschau. Dabei wird nichts gelöscht. Schritt 2: Die Vorschau separat mit „ja“ freigeben. Es folgt kein weiterer Gesamtscan. Nur die bestätigten Dateipakete werden unmittelbar vor der Löschung auf Veränderungen und JPEG-Lesbarkeit geprüft. Veränderte Pakete bleiben geschützt.</p>')
        cleanup_disabled = 'disabled' if busy or not deps['jpeginfo']['path'] or not deps['exiftool']['path'] else ''
        body += f'{_ui_html("<form method='post' action='/fotolabor/start'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn' name='mode' value='cleanup' ")}{disabled}{_ui_html('>Neue Bereinigungs-Vorschau erstellen</button></form>')}'
        if job and job['state'] == 'ready':
            preview = summary['preview']
            body += f'{_ui_html('<h3>Vorschau #')}{job['id']}{_ui_html('</h3><p>')}{preview['dng']}{_ui_html(' DNG-Dateien + ')}{preview['xmp']}{_ui_html(' XMP-Dateien · voraussichtlich ')}{preview['bytes'] / 1024 ** 3:.3f}{_ui_html(' GiB (')}{preview['bytes']}{_ui_html(' Bytes).</p><p>Die Kandidaten sind unter Kategorie 2 einsehbar. JPG/JPEG bleiben erhalten. Während der Bereinigung keine anderen Programme am Bestand schreiben lassen.</p>')}'
            if not job['consumed'] and preview['dng']:
                body += f'{_ui_html("<form method='post' action='/fotolabor/delete/")}{job['id']}{_ui_html("'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><label>Freigegebene DNGs und XMP endgültig löschen? <input name='confirm' placeholder='ja' autocomplete='off' required></label><button class='btn' ")}{cleanup_disabled}{_ui_html('>Bestätigte Pakete prüfen und löschen</button></form>')}'
            elif job['consumed']:
                body += _ui_html('<p>Diese Vorschau wurde bereits verwendet. Für weitere Löschungen eine neue Vorschau erstellen.</p>')
            else:
                body += _ui_html('<p>Keine sicheren Löschkandidaten vorhanden.</p>')
        body += _ui_html('</details></div>')
        if job:
            try:
                offset = max(0, int(request.args.get('offset', 0)))
            except ValueError:
                offset = 0
            category = request.args.get('category', '')
            where, params = 'job_id=?', [job['id']]
            if category in ('2','3','4','5'):
                where += ' AND category=?'; params.append(int(category))
            else:
                where += " AND status IN ('damaged','uncheckable')"
            rows = service.query(f'SELECT * FROM fotolabor_files WHERE {where} ORDER BY path LIMIT 100 OFFSET ?', (*params, offset))
            body += _ui_html("<div class='card'><details") + (" open" if category or offset else "") + _ui_html("><summary>Dateiergebnisse anzeigen</summary><h3>") + ('DNG-Kategorie ' + esc(category) if category else _ui_text('Defekte / nicht prüfbare Dateien')) + _ui_html("</h3><p><a href='/fotolabor?view=checks'>Fehlerliste</a></p><table><tr><th>Datei</th><th>Status</th><th>Grund</th><th>Bereinigung</th></tr>")
            for row in rows:
                body += f'{_ui_html("<tr><td style='overflow-wrap:anywhere'>")}{esc(unpack(row['path']))}{_ui_html('</td><td>')}{esc(STATUS[row['status']])}{_ui_html('</td><td>')}{esc(_ui_text(row['reason']))}{_ui_html('</td><td>')}{(_ui_text('Gelöscht') if row['deleted'] else _ui_text('Kandidat – erneute Prüfung erforderlich') if row['safe'] else _ui_text('Geschützt'))}{_ui_html('</td></tr>')}'
            body += _ui_html('</table>')
            if offset:
                body += f'{_ui_html("<a class='btn' href='/fotolabor?job=")}{job['id']}{_ui_html('&category=')}{esc(category)}{_ui_html('&offset=')}{max(0, offset - 100)}{_ui_html("'>Zurück</a>")}'
            if len(rows) == 100:
                body += f'{_ui_html("<a class='btn' href='/fotolabor?job=")}{job['id']}{_ui_html('&category=')}{esc(category)}{_ui_html('&offset=')}{offset + 100}{_ui_html("'>Weitere</a>")}'
            body += _ui_html('</details></div>')
            audit = service.query('SELECT * FROM fotolabor_audit WHERE job_id=? ORDER BY id DESC LIMIT 100', (job['id'],))
            if audit:
                body += _ui_html('<div class="card"><h3>Bereinigungsprotokoll (letzte 100 Einträge)</h3><table>')
                for row in audit:
                    body += f'{_ui_html('<tr><td>')}{esc(unpack(row['path']))}{_ui_html('</td><td>')}{esc(row['action'])}{_ui_html('</td><td>')}{esc(_ui_text(row['reason']))}{_ui_html('</td></tr>')}'
                body += _ui_html('</table></div>')
        return ctx.page(_ui_text('Fotolabor'), body, 'Fotolabor')

    @app.route('/api/fotolabor/status')
    def fotolabor_status():
        try:
            selected = int(request.args['job']) if request.args.get('job') else None
        except ValueError:
            return 'Ungültige Auftragsnummer.', 400
        return jsonify(service.summary(selected))

    @app.route('/fotolabor/reports/<int:job_id>/<report_kind>.txt')
    def fotolabor_defects_download(job_id, report_kind):
        if report_kind not in ('defekte-bilder', 'nicht-pruefbar'):
            return 'Unbekannter Bericht.', 404
        result_status = 'damaged' if report_kind == 'defekte-bilder' else 'uncheckable'
        jobs = service.query('SELECT * FROM fotolabor_jobs WHERE id=?', (job_id,))
        if not jobs:
            return 'Prüfung nicht gefunden.', 404
        report = jobs[0]
        if report['mode'] in ('duplicates','checksum','restore','repair','apply_repairs','refresh_cleanup','repair_mpf'):
            return 'Dies ist eine Duplikatsuche, keine Integritätsprüfung.', 409
        if report['state'] not in ('completed', 'ready'):
            return 'Der Bericht ist erst nach einer abgeschlossenen Prüfung verfügbar.', 409
        counts = {r['status']: r['n'] for r in service.query(
            'SELECT status,COUNT(*) AS n FROM fotolabor_files WHERE job_id=? GROUP BY status', (job_id,))}

        def line(value):
            # Keep each filename on one line, without losing embedded control bytes.
            text = str(value)
            if any(ord(c) < 32 or ord(c) == 127 for c in text):
                text = json.dumps(text, ensure_ascii=False)
            return text.encode('utf-8', 'backslashreplace').decode('utf-8')

        def content():
            yield ('Fotolabor – ' + ('defekte Bilder' if result_status == 'damaged' else 'nicht prüfbare Bilder') + '\n'
                   f"Prüfung: #{job_id}\nBeginn: {report['started']}\nAbschluss: {report['finished']}\n"
                   f"Bildbestand: {service.root}\nGeprüft: {report['checked']} / {report['total']}\n"
                   f"Defekt: {counts.get('damaged', 0)}\nNicht prüfbar: {counts.get('uncheckable', 0)}\n\n"
                   f"Auswahl: {STATUS[result_status]}. Nur Ergebnisse dieser Prüfung.\n"
                   'Nicht prüfbare Bilder sind nicht als gesund bestätigt und stehen in der Weboberfläche.\n'
                   'Pfadangaben mit Steuerzeichen werden als JSON-Zeichenfolge dargestellt.\n\n')
            if not counts.get(result_status, 0):
                yield 'Keine als defekt erkannten Bilder.\n' if result_status == 'damaged' else 'Keine nicht prüfbaren Bilder.\n'
            last = ''
            while True:
                rows = service.query("SELECT f.path,f.reason,d.reason_code FROM fotolabor_files f LEFT JOIN fotolabor_file_details d ON d.job_id=f.job_id AND d.path=f.path WHERE f.job_id=? AND f.status=? AND f.path>? ORDER BY f.path LIMIT 500", (job_id, result_status, last))
                if not rows:
                    break
                for row in rows:
                    last = row['path']
                    yield f"Pfad: {line(service.root / unpack(row['path']))}\nGrundgruppe: {line(checks.REASONS.get(row['reason_code'], row['reason_code'] or 'Sonstiger Prüfgrund'))}\nFehler: {line(row['reason'])}\n\n"

        return Response(content(), content_type='text/plain; charset=utf-8', headers={
            'Content-Disposition': f'attachment; filename="fotolabor-{report_kind}-scan-{job_id}.txt"',
            'Cache-Control': 'private, no-store',
            'X-Content-Type-Options': 'nosniff',
        })

    @app.route('/fotolabor/start', methods=['POST'])
    def fotolabor_start():
        if not protected():
            return 'Ungültiges Formular. Fotolabor-Seite neu laden.', 403
        mode = request.form.get('mode', '')
        if mode not in ('scan', 'cleanup', 'recheck', 'duplicates', 'incremental', 'checksum', 'restore', 'repair'):
            return 'Löschung nur über eine bestätigte Vorschau möglich.', 400
        try:
            source = int(request.form.get('source_job', '0')) or None
            selection = {k: request.form.get(k, '') for k in ('kind', 'status', 'reason', 'folder', 'exclude', 'restore_path')}
            selection.update(gentle=request.form.get('gentle')=='1',max_load=request.form.get('max_load','0'))
            new_job = service.start(mode, source_job=source, selection=selection)
        except ValueError as exc:
            return str(exc), 409
        return redirect(f'/fotolabor?job={new_job}', code=303)

    @app.route('/fotolabor/repairs/mpf', methods=['POST'])
    def fotolabor_repair_mpf():
        if not protected():return 'Ungültiges Formular',403
        try:service.start('repair_mpf',selection={'apply_after':True})
        except ValueError as exc:return str(exc),409
        return redirect('/fotolabor/repairs',303)

    @app.route('/fotolabor/repairs/apply', methods=['POST'])
    def fotolabor_apply_repairs():
        if not protected():return 'Ungültiges Formular',403
        try:
            source=int(request.form.get('source_job','0')) or None
            if request.form.get('prepare_after')=='1' and not source:return 'Quellprüfung erforderlich',400
            job=service.start('apply_repairs',source_job=source,selection={'prepare_after':request.form.get('prepare_after')=='1'})
        except ValueError as exc:return str(exc),409
        return redirect('/fotolabor/repairs',303)

    @app.route('/fotolabor/prepare/<int:source>', methods=['POST'])
    def fotolabor_prepare_again(source):
        if not protected():return 'Ungültiges Formular',403
        try:job=service.start('refresh_cleanup',source_job=source)
        except ValueError as exc:return str(exc),409
        return redirect(f'/fotolabor?job={job}',303)

    @app.route('/fotolabor/resume/<int:job_id>', methods=['POST'])
    def fotolabor_resume(job_id):
        if not protected():
            return 'Ungültiges Formular.', 403
        try:
            service.resume(job_id)
        except ValueError as exc:
            return str(exc), 409
        return redirect(f'/fotolabor?job={job_id}', code=303)

    @app.route('/fotolabor/delete/<int:job_id>', methods=['POST'])
    def fotolabor_delete(job_id):
        if not protected():
            return 'Ungültiges Formular.', 403
        if request.form.get('confirm', '').lower() != 'ja':
            return 'Löschung abgebrochen: Bestätigung ja erforderlich.', 400
        deps = checks.dependencies()
        if not deps['jpeginfo']['path'] or not deps['exiftool']['path']:
            return 'Bereinigung gesperrt: jpeginfo und ExifTool erforderlich.', 409
        try:
            new_job = service.start('delete', source_job=job_id)
        except ValueError as exc:
            return str(exc), 409
        return redirect(f'/fotolabor?job={new_job}', code=303)

    @app.route('/fotolabor/cancel', methods=['POST'])
    def fotolabor_cancel():
        if not protected():
            return 'Ungültiges Formular.', 403
        service.execute("UPDATE fotolabor_jobs SET cancel=1 WHERE state IN ('queued','running')")
        return redirect('/fotolabor', code=303)
