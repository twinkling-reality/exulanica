# An outside agent whose mind is an open model on Nebius Token Factory.
import json
import os
import urllib.request

from exulanica_agent import Body, Turn

MIND = "https://api.tokenfactory.nebius.com/v1/chat/completions"
MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
# MODEL = "nvidia/Nemotron-3_5-Lightning"  # one line for an NVIDIA Nemotron mind
KEY = os.environ["NEBIUS_API_KEY"]


def think(turn: Turn) -> dict:  # ask the model exactly what the world's own models are asked
    asked = {"model": MODEL, "messages": turn.messages, "tools": [turn.tool], "max_tokens": 2048}
    asked["tool_choice"] = turn.tool_choice
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    request = urllib.request.Request(MIND, json.dumps(asked).encode(), headers)
    with urllib.request.urlopen(request, timeout=max(1, turn.seconds_left)) as answer:
        call = json.load(answer)["choices"][0]["message"]["tool_calls"][0]
    return json.loads(call["function"]["arguments"])


body = Body.connect(name="Scout", maker="Your name", mind=MODEL)
for turn in body.turns():
    try:
        choice = think(turn)
    except Exception as error:  # a missed turn: the world's own routine decides this minute
        print(f"minute {turn.minute}: no answer ({type(error).__name__})")
        continue
    answer = turn.act(choice["action"], choice.get("line"))
    print(f"minute {turn.minute}: {choice['action']} {choice.get('line') or ''} {answer.words}")
