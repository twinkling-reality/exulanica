-- Lines of chat crossing in either direction.
--
-- Outgoing (a player's chat said by their traveller): escapes stripped, then the line is refused
-- whole rather than changed if it holds a control, format or private-use character or is not
-- UTF-8; every name of a player this server knows becomes "someone"; spaces at either end are
-- trimmed; it must hold 1 to `maximum` characters. This screen answers the player at once. The
-- world's own check (the host's line rule and the owner's saved names) stays the authority, so the
-- set of characters refused here is the common subset a chat box can produce, not all of Unicode.
--
-- Incoming (a world's line shown in chat): escapes and control characters removed, length
-- bounded. Never run, parsed or used as anything but text.

local lines = {}

-- Decode UTF-8 into code points, or nil if the text is not well-formed UTF-8.
local function code_points(text)
	local points = {}
	local index, length = 1, #text
	while index <= length do
		local byte = text:byte(index)
		local point, size
		if byte < 0x80 then
			point, size = byte, 1
		elseif byte >= 0xC2 and byte <= 0xDF then
			point, size = byte - 0xC0, 2
		elseif byte >= 0xE0 and byte <= 0xEF then
			point, size = byte - 0xE0, 3
		elseif byte >= 0xF0 and byte <= 0xF4 then
			point, size = byte - 0xF0, 4
		else
			return nil
		end
		if index + size - 1 > length then
			return nil
		end
		for offset = 1, size - 1 do
			local follow = text:byte(index + offset)
			if follow < 0x80 or follow > 0xBF then
				return nil
			end
			point = point * 64 + (follow - 0x80)
		end
		if (size == 3 and point < 0x800) or (size == 4 and (point < 0x10000 or point > 0x10FFFF))
				or (point >= 0xD800 and point <= 0xDFFF) then
			return nil
		end
		points[#points + 1] = point
		index = index + size
	end
	return points
end
lines.code_points = code_points

-- Control (Cc), format (Cf), line and paragraph separators (Zl, Zp) and private use (Co)
-- characters a chat box may carry.
local function refused(point)
	return point < 0x20 or point == 0x7F
		or (point >= 0x80 and point <= 0x9F)
		or point == 0xAD or (point >= 0x600 and point <= 0x605) or point == 0x61C
		or point == 0x6DD or point == 0x70F or point == 0x180E
		or (point >= 0x200B and point <= 0x200F)
		or (point >= 0x2028 and point <= 0x202E)
		or (point >= 0x2060 and point <= 0x2064)
		or (point >= 0x2066 and point <= 0x206F)
		or point == 0xFEFF or (point >= 0xFFF9 and point <= 0xFFFB)
		or (point >= 0xE000 and point <= 0xF8FF)
		or point == 0xE0001 or (point >= 0xE0020 and point <= 0xE007F)
		or point >= 0xF0000
end
lines.refused = refused

-- White space trimmed from either end of a line.
local function space(point)
	return point == 0x20 or point == 0xA0 or point == 0x1680
		or (point >= 0x2000 and point <= 0x200A)
		or point == 0x202F or point == 0x205F or point == 0x3000
end

-- The bytes of one code point.
local function utf8_char(point)
	if point < 0x80 then
		return string.char(point)
	elseif point < 0x800 then
		return string.char(0xC0 + math.floor(point / 64), 0x80 + point % 64)
	elseif point < 0x10000 then
		return string.char(0xE0 + math.floor(point / 4096), 0x80 + math.floor(point / 64) % 64,
			0x80 + point % 64)
	end
	return string.char(0xF0 + math.floor(point / 262144), 0x80 + math.floor(point / 4096) % 64,
		0x80 + math.floor(point / 64) % 64, 0x80 + point % 64)
end
lines.utf8_char = utf8_char

local function join(points, first, last)
	local parts = {}
	for index = first, last do
		parts[#parts + 1] = utf8_char(points[index])
	end
	return table.concat(parts)
end

-- Every run of the player-name alphabet that is, ignoring case, a name in `names` (a set of
-- lowercase names) becomes "someone".
function lines.replace_names(text, names)
	return (text:gsub("[A-Za-z0-9_%-]+", function(run)
		if names[run:lower()] then
			return "someone"
		end
		return nil
	end))
end

-- What to say for a player's chat line: the line, or nil, a code and words for the player.
function lines.outgoing(text, names, maximum)
	if type(text) ~= "string" then
		return nil, "line_not_text", "That was not a line of text."
	end
	local stripped = core.strip_escapes(text)
	local points = code_points(stripped)
	if points == nil then
		return nil, "line_not_text", "That line could not be read as text, so it was not said."
	end
	for _, point in ipairs(points) do
		if refused(point) then
			return nil, "line_has_hidden_characters",
				"That line holds hidden or control characters, so it was not said."
		end
	end
	local first, last = 1, #points
	while first <= last and space(points[first]) do
		first = first + 1
	end
	while last >= first and space(points[last]) do
		last = last - 1
	end
	if first > last then
		return nil, "line_empty", "There was nothing to say."
	end
	local line = lines.replace_names(join(points, first, last), names)
	local count = #code_points(line)
	if count > maximum then
		return nil, "line_too_long", string.format(
			"That line is longer than the world takes (%d letters); it was not said.", maximum)
	end
	return line
end

-- A line from the world, made safe to show as chat or a panel line: escapes and control,
-- format and private-use characters removed, at most `maximum` characters.
function lines.incoming(text, maximum)
	if type(text) ~= "string" then
		return ""
	end
	local points = code_points(core.strip_escapes(text))
	if points == nil then
		return "(a line that could not be read)"
	end
	local kept = {}
	for _, point in ipairs(points) do
		if not refused(point) then
			kept[#kept + 1] = point
		end
	end
	if #kept > maximum then
		return join(kept, 1, maximum - 3) .. "..."
	end
	return join(kept, 1, #kept)
end

-- The number of characters in a line.
function lines.length(text)
	local points = code_points(text)
	return points and #points or nil
end

return lines
