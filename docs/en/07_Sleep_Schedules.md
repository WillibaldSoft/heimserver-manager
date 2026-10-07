# Extended Sleep Schedules

## Extensions

- Days of the week selectable
- Multiple time windows per day
- Priority
- Overlapping rules

## Priority

Lower numbers win.

Example:

```text
Mo–So 08:00–23:00 Wach halten, Priorität 100
Mo–Fr 13:00–14:00 Suspend, Priorität 10
```

The second rule overrides the first during 13:00–14:00.

## Note

This phase extends WebUI and table.
Automatic evaluation follows in the Sleep Policy.
