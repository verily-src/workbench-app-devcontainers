-- severity.lua sets a `severity` (and numeric `severity_level`) field on every
-- forwarded record.
--
-- Journald records carry a syslog PRIORITY field. Container records do not, so
-- the level is derived from the log line itself when the line starts with a
-- recognizable level marker; otherwise it falls back to INFO, as before.

local SYSLOG_SEVERITIES = {
    ["0"] = "EMERGENCY",
    ["1"] = "ALERT",
    ["2"] = "CRITICAL",
    ["3"] = "ERROR",
    ["4"] = "WARNING",
    ["5"] = "NOTICE",
    ["6"] = "INFO",
    ["7"] = "DEBUG"
}

-- Single letter level markers used by Jupyter, Tornado and IPython, e.g.
-- "[I 2026-08-21 10:00:00.000 ServerApp] 200 GET /api/contents/x.csv".
local LETTER_SEVERITIES = {
    C = { severity = "CRITICAL", level = 2 },
    E = { severity = "ERROR", level = 3 },
    W = { severity = "WARNING", level = 4 },
    I = { severity = "INFO", level = 6 },
    D = { severity = "DEBUG", level = 7 }
}

-- Level words used by most other loggers, most severe first.
local WORD_SEVERITIES = {
    { word = "EMERGENCY", severity = "EMERGENCY", level = 0 },
    { word = "FATAL", severity = "CRITICAL", level = 2 },
    { word = "CRITICAL", severity = "CRITICAL", level = 2 },
    { word = "ERROR", severity = "ERROR", level = 3 },
    { word = "WARNING", severity = "WARNING", level = 4 },
    { word = "WARN", severity = "WARNING", level = 4 },
    { word = "NOTICE", severity = "NOTICE", level = 5 },
    { word = "DEBUG", severity = "DEBUG", level = 7 }
}

-- Only the start of the line is inspected. Loggers put the level in a prefix
-- made up of timestamps, process ids and brackets, so a level word is only
-- honored when it appears near the start of the line and nothing lowercase
-- precedes it. That keeps ordinary application output which happens to contain
-- a word like "ERROR" from being reclassified.
local PREFIX_LENGTH = 64

-- Reports whether `text` starts with a log prefix containing `word` as a
-- standalone word. `word` is matched literally, so it needs no pattern
-- escaping.
local function has_level_word(text, word)
    local search_from = 1

    while true do
        local first, last = string.find(text, word, search_from, true)

        if not first then
            return false
        end

        local preceding = string.sub(text, 1, first - 1)
        local before = string.sub(text, first - 1, first - 1)
        local after = string.sub(text, last + 1, last + 1)

        if not string.match(preceding, "%l")
            and not string.match(before, "%a")
            and not string.match(after, "%a") then
            return true
        end

        search_from = last + 1
    end
end

local function severity_from_message(message)
    local letter = string.match(message, "^%[(%u) ")

    if letter and LETTER_SEVERITIES[letter] then
        return LETTER_SEVERITIES[letter]
    end

    local prefix = string.sub(message, 1, PREFIX_LENGTH)

    for _, candidate in ipairs(WORD_SEVERITIES) do
        if has_level_word(prefix, candidate.word) then
            return candidate
        end
    end

    return nil
end

function set_severity(tag, timestamp, record)
    local priority = record["PRIORITY"]

    if priority then
        -- Journald logs: map syslog priority (0-7) to severity levels
        local p = tostring(priority)
        record["severity_level"] = tonumber(priority)
        record["severity"] = SYSLOG_SEVERITIES[p] or "INFO"

        return 1, timestamp, record
    end

    -- No priority field (e.g. Docker logs): derive the level from the message
    -- when it starts with a level marker, otherwise default to INFO.
    local message = record["log"]
    local derived = nil

    if type(message) == "string" then
        derived = severity_from_message(message)
    end

    if derived then
        record["severity"] = derived.severity
        record["severity_level"] = derived.level
    else
        record["severity"] = "INFO"
        record["severity_level"] = 6
    end

    return 1, timestamp, record
end
