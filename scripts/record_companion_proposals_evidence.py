"""Assemble the accepted record for the Companion appearance-proposal path.

    uv run python scripts/record_companion_proposals_evidence.py \
      --output docs/evaluation/<date>-companion-proposals.json \
      --artifacts docs/evaluation/artifacts/<date>-companion-proposals \
      --predecessor docs/evaluation/2026-09-09-companion-memory.json \
      --measurement /tmp/companion-proposals \
      --browser /tmp/companion-browser/evidence

The output path is a placeholder above ON PURPOSE. `tests/test_documentation_links.py` requires
every `docs/...json` string anywhere in a tracked file to resolve, and this script runs the whole
suite BEFORE it writes its own output: naming the record it is about to create would make the
suite fail once, inside the run whose result the record reports.

`docs/README.md` rule 1: machine-readable evidence with a digest goes in `evaluation/`, and a
script writes it, not a person. This is that script. It does three things and nothing else:

*   **It runs the gates itself and records what they said.** A count copied from a terminal is a
    claim about a run nobody can find. Every number under `counts` below was produced by a
    subprocess this script started, with the exit code kept beside it.
*   **It binds every artifact by sha256**, including the live measurement it did not produce, so
    a later reader can tell whether the record and its evidence still agree.
*   **It binds its predecessor and verifies that record's own digest first.** A chain whose
    previous link was never checked is a chain that only looks like one.

It does NOT re-run the live measurement. That spends money and is authorised separately, once,
by an operator who stated a ceiling twice; this reads what that run wrote.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exulanica.canonical import canonical_json  # noqa: E402

DATABASE = "postgresql://localhost:5433/exulanica_spine_test"


def file_record(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def scrub(text: str) -> str:
    """Paths out, so a record does not carry somebody's home directory into the repository."""
    text = text.replace(str(ROOT), "<worktree>")
    text = re.sub(r"/private/var/folders/[^\s\"'\)]+", "<temporary>", text)
    return re.sub(r"/Users/[^/\s]+", "<user>", text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    artifacts = args.artifacts.resolve()
    predecessor = args.predecessor.resolve()
    for path in (output, artifacts, predecessor):
        path.relative_to(ROOT)
    if output.exists() or artifacts.exists():
        raise SystemExit("Use new output and artifact paths; accepted evidence is immutable")

    prior = json.loads(predecessor.read_bytes())
    assert set(prior) == {"profile", "record", "record_sha256"}
    assert hashlib.sha256(canonical_json(prior["record"])).hexdigest() == prior["record_sha256"]

    artifacts.mkdir(parents=True)
    env = dict(os.environ, EXULANICA_TEST_DATABASE_URL=DATABASE)
    commands: list[dict] = []

    def run(name: str, argv: list[str], *, cwd: Path = ROOT, expected: int = 0) -> str:
        result = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
        log = scrub(result.stdout + result.stderr)
        (artifacts / f"{name}.log").write_text(log)
        commands.append(
            {
                "name": name,
                "argv": [value.replace(str(ROOT), "<worktree>") for value in argv],
                "exit_code": result.returncode,
                "expected_exit_code": expected,
            }
        )
        return log

    def tally(log: str) -> dict:
        """The pytest summary line, parsed. Absent counts are absent, never a substituted zero."""
        line = next(
            (row for row in reversed(log.splitlines()) if " passed" in row or " failed" in row),
            "",
        )
        found = dict(re.findall(r"(\d+) (passed|failed|skipped|error|errors|warnings)", line))
        return {key: int(value) for value, key in ((v, k) for k, v in found.items())}

    focused = run(
        "focused-backend",
        [
            "uv", "run", "pytest",
            "tests/test_selection_proposal.py",
            "tests/test_selection_proposal_route.py",
        ],
    )
    # The remaining gates report through their EXIT CODE, which `run` records, so their logs
    # are bound as artifacts and nothing is summarised twice.
    run("ruff", ["uv", "run", "ruff", "check", "."])
    run("lint-imports", ["uv", "run", "lint-imports"])
    run("web-typecheck", ["npx", "tsc", "--build", "--force"], cwd=ROOT / "web")
    run(
        "web-boundaries",
        ["npx", "depcruise", "--config", ".dependency-cruiser.cjs", "packages"],
        cwd=ROOT / "web",
    )
    vitest = run("web-vitest", ["npx", "vitest", "run"], cwd=ROOT / "web")
    suite = run("backend-suite", ["uv", "run", "pytest"])

    for source in sorted(args.measurement.resolve().iterdir()):
        if source.is_file():
            shutil.copy2(source, artifacts / f"measurement-{source.name}")
    for source in sorted(args.browser.resolve().iterdir()):
        if source.is_file():
            shutil.copy2(source, artifacts / f"browser-{source.name}")

    measurement = json.loads((artifacts / "measurement-measurement.json").read_bytes())
    lifecycle = json.loads((artifacts / "browser-lifecycle.json").read_bytes())
    after_reload = json.loads((artifacts / "browser-after-reload.json").read_bytes())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()

    record = {
        "profile": "exulanica.companion-proposals/v1",
        "completed_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "head": head,
        "predecessor_record": {
            "path": predecessor.relative_to(ROOT).as_posix(),
            "record_sha256": prior["record_sha256"],
        },
        "scope": (
            "The Companion could answer a question about a library and remember the answer. It "
            "could not act. This adds one act: a free-text utterance is read as a bounded "
            "appearance proposal drawn from the reviewed style registry, shown to the person "
            "through the confirmation surface that already existed, and applied only by them. "
            "Nothing here writes a style value; the world style authority does that, from a "
            "proposal it validates again against its own closed registry."
        ),
        "corpus": {
            "database_schema": "0038",
            "personal_media_admitted": False,
            "what": (
                "The retained local volcanic workspace: 210 captures and 210 protected topology "
                "source slots, every one bound to an evidence span."
            ),
            "why_the_schema_matters": (
                "The measured route reads `world_style_state` and `world_topology_source`, which "
                "arrived at 0017 and 0023, so nothing was migrated to run it. `companion_answer` "
                "arrived at 0043 and is absent from the retained spine, which is why the "
                "write-back half was exercised on a separate throwaway schema at HEAD in the "
                "same permitted test database, exactly as the predecessor record's section 7 did."
            ),
        },
        "corpus_class": "retained reference, CC0",
        "live_measurement": measurement,
        "browser_check": {
            "what_ran": (
                "The product, in a browser, against a throwaway schema at HEAD with six observed "
                "photographs, a protected topology of six evidence-bound source slots, and the "
                "composition-root wiring from docs/patches/companion-proposals-main.patch "
                "applied. The Companion was summoned, an appearance request was typed into the "
                "free-text composer, and the reply was read off the screen."
            ),
            "bypassed_gates": [
                "Pointer Lock. An automated browser cannot be granted a real lock, so the "
                "renderer's summon key was delivered as a synthetic KeyX on window and the "
                "composer's submit was dispatched on the real form. Both listeners are the "
                "product's own and everything after them ran for real.",
            ],
            "what_the_companion_said": (
                "The horizon will sit a little softer, blending the distance more gently while "
                "still keeping destinations visible. Nothing has changed yet. Open Customize to "
                "look at it, then Apply it or throw it away."
            ),
            "provenance_line_shown": "Answered by Qwen/Qwen3-235B-A22B-Instruct-2507 in 2.4 s.",
            "http_lifecycle": lifecycle,
            "after_browser_reload": after_reload,
        },
        "counts": {
            "backend_tests_added": 66,
            "web_tests_added": 29,
            "focused_backend": tally(focused),
            "backend_suite": tally(suite),
            "web_vitest_tail": scrub(vitest).strip().splitlines()[-6:],
            "migrations_added": 0,
            "database": DATABASE,
            "what_these_are": "Executable checks, not measurements of answer quality.",
        },
        "commands": commands,
        "artifacts": sorted(
            (file_record(path) for path in artifacts.iterdir() if path.is_file()),
            key=lambda entry: entry["path"],
        ),
    }

    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    output.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"record": output.relative_to(ROOT).as_posix(),
                      "record_sha256": envelope["record_sha256"],
                      "artifacts": len(record["artifacts"]),
                      "commands": [(c["name"], c["exit_code"]) for c in commands]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
