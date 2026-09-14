#!/usr/bin/env python3
"""Prepare or inspect an offline, authority-bound model evaluation plan.

This command reads local JSON and local artifacts only. It never imports a model runtime,
uses a credential, contacts a provider, allocates a GPU, or executes a candidate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exulanica.evaluation.model_preflight import inspect_request, inspect_results


def _read(path: Path):
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    plan = subcommands.add_parser("plan", help="validate and freeze a request")
    plan.add_argument("--request", type=Path, required=True)
    plan.add_argument("--source-root", type=Path, required=True)
    plan.add_argument("--manifest", type=Path)
    results = subcommands.add_parser("results", help="inspect result lineage and readiness")
    results.add_argument("--preflight", type=Path, required=True)
    results.add_argument("--artifact-root", type=Path, required=True)
    results.add_argument("--result", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            kwargs = {}
            if args.manifest is not None:
                kwargs["manifest_path"] = args.manifest
            report = inspect_request(_read(args.request), source_root=args.source_root, **kwargs)
            code = 0 if report["status"] == "ready" else 2
        else:
            report = inspect_results(
                _read(args.preflight),
                [_read(path) for path in args.result],
                artifact_root=args.artifact_root,
            )
            code = 0 if report["claimable"] else 2
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
