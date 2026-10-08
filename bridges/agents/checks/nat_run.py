"""Run the NeMo Agent Toolkit example in a real world, and record what its mind cost and took.

    python3 bridges/agents/checks/nat_run.py --nat <a nat command> --facade-python <a Python with
        exulanica-agent[mcp]> --world <the world's address> --key-file <the agent's key file>
        --manifest <the product's models.manifest.json> --record <a new JSON file>
        [--input "<what to ask the agent>"] [--mind <a model id>] [--name <a name>]
        [--maker <a maker>]

The world is real: the facade says hello on the grant the key opens, and the agent takes its turns
there. The mind is the example's own, Nemotron on Nebius Token Factory, or the model ``--mind``
names (one the manifest prices), reached through a local relay that forwards each request
unchanged but for streaming, with the key from this process's ``NEBIUS_API_KEY``, and times and
counts every call. ``--name`` and ``--maker`` change what the agent declares about itself and the
name its instructions call it by. The toolkit's trace goes to this terminal as it runs, for a
screen recording; the agent's key and the model key never appear in it, on a command line or in
the record. The record states each call's start, duration in milliseconds, tokens and the model
the toolkit asked for, the totals, and their price in US dollars (a decimal string) on Nebius
Token Factory at the manifest's per-token prices.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nat_check import EXAMPLE, _config, _Relay, _serve_mind


def _example(key: str) -> str:
    """A value the example sets, read from the example rather than restated here."""
    return next(
        line.split(":", 1)[1].strip()
        for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(f"{key}:")
    )


#: The example's own mind.
MODEL = _example("model_name")


class _TimedRelay(_Relay):
    """The relay, keeping each call's start, duration and tokens."""

    def __init__(self) -> None:
        super().__init__()
        self.per_call: list[dict[str, Any]] = []

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        before = (self.prompt_tokens, self.completion_tokens, len(self.calls))
        message = super().answer(request)
        self.per_call.append(
            {
                "at": at,
                "ms": round((time.monotonic() - started) * 1000),
                "model": request.get("model"),
                "prompt_tokens": self.prompt_tokens - before[0],
                "completion_tokens": self.completion_tokens - before[1],
                "called": self.calls[before[2] :],
            }
        )
        return message


def _usd(manifest: Path, mind: str, prompt: int, completion: int) -> str:
    spec = json.loads(manifest.read_text(encoding="utf-8"))["models"][mind]
    usd = (
        Decimal(prompt) * Decimal(str(spec["input_usd_per_mtok"]))
        + Decimal(completion) * Decimal(str(spec["output_usd_per_mtok"]))
    ) / Decimal(1_000_000)
    return str(usd.quantize(Decimal("0.000001")))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--nat", required=True)
    parser.add_argument("--facade-python", required=True)
    parser.add_argument("--world", required=True, help="the world's address")
    parser.add_argument("--key-file", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--input", default="Take your turns in this world.")
    parser.add_argument("--mind", default=MODEL, help="the model the agent thinks with")
    parser.add_argument("--name", default=_example("EXULANICA_AGENT_NAME"))
    parser.add_argument("--maker", default=_example("EXULANICA_AGENT_MAKER"))
    arguments = parser.parse_args()
    if arguments.record.exists():
        print(f"{arguments.record} exists; the record goes into a new file", file=sys.stderr)
        return 2
    if not os.environ.get("NEBIUS_API_KEY"):
        print("set NEBIUS_API_KEY in this process's environment", file=sys.stderr)
        return 2
    if arguments.mind not in json.loads(arguments.manifest.read_text(encoding="utf-8"))["models"]:
        print(
            f"the manifest prices no model {arguments.mind}; choose one it lists", file=sys.stderr
        )
        return 2
    relay = _TimedRelay()
    server, relay_url = _serve_mind(relay)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "EXULANICA_URL": arguments.world,
        "EXULANICA_AGENT_KEY_FILE": str(arguments.key_file.resolve()),
        "EXULANICA_AGENT_PATH": str(EXAMPLE.parents[1]),
        "NEBIUS_API_KEY": "relayed",
    }
    started = dt.datetime.now(dt.UTC)
    clock = time.monotonic()
    with tempfile.TemporaryDirectory() as folder:
        config = _config(
            arguments.facade_python,
            relay_url,
            Path(folder),
            mind=arguments.mind,
            name=arguments.name,
            maker=arguments.maker,
        )
        run = subprocess.run(
            [arguments.nat, "run", "--config_file", str(config), "--input", arguments.input],
            env=env,
            timeout=3600,
        )
    server.shutdown()
    record = {
        "profile": "exulanica-agent-run/v1",
        "started_at": started.isoformat(timespec="seconds"),
        "ms": round((time.monotonic() - clock) * 1000),
        "world": arguments.world.split("://", 1)[-1].split("/", 1)[0],
        "mind": arguments.mind,
        "declared": {"name": arguments.name, "maker": arguments.maker},
        "account": "Nebius Token Factory",
        "calls": len(relay.per_call),
        "prompt_tokens": relay.prompt_tokens,
        "completion_tokens": relay.completion_tokens,
        "usd": _usd(
            arguments.manifest, arguments.mind, relay.prompt_tokens, relay.completion_tokens
        ),
        "price_source": "the manifest's input_usd_per_mtok and output_usd_per_mtok",
        "nat_exit": run.returncode,
        "per_call": relay.per_call,
    }
    descriptor = os.open(arguments.record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    print(json.dumps({key: record[key] for key in ("calls", "usd", "ms", "nat_exit")}))
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
