"""What a project may publish where: written words, and things whose origin limits where they go.

One check runs before every publication, the rolling pull request and the single file alike,
over every file each commit would publish, and refuses before anything is written:

- **Written words reach only a private repository.** A project holds written words in the
  `readable` blocks capture adds when asked (what a decision was told, the labels it was offered,
  its choice and its spoken line), in an evidence file or in a checkpoint's own records, and, in
  a checkpoint kept with readable text, in the world's title, each character's name and
  personality (a character kept without them holds only its record's revision) and each made
  part's label (a world made from a person's words is worded from them). A
  repository whose visibility does not read `PRIVATE` (public, internal, or not stated) receives
  none: the pull request's text switching to codes is not enough while the files still carry them.
- **A thing goes only where its origin allows.** Each thing kind a published checkpoint names is
  published only where its origin record (:mod:`exulanica.things.origin`) lets it be shown:
  `public` anywhere; `private` (its own workspace) and `restricted` (never in a public artefact)
  only to a private repository. The record cannot say `public` of a person's upload, their own
  work or a private licence. A shipped kind's record is read from the installed library, a made
  kind's from the bytes the project keeps for it; a made kind whose bytes the project does not
  hold, or holds under another digest, is refused, since its rights cannot be read.

A refusal names the file and what it carries, never a value. Identifiers (a thing's placed id, a
session's) are not read as words here; the person reviews them before publishing, as the
transport's own notice says.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from exulanica.errors import ExulanicaError
from exulanica.things.origin import OriginRefused, read_origin
from exulanica.world.placed_things import ThingKindReference, shipped_kind
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError, decode, digest
from exulanica.world_package.projects.repository import PROJECT_FILE

#: The one visibility that receives written words and limited things.
PRIVATE: Final = "PRIVATE"


def _origin_distribution(kind: Mapping[str, Any], kinds: Mapping[str, bytes]) -> str | None:
    """Where a thing kind's origin lets it be shown, or None where that cannot be read."""
    try:
        if kind.get("source") == "workspace":
            data = kinds.get(kind["sha256"])
            if data is None or digest(data) != kind["sha256"]:
                return None
            document = decode(data)
            origin = document.get("origin") if isinstance(document, dict) else None
        else:
            reference = ThingKindReference(kind["kind"], kind["version"], kind["sha256"])
            origin = shipped_kind(reference).document["origin"]
        return str(read_origin(origin).document["distribution"])
    except (OriginRefused, ExulanicaError, KeyError, TypeError, ValueError):
        # Unknown, unshipped or unreadable: rights that cannot be read are refused by the caller.
        return None


def check(files: Mapping[str, bytes], visibility: str, kinds: Mapping[str, bytes]) -> None:
    """Refuse, by `Conflict`, what in `files` may not reach a repository of this visibility.

    `files` are project files by their published path; `kinds` are the made kinds' bytes the
    project keeps, by digest. Returns nothing when every file may be published there.
    """
    private = visibility == PRIVATE
    seen = (visibility or "unstated").lower()
    for path, data in sorted(files.items()):
        document = decode(data)
        if not isinstance(document, dict):
            raise ProjectError(f"{path} is not a project document")
        records = document.get("decisions") or []
        if not private and any(record.get("readable") is not None for record in records):
            raise Conflict(
                f"{path} carries written words (what a decision was told, offered and chose), "
                f"which reach only a private repository; this repository reads {seen}"
            )
        if path != PROJECT_FILE:
            continue
        if not private and (
            document.get("title") is not None
            or any(c.get("words") is not None for c in document.get("characters") or [])
            or any(p.get("label") is not None for p in document.get("parts") or [])
        ):
            raise Conflict(
                f"{path} carries written words (the world's title, a character's name or "
                f"personality, a made part's label), which reach only a private repository; this "
                f"repository reads {seen}"
            )
        for thing in document.get("things") or []:
            distribution = _origin_distribution(thing["kind"], kinds)
            if distribution is None:
                raise Conflict(
                    f"{path} names a made thing whose rights cannot be read: the project holds "
                    "no bytes of its kind under its digest"
                )
            if distribution != "public" and not private:
                raise Conflict(
                    f"{path} names a thing whose origin keeps it {distribution}, which reaches "
                    f"only a private repository; this repository reads {seen}"
                )
