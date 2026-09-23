"""Ask the Companion about a place confirmed from its own sign, end to end, through product routes.

    python scripts/measure_companion_place_link.py draw OUT_DIR
    python scripts/measure_companion_place_link.py run --state STATE.json --photos DIR \\
        --arm before|after --out RUN.json

``draw`` makes the four photographs the pre-registration binds: the places lane's end-to-end
scenes of one place, MIRELAND HALL, drawn by ``scene()`` in
``scripts/make_place_proposal_d_photographs.py`` at the same indices, with a capture time written
where ``exulanica/ingest/exif.py`` reads one. Nothing in them is a personal photograph.

``run`` measures one arm on an acceptance runtime started with the model client, as the synthetic
account holder, through the routes a person's browser uses:

1.  ``POST /intake`` for each photograph, refusing any whose bytes are not the registered ones.
2.  ``POST /personal-admission``: detection permission and model rights for the vision, embedding
    and composer roles, granted by the synthetic account holder for synthetic drawings.
3.  The derivative job to a terminal event, then each photograph's place decision, read from the
    stored vision artifact because no route serves it.
4.  ``POST /identity/name`` on the first photograph whose place was written, with the written
    label, and ``POST /identity/confirm`` for every other written one: the account holder
    confirming the proposed place.
5.  ``POST /selection/ask`` with each registered question in words, once.

Every answer is scored by :func:`score`, the rule the pre-registration states, and every model
call's cost is read from the usage the provider reported. The run file is raw evidence for
``scripts/write_companion_place_link_outcome.py``, which writes the outcome record.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import re
import sys
import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from make_place_photographs import photographic  # noqa: E402
from make_place_proposal_d_photographs import scene  # noqa: E402

from exulanica.canonical import canonical_json  # noqa: E402
from exulanica.ingest.exif import extract_exif_facts  # noqa: E402

PREREGISTRATION = "docs/evaluation/2026-09-23-companion-place-link-preregistration.json"

#: The one place every positive scene names, as its board is painted.
PLACE_NAME = "MIRELAND HALL"

#: (file stem, scene kind, arm, text, local capture time, UTC offset). The indices start at 100, as
#: the places lane's end-to-end scenes did, so the drawings are the ones that lane's vision run
#: proposed a place from; the capture times are this recipe's own.
RECIPE: tuple[tuple[str, str, str, Any, str, str], ...] = (
    ("mireland-01-nameplate", "nameplate", "positive", PLACE_NAME, "2026:08:14 11:20:00", "+01:00"),
    (
        "mireland-02-nameplate-tree",
        "nameplate_tree_beside",
        "positive",
        PLACE_NAME,
        "2026:08:16 15:05:00",
        "+01:00",
    ),
    (
        "mireland-03-covered",
        "covered_last",
        "negative",
        ("MIRELAND", "HALL"),
        "2026:08:15 09:40:00",
        "+01:00",
    ),
    ("mireland-04-no-text", "no_text", "negative", "", "2026:08:17 17:30:00", "+01:00"),
)
FIRST_INDEX = 100
#: The JPEG quality the places lane's end-to-end scenes were saved at.
JPEG_QUALITY = 82

#: The questions, asked in words, each once per arm. Their supported answers and the rule each is
#: scored by are stated in the pre-registration, which this file's :func:`score` implements.
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("sign", "What does the sign say at Mireland Hall?"),
    ("which", "Which of my photographs were taken at Mireland Hall?"),
    ("when", "When were my photographs at Mireland Hall taken?"),
)

#: What the synthetic account holder states when granting the rights below. The drawings are
#: synthetic, and the grant says so; the route is the one a person's own photographs take.
ADMISSION_PURPOSE = (
    "End-to-end Companion place measurement on synthetic drawings: a place proposed from a sign, "
    "confirmed, and asked about"
)
AUTHORITY_BASIS = (
    "synthetic drawings made by scripts/measure_companion_place_link.py from the place proposal "
    "experiment's scene generator; no personal photograph"
)

#: The roles whose models receive the photographs or text derived from them on this path: the
#: vision stage and its sign question, the caption and query vectors, and the composer. The
#: planner is sent the question and a catalogue of ids, never a photograph.
GRANTED_ROLES = ("vision", "embedding", "reasoning_cheap")

#: The brief's bound on one run, from the provider's reported usage. A run that reaches it stops
#: before its next question rather than spending past it.
RUN_CEILING_USD = Decimal("0.25")

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_PLACEHOLDER = re.compile(r"\[(?:person|voice|place|object|conversation|event) [A-Z]+\]", re.I)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_id(sha256_hex: str) -> str:
    """The blob id a permalink names, from the SHA-256 the intake route reports."""
    digest = base64.urlsafe_b64encode(bytes.fromhex(sha256_hex)).decode().rstrip("=")
    return f"ni:///sha-256;{digest}"


def _canonical(placeholder: str) -> str:
    """``[Place A]`` as the server writes it, ``[place A]``."""
    word, letters = placeholder[1:-1].split(" ")
    return f"[{word.lower()} {letters.upper()}]"


# -- the photographs -------------------------------------------------------------------------------


def draw(out: Path) -> list[dict[str, Any]]:
    """Draw every registered photograph into ``out`` and return what each is.

    The capture time is checked with the product's own EXIF reader before anything is written, so
    a photograph whose time the product would not read cannot become a question about when.
    """
    out.mkdir(parents=True, exist_ok=True)
    drawn = []
    for position, (stem, kind, arm, text, when, offset) in enumerate(RECIPE):
        index = FIRST_INDEX + position
        image, truth = scene(index, kind, arm, text)
        image = photographic(image, index)
        exif = Image.Exif()
        exif[0x010F] = "Exulanica synthetic"
        exif[0x0110] = "Synthetic place camera"
        exif.get_ifd(0x8769)[0x9003] = when
        exif.get_ifd(0x8769)[0x9011] = offset
        path = out / f"{stem}.jpg"
        image.save(path, "JPEG", quality=JPEG_QUALITY, exif=exif)
        expected = dt.datetime.strptime(f"{when} {offset}", "%Y:%m:%d %H:%M:%S %z")
        with Image.open(path) as opened:
            _, facts = extract_exif_facts(opened)
        if facts.clock is None or facts.clock.utc != expected:
            raise SystemExit(f"{path.name}: the product reads {facts.clock} as its capture time")
        drawn.append(
            {
                "file": path.name,
                "photograph": position + 1,
                "scene_index": index,
                "kind": kind,
                "arm": arm,
                "board_text": truth["board_text"],
                "place_name": truth["place_name"],
                "hidden_words": truth["hidden_words"],
                "captured_at_utc": expected.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
                "sha256": _sha256(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
        )
    return drawn


# -- the rule each answer is scored by -------------------------------------------------------------


def _states_date(text: str, iso_date: str) -> bool:
    """Whether ``text`` states this day: the ISO date, or the day of the month with its month's name."""
    if iso_date in text:
        return True
    year, month, day = (int(part) for part in iso_date.split("-"))
    named = re.search(rf"\b{_MONTHS[month - 1]}\b", text, re.IGNORECASE) is not None
    numbered = re.search(rf"(?<![\d-]){day}(?:st|nd|rd|th)?\b", text) is not None
    return named and numbered and (str(year) in text or not re.search(r"\b\d{4}\b", text))


def cited_photographs(body: Mapping[str, Any], by_blob: Mapping[str, int]) -> list[set[int]]:
    """For each clause, the registered photographs its citations resolve to, by the answer's own map.

    A token resolves to a permalink through the answer's ``citations``; the permalink names the
    photograph's blob, which the answer's own ``selection`` ties to a capture. A citation that
    resolves to no registered photograph is counted as photograph 0, so it cannot pass silently.
    """
    cited = []
    for clause in body["answer"]["clauses"]:
        photographs = set()
        for token in clause["citations"]:
            uri = body["citations"].get(token.strip().strip("[]"), "")
            blob = uri.removeprefix("exulanica://blob/").split("/img", 1)[0]
            photographs.add(by_blob.get(blob, 0))
        cited.append(photographs)
    return cited


def score(
    question: str,
    status: int,
    body: Any,
    *,
    place_entity_id: str,
    by_blob: Mapping[str, int],
    confirmed: set[int],
    dates: Mapping[int, str],
) -> dict[str, Any]:
    """The registered rule for one answer, applied mechanically: every condition and the verdict."""
    if status != 200 or not isinstance(body, dict):
        return {"right": False, "conditions": {"answered": False}}
    clauses = body["answer"]["clauses"]
    cited = cited_photographs(body, by_blob)
    historical = [
        (clause, photographs)
        for clause, photographs in zip(clauses, cited, strict=True)
        if clause["type"] == "historical"
    ]
    conditions: dict[str, bool] = {
        "answered": body.get("abstained") is None,
        "composed": body.get("deterministic") is False,
    }
    names = body.get("names") or {}
    if question == "sign":
        conditions["names_the_confirmed_place_citing_its_photograph"] = any(
            any(
                names.get(_canonical(placeholder)) == place_entity_id
                for placeholder in _PLACEHOLDER.findall(clause["text"])
            )
            and bool(photographs & confirmed)
            for clause, photographs in historical
        )
    elif question == "which":
        found = set().union(*(photographs for _, photographs in historical))
        conditions["cites_exactly_the_confirmed_photographs"] = found == confirmed
    elif question == "when":
        text = " ".join(clause["text"] for clause in clauses)
        for photograph in sorted(confirmed):
            conditions[f"states_photograph_{photograph}_date"] = _states_date(
                text, dates[photograph]
            )
        conditions["cites_a_confirmed_photograph"] = any(
            photographs & confirmed for _, photographs in historical
        )
    else:
        raise ValueError(f"no rule is registered for the question {question!r}")
    return {"right": all(conditions.values()), "conditions": conditions}


# -- one arm on a runtime --------------------------------------------------------------------------


def _record(path: str) -> dict[str, Any]:
    document = json.loads((ROOT / path).read_bytes())
    record = document["record"]
    if hashlib.sha256(canonical_json(record)).hexdigest() != document["record_sha256"]:
        raise SystemExit(f"{path} does not match its own digest")
    return record


def _usd(value: Any) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


def run(state_path: Path, photos: Path, arm: str, out: Path) -> None:
    from measure_vision_observations import Runtime

    registered = _record(PREREGISTRATION)
    runtime = Runtime(state_path)
    state = json.loads(state_path.read_text())
    steps: list[dict[str, Any]] = []
    spent = Decimal(0)

    def step(name: str, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        started = time.monotonic()
        status, response = runtime.call(method, path, body)
        wall = round((time.monotonic() - started) * 1000)
        steps.append(
            {
                "step": name,
                "request": f"{method} {path}",
                "body": body,
                "status": status,
                "wall_ms": wall,
                "response": response,
            }
        )
        print(f"{status}  {wall:>6} ms  {name}")
        return status, response

    photographs = registered["recipe"]["photographs"]
    uploaded: dict[int, dict[str, Any]] = {}
    for entry in photographs:
        path = photos / entry["file"]
        if _sha256(path.read_bytes()) != entry["sha256"]:
            raise SystemExit(f"{path} is not the registered photograph")
        status, response = runtime.upload(path)
        steps.append(
            {
                "step": f"upload {entry['file']}",
                "request": "POST /intake",
                "status": status,
                "response": response,
            }
        )
        if status != 202 or not response["accepted"]:
            raise SystemExit(f"{entry['file']} was not accepted: {status} {response}")
        uploaded[entry["photograph"]] = {**response["accepted"][0], "bytes": entry["bytes"]}

    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    at = (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    until = (now + dt.timedelta(days=1)).isoformat().replace("+00:00", "Z")
    status, admission = step(
        "detection permission and model rights, granted by the synthetic account holder",
        "POST",
        "/personal-admission",
        {
            "members": [
                {
                    "capture_id": capture["capture_id"],
                    "sha256": capture["blob_sha256"],
                    "bytes": capture["bytes"],
                    "review": "not-reviewed",
                    "edits": [],
                }
                for capture in uploaded.values()
            ],
            "purpose": registered["admission"]["purpose"],
            "authority": {
                "account_authority_basis": registered["admission"]["account_authority_basis"],
                "authorized_at": at,
                "valid_until": until,
            },
            "recorded_at": at,
            "operation": "detect",
            "model_rights": [
                {"role": role, "valid_until": until}
                for role in registered["admission"]["granted_roles"]
            ],
        },
    )
    if status != 202:
        raise SystemExit(f"admission refused: {status} {admission}")

    started = time.monotonic()
    terminal = runtime.await_job(admission["queued_job_id"])
    job_ms = round((time.monotonic() - started) * 1000)
    steps.append(
        {"step": "derivative job to a terminal event", "wall_ms": job_ms, "terminal": terminal}
    )
    print(f"job {terminal['event_type']} in {job_ms} ms")
    _, operations = step("workspace job metrics", "GET", "/operations/derivative-jobs")
    spent += _usd((operations or {}).get("cost", {}).get("usd_estimate"))

    by_capture = {capture["capture_id"]: number for number, capture in uploaded.items()}
    stored = runtime.vision_artifacts(list(by_capture))
    decisions = {}
    for capture_id, number in sorted(by_capture.items(), key=lambda item: item[1]):
        artifact = stored.get(capture_id) or {}
        check = artifact.get("place_check") or {}
        decisions[number] = {
            "capture_id": capture_id,
            "proposed_label": ((artifact.get("observation") or {}).get("proposed_place") or {}).get(
                "label"
            ),
            "outcome": check.get("outcome"),
            "written_label": check.get("written_label"),
            "place_check": check,
            "usage": (artifact.get("header") or {}).get("usage"),
        }
        print(
            f"   photograph {number}: {decisions[number]['outcome']} "
            f"{decisions[number]['written_label']!r}"
        )

    _, graph = step("read the graph", "GET", "/graph")
    occurrences = {
        occurrence["capture_id"]: occurrence
        for occurrence in graph["occurrences"]
        if occurrence["occurrence_class"] == "place"
    }
    written = [number for number, decision in decisions.items() if decision["outcome"] == "written"]
    if not written:
        raise SystemExit("no place was written, so there is nothing to confirm")
    first = decisions[written[0]]
    status, named = step(
        f"name photograph {written[0]}'s place {first['written_label']!r}, as the synthetic "
        "account holder",
        "POST",
        "/identity/name",
        {
            "occurrence_id": occurrences[first["capture_id"]]["occurrence_id"],
            "display_name": first["written_label"],
        },
    )
    if status != 200:
        raise SystemExit(f"naming refused: {status} {named}")
    for number in written[1:]:
        status, _ = step(
            f"confirm photograph {number} shows the same place",
            "POST",
            "/identity/confirm",
            {
                "occurrence_id": occurrences[decisions[number]["capture_id"]]["occurrence_id"],
                "entity_id": named["entity_id"],
            },
        )
        if status != 200:
            raise SystemExit(f"confirming photograph {number} was refused: {status}")
    _, catalogue = step("list the named entities", "GET", "/selection/catalogue")

    by_blob = {blob_id(capture["blob_sha256"]): number for number, capture in uploaded.items()}
    confirmed = set(written)
    dates = {entry["photograph"]: entry["captured_at_utc"][:10] for entry in photographs}
    answers = []
    for asked in registered["questions"]:
        question_id, question = asked["id"], asked["text"]
        if spent >= RUN_CEILING_USD:
            raise SystemExit(f"stopped before {question_id!r}: {spent} USD reported so far")
        status, body = step(
            f"ask {question_id}: {question}", "POST", "/selection/ask", {"question": question}
        )
        calls = (body or {}).get("execution", {}).get("calls", []) if status == 200 else []
        spent += sum((_usd(call.get("usd")) for call in calls), Decimal(0))
        verdict = score(
            question_id,
            status,
            body,
            place_entity_id=named["entity_id"],
            by_blob=by_blob,
            confirmed=confirmed,
            dates=dates,
        )
        answers.append(
            {
                "question_id": question_id,
                "question": question,
                "status": status,
                "clauses": (body or {}).get("answer", {}).get("clauses") if status == 200 else None,
                "names": (body or {}).get("names") if status == 200 else None,
                "abstained": (body or {}).get("abstained") if status == 200 else None,
                "deterministic": (body or {}).get("deterministic") if status == 200 else None,
                "execution": (body or {}).get("execution") if status == 200 else None,
                "plan": (body or {}).get("plan") if status == 200 else None,
                "score": verdict,
            }
        )
        print(f"      -> right={verdict['right']} {json.dumps(answers[-1]['clauses'])[:300]}")

    sources = {
        path: _sha256((Path(state["worktree"]) / path).read_bytes())
        for path in ("exulanica/selection/question.py", "exulanica/selection/packet.py")
    }
    out.write_text(
        json.dumps(
            {
                "arm": arm,
                "runtime": {
                    key: state.get(key)
                    for key in ("worktree", "tree", "slot", "workspace_id", "run_id")
                },
                "sources_sha256": sources,
                "uploaded": uploaded,
                "decisions": decisions,
                "named": named,
                "catalogue": catalogue,
                "confirmed_photographs": sorted(confirmed),
                "answers": answers,
                "operations": operations,
                "reported_usd": str(spent),
                "steps": steps,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )
    print(f"wrote {out}; {spent} USD reported")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    drawing = commands.add_parser("draw")
    drawing.add_argument("out")
    running = commands.add_parser("run")
    running.add_argument("--state", required=True)
    running.add_argument("--photos", required=True)
    running.add_argument("--arm", choices=("before", "after"), required=True)
    running.add_argument("--out", required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "draw":
        for entry in draw(Path(arguments.out)):
            print(f"{entry['file']}  {entry['sha256']}  {entry['captured_at_utc']}")
    elif arguments.command == "run":
        run(Path(arguments.state), Path(arguments.photos), arguments.arm, Path(arguments.out))


if __name__ == "__main__":
    main()
