"""Run bootstrap acceptance on the authorised inspection copy, never the retained database.

No model calls. Tokens are read from the runtime access file and never recorded. The marker is
removed through a stored removal after verification. Re-composition restores the original current
contract in the same transaction, retaining the authored version and source inspector state.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path

from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.canonical import sha256_of_canonical
from exulanica.db import Database
from exulanica.ingest.repository import IngestRepository
from exulanica.orchestration.reference_world import compose_reference_sources
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import WorldObjectRepository, WorldStyleRepository
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo

TABLES = (
    "world_structure_snapshot",
    "world_structure_preview",
    "world_structure_audit_event",
    "world_alternate_version",
    "world_topology_contract",
    "world_topology_source",
)


def digest(value):
    return sha256_of_canonical(value).hex()


def run():
    base = os.environ["EXULANICA_REFERENCE_DATABASE_URL"]
    if conninfo_to_dict(base).get("dbname") != "exulanica_inspect_test":
        raise RuntimeError("this evaluation is authorised only on exulanica_inspect_test")
    runtime = Path(os.environ["BOOTSTRAP_REFERENCE_RUNTIME"])
    access = json.loads((runtime / "access.json").read_bytes())
    selected = {name: access["scenes"][name] for name in ("volcanic", "first-place")}
    writer = Database(make_conninfo(base, options="-c role=exulanica_app"))
    reader = Database(make_conninfo(base, options="-c role=exulanica_ro"))
    tokens = {
        row["token"]: {"workspace_id": row["workspace_id"], "actor": access["actor"]}
        for row in selected.values()
    }
    services = Services(
        database=writer,
        readonly_database=reader,
        store=LocalContentAddressedStore(runtime / "blobs"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(tokens)}),
        executor_shares_the_write_role=False,
        model_client=None,
    )
    results = []
    with TestClient(create_app(services, verify=False)) as client:
        for name, row in selected.items():
            workspace = uuid.UUID(row["workspace_id"])
            client.headers["Authorization"] = f"Bearer {row['token']}"

            def counts(workspace=workspace):
                with reader.session(workspace) as connection:
                    return {
                        table: connection.execute(f"select count(*) as n from {table}").fetchone()[
                            "n"
                        ]
                        for table in TABLES
                    }

            def sources():
                response = client.get("/world/source-media")
                response.raise_for_status()
                return response.json()

            before_sources = sources()
            original_digest = client.get("/world/styles/current").json()["current_topology_digest"]
            before_counts = counts()
            body = {"base_topology_digest": original_digest, "title": "My alternate world"}
            first = client.post("/world/versions/bootstrap", json=body)
            first.raise_for_status()
            opened = first.json()
            after_counts = counts()
            assert sources() == before_sources
            assert (
                client.get("/world/styles/current").json()["current_topology_digest"]
                == original_digest
            )
            second = client.post("/world/versions/bootstrap", json=body)
            second.raise_for_status()
            assert second.json() == {**opened, "snapshot": "reused", "version": "reused"}
            assert counts() == after_counts
            stale = client.post(
                "/world/versions/bootstrap", json={"base_topology_digest": "stale-evaluation-base"}
            )
            assert (
                stale.status_code == 409 and stale.json()["code"] == "protected_topology_conflict"
            )
            assert counts() == after_counts
            version_path = f"/world/versions/{opened['version_id']}"
            object_id = f"bootstrap-proof:{uuid.uuid4()}"
            asset = next(
                a for a in client.get("/world/assets").json() if a["asset_key"] == "cc0.marker-cube"
            )
            added = client.post(
                f"{version_path}/objects",
                json={
                    "base_state_sha256": opened["state_sha256"],
                    "object_id": object_id,
                    "asset_sha256": asset["content_sha256"],
                    "region_id": opened["regions"][0],
                    "transform": dict(
                        x_mm=1500, y_mm=0, z_mm=-800, yaw_microradians=0, scale_milli=1000
                    ),
                    "origin_role": "fictional",
                },
            )
            added.raise_for_status()
            added_state = added.json()
            with writer.session(workspace) as connection:
                assert (
                    connection.execute("select current_user as role").fetchone()["role"]
                    == "exulanica_app"
                )
                styles = WorldStyleRepository(connection, workspace)
                original = styles.current_topology_contract()
                assert len(original.region_ids) == 1
                captures = connection.execute(
                    "select distinct c.capture_id,c.blob_sha256 from world_topology_source s "
                    "join evidence_span e on e.workspace_id=s.workspace_id "
                    "and e.span_id=s.evidence_span_id "
                    "join capture c on c.workspace_id=e.workspace_id "
                    "and c.blob_sha256=e.blob_sha256 "
                    "where s.workspace_id=%s and s.world_id=%s and s.topology_digest=%s "
                    "order by c.capture_id",
                    (workspace, original.world_id, original.topology_digest),
                ).fetchall()
                capture_inputs = [
                    (r["capture_id"], bytes(r["blob_sha256"]).hex(), "existing source")
                    for r in captures
                ]
                recomposed = compose_reference_sources(
                    IngestRepository(connection, workspace),
                    region_id=original.region_ids[0],
                    captures=capture_inputs,
                    source_manifest_sha256=digest([[str(c), sha] for c, sha, _ in capture_inputs]),
                )
                reread = WorldObjectRepository(connection, workspace).version(
                    uuid.UUID(opened["version_id"])
                )
                assert reread.state_sha256 == added_state["state_sha256"]
                assert any(o.object_id == object_id and not o.removed for o in reread.objects)
                assert not reread.source_invalidated
                styles.register_topology(original)
            assert client.get(version_path).json() == added_state
            assert sources() == before_sources
            removed = client.post(
                f"{version_path}/objects/{object_id}/remove",
                json={"base_state_sha256": added_state["state_sha256"]},
            )
            removed.raise_for_status()
            assert next(o for o in removed.json()["objects"] if o["object_id"] == object_id)[
                "removed"
            ]
            bindings = [
                {k: source[k] for k in ("source_id", "slot_key", "region_id", "evidence_span_id")}
                for source in before_sources
            ]
            results.append(
                dict(
                    workspace=name,
                    workspace_id=str(workspace),
                    initial=opened,
                    retry=second.json(),
                    stale_status=stale.status_code,
                    stale_code=stale.json()["code"],
                    counts_before=before_counts,
                    counts_after_bootstrap=after_counts,
                    source_count=len(before_sources),
                    source_bindings=bindings,
                    source_media_sha256_before=digest(before_sources),
                    source_media_sha256_after=digest(sources()),
                    topology_digest=original_digest,
                    recompose_digest=recomposed["topology_digest"],
                    object_id=object_id,
                    object_survived_recompose=True,
                    object_state_sha256=added_state["state_sha256"],
                    cleanup=(
                        "stored removal; original composed topology restored "
                        "in recompose transaction"
                    ),
                    cleanup_state_sha256=removed.json()["state_sha256"],
                )
            )
    predecessor = Path("docs/evaluation/2026-09-11-developer-proof.json")
    record = dict(
        profile="exulanica.version-bootstrap-evaluation/v1",
        completed_at=dt.datetime.now(dt.UTC).isoformat(),
        predecessor=dict(
            path=str(predecessor), sha256=hashlib.sha256(predecessor.read_bytes()).hexdigest()
        ),
        database="exulanica_inspect_test",
        roles=["exulanica_app", "exulanica_ro"],
        migration="NONE",
        model_calls=0,
        transport="authenticated HTTP routes via TestClient, PostgreSQL runtime roles",
        workspaces=results,
        limitations=[
            "First-place already had a snapshot and alternate; this run proves reuse there. "
            "Fresh multi-source creation is covered by PostgreSQL tests.",
            "No browser interaction was exercised in this evaluation. "
            "The UI is checked by typecheck and the existing Vitest suite.",
            "Full backend suite deferred to the serialized integration run "
            "per integration coordination.",
        ],
    )
    output = Path(
        os.environ.get("BOOTSTRAP_EVALUATION_OUTPUT", "/tmp/version-bootstrap-reference.json")
    )
    output.write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(output),
                "workspaces": [
                    {
                        "name": r["workspace"],
                        "sources": r["source_count"],
                        "snapshot": r["initial"]["snapshot"],
                    }
                    for r in results
                ],
            }
        )
    )


if __name__ == "__main__":
    run()
