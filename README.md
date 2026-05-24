# Harry Potter and the Chamber of Secrets (PC) Archipelago tracker

PopTracker pack for the HP2PC Archipelago world, with autotracking via the AP server connection.

Supports both `vanilla` and `open_castle` game modes; mode and category toggles are read from `slot_data` on connect, so the tracker reconfigures itself per seed.

## Status

Schema and logic are in place. Map images and pin coordinates are still being filled in.

## Regenerating

The bulk JSON/Lua (items, locations, autotracking mappings, access rules) is generated from the HP2PC_AP world definition. After the apworld changes, regenerate with:

```
py -3.12 tools/generate.py
```

It expects to be run from this folder with the `HP2PC_AP/apworld` package importable via `../HP2PC_AP`.
