"""What the browser is allowed to know about the people in a photograph.

Three rules, and every one of them is chosen so that a failure reveals nobody.

*   **A photograph nobody screened is ``unscreened``, not empty.** The two look identical in a
    payload that carries an empty list and no state, and they are opposite facts: one means there
    is nobody to hide and the other means nobody has looked. The client draws no pixels for the
    second, so a corpus ingested before this feature existed degrades to silhouettes and a stated
    reason rather than to a photograph of somebody who never agreed to be shown.
*   **A name travels on a naming receipt, and never once a withdrawal stands.** Naming and
    likeness are separate consents, so the name is gated on the naming receipt while the pixels
    are gated on likeness, and a person may be named on a silhouette. A withdrawal outranks every
    receipt, and it has to be applied here: the client draws a name whenever one arrives rather
    than reading the state, so a name that leaves this function is a name on the screen.
*   **The outline travels and the pixels do not.** There is nothing here a client bug could turn
    back into a face: the bytes for a masked region were replaced with neutral fill before
    reconstruction read them, and this row carries a polygon and a state.

The hidden count is computed here rather than in the client for the same reason: a client that
failed to load these rows would otherwise report that nobody was hidden.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import psycopg

from exulanica.graph.payload import MemberPersonRegionRow

__all__ = ["hidden_people", "person_regions_for_captures", "review_states_for_captures"]


def person_regions_for_captures(
    connection: psycopg.Connection, workspace: uuid.UUID, capture_ids: Sequence[uuid.UUID]
) -> dict[str, list[MemberPersonRegionRow]]:
    """Every live confirmed region on these photographs, with the state that holds now.

    One statement for the whole member set rather than one per member, following the rest of this
    package. The state comes from ``person_region_is_masked`` and the consent resolver in
    migration 0037, so the answer the browser is given is the same answer the database gives the
    masking stage; two implementations of that rule would eventually disagree, and the direction
    they would disagree in is a person drawn who should not have been.
    """
    if not capture_ids:
        return {}
    rows = connection.execute(
        "select r.capture_id, encode(r.region_key,'hex') as region_key, r.silhouette, "
        "r.subject_id, "
        "person_region_is_masked(r.workspace_id, r.subject_id, r.region_key) as masked, "
        "person_subject_is_withdrawn(r.workspace_id, r.subject_id) as withdrawn, "
        "person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'presence') "
        "  as presence, "
        "person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'naming') "
        "  as naming, "
        "person_consent_is_granted(r.workspace_id, r.subject_id, r.region_key, 'temporary_hide') "
        "  as temporarily_hidden, "
        "e.display_name as display_name "
        "from person_region_current r "
        "left join person_subject s "
        "  on s.workspace_id = r.workspace_id and s.subject_id = r.subject_id "
        "left join entity e on e.entity_id = s.entity_id "
        "where r.workspace_id = %s and r.capture_id = any(%s) and r.action <> 'deleted' "
        "order by r.capture_id, r.region_key",
        (workspace, list(capture_ids)),
    ).fetchall()
    found: dict[str, list[MemberPersonRegionRow]] = {}
    for row in rows:
        found.setdefault(str(row["capture_id"]), []).append(
            MemberPersonRegionRow(
                region_id=row["region_key"],
                state=_state(row),
                silhouette_ppm=_points(row["silhouette"]),
                display_name=_name(row),
                subject_id=row["subject_id"],
            )
        )
    return found


def _state(row: dict[str, Any]) -> str:
    """The design note's five states, in the order least to most revealed."""
    if row["withdrawn"]:
        return "withdrawn"
    if row["masked"]:
        return "present" if row["presence"] else "unknown"
    return "hidden" if row["temporarily_hidden"] else "shown"


def _name(row: dict[str, Any]) -> str | None:
    """The name, and a withdrawal takes it back whatever the naming receipt still says.

    ``person_consent_is_granted`` answers a narrower question than its name suggests: whether one
    scope's receipt is held at this instant. It has no withdrawal check, and that is right for
    what it is, because migration 0037 composes it rather than widening it. The masking rule at
    0037:189-195 is a disjunction of three reasons to hide somebody, `p_subject is null OR
    person_subject_is_withdrawn(...) OR NOT person_consent_is_granted(..., 'likeness')`, so a
    withdrawal masks whatever the likeness receipt says. Naming needed the same composition with
    the withdrawal term and did not have it, so this is that composition rather than a second
    implementation of the rule.

    MEASURED 2026-09-07 against PostgreSQL, by the test named for it: a subject holding a granted
    naming receipt, given a withdrawal, came back as ``state='withdrawn'`` carrying
    ``display_name='Julie'``. Only ``_state`` read ``withdrawn``, and the name was decided from a
    different fact.
    """
    if row["withdrawn"] or not row["naming"]:
        return None
    return row["display_name"]


def _points(silhouette: Any) -> list[list[int]]:
    points = silhouette.get("points", []) if isinstance(silhouette, dict) else []
    return [[int(x), int(y)] for x, y in points]


def review_states_for_captures(
    connection: psycopg.Connection, workspace: uuid.UUID, capture_ids: Sequence[uuid.UUID]
) -> dict[str, str]:
    """Whether each photograph has been screened for people at all.

    Absence from this map means ``unscreened``, which every caller must default to. That is the
    whole reason it is a separate map rather than an attribute of a region: a photograph with no
    regions is the ambiguous case, and the ambiguity has to be resolved toward hiding.
    """
    if not capture_ids:
        return {}
    rows = connection.execute(
        "select distinct capture_id from person_region "
        "where workspace_id = %s and capture_id = any(%s)",
        (workspace, list(capture_ids)),
    ).fetchall()
    return {str(row["capture_id"]): "screened" for row in rows}


def hidden_people(regions: dict[str, list[MemberPersonRegionRow]]) -> tuple[int, int]:
    """How many people are not being drawn, and how many photographs that reaches.

    Counted over every state except ``shown``, so a temporarily hidden person is included: from
    the status line's point of view "somebody in this scene is not visible" is one fact, and the
    reason is in the inspector rather than in the count.
    """
    hidden = 0
    members = 0
    for people in regions.values():
        not_drawn = sum(1 for person in people if person.state != "shown")
        hidden += not_drawn
        members += 1 if not_drawn else 0
    return hidden, members
