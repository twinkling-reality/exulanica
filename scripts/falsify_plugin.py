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


def pytest_runtest_logreport(report):
    """Every failing phase, by NODE ID, which is the only identity a test has."""
    if report.failed:
        _FAILED.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("FALSIFY_REPORT")
    if not path:
        return
    with open(path, "w", encoding="utf8") as handle:
        json.dump(
            {
                "collected": session.testscollected,
                "failed": sorted(set(_FAILED)),
                "exitstatus": int(exitstatus),
            },
            handle,
        )
