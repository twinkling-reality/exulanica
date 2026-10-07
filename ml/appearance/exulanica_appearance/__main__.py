"""Command line: ``python -m exulanica_appearance <command>``.

    weights build    --spec weights/candidates.json --metadata DIR --out weights/
    weights verify   --manifest FILE --directory DIR
    capture bench    --geometry FILE --out DIR
    measure frames   --structure DIR --frames DIR --out FILE
    measure textures --repository ROOT --out FILE
    measure session  --repository ROOT --results DIR --staged DIR --out FILE
    measure compare  --first DIR --second DIR --out FILE
    look record      --results DIR --findings FILE --crops DIR --records DIR
    sheet before     --structure DIR --frames DIR --out DIR
    sheet pairs      --repository . --results DIR --out DIR
    runner stage     --spec jobs/track-a-session-1.json --repository . --weights weights/ --out DIR
    runner run       --staged DIR --weights DIR --out DIR
    runner check     --out DIR
    runner dry-run   --repository . --out DIR
    runner gate      --results DIR --staged DIR --billed-seconds N --budget-seconds N --rate-cents N --out FILE
    assets dry-run   --repository ROOT --out DIR
    assets remote prepare|run ...   on the rented machine, from container/assets/job.sh
    assets nebius stage|submit|status|fetch|cancel|clear|usage ...   on this Mac

Every command reads and writes files only. None downloads a model, and none needs a GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from exulanica_pieces.canonical import Refused as PieceRefused

from exulanica_appearance.canonical import Refused

REFUSED = 3


def _weights_build(args: argparse.Namespace) -> int:
    from exulanica_appearance.weights import MetadataDirectory, build_weights

    spec = json.loads(Path(args.spec).read_bytes())
    metadata = {}
    for directory in sorted(Path(args.metadata).iterdir()):
        if (directory / "source.txt").is_file():
            read = MetadataDirectory.read(directory)
            metadata[(read.repository, read.revision)] = read
    out = Path(args.out)
    for entry in spec["repositories"]:
        raw = build_weights(entry, spec["read_on"], metadata)
        name = f"{entry['repository'].replace('/', '__')}@{entry['revision'][:12]}.json"
        (out / name).write_bytes(raw)
        document = json.loads(raw)
        print(
            f"{name} {document['licence']['id']} files={len(document['files'])} "
            f"bytes={document['total_bytes']}"
        )
    return 0


def _weights_verify(args: argparse.Namespace) -> int:
    from exulanica_appearance.weights import verify_directory

    checked = verify_directory(Path(args.manifest).read_bytes(), Path(args.directory))
    print(f"verified {checked} bytes")
    return 0


def _capture_bench(args: argparse.Namespace) -> int:
    from exulanica_appearance.capture.bench import capture_bench

    for line in capture_bench(Path(args.geometry), Path(args.out)):
        print(line)
    return 0


def _measure_frames(args: argparse.Namespace) -> int:
    from exulanica_appearance.metrics.report import measure_frames

    Path(args.out).write_bytes(measure_frames(Path(args.structure), Path(args.frames)))
    print(args.out)
    return 0


def _measure_textures(args: argparse.Namespace) -> int:
    from exulanica_appearance.metrics.report import measure_published_textures

    Path(args.out).write_bytes(measure_published_textures(Path(args.repository)))
    print(args.out)
    return 0


def _sheet_before(args: argparse.Namespace) -> int:
    from exulanica_appearance.sheets import before_sheets

    for path in before_sheets(Path(args.structure), Path(args.frames), Path(args.out)):
        print(path)
    return 0


def _sheet_pairs(args: argparse.Namespace) -> int:
    from exulanica_appearance.sheets import texture_pairs

    for path in texture_pairs(
        repository=Path(args.repository), results=Path(args.results), out=Path(args.out)
    ):
        print(path)
    return 0


def _runner_stage(args: argparse.Namespace) -> int:
    from exulanica_appearance.canonical import sha256_hex
    from exulanica_appearance.runner.staging import stage_texture_job

    spec = json.loads(Path(args.spec).read_bytes())
    manifests = {}
    for path in sorted(Path(args.weights).glob("*.json")):
        if path.name == "candidates.json":
            continue
        raw = path.read_bytes()
        manifests[sha256_hex(raw)] = raw
    manifest = stage_texture_job(
        repository=Path(args.repository), job=spec, weights_manifests=manifests, out=Path(args.out)
    )
    print(f"staged {args.out}: manifest {sha256_hex(manifest)}")
    return 0


def _runner_run(args: argparse.Namespace) -> int:
    import os

    from exulanica_appearance.canonical import sha256_hex
    from exulanica_appearance.runner.run import make_backend, run_job

    commit = os.environ.get("EXULANICA_BUILD_REVISION", "")
    image = os.environ.get("EXULANICA_CONTAINER_IMAGE", "")
    if not commit or not image:
        print(
            "refused: EXULANICA_BUILD_REVISION and EXULANICA_CONTAINER_IMAGE name the code and the image",
            file=sys.stderr,
        )
        return REFUSED
    results = run_job(
        staged=Path(args.staged),
        weights_root=Path(args.weights),
        out=Path(args.out),
        backend_factory=make_backend,
        code_commit=commit,
        container_image=image,
    )
    print(f"results {sha256_hex(results)}")
    return 0


def _runner_check(args: argparse.Namespace) -> int:
    from exulanica_appearance.runner.run import check_results

    results = check_results(Path(args.out))
    print(
        f"{len(results['generations'])} generations checked; stopped: {results['stopped'] or 'no'}"
    )
    return 0


def _runner_gate(args: argparse.Namespace) -> int:
    """Apply the smoke job's pass conditions; exit 0 to continue the session, 1 to stop and delete."""
    from exulanica_appearance.canonical import sha256_hex
    from exulanica_appearance.runner.gate import read_gate, smoke_gate
    from exulanica_appearance.runner.job import read_job

    out = Path(args.results)
    results_raw = (out / "results.json").read_bytes()
    job = read_job((Path(args.staged) / "job.json").read_bytes())
    records = {path.stem: path.read_bytes() for path in sorted((out / "records").glob("*.json"))}
    raw = smoke_gate(
        results_raw=results_raw,
        job=job,
        records=records,
        billed_seconds=args.billed_seconds,
        budget_seconds=args.budget_seconds,
        rate_cents_per_hour=args.rate_cents,
    )
    Path(args.out).write_bytes(raw)
    gate = read_gate(raw)
    for name in sorted(gate["checks"]):
        entry = gate["checks"][name]
        print(f"{'passed' if entry['passed'] else 'FAILED'}  {name}: {entry['detail']}")
    print(
        f"gate {sha256_hex(raw)}: {'continue' if gate['continue'] else 'stop, delete the machine and report'}"
    )
    return 0 if gate["continue"] else 1


def _runner_dry_run(args: argparse.Namespace) -> int:
    from exulanica_appearance.runner.dry_run import dry_run

    summary = dry_run(Path(args.repository), Path(args.out))
    for words, refusal in summary["refusals"].items():
        print(f"refused as it must: {words}\n    {refusal}")
    print(f"staged manifest {summary['staged_sha256']}")
    print(f"results {summary['results_sha256']}")
    for item in summary["summary"]["generations"]:
        print(
            f"  {item['target']} {item['role']} seed {item['seed']}: record {item['record_sha256'][:16]} "
            f"output {item['output_sha256'][:16]} seams {item['seams_ppm']} low frequency {item['low_frequency_share_ppm']}"
        )
    return 0


def _measure_session(args: argparse.Namespace) -> int:
    """Measure every generation of a finished run against the published set it dresses."""
    from exulanica_appearance.canonical import parse_canonical
    from exulanica_appearance.metrics.session import measure_session

    raw = measure_session(
        repository=Path(args.repository),
        results=Path(args.results),
        staged=Path(args.staged) if args.staged else None,
    )
    Path(args.out).write_bytes(raw)
    document = parse_canonical(raw, "the session measurements")
    summary = document["summary"]
    seams = summary["seams_ppm"]
    print(
        f"{summary['count']} generations: seams min {seams['min']} median {seams['median']} "
        f"max {seams['max']} (per million, 1000000 is no seam)"
    )
    skipped = summary.get("conditioning_not_measured")
    if skipped:
        print(f"structure edges not measured for {skipped['count']} outputs: {skipped['why']}")
    recall = summary.get("conditioning_recall_ppm")
    if recall:
        print(
            f"structure edges kept: recall median {recall['median']} ppm, min {recall['min']}, "
            f"max {recall['max']} over {recall['measured_over']} outputs"
        )
    for candidate, entry in sorted(summary["by_candidate"].items()):
        words = f"  {candidate}: {entry['seconds']['median']} s an image"
        retention = entry.get("retention_permille")
        if retention:
            words += (
                f", module retention over {retention['measured_over']} axes with a module: median "
                f"{retention['median']} per mille, min {retention['min']}, max {retention['max']}"
            )
        print(words)
    return 0


def _measure_compare(args: argparse.Namespace) -> int:
    """Compare two runs of one job spec by the digests they wrote."""
    from exulanica_appearance.canonical import parse_canonical
    from exulanica_appearance.metrics.session import compare_runs

    raw = compare_runs(first=Path(args.first), second=Path(args.second))
    Path(args.out).write_bytes(raw)
    document = parse_canonical(raw, "the comparison")
    print(
        f"{document['identical']} of {document['compared']} outputs identical: {document['verdict']}"
    )
    for row in document["generations"]:
        if not row["identical"]:
            print(
                f"  differs: {row['target']} {row['candidate']} {row['role']} seed {row['seed']}: "
                f"{row['first_output_sha256'][:16]} then {row['second_output_sha256'][:16]}"
            )
    return 0


def _look_record(args: argparse.Namespace) -> int:
    """Cut every picked output into 1:1 crops, sheet them, and write the look record."""
    from exulanica_appearance.look import look_at_results

    findings = json.loads(Path(args.findings).read_bytes())
    looked = look_at_results(
        findings=findings,
        results=Path(args.results),
        crops_root=Path(args.crops),
        records_root=Path(args.records),
    )
    for item in looked:
        print(
            f"{item['name']}: {item['crops']} crops at 1:1, look {item['look_sha256'][:16]}, "
            f"{item['suspected']} suspected"
        )
    print(f"{len(looked)} outputs looked at; crops and sheets under {args.crops}")
    return 0


def _assets_dry_run(args: argparse.Namespace) -> int:
    from exulanica_appearance.assets.dryrun import dry_run

    result = dry_run(Path(args.repository), Path(args.out))
    for piece in result["pieces"]:
        print(
            f"{piece['look_role']} {piece['piece'][:12]} triangles={piece['triangles']} "
            f"size_mm={piece['size_mm']} within={piece['within']}"
        )
    print(f"job {result['job'][:12]}; records, pieces and sheet.png under {args.out}")
    return 0


def _assets_remote_prepare(args: argparse.Namespace) -> int:
    from exulanica_appearance.assets.remote import prepare
    from exulanica_appearance.canonical import canonical_bytes

    report = prepare(
        code=Path(args.code),
        route=args.route,
        upstream=Path(args.upstream),
        weights=Path(args.weights),
        torch_home=Path(args.torch_home),
        hf_home=Path(args.hf_home),
    )
    Path(args.report).write_bytes(canonical_bytes(report))
    print(json.dumps(report, indent=1, sort_keys=True))
    return 0


def _assets_remote_publish(args: argparse.Namespace) -> int:
    from exulanica_appearance.assets.remote import publish

    counts = publish(Path(args.source), Path(args.target), Path(args.ledger))
    print(json.dumps(counts, sort_keys=True))
    return 0


def _assets_remote_run(args: argparse.Namespace) -> int:
    from exulanica_appearance.assets.job import run_job
    from exulanica_appearance.assets.remote import backend_for

    requests = [path.read_bytes() for path in sorted(Path(args.requests).glob("*.json"))]
    cutouts = {}
    if Path(args.cutouts).is_dir():
        from exulanica_appearance.canonical import sha256_hex

        for path in Path(args.cutouts).glob("*.png"):
            data = path.read_bytes()
            cutouts[sha256_hex(data)] = data
    results = run_job(
        job_raw=Path(args.job).read_bytes(),
        requests=requests,
        backend=backend_for(args.route, Path(args.weights)),
        repository=Path(args.code),
        out=Path(args.out),
        cutouts=cutouts,
    )
    print(json.dumps(results, indent=1, sort_keys=True))
    return 0 if all("piece" in item for item in results["items"]) else REFUSED


def _assets_nebius(args: argparse.Namespace) -> int:
    from exulanica_pieces.records import read_job

    from exulanica_appearance.assets import nebius

    if args.step == "stage":
        result: object = nebius.stage(
            repository=Path(args.repository),
            job=Path(args.job),
            requests=Path(args.requests),
            bucket=args.bucket,
            region=args.region,
            cutouts=Path(args.cutouts) if args.cutouts else None,
        )
    elif args.step == "submit":
        job = read_job(Path(args.job).read_bytes())
        result = nebius.submit(
            route=job["route"],
            job_sha256=args.job_sha256,
            code_sha256=args.code_sha256,
            bucket_id=args.bucket_id,
            subnet_id=args.subnet_id,
            platform=args.platform,
            preset=args.preset,
            timeout_seconds=job["stop"]["stop_at_seconds"],
            rate_cents_per_hour=args.rate_cents,
            bound_cents=args.bound_cents,
            preemptible=args.preemptible,
            profile=args.profile,
            dry_run=args.dry_run,
        )
    elif args.step == "status":
        result = nebius.status(args.id, args.profile)
    elif args.step == "cancel":
        result = nebius.cancel(args.id, args.profile)
    elif args.step == "clear":
        result = nebius.clear(bucket=args.bucket, region=args.region)
    elif args.step == "usage":
        result = nebius.usage(bucket=args.bucket, region=args.region)
    else:
        result = nebius.fetch(bucket=args.bucket, region=args.region, out=Path(args.out))
    print(json.dumps(result, indent=1, sort_keys=True) if not isinstance(result, str) else result)
    return 0


def session_queue_idle() -> int:
    from exulanica_appearance.assets.queue import IDLE_SECONDS_DEFAULT

    return IDLE_SECONDS_DEFAULT


def _assets_session(args: argparse.Namespace) -> int:
    from exulanica_appearance.assets import queue as session_queue

    if args.step == "serve":
        from exulanica_appearance.assets.remote import backend_for, publish
        from exulanica_appearance.assets.session import serve

        root, work, ledger = Path(args.root), Path(args.work), Path(args.ledger)
        result: object = serve(
            root=root,
            session_raw=Path(args.session).read_bytes(),
            code_sha256=args.code_sha256,
            backend=backend_for(args.route, Path(args.weights)),
            repository=Path(args.code),
            work=work,
            publish=lambda: publish(work, root / "out", ledger),
        )
        print(json.dumps(result, indent=1, sort_keys=True))
        return 0
    from exulanica_appearance.assets import nebius

    if args.step == "record":
        from exulanica_appearance.canonical import sha256_hex

        raw = session_queue.build_session(
            route=args.route,
            code_sha256=sha256_hex(nebius.code_archive(Path(args.repository))),
            idle_seconds=args.idle,
            stop_seconds=args.stop,
        )
        Path(args.out).write_bytes(raw)
        result = {"session_sha256": sha256_hex(raw), **session_queue.read_session(raw)}
    elif args.step == "stage":
        result = nebius.session_stage(
            repository=Path(args.repository),
            session_raw=Path(args.session).read_bytes(),
            bucket=args.bucket,
            region=args.region,
        )
    elif args.step == "start":
        from exulanica_appearance.canonical import sha256_hex

        raw = Path(args.session).read_bytes()
        session = session_queue.read_session(raw)
        result = nebius.submit(
            route=session["route"],
            job_sha256=sha256_hex(raw),
            code_sha256=session["code_sha256"],
            bucket_id=args.bucket_id,
            subnet_id=args.subnet_id,
            platform=args.platform,
            preset=args.preset,
            timeout_seconds=session["stop_seconds"],
            rate_cents_per_hour=args.rate_cents,
            bound_cents=args.bound_cents,
            preemptible=False,
            profile=args.profile,
            dry_run=args.dry_run,
            mode="session",
        )
    elif args.step == "submit":
        from datetime import UTC, datetime

        from exulanica_pieces.geometry.postprocess import POSTPROCESS_VERSION
        from exulanica_pieces.records import read_job

        job_raw = Path(args.job).read_bytes()
        job = read_job(job_raw)
        requests = [path.read_bytes() for path in sorted(Path(args.requests).glob("*.json"))]
        receipts = {
            path.name: path.read_bytes() for path in sorted(Path(args.receipts).glob("*.json"))
        }
        kept = session_queue.uncached_requests(
            requests,
            components_sha256=job["components_sha256"],
            postprocess_version=POSTPROCESS_VERSION,
            receipts=receipts,
        )
        if len(kept) != len(requests):
            raise Refused(
                f"{len(requests) - len(kept)} of the job's requests are already made under the "
                "same cache key; build the job without them"
            )
        result = nebius.queue(
            job_raw=job_raw,
            requests=requests,
            bucket=args.bucket,
            region=args.region,
            queued_at=datetime.now(UTC),
        )
    elif args.step == "status":
        result = nebius.session_status(
            session_sha256=args.session_sha256, bucket=args.bucket, region=args.region
        )
    elif args.step == "stop":
        result = nebius.session_stop(
            session_sha256=args.session_sha256, bucket=args.bucket, region=args.region
        )
    elif args.step == "charges":
        done = [path.read_bytes() for path in sorted(Path(args.done).glob("*.json"))]
        result = session_queue.charges_from_done(
            done, session_sha256=args.session_sha256, account=args.account
        )
    else:
        result = nebius.session_fetch(bucket=args.bucket, region=args.region, out=Path(args.out))
    print(json.dumps(result, indent=1, sort_keys=True) if not isinstance(result, str) else result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m exulanica_appearance")
    groups = parser.add_subparsers(dest="group", required=True)

    weights = groups.add_parser("weights").add_subparsers(dest="command", required=True)
    build = weights.add_parser("build")
    build.add_argument("--spec", required=True)
    build.add_argument("--metadata", required=True)
    build.add_argument("--out", required=True)
    build.set_defaults(run=_weights_build)
    verify = weights.add_parser("verify")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--directory", required=True)
    verify.set_defaults(run=_weights_verify)

    capture = groups.add_parser("capture").add_subparsers(dest="command", required=True)
    bench = capture.add_parser("bench")
    bench.add_argument("--geometry", required=True)
    bench.add_argument("--out", required=True)
    bench.set_defaults(run=_capture_bench)

    measure = groups.add_parser("measure").add_subparsers(dest="command", required=True)
    frames = measure.add_parser("frames")
    frames.add_argument("--structure", required=True)
    frames.add_argument("--frames", required=True)
    frames.add_argument("--out", required=True)
    frames.set_defaults(run=_measure_frames)
    textures = measure.add_parser("textures")
    textures.add_argument("--repository", required=True)
    textures.add_argument("--out", required=True)
    textures.set_defaults(run=_measure_textures)
    session = measure.add_parser("session")
    session.add_argument("--repository", required=True)
    session.add_argument("--results", required=True)
    session.add_argument("--staged")
    session.add_argument("--out", required=True)
    session.set_defaults(run=_measure_session)
    compare = measure.add_parser("compare")
    compare.add_argument("--first", required=True)
    compare.add_argument("--second", required=True)
    compare.add_argument("--out", required=True)
    compare.set_defaults(run=_measure_compare)

    look = groups.add_parser("look").add_subparsers(dest="command", required=True)
    look_record = look.add_parser("record")
    look_record.add_argument("--results", required=True)
    look_record.add_argument("--findings", required=True)
    look_record.add_argument("--crops", required=True)
    look_record.add_argument("--records", required=True)
    look_record.set_defaults(run=_look_record)

    sheet = groups.add_parser("sheet").add_subparsers(dest="command", required=True)
    before = sheet.add_parser("before")
    before.add_argument("--structure", required=True)
    before.add_argument("--frames", required=True)
    before.add_argument("--out", required=True)
    before.set_defaults(run=_sheet_before)
    pairs = sheet.add_parser("pairs")
    pairs.add_argument("--repository", required=True)
    pairs.add_argument("--results", required=True)
    pairs.add_argument("--out", required=True)
    pairs.set_defaults(run=_sheet_pairs)

    runner = groups.add_parser("runner").add_subparsers(dest="command", required=True)
    stage = runner.add_parser("stage")
    stage.add_argument("--spec", required=True)
    stage.add_argument("--repository", required=True)
    stage.add_argument("--weights", required=True)
    stage.add_argument("--out", required=True)
    stage.set_defaults(run=_runner_stage)
    run_parser = runner.add_parser("run")
    run_parser.add_argument("--staged", required=True)
    run_parser.add_argument("--weights", required=True)
    run_parser.add_argument("--out", required=True)
    run_parser.set_defaults(run=_runner_run)
    check = runner.add_parser("check")
    check.add_argument("--out", required=True)
    check.set_defaults(run=_runner_check)
    gate = runner.add_parser("gate")
    gate.add_argument("--results", required=True)
    gate.add_argument("--staged", required=True)
    gate.add_argument("--billed-seconds", type=int, required=True)
    gate.add_argument("--budget-seconds", type=int, required=True)
    gate.add_argument("--rate-cents", type=int, required=True)
    gate.add_argument("--out", required=True)
    gate.set_defaults(run=_runner_gate)
    dry = runner.add_parser("dry-run")
    dry.add_argument("--repository", required=True)
    dry.add_argument("--out", required=True)
    dry.set_defaults(run=_runner_dry_run)

    assets = groups.add_parser("assets").add_subparsers(dest="command", required=True)
    assets_dry = assets.add_parser("dry-run")
    assets_dry.add_argument("--repository", required=True)
    assets_dry.add_argument("--out", required=True)
    assets_dry.set_defaults(run=_assets_dry_run)

    remote = assets.add_parser("remote").add_subparsers(dest="step", required=True)
    remote_prepare = remote.add_parser("prepare")
    for name in (
        "--code",
        "--route",
        "--upstream",
        "--weights",
        "--torch-home",
        "--hf-home",
        "--report",
    ):
        remote_prepare.add_argument(name, required=True)
    remote_prepare.set_defaults(run=_assets_remote_prepare)
    remote_run = remote.add_parser("run")
    for name in ("--code", "--route", "--job", "--requests", "--weights", "--cutouts", "--out"):
        remote_run.add_argument(name, required=True)
    remote_run.set_defaults(run=_assets_remote_run)
    remote_publish = remote.add_parser("publish")
    for name in ("--source", "--target", "--ledger"):
        remote_publish.add_argument(name, required=True)
    remote_publish.set_defaults(run=_assets_remote_publish)

    on_nebius = assets.add_parser("nebius").add_subparsers(dest="step", required=True)
    nebius_stage = on_nebius.add_parser("stage")
    for name in ("--repository", "--job", "--requests", "--bucket", "--region"):
        nebius_stage.add_argument(name, required=True)
    nebius_stage.add_argument("--cutouts")
    nebius_submit = on_nebius.add_parser("submit")
    for name in (
        "--job", "--job-sha256", "--code-sha256", "--bucket-id", "--subnet-id", "--platform",
        "--preset", "--profile",
    ):  # fmt: skip
        nebius_submit.add_argument(name, required=True)
    nebius_submit.add_argument("--rate-cents", type=int, required=True)
    nebius_submit.add_argument("--bound-cents", type=int, required=True)
    nebius_submit.add_argument("--preemptible", action="store_true")
    nebius_submit.add_argument("--dry-run", action="store_true")
    for step in ("status", "cancel"):
        command = on_nebius.add_parser(step)
        command.add_argument("--id", required=True)
        command.add_argument("--profile", required=True)
    nebius_fetch = on_nebius.add_parser("fetch")
    for name in ("--bucket", "--region", "--out"):
        nebius_fetch.add_argument(name, required=True)
    for step in ("clear", "usage"):
        command = on_nebius.add_parser(step)
        command.add_argument("--bucket", required=True)
        command.add_argument("--region", required=True)
    on_nebius.required = True
    for command in on_nebius.choices.values():
        command.set_defaults(run=_assets_nebius)

    on_session = assets.add_parser("session").add_subparsers(dest="step", required=True)
    session_serve = on_session.add_parser("serve")
    for name in (
        "--code", "--route", "--session", "--code-sha256", "--root", "--weights", "--work",
        "--ledger",
    ):  # fmt: skip
        session_serve.add_argument(name, required=True)
    session_record = on_session.add_parser("record")
    for name in ("--repository", "--route", "--out"):
        session_record.add_argument(name, required=True)
    session_record.add_argument("--idle", type=int, default=session_queue_idle())
    session_record.add_argument("--stop", type=int, required=True)
    session_stage = on_session.add_parser("stage")
    for name in ("--repository", "--session", "--bucket", "--region"):
        session_stage.add_argument(name, required=True)
    session_start = on_session.add_parser("start")
    for name in ("--session", "--bucket-id", "--subnet-id", "--platform", "--preset", "--profile"):
        session_start.add_argument(name, required=True)
    session_start.add_argument("--rate-cents", type=int, required=True)
    session_start.add_argument("--bound-cents", type=int, required=True)
    session_start.add_argument("--dry-run", action="store_true")
    session_submit = on_session.add_parser("submit")
    for name in ("--job", "--requests", "--receipts", "--bucket", "--region"):
        session_submit.add_argument(name, required=True)
    for step in ("status", "stop"):
        command = on_session.add_parser(step)
        for name in ("--session-sha256", "--bucket", "--region"):
            command.add_argument(name, required=True)
    session_fetch = on_session.add_parser("fetch")
    for name in ("--bucket", "--region", "--out"):
        session_fetch.add_argument(name, required=True)
    session_charges = on_session.add_parser("charges")
    for name in ("--done", "--session-sha256", "--account"):
        session_charges.add_argument(name, required=True)
    for command in on_session.choices.values():
        command.set_defaults(run=_assets_session)

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except (Refused, PieceRefused) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
