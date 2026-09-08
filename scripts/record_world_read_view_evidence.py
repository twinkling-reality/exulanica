#!/usr/bin/env python3
"""Execute the exclusive generated-fixture campaign and preserve every failed attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from exulanica.canonical import canonical_json, sha256_of_canonical

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_world_read_views.py"
BASE = "8e88b59aadb41088dc5fab185c088e1f36c570b5"
PREDECESSOR = "docs/evaluation/2026-09-08-consent-timestamp-integration.json"
CONTROLS = {
    "bytes": "test_wrong_bytes_under_declared_digest_refuse_route",
    "final": "test_final_permission_check_refuses_during_fetch",
    "pixels": "test_camera_pixel_space_refuses_route",
}


def normalize(text: str) -> str:
    text = text.replace(str(ROOT), "<worktree>").replace(sys.executable, "<python>")
    text = re.sub(r"/Users/[^\s'\"]+", "<local-path>", text)
    text = re.sub(r"/(?:private/)?var/folders/[^\s'\"]+", "<fixture-path>", text)
    return text.replace("pytest-of-" + Path.home().name, "pytest-of-fixture")


def plugin(kind: str) -> str:
    # Function code replacement preserves FastAPI's already registered callable identity.
    return (
        '''"""A child-process-only negative control, never a source-tree edit."""
import ast
import inspect


def pytest_sessionstart(session: object) -> None:
    from exulanica.api.routes import evidence
    from exulanica.graph import world_read_views

    kind = '''
        + repr(kind)
        + """
    module = evidence if kind == "final" else world_read_views
    name = {"final": "masked", "bytes": "image_facts", "pixels": "check_pixels"}[kind]
    function = getattr(module, name)
    source = inspect.getsource(function)
    if kind == "bytes":
        source = source.replace("hashlib.sha256(data).hexdigest() == digest", "True")
    tree = ast.parse(source)
    node = tree.body[0]
    node.decorator_list = []
    if kind == "pixels":
        node.body = [ast.Pass()]
    if kind == "final":
        node.body = [statement for statement in node.body if not (
            isinstance(statement, ast.With)
            and any(isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Name)
                    and item.context_expr.func.id == "final_check" for item in statement.items)
        )]
    ast.fix_missing_locations(tree)
    namespace = dict(module.__dict__)
    exec(compile(tree, "<posed-view-negative-control>", "exec"), namespace)
    function.__code__ = namespace[name].__code__
"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--slot-confirmed", action="store_true", required=True)
    parser.add_argument("--previous-attempt", action="append", default=[])
    args = parser.parse_args()
    if not re.fullmatch(r"2026-09-[0-9]{2}-[a-z0-9-]+world-read-views", args.name):
        parser.error("use a unique dated name ending world-read-views")
    directory = ROOT / "docs/evaluation/artifacts" / args.name
    destination = ROOT / "docs/evaluation" / (args.name + ".json")
    if directory.exists() or destination.exists():
        parser.error("previous attempts are immutable; choose fresh paths")
    directory.mkdir(parents=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "EXULANICA_TEST_DATABASE_URL": "postgresql://localhost:5433/exulanica_spine_test",
    }
    commands = []

    def run(label: str, argv: list[str], extra: dict[str, str] | None = None) -> tuple[int, str]:
        print(label, flush=True)
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env={**env, **(extra or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = normalize(result.stdout)
        (directory / (label + ".log")).write_text(output)
        commands.append(
            {"label": label, "argv": [normalize(a) for a in argv], "exit_code": result.returncode}
        )
        (directory / "commands.json").write_bytes(canonical_json(commands))
        return result.returncode, output

    for label, argv in [
        (
            "locked-environment",
            ["uv", "sync", "--locked", "--extra", "pose", "--extra", "reconstruction"],
        ),
        (
            "targeted",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                TEST,
                "tests/test_world_read_bundle.py",
                "tests/test_world_read_route.py",
            ],
        ),
    ]:
        status, _ = run(label, argv, {"WORLD_READ_VIEW_ARTIFACTS": str(directory)})
        if status:
            raise SystemExit(label + " failed; attempt retained")
    for kind, test in CONTROLS.items():
        name = "posed_view_control_" + kind
        path = directory / (name + ".py")
        path.write_text(plugin(kind))
        selector = TEST + "::" + test
        status, output = run(
            "control-" + kind,
            [sys.executable, "-m", "pytest", "-q", "-p", name, selector],
            {"PYTHONPATH": str(ROOT) + os.pathsep + str(directory)},
        )
        # Keep the executed source as evidence, not an importable production module.
        path.rename(path.with_suffix(".py.txt"))
        if status != 1 or "FAILED " + selector not in output:
            raise SystemExit(kind + " did not fail its exact selector; attempt retained")
    for label, argv in [
        (
            "backend",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-o",
                "addopts=--strict-markers --strict-config",
            ],
        ),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("imports", [str(Path(sys.executable).parent / "lint-imports"), "--no-cache"]),
        ("web-typecheck", ["pnpm", "--dir", "web", "run", "typecheck"]),
        ("web-boundaries", ["pnpm", "--dir", "web", "run", "boundaries"]),
        ("web-tests", ["pnpm", "--dir", "web", "run", "test"]),
    ]:
        status, _ = run(label, argv)
        if status:
            raise SystemExit(label + " failed; attempt retained")
    predecessor = json.loads((ROOT / PREDECESSOR).read_bytes())
    assert sha256_of_canonical(predecessor["record"]).hex() == predecessor["record_sha256"]
    artifacts = []
    for folder in [directory, *(ROOT / p for p in args.previous_attempt)]:
        if not folder.resolve().is_relative_to(ROOT / "docs/evaluation/artifacts"):
            parser.error("previous attempts must be evaluation artifacts")
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            data = path.read_bytes()
            artifacts.append(
                {
                    "path": str(path.relative_to(ROOT)),
                    "byte_size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    record = {
        "profile": "exulanica.world-read-views-evaluation/v1",
        "source_base": BASE,
        "tested_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "predecessor_record": {"path": PREDECESSOR, "record_sha256": predecessor["record_sha256"]},
        "exclusive_slot": "Orchestrator granted at reservation 40fe649; isolated test schemas only",
        "commands": commands,
        "artifacts": artifacts,
        "negative_controls": [
            {
                "kind": kind,
                "selector": TEST + "::" + name,
                "exact_failed_line": "FAILED " + TEST + "::" + name,
            }
            for kind, name in CONTROLS.items()
        ],
        "limits": [
            "Generated media and scripted pose outputs; not reconstruction quality",
            "Identity pixels only; non-identity EXIF and changed pose/view input refuse",
            "Presentation receipts do not authorize training or redistribution",
            "Offline verification cannot discover subsequent withdrawals",
            "Migration NONE; no retained activation, personal media, hosted models, merge or push",
        ],
    }
    destination.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": sha256_of_canonical(record).hex(),
            }
        )
    )
    # This log is deliberately outside the sealed inventory to avoid self-reference.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_retained_evaluation_records.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    (directory / "post-final-envelope-check.log").write_text(
        normalize(result.stdout + result.stderr)
    )
    if result.returncode:
        raise SystemExit("Post-generation check failed; envelope and failed attempt retained")
    print(str(destination.relative_to(ROOT)), flush=True)


if __name__ == "__main__":
    main()
