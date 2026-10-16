"""The operator's run that makes the creature looks people asked for: stage the queued look jobs,
and admit what the fit made.

    python -m exulanica.hosting.creature_look_command stage --workspace UUID \\
        [--workspace UUID ...] --out RUN [--limit N] [--data-dir DIR] [--apply]
    python -m exulanica.hosting.creature_look_command admit --run RUN --fits FITS \\
        --cost-usd TOTAL [--data-dir DIR] [--apply]

A person asks for a made look of a creature their workspace keeps (:mod:`exulanica.world.
creature_look_jobs`), and the job waits, queued. The API spends nothing: the run is the operator's,
under the owner's yes, in five steps, of which this command is the first and the last:

1. ``stage`` takes each listed workspace's queued look jobs, oldest first, at most ``--limit`` in
   all, writes each one's request from the creature's kept documents (:func:`look_request`) to
   ``RUN/requests/``, marks the jobs staged under the run's id with the request's digest, and lists
   them in ``RUN/staged.json``;
2. ``python -m exulanica_appearance creatures make-job`` writes the route P job record from those
   requests;
3. the operator stages, submits, watches, deletes, fetches and clears the GPU job with the
   generated assets tooling, under its bound;
4. ``python -m exulanica_appearance creatures fit-run`` fits every model the job made, on the
   operator's own machine, and writes ``FITS/fits.json`` with each request's outcome;
5. ``admit`` ends each staged job: a passed fit's look is admitted into its workspace's store
   (:meth:`~exulanica.world.thing_store.ThingStore.admit_look`, its document written by
   :func:`made_look_document`), then the job is ended made and the creature wears the look by its
   kind (:func:`~exulanica.world.creature_look_jobs.wear_by_kind`), together; a refused fit ends
   the job refused by its code; a request the job did not make, or the fit could not read, ends it
   failed. Each job is given an equal share of ``--cost-usd``, the run's measured cost. A job no
   longer staged under the run (its creature or its workspace erased since) keeps nothing. A look
   already kept from the same fit (its end failed after the admission) is worn rather than kept
   twice, so the step may be run again.

The product and the job meet only at documents (the request, ``fits.json``, the receipts and the
containers), so this command never imports ``ml/appearance``. Without ``--apply`` each step makes
every check that writes nothing and prints what it would do. The database is
``EXULANICA_DATABASE_URL``; the looks go to each workspace's ``looks`` namespace of the store this
deployment's API serves from.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, TypeVar

import psycopg
from psycopg.rows import dict_row

from exulanica.evidence.blob import BlobId
from exulanica.things.bodies import built_again, read_body_recipe
from exulanica.things.creature_looks import creature_look_request
from exulanica.things.looks import Look
from exulanica.world import creature_look_jobs as look_jobs
from exulanica.world.thing_store import ThingStore, ThingStoreRefused, read_admission

__all__ = [
    "FITS_PROFILE",
    "MADE_LOOK_LICENCE",
    "RUN_PROFILE",
    "look_request",
    "made_admits",
    "made_look_document",
    "main",
]

#: What ``stage`` writes, and what ``fit-run`` writes, as each reads the other's.
RUN_PROFILE: Final = "exulanica.creature-look-run/v1"
FITS_PROFILE: Final = "exulanica.creature-fit-run/v1"
#: The ledger's eight decimal places.
_USD: Final = Decimal("0.00000001")
#: Tries of a job's end. Its transaction takes the workspace's lock before the job's row, as a
#: creature's erasure does, but a workspace tombstone deletes the rows before it takes that lock, so
#: the database may still end one of the two to break a cycle; the end is then tried again, and a
#: later try starts from what committed meanwhile.
_DEADLOCK_ATTEMPTS: Final = 3
_FIT_OUTCOMES: Final = ("passed", "refused", "failed")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _connect(parser: argparse.ArgumentParser) -> psycopg.Connection:
    from exulanica.env import env_get

    url = env_get("DATABASE_URL")
    if not url:
        parser.error("EXULANICA_DATABASE_URL is required")
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


def _looks(data_dir: Path | None, workspace_id: uuid.UUID) -> Any:
    from exulanica.store.configured import content_stores

    return content_stores(data_dir=data_dir).looks.for_workspace(workspace_id)


#: The licence a made look is kept under: the creature's own words drafted it and the picture is a
#: concept drawn from them, invented content, so CC0, as route A's generated assets state theirs
#: (docs/generated-appearance.md); the models' licences place no terms on what they make.
MADE_LOOK_LICENCE: Final[Mapping[str, Any]] = {
    "spdx": "CC0-1.0",
    "verdict": "SHIP",
    "attribution": None,
    "share_alike": False,
    "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
    "licence_text_sha256": None,
}


def look_request(
    connection: psycopg.Connection, workspace_id: uuid.UUID, kind_sha256: str, looks: Any
) -> bytes:
    """The creature look request (:func:`~exulanica.things.creature_looks.creature_look_request`)
    of the creature of ``kind_sha256``, written from what the workspace keeps: its drafted plan,
    the recipe it was built from, its body rebuilt from that recipe by the body grammar version
    that built it and held to the plan as kept (:func:`~exulanica.things.bodies.built_again`),
    and its sketch's container read from the workspace's ``looks`` namespace. A creature the
    workspace no longer keeps whole is :class:`~exulanica.world.creature_look_jobs.LookNotAsked`."""
    store = ThingStore(connection, workspace_id, looks)
    kind = store.kind_by_digest(kind_sha256)
    if (
        kind is None
        or not look_jobs.keeps_creature(connection, workspace_id, kind_sha256)
        or not kind.looks
    ):
        raise look_jobs.LookNotAsked("this workspace keeps no creature of that kind")
    plan_sha256 = str(kind.document["body"]["plan_sha256"])
    plan_document = store.plan_document_by_digest(plan_sha256)
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select r.document from body_plan_version p join body_recipe_version r "
            "on r.workspace_id=p.workspace_id and r.sha256=p.recipe_sha256 "
            "where p.workspace_id=%s and p.sha256=%s",
            (workspace_id, plan_sha256),
        ).fetchone()
    if plan_document is None or row is None:
        raise look_jobs.LookNotAsked("this workspace no longer keeps the creature's plan whole")
    recipe = read_body_recipe(row["document"])
    built = built_again(recipe, plan_document)
    if built is None:
        raise look_jobs.LookNotAsked(
            "the creature's body, built again from its recipe, is not its plan"
        )
    sketch = kind.looks[0]
    kept = store.look(str(sketch["look"]), int(sketch["version"]), include_withdrawn=True)
    if kept is None:
        raise look_jobs.LookNotAsked("the creature's sketch is no longer kept")
    container = looks.get(BlobId.from_hex(kept.container_sha256))
    return creature_look_request(
        built=built, recipe=recipe, plan_sha256=plan_sha256, sketch=container
    )


def made_look_document(
    *,
    plan_document: Mapping[str, Any],
    version: int,
    container: bytes,
    height_mm: int,
    made_by: Mapping[str, Any],
    ingredients: list[str],
    receipt_sha256: str,
) -> dict[str, Any]:
    """The look document of a made look (``exulanica.look/v1``): skinned on the creature's drafted
    plan, every bone its own joint, posed by the solved gait (no clips of its own), its sockets
    where the plan has some, its height as the fit measured it, its origin generated by the 3D
    model ``made_by`` names (provider and model id, from the run), its picture's cut-out among its
    ingredients and the fit's receipt in its lineage, private. Its key is the plan's with
    ``-made``; ``version`` is the next the workspace has not used."""
    bones = [str(bone["name"]) for bone in plan_document["bones"]]
    sockets = {
        str(socket["key"]): f"bone:{socket['bone']}"
        for socket in plan_document.get("sockets", [])
        if socket.get("bone") is not None
    }
    return {
        "profile": "exulanica.look/v1",
        "look": f"{str(plan_document['key']).replace('_', '-')}-made",
        "version": version,
        "label": "made from a picture",
        "body_plan": f"{plan_document['key']}/v{plan_document['version']}",
        "look_kind": "skinned",
        "container": {
            "sha256": hashlib.sha256(container).hexdigest(),
            "bytes": len(container),
            "media_type": "model/gltf-binary",
        },
        "rig": {
            "bones": {bone: f"bone:{bone}" for bone in bones},
            "clips": {},
            **({"sockets": sockets} if sockets else {}),
        },
        "height_mm": height_mm,
        "sampling": "linear",
        "light": None,
        "role": None,
        "origin": {
            "profile": "exulanica.origin/v1",
            "class": "generated",
            "by": {
                "kind": "model",
                "provider": made_by["provider"],
                "model_id": made_by["model_id"],
                "prompt_version": None,
                "prompt_sha256": None,
                "words_sha256": None,
                "execution_sha256": None,
            },
            "sources": [],
            "licence": dict(MADE_LOOK_LICENCE),
            "authors": [],
            "lineage": {
                "ingredients": list(ingredients),
                "receipts": [receipt_sha256],
                "translation_manifest_sha256": None,
            },
            "distribution": "private",
        },
    }


def made_admits(plan_name: str) -> Callable[[Look], None]:
    """The intake's own check for a made look: generated, private, and drawn on the creature's own
    drafted plan; or :class:`ThingStoreRefused` (``look_not_admitted``)."""

    def admit(look: Look) -> None:
        origin = look.document["origin"]
        if (
            look.body_plan != plan_name
            or origin["class"] != "generated"
            or origin["distribution"] != "private"
        ):
            raise ThingStoreRefused(
                "look_not_admitted",
                "a made look is generated, private and drawn on its creature's own plan",
            )

    return admit


def _stage(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from exulanica.db.session import set_workspace

    run_id = uuid.uuid4()
    planned: list[tuple[uuid.UUID, look_jobs.CreatureLook, bytes]] = []
    with _connect(parser) as connection:
        for workspace_id in args.workspace:
            set_workspace(connection, workspace_id)
            looks = _looks(args.data_dir, workspace_id)
            for look in look_jobs.queued_looks(
                connection, workspace_id, limit=max(args.limit - len(planned), 0)
            ):
                try:
                    request = look_request(connection, workspace_id, look.kind_sha256, looks)
                except look_jobs.LookNotAsked as exc:
                    print(f"passed by {workspace_id} {look.look_id}: {exc}")
                    continue
                planned.append((workspace_id, look, request))
        if not args.apply:
            for workspace_id, look, request in planned:
                print(f"would stage {workspace_id} {look.look_id} request {_sha256(request)}")
            print(f"would stage {len(planned)} look jobs under a new run")
            return 0
        staged = []
        for workspace_id, look, request in planned:
            digest = _sha256(request)
            target = args.out / "requests" / f"{digest}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(request)
            set_workspace(connection, workspace_id)
            if look_jobs.stage_look(
                connection, workspace_id, look.look_id, run_id=run_id, request_sha256=digest
            ):
                staged.append(
                    {
                        "workspace_id": str(workspace_id),
                        "look_id": str(look.look_id),
                        "kind_sha256": look.kind_sha256,
                        "request_sha256": digest,
                    }
                )
    record = {
        "profile": RUN_PROFILE,
        "run_id": str(run_id),
        "staged_at": datetime.now(UTC).isoformat(),
        "items": staged,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "staged.json").write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    print(f"staged {len(staged)} look jobs under run {run_id}")
    return 0


def _read_fits(fits: Path) -> dict[str, Any]:
    document = json.loads((fits / "fits.json").read_bytes())
    if not isinstance(document, dict) or document.get("profile") != FITS_PROFILE:
        raise ValueError(f"{fits / 'fits.json'} is not {FITS_PROFILE}")
    return document


def _share(total: str, count: int) -> Decimal:
    try:
        amount = Decimal(total)
    except InvalidOperation as exc:
        raise ValueError(f"--cost-usd is an amount in US dollars, not {total!r}") from exc
    if amount < 0 or not amount.is_finite():
        raise ValueError("--cost-usd is a measured cost, at least nothing")
    return (amount / max(count, 1)).quantize(_USD)


_Ended = TypeVar("_Ended")


def _retrying(end: Callable[[], _Ended]) -> _Ended:
    """``end`` (one transaction) tried again when the database ended it to break a lock cycle."""
    for attempt in range(1, _DEADLOCK_ATTEMPTS + 1):
        try:
            return end()
        except psycopg.errors.DeadlockDetected:
            if attempt == _DEADLOCK_ATTEMPTS:
                raise
    raise AssertionError("unreachable")


def _kept_from_fit(store: ThingStore, key: str, receipt_sha256: str) -> Any:
    """The look of ``key`` already kept from this fit (its document names the fit's receipt), not
    withdrawn, or None: a run admitted it and then its end failed (a crash, or every try ended to
    break a lock cycle), so the job is still staged and the run, run again, wears that look rather
    than keeping a second one of the same fit."""
    row = store.connection.execute(
        "select version from look_version where workspace_id=%s and key=%s "
        "and document->'origin'->'lineage'->'receipts' ? %s order by version desc limit 1",
        (store.workspace_id, key, receipt_sha256),
    ).fetchone()
    return None if row is None else store.look(key, int(row["version"]))


def _next_version(connection: psycopg.Connection, workspace_id: uuid.UUID, key: str) -> int:
    row = connection.execute(
        "select coalesce(max(version), 0) as v from look_version where workspace_id=%s and key=%s",
        (workspace_id, key),
    ).fetchone()
    assert row is not None
    return int(row["v"]) + 1


def _admit_one(
    connection: psycopg.Connection,
    item: Mapping[str, Any],
    fitted: Mapping[str, Any] | None,
    *,
    run_id: uuid.UUID,
    share: Decimal,
    fits: Path,
    made_by: Mapping[str, Any],
    data_dir: Path | None,
    apply: bool,
) -> str:
    """One staged job's end, as a line saying what was done or would be."""
    from exulanica.db.session import set_workspace

    workspace_id = uuid.UUID(item["workspace_id"])
    look_id = uuid.UUID(item["look_id"])
    set_workspace(connection, workspace_id)
    job = look_jobs.read_look(connection, workspace_id, look_id)
    if job is None or job.status != "staged" or job.run_id != run_id:
        return f"kept nothing for {look_id}: no longer staged under this run"
    outcome = "failed" if fitted is None else fitted["outcome"]
    if outcome not in _FIT_OUTCOMES:
        raise ValueError(f"a fit's outcome is one of {', '.join(_FIT_OUTCOMES)}")
    if outcome != "passed":
        ended = {
            "status": outcome,
            "refusal_code": fitted["refusal"] if outcome == "refused" and fitted else None,
            "failure": None if outcome == "refused" else (fitted or {}).get("failure", "not_made"),
        }
        if not apply:
            return f"would end {look_id} {outcome}"

        def end_unmade() -> look_jobs.CreatureLook | None:
            with connection.transaction():
                return look_jobs.end_look(
                    connection, workspace_id, look_id, run_id=run_id, cost_usd=share, **ended
                )

        if _retrying(end_unmade) is None:
            return f"kept nothing for {look_id}: no longer staged under this run"
        return f"ended {look_id} {outcome}"
    assert fitted is not None
    store = ThingStore(connection, workspace_id, _looks(data_dir, workspace_id))
    kind = store.kind_by_digest(job.kind_sha256)
    if kind is None:
        return f"kept nothing for {look_id}: its creature is no longer kept"
    plan_document = store.plan_document_by_digest(str(kind.document["body"]["plan_sha256"]))
    if plan_document is None:
        return f"kept nothing for {look_id}: its creature's plan is no longer kept"
    container = (fits / "looks" / f"{fitted['container_sha256']}.glb").read_bytes()
    receipt = (fits / "receipts" / f"{fitted['receipt_sha256']}.json").read_bytes()
    if (
        _sha256(container) != fitted["container_sha256"]
        or _sha256(receipt) != fitted["receipt_sha256"]
    ):
        raise ValueError(f"the fit of {item['request_sha256']} is not the bytes it names")
    key = f"{str(plan_document['key']).replace('_', '-')}-made"
    kept = _kept_from_fit(store, key, fitted["receipt_sha256"])
    if kept is not None:
        if not apply:
            return f"would wear {kept.look.look} v{kept.look.version}, kept already, for {look_id}"
    else:
        document = made_look_document(
            plan_document=plan_document,
            version=_next_version(connection, workspace_id, key),
            container=container,
            height_mm=int(fitted["height_mm"]),
            made_by=made_by,
            ingredients=[str(fitted["cutout_sha256"])],
            receipt_sha256=fitted["receipt_sha256"],
        )
        plan_name = f"{plan_document['key']}/v{plan_document['version']}"
        admit = made_admits(plan_name)
        if not apply:
            look = read_admission(document, container, plan_of=store.plan).look
            admit(look)
            return f"would admit {look.look} v{look.version} {look.sha256} for {look_id}"
        kept = store.admit_look(document, container, created_by=job.requested_by, admit=admit)

    def end_made() -> look_jobs.CreatureLook | None:
        # The job's end and its kind's look together, the workspace's lock first (end_look).
        with connection.transaction():
            made = look_jobs.end_look(
                connection,
                workspace_id,
                look_id,
                run_id=run_id,
                status="made",
                look_sha256=kept.look.sha256,
                cost_usd=share,
            )
            if made is not None:
                look_jobs.wear_by_kind(
                    connection,
                    workspace_id,
                    kind_sha256=job.kind_sha256,
                    look_sha256=kept.look.sha256,
                    chosen_by=job.requested_by,
                    look_id=look_id,
                )
            return made

    if _retrying(end_made) is None:
        return f"admitted {kept.look.sha256} but {look_id} was no longer staged: not worn"
    return f"made {look_id}: {kept.look.look} v{kept.look.version} {kept.look.sha256}"


def _admit(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    run = json.loads((args.run / "staged.json").read_bytes())
    if run.get("profile") != RUN_PROFILE:
        parser.error(f"{args.run / 'staged.json'} is not {RUN_PROFILE}")
    try:
        fits = _read_fits(args.fits)
        share = _share(args.cost_usd, len(run["items"]))
    except ValueError as exc:
        parser.error(str(exc))
    outcomes: Mapping[str, Mapping[str, Any]] = fits["requests"]
    lines = []
    with _connect(parser) as connection:
        for item in run["items"]:
            try:
                lines.append(
                    _admit_one(
                        connection,
                        item,
                        outcomes.get(item["request_sha256"]),
                        run_id=uuid.UUID(run["run_id"]),
                        share=share,
                        fits=args.fits,
                        made_by=fits["made_by"],
                        data_dir=args.data_dir,
                        apply=args.apply,
                    )
                )
            except ThingStoreRefused as exc:
                lines.append(f"refused {item['look_id']}: {exc}")
    for line in lines:
        print(line)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m exulanica.hosting.creature_look_command", description=__doc__
    )
    commands = parser.add_subparsers(dest="command", required=True)
    stage = commands.add_parser("stage", help="stage the queued look jobs of these workspaces")
    stage.add_argument("--workspace", type=uuid.UUID, action="append", required=True)
    stage.add_argument("--out", type=Path, required=True)
    stage.add_argument("--limit", type=int, default=16)
    stage.add_argument("--data-dir", type=Path)
    stage.add_argument("--apply", action="store_true", help="write; otherwise only check")
    admit = commands.add_parser("admit", help="admit what the fit made and end the run's jobs")
    admit.add_argument("--run", type=Path, required=True)
    admit.add_argument("--fits", type=Path, required=True)
    admit.add_argument("--cost-usd", required=True)
    admit.add_argument("--data-dir", type=Path)
    admit.add_argument("--apply", action="store_true", help="write; otherwise only check")
    args = parser.parse_args(argv)
    if args.command == "stage":
        if args.limit < 1:
            parser.error("--limit is at least one")
        return _stage(args, parser)
    return _admit(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
