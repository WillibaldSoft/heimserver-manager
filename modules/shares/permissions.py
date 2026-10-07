from ui_translation import html_literal as _ui_html, text as _ui_text
# -*- coding: utf-8 -*-
from .helpers import RIGHT_LABELS, RIGHT_HELP

def tokens(text):
    return set(str(text or '').split())

def right_from_samba(cfg, token):
    admin=tokens(cfg.get('admin users',''))
    write=tokens(cfg.get('write list',''))
    valid=tokens(cfg.get('valid users',''))
    if token in admin: return 'admin'
    if token in write: return 'write'
    if token in valid: return 'read'
    return 'none'

def build_lists(user_rights, group_rights):
    valid=[]; write=[]; admin=[]
    for user,right in (user_rights or {}).items():
        if right in ('read','write','admin'): valid.append(user)
        if right in ('write','admin'): write.append(user)
        if right == 'admin': admin.append(user)
    for group,right in (group_rights or {}).items():
        token='@'+group
        if right in ('read','write','admin'): valid.append(token)
        if right in ('write','admin'): write.append(token)
        if right == 'admin': admin.append(token)
    return ' '.join(valid), ' '.join(write), ' '.join(admin)

def options(current):
    out=[]
    for k,label in RIGHT_LABELS.items():
        sel=' selected' if current == k else ''
        out.append(f'{_ui_html("<option value='")}{k}{_ui_html("'")}{sel}{_ui_html('>')}{_ui_text(label)}{_ui_html('</option>')}')
    return ''.join(out)

def explain_html():
    body=_ui_html('<table><tr><th>Auswahl</th><th>Was passiert technisch?</th></tr>')
    for k,label in RIGHT_LABELS.items():
        body += f'{_ui_html('<tr><td><b>')}{_ui_text(label)}{_ui_html('</b></td><td>')}{_ui_text(RIGHT_HELP[k])}{_ui_html('</td></tr>')}'
    body += _ui_html('</table>')
    return body
