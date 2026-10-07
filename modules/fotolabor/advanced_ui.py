"""Native Manager scope, archive, comparison, restoration and schedule controls."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import datetime,json,os
from pathlib import Path
from flask import request,redirect,send_file,Response
from . import checks,options,scheduling
from .service import unpack


def register(app,ctx,service,token,protected):
    esc=lambda x:ctx.esc(str(x))
    def form_options():
        return dict(folder=request.form.get('folder',''),exclude=request.form.get('exclude',''),gentle=request.form.get('gentle')=='1',max_load=request.form.get('max_load','0'))
    def fields():
        return _ui_html("""<p><label>Ordner relativ zum Fotolabor (leer = alle) <input name='folder' placeholder='2015'></label></p>
        <p><label>Ausgeschlossene Ordner, je Zeile ein Pfad ab Fotolabor-Root<br><textarea name='exclude' placeholder='.immich-storage/thumbs'></textarea></label></p>
        <p><label><input type='checkbox' name='gentle' value='1' checked> Schonend: niedrige CPU-Priorität und Pausen zwischen Dateien</label></p>
        <p><label>Bei Systemlast über diesem Wert warten (0 = aus) <input name='max_load' type='number' min='0' max='128' step='0.5' value='0'></label></p>""")

    @app.route('/fotolabor/tools')
    def fotolabor_tools():
        csrf=esc(token());busy=bool(service.query("SELECT id FROM fotolabor_jobs WHERE state IN ('queued','running') LIMIT 1"));disabled='disabled' if busy else ''
        body=_ui_html("<div class='card'><h2>Prüfoptionen und Zeitpläne</h2><p><a class='btn' href='/fotolabor'>Fotolabor</a> <a class='btn' href='/fotolabor/archive'>Prüfsummenarchiv</a> <a class='btn' href='/fotolabor/compare'>Scanvergleich</a> <a class='btn' href='/fotolabor/restore'>Aus DNG wiederherstellen</a></p>")
        body+=f'{_ui_html("<form method='post' action='/fotolabor/start'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'>")}'+fields()+f'{_ui_html("<button class='btn' name='mode' value='scan' ")}{disabled}{_ui_html(">Vollprüfung</button> <button class='btn' name='mode' value='incremental' ")}{disabled}{_ui_html(">Nur neue/geänderte Bilder prüfen</button> <button class='btn' name='mode' value='checksum' ")}{disabled}{_ui_html('>Alle Prüfsummen kontrollieren</button></form>')}'
        body+=_ui_html('<p>Schnellprüfung übernimmt unveränderte, früher erfolgreiche Befunde anhand von Dateimerkmalen. Unbemerkte Inhaltsänderungen erkennt erst eine Voll- oder Prüfsummenprüfung. DNG-Paare werden immer frisch geprüft. Ordnerfilter gelten für diesen Auftrag; ein Löschlauf prüft weiterhin den gesamten Bestand.</p></div>')
        body+=f'{_ui_html("<div class='card'><h3>Wiederkehrende Prüfung</h3><form method='post' action='/fotolabor/schedules'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><input name='name' value='Fotolabor prüfen' maxlength='100'><select name='mode'><option value='incremental'>Neue/geänderte Bilder</option><option value='scan'>Vollprüfung</option><option value='checksum'>Prüfsummen</option></select><input type='time' name='clock' value='03:00' required>")}'
        for i,label in enumerate(('Mo','Di','Mi','Do','Fr','Sa','So')):body+=f'{_ui_html("<label><input type='checkbox' name='days' value='")}{i}{_ui_html("' checked>")}{_ui_text(label)}{_ui_html('</label> ')}'
        body+=fields()+_ui_html("<p><label><input type='checkbox' name='enabled' value='1'>Zeitplan aktivieren</label></p><button class='btn'>Zeitplan speichern</button></form><p>Startzeit in Server-Ortszeit. Ein belegtes Fotolabor verschiebt fällige Prüfungen bis zum nächsten freien Zeitpunkt. Der zentrale RTC-Planer erhält den Wecktermin; automatisches Aufwachen setzt dessen aktivierte Ausführung und passende Hardware voraus. Laufende Prüfungen halten den Server wach.</p>")
        for row in service.query('SELECT * FROM fotolabor_schedules ORDER BY id DESC'):
            next_at=datetime.datetime.fromtimestamp(row['next_at']).strftime('%d.%m.%Y %H:%M')
            body+=f'{_ui_html('<p>')}{esc(row['name'])}{_ui_html(' · ')}{(_ui_text('Aktiv') if row['enabled'] else _ui_text('Inaktiv'))}{_ui_html(' · nächster Termin ')}{next_at}{_ui_html(' · letzter Auftrag ')}{row['last_job'] or '–'}{_ui_html(' · ')}{esc(row['last_error'])}{_ui_html("</p><form method='post' action='/fotolabor/schedules/")}{row['id']}{_ui_html("/toggle'><input type='hidden' name='csrf' value='")}{csrf}{_ui_html("'><button class='btn'>Aktivieren / deaktivieren</button></form>")}'
        return ctx.page(_ui_text('Fotolabor – Prüfoptionen'),body+_ui_html('</div>'),'Fotolabor')

    @app.route('/fotolabor/schedules',methods=['POST'])
    def fotolabor_schedule_add():
        if not protected():return 'Ungültiges Formular',403
        try:
            mode=request.form.get('mode')
            if mode not in ('scan','incremental','checksum'):raise ValueError('Ungültiger Prüfmodus')
            selection=options.validate(form_options());days=sorted(set(map(int,request.form.getlist('days'))));clock=request.form.get('clock','')
            next_at=scheduling.next_time(clock,days)
            service.execute('INSERT INTO fotolabor_schedules(name,enabled,mode,clock,days,options,next_at) VALUES(?,?,?,?,?,?,?)',(request.form.get('name','Fotolabor')[:100],int(request.form.get('enabled')=='1'),mode,clock,json.dumps(days),json.dumps(selection),next_at))
        except (ValueError,TypeError) as exc:return str(exc),400
        return redirect('/fotolabor/tools',303)

    @app.route('/fotolabor/schedules/<int:item>/toggle',methods=['POST'])
    def fotolabor_schedule_toggle(item):
        if not protected():return 'Ungültiges Formular',403
        rows=service.query('SELECT * FROM fotolabor_schedules WHERE id=?',(item,))
        if not rows:return 'Zeitplan fehlt',404
        row=rows[0]
        service.execute('UPDATE fotolabor_schedules SET enabled=?,next_at=? WHERE id=?',(int(not row['enabled']),scheduling.next_time(row['clock'],json.loads(row['days'])),item))
        return redirect('/fotolabor/tools',303)

    @app.route('/fotolabor/archive')
    def fotolabor_archive():
        try:job=int(request.args.get('job','0'));offset=max(0,int(request.args.get('offset','0')))
        except ValueError:return 'Ungültige Auswahl',400
        history=service.query('SELECT DISTINCT job_id FROM fotolabor_observations ORDER BY job_id DESC LIMIT 30')
        if not job and history:job=history[0]['job_id']
        total=service.query('SELECT COUNT(*) n FROM fotolabor_archive')[0]['n']
        body=f'{_ui_html("<div class='card'><h2>Prüfsummenarchiv</h2><p><a class='btn' href='/fotolabor/tools'>Prüfoptionen</a></p><p>")}{total}{_ui_html(' Dateien mit gespeichertem Ausgangswert. Der erste SHA-256-Wert dokumentiert den damaligen Inhalt, nicht seine Fehlerfreiheit. Änderungen können beabsichtigt sein; sie sind kein Beweis für einen Defekt.</p>')}'
        body+=_ui_html('<p>')+ ' '.join(f'{_ui_html("<a href='?job=")}{h['job_id']}{_ui_html("'>#")}{h['job_id']}{_ui_html('</a>')}' for h in history)+_ui_html('</p>')
        counts=service.query('SELECT change,reused,COUNT(*) n FROM fotolabor_observations WHERE job_id=? GROUP BY change,reused',(job,))
        labels={'new':'Erstmals erfasst','changed':'Inhalt gegenüber vorherigem Stand geändert','unchanged':'Unverändert'}
        for row in counts:body+=f'{_ui_html('<p>')}{esc(_ui_text(labels[row['change']]))}{(_ui_text(' (Befund übernommen, Inhalt nicht erneut gelesen)') if row['reused'] else _ui_text(' (Inhalt gelesen)'))}{': '}{row['n']}{_ui_html('</p>')}'
        body+=_ui_html('<p>Bei älteren oder laufenden Prüfungen kann die Prüfsummenabdeckung unvollständig sein. Die Liste zeigt neue und geänderte Inhalte.</p><table><tr><th>Pfad</th><th>Änderung</th><th>SHA-256</th></tr>')
        rows=service.query("SELECT path,change,digest FROM fotolabor_observations WHERE job_id=? AND change!='unchanged' ORDER BY path LIMIT 100 OFFSET ?",(job,offset))
        for row in rows:body+=f'{_ui_html('<tr><td>')}{esc(service.root / unpack(row['path']))}{_ui_html('</td><td>')}{esc(_ui_text(labels[row['change']]))}{_ui_html("</td><td style='overflow-wrap:anywhere'>")}{esc(row['digest'])}{_ui_html('</td></tr>')}'
        body+=_ui_html('</table>')
        if offset:body+=f'{_ui_html("<a href='?job=")}{job}{_ui_html('&offset=')}{max(0, offset - 100)}{_ui_html("'>Zurück</a> ")}'
        if len(rows)==100:body+=f'{_ui_html("<a href='?job=")}{job}{_ui_html('&offset=')}{offset + 100}{_ui_html("'>Weitere</a>")}'
        return ctx.page(_ui_text('Fotolabor – Prüfsummen'),body+_ui_html('</div>'),'Fotolabor')

    @app.route('/fotolabor/compare')
    def fotolabor_compare():
        jobs=service.query("SELECT id,mode,finished FROM fotolabor_jobs WHERE mode IN ('scan','incremental','cleanup') AND state IN ('completed','ready') ORDER BY id DESC LIMIT 50")
        body=_ui_html("<div class='card'><h2>Prüfergebnisse vergleichen</h2><p><a class='btn' href='/fotolabor/tools'>Prüfoptionen</a></p><form><label>Vorher <select name='old'>")
        for j in jobs:body+=f'{_ui_html("<option value='")}{j['id']}{_ui_html("'>#")}{j['id']}{_ui_html(' ')}{esc(j['finished'])}{_ui_html('</option>')}'
        body+=_ui_html("</select></label><label>Nachher <select name='new'>")
        for j in jobs:body+=f'{_ui_html("<option value='")}{j['id']}{_ui_html("'>#")}{j['id']}{_ui_html(' ')}{esc(j['finished'])}{_ui_html('</option>')}'
        body+=_ui_html("</select></label><button class='btn'>Vergleichen</button></form><p>Verglichen werden abgeschlossene Prüfungen mit identischer Ordnerauswahl. „Nicht mehr erfasst“ bedeutet nicht zwingend gelöscht. Übernommene Schnellscanbefunde behalten ihre ursprüngliche Aussagekraft.</p>")
        if request.args.get('old') and request.args.get('new'):
            try:
                old,new=int(request.args['old']),int(request.args['new']);offset=max(0,int(request.args.get('offset',0)))
                allowed={j['id'] for j in jobs}
                if old not in allowed or new not in allowed or old==new:raise ValueError('Zwei unterschiedliche abgeschlossene Prüfungen auswählen')
                if options.scope(json.loads(service.details(old)['selection']))!=options.scope(json.loads(service.details(new)['selection'])):raise ValueError('Ordnerauswahl/Ausschlüsse unterscheiden sich; Vergleich wäre irreführend')
                query="""SELECT n.path,'Neu erfasst' change FROM fotolabor_files n LEFT JOIN fotolabor_files o ON o.job_id=? AND o.path=n.path WHERE n.job_id=? AND o.path IS NULL
                UNION ALL SELECT o.path,'Nicht mehr erfasst' FROM fotolabor_files o LEFT JOIN fotolabor_files n ON n.job_id=? AND n.path=o.path WHERE o.job_id=? AND n.path IS NULL
                UNION ALL SELECT n.path,o.status||' → '||n.status FROM fotolabor_files n JOIN fotolabor_files o ON o.job_id=? AND o.path=n.path WHERE n.job_id=? AND n.status!=o.status"""
                args=(old,new,new,old,old,new)
                total=service.query('SELECT COUNT(*) n FROM ('+query+')',args)[0]['n']
                rows=service.query(query+' ORDER BY 1 LIMIT 100 OFFSET ?',(*args,offset))
                body+=f'{_ui_html('<p>')}{total}{_ui_html(' Änderungen</p><table><tr><th>Datei</th><th>Ergebnis</th></tr>')}'
                for row in rows:
                    change=row['change']
                    for a,b in [('damaged','Defekt'),('uncheckable','Nicht prüfbar'),('ok','OK')]:change=change.replace(a,b)
                    body+=f'{_ui_html('<tr><td>')}{esc(service.root / unpack(row['path']))}{_ui_html('</td><td>')}{esc(change)}{_ui_html('</td></tr>')}'
                body+=_ui_html('</table>')
                if offset:body+=f'{_ui_html("<a href='?old=")}{old}{_ui_html('&new=')}{new}{_ui_html('&offset=')}{max(0, offset - 100)}{_ui_html("'>Zurück</a> ")}'
                if offset+100<total:body+=f'{_ui_html("<a href='?old=")}{old}{_ui_html('&new=')}{new}{_ui_html('&offset=')}{offset + 100}{_ui_html("'>Weitere</a>")}'
            except ValueError as exc:body+=_ui_html('<p class="err">')+esc(_ui_text(exc))+_ui_html('</p>')
        return ctx.page(_ui_text('Fotolabor – Scanvergleich'),body+_ui_html('</div>'),'Fotolabor')

    @app.route('/fotolabor/restore')
    def fotolabor_restore():
        busy=bool(service.query("SELECT id FROM fotolabor_jobs WHERE state IN ('queued','running') LIMIT 1"))
        disabled='disabled' if busy else ''
        body=f'{_ui_html("<div class='card'><h2>Bild aus DNG wiederherstellen</h2><p><a class='btn' href='/fotolabor/tools'>Prüfoptionen</a></p><p>Erstellt ein neu entwickeltes 16-Bit-TIFF und ein JPEG in separaten privaten Ordnern. Originaldateien bleiben unverändert. Die Darstellung kann vom ursprünglichen JPEG abweichen; Sichtkontrolle erforderlich. Verwendete DNGs werden dauerhaft vor Bereinigung geschützt.</p><form method='post' action='/fotolabor/start'><input type='hidden' name='csrf' value='")}{esc(token())}{_ui_html("'><input type='hidden' name='mode' value='restore'><label>DNG-Pfad relativ zum Fotolabor <input name='restore_path' required placeholder='2015/Foto.dng'></label><button class='btn' ")}{disabled}{_ui_html('>Wiederherstellung starten</button></form>')}'
        rows=service.query('SELECT r.*,j.state,j.error FROM fotolabor_restores r JOIN fotolabor_jobs j ON j.id=r.job_id ORDER BY job_id DESC LIMIT 100')
        for r in rows:
            body+=f'{_ui_html('<h3>#')}{r['job_id']}{_ui_html(' ')}{esc(unpack(r['path']))}{_ui_html('</h3><p>')}{esc(_ui_text(r['status']))}{_ui_html(' · ')}{esc(_ui_text(r['reason']) or _ui_text(r['error']))}{_ui_html('</p>')}'
            if r['state'] in ('queued','running'):
                body+=f'{_ui_html("<form method='post' action='/fotolabor/cancel'><input type='hidden' name='csrf' value='")}{esc(token())}{_ui_html("'><button class='btn'>Wiederherstellung anhalten</button></form><script>setTimeout(()=>location.reload(),10000)</script>")}'
            elif r['state'] in ('cancelled','interrupted','failed'):
                body+=f'{_ui_html("<form method='post' action='/fotolabor/resume/")}{r['job_id']}{_ui_html("'><input type='hidden' name='csrf' value='")}{esc(token())}{_ui_html("'><button class='btn' ")}{disabled}{_ui_html('>Erneut versuchen</button></form>')}'
            if r['status']=='completed':body+=f'{_ui_html("<a class='btn' href='/fotolabor/restored/")}{r['job_id']}{_ui_html("/tiff'>TIFF herunterladen</a> <a class='btn' href='/fotolabor/restored/")}{r['job_id']}{_ui_html("/jpeg'>JPEG herunterladen</a><p><img loading='lazy' style='max-width:100%;max-height:500px' src='/fotolabor/restored/")}{r['job_id']}{_ui_html("/jpeg?inline=1'></p>")}'
        return ctx.page(_ui_text('Fotolabor – DNG-Wiederherstellung'),body+_ui_html('</div>'),'Fotolabor')

    @app.route('/fotolabor/restored/<int:job>/<kind>')
    def fotolabor_restored(job,kind):
        if kind not in ('tiff','jpeg'):return 'Unbekanntes Format',404
        rows=service.query("SELECT * FROM fotolabor_restores WHERE job_id=? AND status='completed'",(job,))
        if not rows:return 'Keine Wiederherstellung vorhanden',404
        path=Path(rows[0][kind])
        if path.parent.parent!=Path(ctx.state_dir) or not path.parent.name.startswith('fotolabor-restore-'):return 'Ungültiger Ausgabepfad',409
        try:
            with checks.directory(path.parent) as parent,checks.opened(parent,path.name) as fd:handle=os.fdopen(os.dup(fd),'rb')
            response=send_file(handle,mimetype='image/jpeg' if kind=='jpeg' else 'image/tiff',as_attachment=request.args.get('inline')!='1',download_name=path.name,max_age=0)
            response.call_on_close(handle.close);response.headers['Cache-Control']='private, no-store'
            return response
        except (OSError,checks.Uncheckable):return 'Datei nicht verfügbar',404
