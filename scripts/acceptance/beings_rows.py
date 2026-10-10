#!/usr/bin/env python3
"""Rows about the beings of a world, against a running acceptance stack.

    .venv/bin/python scripts/acceptance/beings_rows.py play             --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/beings_rows.py creatures        --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/beings_rows.py guest-arrival    --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/beings_rows.py guest-scene      --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/beings_rows.py crossing-manifest --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/beings_rows.py companion-things --worktree PATH --out DIR
    .venv/bin/python scripts/acceptance/beings_rows.py piece-offer      --worktree PATH --out DIR

Each subcommand checks rows against the stack ``launch.py up`` started for ``--worktree`` and
leaves the stack running. It shares ``domain_rows.py``'s clients, scene builder and readers.

- ``play``: PL1 (a person plays one being of a society of things), FW1 (the played being follows
  another) and ER1 (the society is erased whole). The stack is started with ``--workspaces 2
  --peer-token --society-of-things --no-derivative-worker`` on a fresh database; the driver steps
  every minute itself.
- ``creatures``: CR1 (a creature drafted from a line of words, placed by its kind's digest and
  erased). The stack is started with ``--workspaces 2 --peer-token --creatures --scripted-model
  scripts/acceptance/plans/creatures.json --spending process --no-derivative-worker``.
- ``guest-arrival``: SI1 (a signed-out session answer says how a person may sign in) and AR1 (a
  guest's arrival town living without a scene), on the stack the ``guests`` rows use.
- ``guest-scene``: AR2 (a guest's arrival town dressed with the scene its catalog names). The
  guests stack with ``--society-of-things``.
- ``crossing-manifest``: MF1 (what came across with a visitor and what stayed behind), on the
  stack the ``crossings`` rows use.
- ``companion-things``: CP1 (the Companion's plan over things and beings). The stack is started
  with ``--workspaces 2 --society-of-things --scripted-model
  scripts/acceptance/plans/companion-things.json --spending process --no-derivative-worker``.
- ``piece-offer``: PR3 (a piece request with no maker running, and taking back what was never
  taken in) and CP2 (the Companion offers new pieces, with their time and cost, before the yes).
  The stack is started with ``--workspaces 2 --scripted-model
  scripts/acceptance/plans/piece-offer.json --spending durable --no-derivative-worker``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _domain_rows() -> Any:
    name = "exulanica_acceptance_domain_rows"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "domain_rows.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D = _domain_rows()
F, LAUNCH = D.F, D.LAUNCH
Row, Stack, Transcripts = F.Row, F.Stack, F.Transcripts
#: This file's digest as the run began; the run records whether it changed before the end.
DRIVER_SHA256_AT_START = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def write_results(
    out: Path, stack: Stack, rows: Sequence[Any], started: str, command: Sequence[str]
) -> None:
    results = {
        "profile": "q10-foundation-acceptance-results/v1",
        "candidate": stack.state["tree"],
        "launcher_run": stack.state["run_id"],
        "started_at": started,
        "finished_at": dt.datetime.now(dt.UTC).isoformat(),
        "timing_claims": False,
        "rows": [row.document() for row in rows],
        "counts": {state: sum(row.status == state for row in rows) for state in F.STATES},
    }
    (out / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True))
    manifest = {
        "driver_sha256": DRIVER_SHA256_AT_START,
        "driver_changed_during_run": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        != DRIVER_SHA256_AT_START,
        "domain_rows_sha256": D.DRIVER_SHA256_AT_START,
        "foundation_sha256": F.DRIVER_SHA256_AT_START,
        "launcher_sha256": hashlib.sha256((HERE / "launch.py").read_bytes()).hexdigest(),
        "command": ["beings_rows.py", *command],
        "launcher_state": {k: v for k, v in stack.state.items() if k != "database"},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    for row in rows:
        print(f"{row.row:16} {row.status:8} {'; '.join(row.failures or row.blocked_by)}")


def answered(status: int, body: Any) -> list[Any]:
    """An answer as a row records it: its status, its problem code and a string detail."""
    detail = body.get("detail") if isinstance(body, dict) else None
    return [status, F.problem_code(body), detail if isinstance(detail, str) else None]


# -- PL1, FW1, ER1: a person plays a being, follows another, and the society is erased ---------------

#: The engine's seventh action catalog, which a played being's turn is read under, and the policy
#: catalog that bounds how many beings it may be offered to follow.
PLAY_ACTIONS = Path("assets") / "catalogs" / "society" / "society-decision-action.v7.json"
PLAY_POLICY = Path("assets") / "catalogs" / "society" / "society-decision-policy.v7.json"
#: The contract's quiet minutes before the host gives a being back (decision-roles-contract.md).
QUIET_MINUTES = 5
#: What a person's line holds so that the erasure can be searched for it afterwards.
TYPED_LINE = "Good evening from the acceptance run."
#: How a society that is made opens on a host that sets nothing: the opening policy in force.
OPENING_POLICY = Path("exulanica") / "world" / "society-opening-policy.v2.json"


def opened_as_the_policy_says(made: Any, policy: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether a society of things that was just made stands at a minute the opening policy
    yields, and what was read, in words.

    A society that is made opens awake: the server advances it, minute by ordinary minute, until
    the policy's share of its beings is doing something (an action whose kind is not ``idle``). So
    a society of things made again is first read at the first minute that share holds, which is
    minute 1 for one born with every being idle, and never at a bare minute 0 with everyone idle.
    It may stand short of the share only where the opening ran out of budget: at the policy's most
    minutes, or at or past its least minutes, where the seconds stopped it.
    """
    values = policy["values"]
    tick = made.get("current_tick") if isinstance(made, Mapping) else None
    state = made.get("state") if isinstance(made, Mapping) else None
    beings = state.get("inhabitants") if isinstance(state, Mapping) else None
    if (
        isinstance(tick, bool)
        or not isinstance(tick, int)
        or not isinstance(beings, list)
        or not beings
    ):
        return False, f"minute {tick!r} with no beings read"
    kinds = [
        (b.get("action") or {}).get("kind") if isinstance(b, Mapping) else None for b in beings
    ]
    doing = sum(1 for kind in kinds if isinstance(kind, str) and kind != "idle")
    said = f"minute {tick} with {doing} of {len(beings)} beings doing something"
    if not 0 <= tick <= values["minutes_maximum"]:
        return False, said
    awake = 1000 * doing // len(beings) >= values["active_share_milli"]
    out_of_budget = tick == values["minutes_maximum"] or tick >= values["minutes_minimum"]
    return awake or out_of_budget, said


def play_path(entry: Mapping[str, Any], suffix: str = "") -> str:
    return F.version_path(entry, f"/society/play{suffix}")


def play_call(
    c: Any, label: str, entry: Mapping[str, Any], method: str, suffix: str, body: Any = None
):
    return c.call(label, method, play_path(entry, suffix), query=F.world_query(entry), body=body)


def turn_of(c: Any, label: str, entry: Mapping[str, Any], subject: str) -> dict[str, Any]:
    status, read = play_call(c, label, entry, "GET", f"/{subject}/turn")
    return read if status == 200 and isinstance(read, dict) else {"status": status, "body": read}


def step_once(c: Any, label: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """One minute, stepped by the owner; the society as it reads afterwards."""
    _, now = F.society(c, label, entry)
    F.advance(c, label, entry, now or {})
    return F.society(c, label, entry)[1] or {}


def events_of(c: Any, label: str, entry: Mapping[str, Any], kind: str, subject: str) -> list[Any]:
    return [
        e
        for e in D.society_events(c, label, entry)
        if e.get("event_kind") == kind and e.get("subject_id") == subject
    ]


def scene_society(stack: Stack, c: Any, worktree: Path, out: Path, name: str, token: str):
    """``token``'s own build of the newest locked scene with its society of things made: the
    entry, the society as first read, and the ids its placed things were given."""
    record_path = out / "evidence" / f"{name}-scene-build.json"
    built = D.build_scene(stack, worktree, record_path, token_file=token)
    (out / "evidence" / f"{name}-scene-build.txt").write_text(built.stdout + built.stderr)
    if not record_path.exists():
        return None, {"build_exit": built.returncode}, {}
    record = json.loads(record_path.read_text())
    entry = F.read_entry(c, name, record["entry_id"])
    status, society = c.call(
        name,
        "POST",
        F.version_path(entry, "/society"),
        query=F.world_query(entry),
        body={"region_id": record["arrival"]["region_id"], "profile": D.THINGS_ENGINE},
    )
    state = (society or {}).get("state") or {}
    placed = {p.get("placed_id"): p.get("id") for p in state.get("inhabitants") or []}
    placed |= {t.get("placed_id"): t.get("id") for t in state.get("things") or []}
    return entry, {"status": status, **(society if isinstance(society, dict) else {})}, placed


def row_pl1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> tuple[Row, dict]:
    row = Row(
        "PL1",
        "things.person_plays",
        "A person plays one being (candidate-38; decision-roles-contract.md, a person playing a "
        "being): on workspace 1's own build of the newest locked scene, a society of things the "
        "driver steps. Taking the knight is 201, decider person, played_by_you, the answer naming "
        "no actor; the same take again answers the same play. The peer's take is 409 "
        "being_played and the peer's answer 409 not_played. The turn offers labelled options, a "
        "line bound and the contract's five quiet minutes. Meanwhile a choice naming the knight "
        "is 409 being_played, the models read shows a person decides with no chosen_by, and the "
        "card's decider may not change, refusal being_played. A label not offered is 422 "
        "label_not_offered; a line where the option takes none 422 line_not_taken; an offered "
        "line option with a line 202, and after the minute the said event's decider and the "
        "decision's origin read person; an answer on the old minute is 409 minute_passed with "
        "current_tick. A minute with no answer is decided person_no_answer by the person's "
        "record, no model. A town society's take is 409 engine_takes_no_play.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    peer = F.client(stack, transcripts, "peer", "token-peer")
    entry, society, placed = scene_society(stack, c, worktree, out, "PL1", "token")
    knight, spirit = placed.get("knight"), placed.get("lantern-spirit")
    row.expect(
        entry is not None and society.get("status") in (200, 201) and bool(knight and spirit),
        f"the scene's society answered {society.get('status') or society}",
    )
    facts: dict[str, Any] = {"entry_id": (entry or {}).get("entry_id"), "placed": placed}
    if not (entry and knight and spirit):
        row.observed = facts
        return row.close(), facts
    actors = [
        str(actor)
        for actor in (stack.state.get("actor"), (stack.state.get("peer_token") or {}).get("actor"))
        if actor
    ]

    body = {"idempotency_key": str(uuid.uuid4()), "subject_id": knight}
    took_status, took = play_call(c, "PL1 take", entry, "POST", "", body)
    took = took if isinstance(took, dict) else {}
    row.expect(
        took_status == 201
        and took.get("decider") == {"kind": "person"}
        and took.get("played_by_you") is True,
        f"the take answered {took_status} {took.get('decider')} {took.get('played_by_you')}",
    )
    row.expect(
        not any(actor in json.dumps(took) for actor in actors) and "account_id" not in took,
        "the take's answer names an actor",
    )
    again_status, again = play_call(
        c, "PL1 take again", entry, "POST", "", {**body, "idempotency_key": str(uuid.uuid4())}
    )
    row.expect(
        again_status in (200, 201)
        and (again or {}).get("since_tick") == took.get("since_tick")
        and (again or {}).get("played_by_you") is True,
        f"the same person's second take answered {again_status} {F.problem_code(again)}",
    )
    peer_take = play_call(
        peer, "PL1 peer take", entry, "POST", "", {**body, "idempotency_key": str(uuid.uuid4())}
    )
    row.expect(
        answered(*peer_take)[:2] == [409, "being_played"],
        f"the peer's take answered {answered(*peer_take)}",
    )

    turn = turn_of(c, "PL1 turn", entry, knight)
    options = turn.get("options") or []
    actions = json.loads((worktree / PLAY_ACTIONS).read_text())
    row.expect(
        bool(options)
        and all(isinstance(o.get("label"), str) and o.get("kind") for o in options)
        and turn.get("played") is True
        and turn.get("played_by_you") is True
        and turn.get("quiet_minutes") == QUIET_MINUTES
        and isinstance(turn.get("line_characters_maximum"), int)
        and turn.get("base_tick") == society.get("current_tick"),
        f"the turn read played {turn.get('played')} {turn.get('played_by_you')}, quiet minutes "
        f"{turn.get('quiet_minutes')}, minute {turn.get('base_tick')}, {len(options)} options",
    )
    peer_turn = turn_of(peer, "PL1 peer turn", entry, knight)
    row.expect(
        peer_turn.get("played") is True and peer_turn.get("played_by_you") is False,
        f"the peer's turn read played {peer_turn.get('played')} {peer_turn.get('played_by_you')}",
    )
    say = next((o for o in options if o.get("takes_line")), None)
    plain = next((o for o in options if not o.get("takes_line") and not o.get("takes_point")), None)
    peer_answer = play_call(
        peer,
        "PL1 peer answer",
        entry,
        "POST",
        f"/{knight}/answer",
        {"base_tick": turn.get("base_tick"), "label": (plain or {}).get("label", "wait")},
    )
    row.expect(
        answered(*peer_answer)[:2] == [409, "not_played"],
        f"the peer's answer answered {answered(*peer_answer)}",
    )

    # Meanwhile nobody chooses a model for it, and every read says a person decides.
    chosen = c.call(
        "PL1 choose",
        "POST",
        F.version_path(entry, "/society/models"),
        query=F.world_query(entry),
        body={"idempotency_key": str(uuid.uuid4()), "people": [knight], "model": None},
    )
    row.expect(
        answered(*chosen)[:2] == [409, "being_played"],
        f"a choice naming the played knight answered {answered(*chosen)}",
    )
    _, models = c.call(
        "PL1 models", "GET", F.version_path(entry, "/society/models"), query=F.world_query(entry)
    )
    held = next(
        (x for x in (models or {}).get("choices") or [] if x.get("subject_id") == knight), {}
    )
    row.expect(
        held.get("decider") == {"kind": "person"}
        and held.get("played_by_you") is True
        and held.get("chosen_by") is None,
        f"the models read shows {held.get('decider')} chosen_by {held.get('chosen_by')}",
    )
    _, card = c.call(
        "PL1 card",
        "GET",
        F.version_path(entry, f"/society/things/{knight}"),
        query=F.world_query(entry),
    )
    decider = (card or {}).get("decider") or {}
    row.expect(
        decider.get("kind") == "person"
        and decider.get("played_by_you") is True
        and decider.get("may_change") is False
        and decider.get("refusal") == "being_played",
        f"the card's decider reads {decider}",
    )
    row.expect(
        not any(actor in json.dumps([held, decider]) for actor in actors),
        "a read of who decides names an actor",
    )

    refusals = {}
    for label, sent, wanted in (
        ("label not offered", {"label": "dance on the well"}, "label_not_offered"),
        (
            "a line where none is taken",
            {"label": (plain or {}).get("label"), "line": "Hello."},
            "line_not_taken",
        ),
    ):
        got = play_call(
            c,
            f"PL1 {label}",
            entry,
            "POST",
            f"/{knight}/answer",
            {"base_tick": turn.get("base_tick"), **sent},
        )
        refusals[label] = answered(*got)
        row.expect(
            answered(*got)[:2] == [422, wanted], f"{label}: answered {answered(*got)}, not {wanted}"
        )
    row.expect(say is not None and plain is not None, "the turn offers no line or no plain option")
    said_status, said_answer = play_call(
        c,
        "PL1 say",
        entry,
        "POST",
        f"/{knight}/answer",
        {"base_tick": turn.get("base_tick"), "label": (say or {}).get("label"), "line": TYPED_LINE},
    )
    row.expect(
        said_status == 202 and (said_answer or {}).get("base_tick") == turn.get("base_tick"),
        f"the line's answer was {said_status} {F.problem_code(said_answer)}",
    )
    after = step_once(c, "PL1 step", entry)
    said = events_of(c, "PL1 events", entry, "said", knight)
    applied = [
        e
        for e in events_of(c, "PL1 events", entry, "decision_applied", knight)
        if e.get("tick") == after.get("current_tick")
    ]
    row.expect(
        bool(said)
        and ((said[-1].get("document") or {}).get("thing") or {}).get("decider") == "person"
        and TYPED_LINE in json.dumps(said[-1]),
        f"the said event reads {said[-1:] or 'none'}",
    )
    row.expect(
        bool(applied) and (applied[-1].get("document") or {}).get("origin") == "person",
        f"the minute's decision_applied reads {[e.get('document') for e in applied]}",
    )
    late = play_call(
        c,
        "PL1 late",
        entry,
        "POST",
        f"/{knight}/answer",
        {"base_tick": turn.get("base_tick"), "label": (plain or {}).get("label")},
    )
    row.expect(
        answered(*late)[:2] == [409, "minute_passed"]
        and (late[1] or {}).get("current_tick") == after.get("current_tick"),
        f"an answer on the old minute answered {answered(*late)} "
        f"{(late[1] or {}).get('current_tick') if isinstance(late[1], dict) else None}",
    )

    # A minute the player does not answer: the person's record decides it, idle, and no model.
    quiet = step_once(c, "PL1 quiet step", entry)
    unanswered = [
        e
        for e in events_of(c, "PL1 events", entry, "decision_applied", knight)
        if e.get("tick") == quiet.get("current_tick")
    ]
    request_id = ((unanswered[-1].get("document") if unanswered else None) or {}).get("request_id")
    _, decision = (
        c.call(
            "PL1 decision",
            "GET",
            F.version_path(entry, f"/society/decisions/{request_id}"),
            query=F.world_query(entry),
        )
        if request_id
        else (None, None)
    )
    receipt = (decision or {}).get("receipt") or decision or {}
    row.expect(
        bool(unanswered)
        and (unanswered[-1].get("document") or {}).get("origin") == "person"
        and "person_no_answer" in json.dumps(decision),
        f"the unanswered minute reads {[e.get('document') for e in unanswered]} "
        f"reason {receipt.get('reason')}",
    )

    town = D.generated_town(c, "PL1 town", "Q10 PL1 town")
    _, town_society = F.society(c, "PL1 town", town)
    person = next(
        (p.get("id") for p in ((town_society or {}).get("state") or {}).get("inhabitants") or []),
        None,
    )
    town_take = play_call(
        c,
        "PL1 town take",
        town,
        "POST",
        "",
        {"idempotency_key": str(uuid.uuid4()), "subject_id": person},
    )
    row.expect(
        answered(*town_take)[:2] == [409, "engine_takes_no_play"],
        f"a town's take answered {answered(*town_take)}",
    )
    facts |= {"knight": knight, "spirit": spirit, "town_entry_id": town.get("entry_id")}
    row.observed = {
        "take": [took_status, took.get("decider"), took.get("played_by_you"), again_status],
        "peer": [answered(*peer_take), answered(*peer_answer)],
        "turn": {
            "options": [[o.get("kind"), o.get("label")] for o in options],
            "line_characters_maximum": turn.get("line_characters_maximum"),
            "quiet_minutes": turn.get("quiet_minutes"),
            "catalog": actions.get("profile") or actions.get("version"),
        },
        "meanwhile": {"choice": answered(*chosen), "models": held, "card_decider": decider},
        "refusals": refusals,
        "said": [said_status, (say or {}).get("label")],
        "late": answered(*late),
        "unanswered": {"origin": "person" if unanswered else None, "reason": receipt.get("reason")},
        "town": answered(*town_take),
    }
    return row.close(), facts


def row_fw1(stack: Stack, transcripts: Any, worktree: Path, pl1: Mapping[str, Any]) -> Row:
    policy = json.loads((worktree / PLAY_POLICY).read_text())
    follow_most = next(
        (
            entry.get("value")
            for entry in _entries(policy)
            if entry.get("key") == "follow_options_maximum" and isinstance(entry.get("value"), int)
        ),
        None,
    )
    row = Row(
        "FW1",
        "things.follow",
        "A played being follows another (candidate-38; synthetic-society-contract.md, the follow "
        "module; decision-roles-contract.md): in PL1's society, the played knight's turn offers "
        f"follow options, at most the policy catalog's {follow_most}, each naming another being "
        "whose kind offers to be followed; answering one is 202 and after the minute a followed "
        "event says chose_to_follow with that being, the state says whom the knight follows, and "
        "the turn offers stop_following naming it. The turn read of a being nobody plays is "
        "recorded and not judged: it is made under the person's contract (A-149). Giving the "
        "knight back is 200 ended given_back, "
        "an answer after it 409 not_played, and the next minute a stopped_following event says "
        "not_kept.",
    )
    entry_id, knight, spirit = pl1.get("entry_id"), pl1.get("knight"), pl1.get("spirit")
    if not (entry_id and knight and spirit):
        row.blocked_by.append("PL1 left no society with the knight")
        return row.close()
    row.expect(follow_most is not None, "the policy catalog states no follow_options_maximum")
    c = F.client(stack, transcripts, "w1", "token")
    entry = F.read_entry(c, "FW1", entry_id)
    _, now = F.society(c, "FW1", entry)
    beings = {p.get("id"): p for p in ((now or {}).get("state") or {}).get("inhabitants") or []}
    turn = turn_of(c, "FW1 turn", entry, knight)
    follows = [o for o in turn.get("options") or [] if o.get("kind") == "follow"]
    row.expect(
        0 < len(follows) <= (follow_most or 0)
        and all(o.get("being_id") in beings and o.get("being_id") != knight for o in follows)
        and all(not o.get("takes_line") for o in follows),
        f"the turn offers follow options {[[o.get('label'), o.get('being_id')] for o in follows]}",
    )
    # A-149: the turn read is the person's own, under the person's contract, so a being nobody
    # plays reads what a person who took it would be offered. Recorded, not judged.
    unplayed_turn = turn_of(c, "FW1 spirit turn", entry, spirit)
    offered_to_spirit = sorted({str(o.get("kind")) for o in unplayed_turn.get("options") or []})
    if not follows:
        row.observed = {
            "options": [[o.get("kind"), o.get("label")] for o in turn.get("options") or []]
        }
        return row.close()
    chosen = follows[0]
    other = chosen["being_id"]
    status, _ = play_call(
        c,
        "FW1 follow",
        entry,
        "POST",
        f"/{knight}/answer",
        {"base_tick": turn.get("base_tick"), "label": chosen["label"]},
    )
    row.expect(status == 202, f"the follow answer was {status}")
    after = step_once(c, "FW1 step", entry)
    began = events_of(c, "FW1 events", entry, "followed", knight)
    document = (began[-1].get("document") if began else None) or {}
    row.expect(
        bool(began)
        and document.get("reason") == "chose_to_follow"
        and (document.get("thing") or {}).get("with") == other,
        f"the followed event reads {document or 'none'}",
    )
    me = next(
        (p for p in (after.get("state") or {}).get("inhabitants") or [] if p.get("id") == knight),
        {},
    )
    row.expect(
        (me.get("following") or {}).get("being") == other,
        f"the knight's state follows {me.get('following')}",
    )
    then = turn_of(c, "FW1 turn after", entry, knight)
    stops = [o for o in then.get("options") or [] if o.get("kind") == "stop_following"]
    row.expect(
        len(stops) == 1 and stops[0].get("being_id") == other,
        f"the turn while following offers {[[o.get('kind'), o.get('label')] for o in stops]}",
    )
    back_status, back = play_call(
        c,
        "FW1 give back",
        entry,
        "POST",
        f"/{knight}/give-back",
        {"idempotency_key": str(uuid.uuid4())},
    )
    row.expect(
        back_status == 200 and (back or {}).get("ended") == "given_back",
        f"giving back answered {back_status} {(back or {}).get('ended')}",
    )
    gone = play_call(
        c,
        "FW1 answer after",
        entry,
        "POST",
        f"/{knight}/answer",
        {"base_tick": then.get("base_tick"), "label": (stops[0] if stops else chosen)["label"]},
    )
    row.expect(
        answered(*gone)[:2] == [409, "not_played"],
        f"an answer after giving back answered {answered(*gone)}",
    )
    step_once(c, "FW1 step after", entry)
    stopped = events_of(c, "FW1 events", entry, "stopped_following", knight)
    reason = ((stopped[-1].get("document") if stopped else None) or {}).get("reason")
    row.expect(reason == "not_kept", f"the stopped_following event reads {reason}")
    row.observed = {
        "follow_options": [[o.get("label"), o.get("being_id")] for o in follows],
        "follow_options_maximum": follow_most,
        "followed": document,
        "following": me.get("following"),
        "stop_option": [[o.get("label"), o.get("being_id")] for o in stops],
        "give_back": [back_status, (back or {}).get("ended")],
        "after": answered(*gone),
        "stopped": reason,
        "other_kind": (beings.get(other) or {}).get("kind"),
        "unplayed_turn_kinds_not_judged": [unplayed_turn.get("played"), offered_to_spirit],
    }
    return row.close()


def _entries(document: Any):
    """Every object of a JSON document, at any depth."""
    if isinstance(document, dict):
        yield document
        for value in document.values():
            yield from _entries(value)
    elif isinstance(document, list):
        for value in document:
            yield from _entries(value)


def row_er1(stack: Stack, transcripts: Any, pl1: Mapping[str, Any]) -> Row:
    row = Row(
        "ER1",
        "things.society_erased",
        "A society is erased whole (candidate-38; synthetic-society-contract.md, erasing a "
        "society): PL1's society holds a line a person typed. DELETE on it is 204. Then the "
        "society, its events, its replay and the played being's turn answer 404, and a second "
        "DELETE is 404 society_unavailable. A society made again on the same version opens "
        "awake, as every society that is made does: it is first read at the minute the opening "
        "policy in force yields, the first at which its share of beings is doing something, and "
        "not at a bare minute 0 with every being idle. None of its events holds the typed line. "
        "The town's society PL1 "
        "made in the same workspace still reads 200 with its people. Evidence read as the "
        "database owner: one tombstone of scope society for the workspace.",
    )
    entry_id, knight = pl1.get("entry_id"), pl1.get("knight")
    if not (entry_id and knight):
        row.blocked_by.append("PL1 left no society")
        return row.close()
    c = F.client(stack, transcripts, "w1", "token")
    entry = F.read_entry(c, "ER1", entry_id)
    query = F.world_query(entry)
    before = D.society_events(c, "ER1 before", entry)
    row.expect(
        TYPED_LINE in json.dumps(before),
        "the society's events hold no typed line before the erasure",
    )
    _, held = F.society(c, "ER1 before", entry)
    region = ((held or {}).get("state") or {}).get("region_id") or (held or {}).get("region_id")
    path = F.version_path(entry, "/society")
    status, body = c.call("ER1 erase", "DELETE", path, query=query)
    row.expect(status == 204, f"the erasure answered {status} {F.problem_code(body)}")
    reads = {}
    for label, suffix in (
        ("society", ""),
        ("events", "/events"),
        ("replay", "/replay"),
        ("turn", f"/play/{knight}/turn"),
    ):
        got = c.call(f"ER1 {label}", "GET", path + suffix, query=query)
        reads[label] = answered(*got)[:2]
        row.expect(got[0] == 404, f"the {label} read answered {got[0]} after the erasure")
    again = c.call("ER1 erase again", "DELETE", path, query=query)
    row.expect(
        answered(*again)[:2] == [404, "society_unavailable"],
        f"a second erasure answered {answered(*again)}",
    )
    record = json.loads(
        (transcripts.directory.parent / "evidence" / "PL1-scene-build.json").read_text()
    )
    made_status, made = c.call(
        "ER1 again",
        "POST",
        path,
        query=query,
        body={"region_id": record["arrival"]["region_id"], "profile": D.THINGS_ENGINE},
    )
    opened, opening_read = opened_as_the_policy_says(
        made, json.loads((stack.worktree / OPENING_POLICY).read_text(encoding="utf-8"))
    )
    row.expect(
        made_status in (200, 201) and opened,
        f"a society made again answered {made_status} at {opening_read}, which is not a minute "
        "the opening policy yields",
    )
    step_once(c, "ER1 new step", entry)
    fresh = D.society_events(c, "ER1 after", entry)
    row.expect(TYPED_LINE not in json.dumps(fresh), "the new society's events hold the typed line")
    town = F.read_entry(c, "ER1 town", pl1["town_entry_id"]) if pl1.get("town_entry_id") else None
    town_status, town_society = F.society(c, "ER1 town", town) if town else (None, None)
    row.expect(
        town_status == 200 and bool(((town_society or {}).get("state") or {}).get("inhabitants")),
        f"the town's society reads {town_status}",
    )
    workspace = D.workspace_ids(stack)[0]
    tombstones = D.owner_sql(
        stack,
        "select scope, count(*) from tombstone where workspace_id = %s group by scope",
        workspace,
        workspace=workspace,
    )
    row.observed = {
        "erase": [status, answered(*again)],
        "reads_after": reads,
        "remade": [made_status, (made or {}).get("current_tick"), opening_read],
        "events_before": len(before),
        "events_after": len(fresh),
        "town": town_status,
        "region": region,
        "evidence_read_as_owner": {"tombstones_by_scope": [list(t) for t in tombstones]},
    }
    row.expect(
        any(scope == "society" and count == 1 for scope, count in tombstones),
        f"the owner's read of tombstones shows {tombstones}",
    )
    return row.close()


def play(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if (
        not stack.state.get("society_of_things")
        or not stack.token_file("token-peer").exists()
        or stack.state.get("scripted_model")
    ):
        raise SystemExit(
            "play needs a fresh database and a stack started with --workspaces 2 --peer-token "
            "--society-of-things --no-derivative-worker, and no model"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    pl1, facts = row_pl1(stack, transcripts, worktree, out)
    rows = [pl1, row_fw1(stack, transcripts, worktree, facts), row_er1(stack, transcripts, facts)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- CR1: a creature made from a line of words ------------------------------------------------------

CREATURE_PLAN = HERE / "plans" / "creatures.json"
MODEL_MANIFEST = Path("exulanica") / "models" / "models.manifest.json"
CREATURES = "/things/creatures"
#: How long a draft may take to end on a scripted drafter before the row says it did not.
CREATURE_SECONDS = 180
CREATURE_ENDED = ("kept", "erased", "refused", "failed", "cancelled")
#: The contract's fixed sentence for a movement the grammar does not build (things-contract.md).
NO_FLYING = "This world has no flying creatures yet."


def creature_draft(c: Any, label: str, words: str) -> tuple[int, dict[str, Any]]:
    """Ask for a creature and read its draft until it ends; the last read."""
    status, draft = c.call(label, "POST", CREATURES, body={"words": words})
    draft = draft if isinstance(draft, dict) else {}
    deadline = time.monotonic() + CREATURE_SECONDS
    while status == 202 and draft.get("status") not in CREATURE_ENDED:
        if time.monotonic() > deadline:
            break
        time.sleep(1)
        _, read = c.call(label, "GET", f"{CREATURES}/drafts/{draft.get('draft_id')}")
        draft = read if isinstance(read, dict) else draft
    return status, draft


def row_cr1(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    plan = json.loads(CREATURE_PLAN.read_text())
    lines = plan["utterances"]
    binding = json.loads((worktree / MODEL_MANIFEST).read_text())
    drafter = next(
        (e.get("creature_drafter") for e in _entries(binding) if "creature_drafter" in e), {}
    )
    basis = drafter.get("timeout_basis") or {}
    timing = {
        "record": basis.get("record"),
        "call_p50_seconds": -(-int(basis.get("p50_ms", 0)) // 1000),
        "call_longest_seconds": -(-int(basis.get("longest_ms", 0)) // 1000),
        "call_timeout_seconds": drafter.get("timeout_seconds"),
    }
    row = Row(
        "CR1",
        "things.creature_from_words",
        "A creature made from a line of words (candidate-38; things-contract.md, drafting a "
        "creature, and a workspace's own things; world-objects-contract.md, placed things): on a "
        "stack whose scripted drafter answers three lines, GET /things/creatures/offered says "
        "offered with the model manifest's timing; the walking line is 202 and ends kept, naming "
        "a kind, a look and a label; the draft holds neither the words nor their digest, and the "
        "kind's origin holds the SHA-256 of the words; the flying line ends refused "
        f"creature_movement_unbuilt on moves_flight, saying '{NO_FLYING}'; two physical lines are "
        "422 words_refused. The kind is placed by its digest alone, 201, in the starter world; "
        "an invented digest and the other workspace's placing of it are 422 "
        "invalid_thing_placement, the other workspace's read of the kind 404. The peer reads the "
        "draft 404 and its erasure is 403 kind_not_yours. The drafter's erasure is 204: kind and "
        "look read 404, the draft reads erased naming nothing, the thing reads gone, its move is "
        "410 thing_kind_erased and its removal stands. The same line drafted again is kept and "
        "the thing stays gone.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    peer = F.client(stack, transcripts, "peer", "token-peer")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    _, offer = c.call("CR1 offered", "GET", f"{CREATURES}/offered")
    offer = offer if isinstance(offer, dict) else {}
    row.expect(
        offer.get("offered") is True
        and offer.get("code") is None
        and offer.get("timing") == timing,
        f"the offer reads offered {offer.get('offered')} {offer.get('code')} {offer.get('timing')}, "
        f"the manifest {timing}",
    )
    two = c.call("CR1 two lines", "POST", CREATURES, body={"words": "a dragon\nthat walks"})
    row.expect(answered(*two)[:2] == [422, "words_refused"], f"two lines answered {answered(*two)}")

    words = lines["walking"]
    asked, kept = creature_draft(c, "CR1 walking", words)
    kind, look = kept.get("kind") or {}, kept.get("look") or {}
    row.expect(
        asked == 202
        and kept.get("status") == "kept"
        and bool(kind.get("sha256") and look.get("sha256") and kept.get("label")),
        f"the walking line answered {asked} and ended {kept.get('status')} "
        f"{kept.get('refusal') or kept.get('failure')}",
    )
    digest = hashlib.sha256(words.encode()).hexdigest()
    row.expect(
        words not in json.dumps(kept) and digest not in json.dumps(kept),
        "the draft holds the words or their digest",
    )
    if kept.get("status") != "kept":
        row.observed = {"offer": offer, "draft": kept}
        return row.close()
    kind_path, look_path = f"/things/kinds/{kind['sha256']}", f"/things/looks/{look['sha256']}"
    kind_status, kind_read = c.call("CR1 kind", "GET", kind_path)
    row.expect(
        kind_status == 200 and digest in json.dumps(kind_read),
        f"the kind read {kind_status} and its origin does not hold the words' digest",
    )
    look_status, _ = c.call("CR1 look", "GET", look_path)
    row.expect(look_status == 200, f"the look read {look_status}")

    flew_asked, flew = creature_draft(c, "CR1 flying", lines["flying"])
    refusal = flew.get("refusal") or {}
    row.expect(
        flew_asked == 202
        and flew.get("status") == "refused"
        and [refusal.get("code"), refusal.get("field"), refusal.get("detail")]
        == ["creature_movement_unbuilt", "moves_flight", NO_FLYING],
        f"the flying line ended {flew.get('status')} {refusal or flew.get('failure')}",
    )
    peer_read = peer.call("CR1 peer draft", "GET", f"{CREATURES}/drafts/{kept.get('draft_id')}")
    row.expect(peer_read[0] == 404, f"the peer's read of the draft answered {peer_read[0]}")
    stranger = w2.call("CR1 stranger kind", "GET", kind_path)
    row.expect(stranger[0] == 404, f"the other workspace's read of the kind answered {stranger[0]}")

    status_starter, entry = D.starter(c, "CR1 starter", "Q10 CR1 starter")
    _, other_entry = D.starter(w2, "CR1 starter", "Q10 CR1 other starter")
    row.expect(status_starter in (200, 201), f"the starter answered {status_starter}")
    query, things = F.world_query(entry), F.version_path(entry, "/things")
    thing_id = f"creature:{str(kept.get('draft_id'))[:8]}"
    pose = D.thing_pose("bench")

    def place(c_: Any, label: str, where: Mapping[str, Any], sha256: str, name: str):
        return c_.call(
            label,
            "POST",
            F.version_path(where, "/things"),
            query=F.world_query(where),
            body={
                "base_state_sha256": where["authored_state_sha256"],
                "thing_id": name,
                "kind": {"source": "workspace", "sha256": sha256},
                "region_id": F.STARTER_REGION,
                "pose": pose,
                "origin_role": "fictional",
            },
        )

    invented = place(c, "CR1 invented", entry, hashlib.sha256(b"no such kind").hexdigest(), "c-x")
    foreign = place(w2, "CR1 foreign", other_entry, kind["sha256"], "c-y")
    for label, got in (("an invented digest", invented), ("the other workspace", foreign)):
        row.expect(
            answered(*got)[:2] == [422, "invalid_thing_placement"],
            f"{label}: placing answered {answered(*got)}",
        )
    placed_status, version = place(c, "CR1 place", entry, kind["sha256"], thing_id)
    stood = D.placed(version if isinstance(version, dict) else {}, thing_id) or {}
    row.expect(
        placed_status == 201 and bool(stood) and not stood.get("gone"),
        f"placing the creature answered {placed_status} {F.problem_code(version)}",
    )

    peer_erase = peer.call("CR1 peer erase", "DELETE", kind_path)
    row.expect(
        answered(*peer_erase)[:2] == [403, "kind_not_yours"],
        f"the peer's erasure answered {answered(*peer_erase)}",
    )
    erased = c.call("CR1 erase", "DELETE", kind_path)
    row.expect(erased[0] == 204, f"the erasure answered {answered(*erased)}")
    after = {
        "kind": c.call("CR1 kind after", "GET", kind_path)[0],
        "look": c.call("CR1 look after", "GET", look_path)[0],
    }
    row.expect(after == {"kind": 404, "look": 404}, f"after the erasure the reads answer {after}")
    _, draft_after = c.call("CR1 draft after", "GET", f"{CREATURES}/drafts/{kept.get('draft_id')}")
    draft_after = draft_after if isinstance(draft_after, dict) else {}
    row.expect(
        draft_after.get("status") == "erased"
        and all(draft_after.get(k) is None for k in ("kind", "look", "label")),
        f"the draft reads {draft_after.get('status')} "
        f"{[draft_after.get(k) for k in ('kind', 'look', 'label')]}",
    )
    _, read = c.call("CR1 version", "GET", F.version_path(entry), query=query)
    gone = D.placed(read if isinstance(read, dict) else {}, thing_id) or {}
    row.expect(gone.get("gone") is True, f"the placed thing reads {gone or 'nothing'}")
    state = (read or {}).get("state_sha256")
    moved = c.call(
        "CR1 move",
        "POST",
        f"{things}/{thing_id}/move",
        query=query,
        body={"base_state_sha256": state, "pose": D.thing_pose("stall")},
    )
    row.expect(
        answered(*moved)[:2] == [410, "thing_kind_erased"],
        f"moving the gone thing answered {answered(*moved)}",
    )
    again_asked, again = creature_draft(c, "CR1 walking again", words)
    _, reread = c.call("CR1 version again", "GET", F.version_path(entry), query=query)
    still = D.placed(reread if isinstance(reread, dict) else {}, thing_id) or {}
    row.expect(
        again_asked == 202 and again.get("status") == "kept" and still.get("gone") is True,
        f"the same line again ended {again.get('status')} {again.get('refusal')}; the thing "
        f"reads gone {still.get('gone')}",
    )
    removed = c.call(
        "CR1 remove",
        "POST",
        f"{things}/{thing_id}/remove",
        query=query,
        body={"base_state_sha256": (reread or {}).get("state_sha256")},
    )
    row.expect(
        removed[0] == 200
        and (D.placed(removed[1] if isinstance(removed[1], dict) else {}, thing_id) or {}).get(
            "removed"
        )
        is True,
        f"removing the gone thing answered {answered(*removed)}",
    )
    row.observed = {
        "offer": {k: offer.get(k) for k in ("offered", "code", "timing")},
        "kept": {
            "status": kept.get("status"),
            "label": kept.get("label"),
            "kind": kind,
            "look": {k: look.get(k) for k in ("look", "sha256")},
            "model": kept.get("model"),
        },
        "words_sha256_in_kind": digest in json.dumps(kind_read),
        "flying": [flew.get("status"), refusal],
        "two_lines": answered(*two),
        "placed": [placed_status, thing_id, read.get("schema_version") if read else None],
        "refused_placings": [answered(*invented), answered(*foreign)],
        "peer": [peer_read[0], answered(*peer_erase)],
        "stranger_kind": stranger[0],
        "erase": erased[0],
        "after": after | {"draft": draft_after.get("status"), "gone": gone.get("gone")},
        "move": answered(*moved),
        "again": [
            again.get("status"),
            (again.get("kind") or {}).get("sha256") == kind.get("sha256"),
            still.get("gone"),
        ],
        "remove": removed[0],
        "scripted_calls": len(D.scripted_log(stack)),
    }
    return row.close()


def creatures(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if (
        served != hashlib.sha256(CREATURE_PLAN.read_bytes()).hexdigest()
        or not stack.state.get("creatures")
        or not stack.token_file("token-peer").exists()
    ):
        raise SystemExit(
            "creatures needs a fresh database and a stack started with --workspaces 2 "
            "--peer-token --creatures --scripted-model scripts/acceptance/plans/creatures.json "
            "--spending process --no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    rows = [row_cr1(stack, transcripts, worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- SI1, AR1, AR2: how a guest may come in, and the town a guest arrives in ------------------------

ARRIVAL_WORLDS = Path("exulanica") / "world" / "arrival-worlds.v1.json"
#: The living engine an arrival copy is given where its entry names none (deployment.md, arrival
#: worlds), and the one step a host that does not offer the scene's engine names.
ARRIVAL_LIVING_ENGINE = "exulanica-society/v5"
SCENE_NOT_OFFERED = {"step": "scene", "code": "society_engine_not_offered"}


def arrival_world(worktree: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The first arrival world the catalog names and the scene file it names, if it names one."""
    world = json.loads((worktree / ARRIVAL_WORLDS).read_text())["worlds"][0]
    named = world.get("scene")
    if not named:
        return world, None
    scene = worktree / D.SCENE_CATALOG / f"{named['scene']}.v{named['version']}.json"
    return world, json.loads(scene.read_text())


def arrival_reading(guest: Any, label: str, entered: Mapping[str, Any]) -> dict[str, Any]:
    """What a guest's arrival world holds, as the guest reads it: its society, its placed things,
    who came how, the minds recorded and whether it plays."""
    arrival = entered.get("arrival") or {}
    if not arrival.get("entry_id"):
        return {}
    entry = F.read_entry(guest, label, arrival["entry_id"])
    query = F.world_query(entry)
    status, society = F.society(guest, label, entry)
    society = society if isinstance(society, dict) else {}
    state = society.get("state") or {}
    _, version = guest.call(label, "GET", F.version_path(entry), query=query)
    _, models = guest.call(label, "GET", F.version_path(entry, "/society/models"), query=query)
    _, control = guest.call(label, "GET", F.version_path(entry, "/society/control"), query=query)
    people = state.get("inhabitants") or []
    return {
        "entry": entry,
        "status": status,
        "profile": society.get("profile"),
        "people": people,
        "came_by": sorted({str(p.get("came_by")) for p in people}),
        "placed_beings": {p.get("placed_id"): p.get("id") for p in people if p.get("placed_id")},
        "things": sorted(
            t.get("thing_id")
            for t in (version or {}).get("things") or []
            if isinstance(t, dict) and not t.get("removed")
        ),
        "choices": (models or {}).get("choices") or [] if isinstance(models, dict) else [],
        "mode": (control or {}).get("mode") if isinstance(control, dict) else None,
    }


def row_si1(stack: Stack, transcripts: Any) -> Row:
    row = Row(
        "SI1",
        "accounts.sign_in_stated",
        "A signed-out session answer says how a person may sign in (candidate-38; deployment.md, "
        "the session read): through the local HTTPS edge, GET /auth/session with no cookie is "
        "401 authentication_failed carrying sign_in, which on this stack (entry by a code, no "
        'Google sign-in) is {"google": false, "guest": "code"}; the answer holds neither the '
        "run's code nor its SHA-256. A wrong code is 403 guest_entry_code_wrong and sets no "
        "cookie; a body with a field the route does not take is 422 and sets none.",
    )
    code = Path(stack.state["accounts"]["code_file"]).read_text().strip()
    stranger = D.GuestClient(stack, transcripts, "signed-out")
    status, read = stranger.call("SI1 session", "GET", "/auth/session")
    text = json.dumps(read)
    row.expect(
        status == 401
        and F.problem_code(read) == "authentication_failed"
        and (read or {}).get("sign_in") == {"google": False, "guest": "code"},
        f"the signed-out session read answered {status} {F.problem_code(read)} "
        f"{(read or {}).get('sign_in') if isinstance(read, dict) else None}",
    )
    row.expect(
        code not in text and hashlib.sha256(code.encode()).hexdigest() not in text,
        "the signed-out answer holds the code or its digest",
    )
    wrong = stranger.call(
        "SI1 wrong code", "POST", "/auth/guest", body={"code": f"q10-{uuid.uuid4().hex[:12]}"}
    )
    row.expect(
        answered(*wrong)[:2] == [403, "guest_entry_code_wrong"] and not stranger.set_cookie,
        f"a wrong code answered {answered(*wrong)}; cookie set {bool(stranger.set_cookie)}",
    )
    extra = stranger.call(
        "SI1 extra field", "POST", "/auth/guest", body={"code": "q10", "remember": True}
    )
    row.expect(
        extra[0] == 422 and not stranger.set_cookie,
        f"a body with an extra field answered {extra[0]}; cookie set {bool(stranger.set_cookie)}",
    )
    row.observed = {
        "origin": stranger.origin,
        "session": [status, F.problem_code(read), (read or {}).get("sign_in")],
        "wrong_code": answered(*wrong)[:2],
        "extra_field": extra[0],
    }
    return row.close()


def row_ar1(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    world, scene = arrival_world(worktree)
    engine = world.get("society_engine") or ARRIVAL_LIVING_ENGINE
    row = Row(
        "AR1",
        "accounts.arrival_town_lives",
        "A guest's arrival town lives without a scene (candidate-38; deployment.md, arrival "
        "worlds): on a host that does not offer societies of things, a guest's entry is 201 and "
        "its incomplete list is exactly the step scene with society_engine_not_offered. The "
        f"arrival world's society reads 200 on {engine}, the engine its catalog entry states "
        "(the contract's when it states none), with people in it, nobody who came by being "
        "placed and nothing of the scene placed in the version. It is paused at entry.",
    )
    guest, entered = D.enter_guest(stack, transcripts, "guest-ar1")
    row.expect(
        entered.get("status") == 201 and entered.get("incomplete") == [SCENE_NOT_OFFERED],
        f"the entry answered {entered.get('status')} with incomplete {entered.get('incomplete')}",
    )
    row.expect(scene is not None, "the arrival catalog's first world names no scene")
    seen = arrival_reading(guest, "AR1", entered)
    if not seen:
        row.expect(False, f"the entry named no arrival world: {entered.get('arrival')}")
        return row.close()
    row.expect(
        seen["status"] == 200 and seen["profile"] == engine and bool(seen["people"]),
        f"the arrival society read {seen['status']} on {seen['profile']} with "
        f"{len(seen['people'])} people",
    )
    scene_ids = {t["thing_id"] for t in (scene or {}).get("things") or []}
    row.expect(
        "placed" not in seen["came_by"]
        and not seen["placed_beings"]
        and not scene_ids & set(seen["things"]),
        f"the town holds {seen['things']} and people who came by {seen['came_by']}",
    )
    row.expect(seen["mode"] == "paused", f"the society's control reads {seen['mode']}")
    row.observed = {
        "entry": [entered.get("status"), entered.get("incomplete")],
        "arrival": entered.get("arrival"),
        "society": [seen["status"], seen["profile"], len(seen["people"])],
        "came_by": seen["came_by"],
        "things": seen["things"],
        "mode": seen["mode"],
        "catalog_world": {k: world.get(k) for k in ("key", "recipe", "scene", "society_engine")},
    }
    return row.close()


def row_ar2(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    world, scene = arrival_world(worktree)
    scene = scene or {}
    things = sorted(t["thing_id"] for t in scene.get("things") or [])
    minds = {
        m["thing_id"]: (m.get("decider") or {}).get("model_id") for m in scene.get("minds") or []
    }
    row = Row(
        "AR2",
        "accounts.arrival_town_dressed",
        "A guest's arrival town is dressed with its scene where the host offers societies of "
        "things (candidate-38; deployment.md, arrival worlds): a guest's entry is 201; the "
        f"arrival society is on the scene's own engine, {scene.get('engine')}; the version "
        f"holds every thing the scene's catalog file places ({', '.join(things)}); the scene's "
        f"beings ({', '.join(sorted(minds))}) are inhabitants who came by being placed, beside "
        "townspeople who came by being populated; each being's mind is recorded as a model "
        "choice naming the scene's model, or the entry's incomplete list names that being's "
        "step scene with the refusal's code, and the list holds nothing else. It is paused at "
        "entry. A second guest gets a town of their own, another workspace, dressed the same.",
    )
    readings = []
    for name in ("guest-ar2", "guest-ar2-b"):
        guest, entered = D.enter_guest(stack, transcripts, name)
        seen = arrival_reading(guest, f"AR2 {name}", entered)
        incomplete = entered.get("incomplete")
        row.expect(
            entered.get("status") == 201 and isinstance(incomplete, list) and bool(seen),
            f"{name}: the entry answered {entered.get('status')} {entered.get('arrival')}",
        )
        if not seen or not isinstance(incomplete, list):
            continue
        row.expect(
            seen["status"] == 200 and seen["profile"] == scene.get("engine"),
            f"{name}: the arrival society read {seen['status']} on {seen['profile']}",
        )
        row.expect(
            set(things) <= set(seen["things"]),
            f"{name}: the version holds {seen['things']}, the scene places {things}",
        )
        by_id = {p.get("id"): p for p in seen["people"]}
        beings = {being: seen["placed_beings"].get(being) for being in minds}
        row.expect(
            all(beings.values())
            and all((by_id.get(i) or {}).get("came_by") == "placed" for i in beings.values())
            and "populated" in seen["came_by"],
            f"{name}: the scene's beings read {beings}; people came by {seen['came_by']}",
        )
        excused = {step.get("thing_id") for step in incomplete if step.get("step") == "scene"}
        recorded = {}
        for being, model_id in minds.items():
            choice = next(
                (x for x in seen["choices"] if x.get("subject_id") == beings.get(being)), None
            )
            recorded[being] = bool(choice) and str(model_id) in json.dumps(choice)
            row.expect(
                recorded[being] or being in excused,
                f"{name}: {being}'s mind is neither recorded as {model_id} nor named incomplete",
            )
        row.expect(
            all(
                step.get("step") == "scene" and step.get("thing_id") in minds and step.get("code")
                for step in incomplete
            ),
            f"{name}: the entry left incomplete {incomplete}",
        )
        row.expect(seen["mode"] == "paused", f"{name}: the society's control reads {seen['mode']}")
        readings.append(
            {
                "guest": name,
                "workspace": entered.get("workspace_id"),
                "incomplete": incomplete,
                "society": [seen["status"], seen["profile"], len(seen["people"])],
                "things": seen["things"],
                "beings": beings,
                "minds_recorded": recorded,
                "came_by": seen["came_by"],
                "mode": seen["mode"],
            }
        )
    row.expect(
        len(readings) == 2 and readings[0]["workspace"] != readings[1]["workspace"],
        "the two guests do not each hold a workspace of their own",
    )
    row.observed = {
        "guests": [{k: v for k, v in r.items() if k != "workspace"} for r in readings],
        "scene": {k: scene.get(k) for k in ("scene", "version", "engine")},
        "scene_minds": minds,
        "catalog_world": {k: world.get(k) for k in ("key", "recipe", "scene")},
    }
    return row.close()


def _guest_stack(arguments: argparse.Namespace, *, things: bool) -> tuple[Path, Stack]:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if (
        "accounts" not in stack.state
        or "edge" not in stack.state
        or served != hashlib.sha256(D.COMPARISONS_PLAN.read_bytes()).hexdigest()
        or bool(stack.state.get("society_of_things")) != things
    ):
        raise SystemExit(
            "needs a fresh database and a stack started with --accounts-guest-code --edge-port "
            "PORT --tiles --scripted-model scripts/acceptance/plans/comparisons.json --spending "
            "durable --society-playback --no-derivative-worker"
            + (" --society-of-things" if things else " and no --society-of-things")
        )
    return worktree, stack


def guest_arrival(arguments: argparse.Namespace) -> int:
    worktree, stack = _guest_stack(arguments, things=False)
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    rows = [row_si1(stack, transcripts), row_ar1(stack, transcripts, worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


def guest_scene(arguments: argparse.Namespace) -> int:
    worktree, stack = _guest_stack(arguments, things=True)
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    rows = [row_ar2(stack, transcripts, worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- MF1: what came across with a visitor, and what stayed behind ------------------------------------

MANIFEST_PROFILE = "exulanica.translation-manifest/v2"


def manifest_read(c: Any, label: str, arrival: str, world: str, version: str | None = None):
    query = {"world_id": world} | ({"version_id": version} if version else {})
    return c.call(label, "GET", f"/door/crossings/{arrival}/manifest", query=query)


def row_mf1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    mapping = json.loads((worktree / D.LUANTI_MAPPING).read_text())
    stays = [(e.get("words"), e.get("reason_words")) for e in mapping.get("never_crosses") or []]
    declared = [
        e
        for e in json.loads(stack.state.get("door_bridges") or "[]")
        if isinstance(e, dict) and e.get("bridge") == "luanti"
    ]
    label = declared[0].get("label") if declared else None
    row = Row(
        "MF1",
        "door.crossing_manifest",
        "What came across with a visitor (candidate-38; door-contract.md, the manifest route): on "
        "workspace 2's own build of the newest locked scene, a Luanti visitor crosses in. Its "
        "owner's read of the arrival's manifest is 200 with manifest_sha256, the manifest "
        f"({MANIFEST_PROFILE}) and from, naming the bridge luanti with the label the run's "
        "declaration states; every entry the mapping file says never crosses, a player's name "
        "among them, is in the manifest in the mapping's own words with its reason. The read "
        "naming the society's version answers the same digest. Another workspace's read, an id "
        "nobody sent and a version nobody holds are each 404 unknown_reference. After the "
        "visitor is called home and gone, its departure's id is 404 unknown_reference and the "
        "arrival's manifest still reads, the same digest.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    record_path = out / "evidence" / "mf1-scene-build.json"
    built = D.build_scene(stack, worktree, record_path, token_file="token-2")
    (out / "evidence" / "mf1-scene-build.txt").write_text(built.stdout + built.stderr)
    if not record_path.exists():
        row.expect(False, f"the scene build exited {built.returncode}")
        return row.close()
    record = json.loads(record_path.read_text())
    entry = F.read_entry(w2, "MF1", record["entry_id"])
    query, world, version = F.world_query(entry), entry["world_id"], entry["authored_version_id"]
    status_society, _ = w2.call(
        "MF1",
        "POST",
        F.version_path(entry, "/society"),
        query=query,
        body={"region_id": record["arrival"]["region_id"], "profile": D.THINGS_ENGINE},
    )
    gate = next(t["thing_id"] for t in record["things"] if t["kind"]["kind"] == "gate")
    status_grant, granted = w2.call(
        "MF1",
        "POST",
        "/door/grants",
        query=query,
        body={
            "idempotency_key": str(uuid.uuid4()),
            "bridge": "luanti",
            "version_id": version,
            "minutes": 60,
            "channel_credential": True,
            "visitors_maximum": 1,
            "kinds": [D.CROSSING_TYPE],
            "gate": gate,
            "may_carry_in": True,
            "may_carry_out": True,
        },
    )
    credential = ((granted or {}).get("channel_credential") or {}).get("credential")
    row.expect(
        status_society in (200, 201) and status_grant == 201 and bool(credential),
        f"the society answered {status_society}, the grant {status_grant} {F.problem_code(granted)}",
    )
    if not credential:
        return row.close()
    D.channel(stack, credential, "POST", "/door/channel/hello", raw=D.luanti_hello(worktree))
    arrival_id = str(uuid.uuid4())
    status_in, came = D.channel(
        stack,
        credential,
        "POST",
        "/door/channel/arrivals",
        {
            "arrival_id": arrival_id,
            "game_type": D.CROSSING_TYPE,
            "look_key": D.CROSSING_LOOK,
            "carried": [{"game_item": D.CROSSING_ITEM, "count": 1}],
        },
    )
    thing_id = (came or {}).get("thing_id")
    row.expect(status_in == 201 and bool(thing_id), f"the arrival answered {status_in}")
    D.step(w2, "MF1", entry)
    status, read = manifest_read(w2, "MF1 read", arrival_id, world)
    read = read if isinstance(read, dict) else {}
    manifest, came_from = read.get("manifest") or {}, read.get("from") or {}
    text = json.dumps(manifest, ensure_ascii=False)
    row.expect(
        status == 200
        and isinstance(read.get("manifest_sha256"), str)
        and manifest.get("profile") == MANIFEST_PROFILE
        and came_from.get("bridge") == "luanti",
        f"the manifest read answered {status} {F.problem_code(read)} from {came_from}",
    )
    row.expect(
        label is not None and came_from.get("label") == label and "ai" in came_from,
        f"the manifest names its bridge {came_from}, the declaration's label is {label!r}",
    )
    missing = [words for words, reason in stays if words not in text or reason not in text]
    row.expect(
        bool(stays) and not missing and any("name" in str(words) for words, _ in stays),
        f"the manifest lacks the mapping's words for {missing or 'nothing'} of {len(stays)}",
    )
    status_v, read_v = manifest_read(w2, "MF1 read version", arrival_id, world, version)
    row.expect(
        status_v == 200 and (read_v or {}).get("manifest_sha256") == read.get("manifest_sha256"),
        f"the read naming the version answered {status_v}",
    )
    not_found = {
        "another workspace": manifest_read(w1, "MF1 stranger", arrival_id, world),
        "an id nobody sent": manifest_read(w2, "MF1 unsent", str(uuid.uuid4()), world),
        "a version nobody holds": manifest_read(
            w2, "MF1 no version", arrival_id, world, str(uuid.uuid4())
        ),
    }
    status_home, home = D.channel(
        stack, credential, "POST", "/door/channel/home", {"thing_id": thing_id}
    )
    departure = (home or {}).get("departure_id")
    D.step(w2, "MF1 home", entry)
    _, after = F.society(w2, "MF1 after", entry)
    still_here = thing_id in {
        p.get("id") for p in ((after or {}).get("state") or {}).get("inhabitants") or []
    }
    row.expect(
        status_home == 202 and bool(departure) and not still_here,
        f"the call home answered {status_home}; the visitor is still here {still_here}",
    )
    if departure:
        not_found["a departure's id"] = manifest_read(w2, "MF1 departure", departure, world)
    for name, got in not_found.items():
        row.expect(
            answered(*got)[:2] == [404, "unknown_reference"],
            f"{name}: the manifest read answered {answered(*got)}",
        )
    status_gone, read_gone = manifest_read(w2, "MF1 read after", arrival_id, world)
    row.expect(
        status_gone == 200
        and (read_gone or {}).get("manifest_sha256") == read.get("manifest_sha256"),
        f"after the visitor left the manifest read answered {status_gone}",
    )
    row.observed = {
        "read": [status, read.get("manifest_sha256"), came_from],
        "declared_label": label,
        "never_crosses": len(stays),
        "manifest_keys": sorted(manifest),
        # Recorded, not judged: the contract states the digest, not the form it is taken over.
        "sha256_of_sorted_compact_json": hashlib.sha256(D.canonical_json(manifest)).hexdigest()
        == read.get("manifest_sha256"),
        "with_version": status_v,
        "not_found": {name: answered(*got)[:2] for name, got in not_found.items()},
        "home": [status_home, bool(departure), still_here],
        "after_departure": [status_gone, (read_gone or {}).get("manifest_sha256")],
        "mapping": str(D.LUANTI_MAPPING),
    }
    return row.close()


def crossing_manifest(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    if not stack.state.get("society_of_things") or "door_bridges" not in stack.state:
        raise SystemExit(
            "crossing-manifest needs a fresh database and the crossings stack: --workspaces 2 "
            "--read-only-token --no-derivative-worker --society-of-things --society-playback "
            "--door-bridges FILE (domain_rows.py declare-luanti FILE)"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_mf1(stack, Transcripts(out / "transcripts"), worktree, out)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- PR3: a piece request with no maker running, and taking back what was never taken in ------------

#: The estimate's words for its provider (generated-pieces-contract.md, the estimate).
GPU_PROVIDER_LABEL = "Nebius AI Cloud"


def basis_stated(compute: Mapping[str, Any]) -> dict[str, Any]:
    """Where an estimate says its item figures come from: the catalog entry's basis by its kind,
    runs and items (A-149); the evidence folders are how the catalog names them."""
    return {key: compute["basis"].get(key) for key in ("kind", "runs", "items")}


def served_look(c: Any, worktree: Path) -> dict[str, Any] | None:
    """A served library pack the generation catalog holds style words for, as an ask names it."""
    styles = json.loads((worktree / D.GENERATION_CATALOGS / "piece-styles.v1.json").read_text())
    styled = {e["pack_id"] for e in styles["entries"]}
    packs = (c.call("look", "GET", "/world/style-packs")[1] or {}).get("packs") or []
    pack = next((p for p in packs if p.get("pack_id") in styled), None)
    return pack and {k: pack[k] for k in ("pack_id", "version", "manifest_sha256")}


def row_pr3(stack: Stack, transcripts: Any, worktree: Path, issued: Mapping[str, Any]) -> Row:
    compute = D.piece_compute(worktree)
    row = Row(
        "PR3",
        "pieces.no_maker",
        "A piece request with no maker running, and taking back what was never taken in "
        "(candidate-38; generated-pieces-contract.md, routes and refusals, the estimate): with an "
        "operator's GPU grant, an ask for one shipped kind's pieces in a served look is 202; its "
        "session reads off with words; the estimate names its provider "
        f"'{GPU_PROVIDER_LABEL}' and the compute catalog entry's basis ({compute['basis']['kind']}, "
        f"{compute['basis']['runs']} runs, {compute['basis']['items']} items); the request names "
        "its kind's label and no look step. Taking it back is 409 piece_not_taken_in with a "
        "step; an invented id and the other workspace's take-back are each 404 "
        "unknown_piece_request; cancelled, its take-back is still 409 piece_not_taken_in.",
    )
    w1 = F.client(stack, transcripts, "w1", "token")
    w2 = F.client(stack, transcripts, "w2", "token-2")
    look = served_look(w1, worktree)
    town = D.made_town(w1, "PR3", "Q10 PR3 town")
    if look is None or not town.get("world_id"):
        row.blocked_by.append("no served pack with style words, or no town")
        return row.close()
    kind = D.PIECE_KINDS[0]
    shipped = json.loads(
        (
            worktree / D.THING_CATALOGS / "kinds" / f"{kind['key']}.v{kind['version']}.json"
        ).read_text()
    )
    status, asked = w1.call(
        "PR3 ask",
        "POST",
        "/world/piece-requests",
        body={"world_id": town["world_id"], "look": look, "kinds": [kind]},
    )
    asked = asked if isinstance(asked, dict) else {}
    requests = asked.get("piece_requests") or []
    session, estimate = asked.get("session") or {}, asked.get("estimate") or {}
    row.expect(
        status == 202 and len(requests) == 1, f"the ask answered {status} {F.problem_code(asked)}"
    )
    if len(requests) != 1:
        row.observed = {"issued": dict(issued), "ask": answered(status, asked)}
        return row.close()
    request = requests[0]
    row.expect(
        session.get("state") == "off" and bool(session.get("detail")),
        f"the session reads {session}",
    )
    row.expect(
        estimate.get("provider_label") == GPU_PROVIDER_LABEL
        and estimate.get("basis") == basis_stated(compute),
        f"the estimate names {estimate.get('provider_label')} with basis {estimate.get('basis')}",
    )
    row.expect(
        (request.get("kind") or {}).get("label") == shipped.get("label")
        and request.get("look_step") is None,
        f"the request names {request.get('kind')} with look step {request.get('look_step')}",
    )
    path = f"/world/piece-requests/{request.get('piece_request_id')}/take-back"
    waiting = w1.call("PR3 take back", "POST", path)
    row.expect(
        answered(*waiting)[:2] == [409, "piece_not_taken_in"]
        and bool((waiting[1] or {}).get("step")),
        f"taking back a waiting request answered {answered(*waiting)}",
    )
    invented = w1.call("PR3 invented", "POST", f"/world/piece-requests/{uuid.uuid4()}/take-back")
    foreign = w2.call("PR3 foreign", "POST", path)
    for name, got in (("an invented id", invented), ("the other workspace", foreign)):
        row.expect(
            answered(*got)[:2] == [404, "unknown_piece_request"],
            f"{name}: the take-back answered {answered(*got)}",
        )
    cancelled = w1.call(
        "PR3 cancel", "DELETE", f"/world/piece-requests/{request.get('piece_request_id')}"
    )
    after = w1.call("PR3 take back cancelled", "POST", path)
    row.expect(
        cancelled[0] == 200 and answered(*after)[:2] == [409, "piece_not_taken_in"],
        f"cancelled {cancelled[0]}, then taking back answered {answered(*after)}",
    )
    row.observed = {
        "issued": dict(issued),
        "look": look,
        "ask": [status, request.get("state"), request.get("variants")],
        "session": session,
        "estimate": estimate,
        "kind": request.get("kind"),
        "look_step": request.get("look_step"),
        "take_back": [answered(*waiting), (waiting[1] or {}).get("step")],
        "not_found": [answered(*invented)[:2], answered(*foreign)[:2]],
        "after_cancel": [cancelled[0], answered(*after), (after[1] or {}).get("step")],
    }
    return row.close()


# -- CP1: the Companion's plan over things and beings ------------------------------------------------

THINGS_PLAN = HERE / "plans" / "companion-things.json"
#: The most steps a plan may hold (companion-question.md, world actions).
PLAN_STEPS_MAXIMUM = 8
#: Where the person points and stands when they ask: beside the scene, in its region.
ASK_SPOT = {"x_mm": -6000, "y_mm": 0, "z_mm": 4000, "yaw_microradians": 0, "scale_milli": 1000}
ASK_VIEWER = {"x_mm": 0, "z_mm": 4000, "yaw_microradians": 0}
#: The codes a step that must wait for a minute carries, and how many minutes the page waits.
WAIT_CODES = ("society_input_queued", "inhabitant_action_in_progress", "destination_full")
WAIT_MINUTES = 20
MINTED_ID = r"companion:{kind}:[0-9a-f]{{12}}"


def action_base(c: Any, label: str, entry: Mapping[str, Any], region: str | None) -> dict[str, Any]:
    """What an ask and a prepare both state: the version as it reads now and what the page shows."""
    _, version = c.call(label, "GET", F.version_path(entry), query=F.world_query(entry))
    context = (
        {}
        if region is None
        else {
            "placement": {"region_id": region, "transform": ASK_SPOT},
            "viewer": {**ASK_VIEWER, "region_id": region},
        }
    )
    return {
        "version_id": entry["authored_version_id"],
        "base_state_sha256": (version or {}).get("state_sha256"),
        "origin_role": "fictional",
        "context": context,
    }


def ask(c: Any, label: str, entry: Mapping[str, Any], words: str, region: str | None):
    status, plan = c.call(
        label,
        "POST",
        F.ACTIONS,
        query=F.world_query(entry),
        body={**action_base(c, label, entry, region), "utterance": words},
    )
    return status, plan if isinstance(plan, dict) else {}


def prepare(
    c: Any, label: str, entry: Mapping[str, Any], actions: Sequence[Any], region: str | None
):
    """Typed actions sent back to be prepared, as a page answers a question or prepares a step."""
    status, plan = c.call(
        label,
        "POST",
        f"{F.ACTIONS}/prepare",
        query=F.world_query(entry),
        body={**action_base(c, label, entry, region), "actions": list(actions)},
    )
    return status, plan if isinstance(plan, dict) else {}


def why_not(plan: Mapping[str, Any]) -> list[Any]:
    """What a plan that is not one says about itself."""
    return [
        plan.get("outcome"),
        (plan.get("refusal") or {}).get("code"),
        (plan.get("clarification") or {}).get("code"),
        [[s.get("state"), s.get("code")] for s in plan.get("steps") or []],
    ]


def row_cp1(stack: Stack, transcripts: Any, worktree: Path, out: Path) -> Row:
    lines = json.loads(THINGS_PLAN.read_text())["utterances"]
    row = Row(
        "CP1",
        "companion.things_plan",
        "The Companion drafts a longer plan over things and beings (candidate-38; "
        "companion-question.md, world actions, things and beings): on workspace 1's own build of "
        "the newest locked scene with its society of things, the scripted drafter answers one "
        "request with six steps naming kinds by key: a lantern added, the knight sent to the "
        "well and asked to use it, the sword picked up and put down, the new lantern picked up. "
        "A kind names the one being of that kind where a being is sent to a place, and names "
        "only the thing in a hands step, so the answer asks who is meant: being_required at the "
        "first hands step, the knight among its candidates, carrying all six typed actions in "
        "order: place_thing of a lantern under an id minted companion:lantern:<12 hex>; go_to "
        "and use naming the knight and one place; pick_up and put_down of the sword and pick_up "
        "of the minted lantern, each with no being yet. Nothing is written by asking. Answered "
        "as a page answers, the knight filled in and all six sent to the prepare route, the "
        "answer is a plan of six steps, the first prepared, with no model asked and nothing "
        "written. Confirmed through its own operation the first step is 201, the version holds "
        "the minted thing, and the outcome read with that answer says applied by an add_thing "
        "receipt. The pick-up of the sword, prepared again minute by minute while it says to "
        f"wait (at most {WAIT_MINUTES}), is taken when confirmed, and within {D.ASKED_MINUTES} "
        "minutes the knight picks the sword up. A drafter answer of nine steps, above the eight a "
        "plan may hold, is refused not_drafted; an inexpressible change refuses the plan "
        "action_not_offered; with the knight holding the sword, a take of it by the lantern "
        "spirit, its beings filled in the same way, is blocked act_not_offered.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    entry, society, placed = scene_society(stack, c, worktree, out, "CP1", "token")
    knight, spirit, sword = placed.get("knight"), placed.get("lantern-spirit"), placed.get("sword")
    row.expect(
        entry is not None and society.get("status") in (200, 201) and bool(knight and sword),
        f"the scene's society answered {society.get('status') or society}",
    )
    if not (entry and knight and sword):
        return row.close()
    record = json.loads((out / "evidence" / "CP1-scene-build.json").read_text())
    region = record["arrival"]["region_id"]
    query = F.world_query(entry)

    def reading() -> list[Any]:
        _, version = c.call("CP1 reading", "GET", F.version_path(entry), query=query)
        _, now = F.society(c, "CP1 reading", entry)
        return [
            (version or {}).get("state_sha256"),
            len((version or {}).get("things") or []),
            (now or {}).get("state_sha256"),
            (now or {}).get("current_tick"),
        ]

    before = reading()
    calls = len(D.scripted_log(stack))
    status, asked = ask(c, "CP1 ask", entry, lines["evening"], region)
    question = asked.get("clarification") or {}
    actions = [dict(a) for a in question.get("actions") or []]
    acts = [a.get("act") or a.get("operation") for a in actions]
    wanted = ["place_thing", "go_to", "use", "pick_up", "put_down", "pick_up"]
    row.expect(
        status == 200
        and asked.get("outcome") == "clarify"
        and [question.get("code"), question.get("step"), question.get("slot")]
        == ["being_required", 3, "subject_id"]
        and knight in [x.get("value") for x in question.get("candidates") or []],
        f"the six-step request answered {status} {why_not(asked)} at step {question.get('step')} "
        f"slot {question.get('slot')}",
    )
    row.expect(acts == wanted, f"the typed actions are {acts}, not {wanted}")
    asked_calls = len(D.scripted_log(stack)) - calls
    row.expect(asked_calls <= 4, f"one request asked the model {asked_calls} times")
    row.expect(reading() == before, f"asking changed the world: {before} then {reading()}")
    if acts != wanted:
        row.observed = {"asked": why_not(asked), "acts": acts, "refusal": asked.get("refusal")}
        return row.close()
    minted = actions[0].get("thing_id") or ""
    row.expect(
        re.fullmatch(MINTED_ID.format(kind="lantern"), minted) is not None
        and actions[0].get("kind") == "lantern",
        f"the first action adds {actions[0].get('kind')} as {minted!r}",
    )
    row.expect(
        all(a.get("operation") == "direct_thing" for a in actions[1:])
        and [a.get("subject_id") for a in actions[1:]] == [knight, knight, None, None, None],
        f"the asking actions name {[a.get('subject_id') for a in actions[1:]]}",
    )
    row.expect(
        actions[1].get("target_id") is not None
        and actions[1].get("target_id") == actions[2].get("target_id"),
        f"go_to and use name {actions[1].get('target_id')} and {actions[2].get('target_id')}",
    )
    row.expect(
        [a.get("thing_id") for a in actions[3:]] == ["sword", "sword", minted],
        f"the hands actions name {[a.get('thing_id') for a in actions[3:]]}",
    )

    # The answer, as a page sends it: the open slot and the later hands steps' filled with the
    # knight, and every typed action sent back to be prepared.
    filled = [
        {**a, "subject_id": knight}
        if a.get("operation") == "direct_thing" and a.get("subject_id") is None
        else a
        for a in actions
    ]
    calls = len(D.scripted_log(stack))
    status_plan, plan = prepare(c, "CP1 prepare", entry, filled, region)
    steps = plan.get("steps") or []
    row.expect(
        status_plan == 200
        and plan.get("outcome") == "plan"
        and len(steps) == 6
        and steps[0].get("state") == "prepared",
        f"preparing the six answered actions gave {status_plan} {why_not(plan)}",
    )
    row.expect(
        len(D.scripted_log(stack)) == calls and reading() == before,
        "preparing asked a model or changed the world",
    )
    if len(steps) != 6:
        row.observed = {"asked": why_not(asked), "actions": actions, "plan": why_not(plan)}
        return row.close()

    placed_status, version = F.confirm(c, "CP1 confirm place", entry, steps[0])
    held = D.placed(version if isinstance(version, dict) else {}, minted)
    row.expect(
        placed_status == 201 and held is not None,
        f"confirming the first step answered {placed_status} {F.problem_code(version)}",
    )
    answer = F.edit_answer(placed_status, version)
    _, read = F.outcome(c, "CP1 outcome", entry, plan, [answer])
    first_read = ((read or {}).get("steps") or [{}])[0] if isinstance(read, dict) else {}
    receipts = first_read.get("receipts") or []
    row.expect(
        first_read.get("state") == "applied"
        and any(r.get("kind") == "add_thing" and r.get("thing_id") == minted for r in receipts),
        f"the outcome read says {first_read.get('state')} with receipts {receipts}",
    )

    # As the page does: the asking step prepared again a minute at a time while it says to wait.
    waited, prepared = [], {}
    for _ in range(WAIT_MINUTES):
        _, again = prepare(c, "CP1 prepare pick-up", entry, [filled[3]], region)
        prepared = (again.get("steps") or [{}])[0]
        if prepared.get("state") != "pending":
            break
        waited.append(prepared.get("code"))
        step_once(c, "CP1 wait", entry)
    row.expect(
        prepared.get("state") == "prepared" and all(code in WAIT_CODES for code in waited),
        f"the pick-up step reads {prepared.get('state')} {prepared.get('code')} after waits {waited}",
    )
    asked_status, asked_answer = (
        F.confirm(c, "CP1 confirm pick-up", entry, prepared)
        if prepared.get("state") == "prepared"
        else (0, {})
    )
    row.expect(
        asked_status in (200, 201, 202),
        f"confirming the pick-up answered {asked_status} {F.problem_code(asked_answer)}",
    )
    picked: list[Any] = []
    for _ in range(D.ASKED_MINUTES):
        step_once(c, "CP1 minute", entry)
        picked = events_of(c, "CP1 events", entry, "picked_up", knight)
        if picked:
            break
    row.expect(
        bool(picked)
        and ((picked[0].get("document") or {}).get("thing") or {}).get("thing") == sword,
        f"the knight's pick-up reads {picked[:1] or 'none'}",
    )

    _, nine = ask(c, "CP1 nine", entry, lines["nine"], region)
    row.expect(
        nine.get("outcome") == "refused"
        and (nine.get("refusal") or {}).get("code") == "not_drafted",
        f"nine steps answered {why_not(nine)}",
    )
    _, other = ask(c, "CP1 other", entry, lines["other"], region)
    row.expect(
        (other.get("refusal") or {}).get("code") == "action_not_offered",
        f"an inexpressible change answered {why_not(other)}",
    )
    _, take = ask(c, "CP1 take", entry, lines["take"], region)
    take_question = take.get("clarification") or {}
    take_actions = [
        {
            **a,
            "subject_id": a.get("subject_id") or spirit,
            "with_id": a.get("with_id") or knight,
        }
        for a in take_question.get("actions") or []
    ]
    _, taken = (
        prepare(c, "CP1 prepare take", entry, take_actions, region) if take_actions else (0, take)
    )
    take_steps = taken.get("steps") or []
    row.expect(
        bool(take_steps)
        and [take_steps[0].get("state"), take_steps[0].get("code")]
        == ["blocked", "act_not_offered"],
        f"a take answered {why_not(take)}, then prepared {why_not(taken)}",
    )
    row.observed = {
        "asked": why_not(asked),
        "question": {k: question.get(k) for k in ("code", "step", "slot")},
        "candidates": len(question.get("candidates") or []),
        "prompt_version": (asked.get("execution") or {}).get("prompt_version"),
        "actions": actions,
        "plan": [plan.get("outcome"), plan.get("kind"), plan.get("spends")],
        "steps": [[s.get("operation"), s.get("state"), s.get("code")] for s in steps],
        "titles": [s.get("titles") for s in steps],
        "compensation": steps[0].get("compensation"),
        "before_and_after_planning": before,
        "placed": [placed_status, minted, first_read.get("state")],
        "pick_up": {"waits": waited, "confirmed": asked_status, "picked_up": bool(picked)},
        "nine": why_not(nine),
        "other": why_not(other),
        "take": [why_not(take), take_question.get("code"), why_not(taken)],
        "scripted_calls_for_the_request": asked_calls,
    }
    return row.close()


def companion_things(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    served = (stack.state.get("scripted_model") or {}).get("plan_sha256")
    if served != hashlib.sha256(THINGS_PLAN.read_bytes()).hexdigest() or not stack.state.get(
        "society_of_things"
    ):
        raise SystemExit(
            "companion-things needs a fresh database and a stack started with --workspaces 2 "
            "--society-of-things --scripted-model scripts/acceptance/plans/companion-things.json "
            "--spending process --no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    rows = [row_cp1(stack, Transcripts(out / "transcripts"), worktree, out)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


# -- CP2: the Companion offers new pieces, naming their time and cost before the yes -----------------

OFFER_PLAN = HERE / "plans" / "piece-offer.json"
MODEL_PROVIDER = "nebius_token_factory"


def grant_models(stack: Stack, worktree: Path) -> dict[str, Any]:
    """An authority for the hosted model provider and a grant to the first workspace, as an
    operator issues them, so the Companion's scripted calls are admitted under durable spending."""
    common = ("--operator", "acceptance", "--reason", "acceptance piece offer")
    until = ("--valid-until", "2027-01-01T00:00:00Z")
    authority = D.spending_operator(
        stack,
        worktree,
        "issue",
        "--provider",
        MODEL_PROVIDER,
        "--ceiling-usd",
        "0.05",
        "--max-calls",
        "100",
        *until,
        *common,
    )
    D.spending_operator(
        stack,
        worktree,
        "grant",
        "--authority",
        authority["authority_id"],
        "--workspace",
        stack.state["workspace_id"],
        "--ceiling-usd",
        "0.05",
        "--max-calls",
        "100",
        *until,
        *common,
    )
    return {"authority": authority.get("authority_id")}


def row_cp2(stack: Stack, transcripts: Any, worktree: Path) -> Row:
    lines = json.loads(OFFER_PLAN.read_text())["utterances"]
    compute = D.piece_compute(worktree)
    row = Row(
        "CP2",
        "companion.piece_offer",
        "The Companion offers new pieces, naming their time and cost before the yes "
        "(candidate-38; companion-question.md, new pieces of the world's look): in a town made "
        "through the kinds route, with an operator's GPU grant and no piece maker running, a "
        "request for new pieces of the well and the gate (A-149) answers a plan of one "
        "request_pieces step for those of them that have a piece, "
        "confirmation required, spending, prepared, carrying an estimate that names "
        f"'{GPU_PROVIDER_LABEL}', a typical and a worst-case cost and the compute catalog's "
        "basis. Before the yes the world holds no piece request. The same asked with another "
        "change in one request is refused action_not_offered. Confirmed through its own "
        "operation it is 202, the session off, with the estimate the step carried, and the "
        "world's list then holds exactly the requests the answer names, each requested.",
    )
    c = F.client(stack, transcripts, "w1", "token")
    made = D.made_town(c, "CP2", "Q10 CP2 town")
    if not made.get("entry_id"):
        row.blocked_by.append(f"no town was made: {made}")
        return row.close()
    entry = F.read_entry(c, "CP2", made["entry_id"])
    world = {"world_id": entry["world_id"]}
    status, plan = ask(c, "CP2 ask", entry, lines["pieces"], None)
    steps = plan.get("steps") or []
    step = steps[0] if steps else {}
    row.expect(
        status == 200 and plan.get("outcome") == "plan" and len(steps) == 1,
        f"the request for pieces answered {status} {why_not(plan)}",
    )
    if step.get("state") == "blocked" or (plan.get("refusal") or {}).get("code") in (
        "action_unavailable",
        "look_not_served",
    ):
        row.failures.clear()
        row.blocked_by.append(f"the made town wears no look pieces can be made in: {why_not(plan)}")
        row.observed = {"plan": why_not(plan), "refusal": plan.get("refusal")}
        return row.close()
    action, estimate = step.get("action") or {}, step.get("estimate") or {}
    row.expect(
        action.get("operation") == "request_pieces"
        and step.get("state") == "prepared"
        and step.get("confirmation") == "required"
        and step.get("spends") is True,
        f"the step reads {action.get('operation')} {step.get('state')} confirmation "
        f"{step.get('confirmation')} spends {step.get('spends')}",
    )
    row.expect(
        estimate.get("provider_label") == GPU_PROVIDER_LABEL
        and estimate.get("basis") == basis_stated(compute)
        and all(estimate.get(k) is not None for k in ("usd_typical", "usd_worst_case"))
        and all(
            isinstance(estimate.get(k), int)
            for k in ("items", "first_seconds_warm", "all_seconds_warm", "cold_start_seconds")
        ),
        f"the step's estimate reads {estimate}",
    )
    _, listed = c.call("CP2 list before", "GET", "/world/piece-requests", query=world)
    before = (listed or {}).get("piece_requests")
    row.expect(before == [], f"before the yes the world's piece requests read {before}")
    _, mixed = ask(c, "CP2 mixed", entry, lines["mixed"], None)
    row.expect(
        (mixed.get("refusal") or {}).get("code") == "action_not_offered",
        f"pieces mixed with another change answered {why_not(mixed)}",
    )
    confirmed_status, confirmed = (
        F.confirm(c, "CP2 confirm", entry, {**step, "query": step.get("query") or {}})
        if step.get("state") == "prepared"
        else (0, {})
    )
    confirmed = confirmed if isinstance(confirmed, dict) else {}
    requests = confirmed.get("piece_requests") or []
    row.expect(
        confirmed_status == 202
        and bool(requests)
        and (confirmed.get("session") or {}).get("state") == "off"
        and all(r.get("state") == "requested" for r in requests),
        f"the yes answered {confirmed_status} {F.problem_code(confirmed)} with "
        f"{len(requests)} requests",
    )
    row.expect(
        D.same_estimate(
            confirmed.get("estimate") or {},
            {k: v for k, v in estimate.items() if k not in ("provider_label", "basis")},
        ),
        f"the route's estimate {confirmed.get('estimate')} is not the step's {estimate}",
    )
    expected = D.expected_estimate(compute, [int(r.get("variants") or 0) for r in requests])
    row.expect(
        D.same_estimate(estimate, expected),
        f"the step's estimate is not the catalog's figures {expected}",
    )
    _, after = c.call("CP2 list after", "GET", "/world/piece-requests", query=world)
    ids = sorted(r.get("piece_request_id") for r in (after or {}).get("piece_requests") or [])
    row.expect(
        ids == sorted(r.get("piece_request_id") for r in requests),
        f"the world's list holds {len(ids)} requests, the answer {len(requests)}",
    )
    drafted = json.loads(json.loads(OFFER_PLAN.read_text())["rules"][0]["content"])
    named = set(drafted["steps"][0]["options"])
    row.expect(
        bool(requests) and {(r.get("kind") or {}).get("key") for r in requests} <= named,
        f"the requests are for {[(r.get('kind') or {}).get('key') for r in requests]}, named {sorted(named)}",
    )
    row.observed = {
        "plan": [plan.get("outcome"), plan.get("spends"), plan.get("spends_by")],
        "step": [step.get("operation"), step.get("state"), step.get("confirmation")],
        "action": action,
        "titles": step.get("titles"),
        "estimate": estimate,
        "estimate_expected": {k: str(v) for k, v in expected.items()},
        "before": before,
        "mixed": why_not(mixed),
        "yes": [confirmed_status, confirmed.get("session"), len(requests)],
        "kinds_asked": sorted((r.get("kind") or {}).get("key") for r in requests),
        "scripted_calls": len(D.scripted_log(stack)),
    }
    return row.close()


def piece_offer(arguments: argparse.Namespace) -> int:
    worktree = LAUNCH.checkout(arguments.worktree)
    stack = Stack.read(worktree)
    scripted = stack.state.get("scripted_model") or {}
    if (
        scripted.get("plan_sha256") != hashlib.sha256(OFFER_PLAN.read_bytes()).hexdigest()
        or scripted.get("spending") != "durable"
        or not stack.state.get("other_workspaces")
    ):
        raise SystemExit(
            "piece-offer needs a fresh database and a stack started with --workspaces 2 "
            "--scripted-model scripts/acceptance/plans/piece-offer.json --spending durable "
            "--no-derivative-worker"
        )
    out = Path(arguments.out).resolve()
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    started = dt.datetime.now(dt.UTC).isoformat()
    transcripts = Transcripts(out / "transcripts")
    issued = D.grant_gpu(stack, worktree) | {"models": grant_models(stack, worktree)}
    rows = [row_pr3(stack, transcripts, worktree, issued), row_cp2(stack, transcripts, worktree)]
    write_results(out, stack, rows, started, sys.argv[1:])
    return 0 if all(row.status != "failed" for row in rows) else 1


COMMANDS = {
    "play": play,
    "creatures": creatures,
    "guest-arrival": guest_arrival,
    "guest-scene": guest_scene,
    "crossing-manifest": crossing_manifest,
    "companion-things": companion_things,
    "piece-offer": piece_offer,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        command = commands.add_parser(name)
        command.add_argument("--worktree", required=True)
        command.add_argument("--out", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return COMMANDS[arguments.command](arguments)


if __name__ == "__main__":
    raise SystemExit(main())
