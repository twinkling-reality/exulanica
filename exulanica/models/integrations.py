"""What a person's worlds can connect to: ``integrations.v1.json`` beside the manifest.

The Integrations page lists where a world's models run, the web source a making searches, GitHub,
where a world's versions are kept, and the outside programs a world's door lets in, and it names
none of them itself. Each entry here gives one its key, its kind, its name, one plain line of what
it does, its mark (shapes drawn in a 24 by 24 box) and, where one exists, its guide: a document
under ``docs/`` and one of its headings, read on GitHub under the catalog's ``guides`` address.
Whether an entry is on is never stated here; the read of its kind answers that. ``GET
/integrations`` answers the file as it was loaded.

A provider's entry is keyed by the manifest's own provider id and says whether that provider runs
on this computer (``local``: the manifest bills it nothing); a grant's entry says whether the
programs it lets in are AI (``ai``). A guide is held to a heading its document holds where the
documents are, in a checkout. An installed package ships no ``docs/`` (an image copies the package
and its assets), so there a guide is held to its shape alone, the checkout's tests having held it
to its heading. ``tests/test_integrations_catalog.py`` holds every provider the manifest bills, the
provider on this computer and the web source to an entry, so the page meets none the file does not
name.
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from exulanica.models.manifest import Manifest, load_manifest

__all__ = [
    "INTEGRATIONS_PATH",
    "KINDS",
    "LINE_MAXIMUM",
    "PROFILE",
    "REPOSITORY",
    "IntegrationsError",
    "integrations",
    "read_integrations",
]

INTEGRATIONS_PATH: Final = Path(__file__).with_name("integrations.v1.json")
PROFILE: Final = "exulanica.integrations/v1"
#: The checkout this package sits in, whose ``docs/`` a guide names. Installed, the package sits
#: in ``site-packages``, beside no project.
REPOSITORY: Final = Path(__file__).resolve().parents[2]
#: The longest line an entry keeps, in characters: one plain line beside the entry's name.
LINE_MAXIMUM: Final = 80
#: What an entry is, which says where its state is read: a model provider (``GET /models``), the
#: web source (``GET /worlds/drafts``), GitHub (``GET /world/github-projects/kept``), the door
#: (``GET /door/bridges``) or one kind of program it lets in (``GET /door/grants``).
KINDS: Final = frozenset({"provider", "web", "github", "door", "grant"})
_DOCUMENT_FIELDS: Final = frozenset({"profile", "version", "reason", "guides", "entries"})
_ENTRY_FIELDS: Final = frozenset({"key", "kind", "name", "line", "mark"})
#: The one field an entry of these kinds states beside the rest, always, and no other kind does.
_KIND_FIELDS: Final = {"provider": "local", "grant": "ai"}
#: The attributes each shape of a mark may state: its geometry, and nothing a browser runs.
_SHAPES: Final = {
    "rect": frozenset({"x", "y", "width", "height", "rx", "ry"}),
    "circle": frozenset({"cx", "cy", "r"}),
    "path": frozenset({"d"}),
}
_KEY: Final = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*")
#: A guide's document: a Markdown file under ``docs/``, named with no way out of it.
_DOCUMENT: Final = re.compile(r"docs/[\w/-]+\.md")
_EM_DASH: Final = "\u2014"
#: A Markdown heading's words, without the hashes before them or any closing ones.
_HEADING: Final = re.compile(r" {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*")
#: A line opening or closing a fenced example, whose lines are never headings.
_FENCE: Final = re.compile(r" {0,3}(`{3,}|~{3,})")


class IntegrationsError(ValueError):
    """The integrations file, or one entry in it, is not what this module reads."""


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise IntegrationsError(f"{where} is not a non-empty trimmed string")
    if _EM_DASH in value:
        raise IntegrationsError(f"{where} holds an em dash")
    return value


def _drawn(value: object) -> bool:
    """Whether a shape's attribute is a string or a finite number (never a boolean)."""
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _mark(key: str, value: object) -> None:
    if not isinstance(value, list) or not value:
        raise IntegrationsError(f"{key}: a mark is a list of shapes")
    for shape in value:
        if not isinstance(shape, Mapping) or len(shape) != 1:
            raise IntegrationsError(f"{key}: each shape of a mark is one rect, circle or path")
        [(name, attributes)] = shape.items()
        allowed = _SHAPES.get(name)
        if allowed is None:
            raise IntegrationsError(f"{key}: a mark draws {name!r}, not a rect, circle or path")
        if not isinstance(attributes, Mapping) or not attributes or not set(attributes) <= allowed:
            raise IntegrationsError(f"{key}: a {name} states some of {sorted(allowed)} only")
        for attribute, drawn in attributes.items():
            if not _drawn(drawn):
                raise IntegrationsError(f"{key}: a {name}'s {attribute} is not a string or number")


def _headings(text: str) -> set[str]:
    """Every heading of a Markdown document as a reader sees it: none inside a fenced example."""
    found: set[str] = set()
    fence: str | None = None
    for line in text.splitlines():
        if marker := _FENCE.match(line):
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None and (heading := _HEADING.fullmatch(line)):
            found.add(heading.group(1))
    return found


def _guide(key: str, value: object, repository: Path | None) -> None:
    if not isinstance(value, Mapping) or set(value) != {"document", "heading"}:
        raise IntegrationsError(f"{key}: a guide states exactly a document and a heading")
    document = _text(value["document"], f"{key}: guide document")
    heading = _text(value["heading"], f"{key}: guide heading")
    if _DOCUMENT.fullmatch(document) is None:
        raise IntegrationsError(f"{key}: guide document {document!r} is not a file under docs/")
    if repository is None:
        return
    path = repository / document
    if not path.is_file():
        raise IntegrationsError(f"{key}: guide document {document} does not exist")
    if heading not in _headings(path.read_text(encoding="utf-8")):
        raise IntegrationsError(f"{key}: {heading!r} is not a heading of {document}")


def _entry(value: object, manifest: Manifest, repository: Path | None) -> str:
    if not isinstance(value, Mapping):
        raise IntegrationsError("an entry is an object")
    key = value.get("key")
    if not isinstance(key, str) or _KEY.fullmatch(key) is None:
        raise IntegrationsError(f"{key!r} is not an entry's key")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise IntegrationsError(f"{key}: kind {kind!r} is not one of {sorted(KINDS)}")
    flag = _KIND_FIELDS.get(kind)
    fields = _ENTRY_FIELDS | ({flag} if flag else set())
    if not fields <= set(value) <= fields | {"guide"}:
        raise IntegrationsError(f"{key}: a {kind} states {sorted(fields)} and may state a guide")
    _text(value["name"], f"{key}: name")
    line = _text(value["line"], f"{key}: line")
    if len(line) > LINE_MAXIMUM or "\n" in line:
        raise IntegrationsError(f"{key}: line is one line of {LINE_MAXIMUM} characters or fewer")
    if flag and not isinstance(value[flag], bool):
        raise IntegrationsError(f"{key}: {flag} is true or false")
    if kind == "provider":
        if key not in manifest.providers:
            raise IntegrationsError(f"{key}: not a provider the model manifest declares")
        billed = key in manifest.billing_providers()
        if value["local"] is billed:
            raise IntegrationsError(
                f"{key}: local is {str(billed).lower()}, but the manifest "
                + ("bills it" if billed else "bills it nothing")
            )
    _mark(key, value["mark"])
    if "guide" in value:
        _guide(key, value["guide"], repository)
    return key


def read_integrations(document: object, repository: Path | None) -> dict[str, Any]:
    """An integrations document with every entry checked, as it was read. Each guide is held to a
    heading of its document under ``repository``; where that is None, to its shape alone."""
    if not isinstance(document, Mapping) or document.get("profile") != PROFILE:
        raise IntegrationsError(f"the integrations document is not {PROFILE}")
    if set(document) != _DOCUMENT_FIELDS:
        raise IntegrationsError(f"the integrations document states {sorted(_DOCUMENT_FIELDS)}")
    version = document["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise IntegrationsError("the integrations document's version is a whole number from 1")
    _text(document["reason"], "the integrations document's reason")
    guides = document["guides"]
    if not isinstance(guides, str) or not guides.startswith("https://") or guides[-1] != "/":
        raise IntegrationsError("guides is the https address the guides' documents are under")
    entries = document["entries"]
    if not isinstance(entries, list) or not entries:
        raise IntegrationsError("the integrations document states no entries")
    manifest = load_manifest()
    keys: set[str] = set()
    for entry in entries:
        key = _entry(entry, manifest, repository)
        if key in keys:
            raise IntegrationsError(f"{key}: a second entry with this key")
        keys.add(key)
    return dict(document)


@lru_cache(maxsize=8)
def _checked(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IntegrationsError(f"no integrations catalog at {path}") from exc
    except ValueError as exc:
        raise IntegrationsError(f"the integrations catalog at {path} is not JSON") from exc
    checkout = (REPOSITORY / "pyproject.toml").is_file()
    return read_integrations(document, REPOSITORY if checkout else None)


def integrations(path: Path = INTEGRATIONS_PATH) -> dict[str, Any]:
    """The catalog at ``path``, the shipped one unless a test names another. Read and checked once,
    since the file ships with the code and never changes under it, and answered as a copy, so no
    caller changes what the next one reads."""
    return copy.deepcopy(_checked(path))
