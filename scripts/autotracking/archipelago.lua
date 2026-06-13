ScriptHost:LoadScript("scripts/autotracking/item_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/location_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/setting_mapping.lua")
ScriptHost:LoadScript("scripts/autotracking/level_mapping.lua")

CUR_INDEX = -1
SLOT_DATA = nil
LEVEL_KEY = nil

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

    -- Map-follow: subscribe to this slot's current-level key (written by the
    -- client) and fetch its current value, so the active map tab tracks the
    -- player. Both calls must run from a ClearHandler.
    LEVEL_KEY = "HP2PC_AP_level:" .. TEAM_NUMBER .. ":" .. PLAYER_ID
    Archipelago:Get({LEVEL_KEY})
    Archipelago:SetNotify({LEVEL_KEY})
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

function onLevelRetrieved(key, value)
    if key == LEVEL_KEY then activate_level_tab(value) end
end

function onLevelSetReply(key, value, old_value)
    if key == LEVEL_KEY then activate_level_tab(value) end
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
end

Archipelago:AddClearHandler("clear handler", onClear)
Archipelago:AddItemHandler("item handler", onItem)
Archipelago:AddLocationHandler("location handler", onLocation)
Archipelago:AddRetrievedHandler("level retrieved handler", onLevelRetrieved)
Archipelago:AddSetReplyHandler("level set handler", onLevelSetReply)
