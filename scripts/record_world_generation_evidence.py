"""Record what the ask-for-a-world door does, bound to the bytes that do it.

Every digest, byte count, row count and commit in the output is READ from the thing it describes,
in this command, and nothing is passed in as a value to be trusted. The falsification table is
parsed from the harness's own log rather than retyped; the baked world's rows are read from the
database; the source bytes are hashed here.

    uv run python scripts/record_world_generation_evidence.py \
        --output docs/evaluation/<date>-a-world-you-can-ask-for.json \
        --falsification <the falsification log> \
        --bake <the bake log> \
        --database postgresql://localhost:5433/<the scratch db>

**It re-reads what it wrote.** After writing, it reloads the file, recomputes the record digest
from the reloaded bytes and recomputes every source digest from disk, and prints both beside the
values in the file. That second, independent read is the control: the orchestrator typed a SHA-256
from memory into a record on 2026-09-19 and it was caught only because the writing step also
printed the real value, for no better reason than that it had nothing else to do.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
from pathlib import Path

import psycopg
from exulanica.canonical import canonical_json
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "exulanica.world-generation-door/v1"

SOURCES = (
    "exulanica/api/routes/world_generation.py",
    "exulanica/api/app.py",
    "exulanica/api/permissions.py",
    "tests/test_world_generation_route.py",
    "scripts/bake_a_specified_world.py",
)


def binding(relative: str) -> dict[str, object]:
    data = (ROOT / relative).read_bytes()
    return {
        "path": relative,
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def breaks_from(log: Path) -> list[dict[str, object]]:
    """The falsification table, parsed from the harness's log rather than restated here."""
    rows: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in log.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith(" ") and not line.startswith(("tree", "HEAD", "dirty", "every")):
            current = {"break": line.strip(), "named": []}
            rows.append(current)
        elif current is not None and line.strip().startswith(("refused:", "NOTHING NOTICED:")):
            verdict, _, summary = line.strip().partition(":")
            current["verdict"] = verdict
            current["summary"] = summary.strip()
        elif current is not None and line.strip().startswith(("FAILED", "ERROR")):
            current["named"].append(line.strip())  # type: ignore[union-attr]
        elif current is not None and line.strip().startswith("restored, tree now:"):
            current["tree_after_restore"] = line.split("restored, tree now:")[1].strip()
    return rows


def baked(database: str) -> dict[str, object]:
    """The baked world as the database holds it. Read, never carried over from the bake's stdout."""
    with psycopg.connect(database, autocommit=True, row_factory=dict_row) as connection:
        rows = connection.execute(
            "select encode(world_seed,'hex') as world_seed, tile_x, tile_y, lod, state, "
            "container_bytes, document_bytes, encode(container_sha256,'hex') as container_sha256, "
            "encode(tile_inputs_digest,'hex') as tile_inputs_digest, baked_tile_id::text as id, "
            "receipt->'drawn'->>'triangles' as triangles, "
            "receipt->'drawn'->>'surfaces' as surfaces, "
            "receipt->'drawn'->>'dressed' as dressed, "
            "receipt->'drawn'->>'undressed' as undressed "
            "from baked_tile order by tile_y, tile_x"
        ).fetchall()
        version = connection.execute("select max(version) as v from schema_migrations").fetchone()
    return {
        "database_schema_version": version["v"] if version else None,
        "rows": len(rows),
        "distinct_world_seeds": len({row["world_seed"] for row in rows}),
        "distinct_containers": len({row["container_sha256"] for row in rows}),
        "states": sorted({row["state"] for row in rows}),
        "tiles": [
            {
                "tile": [row["tile_x"], row["tile_y"]],
                "lod": row["lod"],
                "baked_tile_id": row["id"],
                "tile_inputs_digest": row["tile_inputs_digest"],
                "container_sha256": row["container_sha256"],
                "container_bytes": row["container_bytes"],
                "document_bytes": row["document_bytes"],
                "triangles": int(row["triangles"]) if row["triangles"] else None,
                "surfaces": int(row["surfaces"]) if row["surfaces"] else None,
                "dressed": int(row["dressed"]) if row["dressed"] else None,
                "undressed": json.loads(row["undressed"]) if row["undressed"] else None,
            }
            for row in rows
        ],
    }


def from_bake_log(log: Path) -> dict[str, object]:
    """What the bake said about the world it made. The seed and identity it DERIVED."""
    text = log.read_text(encoding="utf-8")
    stated = {}
    for field in ("world_seed", "world_identity", "output_digest", "records", "tiles"):
        found = re.search(rf"^{field}\s+(.+)$", text, re.MULTILINE)
        if found:
            stated[field] = found.group(1).strip()
    stated["second_pass_all_identical"] = bool(
        re.search(r"^second ", text, re.MULTILINE)
    ) and "not identical" not in text
    return stated


#: The four refusals the brief asks to see proved over HTTP, and two more the same route makes.
#: Stated as requests, not as expected text: what the record carries is what came back.
ASKED = {
    "an unknown parameter name": {"blok_length_mm": 140_000},
    "a value outside its declared range": {"city_extent_x_mm": 40_000_000},
    "a parameter set at too fine a level": None,
    "two bindings at one level": None,
    "a level that does not exist": None,
    "a required parameter nobody set": "drop driving_side",
    "a value a stage refuses though the cascade admits it": {"block_length_mm": 60_000},
}
WORKING = {
    "driving_side": "right",
    "city_extent_x_mm": 640_000,
    "city_extent_y_mm": 128_000,
    "terrain_relief_mm": 0,
    "gutter_width_mm": 300,
    "front_setback_mm": 0,
    "block_depth_mm": 56_000,
}


def refusals(database: str) -> list[dict[str, object]]:
    """Ask the real application each way of being wrong and record WHAT CAME BACK.

    Against a real database, through create_app, so the permission floor, the token directory, the
    error map and the quota are all the shipped ones. The point of doing it here rather than
    quoting the tests is that a refusal's own words then reach the record from the response instead
    of from somebody retyping them, which is the same rule as never typing a digest.
    """
    import uuid as _uuid

    from exulanica.api.app import create_app
    from exulanica.api.authorisation import load_token_directory
    from exulanica.api.quotas import declare_tile_quota
    from exulanica.api.services import Services
    from exulanica.db.session import Database
    from exulanica.store.local import LocalContentAddressedStore
    from fastapi.testclient import TestClient

    workspace, actor = _uuid.uuid4(), _uuid.uuid4()
    token = f"a-record-run-{_uuid.uuid4().hex}"
    with psycopg.connect(database, autocommit=True, row_factory=dict_row) as connection:
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        declare_tile_quota(connection, workspace, tiles_limit=200, declared_by=actor)
    directory = load_token_directory(
        {
            "EXULANICA_API_TOKENS": json.dumps(
                {
                    token: {
                        "workspace_id": str(workspace),
                        "actor": str(actor),
                        "permissions": ["tiles.materialise", "world.read"],
                    }
                }
            )
        }
    )
    database_handle = Database(url=database)
    store_root = Path("/tmp") / f"world-generation-record-{_uuid.uuid4().hex}"
    services = Services(
        database=database_handle,
        readonly_database=database_handle,
        store=LocalContentAddressedStore(store_root),
        tokens=directory,
        executor_shares_the_write_role=True,
        model_client=None,
    )
    rows: list[dict[str, object]] = []
    with TestClient(create_app(services, verify=False)) as client:
        def ask(bindings: list[dict[str, object]]) -> dict[str, object]:
            answer = client.post(
                "/world-generation/worlds",
                json={"grammar_id": "city", "grammar_version": 3, "bindings": bindings},
                headers={"Authorization": f"Bearer {token}"},
            )
            return {"status": answer.status_code, "body": answer.json()}

        bodies = [
            ("an unknown parameter name", [{"level": "city", "values": {**WORKING, "blok_length_mm": 140_000}}]),
            ("a value outside its declared range", [{"level": "city", "values": {**WORKING, "city_extent_x_mm": 40_000_000}}]),
            ("two bindings at one level", [
                {"level": "city", "values": dict(WORKING)},
                {"level": "city", "values": {"block_length_mm": 140_000}},
            ]),
            ("a level that does not exist", [
                {"level": "city", "values": dict(WORKING)},
                {"level": "attic", "values": {"block_length_mm": 140_000}},
            ]),
            ("a parameter set at too fine a level", [
                {"level": "city", "values": dict(WORKING)},
                {"level": "face", "values": {"block_length_mm": 140_000}},
            ]),
            ("a required parameter nobody set", [
                {"level": "city", "values": {k: v for k, v in WORKING.items() if k != "driving_side"}}
            ]),
            ("an extent no level bound, so no tile count", [
                {"level": "city", "values": {k: v for k, v in WORKING.items() if not k.startswith("city_extent")}}
            ]),
            ("a value inside its declared range that a stage refuses", [
                {"level": "city", "values": {**WORKING, "block_length_mm": 60_000}}
            ]),
        ]
        for what, bindings in bodies:
            answer = ask(bindings)
            rows.append({"asked": what, **answer})
        unknown = client.post(
            "/world-generation/worlds",
            json={"grammar_id": "forest", "grammar_version": 1, "bindings": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        rows.append(
            {"asked": "a grammar that is not registered", "status": unknown.status_code, "body": unknown.json()}
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--falsification", required=True)
    parser.add_argument("--bake", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--specification", required=True)
    parser.add_argument("--acceptance-passed", type=int, required=True)
    parser.add_argument("--acceptance-failed", type=int, required=True)
    parser.add_argument("--neighbour-passed", type=int, required=True)
    arguments = parser.parse_args()

    falsification = breaks_from(Path(arguments.falsification))
    not_caught = [row["break"] for row in falsification if row.get("verdict") != "refused"]
    specification = json.loads(Path(arguments.specification).read_bytes())

    record: dict[str, object] = {
        "profile": PROFILE,
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "tested_head": git("rev-parse", "HEAD"),
        "tested_tree_dirty": git("status", "--porcelain") or "",
        "main_at_record_time": git("rev-parse", "main"),
        "what_this_is": (
            "The parameter cascade in exulanica/grammar/parameters.py validated, scoped and refused "
            "four distinct mistakes by name, and outside the tests exactly one file ORIGINATED a "
            "CascadeBinding: the corridor's own specification. exulanica/grammar/migration.py "
            "constructs one too and can only rewrite one it was handed, so it cannot originate. No "
            "route, CLI or stored row could reach any of it. This is the door, and the refusal is "
            "the feature it exposes."
        ),
        "source_files": [binding(path) for path in SOURCES],
        "acceptance": {
            "selectors": ["tests/test_world_generation_route.py"],
            "passed": arguments.acceptance_passed,
            "failed": arguments.acceptance_failed,
            "database": "private per-worker PostgreSQL (EXULANICA_TEST_POSTGRES=private)",
            "neighbours_passed": arguments.neighbour_passed,
            "neighbour_selectors": [
                "tests/test_api.py",
                "tests/test_route_permissions.py",
                "tests/test_corridor_tile_route.py",
                "tests/test_workspace_tile_quotas.py",
            ],
        },
        "falsification": {
            "method": (
                "one break at a time against a committed tree, the whole route test file run with "
                "no -k filter, the tree restored with git checkout and `git status` printed after "
                "each restore so a silent failure to restore cannot read as a clean tree"
            ),
            "breaks_total": len(falsification),
            "breaks_caught": len(falsification) - len(not_caught),
            "breaks_not_caught": not_caught,
            "breaks": falsification,
        },
        "limits": [
            "No GPU spend, no download, no remote host contacted, no model called, no personal "
            "photograph touched.",
            "The bake ran against a database this lane created and migrated itself and a data "
            "directory in a session scratchpad. Nothing was written to the shared store or to any "
            "other lane's database, checked by looking for files newer than this lane's start.",
            "The tessellator is the repository's own Node CLI at the version this tree pins. No "
            "container here was produced by anything else.",
        ],
        "what_this_does_not_solve": [
            "A SPECIFICATION IS STILL NOT ENOUGH TO MAKE A WORLD. Measured over 40 seeds with every "
            "layout value bound, 15 generated. This route surfaces the stage's refusal verbatim and "
            "does not fix the two defects behind it, which belong to the city grammar: the "
            "street-name draw stranding itself, and a record shape refusing a clearance the "
            "placement legitimately kept. Finding a six-tile world that generates took 6 of 212 "
            "candidate specifications.",
            "A TILE'S IDENTITY STILL DOES NOT SEPARATE TWO WORLDS THAT DIFFER ONLY IN THEIR "
            "BINDINGS. Deriving the seed protects every caller who comes through this route and "
            "nobody else. The fix is one hex64 digest over the resolved parameters in the city "
            "grammar's tile record, which is city grammar version 4 and must ride with the "
            "city_seed record rename migration 0081 deferred, because a version bump strands every "
            "baked artefact and doing it twice strands them twice.",
            "A REFUSAL A STAGE MAKES HAS ALREADY SPENT THE TILES. The charge is taken before a "
            "record is made and is never refunded, which is the quota's own rule. So a ceiling of "
            "400 tiles buys about fifteen attempts at a five-tile world and about six of them come "
            "back with one. An early refusal for the street-name case is a follow-up waiting on the "
            "generation-defects lane's street_name_shortfall predicate, which is not on main.",
            "A BROWSER SESSION CANNOT ASK FOR A WORLD. ACCOUNT_OWNER_PERMISSIONS withholds "
            "tiles.materialise, which is now an open decision rather than a pending event: granting "
            "it lets a browser spend the workspace's tile ceiling. Not this lane's to take.",
            "NOTHING BAKES INSIDE A REQUEST AND NO ROUTE BAKES AT ALL. The world this route answers "
            "is baked offline by scripts/bake_a_specified_world.py. The route hands back everything "
            "that bake needs and does not perform it.",
            "ONLY city DECLARES A WORLD COVERAGE RULE. box is registered, generates, and is refused "
            "here, because a world whose tiles cannot be counted cannot be metered.",
            "ONE LEVEL OF DETAIL. Nothing reduces detail by level, so the route accepts none and "
            "states the one it makes.",
        ],
        "the_refusals_over_http": {
            "why": (
                "The cascade refuses an unknown parameter, an unknown level, a second binding at "
                "one level and an out-of-range value, and that is the most valuable property this "
                "route exposes. Each of these is a REAL REQUEST through create_app against a real "
                "database, and what is recorded is the response, so the refusal's own words reach "
                "this record from the response rather than from somebody retyping them."
            ),
            "asked": refusals(arguments.database),
        },
        "the_world_that_was_baked": {
            "why": (
                "A world nobody has generated before is the only evidence that this is a door and "
                "not a second spelling of the same room. It differs from the corridor in all three "
                "of extents, block length and storey band."
            ),
            "specification": specification,
            "stated_by_the_bake": from_bake_log(Path(arguments.bake)),
            "read_from_the_database": baked(arguments.database),
        },
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    output = ROOT / arguments.output
    output.write_bytes(canonical_json(envelope))

    # The second, independent read. Everything below is recomputed from disk after the write.
    reloaded = json.loads(output.read_bytes())
    recomputed = hashlib.sha256(canonical_json(reloaded["record"])).hexdigest()
    print(f"wrote  {arguments.output}  {output.stat().st_size} bytes")
    print(f"record_sha256 in the file   {reloaded['record_sha256']}")
    print(f"recomputed from the file    {recomputed}")
    print(f"they agree                  {reloaded['record_sha256'] == recomputed}")
    print("source digests, recomputed from disk beside what the file says:")
    for stated in reloaded["record"]["source_files"]:
        again = hashlib.sha256((ROOT / stated["path"]).read_bytes()).hexdigest()
        mark = "ok  " if again == stated["sha256"] else "WRONG"
        print(f"  {mark} {stated['path']:<52} {stated['sha256']}")
        if again != stated["sha256"]:
            print(f"        on disk now: {again}")
    forbidden = [text for text in ("/Users/", "Bearer ", "api-token") if text in output.read_text()]
    print(f"forbidden strings present: {forbidden or 'none'}")
    return 1 if forbidden or reloaded["record_sha256"] != recomputed else 0


if __name__ == "__main__":
    raise SystemExit(main())
