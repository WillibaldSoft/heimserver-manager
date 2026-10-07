"""DynDNS v4: standalone stdlib update engine, adapted from Multi DynDNS v3.9.
Configuration is data, never shell code. No credentials in argv or status output.
"""
import os
import argparse,base64,contextlib,copy,fcntl,hashlib,ipaddress,json,os,re,shlex,socket,subprocess,tempfile,time
from pathlib import Path
from urllib import request,error,parse

CONFIG=Path(os.environ.get('SERVER_MANAGER_CONFIG', '/etc/server-manager')) / 'dyndns.json'
STATE=Path(os.path.join(os.environ.get('SERVER_MANAGER_STATE', '/var/lib/server-manager'), 'dyndns'))
LEGACY=Path('/etc/multi-dyndns-v3')
UNITS=Path('/etc/systemd/system')
UNIT='multi-dyndns-update'
MODES={'ipv4':'Nur IPv4','ipv6':'Nur IPv6','both':'IPv4 und IPv6 erforderlich','ipv4_required_ipv6_optional':'IPv4, IPv6 wenn verfügbar','ipv6_required_ipv4_optional':'IPv6, IPv4 wenn verfügbar'}
STRATEGIES={'ip_change_only':'Nur bei IP-Änderung','ip_or_dns_change':'Bei IP- oder DNS-Abweichung','always':'Bei jedem Intervall'}
PRESETS={
 'ddnss':('DDNSS · API-Key','none','https://ddnss.de/upd.php?key={secret}&host={host}&ip={ipv4}&ip6={ipv6}'),
 'ddnss_password':('DDNSS · Benutzer/Passwort','none','https://www.ddnss.de/upd.php?user={user}&pwd={secret}&host={host}&ip={ipv4}&ip6={ipv6}'),
 'inwx':('INWX','basic','https://dyndns.inwx.com/nic/update?hostname={host}&myip={ipv4}&myipv6={ipv6}'),
 'dynv6':('dynv6','none','https://dynv6.com/api/update?hostname={host}&token={secret}&ipv4={ipv4}&ipv6={ipv6}'),
 'duckdns':('DuckDNS','none','https://www.duckdns.org/update?domains={host}&token={secret}&ip={ipv4}&ipv6={ipv6}'),
 'custom':('Eigene HTTPS-Update-URL','none',''),
}
DEFAULT={'version':4,'interface':'','interval':15,'strategy':'ip_or_dns_change','lock_hours':6,'providers':[]}
class Problem(ValueError):pass
class DNSProblem(Problem):pass

def command(args,timeout=15):
    try:return subprocess.run(args,text=True,capture_output=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):raise Problem('Systembefehl nicht verfügbar oder Zeitlimit erreicht: '+args[0]) from None

def atomic(path,data,mode=0o600):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'w') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def read_json(path,default):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return copy.deepcopy(default)
    except (OSError,ValueError):raise Problem('Gespeicherte DynDNS-Daten nicht lesbar; bitte Sicherung prüfen.') from None

def load():return read_json(CONFIG,DEFAULT)
def revision():return hashlib.sha256(CONFIG.read_bytes() if CONFIG.exists() else b'').hexdigest()
def save(cfg):atomic(CONFIG,json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')

@contextlib.contextmanager
def lock():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with open(STATE/'operation.lock','a') as stream:
        os.chmod(stream.name,0o600)
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Problem('Eine DynDNS-Aktion läuft bereits. Bitte warten.') from None
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)

def busy():
    if not (STATE/'operation.lock').exists():return False
    try:
        with lock():return False
    except Problem:return True

def hostname(value):
    value=value.strip().rstrip('.').lower()
    if len(value)>253 or '.' not in value or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',p) for p in value.split('.')):raise Problem('Bitte einen vollständigen DNS-Hostnamen eingeben.')
    return value

def endpoint(url):
    try:parts=parse.urlsplit(url);port=parts.port
    except ValueError:raise Problem('Ungültige Update-URL.') from None
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.fragment or port not in (None,443):raise Problem('Update-URL muss HTTPS ohne eingebettete Anmeldung und mit Standardport verwenden.')
    hostname(parts.hostname)
    if any(ch in parts.netloc for ch in '{}') or any(ord(ch)<32 for ch in url):raise Problem('Unzulässige Zeichen in der Update-URL.')
    return parts

def validate_provider(data,old=None):
    old=old or {};kind=data.get('type','ddnss');preset=PRESETS.get(kind)
    if not preset and not old:raise Problem('Unbekannte Anbietervorlage.')
    item={k:str(data.get(k,'')) for k in ('name','host','username','mode','auth','url','success')}
    item['name']=item['name'].strip()
    if not item['name'] or len(item['name'])>100:raise Problem('Bitte einen Namen bis 100 Zeichen eingeben.')
    item['host']=hostname(item['host'])
    if item['mode'] not in MODES:raise Problem('Bitte einen IP-Modus wählen.')
    if item['auth'] not in ('none','basic','bearer'):raise Problem('Unbekannte Anmeldeart.')
    item.update(type=kind,id=old.get('id') or os.urandom(12).hex(),enabled=data.get('enabled') in (True,'1','yes'),secret=str(data.get('secret') or old.get('secret','')))
    if not item['secret']:raise Problem('Zugangsschlüssel oder Passwort fehlt.')
    if item['auth']=='basic' and not item['username']:raise Problem('Basic Auth benötigt einen Benutzernamen.')
    if any(ord(c)<32 for key in ('name','username','secret') for c in item[key]):raise Problem('Steuerzeichen sind nicht zulässig.')
    if len(item['secret'])>4096 or len(item['url'])>4096:raise Problem('Eingabe zu lang.')
    item['url']=item['url'].strip() or (preset[2] if preset else '')
    endpoint(item['url'])
    valid={'host','user','secret','pass','password','token','ipv4','ip4','ipv6','ip6'}
    if set(re.findall(r'\{([^{}]+)\}',item['url']))-valid or re.sub(r'\{(?:'+ '|'.join(valid)+r')\}','',item['url']).count('{') or '}' in re.sub(r'\{[^{}]+\}','',item['url']):raise Problem('Unbekannte URL-Platzhalter.')
    has4=bool(re.search(r'\{(?:ipv4|ip4)\}',item['url']));has6=bool(re.search(r'\{(?:ipv6|ip6)\}',item['url']))
    if item['mode']!='ipv6' and not has4:raise Problem('IPv4-Modus benötigt {ipv4} in der URL.')
    if item['mode']!='ipv4' and not has6:raise Problem('IPv6-Modus benötigt {ipv6} in der URL.')
    if kind=='custom' and not item['success'].strip():raise Problem('Für eigene Anbieter bitte die exakte Erfolgsantwort angeben, z. B. good oder OK.')
    return item

def literal_config(text):
    """Parse only literal assignments, never source/eval legacy input."""
    result={}
    for num,line in enumerate(text.splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):continue
        m=re.fullmatch(r'([A-Z][A-Z0-9_]*)=(.*)',line)
        if not m:raise Problem('Altkonfiguration enthält keine reine Zuweisung (Zeile '+str(num)+').')
        raw=m[2]
        if any(x in raw for x in ('`','$(' ,'${')):raise Problem('Dynamische Shell-Ausdrücke werden nicht importiert.')
        try:parts=shlex.split(raw,comments=False,posix=True)
        except ValueError:raise Problem('Ungültige Anführungszeichen in Altkonfiguration.') from None
        if len(parts)!=1 and raw not in ('',"''",'""'):raise Problem('Mehrdeutige Altkonfiguration.')
        result[m[1]]=parts[0] if parts else ''
    return result

def legacy_inventory():
    rows=[];errors=[]
    for file in sorted((LEGACY/'providers.d').glob('*.conf')):
        try:
            if file.is_symlink():raise Problem('Symbolischer Link nicht importierbar.')
            data=literal_config(file.read_text())
            item={key.lower():value for key,value in data.items()}
            item['id']=hashlib.sha256(file.name.encode()).hexdigest()[:24]
            if data.get('METHOD','GET')!='GET':raise Problem('Nur GET-Updateprotokolle werden unterstützt.')
            if data.get('TYPE')=='cloudflare':raise Problem('Cloudflare benötigt eine Record-API; die Platzhaltervorlage aus v3 ist nicht funktionsfähig.')
            rows.append(validate_provider(item,item))
        except (Problem,OSError):errors.append(file.name+' kann nicht sicher übernommen werden. Im alten Manager prüfen.')
    cfg=copy.deepcopy(DEFAULT)
    try:
        old=literal_config((LEGACY/'config.conf').read_text())
        cfg['interface']=old.get('INTERFACE','')
        interval=old.get('UPDATE_INTERVAL','15min');m=re.fullmatch(r'(\d+)(min|m|h)',interval)
        if m:cfg['interval']=int(m[1])*(60 if m[2]=='h' else 1)
        cfg['strategy']=old.get('UPDATE_STRATEGY','ip_or_dns_change')
        cfg['lock_hours']=int(old.get('LOCK_ON_RATE_LIMIT_HOURS','6'))
        validate_settings(cfg)
    except FileNotFoundError:pass
    except (Problem,ValueError,OSError):errors.append('Allgemeine Altkonfiguration muss geprüft werden.')
    cfg['providers']=rows
    return cfg,errors

def validate_settings(data):
    try:interval=int(data['interval']);hours=int(data['lock_hours'])
    except (ValueError,KeyError):raise Problem('Intervall und Sperrdauer müssen ganze Zahlen sein.') from None
    if interval not in (5,10,15,30,60,120,180,360,720):raise Problem('Unterstützte Intervalle: 5, 10, 15, 30, 60, 120, 180, 360 oder 720 Minuten.')
    if not 1<=hours<=48:raise Problem('Sperrdauer muss zwischen 1 und 48 Stunden liegen.')
    if data.get('strategy') not in STRATEGIES:raise Problem('Unbekannte Aktualisierungsstrategie.')
    iface=data.get('interface','').strip()
    if iface and not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,15}',iface):raise Problem('Ungültige Netzwerkschnittstelle.')
    return dict(interface=iface,interval=interval,lock_hours=hours,strategy=data['strategy'])

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def http(url,headers=None):
    endpoint(url)
    # No environment proxy, redirects or credential-bearing error messages.
    opener=request.build_opener(request.ProxyHandler({}),NoRedirect())
    req=request.Request(url,headers=dict({'User-Agent':'ServerManager-DynDNS/4.0'},**(headers or {})))
    try:
        with opener.open(req,timeout=20) as response:return response.status,response.read(16385).decode('utf-8','replace')[:16384],dict(response.headers)
    except error.HTTPError as exc:return exc.code,'',dict(exc.headers)
    except (OSError,error.URLError,ValueError):raise Problem('HTTPS-Verbindung fehlgeschlagen oder Zeitlimit erreicht.') from None

def public_ip(value,version):
    try:ip=ipaddress.ip_address(value.strip())
    except ValueError:return ''
    return str(ip) if ip.version==version and ip.is_global and not ip.is_multicast else ''

def addresses(cfg):
    needed={4 if p['mode']=='ipv4' else 6 if p['mode']=='ipv6' else 0 for p in cfg['providers'] if p['enabled']}
    ip4=ip6=''
    if 4 in needed or 0 in needed:
        try:
            code,text,_=http('https://api.ipify.org');ip4=public_ip(text,4) if code==200 else ''
        except Problem:pass
    if 6 in needed or 0 in needed:
        iface=cfg['interface']
        if not iface:
            try:
                routes=json.loads(command(['ip','-j','-6','route','show','default']).stdout)
                iface=routes[0].get('dev','') if routes else ''
            except (Problem,ValueError):pass
        if iface:
            try:
                links=json.loads(command(['ip','-j','-6','addr','show','dev',iface]).stdout)
                for link in links:
                    for addr in link.get('addr_info',[]):
                        if addr.get('temporary') or addr.get('deprecated') or addr.get('tentative') or addr.get('dadfailed'):continue
                        value=public_ip(addr.get('local',''),6)
                        if value:ip6=value;break
                    if ip6:break
            except (Problem,ValueError):pass
    return ip4,ip6

def desired(provider,ip4,ip6):
    mode=provider['mode']
    if mode in ('ipv4','both','ipv4_required_ipv6_optional') and not ip4:raise Problem('Öffentliche IPv4-Adresse fehlt.')
    if mode in ('ipv6','both','ipv6_required_ipv4_optional') and not ip6:raise Problem('Stabile öffentliche IPv6-Adresse fehlt; Schnittstelle prüfen.')
    return {'ipv4':ip4 if mode!='ipv6' else '', 'ipv6':ip6 if mode!='ipv4' else ''}

def dns_probe(host,kind):
    """No provider access. Only authoritative answers are accepted as evidence."""
    host=hostname(host)
    if kind not in ('A','AAAA'):raise Problem('Unbekannter DNS-Abfragetyp.')
    report={'kind':kind,'zone':'','records':[],'steps':[],'ok':False}
    def query(args,label):
        try:
            result=command(['dig','+time=2','+tries=1',*args],timeout=5)
            if result.returncode:
                report['steps'].append(label+': DNS-Abfrage fehlgeschlagen.');return ''
            return result.stdout
        except Problem:
            report['steps'].append(label+': nicht erreichbar oder dig fehlt.');return ''
    soa=query(['+noall','+answer','+authority','SOA',host],'Zone ermitteln')
    for line in soa.splitlines():
        parts=line.split()
        if len(parts)>4 and parts[3]=='SOA':
            try:report['zone']=hostname(parts[0])
            except Problem:continue
            break
    if not report['zone']:
        report['message']='DNS-Zone nicht ermittelbar. Lokalen DNS-Resolver und dnsutils prüfen.';return report
    names=query(['+short','NS',report['zone']],'Nameserver ermitteln')
    for raw in names.splitlines()[:3]:
        try:ns=hostname(raw)
        except Problem:continue
        for transport in ('UDP','TCP'):
            label=ns+' / '+transport
            output=query((['+tcp'] if transport=='TCP' else [])+['+norecurse','+noall','+comments','+answer','@'+ns,kind,host],label)
            if not output:continue
            status=re.search(r'status: ([A-Z]+)',output)
            authoritative=bool(re.search(r'flags: [^;]*\baa\b',output))
            truncated=bool(re.search(r'flags: [^;]*\btc\b',output))
            code=status[1] if status else 'unbekannt'
            report['steps'].append(label+': '+code+(' · autoritativ' if authoritative else ' · keine autoritative Antwort'))
            if not authoritative or truncated or code not in ('NOERROR','NXDOMAIN'):continue
            values=set();alias=False
            for line in output.splitlines():
                parts=line.split()
                if len(parts)>4 and parts[0].rstrip('.').lower()==host:
                    if parts[3]=='CNAME':alias=True
                    if parts[3]==kind:
                        value=public_ip(parts[4],4 if kind=='A' else 6)
                        if value:values.add(value)
            if alias:
                report['message']='Host ist ein CNAME. Direkten DynDNS-Host beim Anbieter prüfen.';return report
            report.update(ok=True,records=sorted(values),message=('Autoritative Adresse erkannt.' if values else 'Autoritativ bestätigt: kein '+kind+'-Eintrag vorhanden.'))
            return report
    report['message']='Autoritativer DNS-Abgleich nicht verfügbar. Ausgehendes DNS (UDP/TCP 53), lokalen Resolver und Nameserver des Anbieters prüfen.'
    return report

def dns_records(host,kind):
    report=dns_probe(host,kind)
    if not report['ok']:raise DNSProblem(report['message'])
    return report['records']

def dns_error(state):
    return state.get('error_source')=='dns' or state.get('last_error','').startswith(('Autoritativer DNS-Abgleich','Autoritative DNS-Zone'))

def diagnose(key):
    """Recheck DNS and repair only its error display, never provider cooldowns."""
    with lock():
        cfg=load();provider=next((p for p in cfg['providers'] if p['id']==key),None)
        if not provider:raise Problem('Anbieter nicht gefunden.')
        state=provider_state(key);report={'checked':time.time(),'queries':[]}
        try:
            wanted=desired(provider,*addresses(dict(cfg,providers=[dict(provider,enabled=True)])))
            report['wanted']=wanted
            for family,kind in [('ipv4','A'),('ipv6','AAAA')]:
                if wanted[family]:
                    item=dns_probe(provider['host'],kind)
                    item['wanted']=wanted[family];item['match']=item['ok'] and wanted[family] in item['records']
                    report['queries'].append(item)
            available=all(q['ok'] for q in report['queries'])
            match=available and all(q['match'] for q in report['queries'])
            report['message']=('DNS stimmt mit den ermittelten Adressen überein.' if match else 'DNS weicht ab. Nach Ablauf der Anbieterwartezeit „Jetzt aktualisieren“ verwenden.' if available else 'DNS-Prüfung nicht vollständig möglich; Details unten prüfen.')
            if available and dns_error(state):
                state.update(status='checked',message=report['message']+' DNS-Fehleranzeige repariert; Anbieterwartezeiten bleiben erhalten.',dns_match=match)
                state.pop('last_error',None);state.pop('error_source',None)
            report['message']+=' Kein Anbieter-Update gesendet. Wartezeiten wurden nicht verkürzt.'
        except Problem as exc:report['message']=str(exc)
        state['diagnosis']=report;put_state(key,state)
        return report

def dns_matches(provider,wanted):
    return all(ip in dns_records(provider['host'],kind) for key,kind in [('ipv4','A'),('ipv6','AAAA')] if (ip:=wanted[key]))

def update_url(p,wanted):
    # Remove an unused family's complete query parameter instead of sending an
    # empty value (some providers interpret that as deletion or autodetection).
    parts=endpoint(p['url']);query=[]
    for family,aliases in [('ipv4',('ipv4','ip4')),('ipv6',('ipv6','ip6'))]:
        if not wanted[family] and any('{'+alias+'}' in parts.path for alias in aliases):raise Problem('Fehlende optionale Adresse im URL-Pfad; Anbieter-URL prüfen.')
    for key,value in parse.parse_qsl(parts.query,keep_blank_values=True):
        if any('{'+alias+'}' in value and not wanted[family] for family,aliases in [('ipv4',['ipv4','ip4']),('ipv6',['ipv6','ip6'])] for alias in aliases):continue
        query.append((key,value))
    url=parse.urlunsplit((parts.scheme,parts.netloc,parts.path,parse.urlencode(query,safe='{}'),''))
    host=p['host']
    if p['type']=='duckdns' and host.endswith('.duckdns.org'):host=host[:-12]
    values={'host':host,'user':p['username'],**wanted,'ip4':wanted['ipv4'],'ip6':wanted['ipv6'],**{key:p['secret'] for key in ('secret','pass','password','token')}}
    for key,value in values.items():url=url.replace('{'+key+'}',parse.quote(value,safe=''))
    if '{' in url or '}' in url:raise Problem('Nicht ersetzte URL-Platzhalter.')
    headers={}
    if p['auth']=='basic':headers['Authorization']='Basic '+base64.b64encode((p['username']+':'+p['secret']).encode()).decode()
    if p['auth']=='bearer':headers['Authorization']='Bearer '+p['secret']
    return url,headers

def response_state(p,code,text):
    value=text.strip().lower()
    if code==429 or re.search(r'\b(abuse|911|ucount)\b|rate.?limit|too many|maximum update',value):return 'limited'
    if code not in (200,201):return 'error'
    if p['type']=='custom':return 'ok' if value==p.get('success','').strip().lower() else 'error'
    if re.match(r'^(good|nochg)(?:\s|$)',value) or value in ('ok','addresses updated','addresses unchanged','updated','no changes'):return 'ok'
    # DDNSS also uses numeric status codes.
    if p['type'].startswith('ddnss') and re.match(r'^200(?:\s|$)',value):return 'ok'
    return 'error'

def provider_state(key):return read_json(STATE/(key+'.json'),{})
def put_state(key,state):atomic(STATE/(key+'.json'),json.dumps(state,ensure_ascii=False,indent=2)+'\n')

def run_updates(check_only=False):
    with lock():
        cfg=load();ip4,ip6=addresses(cfg);errors=0
        for p in cfg['providers']:
            if not p['enabled']:continue
            state=provider_state(p['id']);now=time.time();state['checked']=now;attempted=False
            try:
                wanted=desired(p,ip4,ip6);state['detected']=wanted
                if check_only:
                    state['dns_match']=dns_matches(p,wanted);state['message']=('Autoritatives DNS stimmt mit den ermittelten IP-Adressen überein.' if state['dns_match'] else 'Autoritatives DNS weicht von den ermittelten IP-Adressen ab.')+' Kein Update gesendet.';state['status']='checked'
                    put_state(p['id'],state);continue
                if state.get('blocked_until',0)>now:
                    state['message']='Anbieter-Sperrzeit aktiv.';state['status']='limited';put_state(p['id'],state);continue
                changed_after_success=bool(state.get('successful_ips')) and state['successful_ips']!=wanted and not state.get('failures',0)
                if state.get('retry_after',0)>now and not changed_after_success:
                    state['message']='Wartezeit nach letztem Versuch aktiv.'+(' Letzter Fehler: '+state['last_error'] if state.get('last_error') else '');put_state(p['id'],state);continue
                same=state.get('successful_ips')==wanted
                if same and cfg['strategy']=='ip_change_only':needed=False
                elif same and cfg['strategy']=='ip_or_dns_change':needed=not dns_matches(p,wanted)
                else:needed=True
                if not needed:
                    state.update(status='unchanged',message='Keine Aktualisierung nötig.');put_state(p['id'],state);continue
                # Persist attempt before network access; restart cannot create a retry storm.
                state.update(attempted=now,retry_after=now+max(300,cfg['interval']*60));put_state(p['id'],state);attempted=True
                url,headers=update_url(p,wanted);code,text,response_headers=http(url,headers)
                status=response_state(p,code,text)
                dns_confirmed=False
                # Some DDNSS responses include per-host prose instead of DynDNS tokens.
                # Never infer success from an arbitrary HTTP 200 or the word 'updated'.
                if status=='error' and code==200 and p['type'].startswith('ddnss') and re.search(r'\bupdated\b',text,re.I) and not re.search(r'\b(badauth|nohost|error|failed|invalid|denied)\b',text,re.I):
                    try:dns_confirmed=dns_matches(p,wanted)
                    except Problem:pass
                    if dns_confirmed:status='ok'
                if status=='limited':
                    retry=response_headers.get('Retry-After','')
                    delay=max(cfg['lock_hours']*3600,min(int(retry),172800) if retry.isdigit() else 0)
                    state.update(status='limited',blocked_until=now+delay,message='Anbieter meldet Begrenzung. Automatische Sperrzeit gesetzt.');errors+=1
                elif status=='ok':
                    state.update(status='ok',successful_ips=wanted,updated=now,failures=0,message='Anbieter hat die Aktualisierung bestätigt. DNS kann verzögert folgen.')
                    state.pop('last_error',None);state.pop('error_source',None)
                    if dns_confirmed:state.update(dns_match=True,message='Aktuelle IPv4/IPv6 durch autoritative DNS-Abfrage bestätigt.')
                    # DNS drift: at most one resend per hour for unchanged addresses.
                    state['retry_after']=now+max(3600,cfg['interval']*60)
                else:
                    errors+=1;failures=state.get('failures',0)+1
                    state.update(status='error',error_source='provider',failures=failures,retry_after=now+min(21600,300*2**min(failures,6)),message='Anbieter hat das Update nicht bestätigt (HTTP '+str(code)+'). Zugangsdaten und Vorlage prüfen.')
            except Problem as exc:
                errors+=1
                if not attempted:
                    # A read-only check must never consume a provider attempt.
                    state.update(status='error',message=str(exc),error_source='dns' if isinstance(exc,DNSProblem) else 'local')
                else:
                    failures=state.get('failures',0)+1
                    state.update(status='error',error_source='provider',message=str(exc),failures=failures,retry_after=now+min(21600,300*2**min(failures,6)))
            if state.get('status')=='error':state['last_error']=state['message']
            put_state(p['id'],state)
        return errors

def unit_status():
    result={}
    for suffix in ('timer','service'):
        r=command(['systemctl','show',UNIT+'.'+suffix,'--property=ActiveState,UnitFileState,NextElapseUSecRealtime,ExecMainStatus'])
        result[suffix]=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
    return result

def managed():
    file=UNITS/(UNIT+'.service')
    return file.exists() and '# ServerManager DynDNS v4' in file.read_text()

def import_runtime(cfg):
    legacy_state=Path('/var/lib/multi-dyndns-v3')
    for provider in cfg['providers']:
        slug=re.sub(r'[^a-z0-9._-]+','-',(provider['name']+'-'+provider['host']).lower()).strip('-')
        old_lock=legacy_state/'provider-locks'/(slug+'.lock')
        state=provider_state(provider['id'])
        try:
            until=int(old_lock.read_text().strip())
            if until>time.time():state.update(blocked_until=until,status='limited',message='Anbietersperre aus dem bisherigen Skript übernommen.')
        except FileNotFoundError:pass
        except (OSError,ValueError):raise Problem('Vorhandene Anbietersperre nicht lesbar; Übernahme abgebrochen.') from None
        state['retry_after']=max(state.get('retry_after',0),time.time()+cfg['interval']*60)
        put_state(provider['id'],state)

def activate(cfg):
    """Keep original unit/config backups; switch only between scheduled runs."""
    status=unit_status()
    if status['service'].get('ActiveState') in ('active','activating','deactivating'):raise Problem('Der bisherige DynDNS-Lauf ist noch aktiv. Nach Abschluss erneut versuchen.')
    validate_settings(cfg)
    if not any(p['enabled'] for p in cfg['providers']):raise Problem('Mindestens ein aktiver Anbieter ist erforderlich.')
    backup=STATE/'backups'/str(time.time_ns());backup.mkdir(parents=True,mode=0o700)
    files=[CONFIG,UNITS/(UNIT+'.service'),UNITS/(UNIT+'.timer')];original={str(p):p.read_text() if p.exists() else None for p in files}
    atomic(backup/'restore.json',json.dumps({'files':original,'status':status}))
    mins=cfg['interval'];calendar=('*:0/'+str(mins)) if mins<60 else ('*-*-* 0/'+str(mins//60)+':00:00')
    executable=Path(__file__).resolve()
    service=f'''# ServerManager DynDNS v4
[Unit]
Description=Server Manager DynDNS
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {executable} --run-update
UMask=0077
TimeoutStartSec=10min
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={STATE}
'''
    timer=f'''# ServerManager DynDNS v4
[Unit]
Description=Server Manager DynDNS-Zeitplan
[Timer]
OnCalendar={calendar}
AccuracySec=30s
Persistent=false
Unit={UNIT}.service
[Install]
WantedBy=timers.target
'''
    def ctl(*args):
        if command(['systemctl',*args]).returncode:raise Problem('DynDNS-Zeitplan konnte nicht aktiviert werden; Sicherung wird wiederhergestellt.')
    try:
        ctl('stop',UNIT+'.timer')
        if unit_status()['service'].get('ActiveState') in ('active','activating','deactivating'):raise Problem('DynDNS-Lauf wurde inzwischen gestartet.')
        if not CONFIG.exists():import_runtime(cfg)
        save(cfg);atomic(files[1],service,0o644);atomic(files[2],timer,0o644)
        ctl('daemon-reload');ctl('enable','--now',UNIT+'.timer')
    except Exception:
        for path,text in original.items():
            if text is None:Path(path).unlink(missing_ok=True)
            else:atomic(Path(path),text,0o600 if path==str(CONFIG) else 0o644)
        command(['systemctl','daemon-reload'])
        command(['systemctl','enable' if status['timer'].get('UnitFileState')=='enabled' else 'disable',UNIT+'.timer'])
        if status['timer'].get('ActiveState')=='active':command(['systemctl','start',UNIT+'.timer'])
        raise
    return backup

def main():
    parser=argparse.ArgumentParser(description='Multi DynDNS v4 · Server Manager')
    parser.add_argument('--run-update',action='store_true');parser.add_argument('--check',action='store_true');parser.add_argument('--status',action='store_true')
    args=parser.parse_args()
    try:
        if args.status:
            print(json.dumps([dict(name=p['name'],host=p['host'],enabled=p['enabled'],state=provider_state(p['id'])) for p in load()['providers']],ensure_ascii=False,indent=2));return 0
        if args.run_update or args.check:return int(bool(run_updates(args.check)))
        parser.print_help();return 0
    except Problem as exc:print(str(exc));return 1
if __name__=='__main__':raise SystemExit(main())
