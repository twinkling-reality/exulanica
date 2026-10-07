"""A finished reference request's notes, as a drafter takes them.

A drafter that is handed a reference id (KINDS's kind drafter first) calls :func:`notes_for_draft`
and gets the rendered block for its prompt, the pictures that block's notes were read from, and the
provenance to keep with what it drafts. It answers only with the caller's own finished request
(``complete`` or ``partial``) made for the drafter's purpose, so nobody can borrow another person's
notes; otherwise it raises :class:`NotesRefused` with one of :data:`NOTES_REFUSALS`, and the drafter
drafts without notes.

The provenance names the notes and never holds their text: the request id, the bundle's digest,
how many notes the block holds, and their bases. The text stays in the request, with its workspace.

The block is web-derived and untrusted: it is quoted and delimited (:mod:`exulanica.references.
render`), and a drafter puts it in the person's message, never in its instructions. The notes were
screened for links, email addresses, long numbers, screened words and the account's words given to
the job; saved names were not judged here, so the drafter's own replacement of saved names and the
workspace's request policy apply to the block as to the person's words.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

import psycopg

from exulanica.errors import ExulanicaError
from exulanica.references import store
from exulanica.references.bundle import BASES, read_bundle
from exulanica.references.render import RenderedNotes, render_reference_notes

__all__ = [
    "NOTES_REFUSALS",
    "REFERENCE_BASES",
    "NotesForDraft",
    "NotesRefused",
    "notes_for_draft",
]

#: The words a drafted document's provenance may name as its notes' bases: the bundle's own.
REFERENCE_BASES: Final = BASES
#: Why a drafter is given no notes, each with the sentence it may show.
NOTES_REFUSALS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "reference_unknown": "no reference request of yours has this id",
        "reference_not_finished": "the reference request is still running or ended without notes",
        "reference_purpose_differs": "the reference request was made for another kind of draft",
        "reference_has_no_notes": "the reference request found no notes to draft from",
    }
)


class NotesRefused(ExulanicaError):
    """No notes for this draft: ``code`` names why (:data:`NOTES_REFUSALS`), ``detail`` says it."""

    def __init__(self, code: str) -> None:
        super().__init__(f"{code}: {NOTES_REFUSALS[code]}")
        self.code = code
        self.detail = NOTES_REFUSALS[code]


@dataclass(frozen=True, slots=True)
class NotesForDraft:
    rendered: RenderedNotes
    #: What the drafted document keeps: never the notes' text.
    provenance: Mapping[str, Any]


def notes_for_draft(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    reference_id: uuid.UUID,
    *,
    purpose: str,
) -> NotesForDraft:
    """The caller's own finished request ``reference_id`` as a drafter's notes, or a refusal."""
    found = store.read_request(connection, workspace_id, reference_id, owner_actor_id=actor)
    if found is None:
        raise NotesRefused("reference_unknown")
    # 0148 keeps a bundle exactly on a complete or partial request; both are read, for the types.
    if found.status not in ("complete", "partial") or found.bundle is None:
        raise NotesRefused("reference_not_finished")
    if found.purpose != purpose:
        raise NotesRefused("reference_purpose_differs")
    bundle = read_bundle(found.bundle)
    rendered = render_reference_notes(bundle)
    if rendered.used == 0:
        raise NotesRefused("reference_has_no_notes")
    return NotesForDraft(
        rendered=rendered,
        provenance=MappingProxyType(
            {
                "reference_id": str(found.reference_id),
                "bundle_sha256": bundle.digest,
                "notes": rendered.used,
                "basis": list(rendered.bases),
            }
        ),
    )
