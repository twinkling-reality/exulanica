-- A check run of the Exulanica gate on a headless server: a test mod that plays a player.
--
-- It registers stand-in players behind the gate mod's engine seam (a name, a real engine inventory,
-- a position, and a record of what a person would have been told and shown), then walks one of
-- them into a gate and plays a script through the same handlers a person's actions reach: the gate
-- noticing feet in its light, leaving the game and joining again. Each step's verdict and timing
-- goes to <world>/exulanica_gate_check/result.json, and the server stops. Loaded only in check
-- worlds; the gate mod refuses stand-ins unless exulanica_gate.check_mode is set.

local modpath = core.get_modpath(core.get_current_modname())
local check = assert(exulanica_gate and exulanica_gate.check,
	"a check run needs exulanica_gate.check_mode = true")

local started = core.get_us_time()
local function now_ms()
	return math.floor((core.get_us_time() - started) / 1000)
end

local result = {profile = "exulanica-gate.check-result/v1", adapter_version =
	exulanica_gate.adapter_version, checks = {}, timings = {}, chosen = nil}

local function verdict(name, ok, detail)
	result.checks[#result.checks + 1] = {check = name, ok = ok == true, detail = detail,
		at_ms = now_ms()}
	core.log("action", string.format("[exulanica_gate_check] %s %s%s", ok and "PASS" or "FAIL",
		name, detail and (": " .. tostring(detail)) or ""))
end

local function write_result()
	local folder = core.get_worldpath() .. "/exulanica_gate_check"
	core.mkdir(folder)
	local file = assert(io.open(folder .. "/result.json", "w"))
	file:write(core.write_json(result, true))
	file:close()
end

-- A stand-in player: the player methods the gate mod calls, over a real detached inventory.
local StandIn = {}
StandIn.__index = StandIn

local function stand_in(name, pos)
	local inventory = core.create_detached_inventory("exulanica_gate_check_" .. name, {
		allow_move = function() return 0 end,
		allow_put = function() return 0 end,
		allow_take = function() return 0 end,
	})
	inventory:set_size("main", 32)
	local object = setmetatable({
		name = name, pos = vector.new(pos), inventory = inventory, wield = 1, yaw = 0,
		physics = {speed = 1, jump = 1, gravity = 1}, huds = {}, next_hud = 1,
		inventory_form = "the game's own inventory form", heard = {}, forms = {},
	}, StandIn)
	check.add_stand_in(name, object)
	return object
end

function StandIn:get_player_name() return self.name end
function StandIn:get_pos() return vector.new(self.pos) end
function StandIn:set_pos(pos) self.pos = vector.new(pos) end
function StandIn:get_inventory() return self.inventory end
function StandIn:get_wield_index() return self.wield end
function StandIn:get_wielded_item() return self.inventory:get_stack("main", self.wield) end
function StandIn:set_wielded_item(stack)
	self.inventory:set_stack("main", self.wield, stack)
	return true
end
function StandIn:get_physics_override()
	return {speed = self.physics.speed, jump = self.physics.jump, gravity = self.physics.gravity}
end
function StandIn:set_physics_override(override)
	for key, value in pairs(override) do
		self.physics[key] = value
	end
end
function StandIn:hud_add(definition)
	local id = self.next_hud
	self.next_hud = id + 1
	self.huds[id] = table.copy(definition)
	return id
end
function StandIn:hud_change(id, stat, value)
	if self.huds[id] then
		self.huds[id][stat] = value
	end
end
function StandIn:hud_remove(id) self.huds[id] = nil end
function StandIn:get_inventory_formspec() return self.inventory_form end
function StandIn:set_inventory_formspec(formspec) self.inventory_form = formspec end
function StandIn:get_look_horizontal() return self.yaw end
-- The game's own player picture, as Minetest Game's player model wears it.
function StandIn:get_properties() return {textures = {"character.png"}} end
function StandIn:set_look_horizontal(yaw) self.yaw = yaw end
function StandIn:told(text) self.heard[#self.heard + 1] = text end
function StandIn:shown(formname, formspec) self.forms[#self.forms + 1] = {formname, formspec} end

function StandIn:heard_since(index, pattern)
	for at = index + 1, #self.heard do
		if self.heard[at]:find(pattern, 1, true) then
			return self.heard[at]
		end
	end
	return nil
end

-- What the gate mod marks: arrivals, departures, deliveries, frames it leaves to the world.
local marks = {}
check.listen(function(what, details)
	marks[#marks + 1] = {what = what, details = table.copy(details), at_ms = now_ms()}
end)

local function mark_since(index, what, test)
	for at = index + 1, #marks do
		local mark = marks[at]
		if mark.what == what and (not test or test(mark.details)) then
			return mark, at
		end
	end
	return nil
end

-- Pure checks, before any player ------------------------------------------------------------------

local function pure_checks()
	local plain = check.lines.incoming("a \27(c@#ff0000)red\27E line\nwith a break\226\128\174 and more", 200)
	verdict("a world's words are shown as plain text",
		plain == "a red line with a break and more" or plain == "a red linewith a break and more",
		plain)
	local long = check.lines.incoming(string.rep("a", 300), 80)
	verdict("a world's words are bounded", #long == 80 and long:sub(-3) == "...")
	local bytes = check.picture_bytes
	verdict("the gate's pictures are drawn in code and small", bytes > 0 and bytes < 20000,
		bytes .. " bytes of inline pictures")
	verdict("the adapter reads what its mapping accounts for", #check.reads >= 10,
		#check.reads .. " game fields")
end

-- The script ---------------------------------------------------------------------------------------

local steps = {}
local function step(name, timeout_s, run)
	steps[#steps + 1] = {name = name, timeout_s = timeout_s, run = run}
end

local function count(inventory, item)
	local found = 0
	for _, stack in ipairs(inventory:get_list("main")) do
		if stack:get_name() == item then
			found = found + stack:get_count()
		end
	end
	return found
end

-- The line the gate mod shows a player while their character is away, or nil.
local function line_shown(stand)
	for _, hud in pairs(stand.huds) do
		if hud.type == "text" then
			return hud.text
		end
	end
	return nil
end

local player, gate_origin
local GAME_FORM = "the game's own inventory form"
-- crossing: a player's character crosses into a world against the stand-in door
-- (tools/fake_door.py), which plays the world's side: it asks about the character (left to the
-- world), and its character leaves with a sword it was given;
-- crossing_door: the same crossing against the door itself, whose world's owner (check.py) sends
-- the character home and later closes the gate;
-- crossing_invite: the gate opened by an invite code the player types into /cross (the server has
-- no channel credential of its own), then one crossing, sent home by the world's owner.
local scenario = core.settings:get("exulanica_gate_check.scenario") or "crossing_door"
result.scenario = scenario
-- Read once, in a check world only; typed into the form as a player pastes it, never logged.
local invite_code = scenario == "crossing_invite" and os.getenv("EXULANICA_GATE_CHECK_INVITE") or nil
-- Forms shown before the player walks in (an invite's form): none may be added while away.
local forms_at_walk = 0

-- Submit the form last shown to a stand-in, through the handlers a person's submission reaches.
local function submit_form(stand, fields)
	local shown = stand.forms[#stand.forms]
	if not shown then
		return false
	end
	for _, handler in ipairs(core.registered_on_player_receive_fields) do
		if handler(stand, shown[1], fields) then
			return true
		end
	end
	return false
end

-- A player types /cross and pastes a code into the form it opens.
local function type_code(stand, code)
	if core.registered_chatcommands.cross.func(stand.name) == false then
		return false
	end
	return submit_form(stand, {exg_open = "Open the gate", exg_code = code})
end

if scenario == "crossing_invite" then
	step("a server with no credential of its own opens no gate until a code is typed", 10, function()
		player = player or stand_in("checker", {x = 0.5, y = 9, z = 2})
		verdict("a server with no credential of its own opens no gate until a code is typed",
			check.state() == nil and type(invite_code) == "string")
		return true
	end)

	-- Each typed code is answered in words once the door answers: wait for the words.
	local function code_step(name, code_of, words_expected)
		local heard_from
		step(name, 30, function()
			if not heard_from then
				heard_from = #player.heard
				type_code(player, code_of())
				return false
			end
			local words = player:heard_since(heard_from, words_expected)
			if words then
				verdict(name, true, words)
				return true
			end
		end)
	end
	-- Not shaped as an invite at all: the door answers a malformed code as it answers an unknown one.
	code_step("a code that opens nothing is refused in words", function()
		return "no such code"
	end, "That code opens nothing here")
	code_step("the code the world's owner gave opens the gate for this player", function()
		return invite_code
	end, "The gate is open for you")
	code_step("a code opens a gate once", function()
		return invite_code
	end, "That code opens nothing here")
end

step("the server's channel said hello and polls", 90, function()
	local state = check.state()
	if state and state.state == "polling" then
		result.timings.channel_ready_ms = now_ms()
		result.grant_visitors = tonumber(state.grant.scope.visitors_maximum) or 0
		result.world_words = state.world_words
		result.visitors_decided_by = state.grant.scope.visitors_decided_by or "program"
		verdict("the server's channel said hello and polls", true,
			"hold " .. state.hold_seconds .. " s")
		return true
	end
end)

-- The world's own words for itself come with the grant, and everything the player is told about
-- where their character went says them.
step("the grant lets a traveller in", 1, function()
	local ok = (result.grant_visitors or 0) >= 1 and type(result.world_words) == "string"
	verdict("the grant lets a traveller in", ok, result.grant_visitors .. " at a time, into "
		.. tostring(result.world_words))
	return ok or "stop"
end)

-- A headless server has no players to load the map around them, so the check loads the gate's
-- ground itself and keeps it loaded.
local ground_ready = false
step("the gate's ground is loaded", 60, function()
	if ground_ready == false then
		ground_ready = "waiting"
		gate_origin = {x = 0, y = 9, z = 6}
		core.emerge_area(vector.subtract(gate_origin, 16), vector.add(gate_origin, 16),
			function(_, _, remaining)
				if remaining == 0 then
					ground_ready = true
				end
			end)
		return false
	end
	if ground_ready == true then
		core.forceload_block(gate_origin, true)
		verdict("the gate's ground is loaded", true)
		return true
	end
end)

-- Walking in: the stand-in steps from outside the gate into its light, with five torches in hand.
local function walk_in(stand)
	stand:set_pos({x = 0.5, y = 9, z = 2})
	core.after(0.5, function()
		stand:set_pos({x = 0, y = 8.5, z = 6})
	end)
end

local walked_at
step("a player walks into the gate: one torch goes with their character, and they play on", 20,
	function()
		if not (player and player.ready) then
			check.build_gate(gate_origin, true)
			player = player or stand_in("checker", {x = 0.5, y = 9, z = 2})
			player.inventory:set_stack("main", 1, ItemStack("default:torch 5"))
			player.ready = true
			return false
		end
		if not walked_at then
			walked_at = now_ms()
			forms_at_walk = #player.forms
			walk_in(player)
			return false
		end
		local sent = mark_since(0, "arrival_sent")
		local journey = check.journey("checker")
		if not (sent and journey) then
			return false
		end
		result.timings.walk_in_to_arrival_sent_ms = sent.at_ms - walked_at
		local shown = line_shown(player) or ""
		verdict("a player walks into the gate: one torch goes with their character, and they play on",
			player.inventory:get_stack("main", 1):get_count() == 4 and player.physics.speed == 1
				and player.physics.jump == 1 and player.inventory_form == GAME_FORM
				and player:get_pos().z > gate_origin.z + 1
				and #player.forms == forms_at_walk
				and shown:find("Your character is crossing into " .. result.world_words, 1, true) ~= nil,
			"four torches stay in the hand; out the far side, not held; no menu; the line: " .. shown)
		return true
	end)

step("the character arrives carrying a lantern, and the player is told once", 60, function()
	local journey = check.journey("checker")
	if not (journey and journey.state == "across") then
		return false
	end
	local arrived = mark_since(0, "arrived")
	result.timings.walk_in_to_arrived_ms = arrived.at_ms - walked_at
	local told = player:heard_since(0, "Your character is in " .. result.world_words
		.. ", carrying a lantern (your torch:")
	local shown = line_shown(player) or ""
	verdict("the character arrives carrying a lantern, and the player is told once",
		told ~= nil and arrived.details.kind == "carried"
			and shown == "Your character is in " .. result.world_words,
		told)
	verdict("a world that cannot show the own look yet gets the free look, and the player is told",
		player:heard_since(0, "This world cannot show your own look yet") ~= nil)
	return true
end)

-- Who decides for the character is the world's: where the grant says so, no ask about it reaches the
-- gate at all; where the door still names the bridge, the asks come and the gate leaves them alone.
local asked_frame = function(details)
	return details.kind == "asked"
end
step("the world decides for the character: the gate answers no ask about it", 120, function()
	if result.visitors_decided_by == "world" then
		local arrived = mark_since(0, "arrived")
		if not arrived or now_ms() - arrived.at_ms < 20000 then
			return false
		end
		verdict("the world decides for the character: the gate answers no ask about it",
			mark_since(0, "frame_ignored", asked_frame) == nil and #player.forms == forms_at_walk,
			"the world decides; no ask reached the gate")
		return true
	end
	if not mark_since(0, "frame_ignored", asked_frame) then
		return false
	end
	verdict("the world decides for the character: the gate answers no ask about it",
		mark_since(0, "answered") == nil and #player.forms == forms_at_walk,
		"the door named the gate; its asks were left to the world")
	return true
end)

local home_from
if scenario == "crossing" then
	step("the character comes home with the torch and the sword it was given", 120, function()
		if check.journey("checker") ~= nil then
			return false
		end
		home_from = #marks
		local words = player:heard_since(0, "Your character came back from " .. result.world_words
			.. ", carrying a torch and a steel sword.")
		verdict("the character comes home with the torch and the sword it was given",
			count(player.inventory, "default:torch") == 5
				and count(player.inventory, "default:sword_steel") == 1
				and words ~= nil and line_shown(player) == nil,
			tostring(words))
		result.timings.walk_in_to_home_ms = now_ms() - walked_at
		return true
	end)
else
	step("sent home by the world's owner, the character brings back the torch", 180, function()
		if check.journey("checker") ~= nil then
			return false
		end
		home_from = #marks
		local words = player:heard_since(0, "Your character was sent back from "
			.. result.world_words .. ", carrying a torch.")
		verdict("sent home by the world's owner, the character brings back the torch",
			count(player.inventory, "default:torch") == 5 and words ~= nil
				and line_shown(player) == nil,
			tostring(words))
		result.timings.walk_in_to_home_ms = now_ms() - walked_at
		return true
	end)
end

local settled_from
step("the departure is delivered once, and reported", 20, function()
	settled_from = settled_from or now_ms()
	if now_ms() - settled_from < 6000 then
		return false
	end
	local departed, reported = 0, mark_since(0, "delivered", function(details)
		return details.status == 202
	end)
	for _, mark in ipairs(marks) do
		if mark.what == "departed" then
			departed = departed + 1
		end
	end
	verdict("the departure is delivered once, and reported",
		departed == 1 and reported ~= nil and count(player.inventory, "default:torch") == 5,
		departed .. " departure, report " .. tostring(reported and reported.details.status))
	return true
end)

local again
if scenario ~= "crossing_invite" then
step("a player who leaves the game while their character is away is told on return", 240,
	function()
		if not again then
			again = {stage = "walking", heard = #player.heard}
			walk_in(player)
			return false
		end
		local journey = check.journey("checker")
		if again.stage == "walking" then
			if journey and journey.state == "across" then
				again.stage = "away"
				check.left("checker")
				check.remove_stand_in("checker")
				again.heard = #player.heard
			end
			return false
		end
		if again.stage == "away" then
			if journey and journey.state == "returned" then
				again.stage = "back"
				check.add_stand_in("checker", player)
				check.joined("checker")
			end
			return false
		end
		local expected = scenario == "crossing"
			and "Your character came back from " .. result.world_words .. ", carrying a torch."
			or "The world's owner closed the gate, and your character came back from "
				.. result.world_words .. ", carrying a torch."
		local words = player:heard_since(again.heard, expected)
		verdict("a player who leaves the game while their character is away is told on return",
			words ~= nil and check.journey("checker") == nil
				and count(player.inventory, "default:torch") == 5 and mark_since(0, "gone") == nil,
			tostring(words))
		return true
	end)
end

if scenario == "crossing_door" then
	step("the gate's end is read and the channel stops", 60, function()
		local state = check.state()
		if state and state.state == "ended" then
			verdict("the gate's end is read and the channel stops", true)
			return true
		end
	end)
end

-- Running the script -------------------------------------------------------------------------------

local current, since = 1, 0
local function tick()
	local entry = steps[current]
	if not entry then
		result.finished_ms = now_ms()
		write_result()
		core.request_shutdown("check finished", false, 0)
		return
	end
	local ok, outcome = pcall(entry.run)
	if not ok then
		verdict(entry.name, false, "error: " .. tostring(outcome))
		current = #steps + 1
	elseif outcome == "stop" then
		current = #steps + 1
	elseif outcome then
		current, since = current + 1, 0
	else
		since = since + 0.25
		if since > entry.timeout_s then
			verdict(entry.name, false, "no result in " .. entry.timeout_s .. " s")
			current = #steps + 1
		end
	end
	core.after(0.25, tick)
end

core.after(0.1, function()
	pure_checks()
	tick()
end)
