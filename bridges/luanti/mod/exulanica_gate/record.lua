-- A recording of a run, for fixtures and timings: every exchange with the door (method, path,
-- status, how long it took, and the request and response bodies as the text they were) and a few
-- marks (a player took a part, an ask was answered). Off unless exulanica_gate.record_exchanges is
-- set. Never a header, so never a credential; marks name no player. Written as JSON lines to
-- <world>/exulanica_gate/exchanges.jsonl.

local record = {}

local path
local started

function record.init(enabled)
	if not enabled then
		return
	end
	local folder = core.get_worldpath() .. "/exulanica_gate"
	core.mkdir(folder)
	path = folder .. "/exchanges.jsonl"
	started = core.get_us_time()
end

local function write(document)
	if not path then
		return
	end
	document.t_ms = math.floor((core.get_us_time() - started) / 1000)
	local line = core.write_json(document)
	local file = line and io.open(path, "a")
	if file then
		file:write(line, "\n")
		file:close()
	end
end

function record.exchange(entry)
	write({
		exchange = true,
		method = entry.method,
		path = entry.path,
		status = entry.code,
		timed_out = entry.timed_out == true,
		ms = entry.ms,
		request_text = entry.body,
		response_text = entry.response ~= "" and entry.response or nil,
	})
end

-- A check run's listener, told every mark as it happens.
record.listener = nil

function record.mark(what, details)
	if record.listener then
		record.listener(what, details or {})
	end
	if not path then
		return
	end
	local document = {mark = what}
	for name, value in pairs(details or {}) do
		document[name] = value
	end
	write(document)
end

return record
