"""The world draft policy: three chosen budgets, each with its reason and a deployment's own figure.

Expected figures are read from the policy's file here, not from the code that reads it; the
bookkeeping is driven through its own methods with jobs that wait on an event the test holds, so
nothing here depends on timing.
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import pytest
from exulanica.api.kind_drafts import (
    STALE_MARGIN_SECONDS,
    KindDraftCapacity,
    KindDraftLimit,
    KindDrafts,
)
from exulanica.world.draft_policy import (
    BUDGETS,
    current_world_draft_policy,
    load_world_draft_policy,
)

POLICY = Path(__file__).resolve().parents[1] / "exulanica" / "world" / "world-draft-policy.v1.json"
STATED = json.loads(POLICY.read_text(encoding="utf-8"))["budgets"]


def test_the_policy_states_each_budget_with_its_class_its_reason_and_its_variable() -> None:
    assert set(STATED) == set(BUDGETS)
    policy = current_world_draft_policy()
    for key, guest in BUDGETS.items():
        stated = STATED[key]
        assert "CHOSEN BUDGET" in stated["reason"], key
        assert policy.figure(key, environ={}) == stated["figure"]
        assert policy.figure(key, environ={stated["environment"]: "7"}) == 7
        if guest:
            assert policy.figure(key, guest=True, environ={}) == stated["guest_figure"]
            # A guest's figure is the guest's own variable; a signed-in person's does not move it.
            assert (
                policy.figure(key, guest=True, environ={stated["environment"]: "7"})
                == (stated["guest_figure"])
            )
            assert policy.figure(key, guest=True, environ={stated["guest_environment"]: "3"}) == 3
        else:
            assert policy.figure(key, guest=True, environ={}) == stated["figure"]


@pytest.mark.parametrize("value", ["0", "-1", "two", "1.5", "٣"])
def test_a_variable_that_is_not_a_whole_number_of_at_least_one_is_refused_by_name(
    value: str,
) -> None:
    policy = current_world_draft_policy()
    for key in BUDGETS:
        name = STATED[key]["environment"]
        with pytest.raises(ValueError, match=name):
            policy.figure(key, environ={name: value})


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["budgets"].pop("starts_an_hour"),
        lambda d: d["budgets"]["drafts_at_once"].update(figure=0),
        lambda d: d["budgets"]["drafts_at_once"].update(reason=" "),
        lambda d: d["budgets"]["drafts_at_once"].pop("environment"),
        lambda d: d["budgets"]["starts_an_hour"].pop("guest_figure"),
        lambda d: d["budgets"]["workspace_drafts_at_once"].update(environment="DRAFTS"),
        lambda d: d["budgets"]["workspace_drafts_at_once"].update(
            environment=d["budgets"]["drafts_at_once"]["environment"]
        ),
        lambda d: d.update(extra=1),
    ],
)
def test_a_policy_document_that_states_less_or_more_is_refused(tmp_path: Path, change) -> None:
    document = json.loads(POLICY.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "world-draft-policy.v9.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=path.name):
        load_world_draft_policy(path)


def _held(
    drafts: KindDrafts, workspace: uuid.UUID, actor: uuid.UUID, release: threading.Event, **k
):
    return drafts.start(workspace, actor, "a place", lambda draft, held: release.wait(30), **k)


def test_the_bookkeeping_holds_drafts_to_the_figures_in_force_when_each_is_asked(monkeypatch):
    release = threading.Event()
    drafts = KindDrafts()
    at_once = STATED["drafts_at_once"]
    try:
        # The policy's own figure: that many workspaces draft at once and one more is refused.
        for _ in range(at_once["figure"]):
            _held(drafts, uuid.uuid4(), uuid.uuid4(), release)
        with pytest.raises(KindDraftCapacity):
            _held(drafts, uuid.uuid4(), uuid.uuid4(), release)
        # A deployment that states a larger figure is believed at the next ask, with no new holder.
        monkeypatch.setenv(at_once["environment"], str(at_once["figure"] + 1))
        _held(drafts, uuid.uuid4(), uuid.uuid4(), release)
        with pytest.raises(KindDraftCapacity):
            _held(drafts, uuid.uuid4(), uuid.uuid4(), release)
    finally:
        release.set()


def test_a_guest_s_starts_are_held_to_the_guest_s_figure(monkeypatch):
    starts = STATED["starts_an_hour"]
    monkeypatch.setenv(starts["guest_environment"], "1")
    monkeypatch.setenv(STATED["drafts_at_once"]["environment"], "8")
    release = threading.Event()
    release.set()
    drafts = KindDrafts()
    guest, person = uuid.uuid4(), uuid.uuid4()
    _held(drafts, uuid.uuid4(), guest, release, guest=True)
    assert drafts.refusal(uuid.uuid4(), guest, guest=True) == "kind_draft_limit"
    with pytest.raises(KindDraftLimit):
        _held(drafts, uuid.uuid4(), guest, release, guest=True)
    # A signed-in person is held to their own figure, which the guest's variable does not move.
    assert starts["figure"] > 1
    _held(drafts, uuid.uuid4(), person, release)
    assert drafts.refusal(uuid.uuid4(), person) is None


def test_every_figure_a_deployment_states_is_checked_together_as_a_server_starts() -> None:
    policy = current_world_draft_policy()
    policy.check({})
    policy.check({STATED[key]["environment"]: "4" for key in BUDGETS})
    guest = STATED["starts_an_hour"]["guest_environment"]
    with pytest.raises(ValueError, match=guest):
        policy.check({guest: "none"})


def test_a_draft_whose_world_was_made_ends_ready_though_it_outlived_its_bound() -> None:
    """A job still running well past its deadline is ended as failed; one that then finishes
    having made its world is ready all the same, since the world exists."""
    now = [1000.0]
    released, finished = threading.Event(), threading.Event()
    entry = uuid.uuid4()

    def job(draft, drafts) -> None:
        released.wait(10)
        drafts.made(draft, entry_id=entry)
        finished.set()

    drafts = KindDrafts(clock=lambda: now[0])
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    started = drafts.start(workspace, actor, "a farm", job, deadline=30.0, purpose="world")
    now[0] += 30.0 + STALE_MARGIN_SECONDS + 1
    stale = drafts.read(workspace, actor, started.draft_id, purpose="world")
    assert stale is not None and stale.state == "refused"
    released.set()
    assert finished.wait(10), "the job never finished"
    made = drafts.read(workspace, actor, started.draft_id, purpose="world")
    assert made is not None
    assert (made.state, made.refusal, made.entry_id, made.description) == ("ready", None, entry, "")


def test_what_is_left_of_the_hour_s_starts_is_read_without_starting_anything() -> None:
    released = threading.Event()
    drafts = KindDrafts(starts_per_hour=2)
    workspace, actor, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert drafts.allowance(workspace, actor).starts_left == 2
    started = drafts.start(workspace, actor, "a farm", lambda draft, held: released.wait(10))
    mine = drafts.allowance(workspace, actor)
    assert (mine.starts_left, mine.retry_seconds) == (1, None)
    assert mine.running is not None and mine.running.draft_id == started.draft_id
    # Another person in the workspace has their own starts and meets the same running draft.
    theirs = drafts.allowance(workspace, other)
    assert theirs.starts_left == 2 and theirs.running is not None
    assert drafts.allowance(uuid.uuid4(), other).running is None
    released.set()
