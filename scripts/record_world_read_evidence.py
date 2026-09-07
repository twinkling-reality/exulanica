"""Read the retained real scenes through the Phase 10 read paths and retain what they answer.

Read-only against ``postgresql://localhost:5433/exulanica_spine_test`` and the retained
content-addressed store. Writes one digest-bound record under ``docs/evaluation`` and nothing else:
no database write, no store write, no token printed.

Every number in the record is measured here rather than copied from a previous document, which is
the point. The first version of the World Read bundle's ``recorded_sha256`` could not be reproduced
offline, and no test in the suite could see it, because the tests compared two of the same code's
answers. Reading the real scenes is what caught it.
"""

import argparse
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.graph.observations import scene_observations
from exulanica.graph.world_read import world_read_bundle
from exulanica.store.local import LocalContentAddressedStore

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
STORE_PATH = ROOT / ".exulanica/reference-baseline/runtime/blobs"

#: The retained collections, named in docs/retained-reference-workflow.md. Row-level security keys
#: off the session's workspace, so a scan without one of these returns nothing at all.
WORKSPACES = {
    "chili-salmon-bowl": uuid.UUID("bdba4f95-07e3-4ff6-8c5b-eb8989ab63cb"),
    "montserrat-volcanic-sample": uuid.UUID("79004d44-ca24-4d17-9eef-56786415e233"),
}


def _canonical_bytes(value: object) -> bytes:
    """Canonical JSON, spelled out here rather than imported.

    This is the recipient's half of the digest claim: if it and ``exulanica.canonical`` disagree,
    the bundle's promise that another implementation reproduces its digest is false.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _scene_record(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: LocalContentAddressedStore,
) -> dict[str, object]:
    envelope = world_read_bundle(connection, workspace, scene_id, store)
    if envelope is None:
        return {"scene_id": str(scene_id), "readable": False}
    wire = json.loads(json.dumps(envelope))
    bundle = wire["bundle"]

    recorded_input = {key: bundle[key] for key in bundle["recorded_keys"]}
    record: dict[str, object] = {
        "scene_id": str(scene_id),
        "readable": True,
        "bundle_sha256": envelope["bundle_sha256"],
        "recorded_sha256": bundle["recorded_sha256"],
        "bundle_byte_size": len(_canonical_bytes(bundle)),
        # Recomputed from the wire form by an independent canonicaliser, which is the whole claim.
        "bundle_digest_reproduces_offline": hashlib.sha256(_canonical_bytes(bundle)).hexdigest()
        == envelope["bundle_sha256"],
        "recorded_digest_reproduces_offline": hashlib.sha256(
            _canonical_bytes(recorded_input)
        ).hexdigest()
        == bundle["recorded_sha256"],
        "recorded_keys": list(bundle["recorded_keys"]),
        "member_count": bundle["scene"]["member_count"],
        "registered_member_count": bundle["scene"]["registered_member_count"],
        "rendering_substrate": bundle["scene"]["rendering_substrate"],
        "recorded_rung": bundle["rungs"]["recorded"],
        "displayed_rung": bundle["rungs"]["displayed"],
        "views_with_recovered_cameras": sum(
            1 for view in bundle["views"] if view["camera"] is not None
        ),
        "point_map_entries": sum(1 for entry in bundle["geometry"] if entry["kind"] == "point_map"),
        "trained_geometry_entries": sum(
            1 for entry in bundle["geometry"] if entry["kind"] == "trained_geometry"
        ),
        "generated_entries": len(bundle["generated"]),
        "region_graph_state": bundle["region_graph"]["state"],
        "release_state": bundle["release"]["state"],
        "person_consent": bundle["consent"]["person_consent"],
        "captures_with_a_screening_receipt": sum(
            1
            for item in bundle["consent"]["per_capture"].values()
            if item["screening"]["state"] == "screened"
        ),
        "captures_screened_by_a_named_human": sum(
            1
            for item in bundle["consent"]["per_capture"].values()
            if item["screening"]["named_human_reviewer"]
        ),
        # No geometry entry may carry a key a consumer would read as a citation.
        "no_geometry_entry_names_evidence": all(
            {
                "support_span_ids",
                "span_id",
                "evidence",
                "evidence_span_id",
                "assertion_id",
            }.isdisjoint(entry)
            for entry in bundle["geometry"]
        ),
    }

    observations = scene_observations(connection, workspace, scene_id, store)
    if observations is None:
        record["observation_graph"] = {
            "available": False,
            "reason": "no accepted pose receipt for this scene, or it is withdrawn",
        }
    else:
        tracks = [point["track_length"] for point in observations["points"]]
        held = [point["observations_retained"] for point in observations["points"]]
        record["observation_graph"] = {
            "available": True,
            "provenance": observations["provenance"],
            "retained_per_image": observations["retained_per_image"],
            "point_count": observations["point_count"],
            "points_observed_by_more_than_one_photograph": sum(1 for value in held if value > 1),
            "observations_held": sum(held),
            "max_track_length": max(tracks) if tracks else 0,
            # The honesty check: a point may never claim to hold more observations than exist.
            "no_point_holds_more_than_its_track_length": all(
                point["observations_retained"] <= point["track_length"]
                for point in observations["points"]
            ),
        }
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-tests", default=None, help="e.g. '1698 passed'")
    parser.add_argument("--web-tests", default=None, help="e.g. '784 passed'")
    # A record is a dated observation of a tree, not a file that tracks the tree. Re-running this
    # against a changed tree writes a NEW record and binds it to the one it follows; overwriting
    # the old one would destroy exactly the chain `predecessor_record` exists to build, and would
    # leave a record whose stated limitations describe a tree nobody can check out any more.
    parser.add_argument(
        "--date", required=True, help="ISO date this run was executed, e.g. 2026-09-07"
    )
    parser.add_argument(
        "--predecessor",
        default=None,
        help="path, relative to the repository root, of the record this one follows",
    )
    arguments = parser.parse_args()

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    store = LocalContentAddressedStore(STORE_PATH)

    collections = []
    with psycopg.connect(DATABASE, row_factory=dict_row) as connection:
        connection.execute("set role exulanica_app")
        for label, workspace in WORKSPACES.items():
            connection.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
            )
            scenes = connection.execute(
                "select scene_id from reconstruction_scene order by scene_id"
            ).fetchall()
            collections.append(
                {
                    "collection": label,
                    "workspace_id": str(workspace),
                    "scenes": [
                        _scene_record(connection, workspace, row["scene_id"], store)
                        for row in scenes
                    ],
                }
            )

    record: dict[str, object] = {
        "profile": "exulanica.phase-10-read-paths/v1",
        "date": arguments.date,
        "head": head,
        "database": DATABASE,
        "store": str(STORE_PATH.relative_to(ROOT)),
        "read_only": True,
        "what_this_establishes": (
            "The Phase 10 read paths answer over the retained real reconstructions, and their "
            "digests reproduce offline under an independent canonicaliser. It establishes nothing "
            "about visual quality, physical scale, or per-person consent, none of which this work "
            "touched."
        ),
        "collections": collections,
        "verification": {
            "backend": arguments.backend_tests,
            "web": arguments.web_tests,
        },
        "limitations": [
            "The per-person consent layer is present, and every retained photograph is still "
            "unscreened for people: person_region, person_subject and person_presentation_consent "
            "all hold zero rows for both collections. So every bundle reports person_consent "
            "unscreened, which says nobody has looked, and never that there is nobody there.",
            "release internal_only is a decision, not a default. The bundle carries no state for "
            "any individual person, so a recipient holding it cannot check a more permissive "
            "claim; release.not_yet_earnable states what each higher state would require.",
            "The masking chain has never run against these photographs. It is proven against "
            "PostgreSQL on synthetic data (tests/test_person_masking_end_to_end.py); nobody has "
            "seen it act on the bowl or the volcanic collection.",
            "No structural snapshot is committed in either retained workspace, so every bundle "
            "reports its region graph unavailable.",
            "No generation has been recorded against a real scene; the generated tier is "
            "exercised only by tests.",
            "Place alignment is measured against numeric fixtures only. No two real captures of "
            "one place exist.",
        ],
    }
    if arguments.predecessor:
        predecessor = json.loads((ROOT / arguments.predecessor).read_bytes())
        record["predecessor_record"] = {
            "path": arguments.predecessor,
            "record_sha256": hashlib.sha256(canonical_json(predecessor["record"])).hexdigest(),
        }
    output = ROOT / f"docs/evaluation/{arguments.date}-phase-10-read-paths.json"
    output.write_text(
        json.dumps(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
