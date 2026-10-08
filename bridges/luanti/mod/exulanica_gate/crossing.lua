-- A character's crossing: a player walks through the gate, and their character arrives in the world
-- as a thing of its own, lives there with the world's mind, and comes home with what it carries. The
-- player is never held and decides nothing for it: the world asks this server nothing about it.
--
-- Leaving home: one unit of what is in the player's hand goes with the character if the mapping lets
-- that item travel in and the grant lets things be carried in; its whole stack (wear, metadata) is
-- kept here, and once the world says which thing it became, it is kept under that thing's id. The
-- arrival is sent with a fresh id, and sent again with the same id every minute until the world
-- answers. The kept stack is settled only by the world's answer (refused: back to the player;
-- arrived: kept under the thing's id), never by a timeout, so nothing exists twice.
--
-- Coming home: a departure lists what the character carried. A thing whose own stack the game kept
-- comes back as itself; any other becomes the game item the mapping names, only if the mapping lets
-- it travel out and the server has that item. Each departure is delivered once (its id is recorded
-- before the door is told), into the inventory, or kept for the player until they join and have room.

local crossing = {}

local deps
local FRAMES = {arrived = true, arrival_refused = true, departed = true}
local RESEND_SECONDS = 60
local KEPT_SECONDS = 30 * 24 * 3600

local REFUSAL_WORDS = {
	visitor_limit = "The world has as many travellers as it takes right now.",
	visitors_full = "The world has as many travellers as it takes right now.",
	look_not_offered = "The world does not offer that look.",
	item_not_mapped = "What you hold has no counterpart in that world.",
	kind_not_admitted = "The world's owner does not let characters from here in.",
	no_arrival_place = "The world has no gate for travellers to come through.",
	unknown_kind = "The world does not know what a character from here is.",
	grant_ended = "The world's owner closed the gate.",
	kinds_not_allowed = "The world's owner does not let characters from here in.",
	carrying_not_allowed = "The world's owner does not let things be carried in.",
	world_not_open_to_visitors = "The world is not open to travellers.",
	already_here = "Your character is already there.",
	no_visitors_allowed = "The world's owner lets no travellers in through this gate.",
	thing_kind_not_shipped = "The world does not know what a character from here is.",
	kind_not_shipped = "The world does not know what a character from here is.",
	look_not_shipped = "The world cannot show a character from here yet.",
	look_unfit = "The world cannot show a character from here yet.",
	malformed_crossing = "The world could not read that arrival.",
}

local WHY_WORDS = {
	chose_to_leave = "Your character came back",
	sent_home = "Your character was sent back",
	sent_away = "Your character was sent back",
	grant_ended = "The world's owner closed the gate, and your character came back",
	decider_lost = "Your character came back",
	world_changed = "The world changed, and your character came back",
}

function crossing.init(dependencies)
	deps = dependencies
end

function crossing.handles(kind)
	return FRAMES[kind] == true
end

local function uuid4()
	local bytes = {deps.random(16):byte(1, 16)}
	bytes[7] = bytes[7] % 16 + 0x40
	bytes[9] = bytes[9] % 64 + 0x80
	local hex = {}
	for index, byte in ipairs(bytes) do
		hex[index] = string.format("%02x", byte)
	end
	local text = table.concat(hex)
	return text:sub(1, 8) .. "-" .. text:sub(9, 12) .. "-" .. text:sub(13, 16) .. "-"
		.. text:sub(17, 20) .. "-" .. text:sub(21, 32)
end

local function journeys_where(test)
	local found = {}
	for name, record in pairs(deps.journey.all()) do
		if record.mode == "visitor" and test(record) then
			found[#found + 1] = name
		end
	end
	return found
end

-- What the game calls an item, in its own words ("a torch", "a steel sword").
local function game_words(game_item)
	local definition = core.registered_items[game_item]
	local description = definition and definition.description
	local own = description and core.strip_escapes(core.get_translated_string("en", description))
		:match("^[^\n]*")
	return "a " .. ((own and own ~= "") and own:lower() or game_item)
end

local function item_words(game_item)
	local item = deps.mapping_item(game_item)
	local definition = core.registered_items[game_item]
	local description = definition and definition.description
	local own = description and core.strip_escapes(core.get_translated_string("en", description))
		:match("^[^\n]*")
	local game_words = own and own ~= "" and own:lower() or game_item
	if not item then
		return game_words
	end
	local kind = item.kind.key:gsub("_", " ")
	if item.outcome == "approximated" then
		return string.format("a %s (your %s: %s)", kind, game_words,
			item.reason_words or "the nearest match")
	end
	return "a " .. kind
end

local function give_back(player, item_string)
	if not item_string then
		return
	end
	local leftover = player:get_inventory():add_item("main", ItemStack(item_string))
	if not leftover:is_empty() then
		core.add_item(player:get_pos(), leftover)
	end
end

local function keep_for(name, item_string)
	local waiting = deps.store.get("waiting:" .. name) or {}
	local items = deps.store.list(waiting.items)
	items[#items + 1] = item_string
	deps.store.put("waiting:" .. name, {items = items})
end

-- The journey ends before the character ever arrived: what it held is the player's again.
local function home(name, record, words)
	local player = deps.engine.player(name)
	if record.escrow then
		if player then
			give_back(player, record.escrow)
		else
			keep_for(name, record.escrow)
		end
		record.escrow = nil
	end
	deps.journey.finish(name, words)
end

local function send_arrival(name, record)
	local chan = deps.channel_of(record.grant_id)
	if not chan then
		return
	end
	local carried = {}
	for _, item in ipairs(deps.store.list(record.carried)) do
		carried[#carried + 1] = deps.json.object({
			{"game_item", deps.json.string(item.game_item)},
			{"count", deps.json.integer(item.count)},
		})
	end
	local body = deps.json.object({
		{"arrival_id", deps.json.string(record.arrival_id)},
		{"game_type", deps.json.string("player")},
		{"look_key", deps.json.string(record.look_key)},
		{"carried", deps.json.array(carried)},
	})
	record.sent_at = os.time()
	deps.journey.save(name, record)
	deps.record.mark("arrival_sent", {request = record.arrival_id})
	chan.post("/door/channel/arrivals", body, function(code, answer)
		local reason = type(answer) == "table" and answer.code or tostring(code)
		if code == 201 or code == 200 or code == 0 or code == 429 or code >= 500
				or reason == "hello_first" then
			-- Taken, or not heard this time (the channel says hello again on hello_first): the
			-- arrival stands, and the crossing tick sends it again with the same id.
			return
		end
		deps.record.mark("arrival_refused_at_the_door", {request = record.arrival_id, reason = reason})
		local otherwise = deps.adapter_looks.otherwise
		if (reason == "look_not_shipped" or reason == "look_unfit") and record.look_key ~= otherwise then
			-- The world cannot draw this look yet: the traveller crosses in the free look instead,
			-- as a new arrival.
			record.look_key = otherwise
			record.arrival_id = uuid4()
			deps.journey.save(name, record)
			deps.engine.tell(name, "This world cannot show your own look yet, so your character "
				.. "arrives in its traveller look.")
			send_arrival(name, record)
			return
		end
		home(name, record, REFUSAL_WORDS[reason] or "The gate did not open.")
	end)
end

-- The look a player arrives in: the one the adapter names for their picture if the mapping lists
-- it (the game's own picture), else the free look. A custom picture never crosses.
function crossing.look_key(player, visitor)
	local looks = deps.adapter_looks
	local textures = player.get_properties and player:get_properties().textures or {}
	local wanted = looks.by_texture[textures[1] or ""] or looks.otherwise
	for _, look in ipairs(visitor.looks) do
		if look.look_key == wanted then
			return wanted
		end
	end
	return looks.otherwise
end

-- A player walked into the gate of a grant that lets travellers in: their character crosses, and
-- they play on.
function crossing.leave_home(name, chan, portal, outside)
	local player = deps.engine.player(name)
	local visitor = deps.mapping_visitor("player")
	if not visitor then
		deps.journey.push_out(name, outside, "This gate takes no travellers from this game.")
		return
	end
	local scope = chan.grant.scope or {}
	local record = {
		mode = "visitor",
		state = "leaving",
		grant_id = chan.grant.grant_id,
		arrival_id = uuid4(),
		look_key = crossing.look_key(player, visitor),
		carried = {},
	}
	local stack = player:get_wielded_item()
	local item = not stack:is_empty() and deps.mapping_item(stack:get_name())
	local leaves_hand = item and (item.ways == "in" or item.ways == "both")
	if leaves_hand and scope.may_carry_in then
		local one = stack:take_item(1)
		player:set_wielded_item(stack)
		record.escrow = one:to_string()
		record.carried = {{game_item = one:get_name(), count = 1}}
	end
	if leaves_hand and not scope.may_carry_in then
		deps.engine.tell(name, "The world's owner does not let things be carried in; what you hold "
			.. "stays here.")
	end
	deps.journey.push_through(name, portal, outside)
	send_arrival(name, record)
end

local function on_arrived(frame)
	for _, name in ipairs(journeys_where(function(record)
		return record.arrival_id == frame.arrival_id
	end)) do
		local record = deps.journey.record_of(name)
		if record.state == "leaving" then
			record.state = "across"
			record.subject_id = frame.thing_id
			local carried_words = {}
			local crossed = false
			for _, carried in ipairs(deps.store.list(frame.carried)) do
				if record.escrow and ItemStack(record.escrow):get_name() == carried.game_item then
					deps.store.put("kept:" .. carried.thing_id, {item = record.escrow,
						kept_at = os.time()})
					record.escrow = nil
					crossed = true
				end
				carried_words[#carried_words + 1] = item_words(carried.game_item)
			end
			local player = deps.engine.player(name)
			if record.escrow and player then
				give_back(player, record.escrow)
				record.escrow = nil
				deps.engine.tell(name, "What you held could not cross; it is back in your hands.")
			end
			deps.journey.save(name, record)
			deps.record.mark("arrived", {request = frame.arrival_id, subject = frame.thing_id,
				kind = crossed and "carried" or "empty-handed"})
			local words = "Your character is in " .. deps.journey.world_words(record)
			if #carried_words > 0 then
				words = words .. ", carrying " .. table.concat(carried_words, " and ")
			end
			deps.engine.tell(name, words .. ".")
		end
	end
end

local function on_arrival_refused(frame)
	for _, name in ipairs(journeys_where(function(record)
		return record.arrival_id == frame.arrival_id
	end)) do
		local record = deps.journey.record_of(name)
		home(name, record, REFUSAL_WORDS[frame.reason] or "The world did not let your character in.")
	end
end

local function report(chan, departure_id, delivered, refused)
	local given, kept_back = {}, {}
	for _, item in ipairs(delivered) do
		given[#given + 1] = deps.json.object({
			{"thing_id", deps.json.string(item.thing_id)},
			{"game_item", deps.json.string(item.game_item)},
		})
	end
	for _, item in ipairs(refused) do
		kept_back[#kept_back + 1] = deps.json.object({
			{"thing_id", deps.json.string(item.thing_id)},
			{"reason", deps.json.string(item.reason)},
		})
	end
	local body = deps.json.object({
		{"delivered", deps.json.array(given)},
		{"not_delivered", deps.json.array(kept_back)},
	})
	chan.post("/door/channel/departures/" .. core.urlencode(departure_id) .. "/delivered", body,
		function(code)
			deps.record.mark("delivered", {request = departure_id, status = code})
		end)
end

local function stack_for(carried)
	local kept = deps.store.get("kept:" .. carried.thing_id)
	if kept and type(kept.item) == "string" then
		deps.store.put("kept:" .. carried.thing_id, nil)
		return ItemStack(kept.item)
	end
	local item = deps.mapping_item(carried.game_item)
	if item and (item.ways == "out" or item.ways == "both")
			and core.registered_items[carried.game_item] then
		return ItemStack(carried.game_item)
	end
	return nil
end

local function on_departed(chan, frame)
	local already = deps.store.get("delivered:" .. tostring(frame.departure_id))
	if already then
		report(chan, frame.departure_id, deps.store.list(already.delivered),
			deps.store.list(already.not_delivered))
		return
	end
	local names = journeys_where(function(record)
		return record.subject_id == frame.thing_id
	end)
	local name = names[1]
	local delivered, refused, words = {}, {}, {}
	local player = name and deps.engine.player(name)
	for _, carried in ipairs(deps.store.list(frame.carried)) do
		local stack = stack_for(carried)
		if stack then
			delivered[#delivered + 1] = {thing_id = carried.thing_id, game_item = stack:get_name()}
			words[#words + 1] = game_words(stack:get_name())
			local leftover = stack
			if player then
				leftover = player:get_inventory():add_item("main", stack)
			end
			if not leftover:is_empty() and name then
				keep_for(name, leftover:to_string())
			end
		else
			refused[#refused + 1] = {thing_id = carried.thing_id, reason = "not_in_mapping"}
		end
	end
	deps.store.put("delivered:" .. tostring(frame.departure_id), {delivered = delivered,
		not_delivered = refused, at = os.time()})
	report(chan, frame.departure_id, delivered, refused)
	local brought = {}
	for _, item in ipairs(delivered) do
		brought[#brought + 1] = item.game_item
	end
	deps.record.mark("departed", {request = frame.departure_id, subject = frame.thing_id,
		why = frame.why, delivered = brought})
	if name then
		local record = deps.journey.record_of(name)
		local sentence = (WHY_WORDS[frame.why] or "Your character came back") .. " from "
			.. deps.journey.world_words(record)
		if #words > 0 then
			sentence = sentence .. ", carrying " .. table.concat(words, " and ")
		end
		if player then
			deps.journey.finish(name, sentence .. ".")
		else
			-- Told when the player next joins.
			record.state = "returned"
			record.words = sentence .. "."
			deps.journey.save(name, record)
		end
	end
end

function crossing.frame(chan, frame)
	local kind = frame.kind
	if kind == "arrived" then
		on_arrived(frame)
	elseif kind == "arrival_refused" then
		on_arrival_refused(frame)
	elseif kind == "departed" then
		on_departed(chan, frame)
	end
end

local function give_waiting(name)
	local waiting = deps.store.get("waiting:" .. name)
	local player = deps.engine.player(name)
	if not waiting or not player then
		return
	end
	local still = {}
	for _, item in ipairs(deps.store.list(waiting.items)) do
		local leftover = player:get_inventory():add_item("main", ItemStack(item))
		if not leftover:is_empty() then
			still[#still + 1] = leftover:to_string()
		end
	end
	deps.store.put("waiting:" .. name, #still > 0 and {items = still} or nil)
	if #still > 0 then
		deps.engine.tell(name, "Some of what you brought back is waiting until you make room.")
	end
end

-- The player joined with a character on record: told what came home while they were away, or shown
-- where their character still is.
function crossing.rejoined(name, record)
	if record.state == "returned" then
		deps.journey.finish(name, record.words)
	else
		deps.journey.refresh(name)
	end
	give_waiting(name)
end

-- The grant ended: a character still crossing comes straight back with what the player held; one
-- across comes home when the world sends its departure, which the door sends before the gate's end.
function crossing.grant_ended(name, record)
	if record.state == "leaving" then
		home(name, record, REFUSAL_WORDS.grant_ended)
	end
end

-- Every few seconds: arrivals the world has not answered are sent again (the same id, so the world
-- counts it once); kept stacks of things that never came back are dropped after thirty days.
function crossing.tick()
	local now = os.time()
	for _, name in ipairs(journeys_where(function(record)
		return record.state == "leaving"
	end)) do
		local record = deps.journey.record_of(name)
		if now - (record.sent_at or 0) >= RESEND_SECONDS then
			if not record.slow then
				record.slow = true
				deps.engine.tell(name, "The world has not answered yet; the gate keeps trying.")
			end
			send_arrival(name, record)
		end
	end
	for _, key in ipairs(deps.store.keys("kept:")) do
		local kept = deps.store.get(key)
		if not kept or now - (tonumber(kept.kept_at) or now) > KEPT_SECONDS then
			deps.store.put(key, nil)
		end
	end
end

function crossing.give_waiting(name)
	give_waiting(name)
end

return crossing
