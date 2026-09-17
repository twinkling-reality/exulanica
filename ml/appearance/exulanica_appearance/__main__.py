"""Command line: ``python -m exulanica_appearance <command>``.

    weights build    --spec weights/candidates.json --metadata DIR --out weights/
    weights verify   --manifest FILE --directory DIR
    capture bench    --geometry FILE --out DIR
    measure frames   --structure DIR --frames DIR --out FILE
    measure textures --repository ROOT --out FILE
    sheet before     --structure DIR --frames DIR --out DIR
    runner stage     --spec jobs/track-a-session-1.json --repository . --weights weights/ --out DIR
    runner run       --staged DIR --weights DIR --out DIR
    runner check     --out DIR
    runner dry-run   --repository . --out DIR
    runner gate      --results DIR --staged DIR --billed-seconds N --budget-seconds N --rate-cents N --out FILE

Every command reads and writes files only. None downloads a model, and none needs a GPU.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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

    sheet = groups.add_parser("sheet").add_subparsers(dest="command", required=True)
    before = sheet.add_parser("before")
    before.add_argument("--structure", required=True)
    before.add_argument("--frames", required=True)
    before.add_argument("--out", required=True)
    before.set_defaults(run=_sheet_before)

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

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
