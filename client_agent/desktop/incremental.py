"""Bounded-memory incremental transmission. No local system archive."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,io,time,re
# Content anchors are searched in C; SHA-256 still verifies every stored block.
ANCHOR=re.compile(b"\x13\x37[\x00-\x1f]")
MIN_BLOCK=1024*1024
import backup,core
class Stream(io.RawIOBase):
    def __init__(self,sid,progress,call=None,check=None,on_bytes=None,async_finish=False,content_defined=False):
        self.content_defined=content_defined
        self.async_finish=async_finish
        self.on_bytes=on_bytes or (lambda count:None)
        self.check=check or (lambda:None)
        self.call=call or (lambda *args,**kwargs:backup.call(*args,**kwargs))
        self.sid=sid;self.progress=progress;self.buffer=bytearray();self.offset=0;self.hash=hashlib.sha256();self.refs=[];self.sent=0;self.reused=0
    def writable(self):return True
    def seekable(self):return False
    def tell(self):return self.offset+len(self.buffer)
    def write(self,data):
        self.check()
        n=len(data);self.hash.update(data);view=memoryview(data)
        while view:
            count=min(backup.CHUNK-len(self.buffer),len(view));self.buffer.extend(view[:count]);view=view[count:]
            if self.content_defined:
                while len(self.buffer)>=MIN_BLOCK:
                    match=ANCHOR.search(self.buffer,MIN_BLOCK-3)
                    if match:self.flush(match.end())
                    elif len(self.buffer)==backup.CHUNK:self.flush()
                    else:break
            elif len(self.buffer)==backup.CHUNK:self.flush()
        return n
    def flush(self,count=None):
        if not self.buffer:return
        self.check()
        count=len(self.buffer) if count is None else count
        data=bytes(self.buffer[:count]);key=hashlib.sha256(data).hexdigest()
        found=self.call('block-has',query='&hash='+key+'&id='+self.sid)
        if found.get('present'):
            if found.get('bytes')!=len(data):raise core.Error(tr('Blockgröße stimmt nicht.'))
            self.reused+=len(data)
        else:
            self.call('block-put',data,'&id='+self.sid+'&hash='+key);self.sent+=len(data)
        self.refs.append(dict(sha256=key,bytes=len(data)));self.offset+=len(data);del self.buffer[:count]
        if len(self.refs)>262144:raise core.Error(tr('Maximale Anzahl Sicherungsblöcke erreicht.'))
        self.on_bytes(self.offset)
        self.progress(tr('Gelesen: ')+str(self.offset//1024**2)+tr(' MiB · neu übertragen: ')+str(self.sent//1024**2)+tr(' MiB · wiederverwendet: ')+str(self.reused//1024**2)+' MiB')
    def finish(self):
        self.check();self.flush();sha=self.hash.hexdigest()
        if self.async_finish:return self.finish_background(sha)
        try:return self.call('cas-finish',dict(chunks=self.refs,bytes=self.offset,sha256=sha),'&id='+self.sid)
        except (core.Error,OSError) as original:
            if isinstance(original,core.Error) and not any(code in str(original) for code in ('HTTP 502','HTTP 503','HTTP 504')):raise
            # Never duplicate a potentially completed finalization.
            for _ in range(60):
                try:
                    for item in self.call('list')['backups']:
                        if item['id']==self.sid and item['sha256']==sha:return item
                except (core.Error,OSError):pass
                time.sleep(3)
            raise original

    def finish_background(self,sha):
        payload=dict(chunks=self.refs,bytes=self.offset,sha256=sha)
        try:self.call('cas-finalize',payload,'&id='+self.sid)
        except (OSError,core.Error) as exc:
            if isinstance(exc,core.Error) and not any(code in str(exc) for code in ('HTTP 502','HTTP 503','HTTP 504')):raise
            # The request may have been accepted: poll, never blindly resubmit.
        failures=0;last=-1
        while True:
            self.check()
            try:result=self.call('cas-status',query='&id='+self.sid)
            except (OSError,core.Error) as exc:
                if isinstance(exc,core.Error) and not any(code in str(exc) for code in ('HTTP 502','HTTP 503','HTTP 504')):raise
                failures+=1
                if failures>=12:raise core.Error(tr('Serverprüfung nicht erreichbar. Sicherungsdaten nicht verwerfen; Status später prüfen.')) from exc
                self.progress(tr('Verbindung zur Serverprüfung unterbrochen; erneut prüfen …'));time.sleep(5);continue
            failures=0
            if result.get('state')=='complete':
                if result.get('id')!=self.sid or result.get('bytes')!=self.offset or result.get('sha256')!=sha:raise core.Error(tr('Abschlussdaten stimmen nicht mit der Sicherung überein.'))
                return result
            if result.get('state') not in ('queued','verifying'):
                raise core.Error(tr('Serverprüfung nicht abgeschlossen. Daten bleiben erhalten: ')+str(result.get('error') or result.get('state')))
            percent=min(99,int(100*result.get('verified_bytes',0)/max(1,self.offset)))
            if percent!=last:
                self.progress(tr('Serverprüfung: ')+str(percent)+tr(' % · Daten bereits übertragen.'));last=percent
            time.sleep(2)
