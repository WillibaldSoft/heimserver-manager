"""Bounded-memory incremental transmission. No local system archive."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import hashlib,io,time
import backup,core
class Stream(io.RawIOBase):
    def __init__(self,sid,progress):
        self.sid=sid;self.progress=progress;self.buffer=bytearray();self.offset=0;self.hash=hashlib.sha256();self.refs=[];self.sent=0;self.reused=0
    def writable(self):return True
    def seekable(self):return False
    def tell(self):return self.offset+len(self.buffer)
    def write(self,data):
        n=len(data);self.hash.update(data);view=memoryview(data)
        while view:
            count=min(backup.CHUNK-len(self.buffer),len(view));self.buffer.extend(view[:count]);view=view[count:]
            if len(self.buffer)==backup.CHUNK:self.flush()
        return n
    def flush(self):
        if not self.buffer:return
        data=bytes(self.buffer);key=hashlib.sha256(data).hexdigest()
        found=backup.call('block-has',query='&hash='+key+'&id='+self.sid)
        if found.get('present'):
            if found.get('bytes')!=len(data):raise core.Error(tr('Blockgröße stimmt nicht.'))
            self.reused+=len(data)
        else:
            backup.call('block-put',data,'&id='+self.sid+'&hash='+key);self.sent+=len(data)
        self.refs.append(dict(sha256=key,bytes=len(data)));self.offset+=len(data);self.buffer.clear()
        if len(self.refs)>262144:raise core.Error(tr('Maximale Anzahl Sicherungsblöcke erreicht.'))
        self.progress(tr('Gelesen: ')+str(self.offset//1024**2)+tr(' MiB · neu übertragen: ')+str(self.sent//1024**2)+tr(' MiB · wiederverwendet: ')+str(self.reused//1024**2)+' MiB')
    def finish(self):
        self.flush();sha=self.hash.hexdigest()
        try:return backup.call('cas-finish',dict(chunks=self.refs,bytes=self.offset,sha256=sha),'&id='+self.sid)
        except (core.Error,OSError) as original:
            if isinstance(original,core.Error) and not any(code in str(original) for code in ('HTTP 502','HTTP 503','HTTP 504')):raise
            # Never duplicate a potentially completed finalization.
            for _ in range(60):
                try:
                    for item in backup.call('list')['backups']:
                        if item['id']==self.sid and item['sha256']==sha:return item
                except (core.Error,OSError):pass
                time.sleep(3)
            raise original
