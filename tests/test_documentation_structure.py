"""The maintained documentation has one home and resolvable section links.

These checks validate navigation, not the truth of prose. Frozen evidence and decision text are
not rewritten to satisfy a changing navigation scheme.
"""

from __future__ import annotations

import copy
import html
import importlib.util
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
_DOCS = "docs"
_spec = importlib.util.spec_from_file_location(
    "documentation_catalog", ROOT / "scripts/generate_docs_index.py"
)
assert _spec and _spec.loader
catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(catalog)


def _map() -> dict:
    return {
        "version": 1,
        "groups": [
            {
                "id": "world",
                "title": "World",
                "purpose": "World state contracts",
                "documents": [{"path": "world.md", "role": "contract", "owns": "World state"}],
            }
        ],
    }


def test_every_public_document_has_one_declared_home():
    catalog.validate_navigation(
        json.loads(catalog.NAVIGATION.read_text()), catalog.tracked_documents()
    )


def test_an_added_document_requires_classification_and_private_notes_stay_out():
    files = [
        f"{_DOCS}/world.md",
        "docs/README.md",
        "docs/all-documents.md",
        f"{_DOCS}/evaluation/record.md",
        f"{_DOCS}/briefs/note.md",
        f"{_DOCS}/adr/0001-choice.md",
    ]
    catalog.validate_navigation(_map(), files)
    with pytest.raises(ValueError, match="unclassified documents"):
        catalog.validate_navigation(_map(), [*files, f"{_DOCS}/reference/world/behavior.md"])
    navigation = _map()
    navigation["groups"][0]["documents"].append(
        {"path": "reference/world/behavior.md", "role": "contract", "owns": "Behavior"}
    )
    catalog.validate_navigation(navigation, [*files, f"{_DOCS}/reference/world/behavior.md"])


@pytest.mark.parametrize("fault", ["duplicate", "missing", "escape", "role", "responsibility"])
def test_invalid_ownership_is_refused(fault):
    navigation = _map()
    entry = navigation["groups"][0]["documents"][0]
    if fault == "duplicate":
        other = copy.deepcopy(navigation["groups"][0])
        other["id"] = "other"
        navigation["groups"].append(other)
    elif fault == "missing":
        entry["path"] = "absent.md"
    elif fault == "escape":
        entry["path"] = "../outside.md"
    elif fault == "role":
        entry["role"] = "progress-log"
    else:
        entry["owns"] = ""
    with pytest.raises(ValueError):
        catalog.validate_navigation(navigation, [f"{_DOCS}/world.md"])


def _prose(text: str) -> str:
    """Ignore fenced examples when looking for live headings and links."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if not value:
                continue
            if key == "id" or (tag == "a" and key == "name"):
                self.ids.add(value)
            if key in {"href", "src"}:
                self.links.append(value)


def _anchors(text: str) -> set[str]:
    text = _prose(text)
    parser = _HTML()
    parser.feed(text)
    anchors = parser.ids
    for heading in re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        heading = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", heading)
        heading = html.unescape(re.sub(r"<[^>]+>", "", heading)).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        candidate = slug
        suffix = 0
        while candidate in anchors:
            suffix += 1
            candidate = f"{slug}-{suffix}"
        anchors.add(candidate)
    return anchors


def _links(text: str) -> list[str]:
    text = _prose(text)
    parser = _HTML()
    parser.feed(text)
    inline = re.findall(r"\]\(<?([^\s)>]+)>?(?:\s+['\"][^\n]*?['\"])?\)", text)
    definitions = re.findall(r"^\s{0,3}\[[^]]+\]:\s*<?([^\s>]+)", text, re.M)
    return inline + definitions + parser.links


def _broken_sections(document: Path, text: str) -> list[str]:
    broken = []
    for link in _links(text):
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.fragment:
            continue
        target = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
        # File existence is checked by the repository-wide link guard. Fragment checks apply to
        # local Markdown, not code line anchors or a server's route fragments.
        if (
            target.suffix == ".md"
            and target.is_file()
            and unquote(parsed.fragment) not in _anchors(target.read_text(encoding="utf-8"))
        ):
            broken.append(link)
    return broken


def test_section_links_resolve_on_the_maintained_reading_surface():
    navigation = json.loads(catalog.NAVIGATION.read_text())
    documents = [ROOT / "README.md", ROOT / "docs/README.md", catalog.TARGET]
    documents += [
        ROOT / "docs" / item["path"]
        for group in navigation["groups"]
        for item in group["documents"]
    ]
    broken = [
        f"{document.relative_to(ROOT)} -> {link}"
        for document in documents
        for link in _broken_sections(document, document.read_text(encoding="utf-8"))
    ]
    assert not broken, "unresolved documentation sections:\n" + "\n".join(broken)


def test_section_check_catches_a_removed_heading_and_accepts_explicit_and_duplicate_ids(tmp_path):
    target = tmp_path / "target.md"
    target.write_text('# State\n## Read `world`\n## State\n<a id="stable"></a>\n')
    document = tmp_path / "guide.md"
    text = (
        "[State](target.md#state-1) [Read](target.md#read-world) "
        '<a href="target.md#stable">Stable</a> [Bad](target.md#removed)\n'
        "```md\n[Example](target.md#not-a-real-link)\n```"
    )
    assert _broken_sections(document, text) == ["target.md#removed"]
    target.write_text('# Other\n<a id="stable"></a>\n')
    assert set(_broken_sections(document, text)) == {
        "target.md#state-1",
        "target.md#read-world",
        "target.md#removed",
    }


def test_catalog_file_and_html_links_name_repository_files():
    tracked = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
    for link in _links(catalog.TARGET.read_text()):
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (catalog.TARGET.parent / unquote(parsed.path)).resolve().relative_to(ROOT)
        assert target.as_posix() in tracked, f"catalog points outside the repository: {link}"
