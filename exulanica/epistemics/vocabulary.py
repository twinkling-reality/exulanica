"""Every predicate in the vocabulary, and the decision somebody made when adding it.

This exists because of defect R4. ``predicate.writes_a_name`` is what stops a model writing a
name: ``a_name_comes_only_from_the_user`` refuses a row that declares itself a naming predicate
while permitting any kind but ``user``, and ``tg_entity_name_is_user_stated`` reads the flag
rather than the key, so a later ``nickname_is`` cannot escape by being spelled differently. Both
rules are downstream of one boolean that whoever adds the row types.

Whether a predicate's object IS a name is a semantic property. A database cannot decide it, a
regex over keys was rejected in migration 0001 for a reason that still holds, and a classifier
would be a model deciding what models may write. So this file does not enforce the property. It
makes the answer a written sentence in a reviewed diff, beside the boolean it justifies, instead
of a ``false`` in the fourth column of a values tuple that nobody reads twice.

Stated plainly, because the point of the file is to stop overclaiming: **a wrong entry here is
accepted.** What this closes is the row added without anybody answering the question. Migration
0007 removes the column's default so omission raises, and
``tests/test_vocabulary_decisions.py`` refuses a predicate that reached a migration without a
decision reaching this file.

On the scope of the flag. It asks what a PERSON is called, because ``entity.display_name`` is
what invariant 4 protects. ``place_is`` is a proper noun a model may write and it is still false,
and the reason is checkable rather than asserted: ``display_name`` is set only where an active
``kind='user'`` assertion under a ``writes_a_name`` predicate says so, and that flag is
constrained to user-only predicates, so no inference can reach the column whatever it writes.
``tests/test_identity.py`` holds that as a probe rather than as a paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "DECISIONS",
    "RECONSTRUCTION_SCENE_RUNG_PREDICATE",
    "VocabularyDecision",
]


RECONSTRUCTION_SCENE_RUNG_PREDICATE: Final = "reconstruction_scene_rung_is"


@dataclass(frozen=True, slots=True)
class VocabularyDecision:
    """One vocabulary row, and what was decided about its object."""

    key: str
    #: The migration that seeds it. Checked against the files, so the two cannot drift.
    seeded_by: str
    allows_kind: tuple[str, ...]
    writes_a_name: bool
    functional: bool
    #: The answer to the question ``writes_a_name`` asks: is this predicate's object the name a
    #: PERSON is called by? Not a description of the predicate. When the answer is no, say what
    #: the object is instead, because "no" is not a decision anybody reviewed.
    object_is: str


DECISIONS: Final[tuple[VocabularyDecision, ...]] = (
    VocabularyDecision(
        key="name_is",
        seeded_by="0001",
        allows_kind=("user",),
        writes_a_name=True,
        functional=True,
        object_is=(
            "The name a person is called by, said by the account holder about someone in their "
            "own life. This is the predicate the whole rule exists for."
        ),
    ),
    VocabularyDecision(
        key="person_present",
        seeded_by="0001",
        allows_kind=("inference", "user"),
        writes_a_name=False,
        functional=False,
        object_is=(
            "Nothing. The object is null and the claim is that somebody is in this region. "
            "WHICH somebody is a separate question that entity_link answers."
        ),
    ),
    VocabularyDecision(
        key="object_present",
        seeded_by="0001",
        allows_kind=("inference", "user"),
        writes_a_name=False,
        functional=False,
        object_is=(
            "A common noun for a thing in the frame, out of a detector's label set. A category "
            "a thing belongs to, never what anybody is called."
        ),
    ),
    VocabularyDecision(
        key="place_is",
        seeded_by="0001",
        allows_kind=("inference", "user"),
        writes_a_name=False,
        functional=True,
        object_is=(
            "A label for where a photograph was taken. It is a proper noun a model may write, "
            "and it is still not covered, because the flag asks what a PERSON is called and "
            "display_name is what invariant 4 protects. An inference cannot reach that column "
            "whatever it writes here: the trigger requires a naming predicate and that flag is "
            "constrained to user-only ones."
        ),
    ),
    VocabularyDecision(
        key="captured_at",
        seeded_by="0001",
        allows_kind=("capture", "user"),
        writes_a_name=False,
        functional=True,
        object_is="An instant, as an ISO 8601 string out of the recording's own metadata.",
    ),
    VocabularyDecision(
        key="device_model_is",
        seeded_by="0001",
        allows_kind=("capture",),
        writes_a_name=False,
        functional=True,
        object_is=(
            "The camera's model string out of EXIF. It names a product rather than a person, "
            "and only the recording itself may state it."
        ),
    ),
    VocabularyDecision(
        key="gps_position_is",
        seeded_by="0001",
        allows_kind=("capture", "user"),
        writes_a_name=False,
        functional=True,
        object_is="A latitude and a longitude. Two numbers, and nothing else is in the box.",
    ),
    VocabularyDecision(
        key="pixel_size_is",
        seeded_by="0001",
        allows_kind=("capture",),
        writes_a_name=False,
        functional=True,
        object_is=(
            "The width and the height of the recording in pixels. Two integers the file carries."
        ),
    ),
    VocabularyDecision(
        key="caption_is",
        seeded_by="0001",
        allows_kind=("inference",),
        writes_a_name=False,
        functional=False,
        object_is=(
            "A sentence a model wrote about the whole frame. It MAY contain a name it read off "
            "a sign and it still assigns none: nothing reads a caption as an entity's name, and "
            "it is labelled inference everywhere it is shown."
        ),
    ),
    VocabularyDecision(
        key="ocr_text_is",
        seeded_by="0001",
        allows_kind=("inference",),
        writes_a_name=False,
        functional=False,
        object_is=(
            "Text a model read off a surface in the photograph. Quoting a name is not assigning "
            "one: the claim is about what the pixels say, not about who anybody is."
        ),
    ),
    VocabularyDecision(
        key="public_entity_status_is",
        seeded_by="0001",
        allows_kind=("external",),
        writes_a_name=False,
        functional=False,
        object_is=(
            "The present-tense state of a PUBLIC entity, from a live lookup, and never a claim "
            "about a person in the account holder's own corpus."
        ),
    ),
    VocabularyDecision(
        key="reconstruction_rung_is",
        seeded_by="0005",
        allows_kind=("inference",),
        writes_a_name=False,
        functional=True,
        object_is=(
            "A rung between 1 and 4, the fraction of the frame that was placed, and the reason "
            "for both. A number and an explanation of a number."
        ),
    ),
    VocabularyDecision(
        key=RECONSTRUCTION_SCENE_RUNG_PREDICATE,
        seeded_by="0025",
        allows_kind=("inference",),
        writes_a_name=False,
        functional=True,
        object_is=(
            "A rung from 1 through 4 over a complete photograph set, the reasons higher "
            "rungs were withheld, and the number of photographs in that set."
        ),
    ),
    VocabularyDecision(
        key="reconstruction_scene_build_rung_is",
        seeded_by="0123",
        allows_kind=("inference",),
        writes_a_name=False,
        functional=False,
        object_is=(
            "A rung and gate result for one succeeded reconstruction job, named by its job ID. "
            "Several builds of a scene can keep distinct authorized claims. The object is a "
            "build's quality result, never the name a person is called by."
        ),
    ),
)
