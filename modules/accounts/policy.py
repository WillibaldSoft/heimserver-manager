"""Non-admin routes are opt-in. New/unknown endpoints always remain admin-only."""
from ui_translation import html_literal as _ui_html
import re
from urllib.parse import urlsplit
from flask import g,has_request_context,request
SCOPES={
 'server':('Serverstatus','/account/server','Dienste und Startzeit ohne Protokolle, Befehle oder Konfiguration.'),
 'storage':('Speicherstatus','/speicher','Belegung und SMART-Anzeige. Kein Mounten und keine Tests.'),
 'network':('Heimnetz ansehen','/heimnetz','Gerätenamen und Adressen ansehen. Keine Client-Tokens oder Änderungen.'),
 'apps':('Anwendungen ansehen','/apps','Übersicht. Keine Installationen, Updates, Konfigurationen oder Server-Backups.'),
 'tv':('TV & Aufnahmen','/tv','Programm und Aufnahmeliste. Benutzer dürfen Aufnahmen planen; Löschen bleibt Administration.'),
 'downloads':('Downloads','/downloads','Zugriff auf ALLE Dateien im konfigurierten Downloadordner, unabhängig von SMB-/NFS-Rechten. Benutzer dürfen neue Dateien hochladen.'),
 'dyndns':('DynDNS ansehen','/dyndns','Anbieterstatus und Hostnamen. Keine Zugangsdaten oder Änderungen.'),
 'client':('Eigene Clients & Sicherungen','/account/client','Eigene Benutzer-Geräte-Kopplungen und Schlafblocker; eigene Sicherungen erstellen und wiederherstellen; Nur Lesen erlaubt nur Rücksicherung. Keine fremden Ablagen oder Server-Sicherungen.')}
READ={
 '/clients/setup':'client',
 '/account/server':'server','/speicher':'storage','/storage':'storage','/speicher/smart':'storage',
 '/heimnetz':'network','/apps':'apps','/tv':'tv','/tv/epg':'tv','/tv/recordings':'tv','/tv/upcoming':'tv','/tv/streams':'tv',
 '/downloads':'downloads','/downloads/file':'downloads','/dyndns':'dyndns','/account/client':'client','/api/account/access':'client','/api/account/backup':'client',
 '/clients/desktop/download':'client','/clients/windows/download':'client','/clients/recovery/download':'client'}
COMMON={'/','/account','/settings/access','/logout','/language'}
def allowed(principal,path,method='GET'):
    if not principal:return False
    if principal['role']=='admin':return True
    if path.startswith('/static/') and path.rsplit('.',1)[-1].lower() in ('css','js','png','svg','ico','woff','woff2'):return method in ('GET','HEAD')
    if path in COMMON:return method in ('GET','HEAD') or (method=='POST' and path in ('/logout','/language'))
    scope=READ.get(path)
    if re.fullmatch(r'/tv/epg/record/\d+',path):scope='tv'
    if method in ('GET','HEAD'):return scope in principal.get('modules',[])
    if principal['role']!='user' or method!='POST':return False
    if path in ('/api/account/backup','/api/account/agent/pair','/clients/setup/profile'):return 'client' in principal.get('modules',[])
    if path=='/downloads/upload':return 'downloads' in principal.get('modules',[])
    if re.fullmatch(r'/tv/epg/record/\d+',path):return 'tv' in principal.get('modules',[])
    return False

def current():return getattr(g,'auth_principal',None) if has_request_context() else None
def is_admin():
    p=current();return bool(p and p['role']=='admin')
def navigation(groups):
    p=current()
    if not p or p['role']=='admin':return groups
    result=[]
    for label,url,children in groups:
        children=[(name,path) for name,path in children if allowed(p,path)]
        if not allowed(p,url):
            if not children:continue
            url=children[0][1]
        result.append((label,url,children))
    return result

def filter_html(body):
    """Presentation only. Authorization is independently enforced before dispatch."""
    p=current()
    if not p or p['role']=='admin':return body
    from html.parser import HTMLParser
    import html
    class Filter(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=False);self.out=[];self.skip=0;self.anchors=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='form':
                target=urlsplit(a.get('action') or request.path).path
                if self.skip or not allowed(p,target,a.get('method','GET').upper()):self.skip+=1;return
            if self.skip:return
            if tag=='a':
                url=a.get('href','');target=urlsplit(url)
                ok=not url.startswith('/') or allowed(p,target.path or request.path)
                self.anchors.append(ok)
                if not ok:self.out.append(_ui_html('<span>'));return
            self.out.append(self.get_starttag_text())
        def handle_endtag(self,tag):
            if self.skip:
                if tag=='form':self.skip-=1
                return
            if tag=='a' and self.anchors and not self.anchors.pop():self.out.append(_ui_html('</span>'));return
            self.out.append('</'+tag+'>')
        def handle_data(self,text):
            if not self.skip:self.out.append(text)
        def handle_entityref(self,name):
            if not self.skip:self.out.append('&'+name+';')
        def handle_charref(self,name):
            if not self.skip:self.out.append('&#'+name+';')
        def handle_startendtag(self,tag,attrs):
            if not self.skip:self.out.append(self.get_starttag_text())
    f=Filter();f.feed(body);return ''.join(f.out)
