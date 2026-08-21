-- container-name.lua labels forwarded Docker log records with the name of the
-- container that produced them.
--
-- Every container on the VM writes to the same Fluent Bit tag (vm.docker) and
-- the only per-record identifier is `filepath`, which contains an opaque
-- container id. Once a VM runs more than one container there is no way to tell
-- which container a line came from, so this filter adds two flat fields:
--
--   container_name - e.g. "application-server", "proxy-agent"
--   container_id   - short (12 character) container id, as shown by `docker ps`
--
-- The name is resolved from two sources, in order:
--
--   1. The `tag` attribute that the Docker json-file log driver writes into
--      every record, because /etc/docker/daemon.json sets `"tag": "{{.Name}}"`.
--      This is absent when a container overrides the daemon's default log
--      options (`docker run --log-opt ...` replaces them wholesale).
--   2. /var/lib/docker/containers/<id>/config.v2.json, which the Fluent Bit
--      container already bind-mounts read-only. Results are cached per
--      container id, so this costs at most one small file read per container,
--      not one per record.

-- container id -> resolved name, or false when the name could not be resolved.
local name_cache = {}

-- Extracts the container id from a Docker log file path, which looks like
-- /var/lib/docker/containers/<id>/<id>-json.log
local function container_id_from_filepath(filepath)
    return string.match(filepath, "/containers/(%x+)/")
end

-- Reads the container name out of the container's Docker config file. Docker
-- stores names with a leading slash ("/application-server"), which
-- distinguishes the container name from the other "Name" keys in the file,
-- such as mounted volume names.
local function name_from_config(container_id)
    local path = "/var/lib/docker/containers/" .. container_id .. "/config.v2.json"
    local config_file = io.open(path, "r")

    if not config_file then
        return nil
    end

    local contents = config_file:read("*a")
    config_file:close()

    if not contents then
        return nil
    end

    return string.match(contents, '"Name":"/([^"]+)"')
end

local function cached_name(container_id)
    local cached = name_cache[container_id]

    if cached ~= nil then
        return cached
    end

    local name = name_from_config(container_id) or false
    name_cache[container_id] = name

    return name
end

function set_container_name(tag, timestamp, record)
    local filepath = record["filepath"]

    -- Records without a file path do not come from the Docker log tail input.
    if type(filepath) ~= "string" then
        return 0, timestamp, record
    end

    local container_id = container_id_from_filepath(filepath)

    if not container_id then
        return 0, timestamp, record
    end

    record["container_id"] = string.sub(container_id, 1, 12)

    local attrs = record["attrs"]
    local name = nil

    if type(attrs) == "table" and type(attrs["tag"]) == "string" then
        name = attrs["tag"]
    else
        name = cached_name(container_id)
    end

    if name then
        record["container_name"] = name
    end

    return 1, timestamp, record
end
