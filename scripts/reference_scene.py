"""Prepare, upload, human-admit and inspect a retained reference via ordinary Atlas APIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

from exulanica.evaluation.reference_inputs import prepare_inputs, verify_inputs
from exulanica.ingest.reference_admission import HUMAN_ATTESTATION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser(
        "prepare", help="Freeze inputs/split and create an unanswered review form"
    )
    prepare.add_argument("--sources", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--title", required=True)
    prepare.add_argument("--source-url", required=True)
    prepare.add_argument("--license-name", required=True)
    prepare.add_argument("--license-url", required=True)
    prepare.add_argument("--license-file", type=Path, required=True)
    prepare.add_argument("--attribution", required=True)
    prepare.add_argument("--retrieval-date", required=True)
    prepare.add_argument("--heldout-every", type=int, default=8)
    for command in ("intake", "admit", "status"):
        cmd = sub.add_parser(command)
        cmd.add_argument("--api", default="http://127.0.0.1:8000")
        cmd.add_argument("--output", type=Path, required=True)
        if command != "status":
            cmd.add_argument("--sources", type=Path, required=True)
            cmd.add_argument("--manifest", type=Path, required=True)
        if command == "admit":
            cmd.add_argument("--human-review", type=Path, required=True)
            cmd.add_argument("--permitted-use", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        path = prepare_inputs(
            args.sources,
            args.output,
            title=args.title,
            official_source_url=args.source_url,
            license_name=args.license_name,
            license_url=args.license_url,
            license_file=args.license_file,
            attribution=args.attribution,
            retrieval_date=args.retrieval_date,
            heldout_every=args.heldout_every,
        )
        print(path)
        return 0
    token = os.environ.get("EXULANICA_REFERENCE_TOKEN")
    if not token:
        parser.error("EXULANICA_REFERENCE_TOKEN must hold the workspace's configured bearer token")
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        base_url=args.api, headers={"Authorization": f"Bearer {token}"}, timeout=180
    ) as client:
        if args.command == "status":
            response = client.get("/operations/reconstruction-scenes")
            response.raise_for_status()
            (args.output / "status.json").write_text(json.dumps(response.json(), indent=2) + "\n")
            print(json.dumps(response.json(), indent=2))
            return 0
        manifest = verify_inputs(args.manifest, args.sources)
        files = manifest["record"]["files"]
        if args.command == "intake":
            accepted, refused, batches = [], [], []
            # Use conservative 60 MiB batches. Source bytes remain exact.
            pending, total = [], 0
            chunks = []
            for item in files:
                if item["bytes"] > 60 * 1024 * 1024:
                    raise ValueError("one source exceeds the conservative upload request budget")
                if pending and (total + item["bytes"] > 60 * 1024 * 1024 or len(pending) >= 100):
                    chunks.append(pending)
                    pending, total = [], 0
                pending.append(item)
                total += item["bytes"]
            if pending:
                chunks.append(pending)
            for chunk in chunks:
                handles = []
                try:
                    parts = []
                    for item in chunk:
                        stream = (args.sources / item["path"]).open("rb")
                        handles.append(stream)
                        parts.append(("files", (Path(item["path"]).name, stream)))
                    response = client.post("/intake", files=parts)
                    response.raise_for_status()
                    result = response.json()
                    accepted.extend(result["accepted"])
                    refused.extend(result["refused"])
                    batches.append(result["batch_id"])
                finally:
                    for stream in handles:
                        stream.close()
                (args.output / "intake.json").write_text(
                    json.dumps(
                        {
                            "source_manifest_sha256": manifest["record_sha256"],
                            "accepted": accepted,
                            "refused": refused,
                            "batches": batches,
                        },
                        indent=2,
                    )
                    + "\n"
                )
            if refused:
                raise ValueError("some photographs were refused; inspect intake.json")
            print(
                f"Retained {len(accepted)} photographs; human reconstruction review remains required."
            )
            return 0
        review = json.loads(args.human_review.read_bytes())
        if review.get("profile") != "exulanica.reference-human-review/v1":
            raise ValueError("human review profile is invalid")
        if review.get("source_manifest_sha256") != manifest["record_sha256"]:
            raise ValueError("human review does not name this frozen inventory")
        reviewed = review.get("members", [])
        if (
            len(reviewed) != len(files)
            or {row["sha256"] for row in reviewed} != {row["sha256"] for row in files}
            or any(
                row.get("no_visible_people_or_sensitive_regions") is not True for row in reviewed
            )
            or review.get("attestation") != HUMAN_ATTESTATION
            or not review.get("reviewed_by_name")
            or not review.get("reviewed_at")
        ):
            raise ValueError(
                "a named human must complete the exact-byte review; blank forms are not receipts"
            )
        intake = json.loads((args.output / "intake.json").read_bytes())
        if intake["source_manifest_sha256"] != manifest["record_sha256"] or intake["refused"]:
            raise ValueError("intake does not match the complete reviewed set")
        accepted = {row["blob_sha256"]: row for row in intake["accepted"]}
        if set(accepted) != {row["sha256"] for row in files}:
            raise ValueError("intake capture set differs from reviewed source set")
        record = manifest["record"]
        body = {
            "members": [
                {
                    "capture_id": accepted[item["sha256"]]["capture_id"],
                    "source_sha256": item["sha256"],
                }
                for item in files
            ],
            "source_manifest_sha256": manifest["record_sha256"],
            "source_manifest": record,
            "official_source_url": record["official_source_url"],
            "retrieval_date": record["retrieval_date"],
            "license_document_sha256": record["license"]["document_sha256"],
            "permitted_use": args.permitted_use,
            "reviewed_by_name": review["reviewed_by_name"],
            "reviewed_at": review["reviewed_at"],
            "attestation": review["attestation"],
        }
        response = client.post("/operations/reconstruction-admission", json=body)
        response.raise_for_status()
        (args.output / "admission.json").write_text(json.dumps(response.json(), indent=2) + "\n")
        print("Exact human review retained; ordinary derivative job queued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
