"""A read projection of retained identities, never identities inferred from scene drawings.

Each source remains independently pinned. Role membership links a subject to its native role
read; eligibility and execution are answered by that role and the selected-subject detail.
"""

from __future__ import annotations

from typing import Any

from exulanica.world.society_engines import society_engine

PROFILE = "exulanica.world-inventory/v1"


def _society_label(record: dict[str, Any]) -> str | None:
    """Prefer the society's retained display name without inventing one from its kind."""
    for key in ("display_name", "name"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def inventory_document(
    version: dict[str, Any],
    models: dict[str, Any],
    society: dict[str, Any] | None,
    *,
    society_unavailable: str | None = None,
) -> dict[str, Any]:
    """Compose already-authorized public documents without another source read or row cap."""
    entities: list[dict[str, Any]] = []
    authored_things: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    authored_pin = {"state_sha256": version["state_sha256"], "edit_seq": version["edit_seq"]}

    def covered(source: str, state: str, *, code: str | None = None, read: Any = None) -> None:
        coverage.append({"source": source, "state": state, "code": code, "read": read})

    def entity(
        source: str,
        identity: str,
        category: str,
        record: dict[str, Any],
        availability: str,
        label: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "reference": {"source": source, "id": identity},
            "aliases": [],
            "label": label or identity,
            "category": category,
            "availability": availability,
            "sources": [{"source": source, "record": record}],
            "role_instances": [],
            "detail": None,
        }
        entities.append(row)
        return row

    for record in version["objects"]:
        if record["removed"]:
            continue
        asset = record.get("workspace_asset") or record.get("asset") or {}
        entity(
            "authored-object",
            record["object_id"],
            "object",
            record,
            asset.get("availability", "unknown"),
            asset.get("title"),
        )
    covered("authored.objects", "complete", read=authored_pin)
    for record in version["things"]:
        if record["removed"]:
            continue
        identity = record["thing_id"]
        authored_things[identity] = entity(
            "authored-thing",
            identity,
            "object",
            record,
            "gone" if record.get("gone") else "available",
            record["kind"].get("kind"),
        )
    covered("authored.things", "complete", read=authored_pin)
    for record in version["environment_instances"]:
        if not record["removed"]:
            entity(
                "environment-instance",
                record["instance_id"],
                "environment",
                record,
                record["availability"],
            )
    covered("authored.environment_instances", "complete", read=authored_pin)
    representations = [
        {
            "reference": {"source": "point-map-instance", "id": record["instance_id"]},
            "source": record,
            "availability": record["availability"],
        }
        for record in version["point_map_instances"]
        if not record["removed"]
    ]
    covered("authored.point_map_instances", "complete", read=authored_pin)
    society_pin = (
        None
        if society is None
        else {
            "society_id": society["society_id"],
            "engine": society["profile"],
            "tick": society["current_tick"],
            "state_sha256": society["state_sha256"],
        }
    )
    people_roles = [role for role in models["roles"] if role["subject"] == "person"]
    if society is not None:
        has_detail = society_engine(society["profile"]).state_family == "things"
        for collection, source, category in (
            ("inhabitants", "society-being", "being"),
            ("things", "society-thing", "object"),
        ):
            if collection not in society["state"]:
                covered(
                    f"society.{collection}",
                    "not_enumerated",
                    code="collection_not_in_state",
                    read=society_pin,
                )
                continue
            for record in society["state"][collection]:
                identity = str(record["id"])
                label = _society_label(record)
                row = authored_things.get(record.get("placed_id"))
                if row is None:
                    row = entity(source, identity, category, record, "available", label)
                else:
                    row["aliases"].append({"source": source, "id": identity})
                    row["sources"].append({"source": source, "record": record})
                    row["category"] = category
                    if label is not None:
                        row["label"] = label
                if collection == "inhabitants":
                    row["role_instances"] = [
                        {"role_key": role["key"], "subject_id": identity} for role in people_roles
                    ]
                if has_detail:
                    row["detail"] = {
                        "route": "GET /world/versions/{version_id}/subjects/{ref}",
                        "bind": {
                            "version_id": version["version_id"],
                            "ref": f"{'being' if category == 'being' else 'thing'}:{identity}",
                        },
                        "query": {"world_id": version["world_id"]},
                    }
            covered(f"society.{collection}", "complete", read=society_pin)
    else:
        for collection in ("inhabitants", "things"):
            covered(
                f"society.{collection}",
                "unavailable" if society_unavailable else "absent",
                code=society_unavailable,
            )
    for role in models["roles"]:
        if role["subject"] == "person":
            covered(
                f"role.{role['key']}.instances",
                "complete"
                if society is not None and "inhabitants" in society["state"]
                else "not_enumerated"
                if society is not None
                else "unavailable"
                if society_unavailable
                else "absent",
                code=society_unavailable,
                read=society_pin,
            )
            continue
        # The role host supplies these ids. A registered role or a refused enumeration supplies
        # no evidence that an instance exists (or that no instances exist).
        if role["subject"] == "signal":
            for subject in role.get("subjects", []):
                row = entity(
                    "role-subject",
                    subject["signal_id"],
                    "system",
                    subject,
                    "available",
                    subject.get("label"),
                )
                row["reference"]["role_key"] = role["key"]
                row["role_instances"] = [
                    {"role_key": role["key"], "subject_id": subject["signal_id"]}
                ]
            covered(
                f"role.{role['key']}.instances",
                "complete" if role.get("available") else "unavailable",
                code=role.get("reason"),
                read={"clock_second": models["clock_second"], "timebase": role.get("timebase")},
            )
        else:
            covered(f"role.{role['key']}.instances", "not_enumerated")
    for source in (
        "generated_semantics",
        "source_semantics",
        "reconstructed_scene_layers",
        "vehicles",
    ):
        covered(source, "not_enumerated")
    return {
        "profile": PROFILE,
        "world_id": version["world_id"],
        "version_id": version["version_id"],
        "read": {
            "source_snapshot_id": version["source_snapshot_id"],
            "source_invalidated": version["source_invalidated"],
            "authored_state_sha256": version["state_sha256"],
            "authored_edit_seq": version["edit_seq"],
            "society": society_pin,
            "models_clock_second": models["clock_second"],
        },
        "entities": entities,
        "representations": representations,
        "roles": models["roles"],
        "coverage": coverage,
        "consistency": "component-pinned",
        "assignment_authority": "native-role-and-subject-detail",
    }
