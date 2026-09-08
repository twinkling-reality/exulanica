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
    parser.add_argument("--browser-report")
    args = parser.parse_args()
    output = ROOT / args.output
    predecessor_path = ROOT / args.predecessor
    predecessor = json.loads(predecessor_path.read_bytes())
    predecessor_digest = hashlib.sha256(canonical_json(predecessor["record"])).hexdigest()
    if predecessor_digest != predecessor["record_sha256"]:
        raise ValueError("predecessor digest does not verify")
    directory = ROOT / args.artifacts
    artifacts = [
        binding(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.suffix in {".json", ".log", ".png", ".jpg", ".py"}
    ]
    browser = None
    if args.browser_report:
        browser = json.loads((ROOT / args.browser_report).read_bytes())
        for required in (
            "positive",
            "full_page_reload",
            "normalized_outline_matches_stored",
            "pending_mask_has_no_editable_image",
            "second_capture_unchanged",
            "negative_failed",
            "restored_control_passed",
            "integration_tree_clean",
        ):
            if browser.get(required) is not True:
                raise ValueError(f"browser report did not establish {required}")
    if not artifacts:
        raise ValueError("no executed evidence")
    record = {
        "profile": "exulanica.manual-person-review/v1",
        "implementation_head": args.head,
        "predecessor_record": {
            "path": args.predecessor,
            "record_sha256": predecessor_digest,
        },
        "artifacts": artifacts,
        "sources": [
            binding(ROOT / name)
            for name in (
                "web/packages/app/src/ui/person-region-editor.ts",
                "web/packages/app/src/ui/person-review.ts",
                "web/packages/app/src/person-review-api.ts",
                "web/packages/app/test/person-region-editor.test.ts",
                "docs/patches/manual-person-review-main.patch",
                "exulanica/world/repository.py",
                "tests/test_world_api.py",
                "tests/test_world_style_postgres.py",
                "scripts/record_manual_person_review_evidence.py",
            )
        ],
        "executed_path": (
            "Mounted source-only inspector, empty detector inventory, pointer box, authenticated "
            "add route, full app reload, saved outline and unchanged second capture"
            if browser
            else "Generated DOM pointer gesture to authenticated transport payload"
        ),
        "browser": browser,
        "browser_integration": "executed" if browser else "pending",
        "captures": [
            {**binding(directory / "reload-fixed" / name), "shows": shows}
            for name, shows in (
                (
                    "browser-drawn.png",
                    "Generated 800x400 image and pointer-authored box before save",
                ),
                (
                    "browser-full-reloaded.png",
                    "Saved hidden region after full reload; media withheld",
                ),
                ("browser-other-capture.png", "Second generated photograph remains unreviewed"),
                ("browser-negative.png", "Named authoring path fails without editor mounting"),
            )
        ]
        if browser
        else [],
        "gate_heads": {
            "backend_full": {
                "head": "358be0be20610573deb5a5751ebd81a2f4d2983a",
                "passed": 2058,
                "skipped": 3,
                "log": "backend.log",
            },
            "web_full": {
                "head": "7af8ee26128b4d5cd0c96c56aee91070705cbde0",
                "passed": 876,
                "log": "web-corrected.log",
            },
            "backend_scope_correction": {
                "head": "f3a601f3c9da181f8870bb453427b758baedab82",
                "passed": 20,
                "log": "source-identity-focused.log",
            },
        },
        "limitations": [
            "No real personal data, hosted models or GPU spend was used.",
            "The first browser attempt at 098ae51 exposed the full-reload metadata gap; "
            "only reload-fixed artifacts at 2af3049 establish corrected acceptance.",
            "Initial Ruff and web failures are retained; corrected logs establish their fixes.",
            "Final independent full backend gates after the narrow metadata correction belong "
            "to the orchestrator; the owner full backend run predates that correction.",
            "Manual random region keys do not reconcile future detector grid identities.",
            "Pending-mask media stays unavailable; subject authentication is not established.",
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
