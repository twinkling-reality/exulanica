"""One NeMo Agent Toolkit run of an outside agent in a real world, inside a call and spend cap.

    python3 scripts/demo/agent_toolkit_run.py --nat <the toolkit's nat command> --facade-python
        <a Python with the agent library's MCP extra> --world <the stack's API address>
        --key-file <the agent's key file> --record <a new JSON file> --mind <a model id the
        manifest prices> --name <a name> --maker <a maker> --input "<the task>"
        --max-calls N --max-usd X --deadline-s S [--stand-in]
    python3 scripts/demo/agent_toolkit_run.py --used <a folder of such records>

The run is ``bridges/agents/checks/nat_run.py``'s (its relay, its configuration, its record's
fields), with what a bounded allocation needs: the relay refuses a call once N calls were made, or
once their price at the manifest's per-token prices reached X or would pass X if the next call
cost as much as the dearest so far (a call's price is known only when it is answered, so the
first call is the only one that can pass X); the toolkit run then ends. The toolkit
and the facade it started are stopped together after S seconds; and the record lists, in order,
each call's outcome (``ok``, the provider error's type, or ``refused: the bound``), so a stop
rule (a third provider error in a row) can be read across runs. The record's ``answers`` are the
agent's own side of the run: each tool its mind called with the arguments it gave, or the words it
answered with, each with its time. With ``--stand-in`` the mind is a
stand-in built on the check's own (no provider, no key, no cost): it enters the world when the
grant offers a body, then waits for turns and answers up to three with the first action offered.
The model key comes from this process's ``NEBIUS_API_KEY`` only; the toolkit holds a stand-in key;
neither is written anywhere.

``--used`` prints three figures summed over the folder's ``agent-run-<n>.json`` records in order:
the calls made, their price in US dollars, and how many provider errors end the calls in a row.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ROOT / "bridges" / "agents" / "checks"
MANIFEST = ROOT / "exulanica" / "models" / "models.manifest.json"
REFUSED = "refused: the bound"


def used(folder: Path) -> tuple[int, Decimal, int]:
    """Calls, dollars and the provider errors in a row at the end, over a folder's run records."""
    records = sorted(
        folder.glob("agent-run-*.json"), key=lambda path: int(path.stem.rsplit("-", 1)[1])
    )
    calls, usd, outcomes = 0, Decimal(0), []
    for path in records:
        record = json.loads(path.read_text(encoding="utf-8"))
        calls += record["calls"]
        usd += Decimal(record["usd"])
        outcomes += record.get("outcomes", [])
    row = 0
    for outcome in reversed(outcomes):
        if outcome == "ok" or outcome == REFUSED:
            break
        row += 1
    return calls, usd, row


def may_call(
    calls: int, spent: Decimal, dearest: Decimal, *, max_calls: int, max_usd: Decimal
) -> bool:
    """Whether the allocation has room for one more call: a call left, the dollars not reached, and
    room for a call as dear as the dearest answered so far."""
    return calls < max_calls and spent < max_usd and spent + dearest <= max_usd


def answers_of(message: Mapping[str, Any], at: str) -> list[dict[str, Any]]:
    """What a mind's answer did, as the run's own account: each tool called with the arguments it
    gave (arguments that are not JSON are kept as text), or the words it answered with."""
    kept: list[dict[str, Any]] = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
        except (TypeError, ValueError):
            arguments = {"unread": str(function.get("arguments"))[:400]}
        kept.append({"at": at, "tool": function.get("name"), "arguments": arguments})
    if not kept and message.get("content"):
        kept.append({"at": at, "words": str(message["content"])[:600]})
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--used", type=Path)
    for name in ("--nat", "--facade-python", "--world", "--mind", "--name", "--maker", "--input"):
        parser.add_argument(name)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--max-usd", type=Decimal)
    parser.add_argument("--deadline-s", type=float)
    parser.add_argument("--stand-in", action="store_true")
    args = parser.parse_args()
    if args.used is not None:
        calls, usd, row = used(args.used)
        print(calls, usd, row)
        return 0
    missing = [name for name, value in vars(args).items() if value is None and name != "used"]
    if missing:
        parser.error("a run needs --" + ", --".join(name.replace("_", "-") for name in missing))
    sys.path.insert(0, str(CHECKS))
    from nat_check import _OPTION, _TURN, EXAMPLE, _config, _Mind, _serve_mind
    from nat_run import _TimedRelay, _usd

    if args.record.exists():
        print(f"{args.record} exists; the record goes into a new file", file=sys.stderr)
        return 2
    if not args.stand_in and not os.environ.get("NEBIUS_API_KEY"):
        print("set NEBIUS_API_KEY in this process's environment", file=sys.stderr)
        return 2
    outcomes: list[str] = []
    answers: list[dict[str, Any]] = []

    def now() -> str:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    class CappedRelay(_TimedRelay):
        dearest = Decimal(0)

        def priced(self) -> Decimal:
            return Decimal(_usd(MANIFEST, args.mind, self.prompt_tokens, self.completion_tokens))

        def answer(self, request: dict[str, Any]) -> dict[str, Any]:
            spent = self.priced()
            if not may_call(
                len(self.per_call),
                spent,
                self.dearest,
                max_calls=args.max_calls,
                max_usd=args.max_usd,
            ):
                outcomes.append(REFUSED)
                raise RuntimeError("the agent's allocation is reached")
            try:
                message = super().answer(request)
            except Exception as error:
                outcomes.append(type(error).__name__)
                raise
            self.dearest = max(self.dearest, self.priced() - spent)
            outcomes.append("ok")
            answers.extend(answers_of(message, now()))
            return message

    class StandIn(_Mind):
        def __init__(self) -> None:
            super().__init__()
            self.per_call: list[dict[str, Any]] = []
            self.prompt_tokens = self.completion_tokens = 0
            self.acts = 0

        def answer(self, request: dict[str, Any]) -> dict[str, Any]:
            message = self.decide(request)
            answers.extend(answers_of(message, now()))
            return message

        def decide(self, request: dict[str, Any]) -> dict[str, Any]:
            if len(self.per_call) >= args.max_calls:
                outcomes.append(REFUSED)
                raise RuntimeError("the agent's allocation is reached")
            tools = [tool["function"]["name"] for tool in request.get("tools") or []]
            self.tool_names = tools or self.tool_names
            self.per_call.append(
                {
                    "at": now(),
                    "ms": 0,
                    "model": request.get("model"),
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                }
            )
            outcomes.append("ok")

            def named(end: str) -> str | None:
                return next((name for name in self.tool_names if name.endswith(end)), None)

            enter, wait, act = named("enter_world"), named("wait_for_turn"), named("__act")
            messages = request.get("messages") or []
            last = str(messages[-1].get("content")) if messages else ""
            if enter and enter not in self.calls:
                return self._call(enter, {})
            if self.acts >= 3:
                return {"role": "assistant", "content": "I took my turns."}
            turn = _TURN.search(last) if self.calls and self.calls[-1] == wait else None
            if turn:
                self.acts += 1
                offered = [
                    o.strip() for o in _OPTION.findall(last.split("What you can do now:")[-1])
                ]
                quiet = [option for option in offered if not option.lower().startswith("say")]
                if quiet:
                    return self._call(act, {"turn": turn.group(1), "action": quiet[0]})
                said = {"turn": turn.group(1), "action": offered[0], "line": "Hello."}
                return self._call(act, said)
            return self._call(wait, {"wait_seconds": 10})

    relay = StandIn() if args.stand_in else CappedRelay()
    server, relay_url = _serve_mind(relay)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "EXULANICA_URL": args.world,
        "EXULANICA_AGENT_KEY_FILE": str(args.key_file.resolve()),
        "EXULANICA_AGENT_PATH": str(EXAMPLE.parents[1]),
        "NEBIUS_API_KEY": "relayed",
    }
    started = dt.datetime.now(dt.UTC)
    clock = time.monotonic()
    with tempfile.TemporaryDirectory() as folder:
        config = _config(
            args.facade_python,
            relay_url,
            Path(folder),
            mind=args.mind,
            name=args.name,
            maker=args.maker,
        )
        # Its own process group, so the toolkit and the facade it started stop together.
        process = subprocess.Popen(
            [args.nat, "run", "--config_file", str(config), "--input", args.input],
            env=env,
            start_new_session=True,
        )
        try:
            exit_code: int | str = process.wait(timeout=max(args.deadline_s, 1.0))
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            exit_code = "stopped at the deadline"
    server.shutdown()
    priced = _usd(MANIFEST, args.mind, relay.prompt_tokens, relay.completion_tokens)
    record = {
        "profile": "exulanica-agent-run/v1",
        "started_at": started.isoformat(timespec="seconds"),
        "ms": round((time.monotonic() - clock) * 1000),
        "world": args.world.split("://", 1)[-1].split("/", 1)[0],
        "mind": "stand-in" if args.stand_in else args.mind,
        "declared": {"name": args.name, "maker": args.maker},
        "input": args.input,
        "account": "none (stand-in)" if args.stand_in else "Nebius Token Factory",
        "calls": len(relay.per_call),
        "prompt_tokens": relay.prompt_tokens,
        "completion_tokens": relay.completion_tokens,
        "usd": "0" if args.stand_in else priced,
        "price_source": "the manifest's input_usd_per_mtok and output_usd_per_mtok",
        "bound": {"max_calls": args.max_calls, "max_usd": str(args.max_usd)},
        "outcomes": outcomes,
        "answers": answers,
        "nat_exit": exit_code,
        "per_call": relay.per_call,
    }
    descriptor = os.open(args.record, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2)
        handle.write("\n")
    print(json.dumps({key: record[key] for key in ("calls", "usd", "ms", "nat_exit")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
