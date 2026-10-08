-- The seam between the mod and the players it serves.
--
-- Everything the mod does to a player goes through here or through the few player methods it
-- calls (name, position, inventory, wielded item, physics, panel, inventory form, look). In a
-- check run (setting exulanica_gate.check_mode) a test mod may register stand-in players that
-- answer the same methods, so a scripted player walks the same paths a person does on a
-- headless server; in every other run this is the engine and nothing else.

local engine = {}
local check_mode = false
local stand_ins = {}

function engine.init(options)
	check_mode = options.check_mode == true
end

function engine.check_mode()
	return check_mode
end

-- A stand-in player for a check run: an object with the player methods the mod calls, plus
-- told(text) and shown(formname, formspec), which record what a person would have seen.
function engine.add_stand_in(name, object)
	assert(check_mode, "stand-in players exist only in check runs")
	stand_ins[name] = object
end

function engine.remove_stand_in(name)
	stand_ins[name] = nil
end

function engine.player(name)
	local player = core.get_player_by_name(name)
	if player then
		return player
	end
	return stand_ins[name]
end

function engine.connected()
	local names = {}
	for _, player in ipairs(core.get_connected_players()) do
		names[#names + 1] = player:get_player_name()
	end
	for name in pairs(stand_ins) do
		names[#names + 1] = name
	end
	table.sort(names)
	return names
end

function engine.tell(name, text)
	local stand_in = stand_ins[name]
	if stand_in then
		stand_in:told(text)
		return
	end
	core.chat_send_player(name, text)
end

function engine.show_form(name, formname, formspec)
	local stand_in = stand_ins[name]
	if stand_in then
		stand_in:shown(formname, formspec)
		return
	end
	core.show_formspec(name, formname, formspec)
end

return engine
