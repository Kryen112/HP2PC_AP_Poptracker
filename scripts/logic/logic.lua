function has(item)
    return Tracker:ProviderCountForCode(item) > 0
end

function count(item)
    return Tracker:ProviderCountForCode(item)
end

-- Mode / setting helpers driven by the slot_data-backed setting items in items.json.
-- The setting items use multi-stage codes (e.g. "game_mode_vanilla" / "game_mode_open_castle")
-- so we can test the current stage with has(stage_code).
function isOpenCastle()
    return has("game_mode_open_castle")
end

function isVanilla()
    return has("game_mode_vanilla")
end

function vanillaGateLevels()
    return has("vanilla_gate_levels_on")
end

function enableWizardCards()
    return has("enable_wizard_cards_on")
end

function enableSecrets()
    return has("enable_secrets_on")
end

function allowMissableProgression()
    return has("allow_missable_progression_on")
end

function enableChallengeStars()
    return has("enable_challenge_stars_on")
end

function enableQuidditchUpgrades()
    return has("enable_quidditch_upgrades_on")
end

function enableDuelling()
    return has("enable_duelling_on")
end

function enableQuidditchMatches()
    return has("enable_quidditch_matches_on")
end

function enableSpellChallengeTimes()
    return has("enable_spell_challenge_times_on")
end

function enableTraps()
    return has("enable_traps_on")
end

function tradersanityOn()
    return not has("tradersanity_off")
end

function containersanityOn()
    return has("containersanity_on")
end

-- Group visibility helpers. Each returns true iff that group's locations should
-- appear on the map this seed. Used by location JSON visibility_rules.
function visCards()      return enableWizardCards() end
function visSecrets()    return enableSecrets() end
function visStars()      return enableChallengeStars() end
function visQuidPurch()  return enableQuidditchUpgrades() end
function visDuels()      return enableDuelling() end
function visQuidMatch()  return enableQuidditchMatches() end
function visSpellTimes() return enableSpellChallengeTimes() end
function visTraders()    return tradersanityOn() end
function visContainers() return containersanityOn() end
-- Classroom (Learned X) checks only exist in vanilla — open castle skips the
-- spell-teaching cutscenes entirely.
function visClassrooms()        return isVanilla() end
-- The Gryffindor challenge level only exists in open castle distribution maps.
function visOpenCastleOnly()    return isOpenCastle() end
