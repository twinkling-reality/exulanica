"""The page reads the specification this server serves: both are held to one committed document.

``tests/snapshots/world-specification.served.json`` is what ``GET /worlds/specification`` answers
(:func:`exulanica.world.world_recipes.specification_document`), written by running this file::

    uv run python tests/test_world_specification_served_snapshot.py

The test below fails when the served document moves, until the snapshot is written again and
committed with the change. The page's own reader is run over the same file
(``web/packages/app/test/world-specification.test.ts``), so a change to what the server serves
that the page cannot read fails the page's tests in the same change. That is the fault this exists
for: a ground began to state no maximum of people (``most`` null), the page's reader required a
whole number, and the creation screen opened with no recipe and no description field while every
check passed, because the page's test read a document written by hand.

No database: the document is made from the catalogs and the policies' own files.
"""

from __future__ import annotations

import json
from pathlib import Path

from exulanica.world.world_recipes import specification_document

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "world-specification.served.json"


def served() -> str:
    """The served document as the snapshot holds it: JSON, keys in the order served."""
    return json.dumps(specification_document(), indent=1, ensure_ascii=False) + "\n"


def test_the_committed_snapshot_is_the_specification_this_server_serves():
    assert SNAPSHOT.read_text(encoding="utf-8") == served(), (
        "GET /worlds/specification moved: write the snapshot again "
        "(uv run python tests/test_world_specification_served_snapshot.py), run the page's "
        "tests, and commit both with the change"
    )


def test_the_snapshot_states_a_ground_with_no_maximum_as_null_and_never_as_nothing():
    """What the page's reader depends on: every ground states ``most``, a whole number or null."""
    people = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["bounds"]["people"]
    assert people
    for ground in people:
        assert "most" in ground, ground
        assert ground["most"] is None or (type(ground["most"]) is int and ground["most"] > 0)


if __name__ == "__main__":
    SNAPSHOT.write_text(served(), encoding="utf-8")
    print(f"wrote {SNAPSHOT}")
