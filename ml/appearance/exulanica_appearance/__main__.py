"""Command line: ``python -m exulanica_appearance <command>``.

    weights build    --spec weights/candidates.json --metadata DIR --out weights/
    weights verify   --manifest FILE --directory DIR
    capture bench    --geometry FILE --out DIR
    measure frames   --structure DIR --frames DIR --out FILE
    measure textures --repository ROOT --out FILE
    sheet before     --structure DIR --frames DIR --out DIR

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

    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
