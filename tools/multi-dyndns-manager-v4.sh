#!/bin/sh
# Angepasst aus Multi DynDNS Manager v3.9; gemeinsame Engine mit dem Webmodul.
set -eu
exec /usr/bin/python3 /opt/server-manager/modules/dyndns/engine.py "$@"
