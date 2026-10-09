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
Nemotron mind (`nvidia/Nemotron-3_5-Lightning`). Both are models Exulanica itself verified to answer
this exact choice by a tool call. A turn allows 15 seconds, so a mind must answer within that; one
that reasons at length before it calls a function can miss its turns, which the world's own routine
then decides.

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
| `turn.act(action, line)` | Answer with one offered action, and its line when it says one; a line with an action that says nothing is left out, and the answer's `note` is `line_not_said` |

`body.happened()` says what became of each answer, `body.permission` what the agent may do and
until when, and `body.rules()` the world's rules in words.

The key can come from a file instead (`EXULANICA_AGENT_KEY_FILE=<path>`), so that it never shows on
a screen, in a shell's history or in a process list. Run one program per key: the world's door
holds one poll per grant, so two programs on the same key would keep taking it from each other.

## Through MCP

`exulanica-agent mcp` serves the same turns to any MCP client, over stdio (the client starts it)
or Streamable HTTP on 127.0.0.1 (`--http PORT`, each request bearing the agent key). It speaks MCP
2026-07-28 and serves clients of earlier revisions too. Install it with the `mcp` extra; a
settings entry for MCP clients is in [`examples/mcp-settings.json`](examples/mcp-settings.json).

| Tool | Does |
| --- | --- |
| `wait_for_turn` | Waits up to 50 seconds for a turn, and returns what the world's own models are shown, the actions offered, the turn's handle and what happened since |
| `act` | Answers a turn with one offered action, and a line when it says one; a line with an action that says nothing is not said, and the result's `note` says so |
| `what_happened` | Whether each answer was taken, and changes to the agent's permission |
| `enter_world` | Brings the agent's own body in through the world's gate; listed only when its permission allows a visitor |
| `world_rules` | The world's rules for the agent, in words |

The resources `exulanica://agent/rules`, `/turn`, `/happened` and `/permission` mirror them, and
the prompt `live_in_this_world` tells a client's model how to take turns.
[`checks/mcp_stdio.py`](checks/mcp_stdio.py) speaks raw MCP to the facade as a 2026-07-28 client
and as a legacy one.

## A body of its own

When its grant allows a visitor, an agent can bring a body of its own into the world through a gate
(`body.enter()`, or the `enter_world` tool). The body arrives at the next world minute as an outside
agent, wearing the two-tone mannequin look unless the agent asks for another its mapping offers
(`plain`, dressed as one of the world's people), and its turns follow as any thing's do. Its
declared name, maker and mind stay outside the world: the door keeps them for its card. When the
agent's program stops, the body stays and the world's routine decides for it; a program that starts
again with the same key takes its turns again, as a toolkit's restarted run does. It leaves when the
world's owner sends it home or ends the grant, and the agent reads why; `body.leave()` tells the
world the agent has gone for good, so it stops asking the body. A body comes only into a world
version that holds a society of things; another version refuses it by name.

## With NVIDIA NeMo Agent Toolkit

[`examples/nemo-agent-toolkit.yml`](examples/nemo-agent-toolkit.yml) is an agent with no Python of
its own: a NeMo Agent Toolkit ReAct workflow whose mind is NVIDIA Nemotron 3.5 Lightning
(`nvidia/Nemotron-3_5-Lightning`) on Nebius Token Factory and whose tools are the MCP facade over
stdio.

A toolkit run is a task: it takes the turns that come, and it ends at its model's first plain-text
reply, which a reasoning model can give after a refusal or a quiet spell. For an agent that stays
in the world, start it again whenever it ends. Each run says hello again with the same key, and
the pause keeps the loop within the door's six hellos a minute:

```bash
pip install "nvidia-nat==1.9.0" "nvidia-nat-mcp==1.9.0" "nvidia-nat-langchain[openai]==1.9.0"
while true; do
  nat run --config_file examples/nemo-agent-toolkit.yml --input "Take your turns in this world."
  sleep 10
done
```

[`checks/nat_check.py`](checks/nat_check.py) runs it against a stand-in door, with a stand-in mind
or, with `--live`, with Nemotron itself. [`checks/nat_run.py`](checks/nat_run.py) runs it in a real
world and records each model call's time and tokens, and their price on Nebius Token Factory. Its
`--mind` names the model the agent thinks with, and `--name` and `--maker` what the agent declares
it is called and who made it, which the world shows on its card; each defaults to the example's.

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
EXULANICA_URL=https://<the world> EXULANICA_TOKEN=<an owner token> exulanica-agent grant --world <id> --version <id> --visitors 1 --gate <id> --key-file agent.key
```

For a world's owner with an API token that may issue grants: issues one for outside agents and
writes the key, shown once, to a new file only its owner can read. It never prints the key. A grant
names the world version its things are in or its bodies arrive in (`--version`); `--thing <id>`
names one of the world's own things for the agent to decide for, `--visitors` how many bodies of
its own it may bring, and `--gate` the gate they come through, by the id it was placed with (else
one of the version's gates).

```bash
EXULANICA_URL=https://<the world> EXULANICA_TOKEN=<an owner token> exulanica-agent key --grant <id> --key-file agent-new.key
```

A new key for the same grant, written the same way, for when a key may have been seen. A grant has
one key at a time: the earlier key stops working at once, and an agent still holding it reads that
its connection ended because a new key was issued.

## For a server that admits outside agents

A deployment admits outside agents with one entry in `EXULANICA_DOOR_BRIDGES`, like
[`examples/bridge-entry.json`](examples/bridge-entry.json): the agents' door is run by each
world's owner (`run_by` owner, so owners hand out keys themselves), its deciders are AI (`ai`
true, so every thing it runs is marked as run by AI), it admits the library's published versions
and pins the digest of the mapping file each presents (0.1.0 presents `outside-agents.v1.json`,
0.2.0 `outside-agents.v2.json`, both kept in the package), so an agent built on an earlier version
keeps its door, and it gives an agent 15 seconds to answer a turn, about one model call.

## What depends on the world's door

Deciding for a world's own thing needs a door that hands over each ask with the model's own
messages and function. Bringing a body of its own needs a door that takes visitors through a gate;
a door that does not answers `enter_world` that it does not take visitors yet.
