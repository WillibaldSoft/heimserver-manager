#!/usr/bin/env python3
"""Optional IPMI recovery API for a separate, continuously available host."""
import ipaddress,json,os,re,subprocess,threading,time
from pathlib import Path
from flask import Flask,jsonify,request
VERSION='2.2'

def validate(conf):
    for key in ('server_ip','ipmi_host','listen_host'):
        value=ipaddress.ip_address(conf[key])
        if value.version!=4 or value.is_unspecified or value.is_multicast:raise ValueError('Konkrete IPv4-Adresse erforderlich: '+key)
    port=int(conf['port'])
    if not 1024<=port<=65535:raise ValueError('Port muss zwischen 1024 und 65535 liegen.')
    if not str(conf.get('ipmi_user','')).strip() or len(conf['ipmi_user'])>64:raise ValueError('IPMI-Benutzer fehlt oder ist zu lang.')
    if not isinstance(conf.get('allow_reset'),bool):raise ValueError('Reset-Freigabe muss ausdrücklich festgelegt werden.')
    for key in ('wait_seconds','soft_wait_seconds','reset_wait_seconds'):
        if not 30<=int(conf.get(key,conf['wait_seconds']))<=1800:raise ValueError('Wartezeit: 30 bis 1800 Sekunden.')
    if type(conf.get('allow_soft',False)) is not bool:raise ValueError('Soft-Freigabe muss ausdrücklich festgelegt werden.')
    nets=[ipaddress.ip_network(v,strict=False) for v in conf['allowed_clients']]
    if not nets or any(n.version!=4 or n.prefixlen==0 for n in nets):raise ValueError('Erlaubte IPv4-Clients/Netze angeben; Freigabe für alle Adressen ist nicht zulässig.')
    return nets

class Controller:
    def __init__(self,conf,password_file,state_file):
        self.conf=conf;validate(conf);self.password_file=str(password_file);self.state_file=Path(state_file)
        self.lock=threading.RLock();self.command_lock=threading.Lock();self.cache=None;self.cache_time=0
        self.data=dict(recover_active=False,phase='idle',last_action=None,last_error=None,recover_count=0,reset_count=0)
        if self.state_file.exists():
            previous=json.loads(self.state_file.read_text())
            for key in self.data:
                if key in previous:self.data[key]=previous[key]
            if self.data['recover_active']:self.data.update(recover_active=False,phase='interrupted',last_error='Dienst während einer Aktion beendet; Zustand prüfen. Keine Aktion automatisch fortgesetzt.')
        self.persist()
    def persist(self):
        self.state_file.parent.mkdir(parents=True,exist_ok=True)
        temp=self.state_file.with_suffix('.tmp');temp.write_text(json.dumps(self.data,ensure_ascii=False));temp.chmod(0o600);os.replace(temp,self.state_file)
    def update(self,**values):
        with self.lock:self.data.update(values);self.persist()
    def ipmi(self,action):
        if action not in ('status','on','soft','reset'):raise ValueError('Unzulässige IPMI-Aktion.')
        # Password is read from a systemd credential, never from process arguments or logs.
        with self.command_lock:
            try:
                result=subprocess.run(['ipmitool','-I','lanplus','-H',self.conf['ipmi_host'],'-U',self.conf['ipmi_user'],'-f',self.password_file,'chassis','power',action],capture_output=True,text=True,timeout=12)
            except (OSError,subprocess.TimeoutExpired):raise RuntimeError('IPMI-Dienst nicht erreichbar oder Zeitüberschreitung.') from None
        if result.returncode:raise RuntimeError('IPMI-Befehl fehlgeschlagen. Netzwerk, Rechte und Zugangsdaten prüfen.')
        return result.stdout.strip()
    def ping(self):
        try:return subprocess.run(['ping','-n','-c','1','-W','2',self.conf['server_ip']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0
        except (OSError,subprocess.TimeoutExpired):return False
    def power(self):
        raw=self.ipmi('status').lower()
        if re.search(r'\bis off\b',raw):return 'off'
        if re.search(r'\bis on\b',raw):return 'on'
        raise RuntimeError('Unbekannte IPMI-Statusantwort; keine Steueraktion ausgeführt.')
    def snapshot(self):
        # Short cache avoids repeated IPMI queries when several consumers poll together.
        if not self.cache or time.monotonic()-self.cache_time>5:
            try:p=self.power();reachable=self.ping();error=None
            except RuntimeError as exc:p='unknown';reachable=False;error=str(exc)
            self.cache=(p,reachable,error);self.cache_time=time.monotonic()
        p,reachable,error=self.cache
        state='off' if p=='off' else 'running' if p=='on' and reachable else 'on_not_reachable' if p=='on' else 'unknown'
        with self.lock:data=dict(self.data)
        text='Startet' if data['recover_active'] else {'off':'Aus','running':'Läuft','on_not_reachable':'Eingeschaltet, nicht erreichbar','unknown':'Unbekannt'}[state]
        return dict(data,ok=error is None,version=VERSION,server=self.conf.get('server_name','Debian Server'),state=state,state_text=text,power=p,reachable=reachable,ipmi_status='Chassis Power is '+p,last_error=error or data['last_error'])
    def wait_ping(self,seconds=None):
        deadline=time.monotonic()+int(seconds or self.conf['wait_seconds'])
        while time.monotonic()<deadline:
            if self.ping():return True
            time.sleep(5)
        return False
    def perform(self,action):
        error=None;result='success'
        try:
            power=self.power()
            if power=='off':self.update(phase='power_on');self.ipmi('on')
            if action=='recover':
                wait=self.conf['wait_seconds']
                if power=='on' and not self.ping() and self.conf.get('allow_soft',False):
                    # Preserve explicitly chosen legacy behavior; this is not a sleep detector.
                    if self.power()=='on' and not self.ping():
                        self.update(phase='soft_power');self.ipmi('soft')
                        wait=self.conf.get('soft_wait_seconds',wait)
                self.update(phase='waiting_for_server')
                if not self.wait_ping(wait):
                    if not self.conf['allow_reset']:raise RuntimeError('Server antwortet nicht. Automatischer Reset ist deaktiviert; Zustand manuell prüfen.')
                    # Recheck after waiting: never reset a machine that now responds or is off.
                    if not self.ping():
                        if self.power()!='on':raise RuntimeError('Server ist nicht eingeschaltet; kein Reset ausgeführt.')
                        self.update(phase='reset',reset_count=self.data['reset_count']+1);self.ipmi('reset')
                        if not self.wait_ping(self.conf.get('reset_wait_seconds',self.conf['wait_seconds'])):raise RuntimeError('Server antwortet auch nach dem einmaligen Reset nicht.')
        except Exception as exc:error=str(exc) if isinstance(exc,RuntimeError) else 'Interner Fehler; Dienstprotokoll und Konfiguration prüfen.';result='failed'
        finally:
            self.cache=None
            self.update(recover_active=False,phase='failed' if error else 'idle',last_error=error,last_action={'action':action,'time':time.strftime('%Y-%m-%d %H:%M:%S'),'result':result})
    def start(self,action):
        with self.lock:
            if self.data['recover_active']:return False
            self.update(recover_active=True,phase='starting',last_error=None,recover_count=self.data['recover_count']+(action=='recover'))
            try:threading.Thread(target=self.perform,args=(action,),daemon=True,name='ipmi-action').start()
            except Exception:self.update(recover_active=False,phase='failed',last_error='Auftrag konnte nicht gestartet werden.');raise
        return True

def create_app(controller):
    app=Flask(__name__);networks=validate(controller.conf)
    @app.before_request
    def access():
        try:peer=ipaddress.ip_address(request.remote_addr)
        except ValueError:return jsonify(ok=False,error='Zugriff verweigert'),403
        if not any(peer in net for net in networks):return jsonify(ok=False,error='Client nicht freigegeben'),403
    @app.get('/status')
    @app.get('/summary')
    def status():
        data=controller.snapshot();return jsonify(data),200 if data['ok'] else 503
    @app.get('/health')
    def health():
        data=controller.snapshot();return jsonify(healthy=data['ok'],state=data['state'],version=VERSION),200 if data['ok'] else 503
    @app.get('/version')
    def version():return jsonify(version=VERSION)
    @app.route('/poweron',methods=['GET','POST'])
    @app.route('/recover',methods=['GET','POST'])
    def action():
        name='recover' if request.path=='/recover' else 'poweron'
        if not controller.start(name):return jsonify(ok=False,message='Aktion läuft bereits; /status prüfen.'),409
        return jsonify(ok=True,accepted=True,action=name,message='Auftrag läuft im Hintergrund; /status prüfen.'),202
    return app

if __name__=='__main__':
    from waitress import serve
    credentials=Path(os.environ['CREDENTIALS_DIRECTORY']);conf=json.loads((credentials/'config.json').read_text())
    controller=Controller(conf,credentials/'ipmi-password',Path(os.environ.get('STATE_DIRECTORY','/var/lib/server-manager-power-api'))/'status.json')
    serve(create_app(controller),host=conf['listen_host'],port=int(conf['port']),threads=4)
