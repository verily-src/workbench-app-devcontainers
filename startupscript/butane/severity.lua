function set_severity(tag, timestamp, record)
    local priority = record["PRIORITY"]

    if priority then
        -- Journald logs: map syslog priority (0-7) to severity levels
        local p = tostring(priority)
        record["severity_level"] = tonumber(priority)

        if p == "0" then
            record["severity"] = "EMERGENCY"
        elseif p == "1" then
            record["severity"] = "ALERT"
        elseif p == "2" then
            record["severity"] = "CRITICAL"
        elseif p == "3" then
            record["severity"] = "ERROR"
        elseif p == "4" then
            record["severity"] = "WARNING"
        elseif p == "5" then
            record["severity"] = "NOTICE"
        elseif p == "6" then
            record["severity"] = "INFO"
        elseif p == "7" then
            record["severity"] = "DEBUG"
        else
            record["severity"] = "INFO"
        end
    else
        -- No priority field (e.g., Docker logs), default to INFO
        record["severity"] = "INFO"
        record["severity_level"] = 6
    end

    return 1, timestamp, record
end
