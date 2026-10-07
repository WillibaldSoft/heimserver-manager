# Core Plugin Loader

## Ziel

Ab Core wird `app.py` nicht mehr für neue Funktionen gepatcht.

Neue Funktionen werden als Module unter `/opt/server-manager/modules/` abgelegt und beim Start automatisch geladen.

## Unterstützte Pluginformen

### Einzeldatei

```text
modules/example.py
```

mit:

```python
def register(app, ctx):
    @app.route("/example")
    def example():
        return ctx.page("Example", "OK", "Example")
```

### Paket

```text
modules/server_control/plugin.py
```

mit:

```python
def register(app, ctx):
    ...
```

## Kontextobjekt `ctx`

Das Plugin erhält:

- `ctx.db`
- `ctx.page`
- `ctx.card`
- `ctx.esc`
- `ctx.now`
- `ctx.init_db`
- `ctx.version`
- `ctx.branch`
- `ctx.base_dir`
- `ctx.state_dir`
- `ctx.db_path`

## Modulstatus

Geladene Module werden in der DB-Tabelle `module_registry` protokolliert.

Webseite:

```text
/modules
```

## Regel ab Core

Keine neuen Textpatches an `app.py`.

Stattdessen:

1. Moduldatei schreiben.
2. Optional Plugin `register(app, ctx)` bereitstellen.
3. Service neustarten.
4. Modulstatus unter `/modules` prüfen.
