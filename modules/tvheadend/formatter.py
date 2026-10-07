# -*- coding: utf-8 -*-
import datetime

LANG_KEYS = ("ger", "deu", "de", "eng", "en")

TIME_KEYS = {
    "start", "stop", "start_real", "stop_real",
    "start_extra", "stop_extra", "create", "created",
    "scheduled_start", "scheduled_stop",
}

def value(v):
    if isinstance(v, dict):
        for key in LANG_KEYS:
            if key in v and v[key]:
                return v[key]
        for item in v.values():
            if item:
                return item
        return ""
    if isinstance(v, list):
        return ", ".join(str(value(x)) for x in v if x)
    return "" if v is None else v

def timestamp(v):
    v = value(v)
    if v in ("", None):
        return ""
    try:
        if isinstance(v, str) and v.isdigit():
            v = int(v)
        if isinstance(v, (int, float)):
            return datetime.datetime.fromtimestamp(int(v)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass
    return str(v)

def duration_seconds(seconds):
    try:
        seconds = int(seconds or 0)
    except Exception:
        seconds = 0
    if seconds <= 0:
        return ""
    m = seconds // 60
    h = m // 60
    m = m % 60
    if h:
        return f"{h} h {m:02d} min"
    return f"{m} min"

def cell(row, key):
    if not isinstance(row, dict):
        return ""
    v = row.get(key, "")
    if key in TIME_KEYS:
        return timestamp(v)
    return value(v)

def first(row, keys):
    for key in keys:
        v = cell(row, key)
        if v:
            return v
    return ""
