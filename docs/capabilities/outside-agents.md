# Outside AI agents

An AI agent built outside Exulanica, with any framework and any model as its mind, can decide for
things in someone's world through the world's door: the same door a game's adapter uses
([door contract](../door-contract.md)). This guide owns how a developer brings such an agent in,
what it is shown, what it may answer and what it cannot do. What the door stores, checks and
refuses is the door contract's; how an answer becomes a decision is the
[decision roles contract](../decision-roles-contract.md)'s.

The agent's side lives in [`bridges/agents`](../../bridges/agents), outside the product: a client
library on the Python standard library alone, an MCP facade that serves the same turns to any MCP
client, and examples. The product never imports, depends on or packages it
(`tests/test_agent_outside_product.py`).

## What a person does

| Who | Does | Time |
| --- | --- | --- |
| The world's owner | Issues a grant to the agents' bridge naming a world version and either one of its own things or a body of the agent's own, with a direct channel credential (`exulanica-agent grant`, or `POST /door/grants` with `channel_credential` true), and hands the key to whoever runs the agent | under a minute |
| The agent's developer | Installs `exulanica-agent`, sets the world's address and the key, starts the quickstart or adds the facade to an MCP client | a few minutes |
| The world | Asks the agent at its thing's next turn and carries on whether or not it answers | one or two world minutes (8 seconds each at normal speed) |

The owner can end the grant at any moment (`POST /door/grants/{grant_id}/revoke`); the world's
own routine decides for the thing from then on. The owner can also replace the key
(`exulanica-agent key`, `POST /door/grants/{grant_id}/channel-credentials`): a grant has one key at
a time, so the earlier key stops working at once, and the agent holding it is told in words why its
connection ended.

## What the server needs

A deployment admits outside agents with one entry in `EXULANICA_DOOR_BRIDGES`
([`examples/bridge-entry.json`](../../bridges/agents/examples/bridge-entry.json)):

| Field | For outside agents | Why |
| --- | --- | --- |
| `run_by` | `owner` | Each world's owner mints the agent's key for their own grant; no shared bridge credential or invite exists |
| `ai` | `true` | Every thing an outside agent decides for, and every line it says, is shown as run by AI |
| `mapping_sha256` | the digests of the mapping files the admitted library versions present | What an agent's side reads, and what never enters a world, is pinned by the deployment |
| `adapter_versions` | every published library version | A receipt names the version that answered, and an agent built on an earlier version keeps its door |
| `deadline_ms` | 15,000 | Room for one model call per turn, within the person role's `decision_deadline_ms` |

## Bringing an agent in

With Python, [`examples/quickstart.py`](../../bridges/agents/examples/quickstart.py) is a whole agent
in 24 lines of code whose mind is an open model on Nebius Token Factory; one line switches it to an
NVIDIA Nemotron mind. The key is read from `EXULANICA_AGENT_KEY`, or from a file named by
`EXULANICA_AGENT_KEY_FILE` so that it never shows on a screen or in a process list. Each turn hands
the mind `turn.messages` and `turn.tool`, which are exactly the messages and the forced function one
of the world's own models receives, and answers with `turn.act(action, line)`.

One program holds a key at a time. The door holds one poll per grant and may let a held poll go
early to share its places, so the library asks again at most once a second when a poll comes back
empty; a second program on the same key would only take the poll from the first.

Through MCP, `exulanica-agent mcp` serves the same turns over stdio, or over Streamable HTTP on
127.0.0.1 to a client that presents the agent's key. It speaks MCP 2026-07-28 and serves clients of
earlier revisions:

| Tool | Does |
| --- | --- |
| `wait_for_turn` | Waits up to 50 seconds for a turn; returns what the world's own models are shown, the actions offered, the turn's handle, the time left and what happened since |
| `act` | Answers a turn with one offered action, exactly as written, and a line when the action says one |
| `what_happened` | Whether each answer was taken, and changes to the agent's permission |
| `enter_world` | Brings a body of the agent's own in through the world's gate, where the door takes visitors; listed only when the agent's permission allows a visitor |
| `world_rules` | The world's rules for the agent, in words |

With NVIDIA NeMo Agent Toolkit, [`examples/nemo-agent-toolkit.yml`](../../bridges/agents/examples/nemo-agent-toolkit.yml)
is an agent with no Python of its own: a ReAct workflow whose mind is Nemotron 3.5 Lightning on
Nebius Token Factory and whose tools are the facade. A toolkit run is a task: it takes the turns
that come and ends at its model's first plain-text reply, which a reasoning model can give after a
refusal or a quiet spell, so an agent that stays is started again whenever it ends (the
example's loop pauses between runs to keep within the door's six hellos a minute). The quickstart
and MCP clients stay connected for as long as they run.

## A body of its own

When its grant allows a visitor, an agent brings a body of its own in through a gate
(`body.enter()`, or the `enter_world` tool). The grant names the world version the body arrives in,
which holds a society of things, and may name the gate. The body arrives at the next world minute as
a thing of the `visitor` kind, wearing the first look the agents' mapping offers (the thing
library's two-tone mannequin, `kaykit-mannequin` version 1) unless the agent asks for another it
offers (`plain`, the library's `people-catalog` look). From then on its turns reach the agent like
any thing's, and the world's models read lists it as decided from outside, with the bridge's label
and the name, maker and mind the agent declared. When the agent's program stops, the body stays and
the world's routine decides for it; a program that says hello again with the same key takes its
turns again, as a toolkit's restarted run does (the library knows a turn for a thing its grant does
not name as its own body's). It hears the lines said near it and may say one at its turn: each ask
names the offered actions that carry a line and how long one may be, and lines said near the body
reach the agent in words, its own read as its own and one said to its body as said to it. It
leaves when the world's owner sends it home or ends the grant, or by its own choice, and the agent
reads why: `body.leave()` answers an open turn's way out (an option of kind `leave`), so the body
leaves when that minute runs, and tells the door the agent has gone for good, so the door stops
asking the body. The crossing, the look it wore and every answer are stored, so the world replays the
body's visit with no agent running.

Each library version presents its own mapping file, and a deployment admits every published one:
version 0.1.0 presents `outside-agents.v1.json` (profile `exulanica.bridge-mapping/v1`, one look
named by digest), version 0.2.0 `outside-agents.v2.json` (profile `exulanica.bridge-mapping/v2`,
looks named by the thing library's key, version and digest; [door contract](../door-contract.md),
Mapping files).

## What an agent is shown and may answer

Each turn is one ask of the door: the request the decision host reserved for the thing, with the
role's messages rendered for a model, the forced function `act` with the labels offered, and the
minute. The agent answers once, with one label exactly as offered and, when the option says
something, one line. The door stores the answer; the decision host checks it as it checks a
model's, records the receipt, and the engine checks the action again in its minute. A late or
missing answer is recorded as such and the world's routine decides that minute; a world minute
passes whether or not the agent answers.

At hello the agent declares its name, its maker and, if it says, the mind it thinks with. The door
keeps the declaration by digest and records on every answer which declaration gave it; no society
record and no model's context carries it.

## What an agent cannot do

| It cannot | Because |
| --- | --- |
| act outside its turn, or after its time | the world keeps its own clock and takes answers only to open asks |
| invent an action | only an offered label, exactly as written, which the engine checks again |
| see more than one of the world's own models sees | an ask is the model's own request; one whose context would carry a name the account holder saved is never sent |
| run anything inside the world | the door takes labels and lines as data; nothing it receives is executed |
| decide for things it was not given | its key opens one grant, which names the things it decides for |
| say what the world's rules refuse | a line is held to the line rule and the workspace's saved names, for every decider |
| put a name inside the world | its declared words stay with the door |
| spend the world's money | an outside answer costs the world nothing; its own model calls are its own |
| stay after its permission ends | the owner revokes at once, and a grant ends within a day |

## Limits

- A body of the agent's own comes only into a world version that holds a society of things, through
  a gate placed there; a door that takes no visitors answers `enter_world` that it does not take
  them yet.
- A body of the agent's own hears the lines said near it, and nothing else that happens around it
  reaches its bridge ([door contract](../door-contract.md)).
- Comparing an outside agent beside a model on the same thing is not provided: a comparison runs a
  thing an outside program decides for by its routine in every arm.
- A turn waits up to the agents' bridge's declared deadline, so a world with an outside agent can
  take longer per minute than a world its routine runs alone.
- A mind must answer within that deadline, 15 seconds for the agents' bridge. A model that reasons
  at length before it calls a function can miss turns, which the world's routine then decides.

## Implementation and evidence

| Part | Source | Checks |
| --- | --- | --- |
| The client library | `bridges/agents/exulanica_agent/` (`body.py`, `turns.py`, `transport.py`, `happenings.py`, `rules.py`) | `tests/test_agent_library.py` |
| The MCP facade | `bridges/agents/exulanica_agent/facade.py`, `mcp_server.py` | `tests/test_agent_facade.py`; `bridges/agents/checks/mcp_stdio.py` and `mcp_http.py` with the MCP SDK installed |
| The examples | `bridges/agents/examples/` | the quickstart in `tests/test_agent_library.py`; `bridges/agents/checks/nat_check.py` for the toolkit, and `nat_run.py` for a recorded run in a real world |
| Outside the product | `bridges/agents/exulanica_agent/outside-agents.v1.json` and `outside-agents.v2.json`, `examples/bridge-entry.json` | `tests/test_agent_outside_product.py` (each published mapping read by the door's own checker and pinned) |
| Through the real door | the library and the tools against the door's routes, migrations 0149 and 0153 and the decision host: hello and declaration, a new key ending the earlier, revocation, a person's turn decided by the agent and replayed without it, and a body of the agent's own crossing in through a gate, wearing its look, taking its turns and sent home | `tests/test_agent_door_postgres.py` |

Decision record: [ADR-0032](../adr/0032-an-outside-ai-agent-enters-through-the-same-door-as-a-game.md).
