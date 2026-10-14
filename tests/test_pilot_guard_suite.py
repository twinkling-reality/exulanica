"""The pilot guard's own tests run with the suite.

The guard a paid pilot run depends on (``tools/prototypes/entity-model-pilot``) keeps its tests
beside it, offline by its own conftest. They are run here in a pytest of their own rather than
collected with ``tests``: the suite's modules import their ``conftest`` by that name, which the
guard's folder would shadow. So a product change that breaks the guard fails the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools" / "prototypes" / "entity-model-pilot"


def test_the_pilot_guard_s_own_tests_pass():
    environment = {
        **os.environ,
        # The guard's modules import the product from this tree, never another checkout's.
        "PYTHONPATH": os.pathsep.join(filter(None, (str(ROOT), os.environ.get("PYTHONPATH")))),
    }
    # The guard's tests touch no database; a test server's address is not passed on.
    for name in ("EXULANICA_TEST_POSTGRES", "EXULANICA_TEST_DATABASE_URL"):
        environment.pop(name, None)
    run = subprocess.run(
        [sys.executable, "-m", "pytest", str(GUARD), "-p", "no:cacheprovider", "-p", "no:randomly"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-2000:]
    assert " passed" in run.stdout and " failed" not in run.stdout, run.stdout[-2000:]
