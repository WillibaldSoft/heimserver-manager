#!/usr/bin/python3
"""Open the configured HTTPS frontend; never expose or advertise the backend."""
from pathlib import Path
from urllib.parse import urlsplit
import webbrowser,socket,re
URL=Path('/usr/share/server-manager/desktop-url')
def main():
    try:value=URL.read_text().strip()
    except OSError:
        name=re.sub('[^a-z0-9-]','-',socket.gethostname().split('.')[0].lower()).strip('-') or 'heimserver'
        value='https://'+name
    try:
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or any(c.isspace() for c in value):raise ValueError()
        if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError()
    except ValueError:raise SystemExit('Ungültige Manager-HTTPS-Adresse.') from None
    if not webbrowser.open(value):raise SystemExit('Kein Browser gefunden. Manager über HTTPS öffnen.')
if __name__=='__main__':main()
