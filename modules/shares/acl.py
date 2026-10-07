# -*- coding: utf-8 -*-
from .helpers import sudo_run

def get_acl(path):
    return sudo_run(['getfacl','-p',path], timeout=20)

def perm_for(right):
    if right == 'read': return 'r-x'
    if right in ('write','admin'): return 'rwx'
    return ''

def apply_acl(path, user_rights, group_rights, default_acl=True, recursive=False, password=''):
    cmds=[]
    rec=['-R'] if recursive else []
    for user,right in (user_rights or {}).items():
        if right == 'none':
            cmds.append(['setfacl']+rec+['-x',f'u:{user}',path])
            if default_acl: cmds.append(['setfacl','-d','-x',f'u:{user}',path])
        else:
            p=perm_for(right)
            cmds.append(['setfacl']+rec+['-m',f'u:{user}:{p}',path])
            if default_acl: cmds.append(['setfacl','-d','-m',f'u:{user}:{p}',path])
    for group,right in (group_rights or {}).items():
        if right == 'none':
            cmds.append(['setfacl']+rec+['-x',f'g:{group}',path])
            if default_acl: cmds.append(['setfacl','-d','-x',f'g:{group}',path])
        else:
            p=perm_for(right)
            cmds.append(['setfacl']+rec+['-m',f'g:{group}:{p}',path])
            if default_acl: cmds.append(['setfacl','-d','-m',f'g:{group}:{p}',path])
    results=[sudo_run(c, password=password, timeout=60) for c in cmds]
    return {'ok': all(r.get('ok') for r in results) if results else True, 'results': results}
