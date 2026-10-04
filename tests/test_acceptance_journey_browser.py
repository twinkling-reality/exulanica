"""The connected journey's browser runner, ``scripts/acceptance/journey_browser.mjs``, without a
browser.

It reuses the rehearsal's page machinery instead of adding one: these hold that it imports only
the rehearsal's modules and node built-ins, that the session.json it writes has the rehearsal
session's shape (the same report keys, the same outcome keys and evidence keys per step), and
that it registers nothing in the rehearsal's step list, so S9's handler registry is untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "acceptance" / "journey_browser.mjs"
SESSION = ROOT / "scripts" / "rehearsal" / "session.mjs"


def _keys(source: str, opening: str) -> list[str]:
    """The top-level keys of the object literal that starts at ``opening``."""
    start = source.index(opening) + len(opening)
    depth, index = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        index += 1
    body = source[start : index - 1]
    keys, level = [], 0
    for token in re.finditer(r"[{}]|([A-Za-z_]+)\s*:", body):
        if token.group(0) in "{}":
            level += 1 if token.group(0) == "{" else -1
        elif level == 0:
            keys.append(token.group(1))
    return keys


def test_the_session_report_has_the_rehearsal_sessions_keys():
    runner, session = RUNNER.read_text(), SESSION.read_text()
    assert _keys(runner, "const report = {") == _keys(session, "const report = {")


def test_each_step_keeps_the_rehearsal_sessions_evidence_and_outcome_keys():
    runner, session = RUNNER.read_text(), SESSION.read_text()
    evidence = "const evidence = { screenshots: [], api: [], network: [], console: [], notes: [] };"
    assert evidence in runner and evidence in session
    for key in ("status", "reason", "observations", "evidence", "started_at", "finished_at"):
        assert re.search(rf"report\.outcomes\[id\] = \{{[^}}]*\b{key}\b", runner, re.S), key


def test_the_runner_imports_only_the_rehearsals_modules_and_node():
    imported = re.findall(r"^import .* from '([^']+)';$", RUNNER.read_text(), re.M)
    assert imported
    for module in imported:
        assert module.startswith("node:") or module.startswith("../rehearsal/"), module


def test_the_runner_registers_nothing_in_the_rehearsal_step_list():
    runner = RUNNER.read_text()
    # The rehearsal's registry is HANDLERS; the runner's own map is STEP_HANDLERS.
    assert re.search(r"\bHANDLERS\b", runner) is None
    assert "steps.json" not in runner


def test_every_step_a_row_reads_is_a_step_the_runner_runs():
    """N1.j, N1.k and N1.l are read from the runner's outcomes by step id: a step the driver names
    that the runner does not run would leave its row failed as never reached."""
    import importlib.util
    import sys

    path = ROOT / "scripts" / "acceptance" / "foundation.py"
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_foundation_steps", path)
    assert spec is not None and spec.loader is not None
    driver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = driver
    spec.loader.exec_module(driver)
    runner = RUNNER.read_text()
    listed = re.search(r"const STEPS = \[(.*?)\];", runner, re.S)
    assert listed is not None
    runs = re.findall(r"'([a-z-]+)'", listed.group(1))
    read = [*driver.JOURNEY_STEPS, *(step for _, _, step, _ in driver.WORLDS_ROWS)]

    assert sorted(read) == sorted(runs)
    for step in runs:
        assert f"async '{step}'(ctx)" in runner, step
