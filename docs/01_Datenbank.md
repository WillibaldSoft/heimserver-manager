# Datenbankdokumentation

Stand: 2026-07-01_19-51-05

DB: `/var/lib/server-manager/server-manager.sqlite3`

## Tabelle `client_agents`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `name` | `TEXT` | 0 | `None` | 0 |
| `hostname` | `TEXT` | 0 | `None` | 0 |
| `ip` | `TEXT` | 0 | `None` | 0 |
| `mac` | `TEXT` | 0 | `None` | 0 |
| `token` | `TEXT` | 0 | `None` | 0 |
| `mode` | `TEXT` | 0 | `'auto'` | 0 |
| `version` | `TEXT` | 0 | `None` | 0 |
| `enabled` | `INTEGER` | 0 | `1` | 0 |
| `is_online` | `INTEGER` | 0 | `0` | 0 |
| `server_required` | `INTEGER` | 0 | `0` | 0 |
| `last_seen` | `TEXT` | 0 | `None` | 0 |
| `online_since` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `require_reason` | `TEXT` | 0 | `None` | 0 |
| `required_since` | `TEXT` | 0 | `None` | 0 |
| `last_required_seen` | `TEXT` | 0 | `None` | 0 |
| `home_client_id` | `INTEGER` | 0 | `None` | 0 |

Datensätze: **1**

## Tabelle `home_clients`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `name` | `TEXT` | 0 | `None` | 0 |
| `hostname` | `TEXT` | 0 | `None` | 0 |
| `ip` | `TEXT` | 0 | `None` | 0 |
| `mac` | `TEXT` | 0 | `None` | 0 |
| `device_type` | `TEXT` | 0 | `None` | 0 |
| `vendor` | `TEXT` | 0 | `None` | 0 |
| `is_online` | `INTEGER` | 0 | `0` | 0 |
| `last_seen` | `TEXT` | 0 | `None` | 0 |
| `first_seen` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `source` | `TEXT` | 0 | `None` | 0 |

Datensätze: **22**

## Tabelle `meta`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `None` | 0 |

Datensätze: **2**

## Tabelle `module_registry`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `name` | `TEXT` | 0 | `None` | 1 |
| `status` | `TEXT` | 0 | `None` | 0 |
| `message` | `TEXT` | 0 | `None` | 0 |
| `loaded_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **4**

## Tabelle `presence_events`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `client_id` | `INTEGER` | 0 | `None` | 0 |
| `event` | `TEXT` | 0 | `None` | 0 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `ts` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |

Datensätze: **0**

## Tabelle `schema_migrations`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `name` | `TEXT` | 1 | `None` | 0 |
| `applied_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `checksum` | `TEXT` | 0 | `None` | 0 |

Datensätze: **1**

## Tabelle `server_control_actions`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `action` | `TEXT` | 1 | `None` | 0 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `result` | `TEXT` | 0 | `None` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **0**

## Tabelle `server_control_blockers`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `source` | `TEXT` | 1 | `None` | 0 |
| `name` | `TEXT` | 1 | `None` | 0 |
| `reason` | `TEXT` | 0 | `None` | 0 |
| `active` | `INTEGER` | 0 | `1` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **38**

## Tabelle `server_control_rtc_events`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `title` | `TEXT` | 0 | `None` | 0 |
| `wake_time` | `TEXT` | 0 | `None` | 0 |
| `target_time` | `TEXT` | 0 | `None` | 0 |
| `status` | `TEXT` | 0 | `'planned'` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **3**

## Tabelle `server_control_schedules`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `name` | `TEXT` | 1 | `None` | 0 |
| `enabled` | `INTEGER` | 0 | `1` | 0 |
| `type` | `TEXT` | 0 | `'keep-awake'` | 0 |
| `days` | `TEXT` | 0 | `None` | 0 |
| `start_time` | `TEXT` | 0 | `None` | 0 |
| `end_time` | `TEXT` | 0 | `None` | 0 |
| `action` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **0**

## Tabelle `server_control_status`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **2**

## Tabelle `sleep_engine_actions`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `action` | `TEXT` | 1 | `None` | 0 |
| `mode` | `TEXT` | 0 | `None` | 0 |
| `allowed` | `INTEGER` | 0 | `None` | 0 |
| `result` | `TEXT` | 0 | `None` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **3**

## Tabelle `sleep_engine_schedules`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `name` | `TEXT` | 0 | `None` | 0 |
| `enabled` | `INTEGER` | 0 | `1` | 0 |
| `start_time` | `TEXT` | 1 | `None` | 0 |
| `end_time` | `TEXT` | 1 | `None` | 0 |
| `action` | `TEXT` | 1 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `days` | `TEXT` | 0 | `'mon,tue,wed,thu,fri,sat,sun'` | 0 |
| `priority` | `INTEGER` | 0 | `100` | 0 |

Datensätze: **2**

## Tabelle `sleep_engine_settings`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **0**

## Tabelle `tvheadend_events`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `event_type` | `TEXT` | 0 | `None` | 0 |
| `title` | `TEXT` | 0 | `None` | 0 |
| `channel` | `TEXT` | 0 | `None` | 0 |
| `start_time` | `TEXT` | 0 | `None` | 0 |
| `stop_time` | `TEXT` | 0 | `None` | 0 |
| `status` | `TEXT` | 0 | `None` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **0**

## Tabelle `tvheadend_settings`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **0**

## Tabelle `tvheadend_status`

| Spalte | Typ | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Datensätze: **9**
