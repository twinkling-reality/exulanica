"""The look a generated world is made in: a pack of the host's library, named when it is made.

``POST /worlds/generated`` names the pack the person chose, or the library's default when they
chose none (:attr:`~exulanica.world.style_pack_library.StylePackLibrary.default`), so a town is
made already wearing a look, and a later change of the default never restyles a town already made.
The world is made first, its first appearance naming no pack; :func:`name_creation_look` then names
the pack in the appearance's next version, through the same preview and Apply a person's own
change takes (origin ``user``, reference :data:`WORLD_CREATION`), with the saved entry's resume
pointer moved in that same write. A write to a world's look is its own transaction
(:class:`~exulanica.world.repository.WorldStyleRepository`), so it follows the making's rather than
sharing it. Version history shows the choice, and a rollback to the first version returns the
world to naming no pack, which a page draws in the default look.
"""

from __future__ import annotations

import uuid
from typing import Final

from exulanica.world.models import (
    ProposalOrigin,
    ProposalProvenance,
    StylePackBinding,
    StyleProposal,
    StyleScope,
    StyleVersion,
)
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.saved_entries import SavedWorldEntry, SavedWorldEntryRepository

__all__ = ["WORLD_CREATION", "name_creation_look"]

#: The origin reference of the version that names a world's look when it is made.
WORLD_CREATION: Final = "world-creation"


def name_creation_look(
    entries: SavedWorldEntryRepository,
    entry: SavedWorldEntry,
    pack: StylePackBinding,
    actor: uuid.UUID,
) -> SavedWorldEntry:
    """Name ``pack`` in the appearance of the world ``entry`` was just saved for, moving the entry's
    resume pointer to that version in the same write, and return the entry as it then stands.

    The pack is checked against the host's library as any preview's is, and the connection must
    hold no open transaction, as every write to a world's look requires.
    """
    styles = WorldStyleRepository(entries.connection, entries.workspace_id, world_id=entry.world_id)
    base = styles.current()
    preview = styles.preview(
        StyleProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(ProposalOrigin.USER, actor, WORLD_CREATION),
            scope=StyleScope("global"),
            base_style_version_id=base.version_id,
            base_topology_digest=base.topology_digest,
            profile=base.global_style,
            style_pack_stated=True,
            style_pack=pack,
        )
    )

    def before() -> None:
        entries.lock_style_advance_base(
            entry.entry_id,
            base_revision=entry.revision,
            world_id=entry.world_id,
            authored_state_sha256=entry.authored_state_sha256,
            authored_edit_seq=entry.authored_edit_seq,
            style_version_id=entry.style_version_id,
        )

    def after(version: StyleVersion) -> None:
        entries.advance_style_locked(
            entry.entry_id,
            base_revision=entry.revision,
            world_id=entry.world_id,
            style_version_id=version.version_id,
        )

    styles.apply(
        preview.preview_id,
        base_style_version_id=base.version_id,
        base_topology_digest=base.topology_digest,
        applied_by=actor,
        before_write=before,
        after_write=after,
    )
    return entries.entry(entry.entry_id)
