"""The two gates that stand in front of personal media and in front of video.

Neither is a policy document here. Each is the half of a gate that code can hold, written so that
crossing it is a test failure rather than a judgement call somebody makes under deadline.

**Video.** A photograph is modelled as a single-sample ``img`` track carrying ``[0, 1)``. A motion
photograph, a burst or an animation is not that: it carries a real sequence with real presentation
times. Ingesting one today would keep frame one, store a `capture` whose EXIF and `pixel_size_is`
describe the whole file, and address every span at `img` on a blob whose other frames nothing can
cite. That is wrong evidence rather than missing evidence, so it is refused.

**Personal media.** Open item P-1, when a biometric template may exist at all, is unanswered, and
`docs/domain-and-evidence-model.md` section 9.2 says identity work must not begin before it is.
The line the system draws is at the template: a detected person becomes a scene-local occurrence
with an evidence address and nothing else. Caption vectors are now an explicit, opt-in writer;
the default worker has no injected caption pass. These tests keep that exception confined and
continue to forbid biometric writers.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from exulanica.ingest.decode import UNREADABLE, open_upright, probe
from exulanica.ingest.vision import OBSERVATION_SCHEMA
from PIL import Image

_PACKAGE = Path(__file__).resolve().parents[1] / "exulanica"


# -- the video gate ---------------------------------------------------------------------------


def _animation(fmt: str) -> bytes:
    frames = [Image.new("RGB", (48, 32), colour) for colour in ((220, 30, 30), (30, 60, 220))]
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format=fmt, save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    return buffer.getvalue()


@pytest.mark.parametrize("fmt", ["GIF", "WEBP"])
def test_a_multi_frame_container_is_refused_by_the_header_probe(fmt):
    """Refused for the price of a header parse, before any decode."""
    with pytest.raises(UNREADABLE, match="holds 2 frames"):
        probe(_animation(fmt))


@pytest.mark.parametrize("fmt", ["GIF", "WEBP"])
def test_a_multi_frame_container_is_refused_by_the_decode_too(fmt):
    """Both entry points, because a caller that reached the second bypassed the first."""
    with pytest.raises(UNREADABLE, match="holds 2 frames"):
        open_upright(_animation(fmt))


def test_the_refusal_names_the_video_path_rather_than_calling_the_file_corrupt():
    """An operator who is told "unreadable" will re-export the file and try again."""
    try:
        probe(_animation("GIF"))
    except UNREADABLE as exc:
        message = str(exc)
    assert "v:0 track" in message
    assert "video path applies to it unchanged" in message


def test_an_ordinary_single_frame_photograph_still_passes(photo_dir):
    from conftest import photo_bytes

    assert probe(photo_bytes(orientation=6)) == (100, 160)


def test_the_capture_pipeline_reaches_the_refusal_rather_than_ingesting_frame_one(
    tmp_path, photo_dir, repository
):
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    path = photo_dir / "burst.gif"
    path.write_bytes(_animation("GIF"))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store).ingest_file(path)

    assert outcome.error is not None
    assert repository.connection.execute("select count(*) as n from capture").fetchone()["n"] == 0
    assert (
        repository.connection.execute("select count(*) as n from evidence_span").fetchone()["n"]
        == 0
    )


# -- the personal-media gate ------------------------------------------------------------------


#: Every spelling of "put a row into the embedding table" this scan can see.
#:
#: `insert into` and `copy`, quoted or bare, over SQL as well as Python, because a writer added
#: inside a migration or a plpgsql function is a writer.
#:
#: **The trailing `[a-z0-9_]*` is the partition, and leaving it off was a real hole.** `embedding`
#: is `partition by list (workspace_id)` and `provision_workspace` creates one child table per
#: workspace as `embedding_ws_<hex>`. A writer naming the child directly stores exactly the same
#: vector, and `\b` does not fire after `embedding` when the next character is an underscore, so
#: `insert into embedding_ws_9f2c...` matched nothing at all.
#:
#: **What it still cannot see, stated rather than implied.** This is a text scan. SQL composed
#: through `psycopg.sql` -- `sql.SQL("insert into {}").format(sql.Identifier("embedding"))` --
#: is the idiom `exulanica/db/roles.py` is written in, and no regex over source can follow it.
#: The scan is a tripwire on the ordinary spelling, not a proof. The proof that no template
#: exists is the pair of runtime assertions below it, which count rows after a real ingest and
#: after a real answer.
_EMBEDDING_WRITER = re.compile(
    r"""(?:insert\s+into|copy)\s+"?embedding[a-z0-9_]*"?""", re.IGNORECASE
)

#: The modules the answer path is built from. `exulanica.graph` is here because the read model
#: the answer's Selection resolves against is assembled there, `exulanica.store` is what turns a
#: citation back into original bytes, and `exulanica.api/routes` is where the handler for
#: POST /selection/ask lives. That last one was missing at first, which left the HTTP entry
#: point of the answer path outside the scan that exists to guard it: `client.embed(...)` added
#: to the route would have tripped nothing.
_ANSWER_PATH = ("selection", "graph", "store", "api")


def test_nothing_in_the_package_writes_an_embedding():
    """Keep the historical evidence node callable under the current opt-in contract.

    The old name predates caption retrieval and no longer means there is no writer anywhere.
    This test now proves the default worker has no injected embedding pass and that the sole
    permitted writer stays in the audited caption module. Biometric writers remain forbidden.
    The caption lifecycle tests separately verify physical purge under the purge role.
    """
    from exulanica.ingest.worker import DerivativeWorker

    # Construction starts no I/O; collaborators are unused until the worker is run.
    worker = DerivativeWorker(None, None, frozenset())
    assert worker._embedding_pass is None
    writers = []
    for path in sorted([*_PACKAGE.rglob("*.py"), *_PACKAGE.rglob("*.sql")]):
        text = path.read_text(encoding="utf-8")
        if path == _PACKAGE / "epistemics" / "caption_embeddings.py":
            continue  # Authorized caption vectors, runtime scope pinned in test_companion_matching.
        for match in _EMBEDDING_WRITER.finditer(text):
            line = text[: match.start()].count("\n") + 1
            writers.append(f"{path.relative_to(_PACKAGE.parent)}:{line}")
    assert not writers, f"an embedding writer appeared: {writers}"


def test_the_answer_path_does_not_name_the_table_a_template_would_live_in():
    """Preserve the historical node while confining opt-in caption-vector access.

    Question orchestration may call its helpers; it cannot invoke embed or query the vector
    table directly. Runtime tests verify this exception stores no person/occurrence template.
    """
    named = []
    scanned = 0
    for package in _ANSWER_PATH:
        directory = _PACKAGE / package
        assert directory.is_dir(), f"{package} is not a package; this scan would pass over nothing"
        for path in sorted(directory.rglob("*.py")):
            scanned += 1
            if path == _PACKAGE / "selection" / "embeddings.py":
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in (r"\bembedding\b", r"\.embed\("):
                for match in re.finditer(pattern, text):
                    line = text[: match.start()].count("\n") + 1
                    named.append(f"{path.relative_to(_PACKAGE.parent)}:{line}")
    # A scan over zero files passes. The directories are named as bare strings, so a rename or a
    # move would silently empty this assertion rather than break it.
    assert scanned >= 20, f"the answer-path scan opened only {scanned} files"
    assert not named, f"the answer path reached for a vector: {named}"


def test_the_vision_schema_has_no_field_a_name_could_arrive_in():
    """A model cannot propose an identity if the schema has nowhere to put one."""
    encoded = repr(OBSERVATION_SCHEMA)
    for forbidden in ("name", "identity", "person_id", "who", "embedding"):
        assert f"'{forbidden}'" not in encoded, forbidden


def test_a_person_occurrence_carries_an_address_and_no_template(tmp_path, photo_dir, repository):
    """The line is at the template. "Somebody is here" is a box; it is not face geometry."""
    import copy

    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo

    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    located = [entry for entry in payload["objects"] if entry["label"] == "person"]
    assert len(located) == 1
    located[0]["box"] = {"x": 0.55, "y": 0.1, "w": 0.2, "h": 0.6}

    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    outcome = ingest_observed(pipeline, repository, path)
    assert outcome.error is None

    rows = repository.connection.execute(
        "select o.identity_key, o.quality, s.modality from occurrence o "
        "join evidence_span s on s.span_id = o.primary_span_id "
        "where o.class = 'person'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["modality"] == "frame_region"
    assert rows[0]["identity_key"] is not None
    # TIGHTENED 2026-09-06 with schema version 2. The detector's own free-text word for what it
    # saw is gone: it was evidence about the detection and it was also a description of a person,
    # and "woman in a red coat" is a sentence nobody consented to. `part` is a closed vocabulary
    # of visible traces, which locates somebody without characterising them.
    assert set(rows[0]["quality"]) <= {"confidence_band", "part", "trust_tier"}
    assert "label" not in rows[0]["quality"]
    assert repository.connection.execute("select count(*) as n from embedding").fetchone()["n"] == 0
