"""Turn a run's recording into a fixture the repository's tests read, keeping only allowed fields.

    python3 bridges/luanti/tools/fixtures.py RUN_FOLDER NAME --about WORDS

``RUN_FOLDER`` is a check run's folder (``.exulanica/luanti-checks/<time>``) holding the mod's
``exchanges.jsonl``; the fixture is written to ``bridges/luanti/fixtures/NAME.jsonl``. Its first
line says what was recorded and with what; then one line per exchange with the door and per mark
the mod made, each reduced to the fields named below. A field not named is dropped, so nothing the
recording might hold beyond them (a header, a credential, a name) can reach a fixture. The query
of a polled path is dropped too: the cursor is the door's own, and changes run to run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EXCHANGE_FIELDS = (
    "exchange",
    "t_ms",
    "method",
    "path",
    "status",
    "timed_out",
    "ms",
    "request_text",
    "response_text",
)
MARK_FIELDS = (
    "mark",
    "t_ms",
    "request",
    "what",
    "status",
    "reason",
    "why",
    "ms",
    "grant",
    "subject",
    "kind",
    "label",
)


def reduced(entry: dict) -> dict:
    fields = EXCHANGE_FIELDS if entry.get("exchange") else MARK_FIELDS
    kept = {name: entry[name] for name in fields if name in entry}
    if "path" in kept:
        kept["path"] = kept["path"].split("?", 1)[0]
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_folder", type=Path)
    parser.add_argument("name")
    parser.add_argument("--about", required=True)
    arguments = parser.parse_args(argv)
    if not arguments.name.replace("-", "").isalnum():
        raise SystemExit("a fixture's name is letters, digits and hyphens")
    source = arguments.run_folder / "exchanges.jsonl"
    summary = json.loads((arguments.run_folder / "summary.json").read_text())
    lines = [
        json.dumps(
            {
                "fixture": arguments.name,
                "about": arguments.about,
                "adapter_version": summary["adapter_version"],
                "mapping_sha256": summary["mapping_sha256"],
                "started_at": summary["started_at"],
            },
            sort_keys=True,
        )
    ]
    for line in source.read_text().splitlines():
        lines.append(json.dumps(reduced(json.loads(line)), sort_keys=True, ensure_ascii=False))
    target = FIXTURES / f"{arguments.name}.jsonl"
    target.write_text("\n".join(lines) + "\n")
    print(f"{target}: {len(lines) - 1} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
