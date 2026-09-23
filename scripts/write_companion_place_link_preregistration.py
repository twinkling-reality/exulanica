"""Freeze the Companion place-link measurement before any model call is made on its photographs.

    python scripts/write_companion_place_link_preregistration.py --main SHA --head SHA

The measurement asks the Companion three questions about a place the account holder confirmed from
its own sign, on a synthetic workspace, once with the composer's packet as main builds it and once
with this change, which puts the confirmed place on each photograph's line. What each answer must
say to be right is fixed here, from the photographs, before either arm runs.

The photographs are drawn here by ``scripts/measure_companion_place_link.py draw`` and bound by
SHA-256, and so are the scripts and the answer path's sources for each arm. No float appears in
the record: ``exulanica.canonical.canonical_json`` refuses them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure_companion_place_link as measure

from exulanica.canonical import canonical_json
from exulanica.models.manifest import Role, load_manifest

ROOT = Path(__file__).resolve().parents[1]
OUT = measure.PREREGISTRATION
BOUND_SOURCES = (
    "scripts/measure_companion_place_link.py",
    "scripts/make_place_proposal_d_photographs.py",
    "scripts/make_place_photographs.py",
    "scripts/write_companion_place_link_preregistration.py",
    "exulanica/selection/packet.py",
)
#: The answer path's one file that differs between the arms.
ARM_SOURCE = "exulanica/selection/question.py"

SUPPORTED = {
    "sign": (
        "The sign on photographs 1 and 2 reads MIRELAND HALL, the name the account holder "
        "confirmed for the place. A composed answer can carry it only as the placeholder the "
        "answer's names map to the confirmed place, which the browser shows as the confirmed "
        "name."
    ),
    "which": (
        "The photographs the account holder confirmed were taken at the place: photographs 1 and "
        "2, if the vision stage writes the place for both as it did on the places lane's run of "
        "these drawings. Never photograph 3, whose board's last word is covered and which no "
        "confirmation links to the place, and never photograph 4, which has no text."
    ),
    "when": (
        "The capture dates of the confirmed photographs, as the packet's date values state them: "
        "2026-08-14 for photograph 1 and 2026-08-16 for photograph 2."
    ),
}
RIGHT_WHEN = {
    "sign": [
        "names_the_confirmed_place_citing_its_photograph: a historical clause carries a "
        "placeholder that the answer's names map to the confirmed place's entity, and cites a "
        "confirmed photograph"
    ],
    "which": [
        "cites_exactly_the_confirmed_photographs: the photographs the historical clauses cite, "
        "resolved through the answer's own citations and selection, are exactly the confirmed "
        "photographs"
    ],
    "when": [
        "states_photograph_N_date, for each confirmed photograph N: the answer's text states that "
        "photograph's date, as the ISO date or as its day of the month with its month's English "
        "name, with no other year written",
        "cites_a_confirmed_photograph: a historical clause cites a confirmed photograph",
    ],
}


def _sha256(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def record(main_commit: str, head_commit: str, before_sha256: str) -> dict:
    with tempfile.TemporaryDirectory() as scratch:
        photographs = measure.draw(Path(scratch))
    manifest = load_manifest()
    return {
        "profile_note": (
            "Pre-registration of the Companion place-link measurement, written before any model "
            "call on its photographs. Scored once by scripts/measure_companion_place_link.py "
            "(score), whose digest is bound below."
        ),
        "written_before_any_model_call": True,
        "tree": {
            "main": main_commit,
            "worktree_head": head_commit,
            "note": (
                "The measured tree is main with this change: every path lane A's package changed "
                "between the worktree head and main was checked out from main, index and file "
                "together, and the change is the worktree's own edits."
            ),
        },
        "change": {
            "what": (
                "exulanica/selection/packet.py carries, on each photograph line a place's "
                "confirmed link selected, the place's entity id; exulanica/selection/question.py "
                "gives it the request's placeholder and renders it as "
                "'user_confirmed_place: [place A]', and the composer prompt says the line is the "
                "account holder's confirmation of where the photograph was taken and nothing about "
                "what it shows."
            ),
            "arms": {
                "before": {
                    ARM_SOURCE: before_sha256,
                    "prompt_version": "selection-6",
                    "note": (
                        "main's question.py. packet.py already carries the link, which nothing in "
                        "main's question.py reads, so the composer is sent what main sends it."
                    ),
                },
                "after": {ARM_SOURCE: _sha256(ARM_SOURCE), "prompt_version": "selection-7"},
            },
        },
        "recipe": {
            "drawn_by": "scripts/measure_companion_place_link.py draw",
            "scenes_from": "scene() in scripts/make_place_proposal_d_photographs.py",
            "note": (
                "The places lane's end-to-end scenes at the same indices, with capture times "
                "written in the Exif IFD, where exulanica/ingest/exif.py reads them; each time is "
                "checked with the product's EXIF reader when drawn."
            ),
            "place_name": measure.PLACE_NAME,
            "photographs": photographs,
        },
        "admission": {
            "route": "POST /personal-admission",
            "corpus_class": "synthetic",
            "granted_by": (
                "the acceptance runtime's synthetic account holder, through the measurement "
                "script, for synthetic drawings"
            ),
            "purpose": measure.ADMISSION_PURPOSE,
            "account_authority_basis": measure.AUTHORITY_BASIS,
            "granted_roles": list(measure.GRANTED_ROLES),
        },
        "flow": [
            "POST /intake for each photograph, refused unless its bytes are the registered ones",
            "POST /personal-admission with detection permission and the granted model rights",
            "the derivative job to a terminal event; each photograph's place decision read from "
            "its stored vision artifact",
            "POST /identity/name on the first photograph whose place was written, with the "
            "written label, and POST /identity/confirm for every other written one",
            "POST /selection/ask with each question in words, once per arm",
        ],
        "questions": [
            {
                "id": question_id,
                "text": text,
                "supported_answer": SUPPORTED[question_id],
                "right_when": RIGHT_WHEN[question_id],
            }
            for question_id, text in measure.QUESTIONS
        ],
        "every_answer_also": [
            "answered: HTTP 200 and abstained is null",
            "composed: deterministic is false, so the sentence is the composer's",
        ],
        "draws_per_question_per_arm": 1,
        "models": {
            role.value: [spec.model_id for spec in manifest[role].chain]
            for role in (
                Role.STRUCTURED_EXTRACTION,
                Role.REASONING_CHEAP,
                Role.EMBEDDING,
                Role.VISION,
            )
        },
        "spend": {
            "bound_usd": "1",
            "per_run_ceiling_usd": str(measure.RUN_CEILING_USD),
            "read_from": "the usage the provider reported, as the execution blocks and the job "
            "metrics carry it",
        },
        "sources_sha256": {path: _sha256(path) for path in BOUND_SOURCES},
        "not_covered": [
            "One draw per question per arm: a difference between the arms is one observation "
            "each, not a rate.",
            "Each arm is a fresh workspace, so the vision stage runs twice and may propose "
            "differently; each arm records its own decisions, and the confirmed photographs the "
            "rule uses are that arm's.",
            "The planner is not held fixed: each arm plans its own questions, and each answer's "
            "plan is recorded.",
            "Synthetic drawings of one place with one name, English questions, the manifest's "
            "chains. No personal photograph.",
            "The restored name and the opened photograph are checked in the browser on the after "
            "arm; the before arm is read from the API.",
            "An answer remembered across a reload is not measured.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", required=True, help="the main commit the tree is measured on")
    parser.add_argument("--head", required=True, help="the worktree's own head commit")
    parser.add_argument(
        "--before-question-sha256",
        required=True,
        help="SHA-256 of main's exulanica/selection/question.py, the before arm's",
    )
    arguments = parser.parse_args()
    body = record(arguments.main, arguments.head, arguments.before_question_sha256)
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }
    (ROOT / OUT).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{OUT} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
