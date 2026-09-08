"""One instant through the actual SQL writer, authenticated route and offline reader."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import PrivacyAdmissionError
from exulanica.graph.world_read import world_read_bundle
from exulanica.graph.world_read_evidence import _consent_columns_match
from exulanica.graph.world_read_verification import EvidenceError, verify
from exulanica.ingest import person_review
from exulanica.ingest.person_review import create_subject, record_consent, record_region_edits
from exulanica.ingest.privacy import authorize_personal_capture, record_human_screening

from conftest import write_point_map
from test_api import deployment as deployment
from test_screening_currency import ACTOR, KEY, OUTLINE
from test_world_read_route import _scene_in

FIRST = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)


class AdvancingClock:
    def __init__(self):
        self.calls = 0

    def now(self, zone):
        value = FIRST + dt.timedelta(microseconds=self.calls)
        self.calls += 1
        return value.astimezone(zone)


def _clock(clock):
    # Replace this module's datetime binding, never the shared datetime module.
    return patch.object(person_review, "dt", SimpleNamespace(datetime=clock, UTC=dt.UTC))


def _save(name, value):
    root = os.environ.get("CONSENT_TIMESTAMP_ARTIFACTS")
    if root:
        path = Path(root) / name
        path.write_bytes(canonical_json(value))


def _row(repository, consent):
    return repository.connection.execute(
        "select * from person_presentation_consent where workspace_id=%s and consent_id=%s",
        (repository.workspace_id, consent),
    ).fetchone()


def _assert_receipt(row):
    raw = bytes(row["consent_canonical"])
    parsed = json.loads(raw)
    assert parsed == row["consent_record"]
    assert canonical_json(parsed) == raw
    assert hashlib.sha256(raw).digest() == bytes(row["consent_digest"])
    assert dt.datetime.fromisoformat(parsed["effective_at"]) == row["effective_at"], (
        "two-clock effective_at mismatch"
    )
    assert _consent_columns_match(row)
    return {
        "record": parsed,
        "canonical_utf8": raw.decode(),
        "sha256": bytes(row["consent_digest"]).hex(),
        "stored_effective_at": row["effective_at"].isoformat(),
        "stored_valid_until": row["valid_until"].isoformat() if row["valid_until"] else None,
    }


def test_default_time_sql_receipt_uses_one_instant(repository):
    subject = create_subject(repository, actor=ACTOR)
    clock = AdvancingClock()
    with _clock(clock):
        consent = record_consent(
            repository,
            subject_id=subject,
            actor=ACTOR,
            consent_scope="likeness",
            decision="granted",
        )
    row = _row(repository, consent)
    _save(
        "sql-observation.json",
        {
            "receipt_time": row["consent_record"]["effective_at"],
            "column_time": row["effective_at"].isoformat(),
            "clock_calls": clock.calls,
            "columns_match": _consent_columns_match(row),
        },
    )
    _assert_receipt(row)
    assert clock.calls == 1
    assert row["effective_at"] == FIRST


@pytest.mark.parametrize("supplied", [FIRST, FIRST.astimezone(dt.timezone(dt.timedelta(hours=5)))])
def test_explicit_time_and_sequence_preserved(repository, supplied):
    subject = create_subject(repository, actor=ACTOR)
    clock = AdvancingClock()
    with _clock(clock):
        for sequence in range(2):
            consent = record_consent(
                repository,
                subject_id=subject,
                actor=ACTOR,
                consent_scope="naming",
                decision="granted",
                effective_at=supplied,
                valid_until=supplied + dt.timedelta(days=1),
                region_key=KEY,
            )
            row = _row(repository, consent)
            _assert_receipt(row)
            assert row["effective_at"] == supplied
            assert row["sequence"] == sequence
            assert row["region_key"] == KEY
    assert clock.calls == 0


@pytest.mark.parametrize("field", ["effective_at", "valid_until"])
def test_unzoned_time_refused_before_insert(repository, field):
    subject = create_subject(repository, actor=ACTOR)
    values = {"effective_at": FIRST, field: dt.datetime(2020, 1, 2)}
    with pytest.raises(PrivacyAdmissionError, match="UTC offset"):
        record_consent(
            repository,
            subject_id=subject,
            actor=ACTOR,
            consent_scope="likeness",
            decision="granted",
            **values,
        )
    assert repository.person_consent_transitions(subject_id=subject) == []


def test_default_time_writer_to_authenticated_recipient(deployment, repository, tmp_path):
    configured = {}

    def with_person(repo, store, blob, payload):
        capture = repo.live_capture_for_blob(blob).capture_id
        if not configured:
            subject = create_subject(repo, actor=ACTOR)
            record_region_edits(
                repo,
                capture_id=capture,
                actor=ACTOR,
                edits=[
                    {
                        "action": "add",
                        "region_key": KEY.hex(),
                        "subject_id": str(subject),
                        "silhouette": OUTLINE.as_digest_input(),
                    }
                ],
            )
            clock = AdvancingClock()
            with _clock(clock):
                consent = record_consent(
                    repo,
                    subject_id=subject,
                    actor=ACTOR,
                    consent_scope="likeness",
                    decision="granted",
                )
            configured.update(capture=capture, subject=subject, consent=consent, calls=clock.calls)
            record_consent(
                repo,
                subject_id=subject,
                actor=ACTOR,
                consent_scope="naming",
                decision="granted",
                effective_at=FIRST,
                valid_until=dt.datetime(2090, 1, 1, tzinfo=dt.UTC),
            )
        auth = authorize_personal_capture(
            repo,
            capture_id=capture,
            actor=ACTOR,
            account_authority_basis="Generated fixture, no personal media",
            authorization_scope={"purpose": "timestamp test"},
            purpose="timestamp test",
        )
        screening = record_human_screening(
            repo,
            authorization_id=auth.authorization_id,
            reviewed_by=ACTOR,
            sensitive_regions=person_review.review_list(repo, capture),
        )
        return write_point_map(
            repo, store, blob, payload, privacy_screening_id=screening.screening_id
        )

    with patch("test_world_read_route.write_point_map", with_person):
        scene = _scene_in(deployment, repository, tmp_path)
    route = f"/world-read/scenes/{scene}"
    response = deployment.as_owner("GET", route)
    assert response.status_code == 200, response.text
    envelope = response.json()
    _save("route-bundle.json", envelope)
    receipt = _assert_receipt(_row(repository, configured["consent"]))
    assert configured["calls"] == 1
    captures = envelope["bundle"]["recipient_evidence"]["record"]["captures"]
    region = next(c["regions"][0] for c in captures if c["regions"])
    assert any(
        r.get("sha256") == receipt["sha256"] and r.get("record") == receipt["record"]
        for r in region["receipts"]
    )
    _save("persisted-receipt.json", receipt)
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_bytes(canonical_json(envelope))
    verifier = (
        Path(__file__).resolve().parents[1] / "scripts/verify_world_read_recipient_evidence.py"
    )
    env = {
        k: v
        for k, v in os.environ.items()
        if "DATABASE" not in k and k not in {"PYTHONPATH", "PYTHONHOME"}
    }
    for label, at, naming in [
        ("before-expiry", "2089-12-31T23:59:59Z", True),
        ("at-expiry", "2090-01-01T00:00:00Z", False),
    ]:
        result = subprocess.run(
            [
                sys.executable,
                str(verifier),
                str(bundle_path),
                "--at",
                at,
                "--expected-bundle-sha256",
                envelope["bundle_sha256"],
            ],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        evaluation = json.loads(result.stdout)
        person = evaluation["people"][str(configured["capture"])][0]
        assert person["scopes"]["likeness"] is True
        assert person["scopes"]["naming"] is naming
        _save(label + "-evaluation.json", evaluation)
    assert deployment.as_stranger("GET", route).status_code == 404
    record_consent(
        repository,
        subject_id=configured["subject"],
        actor=ACTOR,
        consent_scope="likeness",
        decision="withdrawn",
        effective_at=FIRST,
    )
    withdrawn = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    evaluation = verify(
        withdrawn, at="2026-09-08T00:00:00Z", expected_bundle_sha256=withdrawn["bundle_sha256"]
    )
    assert evaluation["people"][str(configured["capture"])][0]["withdrawn"] is True
    assert deployment.as_owner("GET", route).status_code == 404
    _save("withdrawn-bundle.json", withdrawn)
    _save("withdrawn-evaluation.json", evaluation)
    # Read-only inspection of disagreement policy: no historical row is rewritten.
    import copy

    legacy = copy.deepcopy(envelope)
    old_region = next(
        c["regions"][0]
        for c in legacy["bundle"]["recipient_evidence"]["record"]["captures"]
        if c["regions"]
    )
    old_region["receipts"].append(
        {"state": "unavailable", "reason": "consent_columns_disagree_with_receipt"}
    )
    from test_world_read_evidence import _reseal

    legacy = _reseal(legacy)
    with pytest.raises(EvidenceError, match="consent_receipt_unavailable"):
        verify(legacy, at="2026-09-08T00:00:00Z", expected_bundle_sha256=legacy["bundle_sha256"])
    _save("legacy-disagreement-wire-only.json", legacy)
