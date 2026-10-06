"""The bake stage a test records a tile under (migration 0144).

`record_baked_tile_bake` stores a bake only for the stage the schema states as current, which is
the stage the code runs (`STAGES["baked_tile"]`). A test that records a bake names that stage; a
test about what a newer tessellator's bake does states the newer stage first, as the migration
that ships a stage change does, and gets the schema's own stage back afterwards.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from exulanica.ingest.stages import STAGES

#: The stage the code runs, which migration 0144 states as current.
CURRENT_STAGE_VERSION: int = STAGES["baked_tile"].version
CURRENT_STAGE_PARAMS: bytes = STAGES["baked_tile"].params_digest


@contextlib.contextmanager
def stated_stage(owner, version: int, params: bytes) -> Iterator[None]:
    """The bake stage ``version`` with ``params`` stated as current, as a migration states one,
    then the stage the schema stated before restored. The table keeps every row it is given (its
    trigger refuses a change), so the restore turns that trigger off for the owner's own
    connection alone."""
    previous = owner.execute(
        "select stage_version, stage_params_sha256 from baked_tile_stage where retired_at is null"
    ).fetchone()
    owner.execute("update baked_tile_stage set retired_at = now() where retired_at is null")
    owner.execute(
        "insert into baked_tile_stage (stage_version, stage_params_sha256) values (%s, %s)",
        (version, params),
    )
    owner.commit()
    try:
        yield
    finally:
        owner.rollback()
        owner.execute("alter table baked_tile_stage disable trigger tg_baked_tile_record_kept")
        owner.execute(
            "delete from baked_tile_stage where stage_version = %s and stage_params_sha256 = %s",
            (version, params),
        )
        owner.execute(
            "update baked_tile_stage set retired_at = null "
            "where stage_version = %s and stage_params_sha256 = %s",
            (_field(previous, 0, "stage_version"), _field(previous, 1, "stage_params_sha256")),
        )
        owner.execute("alter table baked_tile_stage enable trigger tg_baked_tile_record_kept")
        owner.commit()


def _field(row, index: int, name: str):
    """A column of a row read with either the tuple or the dict row factory."""
    return row[name] if isinstance(row, dict) else row[index]
