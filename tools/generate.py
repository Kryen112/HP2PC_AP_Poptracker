"""Regenerate the bulk PopTracker pack files from the HP2PC_AP world.

Reads ../HP2PC_AP/apworld/{items,locations,regions,rules}.py (plus the
post-ending chest exclusion set from __init__.py) and emits:
    items/items.json
    locations/<Region>.json   (one per region)
    maps/maps.json            (only if missing — otherwise leaves Stefan's
                               hand-tuned floor map layout alone)
    scripts/locations_import.lua
    scripts/autotracking/item_mapping.lua
    scripts/autotracking/location_mapping.lua
    scripts/autotracking/setting_mapping.lua
    scripts/logic/access_rules.lua

Pure-AST: never imports the apworld package (it pulls in BaseClasses /
ItemClassification / AutoWorld, which only resolve inside an Archipelago
checkout). The rule values in regions.py / rules.py are the access.py _Access
DSL (predicate names combined with & and |, plus never / always / _silver_cards),
a small regular grammar that ast parses directly.

Run from the pack root:
    py -3.12 tools/generate.py
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACK = HERE.parent
APWORLD = PACK.parent / "HP2PC_AP" / "apworld"

# Placeholder chest art every emitted location/group node carries. One source so
# a renamed image or a typo can't drift across the node builders.
CHEST_IMGS = {
    "chest_unopened_img": "images/items/item.png",
    "chest_opened_img": "images/items/item_opened.png",
}

REGION_DISPLAY = {
    "BeanBonusRoom": "Bean Bonus Room",
    "BicornLevel": "Bicorn Level",
    "BoomslangLevel": "Boomslang Level",
    "CastleExterior": "Castle Exterior",
    "ChamberOfSecrets": "Chamber of Secrets",
    "DiffindoChallenge": "Diffindo Challenge",
    "DuellingClub": "Duelling Club",
    "DumbledoreStudy": "Dumbledore's Study",
    "EntryHall": "Entry Hall",
    "ForbiddenForest": "Forbidden Forest",
    "GoldCardRoom": "Gold Card Room",
    "GoyleLevel": "Goyle Level",
    "GrandStaircase": "Grand Staircase",
    "GryffindorChallenge": "Gryffindor Challenge",
    "Quidditch": "Quidditch",
    "RictusempraChallenge": "Rictusempra Challenge",
    "SkurgeChallenge": "Skurge Challenge",
    "SlytherinCommon": "Slytherin Common Room",
    "SpongifyChallenge": "Spongify Challenge",
    "WhompingWillow": "Whomping Willow",
    "Menu": "Menu",
}

# Region → map name for the pins, when it differs from the region's own
# display name. These regions keep their own section names but physically sit
# inside another area, so their pins are placed on that area's map image.
REGION_MAP_OVERRIDE = {
    "DumbledoreStudy": "Grand Staircase",
    "DuellingClub": "Entry Hall",
    "Quidditch": "Castle Exterior",
}

# Regions with no map of their own, listed as real nodes inside a host region's
# file instead of as their own top-level group + file. Their checks pin on the
# host's map (via REGION_MAP_OVERRIDE) and their section path becomes
# @HostDisplay/<node>/<section>, so location_mapping uses the host as the first
# segment. No separate <Region>.json or locations_import line is emitted.
REGION_FOLD_INTO = {
    "Quidditch": "CastleExterior",
    "DuellingClub": "EntryHall",
    "DumbledoreStudy": "GrandStaircase",
}

# "Menu room" pins: a host region's map carries one aggregate pin per source
# region, each listing all that region's checks via section refs. The pin
# shares state with the region's own map while letting players reach a room's
# whole check list from the hub map it branches off. Keyed by host region.
MENU_ROOMS = {
    "GrandStaircase": ("Staircase Rooms", ["ChamberOfSecrets", "GoldCardRoom"]),
    "CastleExterior": ("Castle Exterior Rooms", [
        "DiffindoChallenge", "ForbiddenForest", "BoomslangLevel", "WhompingWillow",
    ]),
    "EntryHall": ("Entry Hall Rooms", [
        "RictusempraChallenge", "SpongifyChallenge", "SkurgeChallenge",
        "BicornLevel", "GoyleLevel", "SlytherinCommon", "GryffindorChallenge",
        "BeanBonusRoom",
    ]),
}

# Checks that share one map pixel: emitted as multiple sections under a single
# shared location node (one marker, popup lists each), instead of separate
# overlapping nodes. Keyed by region → list of (group node name, [section
# names]). The section path becomes @Region/<group>/<section>, so anything
# referencing those sections (location_mapping, menu refs, goal_mapping.lua)
# must use the group as the middle segment.
COLOCATION = {
    "GrandStaircase": [
        ("Secret 4 & Card Maeve", ["Secret 4", "Card Maeve"]),
        ("Secret 5 & Card Oldridge", ["Secret 5", "Card Oldridge"]),
        ("Secret 6 & Card Lufkin", ["Secret 6", "Card Lufkin"]),
    ],
    "EntryHall": [
        ("Secret 3 & Card Wendelin", ["Secret 3", "Card Wendelin"]),
        ("Secret 9 & Card Jones", ["Secret 9", "Card Jones"]),
    ],
    "CastleExterior": [
        ("Secret 1 & Card Twonk", ["Secret 1", "Card Twonk"]),
        ("Secret 4 & Card Oglethorpe", ["Secret 4", "Card Oglethorpe"]),
        ("Secret 5 & Card Sykes", ["Secret 5", "Card Sykes"]),
        ("Secret 7 & Card Marjoribanks", ["Secret 7", "Card Marjoribanks"]),
        ("Secret 8 & Card Wadcock", ["Secret 8", "Card Wadcock"]),
        ("Nimbus 2001 & Quidditch Armour", ["Nimbus 2001", "Quidditch Armour"]),
    ],
    "SlytherinCommon": [
        ("Secret 5 & Card Pilliwickle", ["Secret 5", "Card Pilliwickle"]),
        ("Secret 7 & Card Fay", ["Secret 7", "Card Fay"]),
        ("Secret 6 & Card Platt", ["Secret 6", "Card Platt"]),
    ],
    "ForbiddenForest": [
        ("Secret 4 & Card Scamander", ["Secret 4", "Card Scamander"]),
    ],
    "RictusempraChallenge": [
        ("Completion", ["Complete", "Beat Par Time"]),
        ("Secret 2 & Challenge Star 5", ["Secret 2", "Challenge Star 5"]),
        ("Secret 3 & Card Crumb", ["Secret 3", "Card Crumb"]),
        ("Secret 6 & Card Duke", ["Secret 6", "Card Duke"]),
    ],
    "SkurgeChallenge": [("Completion", ["Complete", "Beat Par Time"])],
    "SpongifyChallenge": [
        ("Completion", ["Complete", "Beat Par Time"]),
        ("Secret 2 & Card Rastrick", ["Secret 2", "Card Rastrick"]),
        ("Secret 1 & Card Merlin", ["Secret 1", "Card Merlin"]),
        ("Secret 4 & Challenge Star 2", ["Secret 4", "Challenge Star 2"]),
        ("Secret 9 & Challenge Star 6", ["Secret 9", "Challenge Star 6"]),
        ("Secret 8 & Card Summerbee", ["Secret 8", "Card Summerbee"]),
        ("Secret 6 & Card Furmage", ["Secret 6", "Card Furmage"]),
        ("Secret 5 & Card Po", ["Secret 5", "Card Po"]),
        ("Secret 10 & Card Grunnion", ["Secret 10", "Card Grunnion"]),
        ("Secret 15 & Card Woodcroft", ["Secret 15", "Card Woodcroft"]),
    ],
    "DiffindoChallenge": [
        ("Completion", ["Complete", "Beat Par Time"]),
        ("Secret 4 & Challenge Stars 6 & 7", ["Secret 4", "Challenge Star 6", "Challenge Star 7"]),
        ("Secret 6 & Card Shimpling", ["Secret 6", "Card Shimpling"]),
        ("Secret 8 & Star 11", ["Secret 8", "Challenge Star 11"]),
    ],
    "Quidditch": [("Quidditch Matches", [
        "Match 1 (Hufflepuff)", "Match 2 (Ravenclaw)", "Match 3 (Slytherin)",
        "Match 4 (Hufflepuff)", "Match 5 (Ravenclaw)", "Match 6 (Slytherin)",
    ])],
    "DuellingClub": [("Duels", [
        "Duel Rank 1", "Duel Rank 2", "Duel Rank 3", "Duel Rank 4", "Duel Rank 5",
        "Duel Rank 6", "Duel Rank 7", "Duel Rank 8", "Duel Rank 9", "Duel Rank 10",
    ])],
}


def colocation_parent(region: str, section_name: str) -> str:
    """The location-node name holding this section: its colocation group, or
    the section's own name when it stands alone."""
    for group_name, members in COLOCATION.get(region, []):
        if section_name in members:
            return group_name
    return section_name


# Map LOCATION_GROUPS group → tracker visibility helper from logic.lua.
# Groups not listed here are always visible.
GROUP_TO_VIS = {
    "CardLocations": "$visCards",
    "Secrets": "$visSecrets",
    "ChallengeStars": "$visStars",
    "QuidditchPurchases": "$visQuidPurch",
    "Duels": "$visDuels",
    "QuidditchMatches": "$visQuidMatch",
    "SpellChallengeTimes": "$visSpellTimes",
    "Tradersanity": "$visTraders",
    "Containers": "$visContainers",
    # "Classrooms" / "LevelCompletions" handled below by mode rather than group.
}

# Map item classification (string from ITEM_CLASSIFICATIONS) → image path.
# Stefan provides the PNGs at these paths; the pack still loads without them.
CLASS_TO_IMG_DIR = {
    "spell": "images/items/spells",
    "key": "images/items/keys",
    "equip": "images/items/equipment",
    "card_bronze": "images/items/cards",
    "card_silver": "images/items/cards",
    "card_gold": "images/items/cards",
    "filler": "images/items/filler",
    "trap": "images/items/traps",
}


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def _eval_literal(node):
    """Evaluate AST literal nodes (Constant/List/Tuple/Set/Dict/Call(frozenset))
    into Python values. Used for the data dicts in items.py / locations.py."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_literal(e) for e in node.elts]
    if isinstance(node, ast.Set):
        return {_eval_literal(e) for e in node.elts}
    if isinstance(node, ast.Dict):
        return {_eval_literal(k): _eval_literal(v) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.Attribute):
        # ItemClassification.progression  →  "progression"
        return node.attr
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset":
        if not node.args:
            return frozenset()
        return frozenset(_eval_literal(node.args[0]))
    if isinstance(node, ast.Name):
        return node.id  # e.g. an enum unqualified
    raise ValueError(f"unhandled literal node: {ast.dump(node)}")


def load_assignments(path: Path) -> dict[str, object]:
    """Return all module-level `NAME = expr` assignments in a file, with
    literal expressions evaluated. Skips assignments whose RHS isn't a
    literal we know how to evaluate."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, object] = {}
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        value = stmt.value
        if value is None:
            continue
        for t in targets:
            if not isinstance(t, ast.Name):
                continue
            try:
                out[t.id] = _eval_literal(value)
            except ValueError:
                pass
    return out


def load_rule_dicts(path: Path) -> dict[str, dict[str, ast.AST]]:
    """For rules.py / regions.py: each top-level dict is { 'Name': lambda ... }.
    Returns { dict_name: { key: lambda_body_ast } } — lambdas kept as AST so
    the translator can walk them."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, ast.AST]] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            value = stmt.value
            if not isinstance(value, ast.Dict):
                continue
            for t in targets:
                if not isinstance(t, ast.Name):
                    continue
                d: dict[str, ast.AST] = {}
                for k, v in zip(value.keys, value.values):
                    key = _eval_literal(k) if isinstance(k, ast.Constant) else None
                    if key is None:
                        continue
                    # _Access expression node (Name / BinOp / _silver_cards Call);
                    # a stray lambda body is unwrapped for tolerance.
                    d[key] = v.body if isinstance(v, ast.Lambda) else v
                out[t.id] = d
    return out


def load_int_constants(path: Path) -> dict[str, int]:
    """Top-level `NAME = <int>` assignments, so a rule can reference a named
    count (e.g. _bronze_cards(CHAMBER_FALL_BRONZE_COUNT)) instead of a literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        if (isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, int)):
            for t in targets:
                if isinstance(t, ast.Name):
                    out[t.id] = stmt.value.value
    return out


def load_item_predicates(path: Path) -> dict[str, str]:
    """Parse access.py: `name = _item('Item Name')` to {name: 'Item Name'}. These
    are the boolean predicates the _Access DSL composes with & and |."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        v = stmt.value
        if (isinstance(target, ast.Name) and isinstance(v, ast.Call)
                and isinstance(v.func, ast.Name) and v.func.id == "_item"
                and len(v.args) == 1 and isinstance(v.args[0], ast.Constant)):
            out[target.id] = v.args[0].value
    return out


def load_rule_aliases(path: Path) -> dict[str, ast.AST]:
    """Module-level _Access aliases in rules.py (e.g.
    `chamber_first_fall = spongify | _bronze_cards(20)`): a bare lowercase name
    bound to an _Access expression and reused across rule values. Kept as AST so
    rule_to_lua can inline the body wherever a rule references the name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, ast.AST] = {}
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name) or not target.id.islower():
            continue
        # The UPPER_CASE rule tables (Dict) and any data collections are handled
        # elsewhere; only scalar _Access expressions belong here.
        if isinstance(stmt.value, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
            continue
        out[target.id] = stmt.value
    return out


# ---------------------------------------------------------------------------
# _Access DSL to Lua expression
# ---------------------------------------------------------------------------

# Logic-flag item names. A rule reachable only when one of these is forced on is
# out of logic (SequenceBreak / yellow) rather than unreachable. Running and
# Glitched are player-selected capabilities, always physically possible, so every
# seed can reach these checks regardless of whether the flag is enabled in logic.
FLAG_ITEMS: frozenset[str] = frozenset({"Running", "Glitched"})

# Item-predicate name from access.py (`alohomora = _item('Alohomora')`) to item
# name. Lets the translator turn a bare predicate Name in the _Access DSL into
# has("Item").
ITEM_PREDICATES: dict[str, str] = {}

# Module-level _Access aliases from rules.py (name -> expression AST), inlined by
# rule_to_lua when a rule references the name (e.g. chamber_first_fall).
RULE_ALIASES: dict[str, ast.AST] = {}

# Top-level int constants from rules.py (e.g. CHAMBER_FALL_BRONZE_COUNT), so a
# card-count helper can take a named count instead of a bare literal.
INT_CONSTANTS: dict[str, int] = {}

# Locations the apworld drops as checks in open castle because they sit past
# the ending cutscene's point of no return. Read from __init__.py's
# ENTRY_HALL_POST_ENDING_CHESTS so the tracker hides them in open castle
# instead of showing them reachable. vis_rules_for gates them vanilla-only.
POST_ENDING_CHESTS: frozenset[str] = frozenset()


def _flatten_binop(node, op_type) -> list:
    """Collapse a left-associative chain of the same & / | op into a flat operand
    list, so a & b & c emits (a and b and c) rather than nested parens."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, op_type):
        return _flatten_binop(node.left, op_type) + _flatten_binop(node.right, op_type)
    return [node]


def rule_to_lua(node, force_true: frozenset[str] = frozenset()) -> str:
    # force_true names item predicates (by item name) rendered as the literal
    # `true` instead of has("Item"). Used to build the out-of-logic variant of a
    # rule, where a logic flag (Running / Glitched) is force-allowed.
    # _Access DSL: a bare item predicate, or never / always.
    if isinstance(node, ast.Name):
        if node.id == "never":
            return "false"
        if node.id == "always":
            return "true"
        item = ITEM_PREDICATES.get(node.id)
        if item is not None:
            if item in force_true:
                return "true"
            return f'has("{_lua_escape(item)}")'
        # Module-level _Access alias (e.g. chamber_first_fall): inline its body.
        alias = RULE_ALIASES.get(node.id)
        if alias is not None:
            return rule_to_lua(alias, force_true)
        raise ValueError(f"unknown predicate name: {node.id}")
    # _Access DSL: a & b (and), a | b (or). Flatten same-op chains to one paren.
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.BitAnd):
            parts = _flatten_binop(node, ast.BitAnd)
            return "(" + " and ".join(rule_to_lua(p, force_true) for p in parts) + ")"
        if isinstance(node.op, ast.BitOr):
            parts = _flatten_binop(node, ast.BitOr)
            return "(" + " or ".join(rule_to_lua(p, force_true) for p in parts) + ")"
        raise ValueError(f"unsupported BinOp op: {ast.dump(node.op)}")
    # _Access DSL: _silver_cards(n) / _bronze_cards(n) -> count(tier) >= n. The
    # count is a literal or a named int constant (INT_CONSTANTS) from rules.py.
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("_silver_cards", "_bronze_cards") and len(node.args) == 1):
        arg = node.args[0]
        if isinstance(arg, ast.Constant):
            count = arg.value
        elif isinstance(arg, ast.Name) and arg.id in INT_CONSTANTS:
            count = INT_CONSTANTS[arg.id]
        else:
            raise ValueError(f"unsupported card-count arg: {ast.dump(node)}")
        tier = "silver_cards" if node.func.id == "_silver_cards" else "bronze_cards"
        return f'(count("{tier}") >= {count})'
    raise ValueError(f"unsupported _Access node: {ast.dump(node)}")


def _lua_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Slug + naming
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def slug(s: str) -> str:
    return _SLUG_RE.sub("_", s).strip("_")


def rule_fn_name(loc_name: str) -> str:
    return f"rule_{slug(loc_name)}"


def region_rule_fn_name(region: str) -> str:
    return f"region_{region}"


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

# Setting items injected on top of the AP items. Each one becomes a
# progressive multi-stage item; stage codes are what slot_data mapping
# resolves to, and what the logic helpers in logic.lua test via has().
# "default" is the initial stage index shown before slot_data arrives (the
# autotracker overwrites it on connect). Binary stages are [off=0, on=1];
# game_mode is [vanilla=0, open_castle=1]. Omit to start at stage 0.
SETTING_ITEMS = [
    {
        "name": "Game mode", "key": "game_mode", "default": 1,
        "stages": [
            ("vanilla", "Vanilla"),
            ("open_castle", "Open Castle"),
        ],
    },
    {"name": "Vanilla gate levels", "key": "vanilla_gate_levels", "binary": True, "default": 1},
    {"name": "Enable wizard cards", "key": "enable_wizard_cards", "binary": True, "default": 1},
    {"name": "Enable secrets", "key": "enable_secrets", "binary": True, "default": 1},
    {"name": "Allow missable progression", "key": "allow_missable_progression", "binary": True},
    # Logic-flag toggles. `logic_code` is the bare rule token (state.has("X") ->
    # has("X") in access_rules.lua); it rides only the ON stage's codes so a
    # `... | Running` / `... | Glitched` clause resolves true exactly when the
    # toggle is on. Default off (no `default`), matching the apworld default.
    {"name": "Allow running logic", "key": "allow_running_logic", "binary": True, "logic_code": "Running"},
    {"name": "Allow glitched logic", "key": "allow_glitched_logic", "binary": True, "logic_code": "Glitched"},
    {"name": "Enable challenge stars", "key": "enable_challenge_stars", "binary": True, "default": 1},
    {"name": "Enable Quidditch upgrades", "key": "enable_quidditch_upgrades", "binary": True},
    {"name": "Enable Duelling", "key": "enable_duelling", "binary": True},
    {"name": "Enable Quidditch matches", "key": "enable_quidditch_matches", "binary": True},
    {"name": "Enable spell challenge times", "key": "enable_spell_challenge_times", "binary": True},
    {"name": "Containersanity", "key": "containersanity", "binary": True},
    {"name": "Enable traps", "key": "enable_traps", "binary": True},
    {"name": "Ring Link", "key": "ring_link", "binary": True},
    {"name": "Death Link", "key": "death_link", "binary": True},
    {
        "name": "Tradersanity", "key": "tradersanity",
        "stages": [
            ("off", "Off"),
            ("price_vanilla", "Vanilla price"),
            ("price_random", "Random price"),
            ("price_low", "Low price"),
        ],
    },
]


def _classify_for_img(name: str, groups: dict[str, list[str]]) -> str:
    def in_group(g):
        return name in groups.get(g, [])
    if in_group("Spells"):
        return "spell"
    if in_group("Blocker Keys"):
        return "key"
    if in_group("Equipment"):
        return "equip"
    if in_group("Cards (Bronze)"):
        return "card_bronze"
    if in_group("Cards (Silver)"):
        return "card_silver"
    if in_group("Cards (Gold)"):
        return "card_gold"
    if in_group("Traps"):
        return "trap"
    return "filler"


def build_items_json(items: dict) -> list:
    name_to_id = items["ITEM_NAME_TO_ID"]
    groups = items["ITEM_GROUPS"]
    out = []
    for name in name_to_id:
        kind = _classify_for_img(name, groups)
        img = f"{CLASS_TO_IMG_DIR[kind]}/{slug(name).lower()}.png"
        out.append({
            "name": name,
            "type": "toggle",
            "img": img,
            "codes": name,
        })
    # Per-tier card counters. These consumables aren't in ITEM_MAPPING; the
    # autotracker bumps them by card tier in archipelago.lua's onItem, so the
    # items+settings panel shows how many of each tier have been collected.
    for kind, label, code in (("card_bronze", "Bronze Cards", "bronze_cards"),
                              ("card_silver", "Silver Cards", "silver_cards"),
                              ("card_gold", "Gold Cards", "gold_cards")):
        total = sum(1 for n in name_to_id if _classify_for_img(n, groups) == kind)
        out.append({
            "name": label,
            "type": "consumable",
            "img": f"{CLASS_TO_IMG_DIR[kind]}/{code}.png",
            "codes": code,
            "min_quantity": 0,
            "max_quantity": total,
            "increment": 1,
            "decrement": 1,
        })
    for s in SETTING_ITEMS:
        if s.get("binary"):
            # A logic-flag setting also carries its rule token on the ON stage
            # only, so has("<logic_code>") in access_rules.lua is true exactly
            # when the toggle is on.
            on_codes = f"{s['key']},{s['key']}_on"
            if s.get("logic_code"):
                on_codes += f",{s['logic_code']}"
            stages = [
                {
                    "img": f"images/items/settings/{s['key']}_off.png",
                    "name": f"{s['name']}: off",
                    "codes": f"{s['key']},{s['key']}_off",
                    "inherit_codes": False,
                },
                {
                    "img": f"images/items/settings/{s['key']}_on.png",
                    "name": f"{s['name']}: on",
                    "codes": on_codes,
                    "inherit_codes": False,
                },
            ]
        else:
            stages = [
                {
                    "img": f"images/items/settings/{s['key']}_{stage_key}.png",
                    "name": f"{s['name']}: {stage_label}",
                    "codes": f"{s['key']},{s['key']}_{stage_key}",
                    "inherit_codes": False,
                }
                for stage_key, stage_label in s["stages"]
            ]
        entry = {
            "name": s["name"],
            "type": "progressive",
            "loop": False,
            "allow_disabled": False,
            "codes": s["key"],
            "stages": stages,
        }
        if s.get("default"):
            entry["initial_stage_idx"] = s["default"]
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def loc_section_ref(region_display: str, loc_name: str) -> str:
    short = loc_name
    # Drop the "Region - " prefix for the section/leaf label so it reads
    # naturally on the map ("Card Agrippa" rather than "Bicorn Level - Card Agrippa").
    prefix = region_display + " - "
    if short.startswith(prefix):
        short = short[len(prefix):]
    return short


def vis_rules_for(region: str, loc_name: str, loc_groups: dict[str, str]) -> list[str]:
    """Visibility helpers gating a location's pin, ANDed by PopTracker — the pin
    shows only when every listed helper returns true. A location can be gated by
    both its region (the open-castle-only Gryffindor challenge) and its group
    (cards, secrets, containers, ...), so a Gryffindor container pin carries
    both $visOpenCastleOnly and $visContainers."""
    rules: list[str] = []
    # The Gryffindor challenge level only exists in the open-castle build.
    if region == "GryffindorChallenge":
        rules.append("$visOpenCastleOnly")
    group = loc_groups.get(loc_name)
    if loc_name in POST_ENDING_CHESTS:
        # East-wing chests stranded past the open castle ending; vanilla-only.
        # The helper also folds in the containersanity gate, so this replaces
        # the plain $visContainers these would otherwise carry.
        rules.append("$visEntryHallPostEndingChests")
    elif group == "Classrooms":
        # Classroom (Learned X) checks only exist in vanilla.
        rules.append("$visClassrooms")
    else:
        gv = GROUP_TO_VIS.get(group or "")
        if gv is not None:
            rules.append(gv)
    return rules


def carry_pins(existing_map_locations: dict[str, list], node_name: str,
               map_name: str) -> list:
    """Carry a node's prior pin coordinates forward only while they belong to
    map_name. A section that moved to a different map (e.g. Dumbledore's Study
    pins relocating onto the Grand Staircase image) has meaningless old x/y on
    the new picture, so reset to (0, 0) for re-placing."""
    prior = [ml for ml in (existing_map_locations.get(node_name) or [])
             if ml.get("map") == map_name]
    return prior if prior else [{"map": map_name, "x": 0, "y": 0}]


def build_region_children(region: str, region_locs: list[str],
                          loc_groups: dict[str, str],
                          existing_map_locations: dict[str, list]) -> list:
    """Build the child location nodes for a single region, pinned on its map.

    existing_map_locations: section name → previous map_locations list from
    the file on disk. Carries pin coordinates forward across regenerations
    so a fresh run doesn't wipe coordinates Stefan has already placed."""
    display = REGION_DISPLAY.get(region, region)
    map_name = REGION_MAP_OVERRIDE.get(region, display)

    def map_locs_for(node_name):
        return carry_pins(existing_map_locations, node_name, map_name)

    sec_to_loc = {loc_section_ref(display, ln): ln for ln in region_locs}
    group_members = {g: ms for g, ms in COLOCATION.get(region, [])}
    sec_to_group = {m: g for g, ms in group_members.items() for m in ms}

    children = []
    emitted_groups = set()
    for loc_name in sorted(region_locs):
        section_name = loc_section_ref(display, loc_name)
        group_name = sec_to_group.get(section_name)
        if group_name:
            # Colocated: one shared node, each member a section with its own
            # access / visibility rules, sharing a single marker.
            if group_name in emitted_groups:
                continue
            emitted_groups.add(group_name)
            sections = []
            for member in group_members[group_name]:
                member_loc = sec_to_loc.get(member)
                if member_loc is None:
                    continue
                sec = {"name": member, "access_rules": [f"^${rule_fn_name(member_loc)}"]}
                vis = vis_rules_for(region, member_loc, loc_groups)
                if vis:
                    sec["visibility_rules"] = vis
                sections.append(sec)
            if not sections:
                continue
            # Prefer the group's own carried-forward pin; on a first merge that
            # pin doesn't exist yet, so inherit a member's prior standalone pin
            # (its old node name is the section name) instead of resetting to 0,0.
            group_map_locs = map_locs_for(group_name)
            if not _has_placed_pin(group_map_locs):
                for member in group_members[group_name]:
                    member_locs = map_locs_for(member)
                    if _has_placed_pin(member_locs):
                        group_map_locs = member_locs
                        break
            children.append({
                "name": group_name,
                **CHEST_IMGS,
                "sections": sections,
                "map_locations": group_map_locs,
            })
        else:
            entry = {
                "name": section_name,
                **CHEST_IMGS,
                "access_rules": [f"^${rule_fn_name(loc_name)}"],
                "sections": [{"name": section_name}],
                "map_locations": map_locs_for(section_name),
            }
            vis = vis_rules_for(region, loc_name, loc_groups)
            if vis:
                entry["visibility_rules"] = vis
            children.append(entry)
    return children


def build_region_locations_json(
    region: str, region_locs: list[str], loc_groups: dict[str, str],
    existing_map_locations: dict[str, list], extra_children: list | None = None,
) -> list:
    """Wrap a region's child nodes in its top-level group. extra_children holds
    nodes from map-less regions folded into this one (see REGION_FOLD_INTO)."""
    display = REGION_DISPLAY.get(region, region)
    children = build_region_children(region, region_locs, loc_groups, existing_map_locations)
    if extra_children:
        children.extend(extra_children)
    return [{
        "name": display,
        **CHEST_IMGS,
        "children": children,
    }]


def build_menu_room_node(parent_name: str, target_map: str,
                         source_regions: list[str], by_region: dict[str, list[str]],
                         existing_map_locations: dict[str, list],
                         loc_groups: dict[str, str]) -> dict:
    """Build an aggregate menu node placed on target_map: one pin per source
    region, each pin's sections being refs to every check in that region, so it
    mirrors the region's own map. Pin coordinates carry forward like checks —
    keyed by the source region's display name, which is the pin's node name."""
    children = []
    for src in source_regions:
        src_display = REGION_DISPLAY.get(src, src)
        sections = []
        for loc_name in sorted(by_region.get(src, [])):
            section_name = loc_section_ref(src_display, loc_name)
            sections.append({
                "name": section_name,
                "ref": f"{src_display}/{colocation_parent(src, section_name)}/{section_name}",
            })
        map_locs = carry_pins(existing_map_locations, src_display, target_map)
        child = {
            "name": src_display,
            **CHEST_IMGS,
            "sections": sections,
            "map_locations": map_locs,
        }
        # Visibility helpers shared by every check in the room gate the whole
        # pin: a room whose checks are all containers (the bean room) carries
        # $visContainers and so vanishes without containersanity. A mixed room
        # (e.g. a level whose Complete check is always shown) keeps an empty
        # intersection, so the pin stays visible and its sections gate one by
        # one via the referenced nodes.
        rule_sets = [set(vis_rules_for(src, ln, loc_groups))
                     for ln in by_region.get(src, [])]
        common = set.intersection(*rule_sets) if rule_sets else set()
        if common:
            child["visibility_rules"] = sorted(common)
        children.append(child)
    return {
        "name": parent_name,
        **CHEST_IMGS,
        "children": children,
    }


def _has_placed_pin(map_locations: list | None) -> bool:
    """True if any pin in the list sits somewhere other than the (0, 0)
    placeholder — i.e. a coordinate someone actually placed."""
    return any((ml.get("x") or 0) != 0 or (ml.get("y") or 0) != 0
               for ml in (map_locations or []))


def load_existing_map_locations(path: Path) -> dict[str, list]:
    """Read a previously-written locations/<Region>.json and pull each
    child's map_locations back out, keyed by section name."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, list] = {}
    for region_entry in data:
        for child in region_entry.get("children", []):
            name = child.get("name")
            ml = child.get("map_locations")
            if name and ml:
                out[name] = ml
    return out


def load_existing_colocation(path: Path) -> list:
    """Colocation groups already present in an existing locations file: each
    top-level child node bundling more than one real (non-ref) section under one
    shared pin, as (node name, [section names]). Lets a regen preserve groupings
    added by hand beyond the COLOCATION defaults so their shared pins survive."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    groups = []
    for region_entry in data:
        for child in region_entry.get("children", []):
            secs = [s for s in (child.get("sections") or [])
                    if s.get("name") and "ref" not in s]
            if len(secs) > 1:
                groups.append((child.get("name"), [s["name"] for s in secs]))
    return groups


def merge_discovered_colocation(by_region: dict) -> None:
    """Augment COLOCATION with the groups already in the locations/*.json on
    disk, so regenerating preserves hand-added groupings (and, via their node
    names, their placed pins) instead of flattening them to single nodes."""
    region_sections = {
        region: {loc_section_ref(REGION_DISPLAY.get(region, region), ln) for ln in locs}
        for region, locs in by_region.items()
    }
    for region, locs in by_region.items():
        if not locs or region in REGION_FOLD_INTO:
            continue  # folded regions have no file of their own; found in the host's
        display = REGION_DISPLAY.get(region, region)
        path = PACK / "locations" / f"{display}.json"
        # A group's pin lives on the host map, but its sections belong to the
        # host region or a region folded into it; assign to whichever owns them.
        candidates = [region] + [f for f, h in REGION_FOLD_INTO.items() if h == region]
        for group_name, members in load_existing_colocation(path):
            owner = next((c for c in candidates
                          if all(m in region_sections.get(c, set()) for m in members)), region)
            existing = COLOCATION.setdefault(owner, [])
            grouped = {m for _, ms in existing for m in ms}
            if any(m in grouped for m in members):
                continue  # already a COLOCATION default or duplicate; leave it
            existing.append((group_name, members))


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def lua_table_kv(items, key_quote=False) -> str:
    """Render { [key] = value, ... }, one entry per line, tab-indented."""
    lines = []
    for k, v in items:
        kk = f'["{_lua_escape(k)}"]' if key_quote else f"[{k}]"
        lines.append(f"\t{kk} = {v},")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generation entry point
# ---------------------------------------------------------------------------

# Linear top-to-bottom orchestration; the complexity is inherent, not accidental.
def main() -> None:  # noqa: C901
    items = load_assignments(APWORLD / "items.py")
    locations = load_assignments(APWORLD / "locations.py")
    regions = load_assignments(APWORLD / "regions.py")
    region_rules = load_rule_dicts(APWORLD / "regions.py")
    location_rules = load_rule_dicts(APWORLD / "rules.py")
    # rules.py builds LOCATION_RULES_VANILLA from the open castle base plus the
    # vanilla deltas (_VANILLA_EXTRA ANDs extra requirements onto the open rule,
    # _VANILLA_OVERRIDE replaces it, _VANILLA_ONLY adds locations open castle does
    # not gate), not as a literal dict, so reconstruct it from the literal blocks.
    if "LOCATION_RULES_VANILLA" not in location_rules:
        open_tbl = location_rules.get("LOCATION_RULES_OPEN_CASTLE", {})
        vanilla = dict(open_tbl)
        for k, extra in location_rules.get("_VANILLA_EXTRA", {}).items():
            vanilla[k] = ast.BinOp(left=open_tbl[k], op=ast.BitAnd(), right=extra)
        vanilla.update(location_rules.get("_VANILLA_OVERRIDE", {}))
        vanilla.update(location_rules.get("_VANILLA_ONLY", {}))
        location_rules["LOCATION_RULES_VANILLA"] = vanilla
    ITEM_PREDICATES.update(load_item_predicates(APWORLD / "access.py"))
    RULE_ALIASES.update(load_rule_aliases(APWORLD / "rules.py"))
    INT_CONSTANTS.update(load_int_constants(APWORLD / "rules.py"))
    # The post-ending chest exclusion lives in __init__.py's _location_enabled,
    # not in the regions/rules tables, so read the name set straight from there.
    global POST_ENDING_CHESTS
    POST_ENDING_CHESTS = load_assignments(
        APWORLD / "__init__.py").get("ENTRY_HALL_POST_ENDING_CHESTS", frozenset())

    name_to_id_items = items["ITEM_NAME_TO_ID"]
    name_to_id_locs = locations["LOCATION_NAME_TO_ID"]
    loc_regions = locations["LOCATION_REGIONS"]
    loc_groups = locations["LOCATION_GROUPS"]
    region_names = regions["REGION_NAMES"]

    # ---- items/items.json -------------------------------------------------
    write_json(PACK / "items" / "items.json", build_items_json(items))

    # ---- locations/<Region>.json -----------------------------------------
    by_region: dict[str, list[str]] = {r: [] for r in region_names}
    for loc, region in loc_regions.items():
        by_region.setdefault(region, []).append(loc)
    merge_discovered_colocation(by_region)
    for region, locs in by_region.items():
        if not locs:
            continue
        if region in REGION_FOLD_INTO:
            continue  # emitted as children of its host region instead
        display = REGION_DISPLAY.get(region, region)
        out_path = PACK / "locations" / f"{display}.json"
        prior = load_existing_map_locations(out_path)
        extra_children = []
        for folded, host in REGION_FOLD_INTO.items():
            if host == region and by_region.get(folded):
                # On the first fold the folded region's pins still live in its
                # own (about-to-be-removed) file; read those coordinates too so
                # hand-placed pins survive the move into the host file. Prefer
                # whichever source has a real (non-placeholder) pin, so an
                # earlier 0,0 already written into the host doesn't clobber a
                # coordinate still recorded in the folded file.
                folded_display = REGION_DISPLAY.get(folded, folded)
                folded_prior = load_existing_map_locations(
                    PACK / "locations" / f"{folded_display}.json")
                merged_prior = dict(prior)
                for node_name, mls in folded_prior.items():
                    host_mls = merged_prior.get(node_name)
                    if not _has_placed_pin(host_mls) and _has_placed_pin(mls):
                        merged_prior[node_name] = mls
                    elif node_name not in merged_prior:
                        merged_prior[node_name] = mls
                extra_children.extend(
                    build_region_children(folded, by_region[folded], loc_groups, merged_prior)
                )
        region_json = build_region_locations_json(region, locs, loc_groups, prior,
                                                  extra_children=extra_children)
        if region in MENU_ROOMS:
            parent_name, sources = MENU_ROOMS[region]
            target_map = REGION_MAP_OVERRIDE.get(region, display)
            region_json.append(
                build_menu_room_node(parent_name, target_map, sources, by_region, prior, loc_groups)
            )
        write_json(out_path, region_json)

    # ---- scripts/locations_import.lua ------------------------------------
    import_lines = []
    for region in sorted(by_region):
        if not by_region[region]:
            continue
        if region in REGION_FOLD_INTO:
            continue  # no file of its own; folded into its host region
        display = REGION_DISPLAY.get(region, region)
        import_lines.append(f'Tracker:AddLocations("locations/{display}.json")')
    write_text(PACK / "scripts" / "locations_import.lua",
               "\n".join(import_lines) + "\n")

    # ---- scripts/autotracking/item_mapping.lua ---------------------------
    item_rows = []
    for name, ap_id in name_to_id_items.items():
        item_rows.append((str(ap_id), f'{{"{_lua_escape(name)}", "toggle"}}'))
    write_text(PACK / "scripts" / "autotracking" / "item_mapping.lua",
               "ITEM_MAPPING = {\n" + lua_table_kv(item_rows) + "\n}\n")

    # ---- scripts/autotracking/location_mapping.lua -----------------------
    loc_rows = []
    for name, ap_id in name_to_id_locs.items():
        region = loc_regions.get(name, "TBD")
        display = REGION_DISPLAY.get(region, region)
        section = loc_section_ref(display, name)
        # Full section path: group node / location node / section. The middle
        # segment is the colocation group when the section shares a marker,
        # else the section's own node. The section segment is always required —
        # "@Group/Section" resolves against the group node, which has no
        # direct sections, so the clear would no-op. A folded region's nodes
        # live under their host's group, so the first segment is the host.
        group_region = REGION_FOLD_INTO.get(region, region)
        group_display = REGION_DISPLAY.get(group_region, group_region)
        code = f"@{group_display}/{colocation_parent(region, section)}/{section}"
        loc_rows.append((str(ap_id), f'{{"{_lua_escape(code)}"}}'))
    write_text(PACK / "scripts" / "autotracking" / "location_mapping.lua",
               "LOCATION_MAPPING = {\n" + lua_table_kv(loc_rows) + "\n}\n")

    # ---- scripts/autotracking/setting_mapping.lua ------------------------
    # Slot data keys → tracker code + value mapping. Boolean and integer
    # slot values are normalised to a stage index in the progressive item.
    slot_lines = ["SLOT_CODES = {"]
    for s in SETTING_ITEMS:
        slot_lines.append(f'\t{s["key"]} = {{')
        slot_lines.append(f'\t\tcode = "{s["key"]}",')
        slot_lines.append("\t\tmapping = {")
        if s.get("binary"):
            # AP slot_data sends booleans (yaml `true`/`false`) or 0/1 ints.
            slot_lines.append("\t\t\t[0] = 0, [1] = 1,")
            slot_lines.append('\t\t\t[false] = 0, [true] = 1,')
        else:
            for i, (stage_key, _) in enumerate(s["stages"]):
                slot_lines.append(f'\t\t\t["{stage_key}"] = {i}, [{i}] = {i},')
        slot_lines.append("\t\t},")
        slot_lines.append("\t},")
    slot_lines.append("}")
    write_text(PACK / "scripts" / "autotracking" / "setting_mapping.lua",
               "\n".join(slot_lines) + "\n")

    # ---- scripts/logic/access_rules.lua ---------------------------------
    # For each AP location, emit `function rule_<slug>()` returning the
    # mode-correct composed rule (region entry AND per-location require).
    region_vanilla = region_rules.get("REGION_ENTRY_RULES_VANILLA", {})
    region_open = region_rules.get("REGION_ENTRY_RULES_OPEN_CASTLE", {})
    loc_rules_v = location_rules.get("LOCATION_RULES_VANILLA", {})
    loc_rules_o = location_rules.get("LOCATION_RULES_OPEN_CASTLE", {})

    def compose(region: str, loc_name: str, region_tbl, loc_tbl,
                force_true: frozenset[str] = frozenset()) -> str:
        parts = []
        rnode = region_tbl.get(region)
        if rnode is not None:
            parts.append(rule_to_lua(rnode, force_true))
        lnode = loc_tbl.get(loc_name)
        if lnode is not None:
            parts.append(rule_to_lua(lnode, force_true))
        if not parts:
            return "true"
        return " and ".join(parts)

    def mode_access(region_tbl, loc_tbl, region: str, loc_name: str) -> str:
        # Strict path (logic flags as the player set them) against the same rule
        # with Running / Glitched forced on. Equal strings mean the rule has no
        # flag branch, so it is a plain Normal-or-None check; differing strings
        # gate the yellow out-of-logic tier via flagAccess.
        strict = compose(region, loc_name, region_tbl, loc_tbl)
        forced = compose(region, loc_name, region_tbl, loc_tbl, FLAG_ITEMS)
        if strict == forced:
            return f"reachAccess({strict})"
        return f"flagAccess({strict}, {forced})"

    lua_lines = [
        "-- Auto-generated by tools/generate.py from HP2PC_AP/apworld/{regions,rules}.py.",
        "-- One function per AP location returning its PopTracker AccessibilityLevel.",
        "-- Reachable in logic is Normal. Reachable only by forcing a Running or",
        "-- Glitched flag on is SequenceBreak (obtainable but out of logic). Otherwise",
        "-- None. Mode-switched on isOpenCastle(): vanilla and open castle both embedded.",
        "",
    ]
    for loc_name in name_to_id_locs:
        region = loc_regions.get(loc_name, "TBD")
        van = mode_access(region_vanilla, loc_rules_v, region, loc_name)
        ocs = mode_access(region_open, loc_rules_o, region, loc_name)
        fn = rule_fn_name(loc_name)
        if van == ocs:
            lua_lines.append(f"function {fn}() return {van} end")
        else:
            lua_lines.append(f"function {fn}()")
            lua_lines.append("\tif isOpenCastle() then")
            lua_lines.append(f"\t\treturn {ocs}")
            lua_lines.append("\telse")
            lua_lines.append(f"\t\treturn {van}")
            lua_lines.append("\tend")
            lua_lines.append("end")
    write_text(PACK / "scripts" / "logic" / "access_rules.lua",
               "\n".join(lua_lines) + "\n")

    # ---- maps/maps.json (only if missing) -------------------------------
    maps_path = PACK / "maps" / "maps.json"
    if not maps_path.exists():
        # One placeholder map per region. Stefan replaces each entry with the
        # per-floor map breakdown when the rendered images land.
        maps = []
        for region in sorted(by_region):
            if not by_region[region]:
                continue
            display = REGION_DISPLAY.get(region, region)
            maps.append({
                "name": display,
                "location_size": 12,
                "location_border_thickness": 1,
                "img": f"images/maps/{slug(display).lower()}.png",
            })
        write_json(maps_path, maps)

    print(f"Wrote items: {len(name_to_id_items)} items")
    print(f"Wrote locations across {sum(1 for r in by_region if by_region[r])} regions ({len(name_to_id_locs)} total)")
    print(f"Wrote access rules for {len(name_to_id_locs)} locations")


if __name__ == "__main__":
    main()
