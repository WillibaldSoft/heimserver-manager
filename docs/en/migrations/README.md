# Migrations

Status: 2026-07-01_19-51-05

From now on, database changes will be managed traceably via migrations.

## Rules

1. No manual `ALTER TABLE` changes without migration.
2. Each migration gets a running number.
3. Each migration must be idempotent.
4. Each migration documents purpose, affected tables and rollback note.
5. After each migration: py_compile, service restart, Git commit.

## Naming scheme

```text
migrations/0001_initial_schema.sql
migrations/0002_sleep_schedules.sql
migrations/0003_tvheadend_blockers.sql
```

## Current status

The current actual state was imported as:

```text
schema_migrations: 0000_current_state_imported
snapshots/schema_2026-07-01_19-51-05.sql
docs/01_Datenbank.md
```
