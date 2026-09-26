"""Branching a version copies what carrying it would, and names what it leaves out.

A branch's rows are new placements. Each of the parent's rows is asked what carrying it onto a
later snapshot asks (``WorldObjectRepository.carry_plan``, the question the binding triggers ask as
a row is written), under the global asset read lock, after the parent is locked and before
anything is written; a row that would stay is left out and named in ``left_behind``. So an ended
right never gives a 500, and never gets a placement copied against it: it is seen and left out, it
waits for the branch, or the branch is refused as stale with nothing written.

Every request runs through the application as a deployment runs it, connected as the runtime
role (``personal_world_support.personal_world_api``).
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.environment.repository import EnvironmentRepository
from exulanica.world.object_repository import WorldObjectRepository

from asset_lock_support import recorded_store_reads
from personal_world_support import (
    CUBE,
    group,
    make_world,
    personal_world_api,
    photograph,
    source_media,
)
from test_personal_world_addition import (
    _add_what_the_read_offers,
    _end_in_this_transaction,
    _placed_environment,
    _placed_estimate,
    _withdraw_elsewhere,
    _withdraw_environment_elsewhere,
    _world_with_a_placed_environment_and_a_new_photograph,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from personal_world_api(tmp_path, repository, spine_schema)


def _world(api) -> tuple[dict, str, uuid.UUID]:
    capture = photograph(api, minute=0)
    group(api)
    entry = make_world(api)
    [region] = {slot["region_id"] for slot in source_media(api, entry)}
    return entry, region, capture


def _with_an_estimate(api):
    entry, region, capture = _world(api)
    return _placed_estimate(api, entry, capture, region)


def _with_an_environment(api, tmp_path):
    entry, region, _ = _world(api)
    return _placed_environment(api, entry, region, tmp_path)


def _branch(api, entry: dict):
    return api.post(
        f"/world/versions?world_id={entry['world_id']}",
        {"title": "Another way it could be", "parent_version_id": entry["authored_version_id"]},
    )


def _versions(api, entry: dict) -> int:
    return api.repository.connection.execute(
        "select count(*) as n from world_alternate_version where workspace_id=%s and world_id=%s",
        (api.repository.workspace_id, entry["world_id"]),
    ).fetchone()["n"]


# -- what a branch leaves out, and says so --------------------------------------------------------


def test_a_branch_copies_every_row_it_may_write_and_leaves_nothing_out(api, tmp_path):
    entry, _ = _with_an_environment(api, tmp_path)
    parent = api.version(entry)
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    body = branched.json()
    assert body["left_behind"] == []
    assert body["parent_version_id"] == entry["authored_version_id"]
    assert body["environment_instances"] == parent["environment_instances"]
    assert body["state_sha256"] == parent["state_sha256"], "the same delta"
    assert body["edits"] == [], "a branch's change list starts empty"


def test_a_branch_from_a_parent_holding_a_withdrawn_environment_leaves_it_out_by_name(
    api, tmp_path
):
    entry, environment = _with_an_environment(api, tmp_path)
    assert _withdraw_environment_elsewhere(api, environment.source.admission_id) == "withdrawn"
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    body = branched.json()
    assert body["environment_instances"] == []
    assert body["left_behind"] == [
        {
            "subject": "environment_instance",
            "subject_id": "environment:yard",
            "removed": False,
            "reason": "source_withdrawn",
        }
    ]
    parent = api.version(entry)
    assert [i["instance_id"] for i in parent["environment_instances"]] == ["environment:yard"]


def test_a_branch_from_a_parent_whose_depth_right_ended_leaves_the_estimate_out_by_name(api):
    entry, right = _with_an_estimate(api)
    assert _withdraw_elsewhere(api, right.right_id, lock_timeout="10s") == "withdrawn"
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    body = branched.json()
    assert body["point_map_instances"] == []
    assert body["left_behind"] == [
        {
            "subject": "point_map_instance",
            "subject_id": "point-map:courtyard",
            "removed": False,
            "reason": "right_ended",
        }
    ]
    assert len(api.version(entry)["point_map_instances"]) == 1, "the parent keeps it"


def test_a_version_made_from_a_snapshot_leaves_nothing_out(api):
    entry, _, _ = _world(api)
    parent = api.version(entry)
    made = api.post(
        f"/world/versions?world_id={entry['world_id']}",
        {"title": "From the place itself", "source_snapshot_id": parent["source_snapshot_id"]},
    )
    assert made.status_code == 201, made.text
    assert made.json()["left_behind"] == []


# -- a right that ends while the branch runs ----------------------------------------------------


def test_a_depth_right_withdrawn_elsewhere_during_the_branch_cannot_commit_before_it(
    api, monkeypatch
):
    """Measured: refused as retryable by the asset read lock, not left waiting on a privacy lock.

    An addition's reads of rights take the privacy currency lock, so a withdrawal during an
    addition waits (55P03 under a short lock timeout). A branch reads no right that way; what holds
    the withdrawal back is the asset read lock the branch takes before its question.
    """
    entry, right = _with_an_estimate(api)
    tried = []
    carry = WorldObjectRepository._carry_point_map

    def withdrawn_while_written(self, *args):
        tried.append(_withdraw_elsewhere(api, right.right_id, lock_timeout="1s"))
        return carry(self, *args)

    monkeypatch.setattr(WorldObjectRepository, "_carry_point_map", withdrawn_while_written)
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    # Refused as retryable while the branch held the lock, so it never ended under it.
    assert tried == ["40001"]
    assert [i["instance_id"] for i in branched.json()["point_map_instances"]] == [
        "point-map:courtyard"
    ]
    monkeypatch.undo()
    assert _withdraw_elsewhere(api, right.right_id, lock_timeout="10s") == "withdrawn"


def test_an_environment_withdrawn_elsewhere_during_the_branch_cannot_commit_before_it(
    api, tmp_path, monkeypatch
):
    """The branch holds the asset read lock from its question until it commits."""
    entry, environment = _with_an_environment(api, tmp_path)
    tried = []
    carry = WorldObjectRepository._carry_environment

    def withdrawn_while_written(self, *args):
        tried.append(_withdraw_environment_elsewhere(api, environment.source.admission_id))
        return carry(self, *args)

    monkeypatch.setattr(WorldObjectRepository, "_carry_environment", withdrawn_while_written)
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    # Refused as retryable while the branch held the lock, so it never ended under it.
    assert tried == ["40001"]
    assert [i["instance_id"] for i in branched.json()["environment_instances"]] == [
        "environment:yard"
    ]
    monkeypatch.undo()
    assert _withdraw_environment_elsewhere(api, environment.source.admission_id) == "withdrawn"


def _end_environment_in_this_transaction(connection, api, admission_id: uuid.UUID) -> None:
    """Withdraw an environment source inside the branch's own transaction.

    Stands in for a source that ends between two of the branch's statements; the refused branch
    rolls this back with it.
    """
    EnvironmentRepository(connection, api.repository.workspace_id, api.store).withdraw(
        "source", admission_id
    )


@pytest.mark.parametrize("kind", ["point_map", "environment"])
def test_a_source_that_ends_as_its_row_is_written_refuses_the_branch_with_nothing_written(
    api, tmp_path, monkeypatch, kind
):
    """After the branch's question, the row's trigger refuses it (23514): a 409, never a 500."""
    if kind == "point_map":
        entry, right = _with_an_estimate(api)
        name = "_carry_point_map"

        def end(self):
            _end_in_this_transaction(self.connection, api, right.right_id)

    else:
        entry, environment = _with_an_environment(api, tmp_path)
        name = "_carry_environment"

        def end(self):
            _end_environment_in_this_transaction(
                self.connection, api, environment.source.admission_id
            )

    before = _versions(api, entry)
    original = getattr(WorldObjectRepository, name)

    def ended_first(self, *args):
        end(self)
        return original(self, *args)

    monkeypatch.setattr(WorldObjectRepository, name, ended_first)
    refused = _branch(api, entry)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "stale_object_base"
    assert _versions(api, entry) == before, "nothing of the branch was written"
    monkeypatch.undo()
    again = _branch(api, entry)
    assert again.status_code == 201, "the source ended only inside the refused branch"
    assert again.json()["left_behind"] == []


def test_a_source_that_ends_before_the_branchs_question_is_left_out(api, monkeypatch):
    """Before the question, inside the branch's own transaction: seen, and the row left out."""
    entry, right = _with_an_estimate(api)
    plan = WorldObjectRepository.carry_plan

    def ended_first(self, version_id):
        _end_in_this_transaction(self.connection, api, right.right_id)
        return plan(self, version_id)

    monkeypatch.setattr(WorldObjectRepository, "carry_plan", ended_first)
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    assert [part["reason"] for part in branched.json()["left_behind"]] == ["right_ended"]
    assert branched.json()["point_map_instances"] == []


# -- nothing is read from the store while the asset read lock is held -----------------------------


def _reads_under_the_lock(api, monkeypatch):
    """Each store read made while the asset read lock is held, with its planted control first.

    Every guarded write in every workspace is refused while the lock is held
    (``docs/asset-read-currency.md``), so a holder reads no stored bytes.
    """
    return recorded_store_reads(
        api.repository.connection,
        api.database,
        api.repository.workspace_id,
        api.store,
        monkeypatch,
        planted=CUBE,
    )


def test_a_branch_reads_no_stored_bytes_while_it_holds_the_asset_read_lock(
    api, tmp_path, monkeypatch
):
    entry, _ = _with_an_environment(api, tmp_path)
    reads = _reads_under_the_lock(api, monkeypatch)
    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    assert [i["availability"] for i in branched.json()["environment_instances"]] == ["available"]
    assert reads.under_the_lock == []
    assert reads.every, "the answer's availability was read from the store, after the commit"


def test_a_carry_reads_no_stored_bytes_while_it_holds_the_asset_read_lock(
    api, tmp_path, monkeypatch
):
    entry, _ = _world_with_a_placed_environment_and_a_new_photograph(api, tmp_path)
    reads = _reads_under_the_lock(api, monkeypatch)
    carried = _add_what_the_read_offers(api, entry)
    assert [i["instance_id"] for i in carried["environment_instances"]] == ["environment:yard"]
    assert reads.under_the_lock == []
    assert reads.every, "the addition's reads of stored bytes were seen, outside the lock"


def test_a_branch_copies_some_rows_leaves_a_removed_one_out_and_takes_an_edit_on_its_token(
    api, tmp_path
):
    """Its stored token is the digest of what it copied, so the next edit on it is accepted."""
    entry, region, capture = _world(api)
    entry, _environment = _placed_environment(api, entry, region, tmp_path)
    entry, right = _placed_estimate(api, entry, capture, region)
    version_id = uuid.UUID(entry["authored_version_id"])
    with api.database.session(api.repository.workspace_id) as connection:
        objects = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        objects.remove_point_map(
            version_id,
            "point-map:courtyard",
            base_state_sha256=objects.version(version_id).state_sha256,
            actor=api.actor,
        )
    assert _withdraw_elsewhere(api, right.right_id, lock_timeout="10s") == "withdrawn"

    branched = _branch(api, entry)
    assert branched.status_code == 201, branched.text
    body = branched.json()
    assert [i["instance_id"] for i in body["environment_instances"]] == ["environment:yard"]
    assert body["point_map_instances"] == []
    assert body["left_behind"] == [
        {
            "subject": "point_map_instance",
            "subject_id": "point-map:courtyard",
            "removed": True,
            "reason": "right_ended",
        }
    ]
    moved = api.post(
        f"/world/versions/{body['version_id']}/environment-instances/environment:yard/move"
        f"?world_id={entry['world_id']}",
        {
            "base_state_sha256": body["state_sha256"],
            "transform": {
                "x_mm": 500,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1000,
            },
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["environment_instances"][0]["transform"]["x_mm"] == 500


@pytest.mark.parametrize(
    "refusal",
    [psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure],
    ids=["deadlock", "serialization"],
)
def test_a_branch_stopped_by_a_concurrent_write_is_busy_and_writes_nothing(
    api, monkeypatch, refusal
):
    """A stop that took the asset read lock before the workspace lock can deadlock the branch."""
    entry, _ = _with_an_estimate(api)
    before = _versions(api, entry)
    plan = WorldObjectRepository.carry_plan

    def stopped(self, version_id):
        plan(self, version_id)
        raise refusal("stopped by a concurrent write")

    monkeypatch.setattr(WorldObjectRepository, "carry_plan", stopped)
    refused = _branch(api, entry)
    assert refused.status_code == 409, refused.text
    assert refused.json() == {
        "code": "busy",
        "detail": "another change was being written at that moment; try again",
    }
    assert _versions(api, entry) == before
