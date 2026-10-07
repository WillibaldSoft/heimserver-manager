# -*- coding: utf-8 -*-
from .helpers import CLIENT_SCRIPT

def info():
    return {'name':'client-mount-manager-v2.3.4.sh','version':'2.3.4','path':str(CLIENT_SCRIPT),'exists':CLIENT_SCRIPT.exists()}
