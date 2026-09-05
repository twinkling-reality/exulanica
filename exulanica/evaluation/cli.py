"""``exulanica-eval``. Run what can be measured and say plainly what cannot.

The ``run`` scoring path reads through the database and HTTP application and writes no product
state. There is no direct INSERT, UPDATE or DELETE in this package, and every product number is
computed from rows the real pipeline put there. ``replay-bundle`` is the explicit orchestration
exception: it applies migrations and invokes that real pipeline, only after proving its target is a
new empty evaluation database. It never confirms an entity or performs another user-class act.

Read-only scoring is a rule rather than an accident of what happens to be implemented. Every
metric this harness has had to turn down for want of a write needed a CONFIRMED ENTITY, and an
entity exists only where a person confirmed an occurrence. A harness that confirmed one out of
``MANIFEST.json``
to make its own number computable would be a machine performing a user-class act, which invariant
3 forbids and which no flag or dedicated workspace would change. So such a metric is a blocked row
in ``metrics.py`` carrying the sentence that names what is missing, and it is never bought with a
shortcut into the tables.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
import uuid
from typing import Any, Final

from exulanica.api.routes import routable_paths
from exulanica.db.session import Database
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.errors import ExulanicaError
from exulanica.evaluation.bundle import AccessPurpose, CorpusBundle, CorpusContractError
from exulanica.evaluation.counts import Count, Sample
from exulanica.evaluation.coverage import what_the_corpus_cannot_support
from exulanica.evaluation.execution import execution_snapshot
from exulanica.evaluation.ground_truth import GroundTruth
from exulanica.evaluation.provenance import (
    RUN_PROFILE,
    ArchiveError,
    create_archive,
    migration_snapshot,
    model_snapshot,
    pipeline_snapshot,
    repository_snapshot,
    verify_archive,
)
from exulanica.evaluation.question_scorers import QUESTION_COMPONENTS, score_gold_questions
from exulanica.evaluation.questions import GoldQuestions, derive_questions
from exulanica.evaluation.replay import ReplayError, run_clean_replay
from exulanica.evaluation.report import render_report
from exulanica.evaluation.scorers import (
    score_authorisation,
    score_capture_time_windows,
    score_citation_identity,
    score_provenance_completeness,
)

__all__ = ["SCORED", "main"]

#: The components this harness can produce a result for, and the whole of them.
#:
#: It exists so that "``blocked_on=None`` means the component is runnable", which is what
#: ``metrics.py`` says of that field, is a checkable claim rather than a comment. A row carrying
#: no sentence that nothing here scores renders as the line "NOT MEASURED: None", which is
#: "blocked" and "scored zero" collapsed into one fact. ``_cmd_run`` asserts it filled exactly
#: these, and ``tests/test_evaluation.py`` asserts the metric table agrees with them.
SCORED: Final[tuple[str, ...]] = (
    "M1.cit_id",
    "M5.provenance_completeness",
    "M10.authorisation",
    "M15.capture_time_window_exact_match",
    *QUESTION_COMPONENTS,
)

_PUBLIC = {"/healthz", "/readyz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
_EVALUATION_OWNER_DATABASE_URL_ENV = env_name("EVALUATION_OWNER_DATABASE_URL")


def _cmd_questions(args: argparse.Namespace, stream: Any) -> int:
    """Freeze synthetic gold independently of any database or model output."""
    try:
        questions = derive_questions(GroundTruth.read(args.corpus))
        questions.write(args.out)
    except (OSError, ValueError) as exc:
        print(f"gold question generation: FAILED: {exc}", file=stream)
        return 2
    print(f"SYNTH-1 gold questions written to {args.out}", file=stream)
    print(f"questions sha256 {questions.sha256}", file=stream)
    return 0


def _cmd_inspect_corpus(args: argparse.Namespace, stream: Any) -> int:
    """Validate public metadata without opening any private source media."""
    try:
        bundle = CorpusBundle.read(args.corpus)
    except CorpusContractError as exc:
        print(f"corpus contract: FAILED: {exc}", file=stream)
        return 2
    counts = {
        split: sum(item.split == split for item in bundle.items)
        for split in ("train", "development", "blind")
    }
    result = {
        "profile": bundle.document["profile"],
        "corpus_id": bundle.corpus_id,
        "synthetic": bundle.synthetic,
        "corpus_sha256": bundle.corpus_digest,
        "split_manifest_sha256": bundle.split_digest,
        "consent_index_sha256": bundle.consent_digest,
        "items": counts,
        "sources_opened": 0,
    }
    if args.json:
        json.dump(result, stream, indent=2, sort_keys=True)
        print(file=stream)
    else:
        print(f"corpus contract: {bundle.corpus_id}", file=stream)
        print(f"  corpus sha256   {bundle.corpus_digest}", file=stream)
        print(f"  splits sha256   {bundle.split_digest}", file=stream)
        print(f"  consent sha256  {bundle.consent_digest}", file=stream)
        print(
            "  items            "
            + ", ".join(f"{split}={count}" for split, count in counts.items()),
            file=stream,
        )
        print("  source media     not opened", file=stream)
    return 0


def _cmd_verify_archive(args: argparse.Namespace, stream: Any) -> int:
    """Verify an evaluation archive without opening corpus media or a database."""
    try:
        receipt = verify_archive(args.archive, expected_root_sha256=args.root_sha256)
    except ArchiveError as exc:
        print(f"evaluation archive: FAILED: {exc}", file=stream)
        return 2
    print(f"evaluation archive: VERIFIED: {receipt.run_id}", file=stream)
    print(f"  root sha256  {receipt.root_sha256}", file=stream)
    print(f"  files        {receipt.files}", file=stream)
    return 0


def _cmd_replay_bundle(args: argparse.Namespace, stream: Any) -> int:
    """Replay one authorized bundle split into a brand-new database."""
    try:
        repository_state = repository_snapshot(args.repository)
        bundle = CorpusBundle.read(args.corpus)
        purpose = AccessPurpose(args.purpose)
        blind_key = None
        if args.blind_key_file:
            blind_key = pathlib.Path(args.blind_key_file).read_text(encoding="utf-8").rstrip("\r\n")
        owner_url = env_get("EVALUATION_OWNER_DATABASE_URL")
        if not owner_url:
            raise ReplayError(
                f"{_EVALUATION_OWNER_DATABASE_URL_ENV} is not set to a new empty database"
            )
        owner_database = Database(owner_url)
        runtime_database = Database.from_env()
        vision = _replay_vision(args, bundle, stream)
        receipt = run_clean_replay(
            bundle=bundle,
            owner_database=owner_database,
            runtime_database=runtime_database,
            data_dir=resolve_data_dir(explicit=args.data_dir),
            audit_path=pathlib.Path(args.access_audit),
            archive_parent=pathlib.Path(args.archive_parent),
            repository_state=repository_state,
            purpose=purpose,
            actor=args.actor,
            blind_key=blind_key,
            vision=vision,
        )
    except (
        ArchiveError,
        CorpusContractError,
        ExulanicaError,
        ReplayError,
        RuntimeError,
        OSError,
    ) as exc:
        print(f"clean evaluation replay: FAILED: {exc}", file=stream)
        return 2
    print(f"clean evaluation replay: {'PASS' if receipt.gate_passed else 'BLOCKED'}", file=stream)
    for blocker in receipt.blockers:
        print(f"  blocker: {blocker}", file=stream)
    print(f"  archive      {receipt.archive.path}", file=stream)
    print(f"  root sha256  {receipt.archive.root_sha256}", file=stream)
    return 0


def _replay_vision(args: argparse.Namespace, bundle: CorpusBundle, stream: Any) -> Any:
    if args.offline:
        if not bundle.synthetic:
            raise ReplayError("--offline is refused for a real evaluation bundle")
        print("vision: disabled for an explicitly synthetic replay fixture", file=stream)
        return None
    from exulanica.ingest.vision import NebiusVisionModel
    from exulanica.models.cache import FileResponseCache
    from exulanica.models.client import ModelClient
    from exulanica.models.preflight import run_preflight

    preflight = run_preflight()
    if not preflight.ok:
        failures = "; ".join(str(issue) for issue in preflight.failures)
        raise ReplayError(f"model preflight failed before replay: {failures}")
    client = ModelClient(
        cache=FileResponseCache(resolve_data_dir(explicit=args.data_dir) / "model-cache"),
        max_attempts=3,
    )
    return NebiusVisionModel(client)


def _git_commit() -> str:
    """The commit measured, read from git and never typed.

    A hand-written commit id in a report is one that is wrong the moment anything lands, and a
    report that names the wrong commit is worse than one that names none.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10
    ).stdout.strip()
    return result.stdout.strip() + (" (working tree dirty)" if dirty else "")


def _cmd_run(args: argparse.Namespace, stream: Any) -> int:
    repository_state: dict[str, object] | None = None
    if args.archive_parent or args.record:
        try:
            repository_state = repository_snapshot(args.repository)
        except ArchiveError as exc:
            print(f"evaluation archive: FAILED: {exc}", file=stream)
            return 2
    truth = GroundTruth.read(args.corpus)
    questions = None
    question_blocker = "Generated gold plans require an explicitly synthetic manifest."
    if truth.synthetic:
        try:
            questions = (
                GoldQuestions.read(args.questions, truth) if getattr(args, "questions", None)
                else derive_questions(truth)
            )
        except (OSError, ValueError) as exc:
            print(f"gold questions: FAILED: {exc}", file=stream)
            return 2
    workspace = uuid.UUID(args.workspace)
    database = Database.from_env()

    from exulanica.store.local import LocalContentAddressedStore

    store = LocalContentAddressedStore(resolve_data_dir(explicit=args.data_dir) / "blobs")

    def read_blob(digest: bytes) -> bytes | None:
        from exulanica.evidence.blob import BlobId

        blob = BlobId(digest)
        return store.get(blob) if store.exists(blob) else None

    results: dict[str, Count | Sample | None] = {}
    blocked: dict[str, str] = {}
    execution: dict[str, object]
    with database.session(workspace) as connection:
        results["M1.cit_id"] = score_citation_identity(connection, workspace, truth, read_blob)
        results["M5.provenance_completeness"] = score_provenance_completeness(connection, workspace)
        windows, why = score_capture_time_windows(connection, workspace, truth)
        results["M15.capture_time_window_exact_match"] = windows
        if windows is None:
            blocked["M15.capture_time_window_exact_match"] = why
        observations: tuple[dict[str, Any], ...] = ()
        if questions is not None:
            scored_questions = score_gold_questions(connection, workspace, truth, questions)
            results.update(scored_questions.results)
            blocked.update(scored_questions.blocked)
            observations = scored_questions.observations
        else:
            results.update(dict.fromkeys(QUESTION_COMPONENTS))
            blocked.update(dict.fromkeys(QUESTION_COMPONENTS, question_blocker))
        coverage = what_the_corpus_cannot_support(connection, workspace, truth)
        execution = execution_snapshot(
            connection,
            workspace,
            (frame.sha256 for frame in truth.frames),
        )

    results["M10.authorisation"] = _score_authorisation_over_http(args)
    if results["M10.authorisation"] is None:
        blocked["M10.authorisation"] = (
            "no stranger token was supplied, so no cross-tenant read was attempted. A zero here "
            "would mean the sweep never made a request"
        )

    assert set(results) == set(SCORED), sorted(set(results) ^ set(SCORED))
    report = render_report(
        results,
        corpus_tag=truth.corpus_tag,
        corpus_version=truth.generator,
        manifest_sha256=truth.manifest_sha256,
        synthetic=truth.synthetic,
        disclosure=truth.disclosure,
        frames=len(truth.frames),
        git_commit=_git_commit(),
        blocked=blocked,
        coverage=coverage,
    )
    print(report, file=stream)

    run_id = str(uuid.uuid4())
    generated_at = dt.datetime.now(dt.UTC)
    model, model_bytes = model_snapshot()
    stages = pipeline_snapshot()
    package_migrations = migration_snapshot()
    record = {
        "profile": RUN_PROFILE,
        "run_id": run_id,
        "harness_version": "2",
        "generated_at": generated_at.isoformat(),
        "git": repository_state,
        "corpus": {
            "id": truth.corpus_tag,
            "corpus_version": truth.generator,
            "manifest_sha256": truth.manifest_sha256,
            "synthetic": truth.synthetic,
            "frames": len(truth.frames),
            "contract": "legacy MANIFEST.json; not an OGC-1 CORPUS.json split bundle",
        },
        # Null with a reason rather than absent. Section 2.0 rule 1 names it as a required
        # key, and a missing key and a blocked one read the same in a JSON file.
        "fixture_version": questions.sha256 if questions else None,
        "fixture_blocked_on": None if questions else question_blocker,
        "question_observations": observations,
        "blind_access_proof": None,
        "blind_access_blocked_on": "legacy corpus has no frozen split or access receipt",
        "workspace_id": str(workspace),
        "components": {
            key: None if value is None else {"k": value.k, "n": value.n}
            for key, value in results.items()
            if not isinstance(value, Sample)
        },
        "blocked": blocked,
        "execution_summary": execution["summary"],
        "execution_source_coverage": execution["source_coverage"],
        "model_manifest": model,
        "pipeline": stages,
        "package_migrations": package_migrations,
    }
    if args.record:
        try:
            with pathlib.Path(args.record).open("x", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2, sort_keys=True)
                handle.write("\n")
        except FileExistsError:
            print(f"\nrecord exists and was not overwritten: {args.record}", file=stream)
            return 2
        print(f"\nrecord written to {args.record}", file=stream)
    if args.archive_parent:
        snapshots = {
            "inputs/corpus-manifest.json": truth.path.read_bytes(),
            "inputs/model-manifest.json": model_bytes,
            "snapshots/repository.json": _pretty_json(repository_state),
            "snapshots/model-bindings.json": _pretty_json(model),
            "snapshots/pipeline.json": _pretty_json(stages),
            "snapshots/package-migrations.json": _pretty_json(package_migrations),
            "snapshots/database-execution.json": _pretty_json(execution),
        }
        if questions is not None:
            snapshots["inputs/gold-questions.json"] = _pretty_json(
                questions.model_dump(mode="json")
            )
        try:
            receipt = create_archive(
                args.archive_parent,
                run_id=run_id,
                record=record,
                report=report + "\n",
                snapshots=snapshots,
                completed_at=generated_at,
            )
        except ArchiveError as exc:
            print(f"\nevaluation archive: FAILED: {exc}", file=stream)
            return 2
        print(f"\nevaluation archive written to {receipt.path}", file=stream)
        print(f"archive root sha256 {receipt.root_sha256}", file=stream)
    return 0


def _pretty_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _score_authorisation_over_http(args: argparse.Namespace) -> Count | None:
    """M10, against the real application with a stranger's token.

    Returns None rather than a zero when the application cannot be built. A harness that reported
    "0 unauthorized reads" because it never made a request would be the worst possible version of
    this number.
    """
    try:
        from fastapi.testclient import TestClient

        from exulanica.api.app import create_app
    except ImportError:
        return None

    stranger = args.stranger_token
    if not stranger:
        return None
    client = TestClient(create_app())

    def probe(method: str, path: str) -> tuple[int, object]:
        filled = path.replace("{span_id}", str(uuid.uuid4())).replace(
            "{batch_id}", str(uuid.uuid4())
        )
        response = client.request(
            method, filled, headers={"Authorization": f"Bearer {stranger}"}, json={}
        )
        try:
            body: object = response.json()
        except ValueError:
            body = response.text
        return int(response.status_code), body

    return score_authorisation(probe, routable_paths(client.app), _PUBLIC)


def main(argv: list[str] | None = None, stream: Any = None) -> int:
    stream = stream or sys.stdout
    parser = argparse.ArgumentParser(prog="exulanica-eval", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    questions = sub.add_parser("questions", help="freeze synthetic gold from MANIFEST.json")
    questions.add_argument("--corpus", required=True)
    questions.add_argument("--out", required=True)
    questions.set_defaults(handler=_cmd_questions)
    inspect = sub.add_parser(
        "inspect-corpus",
        help="validate a Phase 2 CORPUS.json bundle without opening private media",
    )
    inspect.add_argument("--corpus", required=True)
    inspect.add_argument("--json", action="store_true")
    inspect.set_defaults(handler=_cmd_inspect_corpus)
    verify = sub.add_parser(
        "verify-archive",
        help="verify a versioned report archive against its separately retained root",
    )
    verify.add_argument("--archive", required=True)
    verify.add_argument("--root-sha256", required=True)
    verify.set_defaults(handler=_cmd_verify_archive)
    replay_bundle = sub.add_parser(
        "replay-bundle",
        help="replay an authorized CORPUS.json split in a new empty database",
    )
    replay_bundle.add_argument("--corpus", required=True)
    replay_bundle.add_argument("--archive-parent", required=True)
    replay_bundle.add_argument("--access-audit", required=True)
    replay_bundle.add_argument("--data-dir", required=True)
    replay_bundle.add_argument("--repository", default=".")
    replay_bundle.add_argument("--actor", required=True, help="opaque evaluation operator id")
    replay_bundle.add_argument(
        "--purpose",
        choices=(
            AccessPurpose.DEVELOPMENT_EVALUATION.value,
            AccessPurpose.BLIND_EVALUATION.value,
        ),
        required=True,
    )
    replay_bundle.add_argument(
        "--blind-key-file",
        default=None,
        help="file containing the external blind key; never pass the key on the command line",
    )
    replay_bundle.add_argument(
        "--offline",
        action="store_true",
        help="synthetic contract tests only; refused for a real bundle",
    )
    replay_bundle.set_defaults(handler=_cmd_replay_bundle)
    run = sub.add_parser("run", help="measure what can be measured against a corpus")
    run.add_argument("--corpus", required=True, help="the directory holding MANIFEST.json")
    run.add_argument("--questions", default=None, help="frozen synthetic gold question file")
    run.add_argument("--workspace", required=True, help="the workspace uuid the corpus is in")
    run.add_argument(
        "--data-dir",
        default=None,
        help="where the object store lives (defaults to .exulanica/local)",
    )
    run.add_argument("--record", default=None, help="write the machine-readable record here")
    run.add_argument(
        "--archive-parent",
        default=None,
        help="create a write-once versioned report directory under this existing directory",
    )
    run.add_argument(
        "--repository",
        default=".",
        help="clean Git repository whose exact commit and tree produced an archived run",
    )
    run.add_argument(
        "--stranger-token",
        default=None,
        help="a token for a workspace that owns nothing, so M10 can be scored",
    )
    run.set_defaults(handler=_cmd_run)
    args = parser.parse_args(argv)
    return int(args.handler(args, stream))
