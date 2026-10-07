# -*- coding: utf-8 -*-
import time

_cache = {}

def get(key, ttl, loader):
    now = time.time()
    item = _cache.get(key)
    if item and now - item["time"] <= ttl:
        return item["value"]
    value = loader()
    _cache[key] = {"time": now, "value": value}
    return value

def clear():
    _cache.clear()
