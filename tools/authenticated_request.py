#!/usr/bin/env python3
"""Root-owned timer client; never place the machine credential in argv or logs."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib import request,parse,error

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):return None

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=('backup','update-check'))
    parser.add_argument('--app');parser.add_argument('--profile',default='system')
    parser.add_argument('--port',type=int,default=int(os.environ.get('SERVER_MANAGER_PORT','9877')))
    args=parser.parse_args()
    try:
        from .server_port import configured_port
    except ImportError:
        from server_port import configured_port
    args.port=configured_port(args.port)
    if not 1<=args.port<=65535:parser.error('Ungültiger Port')
    if args.action=='backup':
        if not re.fullmatch(r'[a-z0-9_]+',args.app or '') or not re.fullmatch(r'[a-z0-9_-]+',args.profile):parser.error('Ungültige App oder Profil')
        path='/apps/'+args.app+'/backup';data=parse.urlencode({'profile':args.profile}).encode()
    else:path='/apps/update-check/run-all';data=b''
    account=Path(os.environ.get('SERVER_MANAGER_CONFIG','/etc/server-manager'))/'authentication.json'
    try:
        token=json.loads(account.read_text())['automation_token']
        req=request.Request('http://127.0.0.1:'+str(args.port)+path,data=data,
                            headers={'X-Server-Manager-Automation':token,'Content-Type':'application/x-www-form-urlencoded'},method='POST')
        opener=request.build_opener(request.ProxyHandler({}),NoRedirect())
        try:
            with opener.open(req,timeout=60) as response:status=response.status
        except error.HTTPError as exc:
            location=exc.headers.get('Location','')
            if exc.code not in (302,303) or not location.startswith('/apps') or location.startswith('//'):raise
            status=exc.code
        print('Server-Manager-Auftrag angenommen; HTTP',status)
        return 0
    except (OSError,ValueError,KeyError,error.URLError) as exc:
        # Do not print request headers or configuration contents.
        print('Server-Manager-Aufruf fehlgeschlagen:',type(exc).__name__)
        return 1

if __name__=='__main__':raise SystemExit(main())
