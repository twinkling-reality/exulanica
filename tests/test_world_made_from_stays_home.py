"""The sentence a world was made from stays with the world (migration 0222): no export route
carries it. Two routes write a workspace's content to another place, and each is held here by
what decides what it carries:

- World packages, their datasets and training exports, and the projects a person keeps on their
  computer or on GitHub (``exulanica/world_package``) name every table they read, so a source
  check holds them: one that wanted the sentence would have to name its table or the draft read
  that serves it, and this file would then fail until the person's choice to keep it there exists.
- A reviewer seed (``exulanica/orchestration/judge_seed.py``) carries every table that names the
  workspace unless its classification says otherwise, so its classification is read here.
"""

from __future__ import annotations

from pathlib import Path

from exulanica.orchestration import judge_seed

ROOT = Path(__file__).resolve().parents[1]
#: The packages that write a world anywhere outside this install: world packages and their exports,
#: and the projects a person keeps on their computer or on GitHub.
OUTWARD = ROOT / "exulanica" / "world_package"
#: What reaching the sentence would take: its table, or the draft read that answers it.
NAMES = ("world_made_from", "/worlds/drafts")


def test_no_export_or_project_reads_the_sentence_a_world_was_made_from():
    sources = sorted(OUTWARD.rglob("*.py"))
    assert len(sources) > 20  # Positive control: the packages are where this file looks.
    reaching = [
        f"{path.relative_to(ROOT)}: {name}"
        for path in sources
        for name in NAMES
        if name in path.read_text(encoding="utf-8")
    ]
    assert reaching == []


class _Catalog:
    """The one catalog read ``classify_tables`` makes, answered from a list of tables."""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def execute(self, _statement: str) -> _Catalog:
        return self

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


def _table(name: str, *, has_workspace: bool) -> dict[str, object]:
    return {"name": name, "is_partition": False, "has_workspace": has_workspace}


def test_a_reviewer_seed_classifies_the_sentence_as_never_carried():
    named = [
        *judge_seed.GLOBAL_TABLES,
        *judge_seed.INSTANCE_TABLES,
        *judge_seed.REACHED_TABLES,
        *judge_seed.NEVER_EXPORTED_TABLES,
    ]
    rows = [_table(name, has_workspace=False) for name in named if name != "world_made_from"]
    rows += [_table("world_made_from", has_workspace=True), _table("capture", has_workspace=True)]
    buckets = judge_seed.classify_tables(_Catalog(rows))  # type: ignore[arg-type]
    # Positive control: a table that names the workspace and is classified nowhere is carried.
    assert buckets["workspace"] == ("capture",)
    assert buckets["never_exported"] == ("world_made_from",)
    assert "world_made_from" not in buckets["workspace"] + buckets["reached"]
