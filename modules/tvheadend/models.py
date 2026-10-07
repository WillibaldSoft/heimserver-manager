# -*- coding: utf-8 -*-
from . import formatter as fmt

def normalize_recording(row):
    return {
        "title": fmt.first(row, ["title", "disp_title"]),
        "subtitle": fmt.first(row, ["subtitle", "disp_subtitle"]),
        "channel": fmt.first(row, ["channelname", "channel", "channelName"]),
        "start": fmt.first(row, ["start_real", "start"]),
        "stop": fmt.first(row, ["stop_real", "stop"]),
        "status": fmt.first(row, ["status", "sched_status"]),
        "error": fmt.first(row, ["error", "errors"]),
        "raw": row,
    }

def normalize_stream(row):
    return {
        "user": fmt.first(row, ["user", "username"]),
        "peer": fmt.first(row, ["peer", "ip"]),
        "server": fmt.first(row, ["server"]),
        "started": fmt.first(row, ["started", "start"]),
        "title": fmt.first(row, ["title"]),
        "channel": fmt.first(row, ["channel", "channelname", "channelName"]),
        "state": fmt.first(row, ["state", "status"]),
        "error": fmt.first(row, ["error"]),
        "raw": row,
    }

def normalize_epg(row):
    return {
        "title": fmt.first(row, ["title"]),
        "subtitle": fmt.first(row, ["subtitle"]),
        "channel": fmt.first(row, ["channelName", "channelname", "channel"]),
        "start": fmt.first(row, ["start"]),
        "stop": fmt.first(row, ["stop"]),
        "description": fmt.first(row, ["description", "summary"]),
        "raw": row,
    }


def is_epg_grabber(row):
    """Only the internal epggrab subscription is excluded from sleep demand."""
    return str(row.get("title") or "").strip().casefold() == "epggrab"
