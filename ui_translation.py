"""Translate explicitly marked presentation literals, never configuration or form values."""
import ast
import hashlib
import html
import json
import re
import string
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent / 'locales'
DE = {'Health': 'Zustand', 'Repair': 'Reparatur', 'Restore': 'Wiederherstellung',
      'Backup': 'Sicherung', 'Logs': 'Protokolle', 'Discovery': 'Gerätesuche',
      'Application Manager': 'Anwendungsverwaltung', 'Backup & Recovery': 'Sicherung & Wiederherstellung',
      'Restart': 'Neu starten', 'Reload': 'Neu laden', 'Start': 'Starten', 'Stop': 'Stoppen',
      'Enable': 'Autostart aktivieren', 'Disable': 'Autostart deaktivieren',
      'Update': 'Aktualisierung', 'Updates': 'Aktualisierungen', 'Installer': 'Installation',
      'active': 'aktiv', 'inactive': 'inaktiv', 'enabled': 'aktiviert', 'disabled': 'deaktiviert',
      'running': 'läuft', 'failed': 'fehlgeschlagen', 'completed': 'abgeschlossen',
      'unknown': 'unbekannt', 'queued': 'wartend', 'skipped': 'übersprungen',
      'Failed Units': 'Fehlgeschlagene Dienste', 'Checks': 'Prüfungen', 'Check': 'Prüfung'}

@lru_cache(maxsize=2)
def catalog(lang):
    try:
        value = json.loads((ROOT / ('de.json' if lang=='de' else 'en.json')).read_text(encoding='utf-8'))
        return ({**value,**DE} if lang=='de' else value) if isinstance(value, dict) else {}
    except (OSError, ValueError): return DE if lang=='de' else {}

def current_language():
    from i18n import language
    return language()

def text(value):
    """Only pass application-authored labels/messages, never user names or paths."""
    if value is None: return value
    value = str(value)
    return lookup(value, current_language())

@lru_cache(maxsize=4096)
def lookup(value, lang):
    core = value.strip()
    translated = catalog(lang).get(core)
    if translated is None:
        for regex,parts in message_patterns(lang):
            match=regex.fullmatch(core)
            if match:
                translated=''.join(piece if isinstance(piece,str) else match.group(piece[0]) for piece in parts)
                break
    if translated is None: return value
    return value[:len(value)-len(value.lstrip())] + translated + value[len(value.rstrip()):]


@lru_cache(maxsize=2)
def message_patterns(lang):
    result=[];formatter=string.Formatter()
    for source,target in catalog(lang).items():
        if len(source)>1500:continue
        if '{' not in source:
            spec=re.compile(r'%(?:\([^)]+\))?[#0 +\-]*\d*(?:\.\d+)?[sdrif]')
            if not spec.search(source):continue
            def formatted(value):
                count=[0]
                def field(match):
                    i=count[0];count[0]+=1;return '{'+str(i)+'}'
                return spec.sub(field,value)
            source,target=formatted(source),formatted(target)
        try:
            original=list(formatter.parse(source));converted=list(formatter.parse(target))
            if sum(len(lit) for lit,field,spec,conv in original)<14:continue
            fields={};pattern='';index=0;auto=0
            for literal,field,spec,conv in original:
                pattern+=re.escape(literal)
                if field is not None:
                    index+=1
                    key=str(auto) if field=='' else field
                    if field=='':auto+=1
                    fields[key]=index;pattern+='(.{0,4096}?)'
            if not fields or index>4:continue
            pieces=[];auto=0
            for literal,field,spec,conv in converted:
                pieces.append(literal)
                if field is not None:
                    key=str(auto) if field=='' else field
                    if field=='':auto+=1
                    pieces.append((fields[key],))
            result.append((re.compile(pattern,re.S),pieces))
        except (ValueError,KeyError,re.error):continue
    return result

# Script constants are translated before dynamic data is inserted. Keys, URLs,
# selectors and unlisted values are preserved. No script is executed here.
JS_STRING = re.compile(r'''(?P<q>["'])(?:\\.|(?! (?P=q))[^\\])*?(?P=q)''', re.X)

def javascript(source, lang):
    def replace(match):
        raw = match.group(0)
        try: value = ast.literal_eval(raw)
        except (SyntaxError, ValueError): return raw
        if not isinstance(value, str): return raw
        if re.fullmatch(r'[a-z0-9_./#:-]+',value):return raw
        before = source[max(0, match.start()-4):match.start()].strip()
        after = source[match.end():match.end()+4].strip()
        if after.startswith(':') or any(op in before or op in after for op in ('==', '!=')):return raw
        result = lookup(value, lang)
        if result == value: return raw
        return json.dumps(result, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&','\\u0026')
    result=JS_STRING.sub(replace, source)
    # Only diagnostic fields assigned to visible text; never paths or names.
    result=re.sub(r'(\.textContent\s*=\s*)([A-Za-z_$][\w$]*\.(?:message|error|current_detail|state_text))(?![\w.])',r'\1window.hsmTranslate(\2)',result)
    result=re.sub(r'(Error\(\s*)([A-Za-z_$][\w$]*\.(?:message|error))(?![\w.])',r'\1window.hsmTranslate(\2)',result)
    return result

class LiteralParser(HTMLParser):
    def __init__(self, source, lang):
        super().__init__(convert_charrefs=False)
        self.source=source;self.lang=lang;self.edits=[];self.skip=[];self.pending=None
        self.offsets=[0]
        for match in re.finditer('\n',source):self.offsets.append(match.end())
    def source_offset(self):
        line,column=self.getpos();return self.offsets[line-1]+column
    def handle_starttag(self,tag,attrs):
        self.flush()
        if tag in ('pre','code','textarea','style','script'):
            self.skip.append(tag)
        if self.skip:return
        raw=self.get_starttag_text();base=self.source_offset()
        for match in re.finditer(r'''\b(title|placeholder|aria-label|onclick|onsubmit)\s*=\s*(["'])(.*?)\2''',raw,re.S):
            key,quote,value=match.groups();decoded=html.unescape(value)
            result=javascript(decoded,self.lang) if key in ('onclick','onsubmit') else lookup(decoded,self.lang)
            if result!=decoded:self.edits.append((base+match.start(3),base+match.end(3),html.escape(result,quote=True)))
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):
        self.flush()
        if self.skip and self.skip[-1]==tag:self.skip.pop()
    def handle_data(self,data):
        if self.pending is None:self.pending=[self.source_offset(),data,list(self.skip)]
        else:self.pending[1]+=data
    def handle_entityref(self,name):self.handle_data('&'+name+';')
    def handle_charref(self,name):self.handle_data('&#'+name+';')
    def handle_comment(self,data):self.flush()
    def handle_decl(self,data):self.flush()
    def flush(self):
        if self.pending is None:return
        start,data,skip=self.pending;self.pending=None
        if skip:
            if skip[-1]=='script':
                translated=javascript(data,self.lang)
                if translated!=data:self.edits.append((start,start+len(data),translated))
            return
        prefix=re.match(r"^(?:[^<\n]*?[\"']\s*)?>",data)
        if prefix:
            start+=prefix.end();data=data[prefix.end():]
        elif data.lstrip().startswith(('"',"'",'=')):return
        decoded=html.unescape(data);translated=lookup(decoded,self.lang)
        if translated!=decoded:self.edits.append((start,start+len(data),html.escape(translated,quote=False)))
    def close(self):super().close();self.flush()

def html_literal(source):
    """Called on static source literals BEFORE format/concatenation with user data."""
    if not isinstance(source,str):return source
    if source in {'active','inactive','enabled','disabled','running','failed','completed','ok','warn','err','yes','no','true','false','on','off','auto','POST','GET','read','write','none'}:return source
    lang=current_language()
    return render_literal(source,lang)

@lru_cache(maxsize=8192)
def render_literal(source,lang):
    parser=LiteralParser(source,lang)
    try:parser.feed(source);parser.close()
    except Exception:return source
    for start,end,value in reversed(sorted(parser.edits)):source=source[:start]+value+source[end:]
    return source

@lru_cache(maxsize=2)
def asset_url(lang):
    if lang not in ('de','en'):lang='de'
    path=Path(__file__).parent/'static/i18n'/(lang+'.js')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else 'missing'
    return '/static/i18n/'+lang+'.js?v='+digest
