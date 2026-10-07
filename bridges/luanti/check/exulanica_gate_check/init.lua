-- A check run of the Exulanica gate on a headless server: a test mod that plays a player.
--
-- It registers stand-in players behind the gate mod's engine seam (a name, a real engine inventory,
-- a position, and a record of what a person would have been told and shown), then walks one of
-- them into a gate and plays a script through the same handlers a person's actions reach: the
-- gate noticing feet in its light, the chat callback, the menu's submitted fields. Each step's
-- verdict and timing goes to <world>/exulanica_gate_check/result.json, and the server stops.
-- Loaded only in check worlds; the gate mod refuses stand-ins unless exulanica_gate.check_mode is
-- set.

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

-- What the gate mod marks: asks answered, outcomes, things not answered.
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

local function read(path)
	local file = io.open(path, "rb")
	if not file then
		return nil
	end
	local text = file:read("*a")
	file:close()
	return text
end

local function pure_checks()
	local cases = core.parse_json(assert(read(modpath .. "/line-cases.json")))
	local failures = {}
	for _, case in ipairs(cases.cases) do
		local names = {}
		for _, name in ipairs(case.names or {}) do
			names[name:lower()] = true
		end
		local line, code = check.lines.outgoing(case.text, names, cases.maximum)
		local ok
		if case.said then
			ok = line == case.said
		else
			ok = line == nil and code == case.refused
		end
		if not ok then
			failures[#failures + 1] = case.case
		end
	end
	verdict("line cases", #failures == 0, #failures == 0 and (#cases.cases .. " cases")
		or table.concat(failures, "; "))
	local refused_bytes = check.lines.outgoing("broken \255 bytes", {}, 200)
	verdict("a line that is not UTF-8 is refused", refused_bytes == nil)

	local identity = check.choices.identity
	local near = {label = "walk to the well (12 m)", kind = "target", action = "go",
		target_id = "t-1", activity = "drink", walk_mm = 12000}
	local far = {label = "walk to the well (9 m)", kind = "target", action = "go",
		target_id = "t-1", activity = "drink", walk_mm = 9000}
	local other = {label = "walk to the bench (9 m)", kind = "target", action = "go",
		target_id = "t-2", activity = "sit", walk_mm = 9000}
	verdict("an option is the same option when only its distance changed",
		identity(near) == identity(far) and identity(near) ~= identity(other))

	local hostile = {label = "go]button[0,0;9,9;x;y", kind = "target", action = "go",
		target_id = "t-9", activity = "a;b,c", walk_mm = 1}
	local formspec = check.menu_build("nobody-at-all", {mode = "seat", asked = {context = {options = {
		hostile, {label = "wait", kind = "wait", action = "wait"}}}}})
	verdict("a world's label cannot add to a form",
		formspec:find("go]button[", 1, true) == nil and formspec:find("go\\]button\\[", 1, true) ~= nil)

	local bytes = check.picture_bytes
	verdict("the gate's pictures are drawn in code and small", bytes > 0 and bytes < 20000,
		bytes .. " bytes of inline pictures")
	verdict("the adapter reads what its mapping accounts for", #check.reads >= 13,
		#check.reads .. " game fields")
end

-- The script ---------------------------------------------------------------------------------------

local steps = {}
local function step(name, timeout_s, run)
	steps[#steps + 1] = {name = name, timeout_s = timeout_s, run = run}
end

local player, other, gate_origin, subject_id, first_seen, heard_mark, chosen
-- named_thing: a player takes the part of a thing the grant names (the door's channel today);
-- crossing: a player crosses in as a traveller of its own and comes home (the crossing frames).
local scenario = core.settings:get("exulanica_gate_check.scenario") or "named_thing"
result.scenario = scenario

step("the server's channel said hello and polls", 90, function()
	local state = check.state()
	if state and state.state == "polling" then
		result.timings.channel_ready_ms = now_ms()
		result.grant_things = #(state.grant.scope.things or {})
		result.grant_visitors = tonumber(state.grant.scope.visitors_maximum) or 0
		verdict("the server's channel said hello and polls", true,
			"hold " .. state.hold_seconds .. " s")
		return true
	end
end)

if scenario == "named_thing" then
	step("the grant names a thing to play", 1, function()
		local ok = (result.grant_things or 0) >= 1
		verdict("the grant names a thing to play", ok, result.grant_things .. " named")
		return ok or "stop"
	end)
else
	step("the grant lets a traveller in", 1, function()
		local ok = (result.grant_visitors or 0) >= 1
		verdict("the grant lets a traveller in", ok, result.grant_visitors .. " at a time")
		return ok or "stop"
	end)
end

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

if scenario == "named_thing" then
step("a player walks into the gate and takes the part", 20, function()
	if not player then
		check.build_gate(gate_origin, true)
		player = stand_in("checker", {x = 0.5, y = 9, z = 2})
		other = stand_in("Bob", {x = 3, y = 9, z = 2})
		heard_mark = #player.heard
		return false
	end
	if not player.walked_in then
		player.walked_in = now_ms()
		player:set_pos({x = 0, y = 8.5, z = 6})
		return false
	end
	local journey = check.journey("checker")
	if journey and journey.mode == "seat" then
		subject_id = journey.subject_id
		local ok = player.physics.speed == 0 and player.physics.jump == 0
			and player.inventory_form:find("What does the one you play do?", 1, true) ~= nil
			and next(player.huds) ~= nil
		result.timings.took_part_ms = now_ms() - player.walked_in
		verdict("a player walks into the gate and takes the part", ok,
			"held still, panel shown, the menu is their inventory form")
		return true
	end
end)

step("a chat line from the part's player stays off the server's chat", 5, function()
	local kept = check.chat("checker", "hello Bob, are you there?")
	local not_ours = check.chat("Bob", "a line in the server's own chat")
	verdict("a chat line from the part's player stays off the server's chat",
		kept == true and not_ours == false)
	return true
end)

step("the world's first ask is answered with the option that changes nothing", 300, function()
	local mark = mark_since(0, "answered", function(details) return details.what == "idle" end)
	if mark then
		first_seen = first_seen or now_ms()
		result.timings.first_ask_ms = mark.at_ms
		verdict("the world's first ask is answered with the option that changes nothing",
			mark.details.status == 202, "door answered " .. tostring(mark.details.status)
			.. " in " .. tostring(mark.details.ms) .. " ms")
		return true
	end
	local refused = player:heard_since(heard_mark, "cannot speak")
	if refused then
		result.person_cannot_speak = true
	end
end)

step("a part that cannot speak says so to its player", 5, function()
	local _, subject = check.subject_of("checker")
	local speaks = false
	for _, option in ipairs(subject.asked.context.options) do
		speaks = speaks or check.choices.says(option)
	end
	if speaks then
		verdict("a part that cannot speak says so to its player", true, "this part can speak")
		return true
	end
	local before = #player.heard
	check.chat("checker", "is anyone there?")
	verdict("a part that cannot speak says so to its player",
		player:heard_since(before, "cannot speak") ~= nil)
	return true
end)

step("a choice from the menu is done at a later minute", 300, function()
	if not chosen then
		local _, subject = check.subject_of("checker")
		local idle = check.choices.idle(subject.asked)
		check.menu("checker")
		local options = subject.asked.context.options
		for index, option in ipairs(options) do
			if option ~= idle and not check.choices.says(option) then
				local fields = {}
				-- the menu numbers the options it shows, which leave out lines to say
				local shown = 0
				for _, candidate in ipairs(options) do
					if not check.choices.says(candidate) then
						shown = shown + 1
					end
					if candidate == option then
						break
					end
				end
				fields["exg_o" .. shown] = option.label
				check.fields("checker", fields)
				chosen = {label = option.label, identity = check.choices.identity(option),
					at_mark = #marks, at_ms = now_ms()}
				result.chosen = {label = option.label, kind = option.kind}
				return false
			end
		end
		verdict("a choice from the menu is done at a later minute", false,
			"no option but the one that changes nothing was offered")
		return "stop"
	end
	local answered = mark_since(chosen.at_mark, "answered", function(details)
		return details.what == "action"
	end)
	if not answered then
		return false
	end
	local outcome = mark_since(chosen.at_mark, "outcome", function(details)
		return details.request == answered.details.request
	end)
	if outcome then
		result.chosen.request_id = answered.details.request
		result.chosen.status = outcome.details.status
		result.timings.choice_to_answer_ms = answered.at_ms - chosen.at_ms
		result.timings.choice_to_outcome_ms = outcome.at_ms - chosen.at_ms
		verdict("a choice from the menu is done at a later minute",
			outcome.details.status == "accepted" and player:heard_since(0, "Done:") ~= nil,
			outcome.details.status .. " " .. tostring(outcome.details.reason))
		return true
	end
end)

step("stepping back puts the player where they stood, as they were", 10, function()
	check.fields("checker", {exg_back = "Step back out of the gate"})
	local journey = check.journey("checker")
	local pos = player:get_pos()
	local ok = journey == nil and player.physics.speed == 1 and player.physics.jump == 1
		and pos.z < 6 and player.inventory_form == "the game's own inventory form"
		and next(player.huds) == nil
	result.stepped_back_at_mark = #marks
	verdict("stepping back puts the player where they stood, as they were", ok)
	return true
end)

step("a part nobody plays is left to the world's routine", 300, function()
	local mark = mark_since(result.stepped_back_at_mark, "not_answered", function(details)
		return details.why == "nobody plays it"
	end)
	if mark then
		verdict("a part nobody plays is left to the world's routine", true)
		return true
	end
end)

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

if scenario == "crossing" then
local walked_at
step("a traveller walks in holding a torch, and one torch goes with them", 20, function()
	if not player then
		check.build_gate(gate_origin, true)
		player = stand_in("checker", {x = 0.5, y = 9, z = 2})
		other = stand_in("Bob", {x = 3, y = 9, z = 2})
		player.inventory:set_stack("main", 1, ItemStack("default:torch 5"))
		return false
	end
	if not walked_at then
		walked_at = now_ms()
		player:set_pos({x = 0, y = 8.5, z = 6})
		return false
	end
	local journey = check.journey("checker")
	if journey and journey.mode == "visitor" then
		local sent = mark_since(0, "arrival_sent")
		if not sent then
			return false
		end
		result.timings.walk_in_to_arrival_sent_ms = sent.at_ms - walked_at
		verdict("a traveller walks in holding a torch, and one torch goes with them",
			player.inventory:get_stack("main", 1):get_count() == 4 and player.physics.speed == 0,
			"four torches stay in the hand")
		return true
	end
end)

step("the traveller arrives carrying a lantern", 30, function()
	local journey = check.journey("checker")
	if journey and journey.state == "across" then
		local arrived = mark_since(0, "arrived")
		result.timings.walk_in_to_arrived_ms = arrived.at_ms - walked_at
		subject_id = journey.subject_id
		verdict("the traveller arrives carrying a lantern",
			player:heard_since(0, "You arrived carrying a lantern (your torch:") ~= nil
				and arrived.details.kind == "carried",
			player.heard[#player.heard])
		verdict("a world that cannot draw the own look yet gets the free look, and the player is told",
			player:heard_since(0, "Your own look cannot cross into this world yet") ~= nil)
		return true
	end
end)

local said_from
step("a line is said to the knight, with a player's name replaced", 30, function()
	if not said_from then
		said_from = {mark = #marks, heard = #player.heard, at = now_ms()}
		check.chat("checker", "hello Bob, I am looking for a sword")
		return false
	end
	local echo = player:heard_since(said_from.heard, "you said:")
	if echo then
		result.timings.line_typed_to_said_ms = now_ms() - said_from.at
		local answered = mark_since(said_from.mark, "answered", function(details)
			return details.what == "line"
		end)
		verdict("a line is said to the knight, with a player's name replaced",
			echo:find("hello someone, I am looking for a sword", 1, true) ~= nil and answered ~= nil
				and answered.details.label:find("knight", 1, true) ~= nil, echo)
		return true
	end
end)

step("the knight's answer reaches chat, marked as AI", 30, function()
	local heard = player:heard_since(said_from.heard, "the knight (person 2) (AI, run by ")
	if heard then
		result.timings.line_typed_to_reply_ms = now_ms() - said_from.at
		verdict("the knight's answer reaches chat, marked as AI", true, heard)
		return true
	end
end)

step("the hand-over is told", 30, function()
	local heard = player:heard_since(said_from.heard, "gave you a sword")
	if heard then
		verdict("the hand-over is told", true, heard)
		return true
	end
end)

local walk
step("a chosen walk is answered at a later minute though its distance changed", 30, function()
	local _, subject = check.subject_of("checker")
	if not walk then
		local shown = 0
		for _, option in ipairs(subject.asked.context.options) do
			if not check.choices.says(option) then
				shown = shown + 1
				if option.kind == "target" then
					check.menu("checker")
					check.fields("checker", {["exg_o" .. shown] = option.label})
					walk = {label = option.label, mark = #marks}
					return false
				end
			end
		end
		return false
	end
	local answered = mark_since(walk.mark, "answered", function(details)
		return details.what == "action"
	end)
	if answered then
		result.walk = {clicked = walk.label, answered = answered.details.label}
		verdict("a chosen walk is answered at a later minute though its distance changed",
			answered.details.label ~= walk.label and answered.details.label:find("walk to the well",
				1, true) == 1, walk.label .. " -> " .. answered.details.label)
		return true
	end
end)

local leaving
step("leaving through the gate brings home the torch and a steel sword", 40, function()
	if not leaving then
		local _, subject = check.subject_of("checker")
		local shown = 0
		for _, option in ipairs(subject.asked.context.options) do
			if not check.choices.says(option) then
				shown = shown + 1
				if option.kind == "leave" then
					check.menu("checker")
					check.fields("checker", {["exg_o" .. shown] = option.label})
					leaving = {at = now_ms(), heard = #player.heard}
					return false
				end
			end
		end
		return false
	end
	if check.journey("checker") == nil then
		result.timings.leave_chosen_to_home_ms = now_ms() - leaving.at
		local torches = count(player.inventory, "default:torch")
		local swords = count(player.inventory, "default:sword_steel")
		local words = player:heard_since(leaving.heard, "You came back from The Crossroads")
		verdict("leaving through the gate brings home the torch and a steel sword",
			torches == 5 and swords == 1 and player.physics.speed == 1 and words ~= nil,
			string.format("torches %d, swords %d; %s", torches, swords, tostring(words)))
		result.home_at_mark = #marks
		return true
	end
end)

local waited_from
step("a departure repeated before its report delivers nothing twice", 10, function()
	waited_from = waited_from or now_ms()
	if now_ms() - waited_from < 4000 then
		return false
	end
	local delivered = 0
	for _, mark in ipairs(marks) do
		if mark.what == "departed" then
			delivered = delivered + 1
		end
	end
	verdict("a departure repeated before its report delivers nothing twice",
		count(player.inventory, "default:sword_steel") == 1, delivered .. " departure delivered")
	return true
end)

local second
step("a player who quits while across is told on return that their traveller came home", 60,
	function()
		if not second then
			second = {stage = "walking", mark = #marks}
			player:set_pos({x = 0.5, y = 9, z = 2})
			return false
		end
		if second.stage == "walking" then
			second.stage = "entering"
			player:set_pos({x = 0, y = 8.5, z = 6})
			return false
		end
		local journey = check.journey("checker")
		if second.stage == "entering" then
			if journey and journey.state == "across" then
				second.stage = "away"
				check.left("checker")
				check.remove_stand_in("checker")
				second.heard = #player.heard
			end
			return false
		end
		if second.stage == "away" then
			local gone = mark_since(second.mark, "gone")
			local departed = mark_since(second.mark, "departed")
			if gone and departed and journey and journey.state == "returned" then
				second.stage = "back"
				check.add_stand_in("checker", player)
				check.joined("checker")
			end
			return false
		end
		local words = player:heard_since(second.heard, "Your traveller waited for you, then came home")
		verdict("a player who quits while across is told on return that their traveller came home",
			words ~= nil and check.journey("checker") == nil and player.physics.speed == 1,
			tostring(words))
		return true
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
