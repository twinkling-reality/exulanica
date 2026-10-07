-- The menu of what the world offers this minute: one button per offered option, a "Talk to" list
-- when lines can be said, and when it happens. Shown by /x and, while a player's choices go to a
-- world, as their inventory form.
--
-- Every label comes from the world and is untrusted text: cleaned of control characters, clipped
-- and escaped before it enters a form. A button's name is an index into the options kept for that
-- showing, so a submission can only ever pick an option this server showed.

local menu = {}

menu.FORM = core.get_current_modname() .. ":menu"
local LABEL_LIMIT = 72
local showings = {}

local function escaped(lines, text)
	return core.formspec_escape(lines.incoming(text, LABEL_LIMIT))
end

-- The form for `subject` and the record of what it shows.
function menu.build(name, subject, deps)
	local lines, choices = deps.lines, deps.choices
	local frame = subject.asked
	local options, says = {}, {}
	if frame and frame.context and type(frame.context.options) == "table" then
		for _, option in ipairs(frame.context.options) do
			if choices.says(option) then
				says[#says + 1] = option
			else
				options[#options + 1] = option
			end
		end
	end
	local seat = subject.mode == "seat"
	local title = seat and "What does the one you play do?" or "What does your traveller do?"
	local parts = {
		"formspec_version[6]",
		"",
		"label[0.5,0.6;" .. core.formspec_escape(title) .. "]",
	}
	local y = 1.1
	if not frame then
		parts[#parts + 1] = "label[0.5,1.4;" .. core.formspec_escape(
			"Waiting for the world's next minute...") .. "]"
		y = y + 0.8
	end
	for index, option in ipairs(options) do
		parts[#parts + 1] = string.format("button_exit[0.5,%.2f;10,0.8;exg_o%d;%s]", y, index,
			escaped(lines, option.label))
		y = y + 0.95
	end
	local talk_default
	if #says > 0 then
		local items = {}
		talk_default = 1
		for index, option in ipairs(says) do
			items[index] = escaped(lines, option.label)
			if subject.addressee and choices.identity(option) == subject.addressee then
				talk_default = index
			end
		end
		parts[#parts + 1] = string.format("label[0.5,%.2f;%s]", y + 0.4,
			core.formspec_escape("Talk to:"))
		parts[#parts + 1] = string.format("dropdown[2.1,%.2f;8.4,0.8;exg_talk;%s;%d;true]", y,
			table.concat(items, ","), talk_default)
		y = y + 1.1
	end
	parts[#parts + 1] = string.format("label[0.5,%.2f;%s]", y + 0.3, core.formspec_escape(
		#says > 0 and "It happens at the next world minute. Chat to speak."
			or "It happens at the next world minute."))
	y = y + 0.75
	if seat then
		parts[#parts + 1] = string.format("button_exit[0.5,%.2f;5.2,0.8;exg_back;%s]", y,
			core.formspec_escape("Step back out of the gate"))
	end
	parts[#parts + 1] = string.format("button_exit[7.5,%.2f;3,0.8;exg_close;Close]", y)
	parts[2] = string.format("size[11,%.2f]", y + 0.8 + 0.4)
	showings[name] = {options = options, says = says, talk_default = talk_default}
	return table.concat(parts)
end

-- Act on a submission of the menu: on.hold(option), on.addressee(option), on.back().
function menu.fields(name, fields, on)
	local showing = showings[name]
	if not showing then
		return false
	end
	local acted = false
	for key in pairs(fields) do
		local index = type(key) == "string" and key:match("^exg_o(%d+)$")
		if index then
			local option = showing.options[tonumber(index)]
			if option then
				on.hold(option)
				acted = true
			end
		end
	end
	local talk = tonumber(fields.exg_talk)
	if talk and talk ~= showing.talk_default and showing.says[talk] then
		on.addressee(showing.says[talk])
		acted = true
	end
	if fields.exg_back then
		on.back()
		acted = true
	end
	return acted
end

function menu.forget(name)
	showings[name] = nil
end

return menu
