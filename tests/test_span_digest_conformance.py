"""Cross-implementation conformance vectors for the v1 span digest.

``span_digest`` is only useful if a reader that is not this program computes the same 32 bytes
from the same address. Nothing in Python can prove that. What Python can do is state the answer
precisely enough that disagreement is detectable: for each vector this file pins the digest
input, **the exact canonical JSON bytes**, and the digest over them.

The canonical bytes are the part that matters. A second implementation that agrees on the digest
but not on the bytes agrees by luck, and the vector set exists so that the first disagreement is
found on a fixture rather than on somebody's citation. ``scripts/verify_canonical_conformance.mjs``
is the independent reader: it parses the same file with a different JSON stack and a different
SHA-256, and it is what the ratification in ADR-0014 rests on.

The vectors deliberately include the cases where two JSON writers are most likely to differ:

*   a negative ``t_start_ns``, which is real whenever a container's ``start_pts`` is later than
    track zero;
*   non-ASCII text, which JCS emits literally as UTF-8 and many writers escape as ``\\uXXXX``;
*   a quote, a backslash and a control character, which pin which short escapes are used;
*   an absent optional next to a present one, which pins "omit the key" rather than "write null".
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.evidence import BlobId, EvidenceAddress, Modality, TimeInterval
from exulanica.evidence.address import SPAN_FORMAT_VERSION, TextAnchor
from exulanica.evidence.blob import HASH_ALGORITHM
from exulanica.evidence.region import DisplayGeometry, Rect, Region

VECTORS = Path(__file__).resolve().parent / "vectors" / "span_digest_v1.json"

PROFILE = "exulanica.span-digest-conformance/v1"

_BLOB = BlobId.of_bytes(b"exulanica conformance vector")
_ARTIFACT = uuid.UUID("8f14e45f-ceea-567d-861d-4f5b1b2a3c4d")


def _addresses() -> list[tuple[str, EvidenceAddress]]:
    """One address per case, named by what it pins."""
    return [
        ("whole photograph", EvidenceAddress.photograph(_BLOB)),
        (
            "region in a photograph, upright display space",
            EvidenceAddress.photograph(
                _BLOB,
                region=Region(
                    rect=Rect.from_normalised(0.312, 0.22, 0.184, 0.401),
                    display=DisplayGeometry(w=4032, h=3024, rotation=0),
                ),
            ),
        ),
        (
            "video interval starting before track zero",
            EvidenceAddress(
                blob_id=_BLOB,
                track_key="v:0",
                interval=TimeInterval(-1_000_000_001, 18_250_000_000),
                modality=Modality.VIDEO_TIME,
            ),
        ),
        (
            "region in a rotated video frame",
            EvidenceAddress(
                blob_id=_BLOB,
                track_key="v:1",
                interval=TimeInterval(0, 1),
                modality=Modality.FRAME_REGION,
                region=Region(
                    rect=Rect(0, 0, 1_000_000, 1_000_000),
                    display=DisplayGeometry(w=1920, h=1080, rotation=270, sar_num=4, sar_den=3),
                ),
            ),
        ),
        (
            "audio interval on a 48 kHz tick boundary",
            EvidenceAddress(
                blob_id=_BLOB,
                track_key="a:0",
                interval=TimeInterval(20_833, 62_500),
                modality=Modality.AUDIO_TIME,
            ),
        ),
        (
            "transcript span with no exact quote",
            EvidenceAddress(
                blob_id=_BLOB,
                track_key="a:0",
                interval=TimeInterval(0, 1_000),
                modality=Modality.TRANSCRIPT_TEXT,
                text_anchor=TextAnchor(_ARTIFACT, 0, 12),
            ),
        ),
        (
            "transcript span whose quote needs every escape decision",
            EvidenceAddress(
                blob_id=_BLOB,
                track_key="a:0",
                interval=TimeInterval(0, 1_000),
                modality=Modality.TRANSCRIPT_TEXT,
                # Non-ASCII stays literal under JCS; the quote, the backslash and the tab are
                # where two writers pick different short escapes.
                text_anchor=TextAnchor(_ARTIFACT, 0, 12, exact='caf\u00e9 "x"\\y\tz\u00e9\u0301'),
            ),
        ),
    ]


def build_document() -> dict[str, Any]:
    vectors = []
    for name, address in _addresses():
        encoded = canonical_json(address.as_digest_input())
        vectors.append(
            {
                "name": name,
                "uri": address.to_uri(),
                "digest_input": address.as_digest_input(),
                # The bytes are ASCII-safe only after escaping, so they travel as a JSON string
                # and a reader compares against the UTF-8 encoding of that string.
                "canonical_json": encoded.decode("utf-8"),
                "canonical_json_byte_length": len(encoded),
                "span_digest_sha256": address.span_digest_hex,
            }
        )
    return {
        "profile": PROFILE,
        "span_format_version": SPAN_FORMAT_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "canonicalisation": "rfc8785-subset",
        "vectors": vectors,
    }


def test_the_retained_vectors_match_what_this_build_computes():
    """The pin. Any change to the digest input, the canonical form or the hash fails here.

    That is the point: each of those is a `span_format_version` event rather than a patch, so a
    change that reaches this file without one is a mistake, and a change that reaches it with
    one has to rewrite the fixture deliberately.
    """
    assert json.loads(VECTORS.read_text(encoding="utf-8")) == build_document()


def test_every_vector_round_trips_through_its_permalink():
    """A citation string that parsed back to a different address would be worthless."""
    from exulanica.evidence.address import parse_uri

    for vector in json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]:
        parsed = parse_uri(vector["uri"])
        assert parsed.span_digest_hex == vector["span_digest_sha256"], vector["name"]


def test_no_digest_input_carries_a_null():
    """Absent, never null. `{"a":1}` and `{"a":1,"b":null}` are different bytes.

    A writer that emitted nulls for absent optionals would produce a different digest for the
    same address, and would do it silently, because both documents are valid JSON.
    """
    for _, address in _addresses():
        assert "null" not in canonical_json(address.as_digest_input()).decode("utf-8")


def test_the_digest_input_never_carries_the_row_identity():
    """`span_id` and `hint` are properties of the row, not of the address it holds."""
    for _, address in _addresses():
        keys = set(address.as_digest_input())
        assert "span_id" not in keys and "hint" not in keys
        assert keys <= {
            "span_format_version",
            "blob_sha256",
            "track_key",
            "t_start_ns",
            "t_end_ns",
            "modality",
            "region",
            "text_anchor",
        }, keys


def test_the_blob_hash_enters_the_digest_as_lowercase_hex():
    """Not base64url. The ni URI is a rendering; the digest input matches what the database
    prints, so a row and a recomputation are comparable by eye as well as by equality.
    """
    for _, address in _addresses():
        value = address.as_digest_input()["blob_sha256"]
        assert value == address.blob_id.hex
        assert len(value) == 64 and value == value.lower()


def test_non_ascii_is_emitted_literally_rather_than_escaped():
    """JCS emits UTF-8; a writer that escaped to \\uXXXX would hash differently."""
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    quoted = [v for v in document["vectors"] if "every escape decision" in v["name"]]
    assert len(quoted) == 1
    canonical = quoted[0]["canonical_json"]
    assert "café" in canonical
    assert "\\u00e9" not in canonical
    # The three that must be escaped, and are escaped short.
    assert '\\"' in canonical and "\\\\" in canonical and "\\t" in canonical


if __name__ == "__main__":  # pragma: no cover - regeneration is a deliberate act
    VECTORS.write_text(
        json.dumps(build_document(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {VECTORS}")
