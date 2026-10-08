-- Text from a world, made safe to show a player as a chat or panel line: escapes and control,
-- format and private-use characters removed, length bounded. Never run, parsed or used as anything
-- but text.

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

local function join(points, first, last)
	local parts = {}
	for index = first, last do
		parts[#parts + 1] = utf8_char(points[index])
	end
	return table.concat(parts)
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

return lines
