"""Whether a placed thing's kind is gone, as SQL, stated once.

A version's things are read with this condition (the object repository's ``_things``, which reads
:attr:`exulanica.world.placed_things.PlacedThing.kind_gone`), whether a version holds a thing a
society takes in is asked with its negation (``version_holds_things``), and a society asks it of
the things its latest input lists and the beings its state holds before each minute
(:class:`exulanica.world.society_repository.SocietyRepository`). It lives in a module of its own so
all three read one text and none imports another: the society's repository may not reach the
object repository's imports.
"""

from __future__ import annotations

from typing import Final

__all__ = ["THING_KIND_GONE_SQL"]

#: A condition on a ``world_alternate_thing`` row named ``t``: a kind its workspace kept that the
#: workspace no longer holds, or erased after the thing was placed (so the same document kept
#: again never brings the thing back).
THING_KIND_GONE_SQL: Final = (
    "(t.kind_source='workspace' and ("
    "not exists (select 1 from thing_kind_version k where k.workspace_id=t.workspace_id "
    "and k.sha256=encode(t.kind_sha256,'hex')) "
    "or exists (select 1 from thing_erasure e join world_alternate_version_edit p "
    "on p.workspace_id=t.workspace_id and p.edit_id=t.created_edit_id "
    "where e.workspace_id=t.workspace_id and e.sha256=encode(t.kind_sha256,'hex') "
    "and e.erased_at>=p.recorded_at)))"
)
