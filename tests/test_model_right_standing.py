"""Each offered role's standing over a photograph is the server's, by the rule a hand-over meets.

``GET /personal-admission`` serves ``model_right_standings`` beside each source's rights, so the
page shows the standing and never recomputes it: ``current`` when every model of the role's
hand-over is named at its destination by a current right, ``partial``, ``ended`` or ``none``.
"""

from __future__ import annotations

import datetime as dt
import uuid

from exulanica.ingest.model_rights import ModelRightRow
from exulanica.ingest.personal_admission import model_right_offers
from exulanica.ingest.personal_requests import role_standing

START = dt.datetime(2026, 9, 26, 12, 0, tzinfo=dt.UTC)


def _offer():
    """An offered hosted role whose hand-over reaches more than one model."""
    return next(offer for offer in model_right_offers() if len(offer.handoff.identities) > 1)


def _right(offer, identity, *, days, withdrawn=False, destination=None) -> ModelRightRow:
    return ModelRightRow(
        right_id=uuid.uuid4(),
        capture_id=uuid.uuid4(),
        source_sha256=b"\0" * 32,
        authorization_id=uuid.uuid4(),
        operation="detect",
        identity=identity,
        destination=destination or offer.handoff.destination,
        purpose="test",
        granted_by=uuid.uuid4(),
        granted_at=START,
        valid_until=START + dt.timedelta(days=days),
        withdrawn_at=START if withdrawn else None,
        withdrawn_by=None,
        receipt_sha256=b"\0" * 32,
    )


def _words(_right) -> bool:
    return True


def test_a_role_no_right_names_stands_at_none():
    assert role_standing(_offer(), [], _words)["standing"] == "none"


def test_a_role_current_for_every_model_stands_current_until_its_first_model_runs_out():
    offer = _offer()
    first, second = offer.handoff.identities[:2]
    rights = [
        (_right(offer, first, days=30), True),
        (_right(offer, first, days=90), True),
        (_right(offer, second, days=60), True),
        *[(_right(offer, other, days=90), True) for other in offer.handoff.identities[2:]],
    ]
    standing = role_standing(offer, rights, _words)
    assert standing["standing"] == "current"
    # The first model's latest term is 90 days and the second's 60: the role ends with the second.
    assert standing["until"] == rights[2][0].as_reference()["valid_until"]
    assert standing["without_these_words"] is False
    assert role_standing(offer, rights, lambda right: False)["without_these_words"] is True


def test_a_role_current_for_some_models_or_elsewhere_stands_partial():
    offer = _offer()
    first = offer.handoff.identities[0]
    assert role_standing(offer, [(_right(offer, first, days=30), True)], _words)["standing"] == (
        "partial"
    )
    elsewhere = [
        (_right(offer, identity, days=30, destination="elsewhere"), True)
        for identity in offer.handoff.identities
    ]
    assert role_standing(offer, elsewhere, _words)["standing"] == "partial"


def test_a_role_whose_rights_all_ended_says_whether_it_was_stopped():
    offer = _offer()
    first = offer.handoff.identities[0]
    stopped = role_standing(offer, [(_right(offer, first, days=30, withdrawn=True), False)], _words)
    assert (stopped["standing"], stopped["stopped"], stopped["until"]) == ("ended", True, None)
    lapsed = role_standing(offer, [(_right(offer, first, days=30), False)], _words)
    assert (lapsed["standing"], lapsed["stopped"]) == ("ended", False)
