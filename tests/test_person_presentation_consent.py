"""Default deny, three separate consents, and an outline that survives a detector re-run.

The design note this pins is ``docs/person-presentation-consent.md``. It was written because the
old gate asked a reviewer one yes-or-no question about a whole photograph, and the reviewer of the
retained bowl collection answered "no visible people" over frames containing the arms, hands and
clothing of diners at the edge. Four failures follow from that, and each has a test here:

*   **A region nobody decided about was treated as absent.** Now it resolves to ``unknown`` and
    ``unknown`` masks, and there is no argument anywhere that starts it anywhere else.
*   **Presence, naming and likeness were one bit.** A person can be present and named for years
    without ever being visible, and collapsing that is what made the coarse answer the only
    answer available.
*   **A re-run threw the reviewer's work away.** Confirmations are keyed on the evidence, not on a
    row id, so a second detector version does not resurrect a deleted false positive.
*   **Masking after the fact is not masking.** ``MASKED_STATES`` is what the derivative stage
    reads, and the temporarily hidden state is deliberately not in it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from exulanica.consent.regions import Silhouette, region_key
from exulanica.consent.states import (
    MASKED_STATES,
    ConsentTransition,
    resolve_presentation,
)
from exulanica.evidence.blob import BlobId
from exulanica.evidence.region import PPM, DisplayGeometry, Rect

DISPLAY = DisplayGeometry(w=4000, h=3000)
BLOB = BlobId(bytes(range(32)))


def _decision(scope, granted, second, digest=b"\x11" * 32):
    return ConsentTransition(
        scope=scope,
        granted=granted,
        actor="reviewer",
        decided_at=dt.datetime(2026, 9, 5, tzinfo=dt.UTC) + dt.timedelta(seconds=second),
        receipt_digest=digest,
    )


def test_a_person_region_defaults_to_hidden_without_a_consent_receipt():
    resolved = resolve_presentation(())
    assert resolved.state == "unknown"
    assert resolved.masked is True
    assert resolved.drawn is False


def test_naming_consent_alone_never_reveals_likeness():
    """The bowl case: somebody may be named and still never drawn."""
    resolved = resolve_presentation((_decision("naming", True, 1),))
    assert resolved.name_permitted is True
    assert resolved.drawn is False
    assert resolved.masked is True


def test_presence_consent_alone_never_reveals_likeness():
    resolved = resolve_presentation((_decision("presence", True, 1),))
    assert resolved.state == "present"
    assert resolved.masked is True
    assert resolved.drawn is False


def test_a_temporarily_hidden_person_keeps_their_geometry():
    """The one reversible state. Masking here would rebuild the world on every toggle."""
    granted = _decision("likeness", True, 1)
    hidden = resolve_presentation((granted, _decision("temporary_hide", True, 2)))
    assert hidden.state == "hidden"
    assert hidden.drawn is False
    assert hidden.masked is False
    assert "hidden" not in MASKED_STATES
    restored = resolve_presentation(
        (granted, _decision("temporary_hide", True, 2), _decision("temporary_hide", False, 3))
    )
    assert restored.state == "shown"


def test_a_revoked_likeness_masks_again():
    resolved = resolve_presentation(
        (_decision("likeness", True, 1), _decision("likeness", False, 2))
    )
    assert resolved.state == "unknown"
    assert resolved.masked is True


def test_a_withdrawal_is_not_undone_by_a_later_grant():
    """Withdrawal reaches forward; another actor's later receipt does not restore it."""
    resolved = resolve_presentation((_decision("likeness", True, 9),), withdrawn=True)
    assert resolved.state == "withdrawn"
    assert resolved.masked is True
    assert resolved.name_permitted is False


def test_resolution_does_not_depend_on_the_order_receipts_were_read():
    grant = _decision("likeness", True, 1, digest=b"\x01" * 32)
    revoke = _decision("likeness", False, 2, digest=b"\x02" * 32)
    assert resolve_presentation((grant, revoke)) == resolve_presentation((revoke, grant))


def test_two_receipts_at_one_instant_resolve_the_same_way_everywhere():
    """Without the digest tiebreak a package replayed elsewhere could disagree."""
    early = _decision("likeness", True, 5, digest=b"\x01" * 32)
    late = _decision("likeness", False, 5, digest=b"\x02" * 32)
    assert resolve_presentation((early, late)).state == "unknown"
    assert resolve_presentation((late, early)).state == "unknown"


def test_a_consent_receipt_needs_an_offset_aware_time():
    with pytest.raises(ValueError, match="UTC offset"):
        ConsentTransition("likeness", True, "a", dt.datetime(2026, 9, 5), b"\x00" * 32)


def test_an_unknown_consent_scope_is_refused():
    with pytest.raises(ValueError, match="is not one of"):
        _decision("appearance", True, 1)


def test_a_confirmed_region_survives_a_detector_rerun():
    """Keyed on a 16x16 bucket of the box centre, so a re-tightened outline keeps its identity."""
    first = Silhouette.from_rect(Rect.from_normalised(0.30, 0.30, 0.20, 0.40))
    tightened = Silhouette.from_rect(Rect.from_normalised(0.31, 0.32, 0.18, 0.36))
    assert region_key(BLOB, first, DISPLAY) == region_key(BLOB, tightened, DISPLAY)


def test_two_people_in_one_photograph_do_not_collapse_to_one_region():
    left = Silhouette.from_rect(Rect.from_normalised(0.05, 0.30, 0.15, 0.40))
    right = Silhouette.from_rect(Rect.from_normalised(0.70, 0.30, 0.15, 0.40))
    assert region_key(BLOB, left, DISPLAY) != region_key(BLOB, right, DISPLAY)


def test_an_outline_that_encloses_no_area_is_refused():
    with pytest.raises(ValueError, match="positive area"):
        Silhouette(((0, 0), (10_000, 0), (20_000, 0)))


def test_an_outline_of_two_points_is_refused():
    with pytest.raises(ValueError, match="at least 3 points"):
        Silhouette(((0, 0), (10_000, 10_000)))


def test_an_outline_outside_the_normalised_square_is_refused():
    with pytest.raises(ValueError, match="outside the normalised square"):
        Silhouette(((0, 0), (PPM + 1, 0), (0, PPM)))


def test_containment_is_exact_integer_arithmetic_on_a_concave_outline():
    """A chevron: the notch must be outside, which an x-intercept in floats gets wrong at edges."""
    chevron = Silhouette(
        (
            (0, 0),
            (400_000, 0),
            (200_000, 300_000),
            (400_000, 600_000),
            (0, 600_000),
        )
    )
    assert chevron.contains(50_000, 300_000) is True
    assert chevron.contains(350_000, 300_000) is False


def test_a_box_outline_says_it_is_a_box():
    """Masking a box hides more than the person; calling it a silhouette would overclaim."""
    rect = Rect.from_normalised(0.1, 0.1, 0.2, 0.3)
    outline = Silhouette.from_rect(rect)
    assert outline.as_digest_input()["kind"] == "polygon"
    assert len(outline.points) == 4
    assert outline.bounding_rect() == rect
