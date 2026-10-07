# Migrationen

Stand: 2026-07-01_19-51-05

Ab jetzt werden Datenbankänderungen nachvollziehbar über Migrationen verwaltet.

## Regeln

1. Keine manuellen `ALTER TABLE` Änderungen ohne Migration.
2. Jede Migration bekommt eine laufende Nummer.
3. Jede Migration muss idempotent sein.
4. Jede Migration dokumentiert Zweck, betroffene Tabellen und Rollback-Hinweis.
5. Nach jeder Migration: py_compile, Service-Neustart, Git-Commit.

## Namensschema

```text
migrations/0001_initial_schema.sql
migrations/0002_sleep_schedules.sql
migrations/0003_tvheadend_blockers.sql
```

## Aktueller Stand

Der aktuelle Ist-Zustand wurde importiert als:

```text
schema_migrations: 0000_current_state_imported
snapshots/schema_2026-07-01_19-51-05.sql
docs/01_Datenbank.md
```
