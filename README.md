# Harry Potter and the Chamber of Secrets (PC) Archipelago Tracker

Harry Potter and the Chamber of Secrets (PC) Archipelago tracker pack for [PopTracker](https://github.com/black-sliver/PopTracker/) with Autotracking.

Requires PopTracker v0.31.0 or higher.

- Autotracks items, checks, and goal progress live over the AP server connection. Automatically follows Harry around the castle, showing the map he is currently in.
- Per-floor maps (castle hubs, levels, and spell challenges) with a pin for every check.
- Supports both `vanilla` and `open_castle` game modes. The mode and every category toggle (wizard cards, secrets, challenge stars, Quidditch upgrades/matches, duelling, spell-challenge times, tradersanity, traps, ring/death link) are read from `slot_data` on connect, so the tracker reconfigures itself per seed.

## Development

The bulk pack data — `items/items.json`, `locations/<Region>.json`, the `scripts/autotracking/*_mapping.lua` tables, and `scripts/logic/access_rules.lua` — is generated from the HP2PC_AP world definition rather than edited by hand. After the apworld changes, regenerate from the pack root (with the `HP2PC_AP/apworld` package available at `../HP2PC_AP`):

    py -3.12 tools/generate.py

It carries hand-placed map-pin coordinates forward across runs and leaves the hand-tuned `maps/maps.json` alone. Item icons are built from the game's own textures with `tools/make_icons.py`, and `tools/release.py` packages and publishes a release (see its module docstring).
