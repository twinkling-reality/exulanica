"""The shipped-data section of THIRD_PARTY_NOTICES.md cannot go stale silently.

The notices file asserts facts about this repository that nothing else reads. For retained
third party data that is a real risk: a source added beside a catalog, or a new owned-world
source record, would ship with no attribution unless someone remembered this file. So every
retained source is found from the repository itself and must be named in the section, with its
dataset, its attribution, its terms and its digest. The checker is shown to fail on a section
missing a row, so a check that finds nothing is not mistaken for one that passed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
HEADING = "## Shipped third party data (2026-09-17)"
ANCHOR = "#shipped-third-party-data-2026-09-17"


def _section(text: str) -> str:
    start = text.index(HEADING)
    end = text.find("\n## ", start + len(HEADING))
    return text[start : len(text) if end < 0 else end]


def _retained_sources() -> list[dict[str, str]]:
    """What the section must name, read from the provenance the repository keeps."""
    required = []
    for path in sorted(ROOT.glob("assets/catalogs/sources/*.provenance.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        required.append(
            {
                "file": path.with_name(record["source_file"]).relative_to(ROOT).as_posix(),
                "dataset_id": record["dataset_id"],
                "attribution": record["attribution"],
                "terms_url": record["terms_url"],
                "sha256": record["sha256"],
            }
        )
    for manifest in sorted(ROOT.glob("assets/owned-world/*/manifest.json")):
        for record in json.loads(manifest.read_text(encoding="utf-8")).get("source_records", []):
            required.append(
                {
                    "dataset_id": record["dataset_id"],
                    "attribution": record["attribution"],
                    "terms_url": record["terms_url"],
                    "sha256": record["sha256"],
                }
            )
    return required


def _missing(section: str, required: list[dict[str, str]]) -> list[str]:
    return [
        f"{source['dataset_id']}: {name} {value!r}"
        for source in required
        for name, value in source.items()
        if value not in section
    ]


def test_there_are_retained_sources_to_check():
    datasets = sorted(source["dataset_id"] for source in _retained_sources())
    assert datasets == ["52n9-sdep", "5zhs-2jue", "uvpi-gqnh"]


def test_every_retained_source_is_named_in_the_shipped_data_section():
    section = _section(NOTICES.read_text(encoding="utf-8"))
    assert _missing(section, _retained_sources()) == []


def test_every_retained_file_the_section_lists_exists_with_the_digest_it_states():
    section = _section(NOTICES.read_text(encoding="utf-8"))
    rows = [line for line in section.splitlines() if line.startswith("| `assets/")]
    assert len(rows) == len(_retained_sources())
    for line in rows:
        path = line.split("`")[1]
        digest = line.split("SHA-256 `")[1].split("`")[0]
        assert hashlib.sha256(ROOT.joinpath(path).read_bytes()).hexdigest() == digest, path


def test_the_scope_statement_points_at_the_section():
    text = NOTICES.read_text(encoding="utf-8")
    scope = text[text.index("### Scope: nothing is vendored") : text.index("## 2.")]
    assert ANCHOR in scope


@pytest.mark.parametrize("dataset_id", ["uvpi-gqnh", "5zhs-2jue", "52n9-sdep"])
def test_the_check_fails_when_a_source_row_is_missing(dataset_id):
    section = _section(NOTICES.read_text(encoding="utf-8"))
    stripped = "\n".join(line for line in section.splitlines() if dataset_id not in line)
    assert any(item.startswith(dataset_id) for item in _missing(stripped, _retained_sources()))
