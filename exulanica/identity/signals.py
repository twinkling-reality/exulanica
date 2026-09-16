"""What corroborates that two occurrences in different photographs are the same thing.

Three signals, all of them context. None of them is biometric and none of them can become one
from here: there is no face model, no audio for a voice model and no video for gait, and the
decision that would permit a face embedding belongs to a human and has not been made.
``privacy-consent-threat-model.md`` section 10 records the three incompatible candidate rules and
says the choice must be made before identity work begins. It has not been, so this module works
without it, which is possible because a bounding box saying somebody is present is outside that
question and person occurrences already exist.

**A detector label is not one of these signals.** Twenty-seven captures containing *a* red cube do
not contain *the* red cube. Label equality is a hard constraint applied before any of this runs,
a refusal of nonsense rather than evidence of sameness, and treating it as a signal is the single
easiest way to build a system that confidently proposes that every red cube is the same cube.

Time proximity is not a modality either. It is not in the closed id-4 vocabulary and inventing a
seventh member to hold it is exactly the drift migration 0008's CHECK exists to stop. It enters
through ``context_cooccurrence``, because a scene group is built from time and position, and it
is recorded as a parameter rather than claimed as a signal.

These functions read tables that ingest wrote and identity did not: ``capture``,
``derived_artifact``, and ``assertion`` under ``gps_position_is``. Reading a table is not
importing a module, so the layer contract is untouched, but the string ``'scene_group'`` is
written in ``exulanica/ingest/scenes.py`` and read here, and a test pins the two together because a
literal duplicated across a boundary nothing checks is a literal that drifts.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import psycopg

__all__ = ["SCENE_GROUP_KIND", "CaptureContext", "ContextSignals", "corroborating_modalities"]

#: The ``derived_artifact.kind`` ingest writes its clustering under. Duplicated from
#: ``exulanica.ingest.scenes``, which this layer may not import, and pinned by
#: ``tests/test_match_proposals.py::test_the_scene_group_kind_is_the_one_ingest_writes``.
SCENE_GROUP_KIND: Final = "scene_group"

_EARTH_RADIUS_M: Final = 6_371_000.0


@dataclass(frozen=True, slots=True)
class CaptureContext:
    """Everything about one capture that a context signal can be computed from."""

    capture_id: uuid.UUID
    #: None when the file carried no recoverable instant, which is a real state: the corpus has
    #: an indoor trip with no GPS and a device that writes no offset.
    started_at: object | None
    lat: float | None
    lon: float | None
    scene_group_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    object_labels: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_positioned(self) -> bool:
        return self.lat is not None and self.lon is not None


class ContextSignals:
    """The corpus context every capture carries, read once for a whole proposal pass.

    Read once rather than per pair, because the pass is quadratic in candidates and a per-pair
    query would issue one statement per comparison. This is a cache with a lifetime of one pass;
    it is not a live view and must not outlive the transaction that built it.
    """

    def __init__(self, contexts: Mapping[uuid.UUID, CaptureContext]) -> None:
        self._contexts = dict(contexts)

    def __len__(self) -> int:
        return len(self._contexts)

    def of(self, capture_id: uuid.UUID) -> CaptureContext | None:
        return self._contexts.get(capture_id)

    @classmethod
    def read(cls, connection: psycopg.Connection, workspace: uuid.UUID) -> ContextSignals:
        """Every capture in the workspace, with its instant, its position and its groupings."""
        contexts: dict[uuid.UUID, dict] = {
            row["capture_id"]: {
                "capture_id": row["capture_id"],
                "started_at": row["started_at"],
                "lat": None,
                "lon": None,
                "groups": set(),
                "labels": set(),
            }
            for row in connection.execute(
                "select capture_id, started_at from capture "
                "where workspace_id = %s and deleted_at is null",
                (workspace,),
            ).fetchall()
        }

        # Position from the claim rather than from a column, because that is where it lives: a
        # capture-supported fact under `gps_position_is`, which migration 0006 now keeps to one
        # current row per capture.
        for row in connection.execute(
            "select a.subject_ref ->> 'id' as capture_id, "
            "       a.object_value ->> 'lat' as lat, a.object_value ->> 'lon' as lon "
            "from assertion a join predicate p on p.predicate_id = a.predicate_id "
            "where a.workspace_id = %s and p.key = 'gps_position_is' and a.status = 'active' "
            "  and a.subject_ref ->> 'type' = 'capture'",
            (workspace,),
        ).fetchall():
            entry = contexts.get(uuid.UUID(row["capture_id"]))
            if entry is not None and row["lat"] is not None and row["lon"] is not None:
                entry["lat"] = float(row["lat"])
                entry["lon"] = float(row["lon"])

        for row in connection.execute(
            "select derived_id, payload from derived_artifact "
            "where workspace_id = %s and kind = %s and stale = false",
            (workspace, SCENE_GROUP_KIND),
        ).fetchall():
            for value in (row["payload"] or {}).get("capture_ids", []):
                entry = contexts.get(uuid.UUID(value))
                if entry is not None:
                    entry["groups"].add(row["derived_id"])

        for row in connection.execute(
            "select a.subject_ref ->> 'id' as capture_id, a.object_value #>> '{}' as label "
            "from assertion a join predicate p on p.predicate_id = a.predicate_id "
            "where a.workspace_id = %s and p.key = 'object_present' and a.status = 'active' "
            "  and a.subject_ref ->> 'type' = 'capture'",
            (workspace,),
        ).fetchall():
            entry = contexts.get(uuid.UUID(row["capture_id"]))
            if entry is not None and row["label"]:
                entry["labels"].add(row["label"])

        return cls(
            {
                capture_id: CaptureContext(
                    capture_id=entry["capture_id"],
                    started_at=entry["started_at"],
                    lat=entry["lat"],
                    lon=entry["lon"],
                    scene_group_ids=frozenset(entry["groups"]),
                    object_labels=frozenset(entry["labels"]),
                )
                for capture_id, entry in contexts.items()
            }
        )


def metres_between(a: CaptureContext, b: CaptureContext) -> float | None:
    """Great-circle distance, or None when either capture has no position.

    None rather than a large number. "We do not know where this was taken" and "these were taken
    far apart" are different facts, and a sentinel distance would let the first quietly behave
    like the second.
    """
    if not a.is_positioned or not b.is_positioned:
        return None
    lat_a, lon_a, lat_b, lon_b = (
        math.radians(value) for value in (a.lat, a.lon, b.lat, b.lon)
    )
    d_lat, d_lon = lat_b - lat_a, lon_b - lon_a
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(d_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def corroborating_modalities(
    anchor: CaptureContext,
    candidate: CaptureContext,
    *,
    join_label: str | None,
    max_place_distance_m: float,
    min_shared_labels: int,
    annotation_text: Sequence[str] = (),
    display_name: str | None = None,
) -> tuple[str, ...]:
    """Which id-4 modalities corroborate this pair. Possibly none, which is an answer.

    An empty result means the pair is not proposed at all. ``basis_digest`` refuses an empty
    modality list, so that rule is enforced by the function the row cannot be constructed
    without, rather than by remembering to check.
    """
    found: list[str] = []

    distance = metres_between(anchor, candidate)
    if distance is not None and distance <= max_place_distance_m:
        found.append("context_place")

    shared_groups = anchor.scene_group_ids & candidate.scene_group_ids
    # The candidate's own label is excluded from the shared set. It is the join key, and counting
    # it would be counting the hard constraint as its own evidence.
    shared_labels = (anchor.object_labels & candidate.object_labels) - (
        {join_label} if join_label else set()
    )
    if shared_groups or len(shared_labels) >= min_shared_labels:
        found.append("context_cooccurrence")

    # Dormant by design rather than by omission: nothing writes `user_annotation` yet, so this
    # never fires today. It is here so the vocabulary is complete and so the day something does
    # write one, the signal exists rather than being remembered.
    if display_name and any(display_name.lower() in text.lower() for text in annotation_text):
        found.append("user_text")

    return tuple(sorted(found))
