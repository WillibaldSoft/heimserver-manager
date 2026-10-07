# -*- coding: utf-8 -*-
from .disks import df_rows, mount_description, _mount_display_name
from .smart import smart_rows
from .helpers import setting, ntfy_send


def check_storage(ctx, send=False):
    disk_warn = int(setting(ctx, 'disk_warn_percent', '90') or '90')
    temp_warn = int(setting(ctx, 'temp_warn_c', '55') or '55')
    problems=[]
    for r in df_rows():
        if int(r.get('pct') or 0) >= disk_warn:
            problems.append({'type':'diskspace','level':'WARN','text':'{} ({}, {}) ist zu {} belegt'.format(_mount_display_name(r['mount']), r['mount'], r['fs'], r['use']), 'row':r})
    for r in smart_rows(temp_warn):
        if r.get('status') in ('WARN','FAIL'):
            level = 'CRIT' if r.get('status') == 'FAIL' else 'WARN'
            problems.append({'type':'smart','level':level,'text':'SMART {} · {}: {} Temp={} Pending={} Realloc={} Media={}'.format(r['dev'], mount_description(r), r['status'], r.get('temp',''), r.get('pending',''), r.get('realloc',''), r.get('media','')), 'row':r})
    if send and problems:
        msg='\n'.join(p['text'] for p in problems[:10])
        ntfy_send(ctx, 'Server Manager Speicherwarnung', msg, 'warning')
    return {'ok': True, 'problem_count': len(problems), 'problems': problems}
