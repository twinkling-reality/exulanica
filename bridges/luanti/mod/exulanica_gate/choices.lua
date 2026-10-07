-- What a player wants their thing to do, held until the world asks, and the answer to each ask.
--
-- The door gives an outside decider a few seconds from an ask, which no person can meet, so a
-- player's choices are intents: chat lines are queued (at most three), a menu click sets the next
-- action (the latest wins), and every ask is answered at once: a queued line with an offered say
-- option, else the held action if the same option is still offered, else the option that changes
-- nothing. A thing nobody plays is not answered, and the world's routine decides for it.
--
-- The same option across minutes is matched by identity, not label: labels carry distances that
-- change every minute, so an option is known by its record's text and true-or-false members other
-- than its label, ignoring numbers.

local choices = {}

local LINES_QUEUED = 3
local subjects = {}
local asked_requests = {}

function choices.identity(option)
	local parts = {}
	for key, value in pairs(option) do
		if key ~= "label" and (type(value) == "string" or type(value) == "boolean") then
			parts[#parts + 1] = key .. "=" .. tostring(value)
		end
	end
	table.sort(parts)
	return table.concat(parts, "\n")
end

local function says(option)
	return option.line_characters_maximum ~= nil
end
choices.says = says

-- Whether an ask offers anything to say.
function choices.speaks(frame)
	for _, option in ipairs(frame.context and frame.context.options or {}) do
		if says(option) then
			return true
		end
	end
	return false
end

-- The offered option that changes nothing: the frame's idle_label once the door sends it, else
-- (until then, and only for package 3a) an option of kind carry_on, then wait.
function choices.idle(frame)
	local options = frame.context and frame.context.options or {}
	if type(frame.idle_label) == "string" then
		for _, option in ipairs(options) do
			if option.label == frame.idle_label then
				return option
			end
		end
	end
	for _, kind in ipairs({"carry_on", "wait"}) do
		for _, option in ipairs(options) do
			if option.kind == kind then
				return option
			end
		end
	end
	return nil
end

local function mentions(option, id)
	for key, value in pairs(option) do
		if key ~= "label" and value == id then
			return true
		end
	end
	return false
end

-- The say option a line goes with: the one chosen in the menu, else one to whoever last spoke to
-- this thing, else the first offered (the nearest; "everyone near you" comes last).
local function say_option(subject, options)
	local offered = {}
	for _, option in ipairs(options) do
		if says(option) then
			offered[#offered + 1] = option
		end
	end
	if #offered == 0 then
		return nil
	end
	if subject.addressee then
		for _, option in ipairs(offered) do
			if choices.identity(option) == subject.addressee then
				return option
			end
		end
	end
	if subject.last_speaker then
		for _, option in ipairs(offered) do
			if mentions(option, subject.last_speaker) then
				return option
			end
		end
	end
	return offered[1]
end

function choices.bind(subject_id, info)
	local subject = subjects[subject_id] or {lines = {}}
	subject.grant_id = info.grant_id
	subject.player = info.player
	subject.mode = info.mode
	subjects[subject_id] = subject
	return subject
end

function choices.unbind(subject_id)
	local subject = subjects[subject_id]
	if subject then
		subject.player = nil
		subject.action = nil
		subject.addressee = nil
		subject.lines = {}
	end
end

function choices.subject(subject_id)
	return subjects[subject_id]
end

function choices.of_player(name)
	for subject_id, subject in pairs(subjects) do
		if subject.player == name then
			return subject_id, subject
		end
	end
	return nil
end

function choices.forget_grant(grant_id)
	for subject_id, subject in pairs(subjects) do
		if subject.grant_id == grant_id then
			subjects[subject_id] = nil
		end
	end
end

-- The most characters a say option of the latest ask takes, or the line rule's 200.
function choices.line_maximum(subject)
	local options = subject.asked and subject.asked.context and subject.asked.context.options or {}
	for _, option in ipairs(options) do
		if says(option) and tonumber(option.line_characters_maximum) then
			return tonumber(option.line_characters_maximum)
		end
	end
	return 200
end

function choices.queue_line(subject, line)
	if #subject.lines >= LINES_QUEUED then
		return false
	end
	subject.lines[#subject.lines + 1] = line
	return true
end

function choices.hold_action(subject, option)
	subject.action = {key = choices.identity(option), label = option.label}
end

function choices.choose_addressee(subject, option)
	subject.addressee = option and choices.identity(option) or nil
end

-- The answer to an ask: {label, line, what, option}, or nil and why it is not answered.
-- `dropped(subject, label)` is told when a held action is no longer offered.
function choices.decide(frame, dropped)
	local subject = subjects[frame.subject_id]
	if not subject then
		return nil, "not this server's"
	end
	subject.asked = frame
	if not subject.player then
		return nil, "nobody plays it"
	end
	local options = frame.context and frame.context.options or {}
	if #subject.lines > 0 then
		local option = say_option(subject, options)
		if option then
			return {label = option.label, line = table.remove(subject.lines, 1), what = "line",
				option = option}
		end
	end
	if subject.action then
		local held = subject.action
		subject.action = nil
		for _, option in ipairs(options) do
			if choices.identity(option) == held.key then
				return {label = option.label, what = "action", option = option}
			end
		end
		dropped(subject, held.label)
	end
	local idle = choices.idle(frame)
	if idle then
		return {label = idle.label, what = "idle", option = idle}
	end
	return nil, "no option that changes nothing"
end

-- An answer was sent for an ask: kept until the ask's outcome arrives.
function choices.sent(frame, decision)
	asked_requests[frame.request_id] = {subject_id = frame.subject_id, decision = decision}
end

-- What was sent for an ask, taken once: when its outcome arrives, or when the door refused it.
function choices.take(request_id)
	local sent = asked_requests[request_id]
	asked_requests[request_id] = nil
	return sent
end

-- An answer that did not count (too late, or lost on the way): its line or action goes back to be
-- answered at the next ask.
function choices.restore(sent)
	if not sent then
		return
	end
	local subject = subjects[sent.subject_id]
	local decision = sent.decision
	if subject and subject.player then
		if decision.what == "line" and #subject.lines < LINES_QUEUED then
			table.insert(subject.lines, 1, decision.line)
		elseif decision.what == "action" and not subject.action then
			choices.hold_action(subject, decision.option)
		end
	end
end

return choices
