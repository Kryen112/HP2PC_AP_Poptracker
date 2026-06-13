ScriptHost:LoadScript("scripts/autotracking/item_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/location_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/setting_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/level_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/goal_mapping.lua")

CUR_INDEX = -1
SLOT_DATA = nil
LEVEL_KEY = nil
HINTS_KEY = nil

-- AP HintStatus -> PopTracker Highlight enum for the coloured square drawn
-- under a hinted location. Empty (and hint marking is skipped) on builds
-- without hint support, where the Highlight global is absent.
HINT_STATUS_MAPPING = {}
if Highlight then
    HINT_STATUS_MAPPING = {
        [0]  = Highlight.Unspecified,
        [10] = Highlight.NoPriority,
        [20] = Highlight.Avoid,
        [30] = Highlight.Priority,
        [40] = Highlight.None,
    }
end
-- Open-castle Great Hall goal targets, captured from slot_data in onClear.
-- All zero in vanilla (no targets sent), which leaves the overall light off.
GOAL_TARGETS = { cards = 0, spells = 0, levels = 0, duels = 0, quidditch = 0 }

local function dump_table(o, depth)
    if depth == nil then depth = 0 end
    if type(o) == 'table' then
        local tabs = ('\t'):rep(depth)
        local tabs2 = ('\t'):rep(depth + 1)
        local s = '{\n'
        for k, v in pairs(o) do
            if type(k) ~= 'number' then k = '"' .. k .. '"' end
            s = s .. tabs2 .. '[' .. tostring(k) .. '] = ' .. dump_table(v, depth + 1) .. ',\n'
        end
        return s .. tabs .. '}'
    end
    return tostring(o)
end

local function apply_slot_setting(key, value)
    local def = SLOT_CODES[key]
    if not def then return end
    local mapped = def.mapping and def.mapping[value]
    if mapped == nil and type(value) == "boolean" then
        mapped = def.mapping[value and 1 or 0]
    end
    if mapped == nil then
        print("Warning: no slot mapping for", key, "value", tostring(value))
        return
    end
    local obj = Tracker:FindObjectForCode(def.code)
    if not obj then
        print("Warning: no tracker object for code:", def.code)
        return
    end
    obj.CurrentStage = mapped
end

function onClear(slot_data)
    if AUTOTRACKER_ENABLE_DEBUG_LOGGING_AP then
        print(string.format("called onClear, slot_data:\n%s", dump_table(slot_data)))
    end
    SLOT_DATA = slot_data
    CUR_INDEX = -1

    for key, value in pairs(slot_data) do
        apply_slot_setting(key, value)
    end

    for _, v in pairs(LOCATION_MAPPING) do
        if v[1] then
            local obj = Tracker:FindObjectForCode(v[1])
            if obj then
                if v[1]:sub(1, 1) == "@" then
                    obj.AvailableChestCount = obj.ChestCount
                else
                    obj.Active = false
                end
            end
        end
    end

    for _, v in pairs(ITEM_MAPPING) do
        if v[1] and v[2] then
            local obj = Tracker:FindObjectForCode(v[1])
            if obj then
                if v[2] == "toggle" then
                    obj.Active = false
                elseif v[2] == "consumable" then
                    obj.AcquiredCount = 0
                elseif v[2] == "progressive" then
                    obj.CurrentStage = 0
                    obj.Active = false
                end
            end
        end
    end

    for _, counter in pairs({"bronze_cards", "silver_cards", "gold_cards"}) do
        local obj = Tracker:FindObjectForCode(counter)
        if obj then obj.AcquiredCount = 0 end
    end

    PLAYER_ID = Archipelago.PlayerNumber or -1
    TEAM_NUMBER = Archipelago.TeamNumber or 0

    -- Data-storage subscriptions (must run from a ClearHandler):
    --   LEVEL_KEY  — the client mirrors the player's current map here (map-follow).
    --   HINTS_KEY  — the server's read-only hints list for this slot.
    LEVEL_KEY = "HP2PC_AP_level:" .. TEAM_NUMBER .. ":" .. PLAYER_ID
    HINTS_KEY = "_read_hints_" .. TEAM_NUMBER .. "_" .. PLAYER_ID
    Archipelago:Get({LEVEL_KEY, HINTS_KEY})
    Archipelago:SetNotify({LEVEL_KEY, HINTS_KEY})

    -- Great Hall goal targets. cards/spells/levels are NamedRange counts;
    -- duels/quidditch are toggles meaning "win all" (10 / 6).
    local function truthy(v) return v == true or v == 1 end
    GOAL_TARGETS = {
        cards = tonumber(slot_data["open_castle_goal_cards"]) or 0,
        spells = tonumber(slot_data["open_castle_goal_spells"]) or 0,
        levels = tonumber(slot_data["open_castle_goal_levels"]) or 0,
        duels = truthy(slot_data["open_castle_goal_duels"]) and 10 or 0,
        quidditch = truthy(slot_data["open_castle_goal_quidditch"]) and 6 or 0,
    }
    recompute_goal()
end

-- Recompute the Great Hall goal panel from current tracker state: spell
-- toggles, card counters, and cleared completion / duel / match locations.
-- Sets each clause's counter and lights the overall indicator when every
-- active clause (target > 0) is satisfied. No-op-safe before items load.
-- BadgeText / BadgeTextColor are available since PopTracker 0.31.0. On older
-- builds the clause still greys in/out via Active; it just shows no number.
local HAS_BADGE = PopVersion ~= nil and PopVersion >= "0.31.0"

-- One clause: lit with a "progress/target" badge when it is part of the goal
-- (so a required-but-unstarted clause reads "0/N", never grey), greyed with no
-- badge when target is 0 (not part of this seed's goal). Badge turns green
-- once the clause is satisfied.
local function set_clause(code, progress, target)
    local obj = Tracker:FindObjectForCode(code)
    if not obj then return end
    local in_goal = target > 0
    obj.Active = in_goal
    if HAS_BADGE then
        if in_goal then
            obj.BadgeText = tostring(progress) .. "/" .. tostring(target)
            obj.BadgeTextColor = (progress >= target) and "#44dd44" or "#ffffff"
        else
            obj.BadgeText = ""
        end
    end
end

local function cleared(code)
    local obj = Tracker:FindObjectForCode(code)
    return obj ~= nil and obj.ChestCount > 0 and obj.AvailableChestCount == 0
end

local function count_cleared(codes)
    local n = 0
    for _, code in ipairs(codes) do
        if cleared(code) then n = n + 1 end
    end
    return n
end

function recompute_goal()
    local cards = 0
    for _, c in ipairs(GOAL_CARD_COUNTERS) do
        cards = cards + (Tracker:ProviderCountForCode(c) or 0)
    end
    local spells = 0
    for _, s in ipairs(GOAL_SPELL_CODES) do
        if Tracker:ProviderCountForCode(s) > 0 then spells = spells + 1 end
    end
    local levels = count_cleared(GOAL_LEVEL_CODES)
    local duels = count_cleared(GOAL_DUEL_CODES)
    local quidditch = count_cleared(GOAL_QUID_CODES)

    set_clause("goal_cards", cards, GOAL_TARGETS.cards)
    set_clause("goal_spells", spells, GOAL_TARGETS.spells)
    set_clause("goal_levels", levels, GOAL_TARGETS.levels)
    set_clause("goal_duels", duels, GOAL_TARGETS.duels)
    set_clause("goal_quidditch", quidditch, GOAL_TARGETS.quidditch)

    local function clause_ok(progress, target)
        return target <= 0 or progress >= target
    end
    local any_target = GOAL_TARGETS.cards > 0 or GOAL_TARGETS.spells > 0
        or GOAL_TARGETS.levels > 0 or GOAL_TARGETS.duels > 0 or GOAL_TARGETS.quidditch > 0
    local met = any_target
        and clause_ok(cards, GOAL_TARGETS.cards)
        and clause_ok(spells, GOAL_TARGETS.spells)
        and clause_ok(levels, GOAL_TARGETS.levels)
        and clause_ok(duels, GOAL_TARGETS.duels)
        and clause_ok(quidditch, GOAL_TARGETS.quidditch)
    local obj = Tracker:FindObjectForCode("goal_great_hall")
    if obj then obj.Active = met end
end

-- Switch the active map tab to follow the engine map name the client mirrors
-- into AP Data Storage. Unknown maps leave the current tab alone.
function activate_level_tab(level)
    if type(level) ~= "string" or level == "" then return end
    local tabs = LEVEL_TO_TAB[string.upper(level)]
    if not tabs then
        if AUTOTRACKER_ENABLE_DEBUG_LOGGING_AP then
            print(string.format("onLevel: no tab mapping for level %s, using default", level))
        end
        tabs = LEVEL_TO_TAB_DEFAULT
    end
    for _, tab in ipairs(tabs) do
        Tracker:UiHint("ActivateTab", tab)
    end
end

-- Retrieved (Get reply) and SetReply share one dispatcher; old_value is nil
-- for retrieved replies and for "_read"-prefixed keys.
function onDataStorageUpdate(key, value, old_value)
    if key == LEVEL_KEY then
        activate_level_tab(value)
    elseif key == HINTS_KEY then
        onHintsUpdate(value)
    end
end

-- Mark every hinted location in our own world with its Highlight square.
-- A hint sits in the finder's world regardless of who receives the item, so
-- finding_player is the only filter (covers items destined for us and for
-- others alike). Found hints carry status None, which clears the square.
function onHintsUpdate(hints)
    if type(hints) ~= "table" then return end
    for _, hint in ipairs(hints) do
        if hint.finding_player == PLAYER_ID then
            updateHint(hint)
        end
    end
end

function updateHint(hint)
    local highlight_code = hint.status and HINT_STATUS_MAPPING[hint.status]
    if not highlight_code then
        -- Older AP without hint.status: fall back to the found flag.
        if hint.found == true then
            highlight_code = Highlight and Highlight.None
        elseif hint.found == false then
            highlight_code = Highlight and Highlight.Unspecified
        else
            return
        end
    end
    local codes = LOCATION_MAPPING[hint.location]
    if not codes then
        if AUTOTRACKER_ENABLE_DEBUG_LOGGING_AP then
            print(string.format("updateHint: no location mapping for id %s", hint.location))
        end
        return
    end
    for _, code in ipairs(codes) do
        if code:sub(1, 1) == "@" then
            local obj = Tracker:FindObjectForCode(code)
            if obj and obj.Highlight ~= nil then
                obj.Highlight = highlight_code
            end
        end
    end
end

function onItem(index, item_id, item_name, player_number)
    if index <= CUR_INDEX then return end
    CUR_INDEX = index
    local item = ITEM_MAPPING[item_id]
    if not item or not item[1] then
        if AUTOTRACKER_ENABLE_DEBUG_LOGGING_AP then
            print(string.format("onItem: no mapping for id %s (%s)", item_id, item_name or "?"))
        end
        return
    end

    local code = item[1]
    local kind = item[2]
    local obj = Tracker:FindObjectForCode(code)
    if not obj then
        print(string.format("onItem: no tracker object for code %s", code))
        return
    end
    if kind == "toggle" then
        obj.Active = true
    elseif kind == "consumable" then
        obj.AcquiredCount = obj.AcquiredCount + 1
    elseif kind == "progressive" then
        obj.Active = true
        obj.CurrentStage = (obj.CurrentStage or 0) + 1
    end

    bump_card_counter(code)
    recompute_goal()
end

-- Card items each bump their tier counter (bronze_cards / silver_cards /
-- gold_cards) so the items+settings panel shows a per-tier collected count.
CARD_COUNTERS = { Bronze = "bronze_cards", Silver = "silver_cards", Gold = "gold_cards" }

function bump_card_counter(code)
    local tier = code:match("^(%a+) Card %- ")
    local counter = tier and CARD_COUNTERS[tier]
    if not counter then return end
    local obj = Tracker:FindObjectForCode(counter)
    if obj then obj.AcquiredCount = obj.AcquiredCount + 1 end
end

function onLocation(location_id, location_name)
    local mapped = LOCATION_MAPPING[location_id]
    if not mapped or not mapped[1] then
        if AUTOTRACKER_ENABLE_DEBUG_LOGGING_AP then
            print(string.format("onLocation: no mapping for id %s (%s)", location_id, location_name or "?"))
        end
        return
    end
    for _, loc_code in ipairs(mapped) do
        local obj = Tracker:FindObjectForCode(loc_code)
        if obj then
            if loc_code:sub(1, 1) == "@" then
                obj.AvailableChestCount = math.max(0, obj.AvailableChestCount - 1)
            else
                obj.Active = true
            end
        end
    end
    recompute_goal()
end

Archipelago:AddClearHandler("clear handler", onClear)
Archipelago:AddItemHandler("item handler", onItem)
Archipelago:AddLocationHandler("location handler", onLocation)
Archipelago:AddRetrievedHandler("data retrieved handler", onDataStorageUpdate)
Archipelago:AddSetReplyHandler("data set handler", onDataStorageUpdate)
