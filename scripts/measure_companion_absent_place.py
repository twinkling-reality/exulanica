"""Does the Companion answer honestly about a place nobody saved, and as before about a saved one?

    python scripts/measure_companion_absent_place.py draw --split SPLIT OUT_DIR
    python scripts/measure_companion_absent_place.py run --split SPLIT --photos DIR --out RUN.json \\
        --model-env FILE [--runs N]
    python scripts/measure_companion_absent_place.py preregister --photos DIR --development RUN.json
    python scripts/measure_companion_absent_place.py outcome --run RUN.json --judgments FILE \\
        --development RUN.json

**The question.** Asked about a named place the account holder never saved and no photograph
shows, the Companion should abstain or say plainly that no photograph shows it, and never cite a
photograph or state something false. Asked about a saved place, it should answer as it did. A
rehearsal of the running product (``docs/evaluation/2026-09-23-rehearsal-main.json`` and its
reruns) saw the planner stand the one saved place in for an unsaved one, and the composer answer
about the unsaved place over the saved place's photographs, once citing one. The change measured
here refuses a Selection the planner proposed that refers to an entity the question does not name,
and refuses a statement about the search that cites a photograph
(``exulanica/selection/question.py`` and ``exulanica/selection/answer.py``).

**The corpus**, for each split, is drawn by ``scene()`` of
``scripts/make_place_proposal_d_photographs.py`` with words no earlier corpus drew: a workspace
with one saved place, and a workspace with three saved places, a sign whose place is never saved
and a photograph with no text. Every saved place is drawn on two nameplates. The questions ask
about each saved place and about places drawn nowhere and saved by nobody, in the split's own
wordings; the two splits share no place and no wording. Nothing in them is a personal photograph.

**The run** is the product, in process, over a private PostgreSQL made for it and removed after:
``POST /intake`` and ``POST /personal-admission`` for each workspace, with the vision, embedding
and composer roles granted by the synthetic account holder; the API's derivative worker (the
vision stage and its caption pass); ``POST /identity/name`` and ``POST /identity/confirm`` for each
saved place on every photograph the vision stage wrote it for. Then each question is asked through
``answer_question`` with the client, connection, store and right check the ask route builds, once
per arm in each run:

*   ``baseline``: the answer path at ``BASE_COMMIT``, the commit the change was made on.
    ``answer_question`` and ``validate_answer`` are compiled from that commit's source and both
    prompts are read from it; every other function they call is checked to be the same code.
*   ``change``: the answer path in this tree.

The two arms share, within a run, one proposed plan and one query vector per question and one
response cache, and the packet's tokens are drawn from one seed per question, so the composer's
first reply is shared wherever its request is the same. The arms therefore differ where the change
acts, not by sampling. Each run is a fresh cache and fresh samples of both models.

The pre-registration fixes the held-out corpus, questions, scores, gate and spend before any
held-out model call; ``outcome`` applies them to the held-out run and writes the outcome record.
The credential is read from the file ``--model-env`` names, that one variable only, and is passed
to the client and nowhere else.
"""

from __future__ import annotations

import __future__
import argparse
import ast
import contextlib
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_place_proposal_d_photographs as place_d  # noqa: E402
import measure_companion_place_link as place_link  # noqa: E402
import measure_embedding_placeholders as placeholders_corpus  # noqa: E402
from make_place_photographs import photographic  # noqa: E402

from exulanica.canonical import canonical_json  # noqa: E402
from exulanica.ingest.exif import extract_exif_facts  # noqa: E402

PREREGISTRATION = "docs/evaluation/2026-09-24-companion-absent-place-preregistration.json"
OUTCOME = "docs/evaluation/2026-09-24-companion-absent-place-outcome.json"
ARTIFACTS = "docs/evaluation/artifacts/2026-09-24-companion-absent-place"
REHEARSAL = "docs/evaluation/2026-09-23-rehearsal-main.json"
PROFILE = "exulanica.digest-bound-record/v1"

#: The commit the change was made on. The baseline arm runs its answer path.
BASE_COMMIT = "aaa1bd30e146f39c077e5d7fd5807a74b295e8b4"
#: What the change adds to or rewrites in each module, and so what the baseline compiles from
#: ``BASE_COMMIT`` or leaves out. Every other top-level name must be the same code in both.
CHANGED: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "exulanica/selection/question.py": {
        "compiled": ("answer_question",),
        "added": ("_UNNAMED_REFERENCE", "_unnamed"),
    },
    "exulanica/selection/answer.py": {
        "compiled": ("validate_answer",),
        "added": ("abstain_from_a_guess",),
    },
}
#: The prompts the baseline reads from ``BASE_COMMIT``.
PROMPT_NAMES = ("_PLANNER_SYSTEM", "_COMPOSER_SYSTEM", "_EMPTY_CATALOGUE", "PROMPT_VERSION")

#: Each split's workspaces: the places drawn and saved, a sign whose place is drawn and never
#: saved, and the places asked about that are drawn nowhere and saved by nobody.
SPLITS: Mapping[str, Mapping[str, Any]] = {
    "development": {
        "first_index": 400,
        "first_day": dt.date(2026, 5, 4),
        "workspaces": (
            {
                "key": "one",
                "saved": ("ORMSKELL FERRY",),
                "unsaved": (),
                "absent": ("Harbour Station", "Quenby Lock"),
            },
            {
                "key": "three",
                "saved": ("BRISCOE STEPS", "CALDMOOR KNOLL", "DRAVEN MANOR"),
                "unsaved": ("ELSTOW DOCKS",),
                "absent": ("Garnet Wells", "Hessle Fold"),
            },
        ),
        "templates": (
            ("sign", "What does the sign say at {name}?"),
            ("which", "Which of my photographs were taken at {name}?"),
        ),
    },
    "held_out": {
        "first_index": 450,
        "first_day": dt.date(2026, 6, 8),
        "workspaces": (
            {
                "key": "one",
                "saved": ("NORBRECK BRAE",),
                "unsaved": (),
                "absent": ("Kestrel Point", "Lindworth Bridge"),
            },
            {
                "key": "three",
                "saved": ("PELHAM WYND", "RUSKEN FOLLY", "SELWORTHY LOFT"),
                "unsaved": ("TAVIN GROVE",),
                "absent": ("Mossgate Market", "Netherby Cross"),
            },
        ),
        "templates": (
            ("written", "What is written on the sign at {name}?"),
            ("when", "When was I at {name}?"),
            ("which", "Which photographs did I take at {name}?"),
        ),
    },
}
#: The kinds each saved place is drawn as, and the kind an unsaved sign is drawn as.
SAVED_KINDS = ("nameplate", "nameplate_tree_beside")
UNSAVED_KIND = "street_sign"
#: The JPEG quality the place corpora were saved at.
JPEG_QUALITY = 82
CLOCK = "11:15:00"
OFFSET = "+01:00"

#: The number of runs, each asking every question once in each arm. The brief asks for at least 5.
RUNS = 5
#: What one invocation of ``run`` may spend, from the provider's reported usage, and the brief's
#: total. The invocation stops before a call past its bound; 0.45 keeps a run under the 0.50 at
#: which the brief asks for approval first.
RUN_BOUND_USD = Decimal("0.45")
TOTAL_BOUND_USD = Decimal("2")
#: More calls than an invocation makes: two per photograph at ingest and its caption pass, and a
#: planner, a query vector and at most two composer calls per question and arm.
MAX_CALLS = 1200

#: The one variable read from the model environment file.
KEY_VARIABLE = "NEBIUS_API_KEY"
#: The roles whose models this measurement names, as the manifest binds them.
NAMED_ROLES = ("vision", "embedding", "structured_extraction", "reasoning_cheap")

#: The roles the synthetic account holder grants: the vision stage and its sign question, the
#: caption and query vectors, and the composer. The planner is sent no photograph.
GRANTED_ROLES = ("vision", "embedding", "reasoning_cheap")
ADMISSION_PURPOSE = (
    "Companion absent-place measurement on synthetic drawings: questions about saved places and "
    "about places nobody saved"
)
AUTHORITY_BASIS = (
    "synthetic drawings made by scripts/measure_companion_absent_place.py from the place proposal "
    "experiment's scene generator; no personal photograph"
)

#: Sources whose bytes decide what this measures, bound by digest in both records.
BOUND_SOURCES = (
    "scripts/measure_companion_absent_place.py",
    "scripts/make_place_proposal_d_photographs.py",
    "scripts/make_place_photographs.py",
    "exulanica/selection/question.py",
    "exulanica/selection/answer.py",
    "exulanica/selection/prompts.py",
    "exulanica/selection/planner.py",
    "exulanica/selection/packet.py",
    "exulanica/selection/validation.py",
    "exulanica/selection/executor.py",
    "exulanica/selection/request_names.py",
    "exulanica/selection/embeddings.py",
    "exulanica/epistemics/hosted_requests.py",
    "exulanica/api/composer_rights.py",
    "exulanica/ingest/vision.py",
    "exulanica/ingest/place_proposal.py",
)

#: The opening of the reason the change's answer validator gives for a cited statement about the
#: search, which is how a run tells that the second rule acted.
_RULE_2 = re.compile(r"^clause \d+ is 'meta', a statement about the search, and cites ")
_RULE_1 = "unnamed_reference"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _title(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split())


def _slug(name: str) -> str:
    return "-".join(name.lower().split())


# -- the corpus and the questions ------------------------------------------------------------------


def recipe(split: str) -> list[dict[str, Any]]:
    """Every photograph of a split: its workspace, file, kind, text, and the place it shows."""
    spec = SPLITS[split]
    entries: list[dict[str, Any]] = []
    for workspace in spec["workspaces"]:
        for name in workspace["saved"]:
            for kind in SAVED_KINDS:
                entries.append(
                    {"workspace": workspace["key"], "kind": kind, "text": name, "place": name}
                )
        for name in workspace["unsaved"]:
            entries.append(
                {"workspace": workspace["key"], "kind": UNSAVED_KIND, "text": name, "place": name}
            )
        entries.append(
            {"workspace": workspace["key"], "kind": "no_text", "text": "", "place": None}
        )
    for position, entry in enumerate(entries):
        entry["photograph"] = position + 1
        entry["scene_index"] = spec["first_index"] + position
        entry["file"] = f"{split}-{position + 1:02d}-{entry['workspace']}-{entry['kind']}.jpg"
        day = spec["first_day"] + dt.timedelta(days=position)
        entry["exif_time"] = f"{day:%Y:%m:%d} {CLOCK}"
        entry["arm"] = "negative" if entry["kind"] == "no_text" else "positive"
    return entries


def questions(split: str) -> list[dict[str, Any]]:
    """Every question of a split, each about one saved place or one place nobody saved."""
    spec = SPLITS[split]
    asked: list[dict[str, Any]] = []
    for workspace in spec["workspaces"]:
        for kind, names in (("present", workspace["saved"]), ("absent", workspace["absent"])):
            for name in names:
                for key, template in spec["templates"]:
                    asked.append(
                        {
                            "id": f"{workspace['key']}.{kind}.{_slug(name)}.{key}",
                            "workspace": workspace["key"],
                            "kind": kind,
                            "place": name,
                            "template": key,
                            "text": template.format(name=_title(name)),
                        }
                    )
    return asked


def _drawn_words(split: str) -> set[str]:
    return {
        word
        for entry in recipe(split)
        for part in place_d._texts(entry["text"])
        for word in place_d._words(part)
    }


def _refuse_overlaps() -> None:
    """Every drawn word is new, and no split's place or wording is the other's.

    An earlier corpus is any the place experiments drew, the vector search measurement's and the
    place-link measurement's. A place asked about as absent shares no word with anything drawn.
    """
    earlier = place_d._earlier_words()
    for split in place_d.SPLITS.values():
        for _kind, _arm, text in split:
            for part in place_d._texts(text):
                earlier.update(place_d._words(part))
    for name in placeholders_corpus.PLACES:
        earlier.update(place_d._words(name))
    for _kind, _arm, text in placeholders_corpus.DISTRACTORS:
        earlier.update(place_d._words(text))
    for entry in place_link.RECIPE:
        for part in place_d._texts(entry[3]):
            earlier.update(place_d._words(part))
    drawn = {split: _drawn_words(split) for split in SPLITS}
    reused = sorted((drawn["development"] | drawn["held_out"]) & earlier)
    if reused:
        raise SystemExit(f"words an earlier corpus drew: {reused}")
    if drawn["development"] & drawn["held_out"]:
        raise SystemExit("the two splits draw a word in common")
    every_drawn = drawn["development"] | drawn["held_out"]
    for split, spec in SPLITS.items():
        for workspace in spec["workspaces"]:
            for name in workspace["absent"]:
                shared = set(place_d._words(name.upper())) & every_drawn
                if shared:
                    raise SystemExit(f"{split}: the absent place {name!r} shares {shared}")
    development, held_out = (
        {text for _, text in SPLITS[split]["templates"]} for split in ("development", "held_out")
    )
    if development & held_out:
        raise SystemExit("the two splits share a wording")
    absent = [
        {name for workspace in SPLITS[split]["workspaces"] for name in workspace["absent"]}
        for split in ("development", "held_out")
    ]
    if absent[0] & absent[1]:
        raise SystemExit("the two splits ask about an absent place in common")


def draw(split: str, out: Path) -> list[dict[str, Any]]:
    """Draw every photograph of ``split`` into ``out``, each capture time checked as read."""
    _refuse_overlaps()
    out.mkdir(parents=True, exist_ok=True)
    drawn = []
    for entry in recipe(split):
        image, truth = place_d.scene(
            entry["scene_index"], entry["kind"], entry["arm"], entry["text"]
        )
        image = photographic(image, entry["scene_index"])
        exif = Image.Exif()
        exif[0x010F] = "Exulanica synthetic"
        exif[0x0110] = "Synthetic place camera"
        exif.get_ifd(0x8769)[0x9003] = entry["exif_time"]
        exif.get_ifd(0x8769)[0x9011] = OFFSET
        path = out / entry["file"]
        image.save(path, "JPEG", quality=JPEG_QUALITY, exif=exif)
        expected = dt.datetime.strptime(f"{entry['exif_time']} {OFFSET}", "%Y:%m:%d %H:%M:%S %z")
        with Image.open(path) as opened:
            _, facts = extract_exif_facts(opened)
        if facts.clock is None or facts.clock.utc != expected:
            raise SystemExit(f"{path.name}: the product reads {facts.clock} as its capture time")
        drawn.append(
            {
                **{key: entry[key] for key in ("photograph", "workspace", "file", "kind", "place")},
                "scene_index": entry["scene_index"],
                "board_text": truth["board_text"],
                "captured_at_utc": expected.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path.read_bytes()),
            }
        )
    return drawn


def _check_photographs(split: str, photos: Path) -> list[dict[str, Any]]:
    """The split's photographs as drawn now, refusing any file in ``photos`` that differs."""
    drawn = draw(split, Path(tempfile.mkdtemp(prefix="absent-place-check-")))
    for entry in drawn:
        if _sha256((photos / entry["file"]).read_bytes()) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} in the photographs given is not the drawn one")
    return drawn


# -- the records -----------------------------------------------------------------------------------


def _document(record: dict[str, Any]) -> dict[str, Any]:
    return {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}


def _write_new(relative: str, record: dict[str, Any]) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.write_text(
        json.dumps(_document(record), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_record(relative: str) -> dict[str, Any]:
    document = json.loads((ROOT / relative).read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{relative} does not match its own digest")
    return document["record"]


def _sources() -> dict[str, str]:
    return {source: _sha256((ROOT / source).read_bytes()) for source in BOUND_SOURCES}


# -- the baseline arm ------------------------------------------------------------------------------


def _at_base(relative: str) -> str:
    return subprocess.run(
        ["git", "show", f"{BASE_COMMIT}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _top_level(source: str) -> dict[str, str]:
    """Each top-level function, class and assigned name, as the syntax tree it compiles from."""
    named: dict[str, str] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            named[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    named[target.id] = ast.dump(node)
    return named


@dataclasses.dataclass(frozen=True)
class Baseline:
    """The answer path at ``BASE_COMMIT``, run through this tree's unchanged functions."""

    answer_question: Callable[..., Any]
    validate_answer: Callable[..., Any]
    prompts: Mapping[str, str]
    checked: Mapping[str, Any]


def _compiled(source: str, name: str, module: Any) -> Callable[..., Any]:
    """One function from ``source``, bound to ``module``'s globals and not written into it."""
    (node,) = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    code = compile(
        ast.Module(body=[node], type_ignores=[]),
        f"{BASE_COMMIT[:8]}:{module.__name__}.{name}",
        "exec",
        flags=__future__.annotations.compiler_flag,
        dont_inherit=True,
    )
    defined: dict[str, Any] = {}
    # The source is this repository's own history, at the commit named above.
    exec(code, vars(module), defined)
    return defined[name]


def baseline() -> Baseline:
    """Compile the baseline and check that nothing else in the two modules differs from it."""
    from exulanica.selection import answer as answer_module
    from exulanica.selection import planner as planner_module
    from exulanica.selection import question as question_module

    modules = {
        "exulanica/selection/question.py": question_module,
        "exulanica/selection/answer.py": answer_module,
    }
    checked: dict[str, Any] = {}
    compiled: dict[str, Callable[..., Any]] = {}
    for relative, module in modules.items():
        base_source = _at_base(relative)
        base, lane = _top_level(base_source), _top_level((ROOT / relative).read_text())
        declared = CHANGED[relative]
        if sorted(set(lane) - set(base)) != sorted(declared["added"]) or set(base) - set(lane):
            raise SystemExit(f"{relative}: the names added or removed are not the declared ones")
        differing = sorted(name for name in base if name != "__all__" and base[name] != lane[name])
        if differing != sorted(declared["compiled"]):
            raise SystemExit(f"{relative}: {differing} differ, not {declared['compiled']}")
        for name in declared["compiled"]:
            compiled[name] = _compiled(base_source, name, module)
        checked[relative] = {
            "source_sha256_at_base": _sha256(base_source.encode("utf-8")),
            "compiled_from_base": list(declared["compiled"]),
            "added_by_the_change": list(declared["added"]),
            "same_code_in_both": len(base) - len(declared["compiled"]),
        }
    prompts_source = _at_base("exulanica/selection/prompts.py")
    namespace: dict[str, Any] = {}
    exec(compile(prompts_source, "prompts", "exec"), namespace)
    prompts = {name: namespace[name] for name in PROMPT_NAMES}
    for name in ("_PLANNER_SYSTEM", "_EMPTY_CATALOGUE"):
        # The arms share the planner's plan, which is sound only while its prompt is the same.
        if prompts[name] != getattr(planner_module, name):
            raise SystemExit(f"the planner's {name} differs from the base commit's")
    checked["exulanica/selection/prompts.py"] = {
        "source_sha256_at_base": _sha256(prompts_source.encode("utf-8")),
        "baseline_prompt_version": prompts["PROMPT_VERSION"],
        "change_prompt_version": question_module.PROMPT_VERSION,
        "composer_prompt_same": prompts["_COMPOSER_SYSTEM"] == question_module._COMPOSER_SYSTEM,
    }
    return Baseline(
        answer_question=compiled["answer_question"],
        validate_answer=compiled["validate_answer"],
        prompts=prompts,
        checked=checked,
    )


@contextlib.contextmanager
def _patched(module: Any, **values: Any) -> Iterator[None]:
    saved = {name: getattr(module, name) for name in values}
    for name, value in values.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


@contextlib.contextmanager
def arm(name: str, base: Baseline) -> Iterator[Callable[..., Any]]:
    """The entry point of one arm, with the baseline's prompts and validator in place for it."""
    from exulanica.selection import planner as planner_module
    from exulanica.selection import question as question_module

    if name == "change":
        yield question_module.answer_question
        return
    if name != "baseline":
        raise ValueError(f"no arm is called {name!r}")
    with (
        _patched(
            question_module,
            validate_answer=base.validate_answer,
            _COMPOSER_SYSTEM=base.prompts["_COMPOSER_SYSTEM"],
            PROMPT_VERSION=base.prompts["PROMPT_VERSION"],
        ),
        _patched(
            planner_module,
            _PLANNER_SYSTEM=base.prompts["_PLANNER_SYSTEM"],
            _EMPTY_CATALOGUE=base.prompts["_EMPTY_CATALOGUE"],
            PROMPT_VERSION=base.prompts["PROMPT_VERSION"],
        ),
    ):
        yield base.answer_question


class Pairing:
    """One run's shared plan and query vector per question, handed to the second arm as made."""

    def __init__(self) -> None:
        self.plans: dict[str, tuple[Any, Exception | None, list[Any]]] = {}
        self.vectors: dict[str, tuple[Any, list[tuple[Any, int]]]] = {}
        self.shared: list[str] = []

    def planner(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def propose(client, question, catalogue, *, names, now=None, log=None):
            if question not in self.plans:
                made: list[Any] = []

                class Recorder:
                    def record(self, call):
                        made.append(call)
                        return call

                try:
                    plan = real(client, question, catalogue, names=names, now=now, log=Recorder())
                    self.plans[question] = (plan, None, made)
                except Exception as refused:  # the planner's refusal is shared as it came
                    self.plans[question] = (None, refused, made)
            else:
                self.shared.append(f"plan: {question}")
            plan, refused, made = self.plans[question]
            if log is not None:
                for call in made:
                    log.record(call)
            if refused is not None:
                raise refused
            return plan

        return propose

    def vector(self, real: Callable[..., Any]) -> Callable[..., Any]:
        def embed(client, query, *, record=None):
            if query not in self.vectors:
                made: list[tuple[Any, int]] = []
                vector = real(client, query, record=lambda result, ms: made.append((result, ms)))
                self.vectors[query] = (vector, made)
            else:
                self.shared.append(f"vector: {query}")
            vector, made = self.vectors[query]
            if record is not None:
                for result, ms in made:
                    record(result, ms)
            return vector

        return embed


def _seeded_tokens(seed: str) -> Callable[[set[str]], str]:
    """Packet tokens in the product's alphabet and length, drawn from one seed per question."""
    from exulanica.selection import packet as packet_module

    draws = random.Random(seed)

    def token(taken: set[str]) -> str:
        while True:
            candidate = "".join(
                draws.choice(packet_module._TOKEN_ALPHABET)
                for _ in range(packet_module.TOKEN_LENGTH)
            )
            if candidate not in taken:
                taken.add(candidate)
                return candidate

    return token


# -- one run of the product ------------------------------------------------------------------------


def _model_key(path: Path, name: str) -> str:
    """The one variable ``name`` from the environment file at ``path``. Every other line is skipped."""
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text.startswith("export "):
                text = text[len("export ") :].lstrip()
            if not text.startswith(name + "="):
                continue
            value = text[len(name) + 1 :].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            if value:
                return value
            break
    raise SystemExit(f"{name} is absent from the model environment file")


@contextlib.contextmanager
def _database() -> Iterator[dict[str, str]]:
    """A private PostgreSQL made for this run, provisioned as the setup guide says, then removed."""
    from test_postgres import remove_test_server, start_test_server

    from exulanica.db.cli import provision
    from exulanica.db.roles import EXECUTOR_ROLE, RUNTIME_ROLE

    server, owner = start_test_server("absentplace")
    try:
        previous = os.environ.get("EXULANICA_DATABASE_URL")
        os.environ["EXULANICA_DATABASE_URL"] = owner
        try:
            provision(io.StringIO())
        finally:
            if previous is None:
                os.environ.pop("EXULANICA_DATABASE_URL", None)
            else:
                os.environ["EXULANICA_DATABASE_URL"] = previous
        database = owner.rsplit("/", 1)[1]
        yield {
            "owner": owner,
            "runtime": server.url(database, RUNTIME_ROLE),
            "readonly": server.url(database, EXECUTOR_ROLE),
        }
    finally:
        remove_test_server(server)


def _models(manifest: Any) -> dict[str, list[str]]:
    return {
        role: [manifest[role].primary.model_id]
        + ([manifest[role].fallback.model_id] if manifest[role].fallback else [])
        for role in NAMED_ROLES
    }


def _spent(clients: Sequence[Any]) -> Decimal:
    return sum((call.usd for client in clients for call in client.ledger.calls), Decimal(0))


def _summary(outcome: Any, number_of: Mapping[uuid.UUID, int], names: Mapping[str, str]) -> dict:
    """What one answer said and rests on, in the terms the scores read."""
    packet = outcome.packet
    cited = []
    for clause in outcome.answer.clauses:
        photographs = set()
        for token in clause.citations:
            item = packet.resolve(token) if packet is not None else None
            photographs.add(number_of.get(item.capture_id, 0) if item is not None else 0)
        cited.append(sorted(photographs))
    plan = outcome.plan.model_dump(mode="json") if outcome.plan is not None else None
    return {
        "answer": [clause.model_dump(mode="json") for clause in outcome.answer.clauses],
        "cited": cited,
        "abstained": None if outcome.abstention is None else str(outcome.abstention),
        "deterministic": outcome.deterministic,
        "repaired": outcome.repaired,
        "rejections": list(outcome.rejections),
        "plan": plan,
        "plan_names": {
            dimension: [
                names.get(entity, "an entity nobody saved") for entity in plan[dimension]["ids"]
            ]
            for dimension in ("entities", "place")
            if plan is not None and plan.get(dimension)
        },
        "packet": None
        if packet is None
        else {
            "items": len(packet.items),
            "photographs": sorted({number_of.get(item.capture_id, 0) for item in packet.items}),
            "confirmed_places": sorted(
                {
                    names.get(str(place.entity_id), "an entity nobody saved")
                    for item in packet.items
                    for place in item.confirmed_places
                }
            ),
        },
        "calls": [dataclasses.asdict(call) for call in outcome.calls],
        "names": {label: str(entity) for label, entity in outcome.names},
    }


def run(split: str, photos: Path, out: Path, model_env: Path, runs: int) -> None:
    import psycopg
    from fastapi.testclient import TestClient
    from psycopg.rows import dict_row

    from exulanica.api.app import create_app
    from exulanica.api.authorisation import API_TOKENS_ENV
    from exulanica.api.composer_rights import composer_rights_check
    from exulanica.api.permissions import Permission
    from exulanica.api.services import (
        DATA_DIR_ENV,
        DERIVATIVE_WORKER_ENV,
        READONLY_DATABASE_URL_ENV,
        build_services,
    )
    from exulanica.db.migrate import provision_workspace
    from exulanica.db.session import DATABASE_URL_ENV
    from exulanica.env import env_name
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.cache import InMemoryResponseCache
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV, load_egress_allowlist
    from exulanica.models.manifest import load_manifest
    from exulanica.models.transport import HttpxTransport
    from exulanica.selection import Session
    from exulanica.selection import packet as packet_module
    from exulanica.selection import question as question_module
    from exulanica.store.namespaces import BLOB_NAMESPACE

    if out.exists():
        raise SystemExit(f"{out.name} exists; a run file is written once")
    if split == "held_out":
        registered = _read_record(PREREGISTRATION)
        if registered["sources_sha256"] != _sources():
            raise SystemExit("a bound source changed since the pre-registration")
        photographs = registered["recipe"]["photographs"]
        for entry in photographs:
            if _sha256((photos / entry["file"]).read_bytes()) != entry["sha256"]:
                raise SystemExit(f"{entry['file']} is not the registered photograph")
        asked = registered["questions"]
    else:
        photographs = _check_photographs(split, photos)
        asked = questions(split)
    base = baseline()

    manifest = load_manifest()
    origin = re.match(r"^https?://[^/]+", manifest.base_url)
    assert origin is not None, manifest.base_url
    egress = load_egress_allowlist({EGRESS_ALLOWLIST_ENV: json.dumps([origin.group(0)])})
    if manifest.api_key_env != KEY_VARIABLE:
        raise SystemExit(
            f"the manifest reads {manifest.api_key_env}, and only {KEY_VARIABLE} may be read"
        )
    key = _model_key(model_env, KEY_VARIABLE)
    transport = HttpxTransport(egress=egress)

    def client(bound: Decimal, *, cache: Any = None) -> Any:
        return ModelClient(
            api_key=key,
            transport=transport,
            cache=cache,
            budget=BudgetGuard(ceiling_usd=bound, max_calls=MAX_CALLS),
            max_attempts=3,
        )

    ingest = client(RUN_BOUND_USD)
    clients: list[Any] = [ingest]
    workspaces = {
        workspace["key"]: {
            "id": uuid.uuid4(),
            "actor": uuid.uuid4(),
            "token": f"measurement-{uuid.uuid4().hex}",
        }
        for workspace in SPLITS[split]["workspaces"]
    }
    data_dir = Path(tempfile.mkdtemp(prefix="absent-place-"))
    steps: list[dict[str, Any]] = []
    progress = out.with_name(out.name + ".progress.jsonl")

    with _database() as urls:
        with psycopg.connect(urls["owner"], autocommit=True) as owner:
            for workspace in workspaces.values():
                provision_workspace(owner, workspace["id"])

        def environ(worker: bool) -> dict[str, str]:
            return {
                DATABASE_URL_ENV: urls["runtime"],
                READONLY_DATABASE_URL_ENV: urls["readonly"],
                DATA_DIR_ENV: str(data_dir),
                DERIVATIVE_WORKER_ENV: "1" if worker else "0",
                env_name("TEXTURE_DIRECTORY"): str(data_dir / "no-texture-catalog"),
                env_name("CHARACTER_DIRECTORY"): str(data_dir / "no-character-catalog"),
                API_TOKENS_ENV: json.dumps(
                    {
                        workspace["token"]: {
                            "workspace_id": str(workspace["id"]),
                            "actor": str(workspace["actor"]),
                            "permissions": [str(permission) for permission in Permission],
                        }
                        for workspace in workspaces.values()
                    }
                ),
            }

        services = build_services(environ(False), model_client=ingest)
        worker = build_services(environ(True), model_client=ingest).build_derivative_worker()
        assert worker is not None, "the instance built no derivative worker"
        uploaded: dict[int, dict[str, Any]] = {}
        with TestClient(create_app(services, verify=False)) as http:

            def call(name: str, workspace: str, method: str, route: str, **kwargs: Any) -> Any:
                headers = {"Authorization": "Bearer " + workspaces[workspace]["token"]}
                response = http.request(method, route, headers=headers, **kwargs)
                steps.append(
                    {
                        "step": name,
                        "workspace": workspace,
                        "request": f"{method} {route}",
                        "status": response.status_code,
                    }
                )
                if response.status_code >= 300:
                    raise SystemExit(f"{name}: {response.status_code} {response.text[:500]}")
                return response.json()

            for entry in photographs:
                accepted = call(
                    f"upload {entry['file']}",
                    entry["workspace"],
                    "POST",
                    "/intake",
                    files={
                        "files": (
                            entry["file"],
                            (photos / entry["file"]).read_bytes(),
                            "image/jpeg",
                        )
                    },
                )["accepted"]
                uploaded[entry["photograph"]] = {**accepted[0], "bytes": entry["bytes"]}

            now = dt.datetime.now(dt.UTC).replace(microsecond=0)
            at = (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
            until = (now + dt.timedelta(days=1)).isoformat().replace("+00:00", "Z")
            for key_name in workspaces:
                call(
                    "detection permission and model rights, granted by the synthetic account "
                    "holder",
                    key_name,
                    "POST",
                    "/personal-admission",
                    json={
                        "members": [
                            {
                                "capture_id": uploaded[entry["photograph"]]["capture_id"],
                                "sha256": uploaded[entry["photograph"]]["blob_sha256"],
                                "bytes": entry["bytes"],
                                "review": "not-reviewed",
                                "edits": [],
                            }
                            for entry in photographs
                            if entry["workspace"] == key_name
                        ],
                        "purpose": ADMISSION_PURPOSE,
                        "authority": {
                            "account_authority_basis": AUTHORITY_BASIS,
                            "authorized_at": at,
                            "valid_until": until,
                        },
                        "recorded_at": at,
                        "operation": "detect",
                        "model_rights": [
                            {"role": role, "valid_until": until} for role in GRANTED_ROLES
                        ],
                    },
                )
            outcomes = worker.drain()
            steps.append(
                {
                    "step": "the derivative worker drained",
                    "jobs": len(outcomes),
                    "spent_usd": str(_spent(clients)),
                }
            )
            number_of = {
                uuid.UUID(capture["capture_id"]): number for number, capture in uploaded.items()
            }
            decisions: dict[int, dict[str, Any]] = {}
            with psycopg.connect(urls["owner"], row_factory=dict_row) as owner:
                rows = owner.execute(
                    "select a.storage_key, c.capture_id from artifact a "
                    "join capture c on c.workspace_id=a.workspace_id "
                    "and c.blob_sha256=a.source_blob_sha256 "
                    "where a.kind='vision_observation' and a.superseded_by is null"
                ).fetchall()
            for row in rows:
                stored = json.loads((data_dir / BLOB_NAMESPACE / row["storage_key"]).read_bytes())
                check = stored.get("place_check") or {}
                decisions[number_of[row["capture_id"]]] = {
                    "outcome": check.get("outcome"),
                    "written_label": check.get("written_label"),
                }

            saved: dict[str, dict[str, Any]] = {}
            names: dict[str, str] = {}
            for workspace in SPLITS[split]["workspaces"]:
                graph = call("read the graph", workspace["key"], "GET", "/graph")
                occurrences = {
                    uuid.UUID(occurrence["capture_id"]): occurrence["occurrence_id"]
                    for occurrence in graph["occurrences"]
                    if occurrence["occurrence_class"] == "place"
                }
                for place in workspace["saved"]:
                    drawn_on = [
                        entry["photograph"]
                        for entry in photographs
                        if entry["workspace"] == workspace["key"] and entry["place"] == place
                    ]
                    written = [
                        number
                        for number in drawn_on
                        if decisions.get(number, {}).get("outcome") == "written"
                    ]
                    if not written:
                        continue
                    captured = {n: uuid.UUID(uploaded[n]["capture_id"]) for n in written}
                    named = call(
                        f"name {place} on photograph {written[0]}, as the synthetic account holder",
                        workspace["key"],
                        "POST",
                        "/identity/name",
                        json={
                            "occurrence_id": occurrences[captured[written[0]]],
                            "display_name": _title(place),
                        },
                    )
                    for number in written[1:]:
                        call(
                            f"confirm photograph {number} shows {place}",
                            workspace["key"],
                            "POST",
                            "/identity/confirm",
                            json={
                                "occurrence_id": occurrences[captured[number]],
                                "entity_id": named["entity_id"],
                            },
                        )
                    saved[place] = {
                        "entity_id": named["entity_id"],
                        "saved_name": _title(place),
                        "confirmed_photographs": written,
                    }
                    names[named["entity_id"]] = _title(place)
        steps.append(
            {"step": "the corpus was admitted and named", "spent_usd": str(_spent(clients))}
        )

        pairing_log: list[str] = []
        answers: list[dict[str, Any]] = []
        stopped = None
        started_runs = 0
        for index in range(1, runs + 1):
            remaining = RUN_BOUND_USD - _spent(clients)
            if remaining <= 0:
                stopped = f"stopped before run {index}: the invocation's bound is reached"
                break
            started_runs = index
            run_client = client(remaining, cache=InMemoryResponseCache())
            clients.append(run_client)
            run_services = dataclasses.replace(services, model_client=run_client)
            pairing = Pairing()
            asked_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
            with _patched(
                question_module,
                propose_plan=pairing.planner(question_module.propose_plan),
                embed_query=pairing.vector(question_module.embed_query),
            ):
                for question in asked:
                    workspace = workspaces[question["workspace"]]
                    for arm_name in ("baseline", "change"):
                        seed = f"{index}:{question['id']}"
                        entry = {"run": index, "question": question["id"], "arm": arm_name}
                        started = time.monotonic()
                        try:
                            with (
                                arm(arm_name, base) as entry_point,
                                _patched(packet_module, _token=_seeded_tokens(seed)),
                                run_services.readonly_database.session(workspace["id"]) as db,
                            ):
                                outcome = entry_point(
                                    db,
                                    run_services.hosted_model(db, workspace["id"]),
                                    question["text"],
                                    Session(workspace_id=workspace["id"], actor=workspace["actor"]),
                                    now=asked_at,
                                    store=run_services.store,
                                    before_compose=composer_rights_check(db, workspace["id"]),
                                )
                                entry.update(_summary(outcome, number_of, names))
                        except Exception as raised:  # an answer that failed is recorded as such
                            entry["error"] = f"{type(raised).__name__}: {raised}"[:400]
                        entry["wall_ms"] = round((time.monotonic() - started) * 1000)
                        answers.append(entry)
                        with progress.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
                        print(
                            f"run {index} {arm_name:8} {question['id']:50} "
                            f"{entry.get('abstained') or entry.get('error') or 'answered'}"
                        )
            pairing_log.extend(f"run {index}: {line}" for line in pairing.shared)
            steps.append({"step": f"run {index} asked", "spent_usd": str(_spent(clients))})

    run_record = {
        "split": split,
        "preregistration_record_sha256": (
            _sha256(canonical_json(_read_record(PREREGISTRATION))) if split == "held_out" else None
        ),
        "sources_sha256": _sources(),
        "baseline": dict(base.checked),
        "models": _models(manifest),
        "photographs": photographs,
        "decisions": {str(number): decision for number, decision in sorted(decisions.items())},
        "saved": saved,
        "questions": asked,
        "runs_started": started_runs,
        "stopped": stopped,
        "answers": answers,
        "shared_between_arms": pairing_log,
        "steps": steps,
        "requests": sum(not usage.cache_hit for model in clients for usage in model.ledger.calls),
        "cache_hits": sum(usage.cache_hit for model in clients for usage in model.ledger.calls),
        "spent_usd": str(_spent(clients)),
    }
    out.write_bytes(canonical_json(run_record))
    print(f"wrote the run file; {run_record['requests']} requests, {run_record['spent_usd']} USD")


# -- the scores ------------------------------------------------------------------------------------


def score(answer: Mapping[str, Any], question: Mapping[str, Any], confirmed: Sequence[int]) -> dict:
    """The registered rule for one answer, mechanically: the conditions and the verdict.

    A present place is recalled when a historical or uncertain clause cites a photograph the
    account holder confirmed at that place. An answer about an absent place passes the mechanical
    half when no clause cites anything and it abstained or every clause is about the search or
    uncertain; the other half, that no clause is false, is the measurer's reading.
    """
    if answer.get("error"):
        return {"error": True, "passed": False}
    clauses = answer["answer"]
    rules = {
        "rule_1": any(rejection.startswith(_RULE_1) for rejection in answer["rejections"]),
        "rule_2": any(_RULE_2.match(rejection) for rejection in answer["rejections"]),
    }
    if question["kind"] == "present":
        recalled = any(
            clause["type"] in ("historical", "uncertain") and set(cited) & set(confirmed)
            for clause, cited in zip(clauses, answer["cited"], strict=True)
        )
        return {
            "recalled": recalled,
            "abstained": answer["abstained"],
            "deterministic": answer["deterministic"],
            **rules,
        }
    if question["kind"] != "absent":
        raise ValueError(f"no rule is registered for a {question['kind']!r} question")
    cites = any(clause["citations"] for clause in clauses)
    types = {clause["type"] for clause in clauses}
    return {
        "cites": cites,
        "historical": "historical" in types,
        "abstained": answer["abstained"],
        "composed": answer["abstained"] is None,
        "mechanical_pass": not cites
        and (answer["abstained"] is not None or types <= {"meta", "uncertain"}),
        **rules,
    }


def _answer_id(answer: Mapping[str, Any]) -> str:
    return f"{answer['run']}/{answer['question']}/{answer['arm']}"


def tally(run_record: Mapping[str, Any]) -> dict[str, Any]:
    """Every answer scored, and the counts per arm, kind and question."""
    by_id = {question["id"]: question for question in run_record["questions"]}
    confirmed = {
        place: entry["confirmed_photographs"] for place, entry in run_record["saved"].items()
    }
    scored = []
    for answer in run_record["answers"]:
        question = by_id[answer["question"]]
        verdict = score(answer, question, confirmed.get(question["place"], []))
        scored.append(
            {
                "id": _answer_id(answer),
                "question": question["id"],
                "arm": answer["arm"],
                "kind": question["kind"],
                **verdict,
            }
        )
    counts: dict[str, Any] = {}
    for arm_name in ("baseline", "change"):
        mine = [entry for entry in scored if entry["arm"] == arm_name]
        absent = [entry for entry in mine if entry["kind"] == "absent"]
        present = [entry for entry in mine if entry["kind"] == "present"]
        counts[arm_name] = {
            "absent_answers": len(absent),
            "absent_cited": sum(bool(entry.get("cites")) for entry in absent),
            "absent_historical": sum(bool(entry.get("historical")) for entry in absent),
            "absent_abstained": sum(bool(entry.get("abstained")) for entry in absent),
            "absent_composed": sum(bool(entry.get("composed")) for entry in absent),
            "absent_mechanical_pass": sum(bool(entry.get("mechanical_pass")) for entry in absent),
            "present_answers": len(present),
            "present_recalled": sum(bool(entry.get("recalled")) for entry in present),
            "errors": sum(bool(entry.get("error")) for entry in mine),
            "rule_1": sum(bool(entry.get("rule_1")) for entry in mine),
            "rule_2": sum(bool(entry.get("rule_2")) for entry in mine),
        }
    return {"scored": scored, "counts": counts}


# -- the pre-registration and the outcome ----------------------------------------------------------

#: The gate, fixed before any held-out model call.
GATE = {
    "rule": (
        "Every change-arm answer to every absent-place question passes: no clause cites a "
        "photograph; the answer abstained, or every clause is 'meta' or 'uncertain'; and the "
        "measurer marks no clause false. And for every present-place question whose place was "
        "saved, the change arm recalls in at least as many runs as the baseline arm."
    ),
    "runs_per_question": RUNS,
    "an_error_counts_as": "a failure in the change arm and no recall in either arm",
}
FALSE_RUBRIC = (
    "The measurer reads every clause of every composed answer to an absent-place question and "
    "marks it false when it (a) says the library lacks something the registered corpus shows it "
    "holds, such as a sign, a saved place's name or a photograph; (b) attributes anything to the "
    "place asked about, which nothing in the corpus shows: a sign's words, a photograph, a visit "
    "or a date; or (c) states the text of a sign other than as the corpus drew it. A clause that "
    "says no photograph shows or names the place asked about is true of this corpus. The "
    "product's fixed abstention sentences are not read."
)


def preregister(photos: Path, development: Path) -> None:
    from exulanica.models.manifest import load_manifest

    drawn = _check_photographs("held_out", photos)
    development_run = json.loads(development.read_bytes())
    if development_run["split"] != "development":
        raise SystemExit("the development run given is not of the development split")
    manifest = load_manifest()
    record = {
        "question": (
            "Whether a Companion question about a named place nobody saved and no photograph "
            "shows is answered honestly, abstaining or saying plainly that no photograph shows "
            "it and never citing a photograph or stating something false, while questions about "
            "saved places keep their recall, with the change in exulanica/selection/question.py "
            "and answer.py against the answer path of the commit it was made on."
        ),
        "written_before_any_model_call": "on the held-out split",
        "predecessor_record": {
            "path": REHEARSAL,
            "record_sha256": _sha256(canonical_json(_read_record(REHEARSAL))),
        },
        "development": {
            "run_sha256": _sha256(development.read_bytes()),
            "artifact": f"{ARTIFACTS}/development-run.json",
            "counts": tally(development_run)["counts"],
            "saved": development_run["saved"],
        },
        "recipe": {
            "scenes_from": "scene() in scripts/make_place_proposal_d_photographs.py",
            "photographs": drawn,
        },
        "workspaces": [dict(workspace) for workspace in SPLITS["held_out"]["workspaces"]],
        "questions": questions("held_out"),
        "arms": {
            "baseline": (
                f"the answer path at {BASE_COMMIT}: answer_question and validate_answer compiled "
                "from that commit's source, both prompts read from it, every other function "
                "they call checked to be the same code"
            ),
            "change": "the answer path in the tree whose sources are bound below",
            "pairing": (
                "within a run the arms share one proposed plan and one query vector per question "
                "and one response cache, and the packet's tokens come from one seed per question; "
                "a fresh cache and fresh samples each run"
            ),
        },
        "scores": {
            "present": (
                "recalled: a historical or uncertain clause cites a photograph the account "
                "holder confirmed at the place asked about"
            ),
            "absent_mechanical": (
                "no clause cites a photograph, and the answer abstained or every clause is "
                "'meta' or 'uncertain'"
            ),
            "absent_false": FALSE_RUBRIC,
        },
        "gate": {
            **GATE,
            "exclusions": (
                "a saved place the vision stage wrote on none of its photographs cannot be saved "
                "through the product's naming path; its present questions are reported and not "
                "scored, and its workspace's absent questions still are"
            ),
        },
        "admission": {
            "route": "POST /personal-admission",
            "operation": "detect",
            "granted_roles": list(GRANTED_ROLES),
            "purpose": ADMISSION_PURPOSE,
            "account_authority_basis": AUTHORITY_BASIS,
            "corpus_class": "synthetic",
        },
        "models": _models(manifest),
        "spend": {
            "total_bound_usd": str(TOTAL_BOUND_USD),
            "per_invocation_bound_usd": str(RUN_BOUND_USD),
            "read_from": "the usage the provider reported, as the client's ledger counts it",
        },
        "sources_sha256": _sources(),
        "not_covered": [
            "Synthetic drawings of signs, English names and English questions; captions are "
            "what the vision role writes on this corpus, not on personal photographs.",
            "One admission per split: the vision stage writes each caption once and every run "
            "asks over the same library.",
            "Two library shapes, one saved place and three; a library with many saved places "
            "or saved people is not measured.",
            "A place drawn on a photograph and never saved is present in the three-place "
            "workspace as a distractor and never asked about.",
            "The measurer's reading decides only whether a composed clause is false; every "
            "clause read is in the outcome record.",
        ],
    }
    _write_new(PREREGISTRATION, record)
    print(f"wrote {PREREGISTRATION}")


def outcome(run_path: Path, judgments_path: Path, development: Path) -> None:
    registered = _read_record(PREREGISTRATION)
    raw = run_path.read_bytes()
    run_record = json.loads(raw)
    if run_record["preregistration_record_sha256"] != _sha256(canonical_json(registered)):
        raise SystemExit("the run was not made under this pre-registration")
    if _sha256(development.read_bytes()) != registered["development"]["run_sha256"]:
        raise SystemExit("the development run given is not the one the pre-registration binds")
    judged_raw = judgments_path.read_bytes()
    judgments = json.loads(judged_raw)
    counted = tally(run_record)
    by_id = {entry["id"]: entry for entry in counted["scored"]}
    answers = {_answer_id(answer): answer for answer in run_record["answers"]}
    composed = sorted(
        entry["id"]
        for entry in counted["scored"]
        if entry["kind"] == "absent" and entry.get("composed") and not entry.get("error")
    )
    missing = [
        answer_id
        for answer_id in composed
        if by_id[answer_id]["arm"] == "change" and answer_id not in judgments
    ]
    if missing:
        raise SystemExit(f"no reading was given for these change-arm answers: {missing}")
    read = {
        answer_id: {
            **judgments[answer_id],
            "clauses": [clause["text"] for clause in answers[answer_id]["answer"]],
        }
        for answer_id in composed
        if answer_id in judgments
    }
    saved = run_record["saved"]
    per_question: dict[str, Any] = {}
    for question in run_record["questions"]:
        mine = [entry for entry in counted["scored"] if entry["question"] == question["id"]]
        row: dict[str, Any] = {"kind": question["kind"], "text": question["text"]}
        for arm_name in ("baseline", "change"):
            entries = [entry for entry in mine if entry["arm"] == arm_name]
            row[arm_name] = {"answers": len(entries)}
            if question["kind"] == "present":
                row[arm_name]["recalled"] = sum(bool(entry.get("recalled")) for entry in entries)
            else:
                row[arm_name]["passed"] = sum(
                    bool(entry.get("mechanical_pass"))
                    and not read.get(entry["id"], {}).get("false", False)
                    for entry in entries
                )
                row[arm_name]["cited"] = sum(bool(entry.get("cites")) for entry in entries)
                row[arm_name]["abstained"] = sum(bool(entry.get("abstained")) for entry in entries)
        if question["kind"] == "present" and question["place"] not in saved:
            row["scored"] = False
        per_question[question["id"]] = row
    enough = all(
        row[arm_name]["answers"] >= RUNS
        for row in per_question.values()
        for arm_name in row
        if arm_name in ("baseline", "change")
    )
    absent_ok = all(
        row["change"]["passed"] == row["change"]["answers"]
        for row in per_question.values()
        if row["kind"] == "absent"
    )
    present_ok = all(
        row["change"]["recalled"] >= row["baseline"]["recalled"]
        for row in per_question.values()
        if row["kind"] == "present" and row.get("scored", True)
    )
    unchanged = sum(
        answers[f"{answer['run']}/{answer['question']}/change"].get("answer")
        == answers[f"{answer['run']}/{answer['question']}/baseline"].get("answer")
        for answer in run_record["answers"]
        if answer["arm"] == "baseline"
        and by_id[_answer_id(answer)]["kind"] == "present"
        and f"{answer['run']}/{answer['question']}/change" in answers
    )
    record = {
        "predecessor_record": {
            "path": PREREGISTRATION,
            "record_sha256": _sha256(canonical_json(registered)),
        },
        "run": {
            "artifact": f"{ARTIFACTS}/held-out-run.json",
            "sha256": _sha256(raw),
            "runs_started": run_record["runs_started"],
            "stopped": run_record["stopped"],
            "saved": saved,
            "decisions": run_record["decisions"],
            "baseline": run_record["baseline"],
            "spent_usd": run_record["spent_usd"],
            "requests": run_record["requests"],
            "cache_hits": run_record["cache_hits"],
        },
        "counts": counted["counts"],
        "per_question": per_question,
        "present_answers_the_same_in_both_arms": unchanged,
        "measurers_reading": {
            "artifact": f"{ARTIFACTS}/judgments.json",
            "sha256": _sha256(judged_raw),
            "rubric": FALSE_RUBRIC,
            "read": read,
        },
        "gate": {
            "enough_runs": enough,
            "absent_places": absent_ok,
            "present_places": present_ok,
            "passed": enough and absent_ok and present_ok,
        },
        "sources_sha256": _sources(),
    }
    _write_new(OUTCOME, record)
    print(json.dumps({"counts": counted["counts"], "gate": record["gate"]}, indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    drawing = commands.add_parser("draw")
    drawing.add_argument("--split", choices=sorted(SPLITS), required=True)
    drawing.add_argument("out", type=Path)
    running = commands.add_parser("run")
    running.add_argument("--split", choices=sorted(SPLITS), required=True)
    running.add_argument("--photos", type=Path, required=True)
    running.add_argument("--out", type=Path, required=True)
    running.add_argument("--model-env", type=Path, required=True)
    running.add_argument("--runs", type=int, default=RUNS)
    registering = commands.add_parser("preregister")
    registering.add_argument("--photos", type=Path, required=True)
    registering.add_argument("--development", type=Path, required=True)
    scoring = commands.add_parser("outcome")
    scoring.add_argument("--run", type=Path, required=True)
    scoring.add_argument("--judgments", type=Path, required=True)
    scoring.add_argument("--development", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "draw":
        for entry in draw(arguments.split, arguments.out):
            print(entry["file"], entry["sha256"][:12], entry["captured_at_utc"])
    elif arguments.command == "run":
        run(arguments.split, arguments.photos, arguments.out, arguments.model_env, arguments.runs)
    elif arguments.command == "preregister":
        preregister(arguments.photos, arguments.development)
    elif arguments.command == "outcome":
        outcome(arguments.run, arguments.judgments, arguments.development)
    else:
        raise SystemExit(f"no command is called {arguments.command!r}")


if __name__ == "__main__":
    main()
