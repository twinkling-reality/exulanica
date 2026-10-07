-- One player's journey through the gate.
--
-- A player who walks into the gate's light stands still inside it while their choices go to the
-- world: their view tinted, a panel naming the world, their chat going to the one they play, the
-- inventory key opening the menu. Stepping back (or the world ending the grant) puts them where
-- they stood before they walked in, as they were.
--
-- A grant may name things of the world for a player to take the part of ("seats"), and may let
-- travellers cross in as things of their own ("visitors", package 3b). A journey is kept in mod
-- storage, so a player who drops off or a server that stops resumes rather than loses anything.

local journey = {}

local deps
local records = {}

local REASON_WORDS = {
	no_answer_in_time = "Too late for that minute; kept for the next.",
	answer_too_late = "Too late for that minute; kept for the next.",
	decider_disconnected = "The world did not hear from this server in time.",
	grant_revoked = "The world's owner closed the gate.",
	grant_expired = "The gate's time ran out.",
	line_refused_by_rules =
		"The world's owner's rules stopped that line (it named someone they protect); it was not said.",
	line_out_of_bounds =
		"That line could not be said (too long, or holding characters the world does not take).",
	answer_not_offered = "That choice was not offered.",
}

function journey.init(dependencies)
	deps = dependencies
	-- Journeys kept from before a stop, so a departure for a player who is not here finds them.
	for _, stored in ipairs(deps.store.keys("journey:")) do
		local record = deps.store.get(stored)
		if record then
			records[stored:sub(#"journey:" + 1)] = record
		end
	end
end

local function key(name)
	return "journey:" .. name
end

local function save(name, record)
	records[name] = record
	deps.store.put(key(name), record)
end

local function clean(text, maximum)
	return deps.lines.incoming(text, maximum or 120)
end

local function world_words(record)
	local chan = deps.channel_of(record.grant_id)
	local words = chan and chan.world_words
	if type(words) == "string" and words ~= "" then
		return clean(words, 80)
	end
	return deps.settings.world_words
end

local function panel_text(name, record)
	if record.state == "leaving" then
		return "Crossing into " .. world_words(record) .. "..."
	end
	if record.state == "returning" then
		return "Coming back from " .. world_words(record) .. "..."
	end
	local _, subject = deps.choices.of_player(name)
	local text = {world_words(record)}
	if record.mode == "seat" then
		text[#text + 1] = "You decide for one of its people."
	else
		text[#text + 1] = "You are a traveller here."
	end
	if subject and subject.action then
		text[#text + 1] = "Next: " .. clean(subject.action.label, 48)
	elseif subject and #subject.lines > 0 then
		text[#text + 1] = "Next: your line is said."
	else
		text[#text + 1] = "Next: nothing new."
	end
	if record.last then
		text[#text + 1] = clean(record.last, 56)
	end
	local speaks = subject and subject.asked and deps.choices.speaks(subject.asked)
	text[#text + 1] = speaks and "Press I to choose. Chat to speak." or "Press I to choose."
	return table.concat(text, "\n")
end

-- Bring the player's panel and inventory form up to date with what the world last offered.
function journey.refresh(name)
	local record = records[name]
	local player = deps.engine.player(name)
	if not record or not player then
		return
	end
	deps.panel.show(player, name, panel_text(name, record))
	local _, subject = deps.choices.of_player(name)
	if subject then
		player:set_inventory_formspec(deps.menu.build(name, subject, deps))
	end
end

-- Tell a player something, and keep it on their panel as the latest news.
function journey.note(name, words)
	local record = records[name]
	if record then
		record.last = words
		journey.refresh(name)
	end
	deps.engine.tell(name, words)
end

-- Tell a player something the panel already shows another way.
function journey.tell(name, words)
	journey.refresh(name)
	deps.engine.tell(name, words)
end

function journey.record_of(name)
	return records[name]
end

local function face_away(player, from, to)
	local dx, dz = to.x - from.x, to.z - from.z
	if dx ~= 0 or dz ~= 0 then
		player:set_look_horizontal(math.atan2(-dx, dz))
	end
end

local function push_out(name, outside, words)
	local player = deps.engine.player(name)
	if player and outside then
		player:set_pos(outside)
	end
	if words then
		deps.engine.tell(name, words)
	end
end

-- Start a journey: the record kept, the player held still inside the gate's light, their panel
-- shown and the menu made their inventory form.
function journey.begin(name, record)
	local player = deps.engine.player(name)
	local physics = player:get_physics_override()
	record.v = 1
	record.physics = {speed = physics.speed or 1, jump = physics.jump or 1}
	record.inventory_form = player:get_inventory_formspec()
	record.since = os.time()
	save(name, record)
	player:set_physics_override({speed = 0, jump = 0})
	player:set_pos({x = record.portal.x, y = record.portal.y - 0.5, z = record.portal.z})
	journey.refresh(name)
end

-- Keep a journey's record as it now stands.
function journey.save(name, record)
	save(name, record)
end

function journey.world_words(record)
	return world_words(record)
end

local function take_part(name, chan, thing, portal, outside)
	local record = {
		mode = "seat",
		grant_id = chan.grant.grant_id,
		subject_id = thing,
		portal = portal,
		return_to = outside,
	}
	deps.choices.bind(thing, {grant_id = record.grant_id, player = name, mode = "seat"})
	journey.begin(name, record)
	deps.record.mark("seated", {grant = record.grant_id, subject = thing})
	deps.engine.tell(name, "Through the gate: you decide for one of the people of "
		.. world_words(record) .. ". Press I to choose.")
end

-- A player walked into a gate's light at `portal`, from `outside`.
function journey.enter(name, portal, outside)
	if records[name] then
		return
	end
	local chan = deps.channel_for(name)
	if not chan or not chan.ready() or not chan.grant then
		push_out(name, outside, "The gate is closed right now.")
		return
	end
	local scope = chan.grant.scope or {}
	for _, thing in ipairs(deps.store.list(scope.things)) do
		local subject = deps.choices.subject(thing)
		if not (subject and subject.player) then
			take_part(name, chan, thing, portal, outside)
			return
		end
	end
	if (tonumber(scope.visitors_maximum) or 0) > 0 and deps.crossing then
		deps.crossing.leave_home(name, chan, portal, outside)
		return
	end
	push_out(name, outside, "Nobody is waiting on the other side of this gate for you right now.")
end

-- Put a player back where they stood before the gate, as they were, and end their journey.
function journey.step_back(name, words)
	local record = records[name]
	if not record then
		return
	end
	local player = deps.engine.player(name)
	if record.subject_id then
		deps.choices.unbind(record.subject_id)
	end
	if player then
		player:set_physics_override(record.physics or {speed = 1, jump = 1})
		if record.inventory_form then
			player:set_inventory_formspec(record.inventory_form)
		end
		if record.return_to then
			player:set_pos(record.return_to)
			if record.portal then
				face_away(player, record.portal, record.return_to)
			end
		end
		deps.panel.hide(player, name)
	else
		deps.panel.forget(name)
	end
	deps.menu.forget(name)
	deps.record.mark("stepped_back", {grant = record.grant_id, subject = record.subject_id})
	records[name] = nil
	deps.store.put(key(name), nil)
	if words then
		deps.engine.tell(name, words)
	end
end

-- The player left the game. A part they played goes back to the world's routine.
function journey.left(name)
	local record = records[name]
	if not record then
		return
	end
	if record.mode == "seat" then
		journey.step_back(name, nil)
	elseif deps.crossing then
		deps.crossing.left(name, record)
	end
	deps.panel.forget(name)
end

-- The player joined: a journey left over from a stop the server could not finish is ended, and
-- the player put back outside the gate.
function journey.joined(name)
	local record = records[name] or deps.store.get(key(name))
	if not record then
		if deps.crossing then
			deps.crossing.give_waiting(name)
		end
		return
	end
	records[name] = record
	if record.mode == "seat" then
		record.inventory_form = nil
		journey.step_back(name, "You were stepped back out of the gate while you were away.")
	elseif deps.crossing then
		deps.crossing.rejoined(name, record)
	end
end

-- A grant ended: everyone whose choices went through it steps back.
function journey.grant_ended(grant_id, reason)
	for name, record in pairs(records) do
		if record.grant_id == grant_id then
			if record.mode == "seat" then
				journey.step_back(name, REASON_WORDS[reason] or "The gate closed.")
			elseif deps.crossing then
				deps.crossing.grant_ended(name, record, reason)
			end
		end
	end
	deps.choices.forget_grant(grant_id)
end

-- A grant's scope changed: a player whose part is no longer named steps back.
function journey.scope_changed(grant_id, scope)
	local named = {}
	for _, thing in ipairs(deps.store.list(scope and scope.things)) do
		named[thing] = true
	end
	for name, record in pairs(records) do
		if record.grant_id == grant_id and record.mode == "seat" and not named[record.subject_id] then
			journey.step_back(name, "The world's owner gave that part back to the world.")
		end
	end
end

-- Every player with a journey, for a server stopping.
function journey.all()
	return records
end

function journey.reason_words(reason)
	return REASON_WORDS[reason]
end

-- Put a player back outside a gate with words, before any journey began.
journey.push_out = push_out

return journey
