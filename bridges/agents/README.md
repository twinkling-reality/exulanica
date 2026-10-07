# Bring your own AI agent into an Exulanica world

Any AI agent (any program, any framework, any model) can live in an Exulanica world through the
world's door, the same door a game character crosses. The world's owner lets it in and hands over a
key. Each time one of its things may act, the agent is shown exactly what one of the world's own
models is shown, chooses one of the actions offered, and may say a line. The world checks every
answer, records it, and later replays the agent's run without the agent.

This folder is outside the product: the product never imports it, and nothing here ships in the
product's package or images. The library is the Python standard library only; the MCP facade
alone needs the MCP SDK.

## What you need

- The world's address and an agent key from its owner. The owner issues a grant for outside
  agents (the agents' door) and sees the key once.
- Python 3.11 or later.
- A mind: any model you can call. The quickstart uses an open model on Nebius Token Factory, with
  your own account and key.

```bash
pip install "exulanica-agent @ git+https://github.com/twinkling-reality/exulanica#subdirectory=bridges/agents"
```

Copying the `exulanica_agent` folder next to your program works too.

## The quickstart

[`examples/quickstart.py`](examples/quickstart.py) is a whole agent in 24 lines of code. Its mind
is `Qwen/Qwen3-235B-A22B-Instruct-2507` on Nebius Token Factory; one line switches it to an NVIDIA
Nemotron mind (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`). Both are models Exulanica itself verified
to answer this exact choice by a tool call.

```bash
EXULANICA_URL=https://<the world> EXULANICA_AGENT_KEY=<key> NEBIUS_API_KEY=<yours> python examples/quickstart.py
```

What it does, turn by turn:

```python
body = Body.connect(name="Scout", maker="Your name", mind=MODEL)
for turn in body.turns():
    choice = think(turn)  # your model, given turn.messages, turn.tool and turn.tool_choice
    turn.act(choice["action"], choice.get("line"))
```

| A turn gives | What it is |
| --- | --- |
| `turn.messages` | The system and user messages one of the world's own models receives, in the OpenAI chat format |
| `turn.tool`, `turn.tool_choice` | The one function, `act`, a model answers by, and the choice forcing it |
| `turn.options` | The actions offered, each exactly as an answer must repeat it, and whether it says a line |
| `turn.seconds_left` | How long is left to answer; after that the world's own routine decides that minute |
| `turn.act(action, line)` | Answer with one offered action, and its line when it says one |

`body.happened()` says what became of each answer, `body.permission` what the agent may do and
until when, and `body.rules()` the world's rules in words.

## Through MCP

`exulanica-agent mcp` serves the same turns to any MCP client, over stdio (the client starts it)
or Streamable HTTP on 127.0.0.1 (`--http PORT`, each request bearing the agent key). It speaks MCP
2026-07-28 and serves clients of earlier revisions too. Install it with the `mcp` extra; a
settings entry for MCP clients is in [`examples/mcp-settings.json`](examples/mcp-settings.json).

| Tool | Does |
| --- | --- |
| `wait_for_turn` | Waits up to 20 seconds for a turn, and returns what the world's own models are shown, the actions offered, the turn's handle and what happened since |
| `act` | Answers a turn with one offered action, and a line when it says one |
| `what_happened` | Whether each answer was taken, and changes to the agent's permission |
| `enter_world` | Brings the agent's own body in through the world's gate, when its permission allows a visitor |
| `world_rules` | The world's rules for the agent, in words |

The resources `exulanica://agent/rules`, `/turn`, `/happened` and `/permission` mirror them, and
the prompt `live_in_this_world` tells a client's model how to take turns.
[`checks/mcp_stdio.py`](checks/mcp_stdio.py) speaks raw MCP to the facade as a 2026-07-28 client
and as a legacy one.

## What an agent can and cannot do

It decides only for the things its grant names, or for a body of its own when the grant allows a
visitor, and only at their turns. It cannot:

- act outside a turn or after its time: the world keeps its own clock, and a missed turn is decided
  by the world's routine;
- invent an action: only an offered one, exactly as written, which the world checks again;
- see more than one of the world's own models sees;
- run anything inside the world: only its chosen action and its line enter, as data;
- say what the world's rules refuse: a line is one line within the length its action allows, and
  a line the rules would change is not said;
- put a name inside the world: its declared name, maker and mind are shown on its card only;
- spend the world's owner's money: its answers cost the world nothing, and its own model calls are
  its own;
- stay after the owner ends its grant, which happens at once and on its own within a day.

## The command line

```bash
exulanica-agent check
```

Says hello with the settings above and prints what the agent may do and the world's rules.

```bash
EXULANICA_URL=https://<the world> EXULANICA_TOKEN=<an owner token> exulanica-agent grant --world <id> --visitors 1 --key-file agent.key
```

For a world's owner with an API token that may issue grants: issues one for outside agents and
writes the key, shown once, to a new file only its owner can read. It never prints the key.

## For a server that admits outside agents

A deployment admits outside agents with one entry in `EXULANICA_DOOR_BRIDGES`, like
[`examples/bridge-entry.json`](examples/bridge-entry.json): the agents' door is run by each
world's owner (`run_by` owner, so owners hand out keys themselves), its deciders are AI (`ai`
true, so every thing it runs is marked as run by AI), it pins the digest of the mapping file this
library presents and the library versions it admits, and it gives an agent 15 seconds to answer a
turn, about one model call.

## What depends on the world's door

Deciding for a world's own thing needs a door that hands over each ask with the model's own
messages and function. Bringing a body of its own needs a door that takes visitors through a gate;
until then `enter_world` answers that the door does not take visitors yet.
