"""Does the placeholder a withheld place's name becomes change which photographs a search finds?

    python scripts/measure_embedding_placeholders.py draw OUT_DIR
    python scripts/measure_embedding_placeholders.py preregister --photos OUT_DIR
    python scripts/measure_embedding_placeholders.py run --photos OUT_DIR --out RUN.json
    python scripts/measure_embedding_placeholders.py outcome --run RUN.json

**The question.** The boundary every hosted request passes replaces a saved place's name that no
right releases with a placeholder of its class, numbered per request in the order it recognises
names (``exulanica/epistemics/hosted_requests.py``). In text sent for a vector, ``[place A]`` is
therefore a different place in each caption and in each query: a query about one saved place shares
that token with every caption holding any saved place. This measures whether that changes which
photographs a search finds, against one alternative chosen before any model call: a placeholder
stable for each place across every request of the workspace, given to the boundary as the caller's
record of placeholders. A person's name is never part of either: the corpus names no person, and a
person's placeholder is never made stable.

**The corpus** is drawn here from fixed recipes by ``scene()`` of
``scripts/make_place_proposal_d_photographs.py``: six places, three photographs each, whose signs
carry a name no earlier corpus drew, and six photographs that name no saved place. Nothing in them
is a personal photograph.

**The run** is the product, in process, over a private PostgreSQL made for it and removed after:
``POST /intake``, ``POST /personal-admission`` with the vision and embedding roles granted by the
synthetic account holder, the API's derivative worker (the vision stage and its caption pass),
``POST /identity/name`` and ``POST /identity/confirm`` for each place the vision stage wrote. Then
each arm deletes the stored caption vectors and stores every photograph's again, the current and
released arms through the derivative worker's own caption pass and the alternative through the
function that pass calls, ``embed_capture``, with the alternative's policy; and each arm embeds
every registered query with ``embed_query``, the product's query path:

*   ``current``: the workspace's policy as the product attaches it, no place allowed;
*   ``stable``: the same policy, handed a record giving each saved place one placeholder for the
    whole workspace (the alternative);
*   ``released``: every place's embedding use allowed through ``POST /place-name-rights``, so the
    names themselves go (a reference for what an allowed name gives, not a candidate).

Each query is scored twice: by the caption vectors alone, ranked by cosine, and end to end, by
the order the executor returns for a supplied plan that carries the query. The pre-registration
fixes the queries, the photographs each should find, the scores, the gate and the spend before
any model call; ``outcome`` applies them to the run and writes the outcome record.

The credential is read from the environment only (the manifest's ``NEBIUS_API_KEY``), and the
model endpoint must be declared in ``EXULANICA_EGRESS_ALLOWLIST``.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_place_proposal_d_photographs as place_d  # noqa: E402
from make_place_photographs import photographic  # noqa: E402

from exulanica.canonical import canonical_json  # noqa: E402
from exulanica.ingest.exif import extract_exif_facts  # noqa: E402

PREREGISTRATION = "docs/evaluation/2026-09-23-embedding-placeholders-preregistration.json"
OUTCOME = "docs/evaluation/2026-09-23-embedding-placeholders-outcome.json"
PROFILE = "exulanica.digest-bound-record/v1"

#: The places, each drawn on three photographs of three kinds. Two words each, none drawn by an
#: earlier corpus (``draw`` refuses one that was).
PLACES: tuple[str, ...] = (
    "QUORLING QUAY",
    "RASKETT PIER",
    "SOLVEN CHAPEL",
    "TARNWICK BASIN",
    "ULLSBY GARTH",
    "VEDDOW MARKET",
)
#: The third photograph's kind, by place, so each of the three sign kinds is drawn twice.
THIRD_KIND: tuple[str, ...] = (
    "street_sign",
    "park_sign",
    "station_sign",
    "street_sign",
    "park_sign",
    "station_sign",
)
#: Photographs that name no saved place: two signs whose names are never saved, two with no text,
#: a product and a slogan.
DISTRACTORS: tuple[tuple[str, str, str], ...] = (
    ("street_sign", "positive", "WESSOCK GATE"),
    ("nameplate", "positive", "YARLOW CROSS"),
    ("no_text", "negative", ""),
    ("no_text", "negative", ""),
    ("product", "negative", "ZELBY"),
    ("slogan", "negative", "WATCH YOUR HEAD"),
)
#: The first scene index. Any index draws a whole scene; these start clear of earlier corpora's.
FIRST_INDEX = 300
#: The JPEG quality the place corpora were saved at.
JPEG_QUALITY = 82
#: When each photograph was taken: one day apart from the first, at the same time and offset.
FIRST_DAY = dt.date(2026, 7, 1)
CLOCK = "10:30:00"
OFFSET = "+01:00"

#: The query templates for each saved place, filled with its saved name as a person would type it
#: (the words in title case), and the content queries with the scene kinds each should find.
PLACE_QUERIES: tuple[str, ...] = ("{name} sign", "photographs at {name}")
CONTENT_QUERIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("a nameplate on a building", ("nameplate", "nameplate_tree_beside")),
    ("a street sign on a pole", ("street_sign",)),
    ("a tree beside a building", ("nameplate_tree_beside",)),
    ("a sign in a park", ("park_sign",)),
    ("a sign at a station", ("station_sign",)),
)

#: The gate, fixed before any model call. Differences are of mean R-precision, the alternative
#: minus the current redaction, over the queries named.
GATE = {
    "vector_place_min_gain": "0.25",
    "end_to_end_place_min_gain": "0.10",
    "content_max_loss": "0.05",
    "min_saved_places": 4,
}

#: The spend bounds: the brief's total, and the most one run may reach before its client stops.
TOTAL_BOUND_USD = Decimal("2")
RUN_CEILING_USD = Decimal("0.45")
#: More than one run's calls: a vision call and a sign question per photograph, the worker's
#: caption pass, then each arm's caption pass and queries.
RUN_MAX_CALLS = 400

#: The roles the synthetic account holder grants, and what for.
GRANTED_ROLES = ("vision", "embedding")
ADMISSION_PURPOSE = (
    "Vector search measurement on synthetic drawings: signs whose names are saved as places, "
    "searched with each placeholder the names become"
)
AUTHORITY_BASIS = (
    "synthetic drawings made by scripts/measure_embedding_placeholders.py from the place proposal "
    "experiment's scene generator; no personal photograph"
)

#: Sources whose bytes decide what this measures, bound by digest in both records.
BOUND_SOURCES = (
    "scripts/measure_embedding_placeholders.py",
    "scripts/make_place_proposal_d_photographs.py",
    "scripts/make_place_photographs.py",
    "exulanica/epistemics/hosted_requests.py",
    "exulanica/epistemics/saved_names.py",
    "exulanica/epistemics/caption_embeddings.py",
    "exulanica/selection/embeddings.py",
    "exulanica/selection/executor.py",
)

#: Cosine similarities are recorded as integers, in millionths, because a record holds no float.
COSINE_SCALE = 1_000_000


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _title(name: str) -> str:
    return " ".join(word.capitalize() for word in name.split())


# -- the photographs -------------------------------------------------------------------------------


def recipe() -> list[dict[str, Any]]:
    """Every photograph to draw: its file, kind, text, and the place it shows if any."""
    entries: list[dict[str, Any]] = []
    for name, third in zip(PLACES, THIRD_KIND, strict=True):
        for kind in ("nameplate", "nameplate_tree_beside", third):
            entries.append({"kind": kind, "arm": "positive", "text": name, "place": name})
    for kind, arm, text in DISTRACTORS:
        entries.append({"kind": kind, "arm": arm, "text": text, "place": None})
    for position, entry in enumerate(entries):
        entry["photograph"] = position + 1
        entry["scene_index"] = FIRST_INDEX + position
        entry["file"] = f"photograph-{position + 1:02d}-{entry['kind']}.jpg"
        day = FIRST_DAY + dt.timedelta(days=position)
        entry["exif_time"] = f"{day:%Y:%m:%d} {CLOCK}"
    return entries


def _refuse_earlier_words() -> None:
    earlier = place_d._earlier_words()
    for split in place_d.SPLITS.values():
        for _kind, _arm, text in split:
            for part in place_d._texts(text):
                earlier.update(place_d._words(part))
    earlier.update({"MIRELAND", "HALL"})
    drawn = {
        word
        for entry in recipe()
        for part in place_d._texts(entry["text"])
        for word in place_d._words(part)
    }
    repeated = sorted(drawn & earlier)
    if repeated:
        raise SystemExit(f"words an earlier corpus drew: {repeated}")


def draw(out: Path) -> list[dict[str, Any]]:
    """Draw every photograph into ``out``, check its capture time as the product reads it."""
    _refuse_earlier_words()
    out.mkdir(parents=True, exist_ok=True)
    drawn = []
    for entry in recipe():
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
                **{key: entry[key] for key in ("photograph", "file", "kind", "place")},
                "scene_index": entry["scene_index"],
                "board_text": truth["board_text"],
                "captured_at_utc": expected.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path.read_bytes()),
            }
        )
    return drawn


# -- the records -----------------------------------------------------------------------------------


def _document(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "record": record,
        "record_sha256": _sha256(canonical_json(record)),
    }


def _write_new(path: str, record: dict[str, Any]) -> None:
    target = ROOT / path
    if target.exists():
        raise SystemExit(f"{path} exists, and docs/evaluation is append-only")
    target.write_text(
        json.dumps(_document(record), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_record(path: str) -> dict[str, Any]:
    document = json.loads((ROOT / path).read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{path} does not match its own digest")
    return document["record"]


def _sources() -> dict[str, str]:
    return {source: _sha256((ROOT / source).read_bytes()) for source in BOUND_SOURCES}


def preregister(photos: Path) -> None:
    from exulanica.models.manifest import Role, load_manifest

    drawn = draw(Path(tempfile.mkdtemp(prefix="embedding-placeholders-check-")))
    for entry in drawn:
        on_disk = photos / entry["file"]
        if _sha256(on_disk.read_bytes()) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} in the photographs given is not the drawn one")
    manifest = load_manifest()
    record = {
        "question": (
            "Whether the per-request placeholder a withheld place's name becomes in text sent for "
            "a vector changes which photographs a search finds, against a placeholder stable for "
            "each place across the workspace's requests."
        ),
        "written_before_any_model_call": True,
        "recipe": {
            "scenes_from": "scene() in scripts/make_place_proposal_d_photographs.py",
            "photographs": drawn,
        },
        "places": [
            {
                "drawn_name": name,
                "photographs": [e["photograph"] for e in drawn if e["place"] == name],
            }
            for name in PLACES
        ],
        "queries": {
            "place_templates": list(PLACE_QUERIES),
            "place_rule": (
                "each template filled with the place's saved name in title case; the right "
                "photographs are the place's own three"
            ),
            "content": [
                {
                    "text": text,
                    "kinds": list(kinds),
                    "photographs": [e["photograph"] for e in drawn if e["kind"] in kinds],
                }
                for text, kinds in CONTENT_QUERIES
            ],
        },
        "arms": {
            "current": "the workspace policy as the product attaches it; no place's use allowed",
            "stable": (
                "the same policy handed a record giving each saved place one placeholder for the "
                "whole workspace, in entity id order ([place A] for the first); the alternative"
            ),
            "released": (
                "every saved place's embedding use allowed through POST /place-name-rights; a "
                "reference for what an allowed name gives, never adopted by this measurement"
            ),
        },
        "scores": {
            "r_precision": (
                "of the R photographs a query should find, how many are among the first R the "
                "search ranks; R is the number it should find"
            ),
            "vector": (
                "photographs ranked by the cosine of the query's vector to each photograph's "
                "caption vector as the arm stored it; a photograph with no caption vector ranks "
                "last"
            ),
            "end_to_end": (
                "the order the executor returns for SelectionPlan(intent=captures, "
                "semantic_query=query) with the arm's query vector"
            ),
        },
        "gate": {
            **GATE,
            "rule": (
                "the alternative passes only if, over the place-named queries, its mean vector "
                "R-precision exceeds the current redaction's by at least vector_place_min_gain and "
                "its mean end-to-end R-precision by at least end_to_end_place_min_gain, and over "
                "the content queries neither mean falls by more than content_max_loss. A pass is "
                "necessary and not sufficient: the alternative sends a token stable across "
                "requests for each place, which lets a provider link the photographs of one "
                "withheld place, so adopting it needs the account holder's decision on that."
            ),
            "exclusions": (
                "a place the vision stage writes on none of its photographs cannot be saved "
                "through the product's naming path, so its queries are left out and reported; with "
                "fewer than min_saved_places places saved the run is reported and not scored"
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
        "models": {
            role.value: [manifest[role].primary.model_id]
            + ([manifest[role].fallback.model_id] if manifest[role].fallback else [])
            for role in (Role.VISION, Role.EMBEDDING)
        },
        "spend": {
            "bound_usd": str(TOTAL_BOUND_USD),
            "per_run_ceiling_usd": str(RUN_CEILING_USD),
            "read_from": "the usage the provider reported, as the client's ledger counts it",
        },
        "sources_sha256": _sources(),
        "not_covered": [
            "Synthetic drawings, English names, six places; captions are what the vision role "
            "writes on this corpus, not on personal photographs.",
            "One run: the vision stage writes each caption once, and every arm embeds the same "
            "captions.",
            "A question asked in words never reaches the query path with a place's name or "
            "placeholder: the planner's query has both removed. The place-named queries stand for "
            "a plan a person supplies with a place's name typed in it.",
            "No person is named in the corpus; a person's placeholder is never made stable.",
        ],
    }
    _write_new(PREREGISTRATION, record)
    print(f"wrote {PREREGISTRATION}")


# -- one run of the product ------------------------------------------------------------------------


class RecordingTransport:
    """The real transport, keeping what each request asked: an embedding's texts, a chat's model."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.egress = getattr(inner, "egress", None)
        self.sent: list[dict[str, Any]] = []

    def post_json(self, url, *, headers, payload, timeout):
        response = self._inner.post_json(url, headers=headers, payload=payload, timeout=timeout)
        if url.endswith("/embeddings"):
            self.sent.append({"kind": "embedding", "input": list(payload.get("input") or [])})
        else:
            self.sent.append({"kind": "chat", "model": payload.get("model")})
        return response

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class StablePlaces:
    """The alternative: the workspace policy, handed one placeholder per place for every request."""

    def __init__(self, inner: Any, record: Mapping[uuid.UUID, str]) -> None:
        self._inner = inner
        self._record = dict(record)

    def admit(self, request: Any) -> Sequence[str]:
        import dataclasses
        from types import MappingProxyType

        return self._inner.admit(
            dataclasses.replace(request, placeholders=MappingProxyType(self._record))
        )


def _label(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"[place {letters}]"


@contextlib.contextmanager
def _database() -> Iterator[dict[str, str]]:
    """A private PostgreSQL made for this run, provisioned as the setup guide says, then removed."""
    from test_postgres import remove_test_server, start_test_server

    from exulanica.db.cli import provision
    from exulanica.db.roles import EXECUTOR_ROLE, RUNTIME_ROLE

    server, owner = start_test_server("embeddingplaceholders")
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


def _observation_screening(repository: Any, capture: uuid.UUID) -> Any:
    """The receipt the derivative worker hands a detection-only capture's caption pass.

    The worker's own lookup: a geometry-grade screening when one allows the capture, otherwise
    the newest ``person_detection_only`` screening that allows observation
    (``DerivativeWorker._run_job`` in ``exulanica/ingest/worker.py``).
    """
    screening = repository.latest_privacy_screening(capture)
    if screening is not None:
        return screening
    row = repository.connection.execute(
        "select screening_id from reconstruction_privacy_screening "
        "where workspace_id=%s and capture_id=%s "
        "and screening_method='person_detection_only' "
        "and privacy_screening_allows_observation(workspace_id,capture_id,screening_id) "
        "order by screened_at desc,screening_id desc limit 1",
        (repository.workspace_id, capture),
    ).fetchone()
    if row is None:
        raise SystemExit(f"no screening permits observing capture {capture}")
    return repository.privacy_screening(row["screening_id"])


def run(photos: Path, out: Path) -> None:
    import psycopg
    from fastapi.testclient import TestClient
    from psycopg.rows import dict_row

    from exulanica.api.app import create_app
    from exulanica.api.authorisation import API_TOKENS_ENV
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
    from exulanica.epistemics.caption_embeddings import SOURCE_SQL, SEARCHABLE_PREDICATES
    from exulanica.epistemics.hosted_requests import borrowing
    from exulanica.ingest.repository import IngestRepository
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.transport import HttpxTransport
    from exulanica.selection import Session
    from exulanica.selection.embeddings import embed_query
    from exulanica.selection.executor import execute
    from exulanica.selection.plan import Intent, SelectionPlan
    from exulanica.selection.validation import validate
    from exulanica.store.namespaces import BLOB_NAMESPACE

    registered = _read_record(PREREGISTRATION)
    if registered["sources_sha256"] != _sources():
        raise SystemExit("a bound source changed since the pre-registration")
    photographs = registered["recipe"]["photographs"]
    for entry in photographs:
        if _sha256((photos / entry["file"]).read_bytes()) != entry["sha256"]:
            raise SystemExit(f"{entry['file']} is not the registered photograph")
    if out.exists():
        raise SystemExit(f"{out.name} exists; a run file is written once")

    transport = RecordingTransport(HttpxTransport())
    budget = BudgetGuard(ceiling_usd=RUN_CEILING_USD, max_calls=RUN_MAX_CALLS)
    client = ModelClient(transport=transport, budget=budget, max_attempts=3)
    workspace = uuid.uuid4()
    actor = uuid.uuid4()
    token = f"measurement-{uuid.uuid4().hex}"
    auth = {"Authorization": f"Bearer {token}"}
    data_dir = Path(tempfile.mkdtemp(prefix="embedding-placeholders-"))
    steps: list[dict[str, Any]] = []

    def spent() -> str:
        return str(sum((call.usd for call in client.ledger.calls), Decimal(0)))

    with _database() as urls:
        with psycopg.connect(urls["owner"], autocommit=True) as owner:
            provision_workspace(owner, workspace)

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
                        token: {
                            "workspace_id": str(workspace),
                            "actor": str(actor),
                            "permissions": [str(permission) for permission in Permission],
                        }
                    }
                ),
            }

        services = build_services(environ(False), model_client=client)
        worker = build_services(environ(True), model_client=client).build_derivative_worker()
        assert worker is not None, "the instance built no derivative worker"
        with TestClient(create_app(services, verify=False)) as http:

            def call(name: str, method: str, route: str, **kwargs: Any) -> Any:
                response = http.request(method, route, headers=auth, **kwargs)
                steps.append(
                    {"step": name, "request": f"{method} {route}", "status": response.status_code}
                )
                if response.status_code >= 300:
                    raise SystemExit(f"{name}: {response.status_code} {response.text[:500]}")
                return response.json()

            uploaded: dict[int, dict[str, Any]] = {}
            for entry in photographs:
                path = photos / entry["file"]
                accepted = call(
                    f"upload {entry['file']}",
                    "POST",
                    "/intake",
                    files={"files": (entry["file"], path.read_bytes(), "image/jpeg")},
                )["accepted"]
                uploaded[entry["photograph"]] = {**accepted[0], "bytes": entry["bytes"]}

            now = dt.datetime.now(dt.UTC).replace(microsecond=0)
            at = (now - dt.timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
            until = (now + dt.timedelta(days=1)).isoformat().replace("+00:00", "Z")
            call(
                "detection permission and model rights, granted by the synthetic account holder",
                "POST",
                "/personal-admission",
                json={
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
                    "spent_usd": spent(),
                }
            )
            captures = {number: uuid.UUID(c["capture_id"]) for number, c in uploaded.items()}
            number_of = {capture: number for number, capture in captures.items()}

            decisions: dict[int, dict[str, Any]] = {}
            with psycopg.connect(urls["owner"], row_factory=dict_row) as owner:
                rows = owner.execute(
                    "select a.storage_key, c.capture_id from artifact a "
                    "join capture c on c.workspace_id=a.workspace_id "
                    "and c.blob_sha256=a.source_blob_sha256 "
                    "where a.workspace_id=%s and a.kind='vision_observation' "
                    "and a.superseded_by is null",
                    (workspace,),
                ).fetchall()
            for row in rows:
                stored = json.loads((data_dir / BLOB_NAMESPACE / row["storage_key"]).read_bytes())
                check = stored.get("place_check") or {}
                decisions[number_of[row["capture_id"]]] = {
                    "outcome": check.get("outcome"),
                    "written_label": check.get("written_label"),
                }

            graph = call("read the graph", "GET", "/graph")
            occurrences = {
                uuid.UUID(occurrence["capture_id"]): occurrence["occurrence_id"]
                for occurrence in graph["occurrences"]
                if occurrence["occurrence_class"] == "place"
            }
            saved: dict[str, dict[str, Any]] = {}
            for place in registered["places"]:
                written = [
                    number
                    for number in place["photographs"]
                    if decisions.get(number, {}).get("outcome") == "written"
                ]
                if not written:
                    continue
                label = decisions[written[0]]["written_label"]
                named = call(
                    f"name {place['drawn_name']} from photograph {written[0]}",
                    "POST",
                    "/identity/name",
                    json={
                        "occurrence_id": occurrences[captures[written[0]]],
                        "display_name": label,
                    },
                )
                for number in written[1:]:
                    call(
                        f"confirm photograph {number} shows {place['drawn_name']}",
                        "POST",
                        "/identity/confirm",
                        json={
                            "occurrence_id": occurrences[captures[number]],
                            "entity_id": named["entity_id"],
                        },
                    )
                saved[place["drawn_name"]] = {
                    "entity_id": named["entity_id"],
                    "saved_name": label,
                    "written_on": written,
                }

            queries = [
                {
                    "text": template.format(name=_title(entry["saved_name"])),
                    "place": drawn,
                    "photographs": next(
                        p["photographs"] for p in registered["places"] if p["drawn_name"] == drawn
                    ),
                }
                for drawn, entry in saved.items()
                for template in PLACE_QUERIES
            ] + [
                {"text": content["text"], "place": None, "photographs": content["photographs"]}
                for content in registered["queries"]["content"]
            ]
            stable_record = {
                uuid.UUID(entity): _label(index)
                for index, entity in enumerate(sorted(e["entity_id"] for e in saved.values()))
            }

            arms: dict[str, Any] = {}
            session = Session(workspace_id=workspace, actor=actor)
            for arm in ("current", "stable", "released"):
                if arm == "released":
                    for entry in saved.values():
                        read = call(
                            "read the place's uses",
                            "GET",
                            f"/place-name-rights/{entry['entity_id']}",
                        )
                        (use,) = [u for u in read["uses"] if u["use"] == "embedding"]
                        call(
                            f"allow the embedding use of {entry['saved_name']}",
                            "POST",
                            f"/place-name-rights/{entry['entity_id']}/grants",
                            json={"use": "embedding", "notice": use["notice"]},
                        )
                with psycopg.connect(urls["owner"], autocommit=True) as owner:
                    owner.execute("delete from embedding where workspace_id=%s", (workspace,))
                first = len(transport.sent)
                with services.database.session(workspace) as connection:
                    repository = IngestRepository(connection, workspace)
                    hosted = services.hosted_model(connection, workspace)
                    assert hosted is not None
                    if arm == "stable":
                        policy = services.request_policy(
                            workspace,
                            borrowing(connection),
                            released_places=services.released_place_names,
                        )
                        hosted = client.with_policy(StablePlaces(policy, stable_record))
                    for capture in (captures[number] for number in sorted(captures)):
                        screening = _observation_screening(repository, capture)
                        if arm == "stable":
                            from exulanica.epistemics.caption_embeddings import embed_capture
                            from exulanica.ingest.model_rights import require_model_right

                            embed_capture(
                                connection,
                                workspace,
                                capture,
                                hosted,
                                before_send=lambda handoff, r=repository, c=capture, s=screening: (
                                    require_model_right(r, c, s.screening_id, handoff)
                                ),
                            )
                        else:
                            worker._embed_captions(repository, capture, screening.screening_id)
                    captions = transport.sent[first:]
                    scored = []
                    for query in queries:
                        embedded = embed_query(hosted, query["text"])
                        sent_query = transport.sent[-1]["input"]
                        cosines = connection.execute(
                            "with source as (" + SOURCE_SQL + ") "
                            "select source.capture_id, 1 - (e.v <=> %s::halfvec) as cosine "
                            "from source join embedding e on e.workspace_id=%s "
                            "and e.ref_type='span' and e.ref_id=source.span_id",
                            (workspace, list(SEARCHABLE_PREDICATES), embedded.literal, workspace),
                        ).fetchall()
                        by_vector = sorted(
                            (
                                (
                                    number_of[row["capture_id"]],
                                    round(float(row["cosine"]) * COSINE_SCALE),
                                )
                                for row in cosines
                            ),
                            key=lambda pair: (-pair[1], pair[0]),
                        )
                        plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=query["text"])
                        result = execute(
                            connection,
                            validate(connection, plan, session),
                            query_embedding=embedded,
                            store=services.store,
                        )
                        scored.append(
                            {
                                **query,
                                "sent": sent_query,
                                "by_vector": [list(pair) for pair in by_vector],
                                "end_to_end": [
                                    number_of[capture.capture_id] for capture in result.captures
                                ],
                            }
                        )
                arms[arm] = {
                    "captions_sent": [
                        entry["input"] for entry in captions if entry["kind"] == "embedding"
                    ],
                    "queries": scored,
                    "spent_usd_after": spent(),
                }

    run_record = {
        "preregistration_record_sha256": _sha256(canonical_json(registered)),
        "sources_sha256": _sources(),
        "decisions": {str(number): decision for number, decision in sorted(decisions.items())},
        "saved": saved,
        "stable_record": {str(entity): label for entity, label in stable_record.items()},
        "arms": arms,
        "steps": steps,
        "calls": len(client.ledger.calls),
        "spent_usd": spent(),
    }
    out.write_bytes(canonical_json(run_record))
    print(f"wrote the run file; {run_record['calls']} calls, {run_record['spent_usd']} USD")


# -- the outcome -----------------------------------------------------------------------------------


def _r_precision(ranked: Sequence[int], right: Sequence[int]) -> tuple[int, int]:
    wanted = set(right)
    return len(wanted & set(ranked[: len(wanted)])), len(wanted)


def _mean(scores: Sequence[tuple[int, int]]) -> Decimal:
    if not scores:
        return Decimal(0)
    total = sum((Decimal(found) / Decimal(wanted) for found, wanted in scores), Decimal(0))
    return (total / len(scores)).quantize(Decimal("0.0001"))


def outcome(run_path: Path) -> None:
    registered = _read_record(PREREGISTRATION)
    raw = run_path.read_bytes()
    run_record = json.loads(raw)
    if run_record["preregistration_record_sha256"] != _sha256(canonical_json(registered)):
        raise SystemExit("the run was not made under this pre-registration")
    means: dict[str, dict[str, str]] = {}
    per_query: dict[str, list[dict[str, Any]]] = {}
    for arm, data in run_record["arms"].items():
        rows = []
        for query in data["queries"]:
            by_vector = [number for number, _ in query["by_vector"]]
            rows.append(
                {
                    "text": query["text"],
                    "place": query["place"],
                    "vector": list(_r_precision(by_vector, query["photographs"])),
                    "end_to_end": list(_r_precision(query["end_to_end"], query["photographs"])),
                }
            )
        per_query[arm] = rows
        means[arm] = {
            f"{score}_{group}": str(
                _mean(
                    [tuple(r[score]) for r in rows if (r["place"] is None) == (group == "content")]
                )
            )
            for score in ("vector", "end_to_end")
            for group in ("place", "content")
        }
    saved = len(run_record["saved"])
    current, stable = means["current"], means["stable"]
    gains = {
        key: str(Decimal(stable[key]) - Decimal(current[key]))
        for key in ("vector_place", "end_to_end_place", "vector_content", "end_to_end_content")
    }
    scored = saved >= GATE["min_saved_places"]
    passed = scored and (
        Decimal(gains["vector_place"]) >= Decimal(GATE["vector_place_min_gain"])
        and Decimal(gains["end_to_end_place"]) >= Decimal(GATE["end_to_end_place_min_gain"])
        and Decimal(gains["vector_content"]) >= -Decimal(GATE["content_max_loss"])
        and Decimal(gains["end_to_end_content"]) >= -Decimal(GATE["content_max_loss"])
    )
    record = {
        "preregistration": {
            "path": PREREGISTRATION,
            "record_sha256": _sha256(canonical_json(registered)),
        },
        "run_sha256": _sha256(raw),
        "run": run_record,
        "saved_places": saved,
        "scored": scored,
        "means": means,
        "gains_of_the_alternative": gains,
        "per_query": per_query,
        "gate_passed": passed,
        "adopted": False,
        "adoption_note": (
            "Not adopted: the gate was not passed."
            if not passed
            else "Not adopted here: a pass is necessary and not sufficient, and adopting a token "
            "stable across requests for each place needs the account holder's decision."
        ),
        "sources_sha256": _sources(),
    }
    _write_new(OUTCOME, record)
    print(json.dumps({"means": means, "gains": gains, "passed": passed}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    drawn = commands.add_parser("draw")
    drawn.add_argument("out", type=Path)
    pre = commands.add_parser("preregister")
    pre.add_argument("--photos", type=Path, required=True)
    once = commands.add_parser("run")
    once.add_argument("--photos", type=Path, required=True)
    once.add_argument("--out", type=Path, required=True)
    scored = commands.add_parser("outcome")
    scored.add_argument("--run", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "draw":
        for entry in draw(arguments.out):
            print(entry["file"], entry["sha256"][:12])
    elif arguments.command == "preregister":
        preregister(arguments.photos)
    elif arguments.command == "run":
        run(arguments.photos, arguments.out)
    else:
        outcome(arguments.run)


if __name__ == "__main__":
    main()
