-- The panel a player sees while their choices go to a world: a few short lines on the right, below
-- where chat lines appear, over a dark backdrop drawn here (a one-pixel picture made by
-- core.encode_png) and sized to the text.

local panel = {}

local BACKDROP = "[png:" .. core.encode_base64(core.encode_png(1, 1, string.char(14, 10, 26, 190)))
local shown = {}

-- The backdrop's size for a text, in the units HUD pictures are scaled by (pixels of the one-pixel
-- picture): about 9 per character of the longest line and 22 per line, with a margin.
local function backdrop_scale(text)
	local lines, longest = 0, 0
	for line in (text .. "\n"):gmatch("([^\n]*)\n") do
		lines = lines + 1
		longest = math.max(longest, #line)
	end
	return {x = longest * 9 + 28, y = lines * 22 + 18}
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
		position = {x = 1, y = 0.3},
		offset = {x = -12, y = -10},
		alignment = {x = -1, y = 1},
		scale = backdrop_scale(text),
		text = BACKDROP,
		z_index = 10,
	})
	hud.text = player:hud_add({
		type = "text",
		position = {x = 1, y = 0.3},
		offset = {x = -26, y = 0},
		alignment = {x = -1, y = 1},
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
