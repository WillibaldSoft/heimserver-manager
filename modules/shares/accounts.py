# -*- coding: utf-8 -*-
import pwd, grp, subprocess, re
from .helpers import sudo_run, run, sudo_input

def users():
    out=[]
    for u in pwd.getpwall():
        if u.pw_uid >= 1000 and u.pw_name != 'nobody':
            out.append({'name':u.pw_name,'uid':u.pw_uid,'gid':u.pw_gid,'home':u.pw_dir,'shell':u.pw_shell})
    return sorted(out, key=lambda x:x['name'])

def groups():
    out=[]
    for g in grp.getgrall():
        if g.gr_gid >= 1000 or g.gr_name in ('sambashare','users','foto','tv','scanner'):
            out.append({'name':g.gr_name,'gid':g.gr_gid,'members':list(g.gr_mem)})
    return sorted(out, key=lambda x:x['name'])

def user_groups(username):
    res=[]
    try:
        u=pwd.getpwnam(username)
        primary=grp.getgrgid(u.pw_gid).gr_name
        res.append(primary)
    except Exception:
        pass
    for g in grp.getgrall():
        if username in g.gr_mem and g.gr_name not in res:
            res.append(g.gr_name)
    return sorted(res)

def account_name(value):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}[$]?',str(value)):raise ValueError('Kontoname: Kleinbuchstaben, Ziffern, _ und -, beginnend mit einem Buchstaben.')
    return value

def account_password(value):
    if not value or any(c in value for c in ('\n','\r','\0')):raise ValueError('Bitte ein Passwort ohne Zeilenumbrüche eingeben.')
    return value

def numeric_id(value):
    if value in ('',None):return None
    if not re.fullmatch(r'[0-9]{4,5}',str(value)) or not 1000<=int(value)<60000:raise ValueError('UID/GID: 1000 bis 59999 oder leer für automatische Vergabe.')
    return str(int(value))

def create_group(name,password='',gid=''):
    gid=numeric_id(gid)
    return sudo_run(['groupadd',*(['-g',gid] if gid else []),account_name(name)],password=password,timeout=20)

def delete_group(name,password=''):
    return sudo_run(['groupdel',account_name(name)],password=password,timeout=20)

def create_user(name,user_password='',full_name='',shell='/usr/sbin/nologin',home=False,groups_list=None,samba=False,sudo_password='',uid='',primary_group=''):
    name=account_name(name)
    if shell not in ('/bin/bash','/usr/sbin/nologin'):raise ValueError('Ungültige Login-Shell.')
    groups_list=[account_name(g) for g in (groups_list or [])]
    if user_password:account_password(user_password)
    if samba and not user_password:raise ValueError('Für einen Samba-Zugang bitte ein Passwort vergeben.')
    uid=numeric_id(uid)
    if primary_group:grp.getgrnam(account_name(primary_group))
    cmd=['useradd','-s',shell]
    if uid:cmd+=['-u',uid]
    if primary_group:cmd+=['-g',primary_group]
    if home:cmd.append('-m')
    if full_name:cmd+=['-c',full_name]
    if groups_list:cmd+=['-G',','.join(groups_list)]
    result=sudo_run([*cmd,name],password=sudo_password,timeout=20)
    if not result['ok']:return result
    if user_password:
        result=sudo_input(['chpasswd'],name+':'+user_password+'\n',password=sudo_password)
        if not result['ok']:return dict(result,error='Benutzer angelegt, Passwortsetzen fehlgeschlagen. Bitte Passwort separat setzen.')
    if samba:
        result=set_samba_password(name,user_password,sudo_password)
        if not result['ok']:return dict(result,error='Linux-Benutzer angelegt, Samba-Passwortsetzen fehlgeschlagen.')
    return {'ok':True}

def set_user_groups(username,wanted,password=''):
    username=account_name(username);wanted=set(account_name(g) for g in wanted or [])
    current=set(user_groups(username));wanted|=current-{g['name'] for g in groups()};primary=grp.getgrgid(pwd.getpwnam(username).pw_gid).gr_name
    results=[]
    for g in sorted(wanted-current):results.append(sudo_run(['usermod','-aG',g,username],password=password,timeout=20))
    for g in sorted(current-wanted):
        if g not in (primary,username):results.append(sudo_run(['gpasswd','-d',username,g],password=password,timeout=20))
    return {'ok':all(r.get('ok') for r in results),'results':results}

def set_samba_password(username,new_password,sudo_password=''):
    return sudo_input(['smbpasswd','-s','-a',account_name(username)],account_password(new_password)+'\n'+new_password+'\n',password=sudo_password)
