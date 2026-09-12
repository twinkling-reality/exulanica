"""What ends up persisted, and under which provenance class.

Four things are checked here, and each one is an invariant that a plausible-looking pipeline
gets wrong:

*   Capture-supported observation, model inference and user statement are three different
    things. A caption filed as a capture fact is a guess rendered as a measurement.
*   Every evidence address resolves back to the original bytes, and a span read out of the
    database rebuilds to the same digest it was stored under.
*   The ledger records what actually happened, in enough detail that the Assembly Replay does
    not have to read the source code.
*   A tombstoned address refuses the write, terminally.

These run against the real spine, which changes what several of them are able to prove. The
epistemic and tombstone guards used to be application code, because the SQLite mirror the
ingest path ran on could not express a trigger; the assertions against ``IngestRepository``
were therefore the whole guarantee. They are now the *error message*, and the guarantee is a
BEFORE trigger that refuses the same write on routes that never touch this class. So each of
those tests now makes the offending write twice: once through the repository, which must fail
with a sentence naming the rule, and once as raw SQL through the same connection, which must
fail with an SQLSTATE. Neither check subsumes the other, and the second is the one an
application bug cannot remove.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import datetime as dt
import inspect
import json
import pathlib
import uuid

import psycopg
import pytest
from exulanica.errors import EpistemicViolation, TombstonedError
from exulanica.evidence import Modality
from exulanica.ingest import pipeline as pipeline_module
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.resolve import resolve_region_image
from exulanica.ingest.stages import StageSpec
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.resolve import address_from_span_row, resolve_original_bytes
from psycopg.types.json import Jsonb

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, bomb_png, ingest_observed, write_photo

# No module-level postgres marker. tests/conftest.py marks each test by the fixtures it
# actually requests, so the handful here that need no server stay runnable without one.

#: SQLSTATE 23000. Both guards raise ``integrity_constraint_violation``, so this is what a
#: refusal from the database looks like from Python, and it is deliberately narrower than
#: ``psycopg.Error``: a typo in the statement would raise a syntax error and pass a check that
#: only asked for "some database exception".
REFUSED = psycopg.errors.IntegrityConstraintViolation


@pytest.fixture
def ingested(tmp_path, photo_dir, repository):
    """One photograph through the whole pipeline, with the default observation.

    The default payload's person carries no box, which is deliberate rather than incidental:
    the boxless case is the one where a person is asserted and no occurrence is written, and it
    is the shape most of these tests want.
    """
    path = write_photo(photo_dir, "a.jpg", gps=(64.3271, -20.1199))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    vision = CountingVisionModel()
    pipeline = PhotoIngestPipeline(repository, store, vision=vision)
    outcome = ingest_observed(pipeline, repository, path)
    assert outcome.error is None
    return repository, store, pipeline, path, outcome


@pytest.fixture
def ingested_with_a_person(tmp_path, photo_dir, repository):
    """The same, with the person located, so a person occurrence is actually produced."""
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    located = [entry for entry in payload["objects"] if entry["label"] == "person"]
    assert len(located) == 1, payload["objects"]
    located[0]["box"] = {"x": 0.55, "y": 0.1, "w": 0.2, "h": 0.6}

    path = write_photo(photo_dir, "a.jpg", gps=(64.3271, -20.1199))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    vision = CountingVisionModel(payload=payload)
    pipeline = PhotoIngestPipeline(repository, store, vision=vision)
    outcome = ingest_observed(pipeline, repository, path)
    assert outcome.error is None
    return repository, store, pipeline, path, outcome


def _assertions(repository):
    rows = repository.connection.execute(
        "select a.kind, p.key, a.object_value, a.support_span_ids, a.produced_by_run, "
        "a.raw_score, a.stated_by_user from assertion a "
        "join predicate p on p.predicate_id = a.predicate_id"
    ).fetchall()
    return [dict(row) for row in rows]


def _one_span_id(repository):
    row = repository.connection.execute("select span_id from evidence_span limit 1").fetchone()
    return row["span_id"]


# -- epistemic status -------------------------------------------------------------------


def test_exif_facts_are_capture_and_model_output_is_inference(ingested):
    repository, *_ = ingested
    by_predicate = {row["key"]: row for row in _assertions(repository)}

    for key in ("captured_at", "device_model_is", "gps_position_is", "pixel_size_is"):
        assert by_predicate[key]["kind"] == "capture", key
    for key in ("caption_is", "object_present", "ocr_text_is", "place_is"):
        assert by_predicate[key]["kind"] == "inference", key


def test_every_assertion_cites_evidence_and_every_inference_names_its_run(ingested):
    repository, *_ = ingested
    for row in _assertions(repository):
        # support_span_ids is a uuid[], so it arrives as a list and there is nothing to decode.
        assert row["support_span_ids"], f"{row['key']} cites nothing"
        if row["kind"] == "inference":
            assert row["produced_by_run"] is not None, row["key"]


def test_a_model_score_is_never_invented_from_a_confidence_band(ingested):
    """The model emitted 'high', not 0.9. Turning a band into a number invents a frequency."""
    repository, *_ = ingested
    for row in _assertions(repository):
        assert row["raw_score"] is None
    quality = repository.connection.execute(
        "select quality from occurrence where class = 'object'"
    ).fetchone()
    assert quality["quality"]["confidence_band"] in {"low", "medium", "high"}


def test_a_caption_cannot_be_filed_as_a_capture_supported_fact(ingested):
    """The data layer refuses it. This is the collapse that lets a guess render as a fact."""
    repository, *_ = ingested
    span_id = _one_span_id(repository)
    subject = {"type": "capture", "id": str(uuid.uuid4())}
    with pytest.raises(EpistemicViolation, match="does not accept a 'capture'"):
        repository.insert_assertion(
            kind="capture",
            predicate_key="caption_is",
            subject_ref=subject,
            object_value="a waterfall",
            emit_key="test:1",
            support_span_ids=[span_id],
        )

    # And by the database, on a route that never passes through IngestRepository at all. The
    # mirror could not express this, so the sentence above was the entire guarantee; it is now
    # the explanation, and tg_assertion_kind_is_allowed() is the guarantee.
    with (
        pytest.raises(REFUSED, match="does not accept a capture assertion"),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "insert into assertion (workspace_id, kind, predicate_id, subject_ref, "
            "object_value, support_span_ids, emit_key) "
            "values (%s, 'capture', %s, %s, %s, %s::uuid[], 'test:raw:caption')",
            (
                repository.workspace_id,
                repository.predicate_id("caption_is"),
                Jsonb(subject),
                Jsonb("a waterfall"),
                [span_id],
            ),
        )


def test_no_model_can_write_a_name(ingested):
    """``name_is`` allows only ``user``. There is no code path in which a model writes a name."""
    repository, _store, _pipeline, _path, outcome = ingested
    span_id = _one_span_id(repository)
    name_is = repository.predicate_id("name_is")
    for kind in ("inference", "capture", "external"):
        with pytest.raises(EpistemicViolation):
            repository.insert_assertion(
                kind=kind,
                predicate_key="name_is",
                subject_ref={"type": "entity", "id": str(uuid.uuid4())},
                object_value="Anna",
                emit_key=f"test:name:{kind}",
                support_span_ids=[span_id],
                produced_by_run=uuid.uuid4(),
            )
        # The same row, written as raw SQL, and it names a real run and cites a real span so
        # that the epistemic class is the only thing wrong with it.
        with (
            pytest.raises(REFUSED, match=f"does not accept a {kind} assertion"),
            repository.connection.transaction(),
        ):
            repository.connection.execute(
                "insert into assertion (workspace_id, kind, predicate_id, subject_ref, "
                "object_value, support_span_ids, produced_by_run, emit_key) "
                "values (%s, %s, %s, %s, %s, %s::uuid[], %s, %s)",
                (
                    repository.workspace_id,
                    kind,
                    name_is,
                    Jsonb({"type": "entity", "id": str(uuid.uuid4())}),
                    Jsonb("Anna"),
                    [span_id],
                    outcome.run_id,
                    f"test:name:raw:{kind}",
                ),
            )


def test_a_located_person_becomes_an_occurrence_and_never_anything_more(ingested_with_a_person):
    """Invariant 3, at the exact point it is easiest to get wrong.

    A detected person IS a scene-local occurrence: it has an evidence address, so the same
    person photographed twice gives the recurrence thesis two things to connect. What it is not
    is an entity, a link, a name or an embedding, and those are four separate failures rather
    than one. The occurrence table has no column that could hold a name, which is the structural
    half; the behavioural half is that the ingest path writes none of the identity tables at
    all, which the test below this one pins.

    Q-H6, when a biometric embedding may exist at all, is still OPEN, and this does not touch
    it: no template of any kind is derived here. The distinction is the whole reason detection
    can proceed while derivation waits.
    """
    repository, store, *_ = ingested_with_a_person
    people = repository.connection.execute(
        "select primary_span_id, identity_key, quality from occurrence where class = 'person'"
    ).fetchall()
    assert len(people) == 1, people

    person = people[0]
    assert len(bytes(person["identity_key"])) == 32
    # `part`, not `label`. Schema version 2 stopped routing people through the object list, so
    # the model no longer writes free text about somebody: a part from a closed vocabulary says
    # where they are without saying anything about who they are.
    assert person["quality"]["part"] == "full_body"
    assert "label" not in person["quality"]
    assert person["quality"]["trust_tier"] == "T2"

    # The occurrence points at a REGION of the photograph, not at the whole frame. Without that
    # every unlocated person in one capture shares an identity key, and rejection memory is
    # keyed on exactly that, so they would suppress each other's proposals forever.
    span = repository.connection.execute(
        "select modality, region from evidence_span where span_id = %s",
        (person["primary_span_id"],),
    ).fetchone()
    assert span["modality"] == "frame_region"
    assert span["region"] is not None

    columns = {
        row["column_name"]
        for row in repository.connection.execute(
            "select column_name from information_schema.columns "
            "where table_schema = current_schema() and table_name = 'occurrence'"
        ).fetchall()
    }
    assert "display_name" not in columns
    assert not any("name" in column for column in columns), sorted(columns)

    row = repository.connection.execute(
        "select content_sha256 from artifact where stage_key = 'vision'"
    ).fetchone()
    from exulanica.evidence.blob import BlobId

    document = json.loads(store.get(BlobId(bytes(row["content_sha256"]))))
    assert document["person_labels"] == ["person"]
    assert document["header"]["trust_tier"] == "T2"
    assert document["header"]["epistemic_class"] == "inference"


def test_an_unlocated_person_is_asserted_but_gets_no_occurrence(ingested):
    """A detection with no box has no distinguishing address, so it cannot be an occurrence.

    The claim that somebody is present is still written, as an inference citing the whole
    image. What is not written is a row that would collide with every other boxless person in
    the same photograph under one identity key.
    """
    repository, *_ = ingested
    assert repository.rows_in_schema("occurrence") > 0, "the fixture produced no occurrences at all"
    people = repository.connection.execute(
        "select count(*) as n from occurrence where class = 'person'"
    ).fetchone()
    assert people["n"] == 0

    present = repository.connection.execute(
        "select a.object_value, a.support_span_ids from assertion a "
        "join predicate p on p.predicate_id = a.predicate_id "
        "where p.key = 'person_present' and a.kind = 'inference'"
    ).fetchall()
    assert len(present) == 1
    assert present[0]["object_value"] is None, "person_present carries no object; it is a fact"
    assert len(present[0]["support_span_ids"]) == 1


def test_the_ingest_path_never_writes_an_entity_a_link_or_a_match_proposal(ingested):
    """Invariant 3, which used to be enforced by absence and now has to be enforced by conduct.

    The SQLite mirror carried only the fourteen tables the photograph path needed, so it simply
    had no ``entity`` table and the invariant was structural: there was nowhere for a model's
    guess about who someone is to land. The spine is the whole schema, identity work included,
    so absence is no longer available and the guarantee has to be stated as what it always
    meant. A model's output stops at an occurrence, which is scene-local and carries no name.
    Promotion to an entity, a link or a ranked match proposal is a separate, user-driven act,
    and nothing on this path performs it.
    """
    repository, *_ = ingested
    # Without this the three counts below would be zero on an empty database and the test would
    # pass while proving nothing about the ingest.
    assert repository.rows_in_schema("occurrence") > 0
    assert repository.rows_in_schema("assertion") > 0

    for table in ("entity", "entity_link", "match_proposal"):
        # A fixed literal from the tuple above, never user input.
        written = repository.connection.execute(f"select count(*) as n from {table}").fetchone()
        written = written["n"]
        assert written == 0, f"the ingest wrote {written} {table} row(s)"


# -- addresses resolve ------------------------------------------------------------------


def test_every_span_rebuilds_to_the_digest_it_was_stored_under(ingested):
    repository, *_ = ingested
    rows = repository.connection.execute("select * from evidence_span").fetchall()
    assert rows
    for row in rows:
        address = address_from_span_row(row)  # raises if the digest does not match
        assert address.to_uri()


def test_an_address_resolves_to_the_original_bytes_not_to_a_rendition(ingested):
    repository, store, _pipeline, path, _outcome = ingested
    row = repository.connection.execute(
        "select * from evidence_span where modality = 'still_image'"
    ).fetchone()
    address = address_from_span_row(row)
    assert address.modality is Modality.STILL_IMAGE
    assert resolve_original_bytes(address, store) == path.read_bytes()


def test_a_region_address_crops_the_upright_original(ingested):
    """The region was normalised against display space, so the crop must apply orientation."""
    repository, store, *_ = ingested
    row = repository.connection.execute(
        "select * from evidence_span where modality = 'frame_region' limit 1"
    ).fetchone()
    address = address_from_span_row(row)
    cropped = resolve_region_image(address, store)
    assert cropped.size[0] > 0 and cropped.size[1] > 0
    assert cropped.size[0] < 160  # a region, not the whole photograph


def test_the_region_crop_refuses_an_original_over_the_pixel_budget(tmp_path):
    """``resolve_region_image`` is the second decode path, and it must inherit the same bound.

    It is reached from ``GET /evidence/{span_id}/region``, a synchronous route on the same
    threadpool as the upload, and one call at the budget costs half a gigabyte. It used to open
    and load the original itself. That was not unprotected, because importing anything under
    ``exulanica.ingest`` assigns ``Image.MAX_IMAGE_PIXELS`` process-wide, but process state is not
    a bound: reset the warning filters and a frame in Pillow's warn-only band decodes in full.
    So this asserts the explicit comparison, by its exception type and by its message, and it
    goes red if the call goes back to a bare ``Image.open``.

    No database. The bytes are put in a store directly, because a photograph over the budget
    cannot be ingested by definition and so cannot be reached through the ``ingested`` fixture.
    """
    from exulanica.evidence.address import EvidenceAddress
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.decode import MAX_PIXELS
    from PIL import Image

    width, height = 20_000, MAX_PIXELS // 20_000 + 100
    pixels = width * height
    assert MAX_PIXELS < pixels < 2 * MAX_PIXELS, "Pillow only WARNS in this band"

    store = LocalContentAddressedStore(tmp_path / "store")
    data = bomb_png(width, height)
    store.put_bytes(data)
    address = EvidenceAddress.photograph(BlobId.of_bytes(data))

    with pytest.raises(Image.DecompressionBombError) as raised:
        resolve_region_image(address, store)
    assert str(pixels) in str(raised.value), raised.value


def _dotted_name(node: ast.expr) -> str | None:
    """``a.b.c`` for a chain of ``Name`` and ``Attribute``, and ``None`` for anything else."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _pil_open_bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """The names one file can spell ``PIL.Image.open`` with, read off its own imports.

    Two sets, because the call looks different in each. The first holds names that resolve to the
    ``PIL.Image`` *module*, whose ``open`` attribute is then the call. The second holds names
    bound directly to the function, which are called bare.
    """
    modules: set[str] = set()
    direct: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "PIL":
                    modules.add(f"{alias.asname}.Image" if alias.asname else "PIL.Image")
                elif alias.name == "PIL.Image":
                    modules.add(alias.asname or "PIL.Image")
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                if node.module == "PIL" and alias.name == "Image":
                    modules.add(bound)
                elif node.module == "PIL.Image" and alias.name == "open":
                    direct.add(bound)
    return modules, direct


def _pil_image_open_calls(tree: ast.Module) -> list[ast.Call]:
    """Calls that resolve to an explicitly imported ``PIL.Image.open`` spelling."""
    modules, direct = _pil_open_bindings(tree)
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _dotted_name(node.func)
        if called is None:
            continue
        if called in direct or (called.endswith(".open") and called[: -len(".open")] in modules):
            calls.append(node)
    return calls


def _image_open_call_sites() -> list[str]:
    """Every call to ``PIL.Image.open`` under ``orimera/``, as ``module:function``.

    An AST walk rather than a grep, so the prose in a docstring that talks *about* ``Image.open``
    is not counted as a call to it. Attributed to the innermost enclosing function, and a call at
    module scope says so.

    The match is against the import bindings :func:`_pil_open_bindings` found in the same file,
    not against the literal characters ``Image.open``, so renaming the import does not hide a
    decode. The names have to reach Pillow through an import in that file: a module that never
    imports Pillow contributes nothing, so an unrelated ``path.open`` or ``store.open`` is not a
    hit.
    """
    package = pathlib.Path(pipeline_module.__file__).parent.parent
    sites: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enclosing: dict[ast.AST, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(node):
                    enclosing[inner] = node.name
        for node in _pil_image_open_calls(tree):
            where = enclosing.get(node, "<module scope>")
            sites.append(f"{path.relative_to(package.parent).as_posix()}:{where}")
    return sorted(sites)


@pytest.mark.parametrize(
    "source",
    [
        "from PIL import Image\nImage.open(blob)",
        "from PIL import Image as PILImage\nPILImage.open(blob)",
        "import PIL\nPIL.Image.open(blob)",
        "import PIL as pillow\npillow.Image.open(blob)",
        "import PIL.Image as image_module\nimage_module.open(blob)",
        "from PIL.Image import open as image_open\nimage_open(blob)",
    ],
)
def test_the_decode_boundary_recognizes_supported_pillow_open_spellings(source):
    """Import aliases do not turn a Pillow decode into a different operation."""
    assert len(_pil_image_open_calls(ast.parse(source))) == 1


@pytest.mark.parametrize(
    "source",
    [
        "from elsewhere import Image\nImage.open(blob)",
        "import pathlib\npathlib.Path('photo.jpg').open()",
        "store.open(blob)",
    ],
)
def test_the_decode_boundary_does_not_count_unrelated_open_calls(source):
    """The sweep follows Pillow imports, not the method name ``open`` by itself."""
    assert _pil_image_open_calls(ast.parse(source)) == []


def test_a_photograph_becomes_pixels_in_exactly_one_module():
    """``decode.py``'s opening sentence, checked rather than asserted.

    The whole module exists because ``Image.MAX_IMAGE_PIXELS`` and the promotion of
    ``DecompressionBombWarning`` are interpreter-global, so a second decode path anywhere inherits
    whatever the last import happened to set and nothing else. It was false once:
    ``ingest/resolve.py`` opened and loaded an original itself, reached from a synchronous route,
    with no comparison in front of it. A sentence that has been false once is worth a test.

    The sweep is over the whole of ``orimera/`` rather than over the ingest package, because the
    caller that broke it was in ingest and the next one need not be. ``orimera/corpus`` and
    ``orimera/reconstruction`` both import Pillow and are allowed to; what they must not do is
    turn somebody's uploaded bytes into pixels without asking ``decode`` first.

    **What this covers, exactly.** Every statically spelled call that reaches
    ``PIL.Image.open`` through an import binding in the file making it: ``Image.open`` after
    ``from PIL import Image``,
    ``PILImage.open`` after ``from PIL import Image as PILImage``, a spelled-out
    ``PIL.Image.open``, ``pim.open`` after ``import PIL.Image as pim``, and a bare ``_open(...)``
    after ``from PIL.Image import open as _open``. An earlier version of this sweep matched the
    literal ``Image.open`` and nothing else, so the other four walked past it with the assertion
    still green. Each of the four was planted in ``orimera/`` in turn and each turns it red.

    **What it does not cover, said rather than implied.** Pillow has other doors into a decode:
    ``ImageFile.Parser``, ``Image.frombytes``, ``open`` reached through ``getattr`` or rebound at
    run time, and any decoder that is not Pillow. This holds the one door that has actually been
    walked through. It is not a proof that there is no other, and ``decode.py``'s opening
    sentence should be read as the claim, with this as the check that catches the shape which
    broke it before.
    """
    assert _image_open_call_sites() == [
        "exulanica/corpus/decode.py:open_sensor",
        "exulanica/corpus/decode.py:probe",
    ]


def test_a_photograph_carries_the_degenerate_interval_and_the_img_track(ingested):
    repository, *_ = ingested
    row = repository.connection.execute("select * from evidence_span limit 1").fetchone()
    assert (row["t_start_ns"], row["t_end_ns"]) == (0, 1)
    assert row["track_key"] == "img"
    track = repository.connection.execute("select * from media_track").fetchone()
    assert (track["time_base_num"], track["time_base_den"]) == (1, 1_000_000_000)
    assert track["duration_ns"] == 1


def test_wall_clock_lives_in_a_clock_anchor_with_its_uncertainty(ingested):
    repository, *_ = ingested
    anchor = repository.connection.execute("select * from clock_anchor").fetchone()
    assert anchor["source"] == "container_creation_time"
    assert anchor["uncertainty_ms"] > 0
    assert anchor["t_ns"] == 0


def test_an_exif_timestamp_with_no_zone_carries_the_size_of_that_unknown(
    tmp_path, photo_dir, repository
):
    from exulanica.ingest.exif import UNKNOWN_OFFSET_UNCERTAINTY_MS

    path = write_photo(photo_dir, "nozone.jpg", offset=None)
    store = LocalContentAddressedStore(tmp_path / "blobs")
    PhotoIngestPipeline(repository, store).ingest_file(path)
    anchor = repository.connection.execute("select * from clock_anchor").fetchone()
    assert anchor["uncertainty_ms"] == UNKNOWN_OFFSET_UNCERTAINTY_MS


# -- the ledger -------------------------------------------------------------------------


def _events(repository, run_id):
    return [
        dict(row)
        for row in repository.connection.execute(
            "select * from pipeline_event where run_id = %s order by seq", (run_id,)
        ).fetchall()
    ]


def _runs_for_capture(repository, capture_id):
    """Every run recorded against one capture, in the order they were opened.

    One photograph is two runs, since the vision stage began requiring a privacy screening
    receipt for the exact bytes it sends. A receipt is keyed to a capture, and the capture does
    not exist until intake has committed, so intake is one run and the derivative stages are
    another. Both attach the capture, which is what keeps the pair recoverable from the ledger
    alone rather than from whatever the caller happened to hold on to.
    """
    return [
        row["run_id"]
        for row in repository.connection.execute(
            "select run_id from pipeline_run where capture_id = %s order by run_id", (capture_id,)
        ).fetchall()
    ]


def test_the_ledger_records_every_stage_with_timing_and_its_inputs(ingested):
    repository, _store, _pipeline, _path, outcome = ingested
    # Read across both runs of the one photograph. ``seq`` is checked per run because that is
    # what the column promises: gapless within a run, not across the pair.
    runs = _runs_for_capture(repository, outcome.capture_id)
    assert len(runs) == 2, runs
    events = []
    for run_id in runs:
        recorded = _events(repository, run_id)
        assert [e["seq"] for e in recorded] == list(range(1, len(recorded) + 1)), (
            "seq must be gapless"
        )
        events.extend(recorded)

    started = {e["stage_key"]: e for e in events if e["type"] == "stage_started"}
    assert set(started) == {"intake", "rendition", "vision"}
    # input_artifact_ids is recorded, not implied by the shape of the code. It is a uuid[], so
    # an empty list is the value in the column and not a JSON string that happens to render as
    # one.
    assert started["rendition"]["input_artifact_ids"]
    assert started["vision"]["input_artifact_ids"]
    assert started["intake"]["input_artifact_ids"] == []

    for event in (e for e in events if e["type"] == "stage_succeeded"):
        assert event["duration_ms"] is not None
        assert event["started_at"] and event["ended_at"]
        assert event["params_digest"] is not None


def test_the_ledger_refuses_an_unreviewed_stage_definition(tmp_path, repository):
    PhotoIngestPipeline(repository, LocalContentAddressedStore(tmp_path / "blobs"))
    ledger = Ledger.start_run(repository, trigger="manual")
    invented = StageSpec(
        key="publication",
        version=1,
        output_kind="invented",
        deterministic=True,
    )
    with pytest.raises(psycopg.errors.RaiseException, match="is not registered"):
        ledger.skipped(invented, reason="a caller tried to invent a stage")
    assert ledger.finish("failed")


def test_the_ledger_records_the_model_and_its_token_usage(ingested):
    repository, _store, _pipeline, _path, outcome = ingested
    vision = next(
        e
        for e in _events(repository, outcome.run_id)
        if e["type"] == "stage_succeeded" and e["stage_key"] == "vision"
    )
    cost = vision["cost"]
    assert cost["input_tokens"] == 772 and cost["output_tokens"] == 210
    assert vision["model_ref"]["model_id"] == "MiniMaxAI/MiniMax-M3"


def test_the_ledger_records_the_prompt_and_schema_version_in_the_artifact_it_points_at(
    ingested,
):
    """The replay must be able to answer 'which prompt produced this' without the source."""
    repository, store, *_ = ingested
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.vision import PROMPT_VERSION, SCHEMA_VERSION, prompt_digest

    row = repository.connection.execute(
        "select content_sha256 from artifact where stage_key = 'vision'"
    ).fetchone()
    header = json.loads(store.get(BlobId(bytes(row["content_sha256"]))))["header"]
    assert header["prompt_version"] == PROMPT_VERSION
    assert header["schema_version"] == SCHEMA_VERSION
    assert header["prompt_sha256"] == prompt_digest()


def test_a_failed_stage_is_recorded_as_failed_with_its_error_class(tmp_path, photo_dir, repository):
    class Exploding:
        model_id = "MiniMaxAI/MiniMax-M3"

        def observe(self, *, image_bytes, media_type):
            raise RuntimeError("the endpoint said no")

    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=Exploding())
    # Screened, because a vision stage with no screening receipt never reaches the model at all:
    # it reports itself unavailable and there is no failure to record. The stage has to be
    # allowed to look before "it looked and the endpoint said no" is a thing that can happen.
    outcome = ingest_observed(pipeline, repository, path)

    assert outcome.error is not None
    events = _events(repository, outcome.run_id)
    failed = next(e for e in events if e["type"] == "stage_failed")
    assert failed["stage_key"] == "vision"
    assert failed["error_class"] == "RuntimeError"
    assert "the endpoint said no" in failed["error_message"]
    assert events[-1]["type"] == "run_failed"
    # The intake stage still committed: a failed inference does not undo a capture-supported
    # record that was already true.
    assert repository.rows_in_schema("capture") == 1


# -- deletion ---------------------------------------------------------------------------


def _delete_capture(repository, **tombstone_kwargs):
    """Soft-delete the one capture and commit a tombstone. Returns both ids."""
    capture = repository.connection.execute("select capture_id from capture").fetchone()
    capture_id = capture["capture_id"]
    repository.connection.execute(
        "update capture set deleted_at = %s where capture_id = %s",
        (dt.datetime(2026, 8, 27, 12, 0, tzinfo=dt.UTC), capture_id),
    )
    tombstone_id = repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4(), **tombstone_kwargs
    )
    return capture_id, tombstone_id


def _purge_every_blob(store, tombstone_id):
    """Erase the bytes, through the only path that can: an explicit authorisation."""
    purger = privileged_purger(
        store,
        PurgeAuthorization(
            tombstone_id=str(tombstone_id),
            actor="test-operator",
            reason="the user asked for erasure and the tombstone authorises it",
        ),
    )
    for blob_id in list(store.iter_blob_ids()):
        purger.purge(blob_id)


def test_a_deliberate_re_import_after_deletion_proceeds_with_a_new_capture(ingested):
    """Decision del-3, which is easy to get backwards.

    A capture tombstone is keyed by capture id, never by blob hash. Keying it by hash would
    permanently blocklist those exact bytes, so a user who deleted something and later
    deliberately re-imported it would be silently blocked with no way to explain why. The
    re-import gets a fresh capture id and proceeds.
    """
    repository, _store, pipeline, path, _outcome = ingested
    deleted_capture, _tombstone = _delete_capture(repository, reason="user deleted it")

    outcome = pipeline.ingest_file(path)
    assert outcome.error is None
    assert outcome.capture_id != deleted_capture
    assert _events(repository, outcome.run_id)[-1]["type"] == "run_succeeded"
    live = repository.connection.execute(
        "select count(*) as n from capture where deleted_at is null"
    ).fetchone()["n"]
    assert live == 1


def test_a_deliberate_re_import_restores_purged_blob_metadata_and_bytes(ingested):
    """A new live capture must not point at a global blob row that still says purged."""
    repository, store, pipeline, path, first = ingested
    deleted_capture, tombstone_id = _delete_capture(repository, reason="user deleted it")
    _purge_every_blob(store, tombstone_id)
    repository.connection.execute(
        "update blob set purged_at=now(),storage_key=null where blob_sha256=%s",
        (first.blob_id.digest,),
    )
    assert not store.exists(first.blob_id)

    outcome = pipeline.ingest_file(path)

    assert outcome.error is None
    assert outcome.capture_id != deleted_capture
    assert store.exists(first.blob_id)
    row = repository.connection.execute(
        "select byte_size,media_type,storage_key,purged_at from blob where blob_sha256=%s",
        (first.blob_id.digest,),
    ).fetchone()
    assert row == {
        "byte_size": path.stat().st_size,
        "media_type": "image/jpeg",
        "storage_key": store.key_for(first.blob_id),
        "purged_at": None,
    }


def test_an_explicit_hash_blocklist_refuses_the_write_and_cancels_the_run(ingested):
    """The other intent, and it needs its own explicit opt-in: never let this content back in.

    The store is checked as well as the database, and the bytes are genuinely purged first.
    An earlier version of this test asserted only that the capture row rolled back, and the
    fixture had already put the bytes in the store during the successful first ingest, so
    ``store.exists`` was True before the re-import and True after it and the assertion could
    not have failed however the pipeline behaved. It was a test of nothing.
    """
    repository, store, pipeline, path, first = ingested
    _capture, tombstone_id = _delete_capture(repository, reason="never again", blocklist_hash=True)
    _purge_every_blob(store, tombstone_id)
    assert not store.exists(first.blob_id), "the fixture must start from genuinely erased bytes"
    assert list(store.iter_blob_ids()) == []

    outcome = pipeline.ingest_file(path)

    assert outcome.error is not None and "tombstoned" in outcome.error
    assert _events(repository, outcome.run_id)[-1]["type"] == "run_cancelled"
    # The database rolled back, which was never the hard part.
    assert (
        repository.connection.execute(
            "select count(*) as n from capture where deleted_at is null"
        ).fetchone()["n"]
        == 0
    )
    # The hard part. The object store is not enrolled in that transaction, so a refusal
    # discovered after the write would leave the purged bytes sitting on disk: erasure that a
    # re-import silently undoes is not erasure.
    assert not store.exists(first.blob_id), "a refused import put the purged bytes back"
    assert list(store.iter_blob_ids()) == [], "a refused import wrote to the store at all"


_STORE_WRITE_METHODS = frozenset({"put_bytes", "put_stream", "put_file"})

#: Every module in ``orimera/ingest/spine/``, written out by hand. Both sweeps below consume it,
#: and it is a literal rather than a directory listing on purpose: a required set derived from
#: the walk it is checking is a tautology, which is the exact failure the store write sweep
#: already had twice.
_SPINE_MODULES = (
    "__init__.py",
    "artifacts.py",
    "blobs.py",
    "captures.py",
    "counts.py",
    "derived.py",
    "inferences.py",
    "occurrences.py",
    "person_consent.py",
    "places.py",
    "privacy.py",
    "reconstruction_jobs.py",
    "reconstruction_scenes.py",
    "scope.py",
    "source_inputs.py",
    "spans.py",
    "stage_registry.py",
    "tombstones.py",
    "tracks.py",
)


def _swept_packages() -> list[pathlib.Path]:
    """The packages a store write could plausibly be written into.

    ``exulanica.ingest`` because that is where the pipeline lives, and ``exulanica.api`` because
    ``POST /intake`` handles uploaded bytes in a request thread. The route is the one place in
    the codebase where somebody holds a photograph and a store at the same moment, and the
    obvious thing to do with them, write the bytes to the store on arrival so they are inside a
    tombstone guard, is precisely the regression of defect 4. A sweep that stopped at the ingest
    package would have called that clean.
    """
    ingest = pathlib.Path(pipeline_module.__file__).parent
    return [ingest, ingest.parent / "api"]


def _ingest_package_modules() -> list[pathlib.Path]:
    """Every Python file in the swept packages, RECURSIVELY.

    Recursively, and that word is half of this function. The sweep below used to glob one
    level, which was correct while every stage lived in ``pipeline.py`` and stopped being
    correct the moment the stages moved into ``stages/``. Measured, with an unguarded
    ``put_bytes`` planted in a subpackage of ``orimera/ingest/``: the one-level version reported
    the package clean and passed. That is a coverage check over a set that no longer holds the
    thing being checked, which is the failure mode the route sweep already had once.

    The other half is :func:`_swept_packages`, which is the same lesson pointing at package
    boundaries rather than at directory depth.

    ``test_the_store_write_sweep_can_see_every_stage`` consumes this same walk and asserts it
    reaches the stage modules and the upload route by name, so the sweep cannot go quiet again
    by code moving away from it.
    """
    return sorted(path for package in _swept_packages() for path in package.rglob("*.py"))


def _store_write_call_sites() -> list[str]:
    """Every call to a store write method in the swept packages, as ``path:function``.

    Attributed to the INNERMOST enclosing function, so a write hidden in a closure names the
    closure. A call at module scope is reported as such rather than dropped: import-time is a
    time too, and a write that happens before any guard has run is the worst version of this.
    """
    sites: list[str] = []
    for path in _ingest_package_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enclosing: dict[ast.AST, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(node):
                    enclosing[inner] = node.name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _STORE_WRITE_METHODS
            ):
                where = enclosing.get(node, "<module scope>")
                sites.append(f"{_label(path):s}:{where}")
    return sorted(sites)


def _label(path: pathlib.Path) -> str:
    """A path relative to whichever swept package holds it, so a site names itself."""
    for package in _swept_packages():
        if path.is_relative_to(package):
            return f"{package.name}/{path.relative_to(package).as_posix()}"
    raise AssertionError(f"{path} is in no swept package")


def test_the_swept_packages_write_to_the_object_store_in_exactly_one_place():
    """The ordering guarantee is structural, so it is checked structurally.

    Every payload reaches the store through ``committed_writes``, which flushes only after the
    database transaction has committed and therefore only after the tombstone guard inside that
    transaction has passed. A second write anywhere in the ingest package reopens the hole,
    because the store is not transactional: bytes written before a refusal stay written. This
    is the same kind of source-level guard ``test_models_manifest`` uses to keep model
    identifiers out of Python source, and for the same reason, which is that a rule enforced by
    review is a rule that survives until the reviewer is busy.
    """
    assert _store_write_call_sites() == ["ingest/committed_store.py:committed_writes"], (
        "a swept package writes to the object store outside the post-commit flush: "
        f"{_store_write_call_sites()}. A write that happens before the tombstone guard cannot "
        "be rolled back by the transaction that refuses it."
    )


def test_the_store_write_sweep_can_see_every_stage():
    """The sweep above is a coverage check, so what it covers is asserted rather than assumed.

    A one-level ``glob`` was measured against a planted ``put_bytes`` in a subpackage of
    ``orimera/ingest/``: it reported the package clean and passed, while the recursive walk
    named the offending file and function. The stages then moved into ``stages/``, which is
    exactly where that blind spot was. So this asserts the walk reaches them by name.

    The two tests share ``_ingest_package_modules``. If they did not, this one would be
    asserting that some files exist rather than that the guard reads them, and a coverage check
    over a set nobody verified is the thing this is here to prevent.
    """
    walked = {_label(path) for path in _ingest_package_modules()}
    required = {
        "ingest/pipeline.py",
        "ingest/worker.py",
        "ingest/derivative_queue.py",
        "ingest/stages/__init__.py",
        "ingest/stages/writes.py",
        "ingest/stages/intake.py",
        "ingest/stages/rendition.py",
        "ingest/stages/vision.py",
        "ingest/stages/depth.py",
        # The data layer, which is where every SQL write in the ingest path now lives. Named
        # module by module rather than as a directory, because "the sweep walked some files under
        # spine/" is the coverage check that has already gone quiet twice here, once on directory
        # depth and once on a package boundary.
        "ingest/repository.py",
        *(f"ingest/spine/{module}" for module in _SPINE_MODULES),
        # The route that holds uploaded bytes and a store in the same function.
        "api/routes/intake.py",
    }
    assert required <= walked, (
        "the store write sweep no longer reads every stage: "
        f"{sorted(required - walked)} were not walked. A write in a file the sweep does not "
        "open is a write the sweep will call clean."
    )


def _spine_directory() -> pathlib.Path:
    return pathlib.Path(pipeline_module.__file__).parent / "spine"


#: A first parameter that is already a declared workspace. Two spellings, because a receiver is
#: not something a caller writes: ``self`` on ``WorkspaceScope`` itself is a declared workspace,
#: and ``self`` on anything else in this package is not.
_SCOPED_FIRST_PARAMETERS = frozenset({"scope: WorkspaceScope", "self: WorkspaceScope"})


def _public_spine_functions() -> list[tuple[str, str]]:
    """Every public function in the spine package, at any depth, as (label, first parameter).

    At any depth is the whole of this. It read ``tree.body``, so it saw module-level functions
    and nothing else, and a public METHOD on a class in a spine module satisfied a rule written
    about functions while taking whatever it liked. Measured, with
    ``def reload(self, connection, artifact_id)`` planted on ``ArtifactRow``: the old sweep
    reported the package clean. Methods and functions nested inside functions are walked now; a
    helper that genuinely needs no scope says so with a leading underscore, which is what
    ``_row``, ``_iso`` and ``_multirange`` already do.

    The first parameter is rendered as ``name: type`` so that a failure prints the signature
    rather than a bare name. A bound method's receiver is rendered as the class it binds, which
    is what makes the planted method visible: ``self: ArtifactRow`` is not a scope. A
    ``classmethod`` receives ``type[...]`` and a ``staticmethod`` receives no receiver at all,
    so both are rendered as what they actually take.
    """
    return [
        (f"{path.name}:{name}", parameter)
        for path in sorted(_spine_directory().glob("*.py"))
        for name, parameter in _functions_under(
            ast.parse(path.read_text(encoding="utf-8")), prefix="", owner=None
        )
    ]


def _functions_under(node: ast.AST, prefix: str, owner: str | None) -> list[tuple[str, str]]:
    """Public functions under one node, named by the classes and functions they are nested in.

    ``owner`` is the class a function is a method of, and it survives an ``if`` or a ``try`` in a
    class body while a nested function clears it: a function defined inside a method is not
    itself a method.
    """
    found: list[tuple[str, str]] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            found += _functions_under(child, f"{prefix}{child.name}.", child.name)
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            if not child.name.startswith("_"):
                found.append((f"{prefix}{child.name}", _first_parameter(child, owner)))
            found += _functions_under(child, f"{prefix}{child.name}.", None)
        else:
            found += _functions_under(child, prefix, owner)
    return found


def _first_parameter(node: ast.FunctionDef | ast.AsyncFunctionDef, owner: str | None) -> str:
    """How a caller has to begin the call, as ``name: type``."""
    arguments = node.args.posonlyargs + node.args.args
    if not arguments:
        return "<nothing>"
    first = arguments[0]
    decorators = {ast.unparse(decorator) for decorator in node.decorator_list}
    if owner is not None and "staticmethod" not in decorators:
        bound = f"type[{owner}]" if "classmethod" in decorators else owner
        return f"{first.arg}: {bound}"
    if first.annotation is None:
        return f"{first.arg}: <unannotated>"
    return f"{first.arg}: {ast.unparse(first.annotation)}"


def _annotations_naming_a_connection() -> list[str]:
    """Every parameter in the spine package annotated as a psycopg connection, as file:function."""
    named = []
    for path in sorted(_spine_directory().glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        enclosing: dict[ast.AST, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for inner in ast.walk(node):
                    enclosing[inner] = node.name
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.arg)
                and node.annotation is not None
                and "Connection" in ast.unparse(node.annotation)
            ):
                named.append(f"{path.name}:{enclosing.get(node, '<module scope>')}")
    return sorted(set(named))


def test_every_spine_function_takes_a_workspace_scope():
    """Nothing in the spine package is reachable by a session that named no workspace.

    78 tables are under FORCE row-level security keyed on ``current_workspace()``, which is what
    those policies compare against, and the tombstone and epistemic guards go further: they call
    ``assert_workspace_context()`` and raise when it is unset, because a guard that silently sees
    no tombstones is worse than no guard. So no path into the spine package may begin with a
    connection that has not declared one, and ``WorkspaceScope`` has no constructor that skips
    the declaration. ``test_the_prose_count_of_workspace_isolated_tables_matches_the_schema``
    is what keeps that number a measurement rather than a memory, and it is why the sentence
    above says a number at all: nothing else checks it.

    This is checked structurally because there is nothing else to check it with. There is no
    ``[tool.mypy]`` and no pyright configuration in ``pyproject.toml``, so the parameter type is
    documentation until something reads it, and this is the thing that reads it.

    Two halves, and the second is the one that closes the loophole. Requiring the first parameter
    to be a scope says nothing about a *second* parameter that is a bare connection, so the
    package is also asserted to name ``psycopg.Connection`` in exactly one file: ``scope.py``,
    which is where a raw connection is turned into a scoped one and therefore the only place the
    type may legitimately appear.

    The first half reaches methods, not only module-level functions, and that is a correction
    rather than a flourish: a public method on a row class here is a way in whose first
    parameter is ``self``, and the earlier sweep called the package clean with one planted.
    """
    unscoped = [
        f"{label} begins with {parameter}"
        for label, parameter in _public_spine_functions()
        if parameter not in _SCOPED_FIRST_PARAMETERS
    ]
    assert unscoped == [], (
        f"{unscoped}: a spine function reachable with anything but a WorkspaceScope is a spine "
        "function reachable with a connection that declared no workspace, and every guarded "
        "table would refuse it with an SQLSTATE about privileges rather than with a sentence."
    )
    assert _annotations_naming_a_connection() == ["scope.py:__init__"], (
        "a psycopg connection is named outside scope.py: "
        f"{_annotations_naming_a_connection()}. scope.py is the one place a raw connection "
        "becomes a scoped one; anywhere else it is a way around the scope."
    )


def test_the_scope_sweep_reads_every_spine_module():
    """The coverage half of the sweep above, in the same shape as the store write one.

    Without it the sweep is a rule over whatever files happen to be there, and a module renamed
    or added is a module the rule silently stops covering. Equality rather than a subset, so
    this fails both ways: a spine module that disappeared and a new one nobody listed are both
    facts worth a failure.
    """
    walked = {path.name for path in sorted(_spine_directory().glob("*.py"))}
    listed = set(_SPINE_MODULES)
    assert walked == listed, (
        f"the spine package is not what the sweeps think it is: {sorted(walked - listed)} are "
        f"walked but unlisted, {sorted(listed - walked)} are listed but not walked. Both sweeps "
        "here and the store write sweep above read this list."
    )


def _commit_a_workspace_tombstone_from_another_connection(ingest_spine) -> None:
    """Commit a tombstone from a second connection, mid-run, exactly as another actor would.

    Workspace scope rather than capture scope, because the capture this run is creating has not
    committed yet and a second connection cannot name a row it cannot see. Workspace scope needs
    no capture_id and fires the same guards, which is what is being tested.
    """
    _repository, open_another = ingest_spine
    other = open_another()
    other.insert_tombstone(scope="workspace", requested_by=uuid.uuid4(), reason="mid-run")


def _race_a_tombstone(
    ingest_spine,
    tmp_path,
    photo_dir,
    monkeypatch,
    *,
    intercept: str,
    on_call: int = 1,
    observed: bool = False,
):
    """Run one ingest with a real tombstone committed just before ``intercept`` writes.

    Nothing here simulates the guard. The interception commits a real tombstone on a real second
    connection and then calls the real method, so the refusal comes from ``tg_tombstone_guard_*``
    and arrives as an SQLSTATE. That distinction is the point: a trigger can only raise an
    SQLSTATE, an SQLSTATE reaches ``ingest_file`` through its generic handler, and the generic
    handler records the run as **failed**, which is the state a worker retries.

    ``observed`` splits the ingest into the two halves a screened one takes, and only the race
    that has to reach the vision stage asks for it: that stage will not send a photograph
    anywhere without a privacy screening receipt for its exact bytes, and a receipt cannot exist
    until intake has committed. The races against intake and against the rendition stage's
    artifact write are reached by a one-shot ``ingest_file`` and are left on it, because a
    screening they never needed would move what call number three is.
    """
    repository, _open_another = ingest_spine
    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())

    real = getattr(repository, intercept)
    fired = []
    calls = []

    def interception(*args, **kwargs):
        calls.append(True)
        # ``on_call`` exists because a method the pipeline uses in several stages cannot be
        # raced at a chosen stage by intercepting its first call. `find_artifact` is called by
        # intake's own artifact write before intake has committed, so racing there tests the
        # intake guard again rather than the stage after it.
        if len(calls) == on_call and not fired:
            fired.append(True)
            _commit_a_workspace_tombstone_from_another_connection(ingest_spine)
        return real(*args, **kwargs)

    monkeypatch.setattr(repository, intercept, interception)
    if observed:
        outcome = ingest_observed(pipeline, repository, path)
    else:
        outcome = pipeline.ingest_file(path)

    assert fired, f"the interception on {intercept} never ran, so nothing was raced"
    assert outcome.error is not None and "tombstoned" in outcome.error, outcome.error
    assert [e["type"] for e in _events(repository, outcome.run_id)][-1] == "run_cancelled", (
        "a tombstone is terminal. A run recorded as failed is one a worker retries, which is an "
        "unbounded loop against a photograph the user deleted."
    )
    return repository, store


def test_a_tombstone_racing_the_intake_transaction_leaves_the_store_untouched(
    tmp_path, photo_dir, ingest_spine, monkeypatch
):
    """The race the admission check cannot close, and the reason bytes are written last.

    The admission check runs before anything is written. A tombstone committed by another actor
    in the window between that check and the ``evidence_span`` insert is caught by the trigger
    inside the writing transaction instead, and the database rolls back. That rollback is only
    worth something if nothing has been written to the store yet, which is why every payload is
    queued during the transaction and flushed only after it commits.
    """
    repository, store = _race_a_tombstone(
        ingest_spine, tmp_path, photo_dir, monkeypatch, intercept="upsert_span"
    )
    assert repository.rows_in_schema("capture") == 0
    assert repository.rows_in_schema("blob") == 0
    assert list(store.iter_blob_ids()) == [], "the rolled-back transaction left bytes behind"


def test_a_tombstone_racing_the_vision_stage_cancels_the_run_and_writes_no_occurrence(
    tmp_path, photo_dir, ingest_spine, monkeypatch
):
    """The path a real ingest actually takes, and the one the span guard alone does not cover.

    By the time the vision stage runs, intake has committed and its bytes are legitimately in
    the store: they were written before the tombstone existed. What must not happen is the
    vision stage completing, and what must not happen more is the run being recorded as failed,
    because a failed run is retried and the retry would race the same tombstone forever.

    The capture row surviving is honest rather than ideal. A workspace tombstone means delete
    everything, and sweeping what was already committed is the job of the purge worker, which
    does not exist yet: ``purge_job`` is a table with no implementation. What DOES hold since
    migration 0011 is that nothing new is derived from tombstoned bytes; see
    ``test_no_derivative_is_written_for_tombstoned_bytes``.
    """
    repository, _store = _race_a_tombstone(
        ingest_spine, tmp_path, photo_dir, monkeypatch, intercept="insert_occurrence", observed=True
    )
    assert repository.rows_in_schema("occurrence") == 0
    assert repository.rows_in_schema("capture") == 1, (
        "intake committed before the tombstone existed"
    )


def test_an_interval_tombstone_covers_the_degenerate_photograph_interval(ingested):
    """Redacting a whole photograph is the degenerate interval redaction [0, 1)."""
    repository, *_ = ingested
    capture = repository.connection.execute("select capture_id from capture").fetchone()
    capture_id = capture["capture_id"]
    blob_row = repository.connection.execute("select blob_sha256 from blob").fetchone()
    from exulanica.evidence.blob import BlobId

    blob_id = BlobId(bytes(blob_row["blob_sha256"]))
    assert not repository.tombstone_blocks(blob_id, "img", 0, 1)
    repository.insert_tombstone(
        scope="interval",
        capture_id=capture_id,
        track_key="img",
        interval_ns=[(0, 1)],
        requested_by=uuid.uuid4(),
    )
    assert repository.tombstone_blocks(blob_id, "img", 0, 1)

    from exulanica.evidence import EvidenceAddress

    with pytest.raises(TombstonedError):
        repository.upsert_span(EvidenceAddress.photograph(blob_id))

    # The same write as raw SQL, refused by tg_tombstone_guard_span inside the transaction that
    # attempts it. The check above runs before any bytes reach the object store, which is the
    # one thing a trigger cannot do; this one holds on every route into the table, which is the
    # one thing the application check cannot do. The mirror had only the first.
    with (
        pytest.raises(REFUSED, match="tombstoned: write refused for evidence_span"),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, span_digest) "
            "values (%s, %s, 'img', 0, 1, 'still_image', %s)",
            (repository.workspace_id, blob_id.digest, bytes(range(32))),
        )


def test_a_deterministic_stage_that_changes_its_bytes_emits_an_event_and_keeps_the_old_artifact(
    tmp_path, photo_dir, repository, monkeypatch
):
    """The two hashes exist to make exactly this visible rather than silent.

    ``idempotency_key`` is what the output should be, computed before running.
    ``content_sha256`` is what it turned out to be. When they disagree on a stage that claims
    determinism, the stored artifact wins, because citations and replays already point at it,
    and the disagreement is recorded rather than absorbed.
    """
    from exulanica.ingest.stages import rendition as rendition_stage

    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store)
    first = pipeline.ingest_file(path)
    original = repository.connection.execute(
        "select artifact_id, content_sha256 from artifact where stage_key = 'rendition'"
    ).fetchone()
    original_hash = bytes(original["content_sha256"])

    # Patched on the rendition stage, which is the module that imports ``render`` and the
    # namespace the call resolves in. Patching it anywhere else leaves the real encoder in
    # place, the bytes match, and this test passes having proved nothing.
    real_render = rendition_stage.render

    def wobble(upright, spec):
        rendition = real_render(upright, spec)
        return dataclasses.replace(rendition, data=rendition.data + b"\x00")

    monkeypatch.setattr(rendition_stage, "render", wobble)
    # Remove the stored bytes so the stage recomputes instead of short circuiting on the store.
    from exulanica.evidence.blob import BlobId
    from exulanica.store.base import PurgeAuthorization, privileged_purger

    purger = privileged_purger(
        store, PurgeAuthorization(tombstone_id="t", actor="test", reason="force a recompute")
    )
    purger.purge(BlobId(original_hash))

    second = pipeline.ingest_file(path)
    assert second.error is None

    events = _events(repository, second.run_id)
    detected = [e for e in events if e["type"] == "nondeterminism_detected"]
    assert detected, "a deterministic stage produced different bytes and nobody said anything"
    assert original_hash.hex() in detected[0]["error_message"]

    kept = repository.connection.execute(
        "select artifact_id, content_sha256, needs_repair from artifact "
        "where stage_key = 'rendition'"
    ).fetchall()
    assert len(kept) == 1
    assert bytes(kept[0]["content_sha256"]) == original_hash
    # The bytes are gone and this run could not reproduce them, so the row is flagged rather
    # than repointed at bytes the identity key does not name. needs_repair is a real boolean
    # now, not the integer SQLite stored one in.
    assert kept[0]["needs_repair"] is True
    assert first.run_id != second.run_id


def test_no_derivative_is_written_for_tombstoned_bytes(
    tmp_path, photo_dir, ingest_spine, monkeypatch
):
    """R7, closed at the point where it leaked.

    The recorded defect: "Racing a deletion into the window between intake commit and the
    rendition stage leaves three objects committed, including a fresh 768px render of the
    tombstoned photograph." Nine tables carried a tombstone guard and ``artifact`` was not one of
    them, so the next stage wrote a derivative of a photograph the user had just deleted.

    Measured before migration 0011: the rendition row and its bytes were committed. After it, the
    artifact insert is refused inside the writing transaction, and because
    ``committed_writes`` flushes bytes only after that transaction commits, refusing the row
    refuses the bytes with it.

    What this does NOT close is the derivative written BEFORE the tombstone arrived. That is the
    purge queue, and it is still unimplemented.
    """
    # The THIRD call, which is the rendition stage's artifact WRITE. The measured sequence over
    # one unscreened ingest_file is intake-persist, rendition-lookup, rendition-persist: vision
    # requires a screening receipt this call does not supply, so it returns before its own two
    # look-ups. Racing call 3 commits the tombstone in the window between the rendition
    # stage deciding it has no artifact yet and inserting the one it just made, which is the
    # write migration 0011 refuses. Racing call 1 would abort intake instead and leave this
    # assertion true for the wrong reason: no rendition, because no intake.
    # test_the_race_harness_intercepts_the_rendition_stages_artifact_write pins that sequence,
    # because nothing else does and a fourth find_artifact anywhere earlier would silently move
    # this race onto a different guard.
    repository, _store = _race_a_tombstone(
        ingest_spine, tmp_path, photo_dir, monkeypatch, intercept="find_artifact", on_call=3
    )
    renditions = repository.connection.execute(
        "select count(*) as n from artifact where stage_key = 'rendition'"
    ).fetchone()["n"]
    assert renditions == 0, "a rendition of tombstoned bytes was written"


def test_the_race_harness_intercepts_the_rendition_stages_artifact_write(
    tmp_path, photo_dir, repository, monkeypatch
):
    """``on_call=3`` above is a positional count, so what sits in position three is an invariant.

    Measured over one ``ingest_file``: three calls to ``find_artifact`` through the facade, in the
    order intake-persist, rendition-lookup, rendition-persist. Nothing else pins that. A single
    extra look-up added anywhere before the rendition stage would slide the whole sequence along,
    ``test_no_derivative_is_written_for_tombstoned_bytes`` would race a different guard, and it
    would go on passing while proving something else. That is the failure this exists to make
    loud rather than silent, so the observed sequence is printed on failure.

    **RE-MEASURED 2026-09-06, and the number that matters did not move.** It was five calls,
    ending vision-lookup, vision-persist. The vision stage now requires a privacy screening
    receipt because it sends the photograph to a hosted model, and this ``ingest_file`` supplies
    none, so vision reports itself unavailable and returns before either of its look-ups. Position
    three is still the rendition persist, which is the whole reason the sibling races call 3, so
    the guarantee is unchanged and only the tail is shorter. Recorded rather than quietly edited,
    because a measured sequence that changes for a reason is worth the sentence.

    Attributed by the caller's own frame rather than by a stack search, so a call that stopped
    going through the facade would not be counted here at all, which is the other thing worth
    knowing.
    """
    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())

    real = repository.find_artifact
    observed: list[str] = []

    def record(*args, **kwargs):
        frame = inspect.currentframe().f_back
        observed.append(f"{pathlib.Path(frame.f_code.co_filename).name}:{frame.f_code.co_name}")
        return real(*args, **kwargs)

    monkeypatch.setattr(repository, "find_artifact", record)
    assert pipeline.ingest_file(path).error is None

    assert observed == [
        "pipeline.py:persist_artifact",
        "rendition.py:run",
        "pipeline.py:persist_artifact",
    ], (
        "the find_artifact sequence changed, so on_call=3 in "
        f"test_no_derivative_is_written_for_tombstoned_bytes now races {observed[2:3]} rather "
        f"than the rendition stage's artifact write. Observed: {observed}"
    )


def test_the_object_lock_is_taken_before_the_first_content_write(
    tmp_path, photo_dir, repository, monkeypatch
):
    """The purge lock is worth nothing if the ingest has already claimed the bytes.

    ``tests/test_purge.py::test_an_ingest_waits_for_a_purge_of_the_same_object`` proves the lock
    is TAKEN, behaviourally, through a real pipeline. What it cannot prove is that it is taken
    *early enough*, because an ingest that locked after ``upsert_blob`` would still block and
    still pass: it would just block having already inserted the row the purger is about to
    invalidate.

    The property is deliberately not "before the first insert", which is false and measured
    false: ``pipeline_run`` and ``pipeline_event`` rows are written first, three of them, and
    they are ledger entries about a run rather than claims on content. No purge destroys them.
    The true property is the one that matters: the lock precedes every write to a table whose
    rows say this workspace holds these bytes.
    """
    content_tables = ("blob", "capture", "media_track", "clock_anchor", "evidence_span")
    statements: list[str] = []
    connection = repository.connection
    real_execute = connection.execute

    def recorder(query, params=None, **kwargs):
        text = query if isinstance(query, str) else query.decode()
        statements.append(" ".join(text.split()))
        if params is None:
            return real_execute(query, **kwargs)
        return real_execute(query, params, **kwargs)

    # Patched after the pipeline is constructed, so register_stages is not in the trace: the
    # stage registry is a deployment fact written once, not a claim on anyone's photograph.
    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    monkeypatch.setattr(connection, "execute", recorder)
    assert pipeline.ingest_file(path).error is None

    def writes_to_content(statement: str) -> bool:
        lowered = statement.lower()
        return any(lowered.startswith(f"insert into {table} ") for table in content_tables)

    lock_at = next(
        (i for i, s in enumerate(statements) if "purge_lock_object" in s),
        None,
    )
    first_content = next((i for i, s in enumerate(statements) if writes_to_content(s)), None)
    trace = [f"{i}. {s[:60]}" for i, s in enumerate(statements[: (first_content or 0) + 2])]
    assert lock_at is not None, f"the intake never took the object lock at all. Trace: {trace}"
    assert first_content is not None, f"the intake wrote no content row at all. Trace: {trace}"
    assert lock_at < first_content, (
        f"purge_lock_object was issued at statement {lock_at}, after the first content write at "
        f"{first_content}. A lock taken after the row it protects serialises nothing: the purger "
        f"can already see a live claim on bytes it was told to destroy. Trace: {trace}"
    )
    # And say which zero this is. The statements that DO precede the lock are named, so this
    # test cannot be satisfied one day by an insert nobody noticed moving ahead of it.
    ahead = sorted(
        {s.lower().split()[2] for s in statements[:lock_at] if s.lower().startswith("insert into ")}
    )
    assert ahead == ["pipeline_event", "pipeline_run"], (
        f"{ahead} are written before the object lock. Only the ledger may be, because a ledger "
        "row is a statement about a run and not a claim on content."
    )


def test_the_artifact_guard_refuses_directly_and_not_only_through_the_pipeline(ingest_spine):
    """The guard is a database rule, so it is probed as one.

    A pipeline that stopped calling ``persist_artifact`` would not make this rule stop holding,
    and a test that only drove the pipeline could not tell the difference between the rule and
    the caller's care.
    """
    import uuid as _uuid

    from exulanica.evidence.blob import BlobId

    repository, _open_another = ingest_spine
    data = b"bytes that are about to be deleted"
    blob = BlobId.of_bytes(data)
    repository.upsert_blob(blob, byte_size=len(data), media_type="image/jpeg", storage_key="k")
    capture = repository.insert_capture(blob, device_id="probe", started_at=None)
    repository.insert_tombstone(
        scope="capture", capture_id=capture.capture_id, requested_by=_uuid.uuid4()
    )
    repository.connection.execute(
        "update capture set deleted_at = now() where capture_id = %s", (capture.capture_id,)
    )

    with pytest.raises(TombstonedError):
        repository.insert_artifact(
            artifact_id=_uuid.uuid4(),
            kind="rendition",
            source_blob=blob,
            stage_key="rendition",
            stage_version=1,
            params_digest=bytes(32),
            input_digest=bytes(32),
            idempotency_key="probe",
            content_sha256=bytes(32),
            storage_key="k2",
            byte_size=1,
            produced_by_event=None,
        )


def test_only_an_allowlisted_table_can_be_counted(repository):
    """The one statement in this package that interpolates a name into SQL, and its only guard.

    ``rows_in_schema`` builds ``select count(*) from <table>`` by formatting, because a table
    name cannot be a bound parameter. The allowlist is therefore not a convenience for callers,
    it is the whole of what stands between this function and an injection, and it had no test.
    """
    with pytest.raises(ValueError, match="not a countable table: 'capture; drop table capture'"):
        repository.rows_in_schema("capture; drop table capture")
    # Still there, which is the half of the claim a ValueError alone does not make.
    assert repository.rows_in_schema("capture") == 0


def test_a_row_count_is_schema_wide_and_not_workspace_scoped(ingest_spine, workspace_id):
    """``rows_in_schema`` is named for what it counts, and this is the measurement behind it.

    It was called ``count``, on a class every one of whose other methods filters on
    ``workspace_id``, and the name invited a reading the number never supported. Four of the
    thirteen countable tables have no ``workspace_id`` column at all. The other nine are under
    FORCE row-level security, which the owner bypasses, and every caller of this function is a
    test connecting as the owner.

    So the honest sentence is the one asserted here: two workspaces write one capture each into
    one schema, and both of them are told there are two. A zero from this function means "no
    rows in this schema", never "none of mine", and a test that read it the second way would be
    asserting something the database does not say.
    """
    from exulanica.evidence.blob import BlobId
    from exulanica.ingest.repository import IngestRepository

    repository, open_another = ingest_spine
    other_workspace = uuid.uuid4()
    elsewhere = IngestRepository(open_another().connection, other_workspace)
    assert other_workspace != workspace_id

    superuser = repository.connection.execute(
        "select rolsuper from pg_roles where rolname = current_user"
    ).fetchone()["rolsuper"]
    assert superuser, (
        "this test is only meaningful on a connection that bypasses row-level security, which "
        "is the connection every caller of rows_in_schema actually uses"
    )

    for index, repo in enumerate((repository, elsewhere)):
        data = f"probe bytes {index}".encode()
        blob = BlobId.of_bytes(data)
        repo.upsert_blob(
            blob, byte_size=len(data), media_type="image/jpeg", storage_key=f"k{index}"
        )
        repo.insert_capture(blob, device_id="probe", started_at=None)

    assert repository.rows_in_schema("capture") == 2
    assert elsewhere.rows_in_schema("capture") == 2, (
        "rows_in_schema returned a workspace-scoped number, which its name says it does not. "
        "Either the name or the query is now wrong, and they cannot both be right."
    )
