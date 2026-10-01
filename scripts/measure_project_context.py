"""Measure what project context reads cost and hold on local fixtures: size, statements, leaks.

    uv run python scripts/measure_project_context.py --out <record.json>

A private PostgreSQL server is made for the run, provisioned as the setup guide provisions one, and
removed afterwards (``scripts/test_postgres.py``). In it, one person keeps three projects on an
authored starter world, of 10, 100 and 500 items: goals, preferences, questions and tasks in their
own words, decisions naming an accepted edit, suggestions drawn from a Companion answer (some
accepted, some waiting), each item corrected once, and a tenth of them deleted. Each read the
contract names is then taken as the runtime role and measured:

* the assembly at the default budget and at the largest one: entries, bytes, what was left out and
  why, and the digest;
* how many SQL statements each read ran;
* the wall-clock time of each read on this machine, an observation of one run on a machine whose
  other load the run does not control, not a capacity figure;
* how many times a deleted item's words appear in any read's answer or in any row of the project
  tables, which must be zero.

The record states the source tree it measured: the commit, and for uncommitted changes a digest
of every changed or added file in the form of a postimage manifest (``<sha256>  <path>`` lines,
sorted by path), so it can be compared with the manifest of the delta that was delivered. Nothing here asks a model or costs anything.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

#: The project sizes measured, in items, and the share of each deleted.
SIZES = (10, 100, 500)
DELETED_EVERY = 10

_PROJECT_TABLES = (
    "world_project",
    "world_project_binding",
    "world_project_item",
    "world_project_item_revision",
    "world_project_item_source",
    "world_project_share",
)


class _Counting:
    """The runtime role's connection, counting the statements a read runs through it."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self.statements = 0

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.statements += 1
        return self._connection.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


@contextlib.contextmanager
def _database() -> Iterator[dict[str, str]]:
    """A private PostgreSQL made for this run, provisioned as the setup guide says, then removed."""
    from test_postgres import remove_test_server, start_test_server

    from exulanica.db.cli import provision
    from exulanica.db.roles import RUNTIME_ROLE

    server, owner = start_test_server("projectcontext")
    try:
        previous = os.environ.get("EXULANICA_DATABASE_URL")
        os.environ["EXULANICA_DATABASE_URL"] = owner
        try:
            provision(io.StringIO())
        finally:
            if previous is None:
                os.environ.pop("EXULANICA_DATABASE_URL", None)
            else:
                os.environ["EXULANICA_DATABASE_URL"] = previous
        database = owner.rsplit("/", 1)[1]
        yield {"owner": owner, "runtime": server.url(database, RUNTIME_ROLE)}
    finally:
        remove_test_server(server)


def _phrase(size: int, index: int) -> str:
    return f"words kept in project {size} item {index} {uuid.uuid4().hex[:6]}"


def _build(
    repository_cls: Any,
    connection: Any,
    workspace: uuid.UUID,
    actor: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    edit: dict[str, Any],
    answer: uuid.UUID,
    size: int,
) -> dict[str, Any]:
    from exulanica.world.project_context import ItemBasis, ItemKind

    projects = repository_cls(connection, workspace, actor, world_id)
    project, _ = projects.create_project(title=f"{size} items", version_id=version_id)
    revision = project.revision
    kinds = (ItemKind.GOAL, ItemKind.PREFERENCE, ItemKind.QUESTION, ItemKind.TASK)
    made: list[tuple[uuid.UUID, str]] = []
    for index in range(size):
        text = _phrase(size, index)
        if index % 7 == 6:
            item, _ = projects.add_item(
                project.project_id,
                base_revision=revision,
                kind=ItemKind.DECISION,
                basis=ItemBasis.RECORDED_OUTCOME,
                text=text,
                references=[edit],
            )
        elif index % 5 == 4:
            item, _ = projects.add_item(
                project.project_id,
                base_revision=revision,
                kind=ItemKind.PREFERENCE,
                basis=ItemBasis.INFERRED_SUGGESTION,
                text=text,
                references=[{"kind": "companion_answer", "answer_id": str(answer)}],
            )
        else:
            item, _ = projects.add_item(
                project.project_id,
                base_revision=revision,
                kind=kinds[index % len(kinds)],
                basis=ItemBasis.USER_STATEMENT,
                text=text,
            )
        revision = item.project_revision
        if item.status.value == "proposed" and index % 2 == 0:
            revision, _ = projects.review_item(
                project.project_id, item.item_id, base_revision=revision, accept=True
            )
        if item.kind.value in ("goal", "preference", "question", "task"):
            corrected = projects.correct_item(
                project.project_id, item.item_id, base_revision=revision, text=text + " (again)"
            )
            revision = corrected.project_revision
        made.append((item.item_id, text))
    deleted = []
    for position, (item_id, text) in enumerate(made):
        if position % DELETED_EVERY == 0:
            revision = projects.delete_item(project.project_id, item_id)
            deleted.append(text)
    return {"project": project.project_id, "deleted": deleted}


def _measure(
    repository_cls: Any,
    runtime: Any,
    workspace: uuid.UUID,
    actor: uuid.UUID,
    world_id: str,
    built: dict[str, Any],
) -> dict[str, Any]:
    from exulanica.world.project_context_assembly import MAX_BYTES, MAX_ENTRIES, Budget

    reads: dict[str, Any] = {}
    answers: list[str] = []
    for name, call in (
        ("project", lambda r: r.project(built["project"])),
        ("items", lambda r: r.items(built["project"])),
        ("audit", lambda r: r.audit(built["project"])),
        ("context_default", lambda r: r.context(built["project"], budget=Budget())),
        (
            "context_largest",
            lambda r: r.context(
                built["project"], budget=Budget(max_entries=MAX_ENTRIES, max_bytes=MAX_BYTES)
            ),
        ),
    ):
        counting = _Counting(runtime)
        repository = repository_cls(counting, workspace, actor, world_id)
        started = time.perf_counter_ns()
        value = call(repository)
        elapsed_us = (time.perf_counter_ns() - started) // 1000
        answers.append(repr(value))
        reads[name] = {"statements": counting.statements, "wall_microseconds": elapsed_us}
        if name.startswith("context"):
            assembly = value.assembly
            reads[name].update(
                {
                    "entries": len(assembly.entries),
                    "used_bytes": assembly.used_bytes,
                    "max_entries": assembly.budget.max_entries,
                    "max_bytes": assembly.budget.max_bytes,
                    "omitted": dict(assembly.omitted),
                    "assembly_sha256": assembly.assembly_sha256,
                }
            )
        if name == "items":
            reads[name]["items"] = len(value)
    leaks = sum(text in answer for text in built["deleted"] for answer in answers)
    return {"reads": reads, "deleted_items": len(built["deleted"]), "leaks_in_reads": leaks}


def _row_leaks(owner: Any, deleted: list[str]) -> int:
    count = 0
    for table in _PROJECT_TABLES:
        naming = (
            "t.world_id, "
            if table in ("world_project", "world_project_binding", "world_project_item")
            else ""
        )
        for text in deleted:
            count += len(
                owner.execute(
                    f"select {naming}to_jsonb(t)::text as row from {table} t "
                    "where to_jsonb(t)::text like %s",
                    (f"%{text}%",),
                ).fetchall()
            )
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="where the JSON record goes")
    args = parser.parse_args(argv)

    import psycopg
    from psycopg.rows import dict_row

    from exulanica.db.session import set_workspace
    from exulanica.world.companion_memory import (
        AnswerComposed,
        CompanionMemoryRepository,
        RecordedAnswer,
    )
    from exulanica.world.project_context import ProjectContextRepository
    from exulanica.world.starter import create_starter_authorities
    from exulanica.world.worlds import AUTHORED_STARTER, new_world_id

    tree = subprocess.run(
        ["git", "--no-optional-locks", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # NUL-separated and never stripped: each entry is two status characters, a space and the
    # path, and the first entry's status may begin with a space. Without rename detection, every
    # entry names one path.
    dirty = subprocess.run(
        ["git", "--no-optional-locks", "status", "--porcelain", "-z", "-uall", "--no-renames"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    manifest = "".join(
        f"{hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}  {path}\n"
        if (ROOT / path).exists()
        else f"ABSENT  {path}\n"
        for path in sorted(entry[3:] for entry in dirty.split("\0") if entry)
    )
    record: dict[str, Any] = {
        "profile": "exulanica.project-context-measurement/v1",
        "head": tree,
        "tree_has_uncommitted_changes": bool(dirty),
        "changed_files_manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "sizes": list(SIZES),
        "deleted_every": DELETED_EVERY,
        "note": "wall times are one local run each on a machine whose other load the run does "
        "not control, not a capacity figure",
        "projects": [],
    }
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with contextlib.ExitStack() as stack, _database() as urls:
        with psycopg.connect(urls["runtime"], autocommit=True, row_factory=dict_row) as runtime:
            runtime.execute("set time zone 'UTC'")
            set_workspace(runtime, workspace)
            world_id = new_world_id(AUTHORED_STARTER)
            with runtime.transaction():
                _snapshot, _style, version_id = create_starter_authorities(
                    runtime,
                    workspace_id=workspace,
                    actor=actor,
                    title="Measured",
                    world_id=world_id,
                )
            from exulanica.store.local import LocalContentAddressedStore
            from exulanica.world.assets import reviewed_assets, seed_reviewed_assets
            from exulanica.world.object_repository import WorldObjectRepository
            from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform

            store = LocalContentAddressedStore(
                Path(stack.enter_context(tempfile.TemporaryDirectory()))
            )
            seed_reviewed_assets(store)
            objects = WorldObjectRepository(runtime, workspace, world_id=world_id, store=store)
            current = objects.version(version_id)
            asset = next(a for a in reviewed_assets() if a.asset_key == "cc0.bench")
            placed = objects.add_object(
                version_id,
                AuthoredObject(
                    object_id="bench",
                    asset_sha256=asset.content_sha256,
                    region_id="region:starter",
                    transform=Transform(-6000, 0, 4000, 0, 1000),
                    origin=ObjectOrigin("authored", "fictional"),
                ),
                base_state_sha256=current.state_sha256,
                actor=actor,
            )
            edit = next(e for e in placed.edits if e.object_id == "bench")
            reference = {
                "kind": "world_edit",
                "operation": "POST /world/versions/{version_id}/objects",
                "world_id": world_id,
                "version_id": str(version_id),
                "edit_id": str(edit.edit_id),
                "edit_seq": edit.edit_seq,
                "result_state_sha256": edit.result_state_sha256,
            }
            answer = CompanionMemoryRepository(runtime, workspace, actor).record_answer(
                RecordedAnswer(
                    question="Where do people rest?",
                    answer_text="Nobody rests here yet.",
                    abstained=None,
                    deterministic=True,
                    repaired=False,
                    served_model=None,
                    planned_by=None,
                    prompt_version="selection-3",
                    latency_ms=1,
                    citations=(),
                    composed=AnswerComposed.NONE,
                    used_fallback=False,
                    unanswered_attempts=0,
                    unanswered_cost_unknown=False,
                )
            )
            for size in SIZES:
                built = _build(
                    ProjectContextRepository,
                    runtime,
                    workspace,
                    actor,
                    world_id,
                    version_id,
                    reference,
                    answer.answer_id,
                    size,
                )
                measured = _measure(
                    ProjectContextRepository, runtime, workspace, actor, world_id, built
                )
                measured["items"] = size
                record["projects"].append((built, measured))
        with psycopg.connect(urls["owner"], autocommit=True, row_factory=dict_row) as owner:
            owner.execute("set time zone 'UTC'")
            for built, measured in record["projects"]:
                measured["leaks_in_rows"] = _row_leaks(owner, built["deleted"])
    record["projects"] = [measured for _built, measured in record["projects"]]
    record["leaks"] = sum(p["leaks_in_reads"] + p["leaks_in_rows"] for p in record["projects"])
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"leaks": record["leaks"], "out": str(args.out)}))
    return 0 if record["leaks"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
