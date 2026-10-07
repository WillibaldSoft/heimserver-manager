#!/usr/bin/env python3
"""Package bootstrap and private certificate renewal, run as root."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.web_security import manager_https

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--bootstrap',action='store_true');group.add_argument('--renew',action='store_true')
    parser.add_argument('--https-port',type=int,default=443);parser.add_argument('--ip-port',type=int,default=8443)
    args=parser.parse_args()
    if args.bootstrap:manager_https.bootstrap(args.https_port,args.ip_port)
    else:manager_https.renew()
