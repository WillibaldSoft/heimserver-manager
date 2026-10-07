# -*- coding: utf-8 -*-
import re
from .helpers import run
from .disks import disks_summary


def smart_devices():
    r = run(['lsblk','-ndo','NAME,TYPE'], timeout=5)
    devs=[]
    for line in (r['out'] or '').splitlines():
        parts=line.split()
        if len(parts)>=2 and parts[1]=='disk' and (parts[0].startswith('sd') or parts[0].startswith('nvme') or parts[0].startswith('hd')):
            devs.append('/dev/'+parts[0])
    return devs


def smart_row(dev, temp_warn=55):
    rc = run(['sudo','/usr/sbin/smartctl','-H',dev], timeout=15)
    health=(rc.get('out','')+'\n'+rc.get('err',''))
    status='OK' if ('PASSED' in health or 'OK' in health) else ('FAIL' if 'FAILED' in health else '?')
    a = run(['sudo','/usr/sbin/smartctl','-A',dev], timeout=20)
    data=(a.get('out','')+'\n'+a.get('err',''))
    temp=realloc=pending=uncorr=used=media=poh=crc=''
    for line in data.splitlines():
        low=line.lower(); parts=line.split()
        if 'temperature_celsius' in low and parts: temp=parts[-1]
        elif low.startswith('temperature:'):
            m=re.search(r'(\d+)\s+Celsius', line); temp=m.group(1) if m else temp
        elif 'temperature sensor 1' in low and not temp:
            m=re.search(r'(\d+)\s+Celsius', line); temp=m.group(1) if m else temp
        elif 'reallocated_sector_ct' in low and parts: realloc=parts[-1]
        elif 'current_pending_sector' in low and parts: pending=parts[-1]
        elif 'offline_uncorrectable' in low and parts: uncorr=parts[-1]
        elif 'udma_crc_error_count' in low and parts: crc=parts[-1]
        elif 'power_on_hours' in low and parts: poh=parts[-1]
        elif 'power on hours' in low:
            m=re.search(r':\s*([0-9,]+)', line); poh=m.group(1) if m else poh
        elif 'percentage used' in low:
            m=re.search(r'(\d+)%', line); used=m.group(1)+'%' if m else used
        elif 'media_errors' in low or 'media and data integrity errors' in low:
            m=re.search(r':\s*([0-9]+)', line); media=m.group(1) if m else media
    warn=False
    for x in (realloc,pending,uncorr,media):
        try:
            if x and int(str(x).replace(',','')) > 0: warn=True
        except Exception: pass
    try:
        if temp and int(temp) >= int(temp_warn): warn=True
    except Exception: pass
    if warn and status == 'OK': status='WARN'
    return {'dev':dev,'status':status,'temp':temp,'realloc':realloc,'pending':pending,'uncorr':uncorr,'used':used,'media':media,'poh':poh,'crc':crc,'raw_health':health.strip()}


def smart_rows(temp_warn=55):
    identities = {d['path']: d for d in disks_summary()}
    rows = []
    for dev in smart_devices():
        row = smart_row(dev, temp_warn)
        identity = identities.get(dev, {})
        row.update(mountpoints=identity.get('mountpoints', []), display_name=identity.get('display_name', dev))
        rows.append(row)
    return rows
