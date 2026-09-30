"""What a restored judge stack holds of a workspace's generated worlds: each tile's bake and bytes.

    EXULANICA_DATABASE_URL=<restored database> EXULANICA_DATA_DIR=<restored data directory> \\
        python seedcheck.py WORKSPACE_ID

Run by the rehearsal with the application's own environment, after ``exulanica-seed restore``
brought a fresh database and data directory to an archive. For every generated world of the
workspace it reads each tile the way the application does (``generated_tiles``), then reads the
current bake's container from the restored tile store and holds it to the digest the bake records.
Prints one JSON document; reads only.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid

from exulanica.db.session import Database
from exulanica.env import resolve_data_dir
from exulanica.evidence.blob import BlobId
from exulanica.store.namespaces import tile_store
from exulanica.world.baked_tiles import BakedTileRepository
from exulanica.world.generated_worlds import generated_tiles


def main() -> int:
    workspace = uuid.UUID(sys.argv[1])
    database = Database.from_env()
    store = tile_store(resolve_data_dir())
    worlds = []
    with database.session(workspace) as connection:
        rows = connection.execute(
            "select e.world_id, v.source_snapshot_id from saved_world_entry e"
            " join world_identity w on w.workspace_id = e.workspace_id and w.world_id = e.world_id"
            " join world_alternate_version v on v.workspace_id = e.workspace_id"
            "  and v.world_id = e.world_id and v.version_id = e.authored_version_id"
            " where e.workspace_id = %s and w.kind = 'generated' order by e.created_at",
            (workspace,),
        ).fetchall()
        for row in rows:
            tiles = []
            for tile in generated_tiles(
                connection, workspace, row["world_id"], row["source_snapshot_id"]
            ):
                held = None
                if tile.baked_tile_id is not None:
                    bake = BakedTileRepository(connection, store).read(tile.baked_tile_id)
                    try:
                        data = store.get(BlobId(bytes.fromhex(bake.container_sha256)))
                        held = hashlib.sha256(data).hexdigest() == bake.container_sha256
                    except Exception as error:
                        held = f"{type(error).__name__}: {error}"
                tiles.append(
                    {
                        "tile": [tile.tile_x, tile.tile_y],
                        "state": tile.state,
                        "baked_tile_id": None
                        if tile.baked_tile_id is None
                        else str(tile.baked_tile_id),
                        "bytes_held_to_digest": held,
                    }
                )
            worlds.append({"world_id": row["world_id"], "tiles": tiles})
    print(json.dumps({"workspace_id": str(workspace), "generated_worlds": worlds}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
