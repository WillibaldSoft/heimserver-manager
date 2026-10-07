# Core Plugin Loader

## Goal

Starting with Core, new features are no longer patched into `app.py`.

New functions are stored as modules under `/opt/server-manager/modules/` and automatically loaded at startup.

## Supported Plugin Forms

### Single File

```text
modules/example.py
```

with:

```python
def register(app, ctx):
    @app.route("/example")
    def example():
        return ctx.page("Example", "OK", "Example")
```

### Package

```text
modules/server_control/plugin.py
```

with:

```python
def register(app, ctx):
    ...
```

## Context Object `ctx`

The plugin receives:

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

## Module Status

Loaded modules are logged in the database table `module_registry`.

Website:

```text
/modules
```

## Rule from core

No new text patches to `app.py`.

Instead:

1. Write the module file.
2. Optionally provide plugin `register(app, ctx)`.
3. Restart the service.
4. Check the module status under `/modules`.
