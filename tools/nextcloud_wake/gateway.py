#!/usr/bin/env python3
"""Streaming Nextcloud wake gateway behind a local TLS reverse proxy."""
import asyncio,contextlib,json,ssl,time,ipaddress,secrets,hashlib,hmac,contextvars,collections
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web,ClientSession,ClientTimeout,DummyCookieJar,TCPConnector
from multidict import CIMultiDict
from yarl import URL
VERSION='1.1'

# HSM_NEXTCLOUD_WAKE_CONTROL_V2: applies only to this Nextcloud gateway.
WAKE_CONTROL = Path('/etc/server-manager-nextcloud-wake-control.json')
def wake_enabled():
    try:
        config = json.loads(WAKE_CONTROL.read_text())
        mode = config.get('mode')
        if mode in ('active', 'inactive'):return mode == 'active'
        if mode != 'schedule' or type(config.get('default')) is not bool:return False
        now = time.localtime();minute = now.tm_hour * 60 + now.tm_min
        result = config['default']
        for entry in config['periods']:
            start,end = entry['start'],entry['end']
            if type(start) is not int or type(end) is not int or not 0 <= start < 1440 or not 0 <= end < 1440 or start == end or type(entry['enabled']) is not bool:return False
            if (start <= minute < end if start < end else minute >= start or minute < end):result = entry['enabled']
        return result
    except FileNotFoundError:return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):return False


HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade'}
def clean_headers(headers):
    blocked=HOP|{v.strip().lower() for v in headers.get('Connection','').split(',')}
    return CIMultiDict((k,v) for k,v in headers.items() if k.lower() not in blocked)
REQUEST_ID=contextvars.ContextVar('wake_request_id',default='background')
_AUDIT_WINDOW=collections.deque()
_AUDIT_DROPPED=0
def audit(event,**fields):
    """Bounded local journal events. Callers pass only allowlisted metadata."""
    global _AUDIT_DROPPED
    now=time.monotonic()
    while _AUDIT_WINDOW and now-_AUDIT_WINDOW[0]>=60:_AUDIT_WINDOW.popleft()
    if len(_AUDIT_WINDOW)>=120:
        _AUDIT_DROPPED+=1;return
    _AUDIT_WINDOW.append(now)
    data=dict(event=event,request_id=REQUEST_ID.get(),**fields)
    if _AUDIT_DROPPED:data['suppressed_events']=_AUDIT_DROPPED;_AUDIT_DROPPED=0
    print('HSM_WAKE '+json.dumps(data,ensure_ascii=True,sort_keys=True),flush=True)
def request_meta(request,token):
    peer=request.headers.get('X-Forwarded-For','').split(',')[0].strip() if request.remote in ('127.0.0.1','::1') else request.remote
    try:peer=str(ipaddress.ip_address(peer))
    except (ValueError,TypeError):peer='unknown'
    source=hmac.new(token.encode(),peer.encode(),hashlib.sha256).hexdigest()[:12]
    ua=request.headers.get('User-Agent','').lower()
    client='davx' if 'davx' in ua else 'nextcloud' if 'nextcloud' in ua else 'other'
    path=request.path.lower()
    category='dav' if '/remote.php/dav' in path else 'discovery' if path.startswith('/.well-known/') else 'status' if path.endswith('/status.php') else 'other'
    method=request.method if request.method in ('GET','HEAD','POST','PUT','DELETE','PROPFIND','REPORT','OPTIONS','MKCOL','MOVE','COPY','PROPPATCH') else 'OTHER'
    return dict(source_id=source,client=client,category=category,method=method,authorization_present=bool(request.headers.get('Authorization')))
def background_poll(request):
    """Only recognizable, read-only desktop polling; DAVx remains wake eligible."""
    ua=request.headers.get('User-Agent','').lower()
    if 'nextcloud' not in ua or 'davx' in ua:return False
    path=request.path.lower().rstrip('/')
    if request.method=='PROPFIND':
        return '/remote.php/dav/' in path or path.endswith('/remote.php/dav') or '/remote.php/webdav' in path
    if request.method not in ('GET','HEAD'):return False
    return (path.endswith('/status.php') or
            any(path.endswith(endpoint) for endpoint in (
                '/ocs/v2.php/apps/notifications/api/v2/notifications',
                '/ocs/v2.php/apps/user_status/api/v1/user_status',
                '/ocs/v1.php/cloud/capabilities','/ocs/v2.php/cloud/capabilities',
                '/ocs/v1.php/cloud/user','/ocs/v2.php/cloud/user')))

class Gateway:
    def __init__(self,c):
        self.c=c;self.active=set();self.protected=set();self.tail_until=0;self.lease_until=0;self.last_wake=-1e12;self.waking=None;self.session=None;self.background=None;self.draining=False;self.last_lease_state=None
    async def start(self,app):
        tls=ssl.create_default_context()
        if self.c.get('ca_pem'):tls.load_verify_locations(cadata=self.c['ca_pem'])
        self.session=ClientSession(connector=TCPConnector(ssl=tls,limit=64),cookie_jar=DummyCookieJar(),auto_decompress=False,trust_env=False,skip_auto_headers={'Accept-Encoding','Content-Type'},timeout=ClientTimeout(total=None,sock_connect=8,sock_read=120))
        if hasattr(self.session,'_retry_connection'):self.session._retry_connection=False
        self.background=asyncio.create_task(self.keep_awake())
    async def close(self,app):
        self.background.cancel()
        with contextlib.suppress(asyncio.CancelledError):await self.background
        if self.waking and not self.waking.done():
            self.waking.cancel()
            with contextlib.suppress(asyncio.CancelledError):await self.waking
        await self.session.close()
    def lease_result(self,ok):
        if ok!=self.last_lease_state:audit('blocker_state',confirmed=ok,active_requests=len(self.active));self.last_lease_state=ok
        return ok
    async def lease(self):
        try:
            async with self.session.post(self.c['manager_url']+'/api/clients/heartbeat',json=dict(client='Nextcloud Wake',mode='with_server',server_required=True,reason='Nextcloud: laufende Übertragung oder Nachlaufzeit',version='wake-'+VERSION),headers={'Authorization':'Bearer '+self.c['token']},allow_redirects=False,timeout=ClientTimeout(total=10)) as r:
                data=await r.json()
                if r.status!=200 or data.get('ok') is not True or data.get('sleep_blocker_enabled') is not True:return self.lease_result(False)
            self.lease_until=time.monotonic()+60;return self.lease_result(True)
        except Exception:return self.lease_result(False)
    async def keep_awake(self):
        while True:
            if self.protected or time.monotonic()<self.tail_until:
                ok=await self.lease()
                if not ok and self.lease_until and time.monotonic()>self.lease_until:
                    # Stop transfers before the manager's 180-second lease expires.
                    for task in list(self.protected):task.cancel()
            await asyncio.sleep(20)
    async def ready(self):
        try:
            async with self.session.get(self.c['backend'].rstrip('/')+self.c.get('health_path','/status.php'),headers={'Host':self.c['domain']},allow_redirects=False,server_hostname=self.c['domain'] if self.c['backend'].startswith('https:') else None,timeout=ClientTimeout(total=5)) as r:
                if r.status!=200:return 'not_ready'
                try:data=await r.json(content_type=None)
                except Exception:return 'not_ready'
                return 'ready' if data.get('installed') is True and not data.get('maintenance') and not data.get('needsDbUpgrade') else 'not_ready'
        except Exception:return 'unreachable'
    async def wake_wait(self):
        if await self.ready()=='ready':return True
        if not wake_enabled():
            audit('recovery_not_sent',cause='wake_disabled');return False
        if await self.ready()=='unreachable' and time.monotonic()-self.last_wake>=self.c['wake_cooldown']:
            if not wake_enabled():return False
            self.last_wake=time.monotonic()
            audit('recovery_requested',cause='backend_unreachable')
            try:
                # Legacy GET compatibility; never retry this potentially state-changing call.
                async with self.session.get(self.c['recovery_url'],allow_redirects=False,timeout=ClientTimeout(total=8)) as r:
                    audit('recovery_response',http_status=r.status)
                    if r.status not in (200,202,409):return False
            except Exception as exc:
                audit('recovery_transport_error',error_class=type(exc).__name__)
                # Older synchronous API may still be working after its HTTP timeout.
                pass
        else:audit('recovery_not_sent',cause='backend_responding_or_cooldown',cooldown_remaining=max(0,round(self.c['wake_cooldown']-(time.monotonic()-self.last_wake))))
        end=time.monotonic()+self.c['wake_wait']
        while time.monotonic()<end:
            if await self.ready()=='ready':
                audit('backend_ready');return True
            await asyncio.sleep(2)
        audit('wake_wait_expired');return False
    async def ensure_ready(self):
        if await self.ready()=='ready':return True
        if self.waking is None or self.waking.done():self.waking=asyncio.create_task(self.wake_wait())
        return await asyncio.shield(self.waking)
    async def handle(self,request):
        if request.path=='/__wake_health' and request.remote in ('127.0.0.1','::1'):
            return web.json_response(dict(ok=True,version=VERSION,active=len(self.active)))
        if request.path=='/__wake_drain':
            if request.remote not in ('127.0.0.1','::1') or request.method!='POST' or not secrets.compare_digest(request.headers.get('Authorization',''),'Bearer '+self.c['token']):raise web.HTTPForbidden()
            if self.active:raise web.HTTPConflict(text='Übertragungen aktiv.')
            self.draining=True
            return web.json_response(dict(ok=True))
        if self.draining:raise web.HTTPServiceUnavailable(headers={'Retry-After':'30'})
        if request.host.lower().split(':')[0]!=self.c['domain'].lower():raise web.HTTPMisdirectedRequest()
        if request.headers.get('Upgrade'):raise web.HTTPNotImplemented(text='WebSocket-Verbindungen werden von diesem Nextcloud-Wake-Gateway nicht unterstützt.')
        if len(self.active)>=32:raise web.HTTPServiceUnavailable(headers={'Retry-After':'30'})
        poll=background_poll(request)
        task=asyncio.current_task();self.active.add(task);response=None
        if not poll:self.protected.add(task)
        context_token=REQUEST_ID.set(secrets.token_hex(6));started=time.monotonic();outcome='error'
        audit('request_started',background_poll=poll,**request_meta(request,self.c['token']))
        try:
            if poll and await self.ready()!='ready':
                audit('poll_deferred',cause='backend_not_ready')
                raise web.HTTPServiceUnavailable(text='Nextcloud schläft. Hintergrundabfrage später wiederholen.',headers={'Retry-After':'300'})
            if not poll and not await self.ensure_ready():raise web.HTTPServiceUnavailable(text='Nextcloud noch nicht bereit. Später erneut versuchen.',headers={'Retry-After':'30'})
            if not poll and not await self.lease():raise web.HTTPServiceUnavailable(text='Schlafblocker nicht bestätigt. Manager-Zugang und Netzwerkmodul prüfen.',headers={'Retry-After':'30'})
            headers=clean_headers(request.headers)
            for key in ('Forwarded','X-Forwarded-For','X-Forwarded-Host','X-Forwarded-Proto','X-Real-IP'):
                headers.popall(key,None)
            # Only the loopback Apache frontend is trusted; it sanitizes incoming headers.
            peer=request.headers.get('X-Forwarded-For','').split(',')[0].strip()
            try:ipaddress.ip_address(peer)
            except ValueError:peer='127.0.0.1'
            headers['X-Forwarded-For']=peer;headers['X-Forwarded-Proto']='https';headers['X-Forwarded-Host']=self.c['domain'];headers['Host']=self.c['domain']
            target=URL(self.c['backend'].rstrip('/')+request.raw_path,encoded=True)
            data=request.content.iter_chunked(65536) if request.can_read_body else None
            async with self.session.request(request.method,target,headers=headers,data=data,allow_redirects=False,server_hostname=self.c['domain'] if self.c['backend'].startswith('https:') else None) as upstream:
                response=web.StreamResponse(status=upstream.status,reason=upstream.reason,headers=clean_headers(upstream.headers));await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(65536):await response.write(chunk)
                await response.write_eof();outcome=upstream.status;return response
        except web.HTTPException as exc:
            outcome=exc.status;raise
        except asyncio.CancelledError:
            outcome='cancelled'
            if request.transport:request.transport.close()
            raise
        except Exception:
            if response is not None and response.prepared:
                if request.transport:request.transport.close()
                raise
            raise web.HTTPBadGateway(text='Übertragung nicht abgeschlossen. Status prüfen; keine automatische Wiederholung.')
        finally:
            self.active.discard(task);self.protected.discard(task)
            if not poll:self.tail_until=time.monotonic()+self.c['hold_seconds']
            audit('request_finished',outcome=outcome,duration_seconds=round(time.monotonic()-started,1),hold_seconds=0 if poll else self.c['hold_seconds'],background_poll=poll,active_requests=len(self.active))
            REQUEST_ID.reset(context_token)
def create_app(conf):
    g=Gateway(conf);app=web.Application(client_max_size=0,handler_args={'auto_decompress':False});app['gateway']=g
    app.router.add_route('*','/{path:.*}',g.handle);app.on_startup.append(g.start);app.on_cleanup.append(g.close);return app
if __name__=='__main__':
    import os
    conf=json.loads((Path(os.environ['CREDENTIALS_DIRECTORY'])/'config.json').read_text())
    web.run_app(create_app(conf),host='127.0.0.1',port=conf['port'],access_log=None,print=None)
