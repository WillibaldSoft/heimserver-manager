from ui_translation import html_literal as _ui_html, text as _ui_text
from werkzeug.exceptions import RequestEntityTooLarge
import datetime
import hashlib
import html
import os
import secrets
from urllib.parse import urlencode
from flask import request,send_file,session,redirect
from werkzeug.exceptions import RequestedRangeNotSatisfiable
from . import files
import server_settings as cfg

esc=lambda value:html.escape(str(value),quote=True)
def size(value):
    for unit in ('B','KiB','MiB','GiB','TiB'):
        if value<1024 or unit=='TiB':return f'{value:.1f} {unit}'
        value/=1024

def register(app,ctx):
    def page(body,code=200):
        response=app.make_response((ctx.page(_ui_text('Downloads'),body,'Daten'),code))
        response.headers['Cache-Control']='private, no-store'
        return response
    def fail(exc):
        message='Ordner oder Datei ist nicht verfügbar. Hauptordner und Zugriffsrechte in den Einstellungen prüfen.'
        if isinstance(exc,ValueError):message=str(exc)
        return page(_ui_html("<div class='card'><p>")+esc(_ui_text(message))+_ui_html("</p><p><a href='/downloads'>Downloads</a> · <a href='/settings/server-paths'>Einstellungen</a></p></div>"),400 if isinstance(exc,ValueError) else 404)
    @app.route('/downloads/upload',methods=['POST'])
    def upload():
        request.max_content_length=files.UPLOAD_LIMIT+1024*1024
        finish=files.track()
        try:
            if not secrets.compare_digest(request.form.get('csrf',''),session.get('download_upload_csrf','!')):
                return page(_ui_html('Formular abgelaufen.'),403)
            if session.get('download_upload_root')!=str(cfg.get('download_root')):
                raise ValueError('Der Hauptordner wurde geändert. Bitte die Seite neu öffnen.')
            item=request.files.get('file')
            if item is None or not item.filename:raise ValueError('Bitte eine Datei auswählen.')
            files.upload(item.stream,item.filename)
            return redirect('/downloads?uploaded=1',303)
        except RequestEntityTooLarge:return page(_ui_html('Upload zu groß. Maximal 512 MiB erlaubt.'),413)
        except (OSError,ValueError) as exc:return fail(exc)
        finally:finish()
    @app.route('/downloads',endpoint='downloads_index')
    def index():
        value=request.args.get('path','');query=request.args.get('q','')[:200]
        try:
            components=files.parts(value);number=int(request.args.get('page','1'))
            rows,number,pages,total=files.entries(value,query,number)
            session.setdefault('download_upload_csrf',secrets.token_urlsafe(32))
            session['download_upload_root']=str(cfg.get('download_root'))
            upload_card=_ui_html("<div class='card'><h2>Datei hochladen</h2><p>Ziel ist immer der oben angegebene Hauptordner, auch wenn ein Unterordner geöffnet ist. Maximal 512 MiB pro Datei. Vorhandene Dateien werden nicht überschrieben.</p>")
            if request.args.get('uploaded')=='1':upload_card+=_ui_html('<p>Datei erfolgreich hochgeladen.</p>')
            upload_card+=_ui_html("<form method='post' action='/downloads/upload' enctype='multipart/form-data'><input type='hidden' name='csrf' value='")+esc(session['download_upload_csrf'])+_ui_html("'><label>Datei auswählen <input type='file' name='file' required></label><button class='btn'>In Hauptordner hochladen</button></form><p>Während der Übertragung diese Seite geöffnet lassen.</p>")
            upload_card+=_ui_html("</div>")
            body=_ui_html("<div class='card'><h2>Dateien herunterladen</h2><p>Hauptordner: <code>")+esc(cfg.get('download_root'))+_ui_html("</code> · <a href='/settings/server-paths'>Vorgabe ändern</a></p><p>Unterordner öffnen und gewünschte Dateien herunterladen. Versteckte Dateien, symbolische Links und Hardlinks werden nicht angeboten.</p><nav aria-label='Ordnerpfad'><a href='/downloads'>Hauptordner</a>")
            for i,name in enumerate(components):body+=_ui_html(" / <a href='/downloads?")+esc(urlencode({'path':'/'.join(components[:i+1])}))+"'>"+esc(name)+_ui_html('</a>')
            body+=_ui_html("</nav><form method='get'><input type='hidden' name='path' value='")+esc(value)+_ui_html("'><label>Dateiname im aktuellen Ordner <input name='q' value='")+esc(query)+_ui_html("'></label> <button class='btn'>Suchen</button></form></div>")+upload_card+_ui_html("<div class='card' style='overflow-x:auto'><table><tr><th>Name</th><th>Größe</th><th>Geändert</th><th>Aktion</th></tr>")
            for row in rows:
                path='/'.join(components+[row['name']]);url=('/downloads' if row['directory'] else '/downloads/file')+'?'+urlencode({'path':path})
                body+=_ui_html('<tr><td>')+('📁 ' if row['directory'] else '')+esc(row['name'])+_ui_html('</td><td>')+('—' if row['directory'] else size(row['size']))+_ui_html('</td><td>')+datetime.datetime.fromtimestamp(row['modified']).strftime('%d.%m.%Y %H:%M')+_ui_html("</td><td><a class='btn' href='")+esc(url)+"'>"+(_ui_text('Öffnen') if row['directory'] else _ui_text('Herunterladen'))+_ui_html('</a></td></tr>')
            body+=_ui_html('</table>')
            if not rows:body+=_ui_html('<p>Keine passenden Dateien oder Unterordner vorhanden.</p>')
            body+=_ui_html('<p>')+str(total)+_ui_html(' Einträge · Seite ')+str(number)+' / '+str(pages)+_ui_html('</p>')
            for label,n in [('Zurück',number-1),('Weiter',number+1)]:
                if 1<=n<=pages:body+=_ui_html("<a class='btn' href='/downloads?")+esc(urlencode({'path':value,'q':query,'page':n}))+"'>"+_ui_text(label)+_ui_html('</a>')
            return page(body+_ui_html('</div>'))
        except (OSError,ValueError) as exc:return fail(exc)
    @app.route('/downloads/file',endpoint='downloads_file')
    def download():
        stream=None;finish=None
        try:
            value=request.args.get('path','');fd,info=files.open_path(value)
            stream=os.fdopen(fd,'rb');finish=files.track()
            response=send_file(stream,as_attachment=True,download_name=files.parts(value)[-1],mimetype='application/octet-stream',conditional=False,etag=False,last_modified=info.st_mtime)
            response.content_length=info.st_size
            response.set_etag(hashlib.sha256(f'{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}'.encode()).hexdigest())
            response.make_conditional(request.environ,accept_ranges=True,complete_length=info.st_size)
            response.headers['Cache-Control']='private, no-store'
            response.headers['X-Content-Type-Options']='nosniff'
            response.direct_passthrough=False
            def close():
                try:stream.close()
                finally:finish()
            response.call_on_close(close)
            return response
        except RequestedRangeNotSatisfiable:
            if stream:stream.close()
            if finish:finish()
            raise
        except (OSError,ValueError) as exc:
            if stream:stream.close()
            if finish:finish()
            return fail(exc)
