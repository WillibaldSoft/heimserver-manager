"""Emergency administrator, explicitly approved PAM users and scoped machine tokens."""
from ui_translation import html_literal as _ui_html, text as _ui_text
from i18n import tr, language, selector, COOKIE
from responsive_ui import CSS as RESPONSIVE_CSS
from collections import OrderedDict
from datetime import timedelta
import html
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit, quote, unquote
import ipaddress
from flask import request, session, redirect, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

AGENT_PATHS={'/api/clients/enroll','/api/clients/backup','/api/clients/status','/api/clients/heartbeat','/api/clients/need-server','/api/clients/release-server'}
SESSION_SECONDS=8*60*60


def atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.auth-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(data,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


class Accounts:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.path.with_suffix('.lock'),os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if not self.path.exists():
                atomic(self.path,dict(username='ADMIN',password_hash=generate_password_hash('ADMIN'),
                                      default_password=True,revision=secrets.token_hex(16),
                                      session_secret=secrets.token_hex(32),automation_token=secrets.token_urlsafe(48)))
        self.read()  # Fail closed on invalid configuration; never recreate a broken account.
    def read(self):
        with self.lock:
            data=json.loads(self.path.read_text())
            for key in ('username','password_hash','revision','session_secret','automation_token'):
                if not isinstance(data.get(key),str) or not data[key]:raise ValueError('Ungültige Zugangskonfiguration: '+key)
            return data
    def set_session_minutes(self,value):
        try:
            if not re.fullmatch(r'[0-9]{1,4}',str(value)):raise ValueError
            minutes=int(value)
            if not 1<=minutes<=1440:raise ValueError
        except (ValueError,TypeError):
            raise ValueError('Anmeldedauer: 1 bis 1440 Minuten eingeben.')
        with self.lock:
            data=self.read();data['session_minutes']=minutes;atomic(self.path,data)
        return data
    def verify(self,username,password):
        if not isinstance(password,str) or len(password)>256:return False
        data=self.read()
        valid=check_password_hash(data['password_hash'],password)
        return valid and secrets.compare_digest(str(username).encode(),data['username'].encode())
    def change(self,username,password):
        if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}',username):raise ValueError('Benutzername: 1–64 Buchstaben, Ziffern oder _ . @ - verwenden.')
        if len(password)<8 or len(password)>256:raise ValueError('Neues Passwort: 8 bis 256 Zeichen verwenden.')
        with self.lock:
            data=self.read();data.update(username=username,password_hash=generate_password_hash(password),
                                         default_password=False,revision=secrets.token_hex(16))
            atomic(self.path,data)
        return data


class Attempts:
    """Bounded rate limit by peer address (never trust forwarded IP headers)."""
    def __init__(self):self.entries=OrderedDict();self.lock=threading.Lock()
    def take(self,key):
        now=time.monotonic()
        with self.lock:
            times=[v for v in self.entries.get(key,[]) if v>now-600]
            if len(times)>=10:return False
            times.append(now);self.entries[key]=times;self.entries.move_to_end(key)
            while len(self.entries)>2048:self.entries.popitem(last=False)
            return True
    def clear(self,key):
        with self.lock:self.entries.pop(key,None)


def safe_next(value):
    if not value or not value.startswith('/') or unquote(value).startswith('//') or '\\' in unquote(value) or any(ord(c)<32 for c in unquote(value)):return '/'
    parsed=urlsplit(value)
    return value if not parsed.netloc and not parsed.scheme else '/'


def machine_allowed(path,method):
    return method=='POST' and (path=='/apps/update-check/run-all' or re.fullmatch(r'/apps/[a-z0-9_]+/backup',path) is not None)


def register(app,config_dir):
    accounts=Accounts(Path(config_dir)/'authentication.json')
    from modules.accounts.store import Users
    from modules.accounts import system,policy
    users=Users(Path(config_dir)/'system-users.json')
    system.ensure_policy()
    attempts=Attempts()
    app.secret_key=accounts.read()['session_secret']
    app.config.update(SESSION_COOKIE_NAME='server_manager_session',SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict',PERMANENT_SESSION_LIFETIME=timedelta(hours=24),SESSION_REFRESH_EACH_REQUEST=False,
                      SESSION_COOKIE_SECURE=os.environ.get('SERVER_MANAGER_COOKIE_SECURE','0')=='1')
    app.extensions['server_manager_auth']=accounts
    app.extensions['server_manager_users']=users

    def csrf():
        session.setdefault('auth_csrf',secrets.token_urlsafe(32))
        return session['auth_csrf']
    def csrf_input():return "<input type='hidden' name='auth_csrf' value='"+html.escape(csrf(),quote=True)+"'>"
    def valid_csrf():
        supplied=request.form.get('auth_csrf','') or request.headers.get('X-Server-Manager-CSRF','')
        return bool(supplied and secrets.compare_digest(supplied,session.get('auth_csrf','!')))
    def logged_in():
        data=accounts.read();principal=None
        if session.get('auth_expires',0)>time.time():
            if session.get('auth_kind','local')=='local':
                if session.get('auth_user')==data['username'] and session.get('auth_revision')==data['revision']:
                    principal=dict(kind='local',name=data['username'],role='admin',modules=[],revision=data['revision'])
            elif session.get('auth_kind')=='system':
                candidate=users.principal(session.get('auth_user',''),data['session_secret'])
                if candidate and candidate['revision']==session.get('auth_revision') and candidate['uid']==session.get('auth_uid') and secrets.compare_digest(candidate['stamp'],session.get('auth_stamp','')):principal=candidate
        g.auth_principal=principal
        return principal is not None
    def verify_login(username,password):
        data=accounts.read()
        if username==data['username']:
            if accounts.verify(username,password):return dict(kind='local',name=data['username'],role='admin',modules=[],revision=data['revision'])
            return None
        return users.verify(username,password,data['session_secret'])
    def reauth(password):
        if not attempts.take('account:'+str(request.remote_addr)):return False
        current=getattr(g,'auth_principal',None)
        verified=verify_login(session.get('auth_user',''),password)
        if verified and current and verified['kind']==current['kind'] and verified['role']=='admin' and verified['revision']==current['revision']:
            attempts.clear('account:'+str(request.remote_addr));return True
        return False
    app.extensions['server_manager_admin_reauth']=reauth

    def sign_in(principal=None):
        data=accounts.read();session.clear();session.permanent=True
        principal=principal or dict(kind='local',name=data['username'],role='admin',modules=[],revision=data['revision'])
        session.update(auth_kind=principal['kind'],auth_user=principal['name'],auth_revision=principal['revision'],auth_expires=time.time()+data.get('session_minutes',SESSION_SECONDS//60)*60)
        if principal['kind']=='system':session.update(auth_uid=principal['uid'],auth_stamp=principal['stamp'])
        g.auth_principal=principal;csrf()
    def denied():
        if request.path.startswith('/api/') or request.method not in ('GET','HEAD'):
            return jsonify(ok=False,error='authentication_required',login='/login'),401
        return redirect('/login?next='+quote(request.full_path.rstrip('?'),safe=''),303)

    @app.before_request
    def authenticate():
        if request.endpoint in ('auth_login','auth_language'):return
        # Basic liveness reveals no configuration and keeps existing client probes working.
        if request.path=='/api/health' and request.method in ('GET','HEAD'):return
        # Each endpoint verifies its own enabled client token before returning any data.
        if request.path in AGENT_PATHS:return
        token=request.headers.get('X-Server-Manager-Automation','')
        if token and request.remote_addr in ('127.0.0.1','::1') and machine_allowed(request.path,request.method):
            if secrets.compare_digest(token,accounts.read()['automation_token']):
                g.auth_machine=True;return
        if not logged_in():return denied()
        g.auth_user=session['auth_user']
        if not policy.allowed(g.auth_principal,request.path,request.method):
            if request.path.startswith('/api/') or request.method not in ('GET','HEAD'):return jsonify(ok=False,error='permission_denied'),403
            return shell('Kein Zugriff',_ui_html("<p>Dieser Bereich ist für dein Manager-Konto nicht freigegeben.</p><p><a href='/account'>Mein Bereich</a></p>")),403
        if request.path=='/' and g.auth_principal['role']!='admin':return redirect('/account',303)
        # Legacy forms are protected centrally in addition to module-specific tokens.
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('Origin','')
            expected=request.host_url.rstrip('/')
            if origin:
                if origin!=expected:return jsonify(ok=False,error='cross_origin_request'),403
            elif not valid_csrf():return jsonify(ok=False,error='csrf_required'),403

    @app.after_request
    def auth_headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        response.headers['Referrer-Policy']='same-origin'
        if request.path in ('/static/i18n/de.js','/static/i18n/en.js') and request.method in ('GET','HEAD') and response.status_code==200:
            response.headers['Cache-Control']='private, max-age=86400'
        elif request.path not in AGENT_PATHS and request.path!='/api/health':
            response.headers['Cache-Control']='no-store'
        return response

    def shell(title,body):
        title = tr(title)
        body = body.replace("Heimserver Manager", tr(_ui_text("Heimserver Manager")))
        return """<!doctype html><html lang='"""+language()+"""'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>"""+html.escape(title)+""" · """+html.escape(tr(_ui_text("Heimserver Manager")))+"""</title><style>body{font-family:system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0;padding:24px}main{max-width:440px;margin:8vh auto;background:#1f2937;padding:28px;border-radius:14px;border:1px solid #374151}input{box-sizing:border-box;width:100%;padding:12px;margin:8px 0 16px;border-radius:7px;border:1px solid #6b7280;background:#111827;color:#fff}button{padding:12px 18px;border:0;border-radius:7px;background:#1d4ed8;color:white;font:inherit;cursor:pointer}a{color:#93c5fd}.error{color:#fca5a5}</style><style>"""+RESPONSIVE_CSS+_ui_html("""</style></head><body class="auth-page"><main><h1>""")+html.escape(title)+_ui_html('</h1>')+selector(csrf_input())+body+'</main></body></html>'

    @app.route('/language', methods=['POST'], endpoint='auth_language')
    def set_language():
        if not valid_csrf():return 'csrf_required',403
        choice=request.form.get('language','')
        if choice not in ('de','en'):return 'invalid_language',400
        response=redirect(safe_next(request.form.get('next')),303)
        response.set_cookie(COOKIE,choice,max_age=31536000,httponly=True,secure=request.is_secure,samesite='Lax')
        return response

    @app.route('/login',methods=['GET','POST'],endpoint='auth_login')
    def login():
        dest=safe_next(request.form.get('next') if request.method=='POST' else request.args.get('next'))
        if request.method=='GET' and logged_in() and request.args.get('reauth')!='1':return redirect(dest,303)
        error='';code=200
        if request.method=='POST':
            if not valid_csrf():error='Formular abgelaufen. Bitte erneut anmelden.';code=403
            elif not attempts.take(request.remote_addr):error='Zu viele Anmeldeversuche. Bitte in zehn Minuten erneut versuchen.';code=429
            else:
                principal=verify_login(request.form.get('username',''),request.form.get('password',''))
                if principal:
                    attempts.clear(request.remote_addr);sign_in(principal)
                    if principal['role']!='admin' and not policy.allowed(principal,urlsplit(dest).path):dest='/account'
                    return redirect(dest,303)
                error='Benutzername oder Passwort ist falsch.';code=401
        if code in (401,429):
            try:peer=str(ipaddress.ip_address(request.remote_addr))
            except ValueError:peer=None
            if peer:app.logger.warning("SERVER_MANAGER_AUTH_FAILURE ip=%s",peer)
        body=_ui_html("<p>")+tr(_ui_text('Bitte anmelden, um den Server zu verwalten.'))+_ui_html("</p>")
        body+=_ui_html('<p>Freigeschaltete Linux-Benutzer melden sich mit ihrem Systempasswort an. Der eigenständige Manager-Administrator bleibt als Notfallzugang verfügbar.</p>')
        if accounts.read().get('default_password',False):
            body+=_ui_html("<aside class='default-login'><p><strong>")+tr('Standard-Anmeldedaten')+_ui_html("</strong></p><p>")+tr(_ui_text('Benutzername'))+_ui_html(": <code>ADMIN</code><br>")+tr(_ui_text('Passwort'))+_ui_html(": <code>ADMIN</code></p><p>")+tr(_ui_text('Bitte nach der ersten Anmeldung unter „Zugang ändern“ ein eigenes Passwort festlegen.'))+_ui_html("</p></aside>")

        if error:body+=_ui_html("<p class='error' role='alert'>")+html.escape(tr(error))+_ui_html('</p>')
        body+=_ui_html("<form method='post'>")+csrf_input()+_ui_html("<input type='hidden' name='next' value='")+html.escape(dest,quote=True)+_ui_html("'><label>")+tr(_ui_text('Benutzername'))+_ui_html("<input name='username' autocomplete='username' required autofocus maxlength='64'></label><label>")+tr(_ui_text('Passwort'))+_ui_html("<input name='password' type='password' autocomplete='current-password' required maxlength='256'></label><button>")+tr('Anmelden')+_ui_html("</button></form>")
        response=app.make_response((shell('Heimserver Manager',body),code))
        if code==429:response.headers['Retry-After']='600'
        return response

    @app.route('/logout',methods=['POST'],endpoint='auth_logout')
    def logout():
        if not valid_csrf():return 'Formular abgelaufen.',403
        session.clear();return redirect('/login',303)

    @app.route('/settings/access',methods=['GET','POST'],endpoint='auth_settings')
    def access():
        if g.auth_principal['kind']=='system':
            body=_ui_html("<p>Systemkonto: <b>")+html.escape(session['auth_user'])+_ui_html("</b>. Das Passwort wird von Linux/PAM geprüft und nicht im Manager gespeichert. Mit <code>passwd</code> oder der Benutzerverwaltung des Betriebssystems ändern.</p><p><a href='/account'>Mein Bereich</a></p>")
            if g.auth_principal['role']=='admin':body+=_ui_html("<p><a href='/settings/users'>Manager-Benutzer verwalten</a></p><p>Den unabhängigen Notfallzugang nur nach Anmeldung mit dessen Zugangsdaten ändern.</p>")
            return shell('Mein Zugang',body)
        error='';message='';code=200
        if request.method=='POST':
            if not valid_csrf():error='Formular abgelaufen.';code=403
            elif not attempts.take('account:'+str(request.remote_addr)):error='Zu viele Versuche. Bitte zehn Minuten warten.';code=429
            elif not accounts.verify(session['auth_user'],request.form.get('current_password','')):error='Das aktuelle Passwort ist falsch.';code=400
            elif request.form.get('action')=='session_duration':
                try:
                    accounts.set_session_minutes(request.form.get('session_minutes',''))
                    attempts.clear('account:'+str(request.remote_addr))
                    message='Anmeldedauer gespeichert. Gilt ab der nächsten Anmeldung; laufende Sitzungen behalten ihr Ablaufdatum.'
                except ValueError as exc:error=str(exc);code=400
            elif request.form.get('new_password')!=request.form.get('repeat_password'):error='Die neuen Passwörter stimmen nicht überein.';code=400
            else:
                try:
                    if request.form.get('username','').strip() in users.read()['users']:raise ValueError('Dieser Name ist bereits als Systemkonto freigeschaltet.')
                    accounts.change(request.form.get('username','').strip(),request.form.get('new_password',''))
                    attempts.clear('account:'+str(request.remote_addr));sign_in()
                    message='Zugang gespeichert. Andere Anmeldungen sind jetzt ungültig.'
                except ValueError as exc:error=str(exc);code=400
        data=accounts.read()
        body=_ui_html("<p><a href='/settings'>← Einstellungen</a> · <a href='/settings/users'>Manager-Benutzer</a></p><p>Benutzername und Passwort für den Heimserver Manager ändern.</p>")
        if data.get('default_password'):body+=_ui_html('<p>Das Installationspasswort ist noch aktiv. Hier kannst du einen eigenen Zugang festlegen.</p>')
        if error:body+=_ui_html("<p class='error' role='alert'>")+html.escape(tr(error))+_ui_html('</p>')
        if message:body+=_ui_html('<p>')+html.escape(tr(message))+_ui_html('</p>')
        body+=_ui_html("<form method='post'>")+csrf_input()+_ui_html("<label>")+tr(_ui_text('Benutzername'))+_ui_html("<input name='username' value='")+html.escape(data['username'],quote=True)+_ui_html("' autocomplete='username' required maxlength='64'></label><label>Aktuelles Passwort<input name='current_password' type='password' autocomplete='current-password' required></label><label>Neues Passwort<input name='new_password' type='password' autocomplete='new-password' minlength='8' maxlength='256' required></label><label>Neues Passwort wiederholen<input name='repeat_password' type='password' autocomplete='new-password' minlength='8' maxlength='256' required></label><button>Zugang speichern</button></form>")
        body+=_ui_html("<hr><h2>")+tr('Anmeldedauer')+_ui_html("</h2><p>")+tr(_ui_text('Feste Dauer ab Anmeldung, unabhängig von Aktivität. Danach erneut mit demselben Passwort anmelden. Laufende Hintergrundaufträge laufen weiter.'))+_ui_html("</p><form method='post'>")+csrf_input()+_ui_html("<input type='hidden' name='action' value='session_duration'><label>")+tr('Dauer in Minuten (1–1440; 60 Minuten = 1 Stunde)')+_ui_html("<input type='number' name='session_minutes' min='1' max='1440' step='1' required value='")+str(data.get('session_minutes',SESSION_SECONDS//60))+_ui_html("'></label><label>")+tr(_ui_text('Aktuelles Passwort'))+_ui_html("<input name='current_password' type='password' autocomplete='current-password' required maxlength='256'></label><button>")+tr('Anmeldedauer speichern')+_ui_html("</button></form>")
        return shell('Zugang verwalten',body),code

    app.extensions['manager_language_selector'] = lambda: selector(csrf_input())

    def toolbar():
        if not logged_in():return ''
        data=accounts.read()
        body=_ui_html("<details class='account-menu'><summary>")+tr('Angemeldet: ')+_ui_html("<b>")+html.escape(session['auth_user'])+_ui_html("</b></summary><div class='account-menu-content'><div class='account-toolbar'><a href='/settings/access'>")+tr(_ui_text('Zugang ändern'))+_ui_html("</a><form method='post' action='/logout' style='margin:0'>")+csrf_input()+_ui_html("<button class='btn' type='submit'>")+tr(_ui_text('Abmelden'))+_ui_html("</button></form></div>")
        if g.auth_principal['role']=='admin':body+=_ui_html("<p><a href='/settings/users'>Manager-Benutzer</a></p>")
        else:body+=_ui_html("<p><a href='/account'>Mein Bereich</a></p>")
        if g.auth_principal['kind']=='local' and data.get('default_password'):body+=_ui_html("<p class='warn account-notice'>")+tr('Installationspasswort aktiv · ')+_ui_html("<a href='/settings/access'>")+tr('Eigenes Passwort festlegen')+_ui_html("</a></p>")
        return body + selector(csrf_input()) + _ui_html("</div></details>")
    from modules.accounts.ui import register as register_users
    register_users(app,users,accounts,shell,csrf_input,valid_csrf,reauth)
    return toolbar
