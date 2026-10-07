"""Read-only channel-tag EPG with a two-day scrollable timeline and channel programme lists."""
from ui_translation import html_literal as _ui_html, text as _ui_text
import datetime,hashlib,html,json,time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from . import api,formatter
E=lambda value:html.escape(str(value),quote=True)
DEFAULT_TAG='Fernseher HD'

def catalog():
    tags=api.entries(api.request_json('/api/channeltag/list'))
    data=api.request_json('/api/channel/grid',dict(start=0,limit=5000))
    channels=[c for c in api.entries(data) if c.get('enabled',True)]
    if int(data.get('total',len(channels)))>5000:raise ValueError('Zu viele Sender für die Übersicht (mehr als 5000).')
    return tags,channels

def select(tags,channels,requested):
    tag=next((str(t['key']) for t in tags if t.get('val')==DEFAULT_TAG),None) if requested is None else requested
    if tag is None:raise ValueError('Der Standard-Tag „Fernseher HD“ ist nicht vorhanden. Bitte einen Tag auswählen oder „Alle Sender“ öffnen.')
    if tag and tag not in {str(t.get('key')) for t in tags}:raise ValueError('Der ausgewählte Kanal-Tag ist nicht verfügbar.')
    chosen=[c for c in channels if not tag or tag in c.get('tags',[])]
    def number(c):
        try:return float(c.get('number') or 999999)
        except (ValueError,TypeError):return 999999
    chosen.sort(key=lambda c:(number(c),str(c.get('name','')).casefold()))
    return tag,chosen

def events(channel,tag,start,end,query):
    filters=[dict(field='start',type='numeric',comparison='lt',value=int(end)),dict(field='stop',type='numeric',comparison='gt',value=int(start))]
    params=dict(start=0,limit=500,sort='start',dir='ASC',channel=channel['uuid'],filter=json.dumps(filters))
    if tag:params['channelTag']=tag
    if query:params['title']=query
    data=api.request_json('/api/epg/events/grid',params)
    rows=[]
    for event in api.entries(data):
        # Do not display unrelated channels if a server ignores an invalid filter.
        if event.get('channelUuid')!=channel['uuid']:continue
        try:a,b=float(event['start']),float(event['stop'])
        except (KeyError,ValueError,TypeError):continue
        if a>=end or b<=start or b<=a:continue
        title=str(formatter.value(event.get('title','Ohne Titel')))
        if query and query.casefold() not in title.casefold():continue
        description=formatter.value(event.get('description') or event.get('summary') or '')
        ident='programme-'+hashlib.sha256((str(channel['uuid'])+str(event.get('eventId',a))+title).encode()).hexdigest()[:18]
        rows.append(dict(start=a,stop=b,title=title,description=description,id=ident,event_id=event.get("eventId"),recording=event.get("dvrState") in ("scheduled","recording"),recording_state=event.get("dvrState", "")))
    return sorted(rows,key=lambda x:x['start']),int(data.get('totalCount',len(rows)))>500

def url(params,**changes):
    values=dict(params);values.update(changes)
    return '/tv/epg?'+urlencode(values)

def recording_url(event,params):
    ident=str(event.get("event_id") or "")
    return "/tv/epg/record/"+ident+"?"+urlencode({"back":url(params)}) if ident.isdecimal() and int(ident)>0 else "#"+event["id"]

def render(ctx,args):
    try:
        now=time.time();default=datetime.datetime.fromtimestamp(now).replace(minute=0,second=0,microsecond=0)
        date=args.get('date',default.date().isoformat());hour=args.get('time',default.strftime('%H:%M'))
        focus=datetime.datetime.fromisoformat(date+'T'+hour).timestamp()
        midnight=datetime.datetime.fromisoformat(date).replace(hour=0,minute=0,second=0,microsecond=0)
        start=midnight.timestamp();end=(midnight+datetime.timedelta(days=2)).timestamp()
        hours=int((end-start)/3600);track_width=hours*180
        if len(date)!=10 or len(hour)!=5:raise ValueError('Datum und Uhrzeit prüfen.')
        query=args.get('q','').strip()[:200];view=args.get('view','grid')
        if view not in ('grid','list'):view='grid'
        tags,channels=catalog();requested=args.get('tag')
        try:tag,chosen=select(tags,channels,requested)
        except ValueError as exc:
            return ctx.page(_ui_text('Programm suchen'),_ui_html("<div class='card'><p>")+E(_ui_text(exc))+_ui_html("</p><a class='btn' href='/tv/epg?tag='>Alle Sender öffnen</a></div>"),'TV'),400
        channel=args.get('channel','')
        if channel and channel not in {c['uuid'] for c in chosen}:channel=''
        filtered=[c for c in chosen if not channel or c['uuid']==channel]
        visible=filtered
        params=dict(tag=tag,channel=channel,date=date,time=hour,q=query,view=view)
        body=_ui_html("<div class='card'><h2>Fernsehprogramm durchsuchen</h2><form method='get' style='display:flex;gap:12px;flex-wrap:wrap;align-items:end'><label>Kanal-Tag<br><select name='tag'><option value=''")+(' selected' if not tag else '')+_ui_html(">Alle Sender</option>")
        for t in tags:body+=_ui_html("<option value='")+E(t['key'])+"'"+(' selected' if str(t['key'])==tag else '')+'>'+E(t['val'])+_ui_html('</option>')
        body+=_ui_html("</select></label><label>Sender<br><select name='channel'><option value=''>Alle Sender im Tag</option>")
        for c in chosen:body+=_ui_html("<option value='")+E(c['uuid'])+"'"+(' selected' if c['uuid']==channel else '')+'>'+E(c['name'])+_ui_html('</option>')
        body+=_ui_html("</select></label><label>Datum<br><input type='date' name='date' value='")+E(date)+_ui_html("' required></label><label>Zur Uhrzeit<br><input type='time' name='time' value='")+E(hour)+_ui_html("' required></label><label>Sendung<br><input name='q' value='")+E(query)+_ui_html("' placeholder='Titel suchen'></label><label>Ansicht<br><select name='view'><option value='grid'")+(' selected' if view=='grid' else '')+_ui_html(">EPG-Zeitleiste</option><option value='list'")+(' selected' if view=='list' else '')+_ui_html(">Programm pro Sender</option></select></label><button class='btn'>Anzeigen</button></form><p>Zeitraum: ")+E(datetime.datetime.fromtimestamp(start).strftime('%d.%m.%Y %H:%M'))+' bis '+E(datetime.datetime.fromtimestamp(end).strftime('%d.%m.%Y %H:%M'))+' · '+str(len(filtered))+_ui_html(' Sender</p>')
        for label,stamp in [('← Vortag',(midnight-datetime.timedelta(days=1)).timestamp()),('Jetzt',now),('Folgetag →',(midnight+datetime.timedelta(days=1)).timestamp())]:
            dt=datetime.datetime.fromtimestamp(stamp).replace(minute=0,second=0,microsecond=0)
            body+=_ui_html("<a class='btn' href='")+E(url(params,date=dt.date().isoformat(),time=dt.strftime('%H:%M')))+"'>"+_ui_text(label)+_ui_html('</a>')
        body+=_ui_html("<a class='btn' href='/tv/epg'>Fernseher HD · Jetzt</a></div>")
        def load(c):
            try:rows,truncated=events(c,tag,start,end,query);return c,rows,'Anzeigelimit erreicht; Suche eingrenzen.' if truncated else ''
            except (api.TvheadendError,ValueError):return c,[],'Programmdaten konnten nicht geladen werden.'
        with ThreadPoolExecutor(max_workers=4) as pool:loaded=list(pool.map(load,visible))
        if not visible:body+=_ui_html("<div class='card'><p>Keine Sender in diesem Tag vorhanden.</p></div>")
        if view=='grid' and visible:
            body+=_ui_html("<style>#epg-scroll{padding:0;isolation:isolate;height:864px;max-height:calc(65vh + 304px);overflow-x:auto;overflow-y:scroll;scrollbar-gutter:stable;overscroll-behavior:contain}.epg-table{margin:0;table-layout:fixed;border-collapse:separate;border-spacing:0;width:calc(var(--epg-width) + 170px)}.epg-table th:first-child{width:170px;min-width:170px;position:sticky;left:0;background:#182333;z-index:3}.epg-table thead th{position:sticky;top:0;padding:12px 0;background:#182333;z-index:4}.epg-table thead th:first-child{z-index:5}.epg-table td{padding:0}.epg-table th{box-sizing:border-box}.epg-hours{display:flex;width:var(--epg-width)}.epg-hours span{flex:0 0 180px;box-sizing:border-box;text-align:left}.epg-track{position:relative;height:76px;width:var(--epg-width);background:repeating-linear-gradient(to right,transparent 0,transparent calc(180px - 1px),#4b5563 calc(180px - 1px),#4b5563 180px)}.epg-programme{position:absolute;top:6px;height:62px;overflow:hidden;box-sizing:border-box;background:#27374d;border:1px solid #64748b;border-radius:6px;padding:5px;font-size:12px;color:#fff}.epg-programme.now{background:#164e40;border-color:#34d399}.epg-programme.recording{background:#991b1b;border-color:#f87171}.epg-recording-label{color:#f87171;font-weight:bold}.epg-marker{position:absolute;height:100%;border-left:2px solid #fbbf24;pointer-events:none;z-index:2}</style><div class='card'><button type='button' class='btn' data-epg-step='-1'>← Früher</button> <button type='button' class='btn' data-epg-step='1'>Später →</button> <button type='button' class='btn' id='epg-focus'>Zur gewählten Uhrzeit</button><p>Horizontal scrollen: ganzer Tag und Folgetag · Vertikal scrollen: weitere Sender. Sendernamen und Uhrzeiten bleiben sichtbar.</p></div><div id='epg-scroll' class='card epg-scroll' tabindex='0' aria-label='Fernsehprogramm für zwei Tage' style='--epg-width:")+str(track_width)+_ui_html("px'><table class='epg-table'><thead><tr><th>Sender</th><th><div class='epg-hours'>")
            for i in range(hours):body+=_ui_html("<span>")+datetime.datetime.fromtimestamp(start+i*3600).strftime('%a %d.%m. %H:%M')+_ui_html('</span>')
            body+=_ui_html('</div></th></tr></thead><tbody>')
            for c,rows,error in loaded:
                body+=_ui_html("<tr><th><a href='")+E(url(params,channel=c['uuid'],view='list'))+"'>"+E(c['name'])+_ui_html("</a></th><td><div class='epg-track'>")
                if error:body+=_ui_html("<span class='warn'>")+E(_ui_text(error))+_ui_html('</span>')
                elif not rows:body+=_ui_html('<span>Keine Programmdaten / Treffer in diesem Zeitraum.</span>')
                for event in rows:
                    left=max(0,(event['start']-start)/(end-start)*100);width=(min(end,event['stop'])-max(start,event['start']))/(end-start)*100
                    times=datetime.datetime.fromtimestamp(event['start']).strftime('%H:%M')+'–'+datetime.datetime.fromtimestamp(event['stop']).strftime('%H:%M')
                    body+=_ui_html("<a class='epg-programme")+(' recording' if event.get('recording',False) else ' now' if event['start']<=now<event['stop'] else '')+"' style='left:"+str(round(left,4))+'%;width:'+str(round(width,4))+"%' href='"+E(recording_url(event,params))+"' title='"+E(times+' '+event['title']+(' · Aufnahme geplant / läuft' if event.get('recording',False) else ''))+"'>"+E(times)+_ui_html('<br><b>')+E(event['title'])+_ui_html('</b></a>')
                if start<=now<end:body+=_ui_html("<span class='epg-marker' style='left:")+str((now-start)/(end-start)*100)+_ui_html("%'></span>")
                body+=_ui_html('</div></td></tr>')
            body+=_ui_html('</tbody></table><p>Rot: Aufnahme geplant / läuft · Grün: läuft jetzt · Gelbe Linie: aktuelle Zeit · Sendung anklicken zum Aufnehmen · Sender anklicken für dessen Programmliste.</p></div>')
        if view=='grid' and visible:
            body += _ui_html("""<script>(()=>{const box=document.getElementById('epg-scroll');
            const focus=""")+str(max(0,(focus-start)/3600*180))+_ui_html(""";
            box.scrollLeft=focus;
            document.querySelectorAll('[data-epg-step]').forEach(button=>button.addEventListener('click',()=>box.scrollBy({left:Number(button.dataset.epgStep)*Math.max(180,box.clientWidth-170),behavior:'smooth'})));
            document.getElementById('epg-focus').addEventListener('click',()=>box.scrollTo({left:focus,behavior:'smooth'}));
            })();</script>""")
        for c,rows,error in loaded:
            body+=_ui_html("<div class='card'><h3>")+E(c['name'])+_ui_html('</h3>')
            if error:body+=_ui_html("<p class='warn'>")+E(_ui_text(error))+_ui_html('</p>')
            if not rows and not error:body+=_ui_html('<p>Keine Programmdaten / Treffer in diesem Zeitraum.</p>')
            for event in rows:
                times=datetime.datetime.fromtimestamp(event['start']).strftime('%d.%m. %H:%M')+'–'+datetime.datetime.fromtimestamp(event['stop']).strftime('%H:%M')
                body+=_ui_html("<details id='")+event['id']+_ui_html("'><summary style='padding:8px;cursor:pointer'>")+E(times)+_ui_html(' · <b>')+E(event['title'])+_ui_html('</b>')+(_ui_html(' <span class="epg-recording-label">● ')+(_ui_text('Aufnahme läuft') if event.get('recording_state')=='recording' else _ui_text('Aufnahme geplant'))+_ui_html('</span>') if event.get('recording',False) else '')+(_ui_text(' · läuft jetzt') if event['start']<=now<event['stop'] else '')+_ui_html('</summary><p>')+E(event['description'] or _ui_text('Keine Beschreibung vorhanden.'))+_ui_html('</p><a class="btn" href="')+E(recording_url(event,params))+_ui_html('">1× aufnehmen / Serie aufnehmen</a></details>')
            body+=_ui_html('</div>')
        return ctx.page(_ui_text('Programm suchen'),body,'TV')
    except (ValueError,OverflowError,OSError,api.TvheadendError):
        return ctx.page(_ui_text('Programm suchen'),_ui_html("<div class='card'><p>EPG konnte nicht geladen werden. Datum/Uhrzeit und Verbindung prüfen.</p><a class='btn' href='/tv/epg'>Erneut versuchen</a> <a class='btn' href='/tv/status'>Verbindung prüfen</a></div>"),'TV'),400
