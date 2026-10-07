-- The gate: a frame and a portal of light, their pictures drawn here at load, and the moment a
-- player walks in.
--
-- Both pictures are made by core.encode_png and used inline as "[png:" textures, so the mod
-- carries no media file. The frame may instead be any node the server names in
-- exulanica_gate.frame_node (a game's own stone, say); no game's node is named in this code.

local gate = {}

local modname = core.get_current_modname()
gate.FRAME = modname .. ":frame"
gate.PORTAL = modname .. ":portal"

-- Pixels as raw RGBA bytes, one row after another.
local function rgba(r, g, b, a)
	return string.char(math.max(0, math.min(255, math.floor(r + 0.5))),
		math.max(0, math.min(255, math.floor(g + 0.5))),
		math.max(0, math.min(255, math.floor(b + 0.5))), a)
end

local function inline(width, height, pixels)
	return "[png:" .. core.encode_base64(core.encode_png(width, height, table.concat(pixels), 9))
end

-- A light that turns: eight frames of a three-armed swirl, deep violet to pale lavender.
local PORTAL_FRAMES = 8
local function portal_picture()
	local pixels = {}
	for frame = 0, PORTAL_FRAMES - 1 do
		for y = 0, 15 do
			for x = 0, 15 do
				local dx, dy = x - 7.5, y - 7.5
				local radius = math.sqrt(dx * dx + dy * dy)
				local turn = math.sin(3 * math.atan2(dy, dx) + radius * 0.8
					- frame * (2 * math.pi / PORTAL_FRAMES))
				local light = math.max(0, math.min(1, 0.55 + 0.35 * turn - radius / 26))
				pixels[#pixels + 1] = rgba(91 + 150 * light, 51 + 179 * light, 168 + 87 * light, 200)
			end
		end
	end
	return inline(16, 16 * PORTAL_FRAMES, pixels)
end

-- Grey stone laid in courses, its grain from a fixed seed so every server draws the same.
local function frame_picture()
	local random = PcgRandom(1009)
	local pixels = {}
	for y = 0, 15 do
		for x = 0, 15 do
			local course = math.floor(y / 4)
			local joint = (y % 4 == 3) or ((x + (course % 2) * 4) % 8 == 7)
			local shade = joint and 92 or (128 + random:next(-10, 10))
			pixels[#pixels + 1] = rgba(shade, shade, shade + 4, 255)
		end
	end
	return inline(16, 16, pixels)
end

local PORTAL_PICTURE = portal_picture()
local FRAME_PICTURE = frame_picture()
gate.picture_bytes = #PORTAL_PICTURE + #FRAME_PICTURE

core.register_node(gate.FRAME, {
	description = "Gate stone",
	tiles = {FRAME_PICTURE},
	is_ground_content = false,
	diggable = false,
	groups = {not_in_creative_inventory = 1},
	on_blast = function() end,
})

core.register_node(gate.PORTAL, {
	description = "Gate light",
	drawtype = "nodebox",
	paramtype = "light",
	paramtype2 = "facedir",
	node_box = {type = "fixed", fixed = {-0.5, -0.5, -0.12, 0.5, 0.5, 0.12}},
	tiles = {{name = PORTAL_PICTURE, backface_culling = false,
		animation = {type = "vertical_frames", aspect_w = 16, aspect_h = 16, length = 2.4}}},
	use_texture_alpha = "blend",
	sunlight_propagates = true,
	light_source = 9,
	walkable = false,
	pointable = false,
	diggable = false,
	buildable_to = false,
	is_ground_content = false,
	drop = "",
	post_effect_color = {a = 110, r = 110, g = 70, b = 210},
	groups = {not_in_creative_inventory = 1},
	on_blast = function() end,
})

-- The gate's shape as data: offsets along its width (x) and up (y) from the lower left node of
-- its opening; a 2 by 3 opening in a frame one node thick, with a sill under it.
local SHAPE = {
	frame = {
		{-1, -1}, {0, -1}, {1, -1}, {2, -1},
		{-1, 0}, {-1, 1}, {-1, 2}, {-1, 3},
		{2, 0}, {2, 1}, {2, 2}, {2, 3},
		{0, 3}, {1, 3},
	},
	portal = {{0, 0}, {0, 1}, {0, 2}, {1, 0}, {1, 1}, {1, 2}},
}

-- Build a gate whose opening's lower left node is `origin`; `across_x` lays its width along x
-- (people walk through it along z), otherwise along z. The space it stands in, and two nodes in
-- front of and behind it, is cleared first, so it never stands inside a tree or a wall.
function gate.build(origin, across_x, frame_node)
	local frame = frame_node or gate.FRAME
	local function at(offset, depth)
		if across_x then
			return {x = origin.x + offset[1], y = origin.y + offset[2], z = origin.z + (depth or 0)}
		end
		return {x = origin.x + (depth or 0), y = origin.y + offset[2], z = origin.z + offset[1]}
	end
	for width = -2, 3 do
		for height = 0, 4 do
			for depth = -2, 2 do
				core.set_node(at({width, height}, depth), {name = "air"})
			end
		end
	end
	for _, offset in ipairs(SHAPE.frame) do
		core.set_node(at(offset), {name = frame})
	end
	for _, offset in ipairs(SHAPE.portal) do
		core.set_node(at(offset), {name = gate.PORTAL, param2 = across_x and 0 or 1})
	end
end

-- Ground a gate may stand on: a full, walkable node of the world's own terrain. A thin layer
-- (snow, a carpet) or a tree's leaves is not ground; the space the gate clears takes them away.
function gate.solid_ground(definition)
	return definition ~= nil and definition.walkable == true
		and definition.is_ground_content ~= false
		and (definition.drawtype == nil or definition.drawtype == "normal")
end

-- Where to build a gate facing a person at `pos` looking along `yaw`: four nodes ahead of them,
-- on the first solid node below.
function gate.in_front_of(pos, yaw)
	local ahead = {
		x = math.floor(pos.x - math.sin(yaw) * 4 + 0.5),
		z = math.floor(pos.z + math.cos(yaw) * 4 + 0.5),
	}
	local across_x = math.abs(math.cos(yaw)) >= math.abs(math.sin(yaw))
	local y = math.floor(pos.y + 0.5) + 6
	for _ = 1, 24 do
		local node = core.get_node({x = ahead.x, y = y - 1, z = ahead.z})
		if gate.solid_ground(core.registered_nodes[node.name]) then
			break
		end
		y = y - 1
	end
	return {x = ahead.x, y = y, z = ahead.z}, across_x
end

-- Noticing a player walking in: every 0.2 s each player's feet and head are read; the first time
-- either is in a portal, `on_enter(name, portal position, the last position outside)` is called.
-- `players` lists the names to watch; `player_of` gives the object for a name.
function gate.watch(players, player_of, on_enter)
	local outside = {}
	local inside = {}
	local elapsed = 0
	core.register_globalstep(function(dtime)
		elapsed = elapsed + dtime
		if elapsed < 0.2 then
			return
		end
		elapsed = 0
		local seen = {}
		for _, name in ipairs(players()) do
			seen[name] = true
			local player = player_of(name)
			local pos = player and player:get_pos()
			if pos then
				local feet = {
					x = math.floor(pos.x + 0.5), y = math.floor(pos.y + 0.5), z = math.floor(pos.z + 0.5),
				}
				local head = {x = feet.x, y = feet.y + 1, z = feet.z}
				local portal = (core.get_node(feet).name == gate.PORTAL and feet)
					or (core.get_node(head).name == gate.PORTAL and head)
				if portal then
					-- Only a player seen outside first walked in; one who joined standing in the
					-- light steps out and in again to cross.
					if not inside[name] and outside[name] then
						inside[name] = true
						on_enter(name, portal, outside[name])
					end
				else
					inside[name] = nil
					outside[name] = {x = pos.x, y = pos.y, z = pos.z}
				end
			end
		end
		for name in pairs(outside) do
			if not seen[name] then
				outside[name], inside[name] = nil, nil
			end
		end
	end)
end

return gate
