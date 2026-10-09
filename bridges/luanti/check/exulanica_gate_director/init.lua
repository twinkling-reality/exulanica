-- A director for a pictured run of the Exulanica gate: a test mod that walks one real, connected
-- player through the gate and back, so a run with a real client window needs nobody at the
-- keyboard.
--
-- The run's script is not here. check.py appends commands to
-- <world>/exulanica_gate_director/commands.jsonl, one JSON object a line with an increasing "n";
-- the director carries out each in turn and answers in done.jsonl beside it, where it also writes
-- when the player joins and leaves. While it directs, the player's own movement is held (physics
-- speed and jump 0), so keys pressed in the window move nobody; the director moves the player by
-- setting their position, and the gate mod notices their feet in its light as it would anyone's.
-- What the player is told in chat goes to told.jsonl, for the run to hold against the lines said in
-- the world. The server's own status line and the join announcement are not sent to that player:
-- they say nothing of the crossing, and the status line names the server's game. Loaded only in
-- the worlds check.py makes for --pictures; the gate is found in the map, and every item and
-- command comes from a command, so nothing here names a game.

local modname = core.get_current_modname()
local player_name = core.settings:get(modname .. ".player") or ""
local folder = core.get_worldpath() .. "/" .. modname
core.mkdir(folder)
local COMMANDS = folder .. "/commands.jsonl"
local DONE = folder .. "/done.jsonl"
local TOLD = folder .. "/told.jsonl"
local PORTAL = "exulanica_gate:portal"
local INVENTORY_FORM = modname .. ":inventory"
-- How far around the spawn point the gate is looked for, in nodes.
local REACH = {x = 16, y = 32, z = 16}
local started = core.get_us_time()

local function now_ms()
	return math.floor((core.get_us_time() - started) / 1000)
end

local function append(path, document)
	document.t_ms = now_ms()
	local line = core.write_json(document)
	local file = line and io.open(path, "a")
	if file then
		file:write(line, "\n")
		file:close()
	end
end

local function answer(command, ok, detail, extra)
	local document = {n = command.n, act = command.act, ok = ok == true, detail = detail}
	for key, value in pairs(extra or {}) do
		document[key] = value
	end
	append(DONE, document)
end

-- Every line the player is told in chat, recorded as it is sent.
local chat_send_player = core.chat_send_player
function core.chat_send_player(name, text)
	if name == player_name then
		append(TOLD, {told = text})
	end
	return chat_send_player(name, text)
end

local get_server_status = core.get_server_status
function core.get_server_status(name, joined)
	if joined and name == player_name then
		return ""
	end
	return get_server_status(name, joined)
end

local send_join_message = core.send_join_message
function core.send_join_message(name)
	if name ~= player_name then
		return send_join_message(name)
	end
end

core.register_on_joinplayer(function(player)
	if player:get_player_name() == player_name then
		append(DONE, {event = "joined"})
	end
end)

core.register_on_leaveplayer(function(player)
	if player:get_player_name() == player_name then
		append(DONE, {event = "left"})
	end
end)

-- The gate's opening, read from the map: its light's nodes near the spawn point, the middle of its
-- floor, and the way a person walks through it (from the spawn point's side).
local function opening()
	local spawn = core.settings:get_pos("static_spawnpoint") or vector.new(0, 10, 0)
	local found = core.find_nodes_in_area(vector.subtract(spawn, REACH), vector.add(spawn, REACH),
		{PORTAL})
	if #found == 0 then
		return nil
	end
	local low, high = vector.copy(found[1]), vector.copy(found[1])
	for _, pos in ipairs(found) do
		low = vector.new(math.min(low.x, pos.x), math.min(low.y, pos.y), math.min(low.z, pos.z))
		high = vector.new(math.max(high.x, pos.x), math.max(high.y, pos.y), math.max(high.z, pos.z))
	end
	local middle = vector.new((low.x + high.x) / 2, low.y - 0.5, (low.z + high.z) / 2)
	local across_x = high.x > low.x
	local way
	if across_x then
		way = vector.new(0, 0, middle.z >= spawn.z and 1 or -1)
	else
		way = vector.new(middle.x >= spawn.x and 1 or -1, 0, 0)
	end
	return {middle = middle, way = way}
end

-- The yaw that looks along `way`: yaw 0 looks along +z, and the look turns towards -x as it grows.
local function yaw_along(way)
	return math.atan2(-way.x, way.z)
end

local function look(player, way, pitch_deg)
	player:set_look_horizontal(yaw_along(way))
	player:set_look_vertical(math.rad(pitch_deg or 0))
end

-- How far past the middle of the light a position is, along the way through it.
local function along(gate, pos)
	return (pos.x - gate.middle.x) * gate.way.x + (pos.z - gate.middle.z) * gate.way.z
end

local walking

local acts = {}

function acts.hold(player, command)
	player:set_physics_override({speed = 0, jump = 0})
	answer(command, true)
end

function acts.release(player, command)
	player:set_physics_override({speed = 1, jump = 1})
	answer(command, true)
end

-- Stand `distance` nodes before the gate, facing it.
function acts.stand(player, command)
	local gate = opening()
	if not gate then
		answer(command, false, "no gate near the spawn point")
		return
	end
	local distance = tonumber(command.distance) or 3.5
	player:set_pos(vector.subtract(gate.middle, vector.multiply(gate.way, distance)))
	look(player, gate.way, command.pitch_deg)
	answer(command, true, nil, {pos = player:get_pos()})
end

-- Walk into the light at `speed` nodes a second, until the gate puts the player on its far side.
function acts.walk_in(player, command)
	local gate = opening()
	if not gate then
		answer(command, false, "no gate near the spawn point")
		return
	end
	walking = {command = command, gate = gate, speed = tonumber(command.speed) or 4,
		ends = now_ms() + 1000 * (tonumber(command.limit_s) or 10)}
end

-- Turn round to face the gate from its far side, first walking on to `distance` nodes past its
-- middle when given.
function acts.look_back(player, command)
	local gate = opening()
	if not gate then
		answer(command, false, "no gate near the spawn point")
		return
	end
	local distance = tonumber(command.distance)
	if distance then
		player:set_pos(vector.add(gate.middle, vector.multiply(gate.way, distance)))
	end
	look(player, vector.multiply(gate.way, -1), command.pitch_deg)
	answer(command, true, nil, {pos = player:get_pos()})
end

-- Take the named item into the hand, from wherever it is in the player's main inventory.
function acts.wield(player, command)
	local inventory = player:get_inventory()
	local hand = player:get_wield_index()
	for index, stack in ipairs(inventory:get_list("main") or {}) do
		if stack:get_name() == command.item then
			if index ~= hand then
				local held = inventory:get_stack("main", hand)
				inventory:set_stack("main", hand, stack)
				inventory:set_stack("main", index, held)
			end
			answer(command, true)
			return
		end
	end
	answer(command, false, "not in the inventory")
end

-- What the player's main inventory holds, by item name and count.
function acts.contents(player, command)
	local held = {}
	for _, stack in ipairs(player:get_inventory():get_list("main") or {}) do
		if not stack:is_empty() then
			held[#held + 1] = {item = stack:get_name(), count = stack:get_count()}
		end
	end
	answer(command, true, nil, {contents = held})
end

-- Open the player's own inventory form, as their inventory key would.
function acts.inventory(player, command)
	local form = player:get_inventory_formspec()
	if form == "" then
		form = "formspec_version[6]size[10.5,5.4]list[current_player;main;0.4,0.4;8,4;]"
	end
	core.show_formspec(player_name, INVENTORY_FORM, form)
	answer(command, true)
end

function acts.close(player, command)
	core.close_formspec(player_name, INVENTORY_FORM)
	answer(command, true)
end

-- Run one of the server's chat commands as the player, and tell them what it answers, as typing it
-- would.
function acts.command(player, command)
	local definition = core.registered_chatcommands[tostring(command.name)]
	if not definition then
		answer(command, false, "no such command")
		return
	end
	local ok, said = definition.func(player_name, command.param or "")
	if said then
		core.chat_send_player(player_name, said)
	end
	answer(command, ok ~= false, said)
end

local function walk_on(player, dtime)
	local command, gate = walking.command, walking.gate
	local pos = player:get_pos()
	-- The gate put the player through: more than a node past the light.
	if along(gate, pos) > 0.9 then
		walking = nil
		answer(command, true, "through", {pos = pos})
		return
	end
	if now_ms() > walking.ends then
		walking = nil
		answer(command, false, "not put through in time", {pos = pos})
		return
	end
	-- Never past the light's middle by more than a little: the gate's watch notices feet in the
	-- light and puts the player through.
	local step = math.min(walking.speed * dtime, 0.3 - along(gate, pos))
	if step > 0 then
		player:set_pos(vector.new(pos.x + gate.way.x * step, gate.middle.y,
			pos.z + gate.way.z * step))
	end
end

local next_n = 1

local function next_command()
	local file = io.open(COMMANDS, "r")
	if not file then
		return nil
	end
	local found
	for line in file:lines() do
		local command = core.parse_json(line)
		if type(command) == "table" and command.n == next_n then
			found = command
			break
		end
	end
	file:close()
	return found
end

local elapsed = 0
core.register_globalstep(function(dtime)
	local player = player_name ~= "" and core.get_player_by_name(player_name)
	if not player then
		return
	end
	if walking then
		walk_on(player, dtime)
		return
	end
	elapsed = elapsed + dtime
	if elapsed < 0.1 then
		return
	end
	elapsed = 0
	local command = next_command()
	if not command then
		return
	end
	next_n = next_n + 1
	local act = acts[tostring(command.act)]
	if not act then
		answer(command, false, "no such act")
		return
	end
	act(player, command)
end)
