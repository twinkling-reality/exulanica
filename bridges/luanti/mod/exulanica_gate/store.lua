-- What the mod keeps across restarts, in its own mod storage: one JSON document per key.
--
-- Keys: "channel:<grant id>" (cursor and the grant as last read; a redeemed channel's credential),
-- "journey:<player>" (one player's crossing), "kept:<thing id>" (a game item's own stack, kept
-- while its thing is across), "delivered:<departure id>", "requester-secret". The engine writes an
-- empty table as null, so every reader treats a missing list as empty.

local store = {}
local storage

function store.init(mod_storage)
	storage = mod_storage
end

function store.get(key)
	local text = storage:get_string(key)
	if text == "" then
		return nil
	end
	local value = core.parse_json(text, nil, true)
	if type(value) ~= "table" then
		return nil
	end
	return value
end

function store.put(key, document)
	if document == nil then
		storage:set_string(key, "")
		return
	end
	storage:set_string(key, assert(core.write_json(document)))
end

function store.keys(prefix)
	local found = {}
	for _, key in ipairs(storage:get_keys()) do
		if key:sub(1, #prefix) == prefix then
			found[#found + 1] = key
		end
	end
	table.sort(found)
	return found
end

-- A list member that may have been written as null.
function store.list(value)
	if type(value) == "table" then
		return value
	end
	return {}
end

return store
