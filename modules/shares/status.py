# -*- coding: utf-8 -*-
from .samba import list_all_shares
from .nfs import list_exports
from .accounts import users, groups
from .helpers import service_state
from .client import info as client_info

def status():
    smb=list_all_shares(); nfs=list_exports()
    return {'ok':True,'smbd':service_state('smbd.service'),'nfs':service_state('nfs-server.service'),'samba_shares':smb,'nfs_exports':nfs,'users':users(),'groups':groups(),'client_script':client_info()}
