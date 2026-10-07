from server_settings import get as host_setting
# -*- coding: utf-8 -*-
import json, os, re, shlex
from .helpers import run, bytes_human


def lsblk_tree():
    r = run(['lsblk','-J','-O','-b'], timeout=20)
    if not r['ok']:
        return []
    try:
        return json.loads(r['out']).get('blockdevices', [])
    except Exception:
        return []


def flatten_devices(devs, parent=None):
    out = []
    for d in devs:
        x = dict(d)
        x['parent'] = parent
        out.append(x)
        out.extend(flatten_devices(d.get('children') or [], d.get('name')))
    return out


def df_rows():
    r = run(['df','-h','-x','tmpfs','-x','devtmpfs'], timeout=15)
    rows=[]
    for line in (r['out'] or '').splitlines()[1:]:
        parts=line.split()
        if len(parts) >= 6:
            try: pct=int(parts[4].rstrip('%'))
            except Exception: pct=0
            rows.append({'fs':parts[0], 'size':parts[1], 'used':parts[2], 'avail':parts[3], 'use':parts[4], 'pct':pct, 'mount':' '.join(parts[5:])})
    return rows


def mount_candidates():
    devs = flatten_devices(lsblk_tree())
    rows=[]
    for d in devs:
        typ = d.get('type')
        name = d.get('name')
        path = d.get('path') or ('/dev/'+name if name else '')
        fstype = d.get('fstype') or ''
        mount = d.get('mountpoint') or ''
        if typ not in ('part','crypt','lvm'):
            continue
        if mount:
            continue
        if not fstype or fstype in ('swap','crypto_LUKS'):
            continue
        rows.append({
            'name': name, 'path': path, 'fstype': fstype, 'label': d.get('label') or '',
            'uuid': d.get('uuid') or '', 'size': bytes_human(d.get('size')), 'model': d.get('model') or '',
            'tran': d.get('tran') or '', 'mountable': True
        })
    return rows


def mounted_devices():
    devs=flatten_devices(lsblk_tree())
    rows=[]
    for d in devs:
        if d.get('type') not in ('part','crypt','lvm'):
            continue
        if not d.get('mountpoint'):
            continue
        rows.append({
            'name': d.get('name'), 'path': d.get('path') or '/dev/'+d.get('name',''), 'mount': d.get('mountpoint'),
            'fstype': d.get('fstype') or '', 'label': d.get('label') or '', 'uuid': d.get('uuid') or '',
            'size': bytes_human(d.get('size')), 'model': d.get('model') or '', 'tran': d.get('tran') or ''
        })
    return rows


def _mount_display_name(mountpoint):
    mountpoint = str(mountpoint or '').strip()

    if mountpoint == '/':
        return 'System'

    mountpoint = mountpoint.rstrip('/')

    special = {'/boot':'System', '/boot/efi':'System', **host_setting('storage_labels')}

    if mountpoint in special:
        return special[mountpoint]

    return os.path.basename(mountpoint) if mountpoint else ''


def _disk_display_name(disk, children):
    mountpoints = []

    for item in [disk] + children:
        values = item.get('mountpoints')

        if isinstance(values, list):
            mountpoints.extend(
                str(value).strip()
                for value in values
                if value
            )

        mountpoint = item.get('mountpoint')

        if mountpoint:
            mountpoints.append(str(mountpoint).strip())

    mountpoints = list(dict.fromkeys(mountpoints))

    priorities = ['/', *host_setting('storage_labels')]

    for mountpoint in priorities:
        if mountpoint in mountpoints:
            return _mount_display_name(mountpoint)

    for mountpoint in mountpoints:
        name = _mount_display_name(mountpoint)

        if name:
            return name

    for item in [disk] + children:
        label = str(item.get('label') or '').strip()

        if label:
            return label

    model = str(disk.get('model') or '').strip()

    return model or str(disk.get('name') or 'Unbekannt')


def disk_mounts(disk, children):
    mounts = []
    for node in [disk] + children:
        values = node.get('mountpoints') or []
        if not isinstance(values, list):
            values = [values]
        for value in values + [node.get('mountpoint')]:
            if value and value != '[SWAP]' and value not in mounts:
                mounts.append(value)
    return mounts


def mount_description(row):
    mounts = row.get('mountpoints', [])
    if not mounts:
        return 'Nicht gemountet / Mount-Zuordnung nicht verfügbar'
    return ', '.join('{} ({})'.format(_mount_display_name(m), m) for m in mounts)


def disks_summary():
    disks = []
    def visit(nodes):
        for disk in nodes:
            if disk.get('type') == 'disk':
                name = disk.get('name') or ''
                children = flatten_devices(disk.get('children') or [])
                disks.append({
                    'name': name, 'display_name': _disk_display_name(disk, children),
                    'mountpoints': disk_mounts(disk, children),
                    'path': disk.get('path') or '/dev/' + name,
                    'model': disk.get('model') or '', 'serial': disk.get('serial') or '',
                    'size': bytes_human(disk.get('size')), 'tran': disk.get('tran') or '',
                    'rota': disk.get('rota'), 'vendor': disk.get('vendor') or '',
                })
            else:
                visit(disk.get('children') or [])
    visit(lsblk_tree())
    return disks
