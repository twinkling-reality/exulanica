"""Select native authored things without serializing private runtime or actor records."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.placed_things import placed_thing_document
from exulanica.world_package.projects.checkpoint import ProjectError, document
from exulanica.world_package.projects.schema import Decision, Dependency, ModelBinding


def select_checkpoint(
    version: AlternateVersion,
    *,
    project_id: str,
    selected_thing_ids: frozenset[str],
    snapshot_sha256: str,
    dependencies: Sequence[Dependency],
    models: Sequence[ModelBinding] = (),
    decisions: Sequence[Decision] = (),
) -> dict[str, Any]:
    """Project an explicit selection from an already-authorized native version.

    The caller must obtain the version through the owning world's authorized read boundary and
    review rights to export each selected item. This pure function grants no read/export right.
    It includes no actors, edit log, other authored sections or implicit dependencies. It refuses
    invalidated sources and unavailable/support-bound things rather than silently degrading them.
    """
    if version.source_invalidated:
        raise ProjectError("an invalidated source cannot supply a project checkpoint")
    if version_delta_sha256(version) != version.state_sha256:
        raise ProjectError("native version state does not match its bound digest")
    things = {thing.thing_id: thing for thing in version.things}
    if not selected_thing_ids <= things.keys():
        raise ProjectError("selection names things absent from the native version")
    selected = [things[key] for key in sorted(selected_thing_ids)]
    if any(thing.kind_gone or thing.support is not None for thing in selected):
        raise ProjectError("unavailable kinds and support-bound placements are unsupported")
    if not selected:
        raise ProjectError("select at least one native thing")
    return document(
        {
            "profile": "exulanica.world-project/v1",
            "project_id": project_id,
            "source": {
                "world_id": version.world_id,
                "version_id": str(version.version_id),
                "snapshot_id": str(version.source_snapshot_id),
                "state_sha256": version.state_sha256,
                "snapshot_sha256": snapshot_sha256,
            },
            "forked_from": None,
            "region_ids": sorted({thing.region_id for thing in selected}),
            "things": [placed_thing_document(thing) for thing in selected],
            "dependencies": [dependency.model_dump() for dependency in dependencies],
            "models": [model.model_dump() for model in models],
            "decisions": [decision.model_dump() for decision in decisions],
        }
    )
