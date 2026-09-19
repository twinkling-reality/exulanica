"""A pytest plugin that writes what a falsification needs, as data it owns.

WHY, and it is one project fact breaking three separate measurements:

  * a second ``-q`` hides the pass count;
  * ``-qq`` drops the pass/fail line entirely and reshapes ``--collect-only``, so a test that parses
    it asserts nothing;
  * and ``-q`` in this project's addopts means pytest's ``=`` banner never appears, so a counter
    written against it read every run as having selected zero and reported a real refusal as having
    asked nothing.

Three times, one fact, and each time the measurement changed silently. Reading pytest's human
summary is reading a presentation layer that nobody promised to keep stable. This reads the session
instead: ``testscollected`` and the node ids that failed, written as JSON to the path in
``FALSIFY_REPORT``. Then addopts, ``-q``, colour and summary formatting cannot reach the numbers.

It is added with ``-p`` and never by editing addopts, because ``--strict-markers`` and
``--strict-config`` live there and are load bearing.
"""

from __future__ import annotations

import json
import os


_FAILED: list[str] = []
_ASKED: set[str] = set()


def pytest_runtest_logreport(report):
    """Every failing phase by NODE ID, and every test that actually ANSWERED.

    COLLECTED IS NOT ASKED, and the difference is the whole point. `session.testscollected` counts
    what pytest gathered, INCLUDING everything that then skipped without running, so a falsification
    run with the database down reports "nothing noticed over N tests" when nothing ran at all. This
    repository already takes the other view: `tests/conftest.py` prints UNVERIFIED INVARIANT in red
    when the postgres tests skip, calling them the only executable proof of what the database
    guarantees, and 66 test files carry those markers. A skip is the absence of proof here.

    A test is ASKED when it reported an outcome of its own:

      * it FAILED, in any phase, which is also how a setup error arrives;
      * or it reached the CALL phase and passed.

    A skip at setup never reaches the call phase, and `pytest.skip()` inside a test body reports the
    call phase as skipped, so neither counts. That is deliberate: the toolchain guards in this lane's
    own tests skip exactly that way when node or the web toolchain is missing.

    XFAIL AND XPASS COUNT AS ASKED, stated here rather than left to accident: the prose parser this
    replaced counted `xfailed` and `xpassed`, and the migration is not the place to change what a
    denominator means.
    """
    if report.failed:
        _FAILED.append(report.nodeid)
        _ASKED.add(report.nodeid)
    elif report.when == "call" and (report.outcome == "passed" or hasattr(report, "wasxfail")):
        _ASKED.add(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("FALSIFY_REPORT")
    if not path:
        return
    with open(path, "w", encoding="utf8") as handle:
        json.dump(
            {
                # BOTH numbers, because the GAP between them is itself a measurement: it is how a
                # reader learns the database was down rather than that a property is unpinned.
                "collected": session.testscollected,
                "asked": len(_ASKED),
                "failed": sorted(set(_FAILED)),
                "exitstatus": int(exitstatus),
            },
            handle,
        )
