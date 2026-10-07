#!/usr/bin/env python3
"""Streaming Nextcloud wake gateway behind a local TLS reverse proxy."""
import asyncio,contextlib,json,ssl,time,ipaddress,secrets
from pathlib import Path
from urllib.parse import urlsplit
from aiohttp import web,ClientSession,ClientTimeout,DummyCookieJar,TCPConnector
from multidict import CIMultiDict
from yarl import URL
VERSION='1.0'
HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade'}
def clean_headers(headers):
    blocked=HOP|{v.strip().lower() for v in headers.get('Connection','').split(',')}
    return CIMultiDict((k,v) for k,v in headers.items() if k.lower() not in blocked)
class Gateway:
    def __init__(self,c):
        self.c=c;self.active=set();self.tail_until=0;self.lease_until=0;self.last_wake=-1e12;self.waking=None;self.session=None;self.background=None;self.draining=False
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
    async def lease(self):
        try:
            async with self.session.post(self.c['manager_url']+'/api/clients/heartbeat',json=dict(client='Nextcloud Wake',mode='with_server',server_required=True,reason='Nextcloud: laufende Übertragung oder Nachlaufzeit',version='wake-'+VERSION),headers={'Authorization':'Bearer '+self.c['token']},allow_redirects=False,timeout=ClientTimeout(total=10)) as r:
                data=await r.json()
                if r.status!=200 or data.get('ok') is not True or data.get('sleep_blocker_enabled') is not True:return False
            self.lease_until=time.monotonic()+60;return True
        except Exception:return False
    async def keep_awake(self):
        while True:
            if self.active or time.monotonic()<self.tail_until:
                ok=await self.lease()
                if not ok and self.lease_until and time.monotonic()>self.lease_until:
                    # Stop transfers before the manager's 180-second lease expires.
                    for task in list(self.active):task.cancel()
            await asyncio.sleep(20)
    async def ready(self):
        try:
            async with self.session.get(self.c['backend'].rstrip('/')+'/status.php',headers={'Host':self.c['domain']},allow_redirects=False,server_hostname=self.c['domain'] if self.c['backend'].startswith('https:') else None,timeout=ClientTimeout(total=5)) as r:
                if r.status!=200:return 'not_ready'
                try:data=await r.json(content_type=None)
                except Exception:return 'not_ready'
                return 'ready' if data.get('installed') is True and not data.get('maintenance') and not data.get('needsDbUpgrade') else 'not_ready'
        except Exception:return 'unreachable'
    async def wake_wait(self):
        if await self.ready()=='ready':return True
        if await self.ready()=='unreachable' and time.monotonic()-self.last_wake>=self.c['wake_cooldown']:
            self.last_wake=time.monotonic()
            try:
                # Legacy GET compatibility; never retry this potentially state-changing call.
                async with self.session.get(self.c['recovery_url'],allow_redirects=False,timeout=ClientTimeout(total=8)) as r:
                    if r.status not in (200,202,409):return False
            except Exception:
                # Older synchronous API may still be working after its HTTP timeout.
                pass
        end=time.monotonic()+self.c['wake_wait']
        while time.monotonic()<end:
            if await self.ready()=='ready':return True
            await asyncio.sleep(2)
        return False
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
        task=asyncio.current_task();self.active.add(task);response=None
        try:
            if not await self.ensure_ready():raise web.HTTPServiceUnavailable(text='Nextcloud noch nicht bereit. Später erneut versuchen.',headers={'Retry-After':'30'})
            if not await self.lease():raise web.HTTPServiceUnavailable(text='Schlafblocker nicht bestätigt. Manager-Zugang und Netzwerkmodul prüfen.',headers={'Retry-After':'30'})
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
                await response.write_eof();return response
        except web.HTTPException:raise
        except asyncio.CancelledError:
            if request.transport:request.transport.close()
            raise
        except Exception:
            if response is not None and response.prepared:
                if request.transport:request.transport.close()
                raise
            raise web.HTTPBadGateway(text='Übertragung nicht abgeschlossen. Status prüfen; keine automatische Wiederholung.')
        finally:
            self.active.discard(task);self.tail_until=time.monotonic()+self.c['hold_seconds']
def create_app(conf):
    g=Gateway(conf);app=web.Application(client_max_size=0,handler_args={'auto_decompress':False});app['gateway']=g
    app.router.add_route('*','/{path:.*}',g.handle);app.on_startup.append(g.start);app.on_cleanup.append(g.close);return app
if __name__=='__main__':
    import os
    conf=json.loads((Path(os.environ['CREDENTIALS_DIRECTORY'])/'config.json').read_text())
    web.run_app(create_app(conf),host='127.0.0.1',port=conf['port'],access_log=None,print=None)
