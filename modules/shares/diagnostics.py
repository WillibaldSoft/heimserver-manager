# -*- coding: utf-8 -*-
from .helpers import run, sudo_run, service_state

def diagnostics(path=''):
    d={
        'smbd': service_state('smbd.service'),
        'nmbd': service_state('nmbd.service'),
        'nfs': service_state('nfs-server.service'),
        'testparm': run(['testparm','-s'], timeout=30),
        'exportfs': sudo_run(['exportfs','-v'], timeout=30),
    }
    if path:
        d['getfacl'] = sudo_run(['getfacl','-p',path], timeout=20)
    return d
