# -*- coding: utf-8 -*-
from pathlib import Path
import re
from .helpers import SMB_CONF, SMB_SHARES_DIR, run, sudo_run, safe_name, backup_file

SPECIAL = {'global','printers','print$','homes'}

def ensure_include(password=''):
    SMB_SHARES_DIR.mkdir(parents=True, exist_ok=True)
    include = 'include = /etc/samba/shares.d/*.conf'
    if not SMB_CONF.exists():
        return True
    txt = SMB_CONF.read_text(errors='ignore')
    if include.lower() not in txt.lower():
        backup_file(SMB_CONF)
        SMB_CONF.write_text(txt.rstrip() + '\n\n# Server Manager Freigaben\n' + include + '\n')
    return True

def parse_config_text(txt, source=''):
    shares = []
    current = None
    cfg = {}
    raw = []
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            if current:
                shares.append({'name': current, 'file': source, 'path': cfg.get('path',''), 'comment': cfg.get('comment',''), 'config': cfg, 'raw': '\n'.join(raw)})
            current = s[1:-1].strip()
            cfg = {}
            raw = [line]
            continue
        if current:
            raw.append(line)
            if not s or s.startswith(('#',';')):
                continue
            if '=' in s:
                k,v = s.split('=',1)
                cfg[k.strip().lower()] = v.strip()
    if current:
        shares.append({'name': current, 'file': source, 'path': cfg.get('path',''), 'comment': cfg.get('comment',''), 'config': cfg, 'raw': '\n'.join(raw)})
    return [s for s in shares if s['name'].lower() not in SPECIAL]

def list_file_shares():
    out=[]
    for p in sorted(SMB_SHARES_DIR.glob('*.conf')):
        out.extend(parse_config_text(p.read_text(errors='ignore'), str(p)))
    return out

def list_all_shares():
    from .configuration import smb_shares
    return smb_shares()

def share_file(name):
    return SMB_SHARES_DIR / (safe_name(name) + '.conf')

def write_share(name, path, comment='', browseable=True, guest=False, force_group='', valid_users='', write_list='', admin_users='', password=''):
    ensure_include(password)
    SMB_SHARES_DIR.mkdir(parents=True, exist_ok=True)
    f = share_file(name)
    if f.exists():
        backup_file(f)
    lines = [
        f'[{name}]',
        f'   path = {path}',
        f'   comment = {comment or name}',
        f'   browseable = {"yes" if browseable else "no"}',
        '   read only = no',
        f'   guest ok = {"yes" if guest else "no"}',
        '   create mask = 0660',
        '   directory mask = 2770',
        '   force create mode = 0660',
        '   force directory mode = 2770',
        '   inherit permissions = yes',
        '   inherit acls = yes',
        '   map acl inherit = yes',
        '   store dos attributes = yes',
    ]
    if force_group:
        lines.append(f'   force group = {force_group}')
    if valid_users:
        lines.append(f'   valid users = {valid_users}')
    if write_list:
        lines.append(f'   write list = {write_list}')
    if admin_users:
        lines.append(f'   admin users = {admin_users}')
    f.write_text('\n'.join(lines) + '\n')
    t = run(['testparm','-s'], timeout=30)
    if not t['ok']:
        return {'ok': False, 'error': 'testparm failed', 'details': t}
    sudo_run(['systemctl','reload','smbd.service'], password=password, timeout=20)
    return {'ok': True, 'file': str(f)}

def delete_share(name, password=''):
    f = share_file(name)
    if f.exists():
        backup_file(f)
        f.unlink()
    sudo_run(['systemctl','reload','smbd.service'], password=password, timeout=20)
    return {'ok': True}

def import_legacy_share(name, password=''):
    all_shares = {s['name']: s for s in list_all_shares()}
    if name not in all_shares:
        return {'ok': False, 'error': 'Freigabe nicht gefunden'}
    s = all_shares[name]
    c = s['config']
    return write_share(
        s['name'], c.get('path',''), c.get('comment',''),
        c.get('browseable','yes').lower() != 'no',
        c.get('guest ok','no').lower() == 'yes',
        c.get('force group',''), c.get('valid users',''), c.get('write list',''), c.get('admin users',''), password=password)
