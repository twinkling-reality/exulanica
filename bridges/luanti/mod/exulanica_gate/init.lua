-- exulanica_gate: a gate from a Luanti world into an Exulanica world, through the door.
--
-- Wiring only: settings and the environment are read once here, the engine's HTTP table and the
-- credentials stay in locals of this file and the channel closures it makes, and every callback
-- is registered here. The mod uses the engine's own API and nothing of any game, so one mod serves
-- every Luanti game; what a game's items become is its mapping file (mapping/), which is data.

local modname = core.get_current_modname()
local modpath = core.get_modpath(modname)

-- Only in the main scope at load, and never handed to another mod.
local http = core.request_http_api()
local server_credential = os.getenv("EXULANICA_GATE_CHANNEL_CREDENTIAL")
local bridge_credential = os.getenv("EXULANICA_GATE_BRIDGE_CREDENTIAL")

local function load(name)
	return dofile(modpath .. "/" .. name .. ".lua")
end

local json = load("json")
local store = load("store")
local engine = load("engine")
local lines = load("lines")
local gate = load("gate")
local channel = load("channel")
local panel = load("panel")
local journey = load("journey")
local crossing = load("crossing")
local record = load("record")

local function log(form, ...)
	core.log("action", "[" .. modname .. "] " .. string.format(form, ...))
end

local function setting(name, default)
	local value = core.settings:get(modname .. "." .. name)
	if value == nil or value == "" then
		return default
	end
	return value
end

local settings = {
	door_url = (setting("door_url", ""):gsub("/+$", "")),
	world_words = setting("world_words", "The world beyond the gate"),
	mapping = setting("mapping", "luanti-minetest-game.v2.json"),
	allowed_players = setting("allowed_players", ""),
	frame_node = setting("frame_node", ""),
	gate_at_spawn = core.settings:get_bool(modname .. ".gate_at_spawn", false),
	record_exchanges = core.settings:get_bool(modname .. ".record_exchanges", false),
	check_mode = core.settings:get_bool(modname .. ".check_mode", false),
}

-- A door address the mod will send a credential to: HTTPS anywhere, plain HTTP only on this
-- machine.
local function door_url_allowed(url)
	if url:match("^https://[%w%.%-]+:?%d*[/%w%._~%-]*$") then
		return true
	end
	return url:match("^http://127%.0%.0%.1:?%d*[/%w%._~%-]*$") ~= nil
		or url:match("^http://localhost:?%d*[/%w%._~%-]*$") ~= nil
end

local function read_file(path)
	local file = io.open(path, "rb")
	if not file then
		return nil
	end
	local text = file:read("*a")
	file:close()
	return text
end

local adapter = assert(json.parse(read_file(modpath .. "/adapter.json")),
	"adapter.json is the adapter's declaration")
assert(settings.mapping:match("^[a-z0-9][a-z0-9.%-]*%.json$"),
	modname .. ".mapping names a file in the mod's mapping folder")
local mapping_text = assert(read_file(modpath .. "/mapping/" .. settings.mapping),
	"no mapping file " .. settings.mapping)
local mapping = assert(json.parse(mapping_text), "the mapping file is JSON")

-- The game fields this adapter reads: the declared ones and every item its mapping lists.
local reads = {}
for _, field in ipairs(adapter.reads) do
	reads[#reads + 1] = field
end
for _, item in ipairs(mapping.items or {}) do
	reads[#reads + 1] = item.game_item
end

-- What the mapping says of one game item, and of one kind of game character.
local items_by_name = {}
for _, item in ipairs(mapping.items or {}) do
	items_by_name[item.game_item] = item
end
local function mapping_item(game_item)
	return items_by_name[game_item]
end
local function mapping_visitor(game_type)
	for _, visitor in ipairs(mapping.visitors or {}) do
		if visitor.game_type == game_type then
			return visitor
		end
	end
	return nil
end

-- Arrival ids come from the operating system's secure random source.
local secure_random = SecureRandom()

store.init(core.get_mod_storage())
engine.init({check_mode = settings.check_mode})
record.init(settings.record_exchanges)

-- Channels, one per grant: the server's own (its credential from the environment) and any a
-- player's invite opened.
local channels = {}
local server_channel

local function channel_of(grant_id)
	return grant_id and channels[grant_id] or nil
end

local function channel_for(name)
	local mine = store.get("player-grant:" .. name)
	if mine and channels[mine.grant_id] then
		return channels[mine.grant_id]
	end
	return server_channel
end

local deps = {
	json = json,
	store = store,
	engine = engine,
	lines = lines,
	panel = panel,
	record = record,
	settings = settings,
	channel_of = channel_of,
	channel_for = channel_for,
	mapping_item = mapping_item,
	mapping_visitor = mapping_visitor,
	adapter_looks = {
		by_texture = adapter.looks and adapter.looks.by_texture or {},
		otherwise = adapter.looks and adapter.looks.otherwise or "",
	},
	random = function(count)
		return secure_random:next_bytes(count)
	end,
	journey = journey,
	crossing = crossing,
}
journey.init(deps)
crossing.init(deps)

-- Frames ------------------------------------------------------------------------------------------

local function on_frames(chan, frames)
	for _, frame in ipairs(frames) do
		local kind = frame.kind
		if kind == "grant" then
			if chan.grant then
				chan.grant.scope = frame.scope
				chan.grant.grant_seq = frame.grant_seq
				local scope = type(frame.scope) == "table" and frame.scope or {}
				chan.world_words = type(scope.world_words) == "string" and scope.world_words or nil
			end
		elseif kind == "grant_ended" then
			journey.grant_ended(chan.grant and chan.grant.grant_id, frame.reason)
		elseif crossing.handles(kind) then
			crossing.frame(chan, frame)
		else
			-- Asks and outcomes included: the world decides for a character that crossed.
			record.mark("frame_ignored", {kind = tostring(kind), request = frame.request_id})
		end
	end
end

local function open_channel(credential, label)
	local chan = channel.open({
		http = http,
		json = json,
		door_url = settings.door_url,
		credential = credential,
		adapter_version = adapter.adapter_version,
		mapping_text = mapping_text,
		reads = reads,
		log = log,
		record = record.exchange,
		on_hello = function(opened)
			channels[opened.grant.grant_id] = opened
		end,
		on_frames = on_frames,
		on_ended = function(ended, reason)
			local grant_id = ended.grant and ended.grant.grant_id
			journey.grant_ended(grant_id, reason)
			log("%s gate closed: %s", label, reason)
		end,
	})
	chan.start()
	return chan
end

-- Invites and the gate ----------------------------------------------------------------------------

-- Invites: a code a world's owner gave a player opens that world's gate for them. The code is
-- pasted into a masked field (a chat command's parameters reach the engine's log), redeemed with
-- this server's own bridge credential, and never written, logged or recorded; the door is told who
-- asked only as a digest of this server's secret and the player's name, which names nobody.
local INVITE_FORM = modname .. ":invite"

local function requester(name)
	local kept = store.get("requester-secret")
	if not kept then
		local bytes = {secure_random:next_bytes(32):byte(1, 32)}
		for index, byte in ipairs(bytes) do
			bytes[index] = string.format("%02x", byte)
		end
		kept = {secret = table.concat(bytes)}
		store.put("requester-secret", kept)
	end
	return core.sha256(kept.secret .. ":" .. name)
end

local function redeemed(name, code, answer)
	if code == 201 and type(answer) == "table" and type(answer.credential) == "string"
			and type(answer.grant) == "table" then
		local grant_id = answer.grant.grant_id
		-- A grant has one live credential: the newest replaces any this server kept.
		local older = channels[grant_id]
		if older then
			older.stop()
			channels[grant_id] = nil
		end
		store.put("channel:" .. grant_id, {credential = answer.credential, opened_at = os.time()})
		store.put("player-grant:" .. name, {grant_id = grant_id})
		open_channel(answer.credential, "an invite's")
		engine.tell(name, "The gate is open for you. Walk through it.")
		return
	end
	local refusal = type(answer) == "table" and answer.code or nil
	if refusal == "too_many_redemptions" then
		engine.tell(name, "Too many tries; wait a minute and try again.")
	elseif code == 0 then
		engine.tell(name, "The world could not be reached; try again in a moment.")
	else
		engine.tell(name, "That code opens nothing here: it may be mistyped, used or out of time.")
	end
end

local function on_invite(name, fields)
	if not (fields.exg_open or fields.key_enter_field == "exg_code") then
		return
	end
	local code = type(fields.exg_code) == "string" and fields.exg_code or ""
	if #code < 4 or #code > 40 then
		engine.tell(name, "Paste the whole code your world shows.")
		return
	end
	channel.redeem({http = http, json = json, door_url = settings.door_url,
		bridge_credential = bridge_credential}, code, requester(name), function(status, answer)
		redeemed(name, status, answer)
	end)
end

core.register_chatcommand("cross", {
	description = "Open the gate to a world with the code its owner gave you",
	func = function(name)
		if not (http and bridge_credential and bridge_credential ~= "") then
			return false, "This server's gate does not take codes."
		end
		engine.show_form(name, INVITE_FORM, table.concat({
			"formspec_version[6]",
			"size[9,3.7]",
			"label[0.5,0.6;" .. core.formspec_escape("Paste the code your world shows:") .. "]",
			"pwdfield[0.5,1.1;8,0.8;exg_code;]",
			"button_exit[0.5,2.4;3.6,0.8;exg_open;" .. core.formspec_escape("Open the gate") .. "]",
			"button_exit[5.4,2.4;3.1,0.8;exg_cancel;Cancel]",
		}))
		return true
	end,
})

-- Not /home: Minetest Game's own sethome mod names a player's home point so, and the gate takes
-- nothing away from a game.
core.register_chatcommand("comehome", {
	description = "Call your character home from the world it is in",
	func = function(name)
		return crossing.call_home(name)
	end,
})

core.register_on_player_receive_fields(function(player, formname, fields)
	local name = player:get_player_name()
	if formname == INVITE_FORM then
		on_invite(name, fields)
		return true
	end
	return false
end)

core.register_on_joinplayer(function(player)
	journey.joined(player:get_player_name())
end)

core.register_on_leaveplayer(function(player)
	journey.left(player:get_player_name())
end)

local allowed = {}
for name in settings.allowed_players:gmatch("[^,%s]+") do
	allowed[name:lower()] = true
end
if next(allowed) then
	core.register_on_prejoinplayer(function(name)
		if not allowed[name:lower()] then
			return "This is a private server."
		end
	end)
end

local frame_node
core.register_on_mods_loaded(function()
	if settings.frame_node ~= "" and core.registered_nodes[settings.frame_node] then
		frame_node = settings.frame_node
	end
end)

gate.watch(engine.connected, engine.player, function(name, portal, outside)
	journey.enter(name, portal, outside)
end)

core.register_chatcommand("gate", {
	params = "here",
	privs = {server = true},
	description = "Build a gate in front of you",
	func = function(name, param)
		if param ~= "here" then
			return false, "Type /gate here to build a gate in front of you."
		end
		local player = core.get_player_by_name(name)
		if not player then
			return false, "Only a player in the world can build a gate."
		end
		local origin, across_x = gate.in_front_of(player:get_pos(), player:get_look_horizontal())
		gate.build(origin, across_x, frame_node)
		return true, "A gate stands in front of you."
	end,
})

-- The demo world's gate: built once, five nodes in front of the static spawn point.
local function gate_at_spawn()
	if store.get("gate") then
		return
	end
	local spawn = core.settings:get_pos("static_spawnpoint") or {x = 0, y = 10, z = 0}
	local column = {x = math.floor(spawn.x + 0.5), y = math.floor(spawn.y + 0.5),
		z = math.floor(spawn.z + 0.5) + 5}
	core.emerge_area(vector.subtract(column, 24), vector.add(column, 24),
		function(_, _, remaining)
			if remaining > 0 or store.get("gate") then
				return
			end
			local y = column.y + 16
			while y > column.y - 32 do
				local below = core.registered_nodes[core.get_node({x = column.x, y = y - 1,
					z = column.z}).name]
				if gate.solid_ground(below) then
					break
				end
				y = y - 1
			end
			local origin = {x = column.x, y = y, z = column.z}
			gate.build(origin, true, frame_node)
			store.put("gate", {pos = origin})
			log("gate built at %s", core.pos_to_string(origin))
		end)
end

-- Start ------------------------------------------------------------------------------------------

local function start()
	if settings.gate_at_spawn then
		gate_at_spawn()
	end
	if not http then
		log("not connected: the server's secure.http_mods setting must list %s", modname)
		return
	end
	if not door_url_allowed(settings.door_url) then
		log("not connected: %s.door_url must be https, or http on this machine", modname)
		return
	end
	if server_credential and server_credential ~= "" then
		server_channel = open_channel(server_credential, "the server's")
	else
		log("no channel credential in the environment; the gate opens only by invites")
	end
	for _, key in ipairs(store.keys("channel:")) do
		local kept = store.get(key)
		if kept and type(kept.credential) == "string" then
			open_channel(kept.credential, "an invite's")
		end
	end
end

core.after(0.5, start)

local since_tick = 0
core.register_globalstep(function(dtime)
	since_tick = since_tick + dtime
	if since_tick >= 5 then
		since_tick = 0
		crossing.tick()
	end
end)

core.register_on_shutdown(function()
	for name in pairs(journey.all()) do
		journey.left(name)
	end
	for _, chan in pairs(channels) do
		chan.stop()
	end
	if server_channel then
		server_channel.stop()
	end
end)

-- What other mods see: the adapter's version. A check run (and only a check run) also gets the
-- handlers a person's actions reach, so a test mod can play a player on a headless server.
exulanica_gate = {adapter_version = adapter.adapter_version}

if settings.check_mode then
	exulanica_gate.check = {
		add_stand_in = engine.add_stand_in,
		remove_stand_in = engine.remove_stand_in,
		left = journey.left,
		joined = journey.joined,
		journey = journey.record_of,
		lines = lines,
		reads = reads,
		picture_bytes = gate.picture_bytes,
		-- The server's own channel, else the first an invite opened.
		state = function()
			local chan = server_channel
			if not chan then
				for _, opened in pairs(channels) do
					chan = opened
					break
				end
			end
			if not chan then
				return nil
			end
			return {state = chan.state, grant = chan.grant, hold_seconds = chan.hold_seconds,
				world_words = chan.world_words}
		end,
		build_gate = function(origin, across_x)
			gate.build(origin, across_x, frame_node)
		end,
		listen = function(listener)
			record.listener = listener
		end,
	}
	log("check mode: stand-in players allowed")
end
