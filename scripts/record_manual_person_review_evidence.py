"""Record executed manual review checks without rewriting earlier evidence.

This recorder binds logs and source bytes. Browser acceptance must be recorded separately after
serialized integration; a component test cannot establish the mounted browser path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]


def binding(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--predecessor", required=True)
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    output = ROOT / args.output
    predecessor_path = ROOT / args.predecessor
    predecessor = json.loads(predecessor_path.read_bytes())
    predecessor_digest = hashlib.sha256(canonical_json(predecessor["record"])).hexdigest()
    if predecessor_digest != predecessor["record_sha256"]:
        raise ValueError("predecessor digest does not verify")
    directory = ROOT / args.artifacts
    artifacts = [binding(path) for path in sorted(directory.iterdir()) if path.is_file()]
    if not artifacts:
        raise ValueError("no executed evidence")
    record = {
        "profile": "exulanica.manual-person-review/v1",
        "tested_head": args.head,
        "predecessor_record": {
            "path": args.predecessor,
            "record_sha256": predecessor_digest,
        },
        "artifacts": artifacts,
        "sources": [binding(ROOT / name) for name in (
            "web/packages/app/src/ui/person-region-editor.ts",
            "web/packages/app/src/ui/person-review.ts",
            "web/packages/app/src/person-review-api.ts",
            "web/packages/app/test/person-region-editor.test.ts",
            "docs/patches/manual-person-review-main.patch",
        )],
        "executed_path": "Generated DOM pointer gesture to authenticated transport payload",
        "negative_control": "Remove editor mounting and fail the named empty-detector gesture path",
        "browser_integration": "pending",
        "real_authenticated_route_add_reload": "pending",
        "screenshot_bindings": [],
        "limitations": [
            "No real personal data, hosted models or GPU work was used.",
            "Transport tests mock HTTP. They do not prove persistence in PostgreSQL.",
            "main.ts remains reserved; the patch is not integrated in this tested tree.",
        ],
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    with output.open("xb") as stream:
        stream.write(canonical_json(envelope) + b"\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
