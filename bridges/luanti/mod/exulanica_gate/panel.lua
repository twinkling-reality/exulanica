-- The one line a player sees while their character is away: centred just above the hotbar, where
-- chat does not reach, over a dark backdrop drawn here (a one-pixel picture made by
-- core.encode_png) and sized to the text.

local panel = {}

local BACKDROP = "[png:" .. core.encode_base64(core.encode_png(1, 1, string.char(14, 10, 26, 190)))
local POSITION = {x = 0.5, y = 1}
local OFFSET_Y = -96
local shown = {}

-- The backdrop's size for a line, in the units HUD pictures are scaled by (pixels of the one-pixel
-- picture): about 9 per character and 22 for the line, with a margin.
local function backdrop_scale(text)
	return {x = #text * 9 + 28, y = 22 + 14}
end

function panel.show(player, name, text)
	local hud = shown[name]
	if hud then
		player:hud_change(hud.text, "text", text)
		player:hud_change(hud.backdrop, "scale", backdrop_scale(text))
		return
	end
	hud = {}
	hud.backdrop = player:hud_add({
		type = "image",
		position = POSITION,
		offset = {x = 0, y = OFFSET_Y + 7},
		alignment = {x = 0, y = -1},
		scale = backdrop_scale(text),
		text = BACKDROP,
		z_index = 10,
	})
	hud.text = player:hud_add({
		type = "text",
		position = POSITION,
		offset = {x = 0, y = OFFSET_Y},
		alignment = {x = 0, y = -1},
		number = 0xFFFFFF,
		text = text,
		z_index = 11,
	})
	shown[name] = hud
end

function panel.hide(player, name)
	local hud = shown[name]
	shown[name] = nil
	if hud and player then
		player:hud_remove(hud.text)
		player:hud_remove(hud.backdrop)
	end
end

function panel.forget(name)
	shown[name] = nil
end

return panel
