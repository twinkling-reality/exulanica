-- JSON bodies for the door, written so their shape never depends on how the engine writes an
-- empty table (as null) or a missing value (left out): objects list their members in order,
-- arrays are joined by hand, and a mapping file is spliced in as the text it was read as.

local json = {}

-- A string, escaped as JSON.
function json.string(text)
	return assert(core.write_json(tostring(text)))
end

-- A whole number. Fractions never appear in anything this mod sends.
function json.integer(number)
	assert(type(number) == "number" and number == math.floor(number), "a whole number")
	return string.format("%d", number)
end

function json.boolean(value)
	return value and "true" or "false"
end

-- An array of values already encoded.
function json.array(encoded)
	return "[" .. table.concat(encoded, ",") .. "]"
end

-- An array of strings.
function json.strings(list)
	local encoded = {}
	for index, text in ipairs(list) do
		encoded[index] = json.string(text)
	end
	return json.array(encoded)
end

-- An object whose members are {name, encoded value} pairs, in the order given; a pair whose
-- value is nil is left out.
function json.object(members)
	local parts = {}
	for _, member in ipairs(members) do
		if member[2] ~= nil then
			parts[#parts + 1] = json.string(member[1]) .. ":" .. member[2]
		end
	end
	return "{" .. table.concat(parts, ",") .. "}"
end

-- The value a body holds, or nil and why. JSON null reads as nil.
function json.parse(text)
	if type(text) ~= "string" or text == "" then
		return nil, "empty body"
	end
	return core.parse_json(text, nil, true)
end

return json
