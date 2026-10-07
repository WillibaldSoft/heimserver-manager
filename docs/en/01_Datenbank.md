# Database documentation

Status: 2026-07-01_19-51-05

DB: `/var/lib/server-manager/server-manager.sqlite3`

## Table `client_agents`

| Column | Type | NOT NULL | Default | PK |
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

Records: **1**

## Table `home_clients`

| Column | Type | NOT NULL | Default | PK |
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

Records: **22**

## Table `meta`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `None` | 0 |

Records: **2**

## Table `module_registry`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `name` | `TEXT` | 0 | `None` | 1 |
| `status` | `TEXT` | 0 | `None` | 0 |
| `message` | `TEXT` | 0 | `None` | 0 |
| `loaded_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **4**

## Table `presence_events`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `client_id` | `INTEGER` | 0 | `None` | 0 |
| `event` | `TEXT` | 0 | `None` | 0 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `ts` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |

Records: **0**

## Table `schema_migrations`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `name` | `TEXT` | 1 | `None` | 0 |
| `applied_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `checksum` | `TEXT` | 0 | `None` | 0 |

Records: **1**

## Table `server_control_actions`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `action` | `TEXT` | 1 | `None` | 0 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `result` | `TEXT` | 0 | `None` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **0**

## Table `server_control_blockers`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `source` | `TEXT` | 1 | `None` | 0 |
| `name` | `TEXT` | 1 | `None` | 0 |
| `reason` | `TEXT` | 0 | `None` | 0 |
| `active` | `INTEGER` | 0 | `1` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **38**

## Table `server_control_rtc_events`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `source` | `TEXT` | 0 | `None` | 0 |
| `title` | `TEXT` | 0 | `None` | 0 |
| `wake_time` | `TEXT` | 0 | `None` | 0 |
| `target_time` | `TEXT` | 0 | `None` | 0 |
| `status` | `TEXT` | 0 | `'planned'` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **3**

## Table `server_control_schedules`

| Column | Type | NOT NULL | Default | PK |
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

Records: **0**

## Table `server_control_status`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **2**

## Table `sleep_engine_actions`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `id` | `INTEGER` | 0 | `None` | 1 |
| `action` | `TEXT` | 1 | `None` | 0 |
| `mode` | `TEXT` | 0 | `None` | 0 |
| `allowed` | `INTEGER` | 0 | `None` | 0 |
| `result` | `TEXT` | 0 | `None` | 0 |
| `details` | `TEXT` | 0 | `None` | 0 |
| `created_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **3**

## Table `sleep_engine_schedules`

| Column | Type | NOT NULL | Default | PK |
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

Records: **2**

## Table `sleep_engine_settings`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **0**

## Table `tvheadend_events`

| Column | Type | NOT NULL | Default | PK |
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

Records: **0**

## Table `tvheadend_settings`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **0**

## Table `tvheadend_status`

| Column | Type | NOT NULL | Default | PK |
|---|---:|---:|---|---:|
| `key` | `TEXT` | 0 | `None` | 1 |
| `value` | `TEXT` | 0 | `None` | 0 |
| `updated_at` | `TEXT` | 0 | `datetime('now','localtime')` | 0 |

Records: **9**
