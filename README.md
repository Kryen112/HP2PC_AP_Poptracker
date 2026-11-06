# Harry Potter and the Chamber of Secrets (PC) Archipelago Tracker

Harry Potter and the Chamber of Secrets (PC) Archipelago tracker pack for [PopTracker](https://github.com/black-sliver/PopTracker/) with Autotracking.

Requires PopTracker v0.31.0 or higher.

- Autotracks items, checks, and goal progress live over the AP server connection. Automatically follows Harry around the castle, showing the map he is currently in.
- Per-floor maps (castle hubs, levels, and spell challenges) with a pin for every check.
- Supports both `vanilla` and `open_castle` game modes. The mode and every category toggle (wizard cards, secrets, challenge stars, containers, Quidditch upgrades and matches, duelling, spell-challenge times, tradersanity, traps, ring and death link) are read from `slot_data` on connect, so the tracker sets itself up for each seed.

## Installing

Download the zip from this repo's [releases](https://github.com/Kryen112/HP2PC_AP_Poptracker/releases) and put it, still zipped, in PopTracker's `packs` folder. Connect to the same room as your HP2 PC Client.

The randomizer itself lives at [HP2PC_AP](https://github.com/Kryen112/HP2PC_AP).

## Development

The items, locations, autotracking tables and access rules are generated from the HP2PC_AP world definition, not edited by hand. The map pins and `maps/maps.json` are placed by hand.
