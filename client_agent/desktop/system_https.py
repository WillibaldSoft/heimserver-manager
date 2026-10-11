"""Complete logical system snapshots, deduplicated HTTPS transport, bounded memory."""
try:
    from client_i18n import tr
except ModuleNotFoundError:
    from client_agent.desktop.client_i18n import tr
import json,subprocess,threading,zipfile,tempfile,time
import backup,core
from incremental import Stream

def cancel_helper(process):
    try:process.stdin.write(b'cancel\n');process.stdin.flush()
    except (OSError,ValueError):pass

def inventory_helper(argv):
    backup.check_cancel()
    with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as error:
        process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=output,stderr=error)
        job=backup.CURRENT_BACKUP;stop=lambda:cancel_helper(process)
        if job:job.callbacks.append(stop)
        try:
            if job and job.event.is_set():stop()
            process.wait();output.seek(0);error.seek(0);backup.check_cancel()
            return subprocess.CompletedProcess(argv,process.returncode,output.read(32*1024**2+1),error.read(8192))
        finally:
            if job:job.callbacks.remove(stop)
            process.stdin.close()

class VolumeProgress:
    def __init__(self,total,emit):
        self.total=max(1,total);self.emit=emit;self.done=0;self.last=-1
    def update(self,count):
        percent=min(99,int(100*(self.done+count)/self.total))
        if percent>self.last:
            self.last=percent
            self.emit(tr('Fortschritt nach Umfang (ca.): ')+str(percent)+' %')
    def component_done(self,size):self.done+=size
    def finish(self):self.emit(tr('Sicherung erfolgreich abgeschlossen: 100 %'))

def check_sources(options,confirm,progress):
    progress(tr('Lesbarkeit der Sicherungsquellen prüfen …'))
    prefix=['/usr/bin/python3'] if options['component']=='personal' else ['pkexec','/usr/bin/python3']
    result=inventory_helper(prefix+['/usr/lib/heimserver-manager-client/system_stream.py','preflight',json.dumps(dict(options,cancellable=True))])
    if result.returncode:raise core.Error(result.stderr.decode(errors='replace')[-3000:])
    if len(result.stdout)>32*1024**2:raise core.Error(tr('Prüfbericht zu groß. Sicherung nicht gestartet.'))
    blocked=json.loads(result.stdout)['blocked']
    if blocked:
        if confirm is None or not confirm(blocked):raise core.Error(tr('Ausschlüsse nicht bestätigt. Sicherung nicht gestartet.'))
        options=dict(options,approved_exclusions=[row['path'] for row in blocked])
        for row in blocked:progress(tr('Für diesen Lauf ausgeschlossen: ')+row['path'])
    return options

def prepare_inventory(progress,options):
    options=dict(options,cancellable=True,estimate_size=True)
    component=options['component']
    helper='/usr/lib/heimserver-manager-client/system_stream.py';choice=json.dumps(options)
    prefix=['/usr/bin/python3'] if component=='personal' else ['pkexec','/usr/bin/python3']
    progress(tr('Sicherungsumfang ermitteln …'))
    progress(tr('Persönliches Inventar erfassen …') if component=='personal' else tr('System- und Softwareinventar erfassen (Administratorfreigabe) …'))
    result=inventory_helper(prefix+[helper,'inventory',choice])
    if len(result.stdout)>32*1024**2:raise core.Error(tr('Inventar zu groß.'))
    if result.returncode:raise core.Error(tr('Inventar konnte nicht erfasst werden: ')+result.stderr.decode(errors='replace')[-3000:])
    inventory=json.loads(result.stdout)
    return inventory


def create_component(progress,options,call,name,system_id="",inventory=None,on_bytes=None,confirm_interrupted=None):
    component=options['component']
    options=dict(options or {},cancellable=True);backup.check_cancel();cfg=core.validate(core.load())
    if backup.ACCOUNT and not backup.ACCOUNT[2].get('backup'):raise core.Error(tr('Nur Lesen: neue Systemsicherung nicht freigegeben.'))
    if not cfg['SERVER_URL'].startswith('https://'):raise core.Error(tr('Systemsicherung benötigt HTTPS mit gültigem Zertifikat.'))
    capabilities=backup.call('list').get('capabilities',[])
    if 'system-cas-v1' not in capabilities:raise core.Error(tr('Manager benötigt die Erweiterung für inkrementelle Systemsicherungen.'))
    helper='/usr/lib/heimserver-manager-client/system_stream.py';choice=json.dumps(options)
    prefix=['/usr/bin/python3'] if component=='personal' else ['pkexec','/usr/bin/python3']
    if inventory is None:inventory=prepare_inventory(progress,options)
    progress(tr('Enthaltene Datenträger: ')+', '.join(r['target'] for r in inventory.get('selected_mounts',[])))
    progress(tr('Ausgeschlossene Datenträger: ')+', '.join(r['target'] for r in inventory.get('excluded_mounts',[])))
    backup.check_cancel()
    if 'retire-incomplete-v1' in capabilities:
        for row in call('cas-pending')['uploads']:
            if row['idle_seconds']<600:raise core.Error(tr('Unvollständiger Auftrag war kürzlich aktiv. Zehn Minuten ohne Aktivität abwarten; laufende Sicherung nicht ersetzen.'))
            if confirm_interrupted is None or not confirm_interrupted(row):raise core.Error(tr('Neustart nicht bestätigt. Vorhandener Auftrag bleibt erhalten.'))
            call('cas-retire',dict(id=row['id'],revision=row['revision'],confirmed=True))
            progress(tr('Unvollständiger Auftrag zurückgelegt; Datenblöcke bleiben erhalten.'))
    sid=call('cas-begin',dict(name=name,system_id=system_id,personal_user=inventory.get('personal_user',''),personal_home=inventory.get('personal_home','')))['id']
    process=subprocess.Popen(prefix+[helper,'backup',choice],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    job=backup.CURRENT_BACKUP;stop=lambda:cancel_helper(process)
    if job:
        job.callbacks.append(stop)
        if job.event.is_set():stop()
    unwatch=backup.watch_upload(call,sid)
    errors=[]
    def drain():
        for line in iter(process.stderr.readline,b''):
            errors.append(line.decode(errors='replace').strip());del errors[:-20]
    reader=threading.Thread(target=drain,daemon=True);reader.start();stream=Stream(sid,progress,call=call,check=backup.check_cancel,on_bytes=on_bytes,async_finish='async-finalize-v1' in capabilities)
    try:
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_STORED,allowZip64=True) as archive:
            entry=zipfile.ZipInfo('files/system.tar',(1980,1,1,0,0,0))
            with archive.open(entry,'w',force_zip64=True) as out:
                for chunk in iter(lambda:process.stdout.read(backup.CHUNK),b''):out.write(chunk)
            code=process.wait();reader.join()
            if code:raise core.Error(tr('Systemdateien geändert oder nicht lesbar; Sicherung nicht freigegeben. ')+ '\n'.join(errors))
            for name,value in [('files/ANLEITUNG.txt',tr('Getrennte PC-Sicherung: Systemstand ohne normale Benutzer-Homes; persönliche Stände enthalten nur das eigene Home. System und persönliche Stände getrennt wiederherstellen. Partitionierung und Bootloader bleiben manuell.')),('files/system-inventory.json',json.dumps(inventory,sort_keys=True)),('hsm-backup.json',json.dumps(dict(format='client-zip-v1',scope='linux-system-tar-v2',component=component,system_id=system_id)))]:
                archive.writestr(zipfile.ZipInfo(name,(1980,1,1,0,0,0)),value)
        progress(tr('Sicherungsstand am Server prüfen …'));stream.finish()
        failed=sum(1 for x in inventory['commands'].values() if x['status']=='failed')+sum(1 for user in inventory.get('users',{}).values() for x in user.values() if x['status']=='failed')
        return sid,tr('Systemstand abgeschlossen. Neu: ')+str(stream.sent//1024**2)+tr(' MiB; wiederverwendet: ')+str(stream.reused//1024**2)+tr(' MiB. Inventarfehler: ')+str(failed)+tr(' (Details in system-inventory.json).')
    except Exception:
        if job and job.event.is_set():
            stream.buffer.clear()
            try:message=backup.abort_upload(call,sid)
            except Exception as exc:message=tr('Abbruch angefordert; Server-Aufräumen nicht bestätigt. Übertragung später verwerfen. ')+str(exc)
            raise backup.Cancelled(message) from None
        raise
    finally:
        unwatch()
        if job:job.callbacks.remove(stop)
        process.stdin.close()
        stream.buffer.clear();process.stdout.close()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            except PermissionError:pass # privileged helper exits when its output pipe closes
        reader.join(timeout=5)


@backup.cancellable
def create(progress=lambda text:None,options=None,confirm_exclusions=None,confirm_interrupted=None):
    options=dict(options or {})
    if options.get('source_root','/')!='/':
        raise core.Error(tr('Getrennte PC-Sicherung vom laufenden Client starten. Offline-Quellen über den USB-Assistenten sichern.'))
    if 'shared-pc-v1' not in backup.call('list').get('capabilities',[]):
        raise core.Error(tr('Manager benötigt die Erweiterung für gemeinsame PC-Sicherungen.'))
    status=backup.call('pc-status');system=status.get('system');messages=[]
    refresh=bool(options.pop('refresh_system',False))
    if system and not refresh and (options.get('extra_mounts') or options.get('network_profiles')):
        raise core.Error(tr('Zusätzliche Datenträger oder Netzwerkprofile gewählt: gemeinsamen PC-Systemstand ausdrücklich neu sichern.'))
    if status.get('personal'):progress(tr('Vorhandene persönliche Sicherung prüfen: ')+status['personal']['created'])
    if refresh and not status['system_admin']:
        raise core.Error(tr('Gemeinsamen Systemstand aktualisieren: als Administrator oder mit Systemsicherungsfreigabe anmelden.'))
    need_system=(not system or refresh) and status['system_admin']
    system_options=check_sources(dict(options,component='system'),confirm_exclusions,progress) if need_system else None
    personal_options=check_sources(dict(source_root='/',component='personal'),confirm_exclusions,progress)
    system_inventory=prepare_inventory(progress,system_options) if need_system else None
    personal_inventory=prepare_inventory(progress,personal_options)
    total=sum(i['archive_estimate']['bytes'] for i in (system_inventory,personal_inventory) if i is not None)
    progress(tr('Geschätzter Sicherungsumfang: ')+str(total//1024**2)+' MiB')
    volume=VolumeProgress(total,progress);volume.update(0)
    if not system or refresh:
        if status['system_admin']:
            pc=status['device_id']
            def system_call(action,data=None,query='',binary=False):
                return backup.call(action,data,query+'&pc='+pc,binary)
            progress(tr('Gemeinsamen Systemstand dieses PCs sichern …'))
            sid,message=create_component(progress,system_options,system_call,tr('Gemeinsamer PC-Systemstand'),inventory=system_inventory,on_bytes=volume.update,confirm_interrupted=confirm_interrupted)
            volume.component_done(system_inventory['archive_estimate']['bytes'])
            messages.append(message);system=dict(id=sid)
        else:
            messages.append(tr('Noch kein gemeinsamer Systemstand vorhanden. Ein Administrator oder freigegebener Benutzer muss ihn anlegen; persönliche Daten werden trotzdem gesichert.'))
    else:
        progress(tr('Vorhandenen PC-Systemstand wiederverwenden: ')+system['created'])
    if backup.CURRENT_BACKUP and backup.CURRENT_BACKUP.event.is_set():
        return '\n'.join(messages+[tr('Abbruch angefordert; vorhandener Systemstand bleibt erhalten. Persönliche Übertragung nicht gestartet.')])
    def personal_call(action,data=None,query='',binary=False):
        return backup.call(action,data,query+'&personal=1',binary)
    progress(tr('Nur persönliche Daten dieses Benutzers sichern; unveränderte Blöcke wiederverwenden …'))
    _,message=create_component(progress,personal_options,personal_call,tr('Persönliche Daten'),system['id'] if system else '',inventory=personal_inventory,on_bytes=volume.update,confirm_interrupted=confirm_interrupted)
    volume.finish()
    return '\n'.join(messages+[message,tr('PC-System und persönliche Daten sind getrennt gespeichert. Andere Benutzer-Homes wurden nicht gesichert.')])
