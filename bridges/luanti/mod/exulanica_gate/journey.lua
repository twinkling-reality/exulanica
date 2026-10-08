-- One player's character, away in a world.
--
-- A player who walks into the gate's light sends their character through it: the character crosses
-- into the world as a thing of its own and lives there, its mind the world's, while the player plays
-- on here, never held. One line at the top of their screen says where it is; when it comes home,
-- what it carries lands in their inventory. A journey is kept in mod storage, so a player who leaves
-- the game, or a server that stops, loses nothing: the character lives on, and what it brings home
-- waits for its player.

local journey = {}

local deps
local records = {}

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

local function world_words(record)
	local chan = deps.channel_of(record.grant_id)
	local words = chan and chan.world_words
	if type(words) == "string" and words ~= "" then
		return deps.lines.incoming(words, 80)
	end
	return deps.settings.world_words
end

-- The one line a player sees while their character is away.
local function status_text(record)
	if record.state == "leaving" then
		return "Your character is crossing into " .. world_words(record) .. "..."
	end
	return "Your character is in " .. world_words(record)
end

-- Bring the player's line up to date with where their character is.
function journey.refresh(name)
	local record = records[name]
	local player = deps.engine.player(name)
	if record and player then
		deps.panel.show(player, name, status_text(record))
	end
end

function journey.record_of(name)
	return records[name]
end

-- Keep a journey's record as it now stands, and the player's line with it.
function journey.save(name, record)
	save(name, record)
	journey.refresh(name)
end

function journey.world_words(record)
	return world_words(record)
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

-- Put a player on the far side of the gate they walked into, still facing on, so they are never
-- left standing in its light (the gate keeps two nodes clear behind it).
function journey.push_through(name, portal, outside)
	local player = deps.engine.player(name)
	if not (player and portal and outside) then
		return
	end
	local dx, dz = portal.x - outside.x, portal.z - outside.z
	local length = math.sqrt(dx * dx + dz * dz)
	if length < 0.01 then
		return
	end
	player:set_pos({x = portal.x + dx / length * 1.6, y = outside.y, z = portal.z + dz / length * 1.6})
end

-- A player walked into a gate's light at `portal`, from `outside`: their character crosses, if the
-- gate is open to travellers and their character is not away already.
function journey.enter(name, portal, outside)
	if records[name] then
		deps.engine.tell(name, "Your character is already away in " .. world_words(records[name])
			.. ".")
		return
	end
	local chan = deps.channel_for(name)
	if not chan or not chan.ready() or not chan.grant then
		push_out(name, outside, "The gate is closed right now.")
		return
	end
	local scope = chan.grant.scope or {}
	if (tonumber(scope.visitors_maximum) or 0) > 0 then
		deps.crossing.leave_home(name, chan, portal, outside)
		return
	end
	push_out(name, outside, "This gate takes no travellers right now.")
end

-- The character's journey is over: the line goes, the record is dropped, and the player is told.
function journey.finish(name, words)
	local record = records[name]
	if not record then
		return
	end
	local player = deps.engine.player(name)
	if player then
		deps.panel.hide(player, name)
	else
		deps.panel.forget(name)
	end
	deps.record.mark("journey_ended", {grant = record.grant_id, subject = record.subject_id})
	records[name] = nil
	deps.store.put(key(name), nil)
	if words then
		deps.engine.tell(name, words)
	end
end

-- The player left the game: their character lives on; only their line is forgotten.
function journey.left(name)
	deps.panel.forget(name)
end

-- The player joined: what came home while they were away is given, and the line is shown again
-- for a character still away.
function journey.joined(name)
	local record = records[name] or deps.store.get(key(name))
	if record then
		records[name] = record
		deps.crossing.rejoined(name, record)
	else
		deps.crossing.give_waiting(name)
	end
end

-- A grant ended: a character still crossing comes straight back; one across comes home when the
-- world sends its departure.
function journey.grant_ended(grant_id, reason)
	for name, record in pairs(records) do
		if record.grant_id == grant_id then
			deps.crossing.grant_ended(name, record, reason)
		end
	end
end

-- Every player with a character away.
function journey.all()
	return records
end

journey.push_out = push_out

return journey
