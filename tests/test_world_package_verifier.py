"""Why the consent receipts are still not in a World Memory Package, held in place by tests.

A signed package is unrecallable. Once a recipient holds one, the only thing that constrains what
they believe about the people in it is what the package says and what an offline verifier can
prove from it. These tests guard the two facts that decide whether the presentation consent
receipts may ever be projected.

**The required-path set is checked before the signature, so it is part of the profile contract.**
Adding a path to :data:`REQUIRED_PAYLOAD_PATHS` does not merely reject future packages; it makes
every already-signed ``exulanica-wmp-1.0`` package fail verification while its bytes and its
Ed25519 signature are still perfectly sound. That is why carrying consent is a profile version
bump and not a new required file under 1.0. An unlisted path, by contrast, rides along without
disturbing 1.0 verification at all, which is the route a bump would take.

**The offline fold is not yet the database's rule.** :func:`resolve_presentation` and the SQL
``person_consent_is_granted`` from migration 0037 return different answers for the same receipts,
and in one case the offline answer draws a person the source system says revoked their likeness
consent. Until they agree, projecting receipts and telling a recipient to resolve them offline
would sign a claim the source system contradicts.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from exulanica.canonical import canonical_json
from exulanica.consent.states import ConsentTransition, resolve_presentation
from exulanica.world_package import package as package_module
from exulanica.world_package.package import (
    MANIFEST_PATH,
    PROFILE_ID,
    PROFILE_VERSION,
    REQUIRED_PAYLOAD_PATHS,
    SIGNATURE_PATH,
    PackageError,
    build_manifest,
    canonical_file,
    profile_bytes,
    sign_manifest,
    verify_package,
)

#: The path a 1.1 profile would carry the receipts at. It is deliberately not a required path of
#: any profile this repository can verify today; see the module docstring.
CONSENT_PATH = "consent/presentation.json"

_CRATE: dict[str, Any] = {
    "@context": "https://w3id.org/ro/crate/1.2/context",
    "@graph": [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"},
        },
        {
            "@id": "./",
            "@type": "Dataset",
            "conformsTo": {"@id": PROFILE_ID},
            "description": "A package built to exercise the verifier.",
            "name": "Verifier WMP",
        },
        {"@id": PROFILE_ID, "@type": ["CreativeWork", "Profile"]},
        {
            "@id": "#responsible-ai-boundary",
            "@type": "Dataset",
            "http://purl.org/dc/terms/conformsTo": [
                "http://mlcommons.org/croissant/1.0",
                "http://mlcommons.org/croissant/RAI/1.0",
            ],
        },
    ],
}


def _signed_package(root: Path, *, extra: dict[str, Any] | None = None) -> Path:
    """Build and sign a complete 1.0 package, plus any extra unlisted payload files.

    The payload set is derived from :data:`REQUIRED_PAYLOAD_PATHS` rather than copied from it, so
    a change to the profile's required set cannot leave this builder quietly producing a package
    that is incomplete for a reason unrelated to what the test is asserting.
    """
    values: dict[str, Any] = {path: {"state": "unavailable"} for path in REQUIRED_PAYLOAD_PATHS}
    # The three the profile validator reads rather than merely inventories.
    values["external/fetch.json"] = {"items": []}
    values["ro-crate-metadata.json"] = _CRATE
    values.update(extra or {})
    files = {path: canonical_file(value) for path, value in values.items()}
    files["wmp/profile.json"] = profile_bytes()
    manifest_bytes = canonical_file(build_manifest(files))
    signature = sign_manifest(manifest_bytes, Ed25519PrivateKey.generate())
    files[MANIFEST_PATH] = manifest_bytes
    files[SIGNATURE_PATH] = canonical_file(signature)
    for path, data in files.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return root


def _signature_is_intact(root: Path) -> bool:
    """Verify the Ed25519 signature straight from signature.json, using no verifier code path."""
    signature = json.loads((root / SIGNATURE_PATH).read_text(encoding="utf-8"))
    manifest = json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))
    payload = canonical_json(
        {
            "manifest_sha256": package_module._sha256((root / MANIFEST_PATH).read_bytes()),
            "merkle_root_sha256": manifest["merkle_root_sha256"],
            "profile_version": signature["profile_version"],
        }
    )
    public_key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(signature["public_key_base64"], validate=True)
    )
    try:
        public_key.verify(base64.b64decode(signature["signature_base64"], validate=True), payload)
    except Exception:
        return False
    return True


def test_adding_a_required_path_retroactively_breaks_an_already_signed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches somebody carrying consent by adding a path to the 1.0 required set.

    The package under test is byte-intact and its signature still verifies. It fails anyway, and
    it would fail in every recipient's hands the moment they upgraded their verifier. This is the
    whole reason the consent receipts need a profile version bump rather than a new required file.
    """
    package = _signed_package(tmp_path / "package")
    assert verify_package(package).file_count == len(REQUIRED_PAYLOAD_PATHS) == 18

    monkeypatch.setattr(
        package_module, "REQUIRED_PAYLOAD_PATHS", REQUIRED_PAYLOAD_PATHS | {CONSENT_PATH}
    )
    with pytest.raises(PackageError, match="incomplete") as raised:
        verify_package(package)
    assert CONSENT_PATH in str(raised.value)
    assert _signature_is_intact(package), "the package itself must still be cryptographically sound"


def test_the_required_path_gate_rejects_before_the_signature_is_ever_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches a reordering of verify_package that would make the required-path gate survivable.

    If the Ed25519 verify ran first, a deployment could add a required path and tell holders of
    old packages that only the signature matters. It does not: MEASURED 2026-09-07, a package with
    a deliberately corrupted signature and a newly required path is refused for the missing path
    and the signature is never reached. package.py checks the set at line 311 and verifies the
    signature at line 352, and this test is what keeps those in that order.
    """
    package = _signed_package(tmp_path / "package")
    signature = json.loads((package / SIGNATURE_PATH).read_text(encoding="utf-8"))
    signature["signature_base64"] = base64.b64encode(b"\x00" * 64).decode("ascii")
    (package / SIGNATURE_PATH).write_bytes(canonical_file(signature))
    assert not _signature_is_intact(package)

    monkeypatch.setattr(
        package_module, "REQUIRED_PAYLOAD_PATHS", REQUIRED_PAYLOAD_PATHS | {CONSENT_PATH}
    )
    with pytest.raises(PackageError) as raised:
        verify_package(package)
    message = str(raised.value)
    assert "incomplete" in message
    assert "signature" not in message.lower() and "Ed25519" not in message


def test_an_unlisted_payload_path_does_not_disturb_wmp_1_0_verification(tmp_path: Path):
    """Catches a future 'reject unknown paths' rule closing the only route a profile bump has.

    A bumped profile carries consent at an OPTIONAL path. That works today only because the
    verifier requires the manifest to inventory exactly the files on disk and requires the
    required set to be a subset, never an equality. Tighten either into 'no path the profile does
    not name' and every 1.0 package holding a 1.1 payload becomes unverifiable.
    """
    package = _signed_package(
        tmp_path / "package",
        extra={
            CONSENT_PATH: {
                "items": [
                    {
                        "decided_at": "2026-09-07T12:00:00Z",
                        "granted": True,
                        "receipt_digest": "00" * 32,
                        "scope": "likeness",
                    }
                ],
                "profile": "exulanica-person-presentation-consent-v1",
            }
        },
    )
    report = verify_package(package)
    assert report.file_count == len(REQUIRED_PAYLOAD_PATHS) + 1 == 19
    assert report.profile_version == PROFILE_VERSION


# --------------------------------------------------------------------------------------------
# The offline fold against the database's rule.
#
# Each case below was run on BOTH sides on 2026-09-07 with identical receipts. The SQL side is the
# verbatim body of person_consent_is_granted (migration 0037, lines 158-172) evaluated over a
# VALUES list, so no table was read and nothing was written. The Python side is
# resolve_presentation, reached the way exulanica/ingest/person_state.py:82-89 reaches it.
#
#   ORDER BY (region_key is not null) desc, sequence desc     <- the database
#   sorted(key=lambda item: (item.decided_at, item.receipt_digest))   <- the fold
#
# Those are not the same ordering, and ConsentTransition carries no `sequence` and no
# `valid_until` for the fold to use even if it wanted to.
# --------------------------------------------------------------------------------------------

_NOW = dt.datetime(2026, 9, 7, 12, 0, tzinfo=dt.UTC)


def _receipt(scope: str, granted: bool, when: dt.datetime, digest: bytes) -> ConsentTransition:
    return ConsentTransition(
        scope=scope, granted=granted, actor="operator", decided_at=when, receipt_digest=digest
    )


def test_the_offline_fold_is_not_yet_the_database_rule_so_receipts_must_not_be_projected():
    """Catches the moment the fold learns sequence, valid_until and region precedence.

    This test pins a disagreement rather than a behaviour, and it is meant to go red: the day
    resolve_presentation agrees with person_consent_is_granted on all three receipt sets is the
    day the blocker on projecting consent into a World Memory Package lifts. Delete the case that
    now agrees, and when none are left, delete this test and the note in projector.py with it.

    The third case is the one that forbids projection outright rather than merely delaying it.
    Every disagreement here is a wrong answer, but two of them err towards hiding somebody. The
    third draws a person the database says revoked their likeness consent, and `shown` is not in
    MASKED_STATES, so nothing downstream catches it.

    **One side of the comparison is a transcript, and that is the standing weakness here.** The
    ``database_drawn`` values were read from a psql session and written down; this test executes
    no SQL, because the fold it checks is pure and gets no database fixture. So it is armed for
    the fold changing and blind to the SQL changing: a migration that moved
    ``person_consent_is_granted`` towards the fold would erase the divergence and leave this test
    green. Closing that needs this case table driven against a live schema, which is a bigger
    change than the blocker it guards.
    """
    cases = [
        (
            # An expired temporary_hide. MEASURED: SQL says likeness granted=t, temporary_hide
            # granted=f, because `valid_until > clock_timestamp()` drops the expired receipt. The
            # fold has neither valid_until nor any notion of now, so the hide never lifts.
            "expired temporary_hide",
            (
                _receipt("likeness", True, _NOW - dt.timedelta(hours=2), b"\x01" * 32),
                _receipt("temporary_hide", True, _NOW - dt.timedelta(hours=2), b"\x02" * 32),
            ),
            {"database_drawn": True, "fold_state": "hidden", "fold_drawn": False},
        ),
        (
            # A region-scoped grant and a LATER subject-wide revoke. MEASURED: SQL says granted=t,
            # because a region-scoped receipt outranks a subject-wide one whatever the times are.
            # person_state.py hands the fold both receipts and the fold takes the later one.
            "region grant outranked by nothing, then revoked subject-wide",
            (
                _receipt("likeness", True, _NOW - dt.timedelta(hours=2), b"\x01" * 32),
                _receipt("likeness", False, _NOW - dt.timedelta(hours=1), b"\x02" * 32),
            ),
            {"database_drawn": True, "fold_state": "unknown", "fold_drawn": False},
        ),
        (
            # Two likeness receipts at the SAME instant: sequence 0 granted, sequence 1 revoked.
            # MEASURED: SQL says granted=f. record_consent takes effective_at from its caller and
            # exulanica/ingest/spine/person_consent.py says sequence numbers exist precisely
            # because "two receipts in the same second are common". The fold breaks the tie on
            # receipt_digest, so which decision wins depends on a hash, not on the decision order.
            "same-instant grant and revoke",
            (
                _receipt("likeness", False, _NOW, b"\x01" * 32),
                _receipt("likeness", True, _NOW, b"\xff" * 32),
            ),
            {"database_drawn": False, "fold_state": "shown", "fold_drawn": True},
        ),
    ]
    for name, receipts, expected in cases:
        resolved = resolve_presentation(receipts)
        # The divergence is asserted FIRST, and the order is the point. `drawn` is exactly
        # `state == "shown"`, and every case pins `fold_drawn` to match `fold_state`, so once the
        # state assertion has passed the divergence assertion cannot fail: it was a tautology
        # sitting behind the two lines that would trip first. The tripwire still went red, but on
        # `assert 'unknown' == 'shown'`, and the reader never saw the sentence below telling them
        # what to do about it. A tripwire whose message is unreachable is half a tripwire.
        assert resolved.drawn != expected["database_drawn"], (
            f"{name}: the fold now agrees with person_consent_is_granted. If every case here "
            "agrees, the offline verifier can be trusted with the receipts and the consent path "
            "may be projected under a bumped profile."
        )
        assert resolved.state == expected["fold_state"], name
        assert resolved.drawn == expected["fold_drawn"], name

    unsafe = resolve_presentation(cases[2][1])
    assert unsafe.drawn is True and unsafe.masked is False, (
        "the same-instant case draws somebody the database says revoked; `shown` is not in "
        "MASKED_STATES, so no later stage re-hides them"
    )
