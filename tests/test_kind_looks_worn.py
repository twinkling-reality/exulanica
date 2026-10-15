"""A creature wears its kind's made look wherever it is placed (migration 0220's ``kind_look``),
with no database: the reads of look choices, of the workspace's looks and of a participant's
snapshot stand in.

*   A being of a workspace kind with no choice of its own wears its kind's made look, before its
    kind's first look; its own choice comes first; a kind look on another plan, or one the
    workspace no longer keeps, is passed by for the first look; a kind look never dresses another
    kind.
*   A participant may read a present being's kind look, as it may a chosen one, and never the kind
    look of a kind no present being has, or one drawn on another plan.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from exulanica.api import participation
from exulanica.world import thing_looks

KIND, OTHER = "1" * 64, "2" * 64
FIRST, MADE, CHOSEN = "a" * 64, "b" * 64, "c" * 64
PLAN = "made_heron/v1"


def _kind(sha256: str = KIND) -> SimpleNamespace:
    return SimpleNamespace(sha256=sha256, plan=PLAN, document={"looks": [{"sha256": FIRST}]})


def _choices(*, chosen: str | None = None, kind_looks: dict[str, str] | None = None) -> dict:
    return {
        "looks": [],
        **(
            {
                "workspace_looks": [
                    {
                        "thing_id": "heron-1",
                        "look": {"sha256": chosen, "source": "workspace"},
                        "chosen_by": "owner",
                    }
                ]
            }
            if chosen
            else {}
        ),
        **(
            {
                "kind_looks": [
                    {"kind_sha256": kind, "look": {"sha256": look, "source": "workspace"}}
                    for kind, look in (kind_looks or {}).items()
                ]
            }
            if kind_looks
            else {}
        ),
    }


def _worn(monkeypatch, choices: dict, *, kept: dict[str, str], kind=None) -> str | None:
    """The digest the being wears, the workspace keeping the looks ``kept`` names (digest, plan)."""
    monkeypatch.setattr(thing_looks, "look_choices", lambda *_args, **_kwargs: choices)
    monkeypatch.setattr(
        thing_looks,
        "admitted_look_by_digest",
        lambda _connection, _workspace, sha256: (
            SimpleNamespace(sha256=sha256, body_plan=kept[sha256]) if sha256 in kept else None
        ),
    )
    effective = thing_looks.effective_look(
        None, uuid.uuid4(), "world", uuid.uuid4(), "heron-1", kind or _kind(), workspace_kind=True
    )
    return None if effective is None else effective.reference.sha256


def test_a_being_with_no_choice_wears_its_kind_s_made_look_before_its_first(monkeypatch):
    kept = {FIRST: PLAN, MADE: PLAN, CHOSEN: PLAN}
    assert _worn(monkeypatch, _choices(), kept=kept) == FIRST
    assert _worn(monkeypatch, _choices(kind_looks={KIND: MADE}), kept=kept) == MADE
    # Its own choice first.
    assert _worn(monkeypatch, _choices(chosen=CHOSEN, kind_looks={KIND: MADE}), kept=kept) == CHOSEN
    # Another kind's look never dresses it.
    assert _worn(monkeypatch, _choices(kind_looks={OTHER: MADE}), kept=kept) == FIRST


def test_a_kind_look_on_another_plan_or_no_longer_kept_is_passed_by(monkeypatch):
    assert _worn(monkeypatch, _choices(kind_looks={KIND: MADE}), kept={FIRST: PLAN}) == FIRST
    elsewhere = {FIRST: PLAN, MADE: "another_body/v1"}
    assert _worn(monkeypatch, _choices(kind_looks={KIND: MADE}), kept=elsewhere) == FIRST


#: The plan each kept look is drawn on; the kind's made look is on its own plan unless a test says.
_PLANS = {FIRST: PLAN, MADE: PLAN}


class _Store:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def kind_by_digest(self, sha256: str) -> SimpleNamespace:
        return SimpleNamespace(sha256=sha256, plan=PLAN, looks=[{"sha256": FIRST}])

    def look_by_digest(self, sha256: str) -> SimpleNamespace:
        return SimpleNamespace(
            container_sha256=f"{sha256[:8]}-container",
            container_bytes=1,
            look=SimpleNamespace(body_plan=_PLANS.get(sha256, PLAN)),
        )


def test_a_participant_reads_a_present_being_s_kind_look_and_no_absent_kind_s(monkeypatch):
    absent = "d" * 64
    monkeypatch.setattr(
        participation,
        "look_choices",
        lambda *_args, **_kwargs: _choices(kind_looks={KIND: MADE, OTHER: absent}),
    )
    monkeypatch.setattr(participation, "ThingStore", _Store)
    snapshot = {
        "state": {
            "inhabitants": [{"id": "heron-1", "kind": {"source": "workspace", "sha256": KIND}}]
        }
    }
    runtime = SimpleNamespace(
        _standing=lambda *_args: {}, eligible=lambda *_args: (None, None, snapshot)
    )
    scope = SimpleNamespace(workspace_id=uuid.uuid4(), world_id="world", version_id=uuid.uuid4())
    files = participation.ParticipationRuntime._files(runtime, None, scope)  # type: ignore[arg-type]
    assert {entry["look_sha256"] for entry in files.values()} == {FIRST, MADE}
    # A kind look drawn on another plan is no look the kind wears, so none a participant reads.
    monkeypatch.setitem(_PLANS, MADE, "another_body/v1")
    files = participation.ParticipationRuntime._files(runtime, None, scope)  # type: ignore[arg-type]
    assert {entry["look_sha256"] for entry in files.values()} == {FIRST}
