"""The schema rules that make default deny a database fact rather than a Python convention.

These read the migration text rather than a live database, so they run without PostgreSQL. That
is deliberate and it is not a substitute: the executed behaviour still needs a `-m postgres` run.
What these catch is the class of edit that silently removes a guarantee, which is exactly what
happened in 0029 and is the reason this feature exists.

0029 made the honest answer unrepresentable in three places at once, so no single reviewer of any
one of them would have seen it: a CHECK forbidding mask artifacts, a CHECK requiring an eligible
receipt to name no regions, and a resolver function repeating both. A reviewer looking at a
photograph with somebody in it had no eligible answer available except to say nobody was there,
and on 2026-09-05 that is the answer the retained bowl review gave over 51 frames containing
diners' arms and hands.
"""

from __future__ import annotations

import pytest
from exulanica.migrations import migrations

MIGRATION = {migration.version: migration.sql for migration in migrations()}
ALL_SQL = "\n".join(MIGRATION[version] for version in sorted(MIGRATION))
CONSENT_SQL = MIGRATION["0037"]


def test_an_eligible_screening_may_now_name_a_person():
    """The three 0029 rules that made a truthful region list impossible are all removed."""
    assert "drop constraint" in CONSENT_SQL
    assert "mask_artifacts" in CONSENT_SQL
    assert "sensitive_regions" not in CONSENT_SQL.split("create or replace function")[-1]


def test_the_resolver_no_longer_requires_a_screening_to_name_nobody():
    resolver = CONSENT_SQL.split("create or replace function privacy_screening_allows_capture")[1]
    assert "jsonb_array_length(s.sensitive_regions) = 0" not in resolver
    assert "jsonb_array_length(s.mask_artifacts) = 0" not in resolver
    assert "tombstone_blocks_capture" in resolver


def test_a_region_with_no_subject_is_masked():
    """Nobody could have consented, so nobody did."""
    masked = CONSENT_SQL.split("create function person_region_is_masked")[1]
    assert "p_subject is null" in masked


def test_a_withdrawn_person_is_masked():
    masked = CONSENT_SQL.split("create function person_region_is_masked")[1]
    assert "person_subject_is_withdrawn" in masked


def test_masking_requires_likeness_and_nothing_weaker():
    """Presence and naming must not reach the pixels."""
    masked = CONSENT_SQL.split("create function person_region_is_masked")[1]
    assert "'likeness'" in masked
    assert "'presence'" not in masked
    assert "'naming'" not in masked


def test_a_temporarily_hidden_person_is_not_masked_in_the_derivative():
    """Masking here would rebuild the world every time somebody toggled a switch."""
    masked = CONSENT_SQL.split("create function person_region_is_masked")[1]
    assert "temporary_hide" not in masked


def test_geometry_over_an_unconsented_person_is_refused_by_the_database():
    trigger = CONSENT_SQL.split("create function tg_geometry_reads_the_masked_derivative")[1]
    assert "point_map" in trigger
    assert "capture_requires_masking" in trigger
    assert "read_source_sha256 is null" in trigger
    assert "raise exception" in trigger
    assert "create trigger tg_geometry_reads_the_masked_derivative" in CONSENT_SQL


def test_the_masked_bytes_a_point_map_names_must_really_be_a_masked_source():
    """Declaring a digest is not enough; an attacker or a bug could name the original."""
    trigger = CONSENT_SQL.split("create function tg_geometry_reads_the_masked_derivative")[1]
    assert "kind = 'masked_source'" in trigger
    assert "m.content_sha256 = new.read_source_sha256" in trigger


def test_a_withdrawal_cannot_be_recorded_as_a_grantable_scope():
    assert "check (decision <> 'withdrawn' or consent_scope = 'likeness')" in CONSENT_SQL


@pytest.mark.parametrize(
    "table", ["person_subject", "person_region", "person_presentation_consent"]
)
def test_every_consent_table_is_append_only_and_workspace_isolated(table):
    """A consent receipt somebody can edit is not a receipt."""
    assert f"'{table}'" in CONSENT_SQL
    assert "tg_reconstruction_privacy_append_only" in CONSENT_SQL
    assert "force row level security" in CONSENT_SQL
    assert "workspace_id = current_workspace()" in CONSENT_SQL


@pytest.mark.parametrize("table", ["person_region", "person_presentation_consent"])
def test_every_receipt_binds_its_canonical_bytes_to_its_digest(table):
    """The same binding every other receipt in this schema carries."""
    body = CONSENT_SQL.split(f"create table {table} (")[1].split("\n);")[0]
    assert "'sha256')" in body
    assert "convert_from(" in body


def test_a_detected_region_names_its_detector_and_a_confirmed_one_names_its_human():
    body = CONSENT_SQL.split("create table person_region (")[1].split("\n);")[0]
    assert "detector_id is not null and confirmed_by is null" in body
    assert "confirmed_by is not null" in body


def test_a_consent_receipt_records_who_decided_and_in_what_role():
    body = CONSENT_SQL.split("create table person_presentation_consent (")[1].split("\n);")[0]
    assert "actor_id" in body
    assert "'subject'" in body, "the person in the photograph must be a representable actor"


def test_the_migration_stores_no_biometric_column():
    """A region is a location. Nothing here could recognise this person elsewhere.

    Read over the statements rather than the whole file: the prose above them says the words
    "descriptor" and "template" on purpose, and a test that could not tell a comment from a
    column would force the explanation to be deleted to stay green.
    """
    statements = "\n".join(
        line for line in CONSENT_SQL.splitlines() if not line.strip().startswith("--")
    ).lower()
    for forbidden in ("embedding", "descriptor", "template", "keypoint", "face_", "biometric"):
        assert forbidden not in statements, f"0037 must not introduce {forbidden}"


def test_the_only_new_person_tables_are_the_three_declared_ones():
    created = {
        line.split("create table ")[1].split(" (")[0]
        for line in CONSENT_SQL.splitlines()
        if line.startswith("create table ")
    }
    assert created == {"person_subject", "person_region", "person_presentation_consent"}


def test_the_privacy_policy_version_moved_so_old_receipts_are_provably_old():
    """The digest of these parameters is in every receipt; bumping it forces a re-screening.

    Deliberately not free. The two retained collections were screened under version 1, whose only
    eligible answer about a photograph with somebody in it was that there was nobody in it, and
    carrying those receipts forward unchanged would carry that answer forward with them.
    """
    from exulanica.ingest.privacy import PRIVACY_POLICY_PARAMS, PRIVACY_POLICY_VERSION

    assert PRIVACY_POLICY_VERSION == "exulanica.reconstruction-privacy/v2"
    assert PRIVACY_POLICY_PARAMS["masking"] != "not-implemented"
    assert PRIVACY_POLICY_PARAMS["default_state"].startswith("hidden-until")
    assert PRIVACY_POLICY_PARAMS["biometric_templates"] == "never"


def test_the_policy_names_three_separate_consents():
    from exulanica.ingest.privacy import PRIVACY_POLICY_PARAMS

    consents = PRIVACY_POLICY_PARAMS["consents"]
    for scope in ("presence", "naming", "likeness"):
        assert scope in consents


def test_the_receipt_vocabulary_is_the_one_the_resolver_uses():
    """Two spellings of the five states is how one of them quietly grows a sixth."""
    from exulanica.consent.states import MASKED_STATES
    from exulanica.ingest.privacy import _REGION_STATES

    assert MASKED_STATES <= _REGION_STATES
    assert {"unknown", "present", "shown", "hidden", "withdrawn"} == _REGION_STATES


def test_an_undecided_person_never_produces_an_eligible_screening():
    """The regression this file exists to stop coming back.

    Migration 0029 blocked any photograph whose screening named a person at all. 0037 removes that
    rule so a confirmed region list can be recorded, and for a while the replacement accepted a
    region in state ``unknown`` -- which means somebody was seen and nobody decided -- as eligible.
    That is the exact case default deny exists for, and it made this branch strictly less safe than
    the version it replaced. Until masking is wired into the pipeline, a masked region blocks.
    """
    from exulanica.consent.states import MASKED_STATES
    from exulanica.ingest.privacy import _REGION_STATES

    assert "unknown" in MASKED_STATES
    assert MASKED_STATES < _REGION_STATES, "a masked state must still be a recordable state"


def test_a_receipt_written_under_a_superseded_policy_no_longer_counts():
    """The bump has to bite, or it is a number in a docstring.

    Every screening stored `policy_version` and `policy_params_digest` from the beginning and
    nothing compared either, so moving the policy to v2 invalidated nothing: the two retained
    collections kept their version 1 receipts and those receipts kept passing. The claim that they
    "must be re-screened" was true of the intent and false of the code.
    """
    resolver = CONSENT_SQL.split("create or replace function privacy_screening_allows_capture")[1]
    assert "s.policy_version = current_privacy_policy()" in resolver


def test_the_database_and_python_name_the_same_current_policy():
    """One place each, and a test between them, because two literals drift."""
    from exulanica.ingest.privacy import PRIVACY_POLICY_VERSION

    declared = CONSENT_SQL.split("create function current_privacy_policy()")[1].split("$fn$")[1]
    assert PRIVACY_POLICY_VERSION in declared
