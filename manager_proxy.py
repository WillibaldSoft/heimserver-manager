"""Trust HTTPS metadata only from our loopback Apache and its host-local token."""
import hmac
import ipaddress
import json
from pathlib import Path
from flask import request
from flask.sessions import SecureCookieSessionInterface


class ManagerProxy:
    def __init__(self, app, config):
        self.app, self.config = app, Path(config)

    def __call__(self, environ, start_response):
        supplied = environ.pop('HTTP_X_SERVER_MANAGER_PROXY_TOKEN', '')
        scheme = environ.pop('HTTP_X_SERVER_MANAGER_HTTPS', '')
        address = environ.pop('HTTP_X_SERVER_MANAGER_CLIENT_IP', '')
        try:
            local = ipaddress.ip_address(environ.get('REMOTE_ADDR', '')).is_loopback
            token = json.loads(self.config.read_text()).get('proxy_token', '') if local else ''
            if token and hmac.compare_digest(token, supplied) and scheme == 'on':
                environ['wsgi.url_scheme'] = 'https'
                if address:
                    environ['REMOTE_ADDR'] = str(ipaddress.ip_address(address))
        except (OSError, ValueError, TypeError):
            pass
        return self.app(environ, start_response)


class ManagerSessions(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return request.is_secure or super().get_cookie_secure(app)


def configure(app, config):
    app.wsgi_app = ManagerProxy(app.wsgi_app, config)
    app.session_interface = ManagerSessions()
