"""Identity separation and wall-clock boundaries of human invitations."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from exulanica.participation.contracts import issue_expiry, not_expired, public_world_words
from exulanica.participation.identity import (
    grant_actor,
    grant_id,
    principal_matches,
    principal_sha256,
)

WORKSPACE = UUID("52bb1e1b-3208-4596-9975-37b51a21b924")
OTHER = UUID("c9547103-adfc-4aed-9495-56c543909884")
KEY = UUID("04c68b3b-7849-4bdb-bd17-61288df54bf3")
ACTOR = UUID("7fbc5259-3e97-4bea-a7cc-1b4bdb327ec8")


def test_issue_identity_is_idempotent_and_cannot_move_between_workspaces():
    grant = grant_id(WORKSPACE, KEY)
    assert grant == grant_id(WORKSPACE, KEY)
    assert grant != grant_id(OTHER, KEY)
    assert grant != grant_id(WORKSPACE, OTHER)


def test_binding_names_one_account_in_one_grant_only():
    first, second = grant_id(WORKSPACE, KEY), grant_id(WORKSPACE, OTHER)
    binding = principal_sha256(first, ACTOR)
    assert principal_matches(first, ACTOR, binding)
    assert not principal_matches(first, OTHER, binding)
    assert not principal_matches(second, ACTOR, binding)
    assert principal_sha256(first, ACTOR) != principal_sha256(second, ACTOR)
    assert grant_actor(first) not in (ACTOR, first, grant_actor(second))
    assert str(ACTOR) not in binding


def test_persisted_binding_format_does_not_change_when_readers_are_replaced():
    grant = grant_id(WORKSPACE, KEY)
    assert grant == UUID("4a5b3921-f540-5ea4-8d30-7295d50951f7")
    assert principal_sha256(grant, ACTOR) == (
        "cfa546d713980bb198d3358d3edbe36842d8606faf889485cc6bfecca572c933"
    )


@pytest.mark.parametrize("binding", [None, {}, 0, "", "a" * 63, "é" * 64, "F" * 64])
def test_absent_or_malformed_principal_never_matches(binding):
    assert not principal_matches(grant_id(WORKSPACE, KEY), ACTOR, binding)


def test_expiry_is_real_time_and_ends_at_the_exact_boundary():
    expires = datetime(2026, 10, 11, 19, 0, tzinfo=UTC)
    equivalent = datetime(2026, 10, 11, 15, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert issue_expiry(equivalent, now=expires - timedelta(seconds=1)) == expires
    assert not_expired(expires, now=expires - timedelta(microseconds=1))
    assert not not_expired(expires, now=equivalent)
    assert not not_expired(expires, now=expires + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="after the issuing instant"):
        issue_expiry(expires, now=equivalent)


def test_naive_clock_is_refused_on_either_side_of_the_access_check():
    aware = datetime(2026, 10, 11, 19, 0, tzinfo=UTC)
    naive = aware.replace(tzinfo=None)
    with pytest.raises(ValueError, match="UTC offset"):
        not_expired(aware, now=naive)
    with pytest.raises(ValueError, match="UTC offset"):
        not_expired(naive, now=aware)


@pytest.mark.parametrize("words", ["two\nlines", "hidden\u200bword", " trailing ", "x" * 81])
def test_public_words_cannot_smuggle_layout_or_hidden_text(words):
    with pytest.raises(ValueError):
        public_world_words(words)


def test_public_words_reuse_the_products_plain_line_rule():
    assert public_world_words("A garden to explore together") == "A garden to explore together"


def test_revision_rejects_added_authority_and_changed_catalog_pins():
    import copy

    from exulanica.participation.contracts import revision_document, validate_revision

    document = revision_document(KEY, OTHER, datetime(2027, 1, 1, tzinfo=UTC), "A garden")
    assert validate_revision(document) == document
    for path, value in (("may_act", True), ("grant_seq", 2), ("principal_kind", "program")):
        altered = copy.deepcopy(document)
        altered[path] = value
        with pytest.raises(ValueError):
            validate_revision(altered)
    altered = copy.deepcopy(document)
    altered["role"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_revision(altered)


def test_positive_inhabitant_projection_drops_private_fields_and_indoor_positions():
    from exulanica.participation.projection import inhabitant

    person = {
        "id": "knight",
        "kind": {"kind": "knight", "version": 1, "sha256": "a" * 64, "private": "must disappear"},
        "position_mm": [1, 0, 2],
        "motion_path_mm": [[1, 2], [3, 4]],
        "location": {"indoors": True, "home_id": "private-home"},
        "name": "private name",
        "thoughts": "private thought",
        "heard": ["secret"],
        "actor_id": str(ACTOR),
        "new_field": {"private": True},
    }
    visible = inhabitant(person)
    assert set(visible) == {"id", "kind", "position_mm", "indoors", "motion_path_mm"}
    assert set(visible["kind"]) == {"kind", "version", "sha256"}
    assert visible["position_mm"] is None and visible["motion_path_mm"] == []
    person["location"]["indoors"] = False
    assert inhabitant(person)["position_mm"] == [1, 0, 2]
