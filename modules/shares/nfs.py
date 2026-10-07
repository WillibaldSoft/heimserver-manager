# -*- coding: utf-8 -*-
from server_settings import get as host_setting
from .helpers import NFS_EXPORTS, sudo_run, backup_file

def list_exports():
    from .configuration import nfs_exports
    return nfs_exports()

def save_exports(rows, password=''):
    backup_file(NFS_EXPORTS)
    txt = NFS_EXPORTS.read_text(errors='ignore') if NFS_EXPORTS.exists() else ''
    keep=[]
    for line in txt.splitlines():
        s=line.strip()
        if not s or s.startswith('#'):
            keep.append(line)
    body = keep + [r['path'] + ' ' + r['clients'] for r in rows if r.get('path') and r.get('clients')]
    NFS_EXPORTS.write_text('\n'.join(body).rstrip() + '\n')
    r = sudo_run(['exportfs','-ra'], password=password, timeout=30)
    sudo_run(['systemctl','reload','nfs-server.service'], password=password, timeout=20)
    return {'ok': r['ok'], 'details': r}

def upsert_export(path, clients=None, password=''):
    if clients is None:clients=host_setting('lan_network')+'(rw,sync,no_subtree_check)'
    rows = list_exports()
    found=False
    for r in rows:
        if r['path'] == path:
            r['clients'] = clients
            found=True
    if not found:
        rows.append({'path': path, 'clients': clients})
    return save_exports(rows, password=password)

def delete_export(path, password=''):
    rows=[r for r in list_exports() if r['path'] != path]
    return save_exports(rows, password=password)
