# -*- coding: utf-8 -*-
import base64
import json
import urllib.parse
import urllib.request

from .config import read_config

class TvheadendError(RuntimeError):
    pass

def _auth_header(cfg):
    user = cfg.get("username", "")
    if not user:
        return {}
    raw = (user + ":" + cfg.get("password", "")).encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}

def request_json(path, params=None, *, method="GET"):
    cfg = read_config()
    base = cfg.get("url", "http://127.0.0.1:9981").rstrip("/")
    url = base + path
    if params and method == "GET":
        url += "?" + urllib.parse.urlencode(params)

    payload = urllib.parse.urlencode(params or {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=payload, headers=_auth_header(cfg), method=method)
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout", "8"))) as response:
            data = response.read()
    except Exception as exc:
        raise TvheadendError(str(exc)) from exc

    try:
        return json.loads(data.decode("utf-8", "replace"))
    except Exception as exc:
        raise TvheadendError("Antwort ist kein JSON") from exc

def entries(obj):
    if isinstance(obj, dict):
        for key in ("entries", "grid"):
            if isinstance(obj.get(key), list):
                return obj[key]
    if isinstance(obj, list):
        return obj
    return []

def serverinfo():
    return request_json("/api/serverinfo")

def connections():
    return entries(request_json("/api/status/connections"))

def subscriptions():
    return entries(request_json("/api/status/subscriptions"))

def recordings(kind="grid_upcoming", limit=100):
    return entries(request_json("/api/dvr/entry/" + kind, {"start": 0, "limit": limit}))

def epg(query="", limit=100):
    params = {"start": 0, "limit": limit}
    if query:
        params["title"] = query
    return entries(request_json("/api/epg/events/grid", params))
