"""The entity graph as one snapshot, which is what the interface renders against.

``graph-client``'s read model is explicit about why this is a snapshot rather than a live
connection: "Turn generation and index rendering both run against a snapshot rather than against
a live connection, because both must be reproducible in a test with no transport, and because
``stateVersion`` is what expires an update proposal."

**What this endpoint returns and what it deliberately does not.** The web read model was designed
against a fuller system than exists, and rather than filling its fields with plausible zeroes,
this returns what the server actually knows and leaves the mapping to the client adapter, which
documents each gap in one auditable place. Two gaps are worth naming here because they are
properties of the server rather than of the adapter:

*   **Islands are not a server concept.** An island is a layout unit, and ADR-0005 records that
    whether one is a single capture or a place-on-a-trip cluster is OPEN "until the real
    distribution of the corpus has been measured". So captures are returned and the client
    decides what an island is. A server that shipped an island id would be settling that
    question by accident.

    What IS returned is ``scene_groups``: the time-and-position clustering the ingest pipeline
    already computed and stored. That is not the same thing as an island and must not be read as
    one. It is an ingest artifact with its own provenance, the client is free to ignore it, and
    the field is named after what it is rather than after what the client does with it.
    It is carried on this payload rather than on a second endpoint because a grouping fetched at
    a different moment from the graph it groups can disagree with it, and the whole value of a
    snapshot is that its parts were true at one state version.
*   **Nothing counts citing answers, because no answer is stored.** The field exists in the read
    model because a tier 3 confirmation must state how many existing answers lose their citation,
    and that is a real requirement. It is not answerable yet, and a zero here would read as
    "none" rather than as "not recorded".
"""

from __future__ import annotations

from exulanica.graph.payload import (
    AssertionRow,
    EntityRow,
    GraphPayload,
    HistoryRow,
    OccurrenceRow,
    ProposalRow,
    ReconstructionSceneMemberRow,
    ReconstructionSceneRow,
    SceneGroupRow,
    ScenePointMapPlacementRow,
)
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.graph.scene_rungs import SceneRungRow, scene_rung_rows
from exulanica.graph.snapshot import read_snapshot

__all__ = [
    "AssertionRow",
    "EntityRow",
    "GraphPayload",
    "HistoryRow",
    "OccurrenceRow",
    "ProposalRow",
    "ReconstructionSceneMemberRow",
    "ReconstructionSceneRow",
    "SceneGroupRow",
    "ScenePointMapPlacementRow",
    "SceneRungRow",
    "read_snapshot",
    "reconstruction_scene_rows",
    "scene_rung_rows",
]
