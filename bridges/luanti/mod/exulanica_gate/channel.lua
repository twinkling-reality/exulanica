-- One grant's channel to the door (docs/door-contract.md, bridges/door_client/door_client.py).
--
-- Hello presents the adapter's version, its mapping file and the game fields it reads; then one
-- held poll at a time reads frames after a cursor the door writes, and posts answer asks and
-- report what the game did. The engine hands a mod a response's status and body and never its
-- headers, so everything here is read from bodies. The credential lives in this closure only:
-- it is never logged, recorded, shown or kept anywhere else by this module.
--
-- A failed or timed out request waits 1, 2, 4, 8, then 15 seconds between tries. A refusal is read
-- by its code: hello_first says hello again; grant_ended (410) and a refused credential (401)
-- end the channel; too_many_redemptions and door_busy wait as the body says.

local channel = {}

local BACKOFF_SECONDS = {1, 2, 4, 8, 15}

-- options: http, door_url, credential, adapter_version, mapping_text, reads, json,
-- on_hello(chan, answer), on_frames(chan, frames), on_ended(chan, reason), log(...), record(entry)
function channel.open(options)
	local json = options.json
	local credential = options.credential
	options.credential = nil
	local chan = {
		state = "starting",
		grant = nil,
		hold_seconds = 15,
		cursor = nil,
		polled_at = nil,
	}
	local failures = 0
	local stopped = false
	local generation = 0
	-- Which poll is the current one: a hello or a newer poll makes an older one's answer stale, so
	-- only one poll is ever held for this grant.
	local current_poll = 0

	local function call(method, path, body, timeout, done)
		local headers = {"Authorization: Bearer " .. credential}
		if body then
			headers[2] = "Content-Type: application/json"
		end
		local started = core.get_us_time()
		options.http.fetch({
			url = options.door_url .. path,
			method = method,
			data = body,
			timeout = timeout,
			extra_headers = headers,
			quiet = true,
		}, function(result)
			if stopped then
				return
			end
			local ms = math.floor((core.get_us_time() - started) / 1000)
			local answer
			if result.succeeded and result.data and result.data ~= "" then
				answer = json.parse(result.data)
			end
			options.record({
				method = method, path = path, body = body, code = result.code,
				timed_out = result.timeout, response = result.data, ms = ms,
			})
			done(result, answer, ms)
		end)
	end

	local function wait_then(seconds, again)
		local mine = generation
		core.after(seconds, function()
			if not stopped and mine == generation then
				again()
			end
		end)
	end

	local function failed(again)
		failures = failures + 1
		wait_then(BACKOFF_SECONDS[math.min(failures, #BACKOFF_SECONDS)], again)
	end

	local function finish(reason)
		if chan.state == "ended" then
			return
		end
		chan.state = "ended"
		generation = generation + 1
		options.log("channel %s ended: %s", chan.grant and chan.grant.grant_id:sub(1, 8) or "?", reason)
		options.on_ended(chan, reason)
	end

	local poll

	local function hello()
		chan.state = "hello"
		current_poll = current_poll + 1
		local body = json.object({
			{"adapter_version", json.string(options.adapter_version)},
			{"mapping", options.mapping_text},
			{"reads", json.strings(options.reads)},
		})
		call("POST", "/door/channel/hello", body, 20, function(result, answer)
			local code = result.code
			if code == 200 and type(answer) == "table" and type(answer.cursor) == "string" then
				failures = 0
				chan.grant = answer.grant
				chan.hold_seconds = tonumber(answer.hold_seconds) or 15
				chan.world_words = type(answer.world_words) == "string" and answer.world_words
					or (answer.grant and answer.grant.world_words) or nil
				chan.cursor = answer.cursor
				chan.state = "polling"
				options.log("channel %s hello: adapter %s, hold %d s", chan.grant.grant_id:sub(1, 8),
					options.adapter_version, chan.hold_seconds)
				options.on_hello(chan, answer)
				poll()
			elseif code == 401 then
				finish("credential_refused")
			elseif code == 410 then
				finish("grant_ended")
			elseif code == 403 or code == 422 then
				finish("hello_refused:" .. tostring(answer and answer.code or code))
			else
				failed(hello)
			end
		end)
	end

	poll = function()
		if stopped or chan.state ~= "polling" then
			return
		end
		local path = "/door/channel/frames"
		if chan.cursor then
			path = path .. "?after=" .. core.urlencode(chan.cursor)
		end
		current_poll = current_poll + 1
		local mine = current_poll
		call("GET", path, nil, chan.hold_seconds + 10, function(result, answer)
			if mine ~= current_poll then
				return
			end
			chan.polled_at = core.get_us_time()
			local code = result.code
			if code == 200 and type(answer) == "table" and type(answer.cursor) == "string" then
				failures = 0
				chan.cursor = answer.cursor
				options.on_frames(chan, type(answer.frames) == "table" and answer.frames or {})
				poll()
			elseif code == 409 then
				hello()
			elseif code == 422 then
				chan.cursor = nil
				hello()
			elseif code == 410 then
				finish("grant_ended")
			elseif code == 401 then
				finish("credential_refused")
			elseif code == 429 or code == 503 then
				local seconds = answer and (tonumber(answer.retry_after_s)
					or (tonumber(answer.retry_after_ms) and tonumber(answer.retry_after_ms) / 1000)) or 1
				wait_then(math.max(0.25, math.min(60, seconds)), poll)
			else
				failed(poll)
			end
		end)
	end

	-- Post a body to a channel route; done(code, answer, ms) with code 0 for no answer at all. A
	-- refused credential ends the channel; a door that wants a hello first gets one.
	function chan.post(path, body, done)
		call("POST", path, body, 10, function(result, answer, ms)
			if result.code == 401 then
				finish("credential_refused")
			elseif result.code == 409 and type(answer) == "table" and answer.code == "hello_first"
					and chan.state == "polling" then
				hello()
			end
			done(result.succeeded and result.code or 0, answer, ms)
		end)
	end

	function chan.ready()
		return chan.state == "polling"
	end

	function chan.start()
		hello()
	end

	function chan.stop()
		stopped = true
		chan.state = "stopped"
	end

	return chan
end

-- Redeem an invite as this server's bridge: answer(code, document) with the grant and its
-- channel credential when the door says yes. The code and the credentials pass through here and
-- nowhere else; the requester is a digest that names nobody.
function channel.redeem(options, invite_code, requester, done)
	local json = options.json
	local body = json.object({
		{"code", json.string(invite_code)},
		{"requester", json.string(requester)},
	})
	options.http.fetch({
		url = options.door_url .. "/door/invites/redeem",
		method = "POST",
		data = body,
		timeout = 10,
		extra_headers = {"Authorization: Bearer " .. options.bridge_credential,
			"Content-Type: application/json"},
		quiet = true,
	}, function(result)
		local answer = result.succeeded and json.parse(result.data) or nil
		done(result.succeeded and result.code or 0, answer)
	end)
end

return channel
