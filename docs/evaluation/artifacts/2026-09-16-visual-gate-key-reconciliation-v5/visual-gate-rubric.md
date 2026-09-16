# Visual gate rubric: readsAsInhabitedStreet

Status: version 5, fixed before any street geometry is generated and before any corridor is scored. Changing it needs a new reconciliation record, never an edit made after a corridor has been scored.

Rubric version: 5

Version 5 was written on 2026-09-16, on branch `lane/gate` at main `63d97d2`. At that commit
`exulanica.grammar` emits only the box proof's three integer extents, which are admitted to no
projection, and every city stage (terrain, streets, parcels, massing, facade, material,
streetlife, vitrine, premises, tile) is a record shape with a validator and no generator. No
tessellator, no tile and no drawable generated geometry exists anywhere in the repository, and no
corridor has been scored.

Key set: `exulanica.visual-gate-keys/v5`, reconciled in
`docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v5.json`, which supersedes
`docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v4.json` and, through it, versions 3,
2 and 1.

Why the question changed. Version 1 asked three questions of each picture, nine in all, and a
judgement that long could not be completed. Version 2 asked one question of each picture, whether
it looked like a real street where people live, shop and work. Asked of the shipped Flatiron
district, whose surfaces are flat colour, it got yes for all three pictures, so it did not separate
a finished street from a block mock-up. Version 3 asked about that, but joined two claims in one
question, a finished, lived-in street and not a plain block mock-up, so a yes, a no or a short
negation in the judge's own words could attach to either, and the first answer given under it
could not be read without guessing. Version 4 asks one thing, and each option says what it means.
The answers given under versions 2, 3 and 4 are the calibration evidence for these changes: the
reconciliation records carry each pick, its reading and the SHA-256 of the judge's words, and
their private companions keep the words. No answer was scored, and no record was written, under
versions 1, 2, 3 or 4.

Why the reading of a typed reply changed. Version 5 shows the judge exactly what version 4 showed
and changes only how a reply typed in place of a pick is read. Version 4 counted a typed reply only
when its first word was yes or no. The first reply given under it was typed in place of a pick and
held the word no without opening with it, so it could not be read. Version 5 reads a typed reply as
no when it holds the whole word no and not the whole word yes, and never as yes. A typed reply can
therefore only fail the key, never pass it, which is the cautious direction for a stop condition.
This rule was adopted after that reply was given. That reply is the rule's first application, and
the judge had declined further questions about these pictures. The version 5 reconciliation record
states all of this. The replies given under version 2 are not re-read, because they were given
under version 2.

Where the judge's words are kept. Before this repository was first published, the storage clause
of every version of this rubric was set to keep the judge's words in a private companion record,
with only their SHA-256 and byte count in the public records. The text the judge is shown did not
change in any version.

## Judge

Named human judge: Glendon

The judge is the one person who scores this key. The name above is written exactly as the operator
supplied it on 2026-09-16, when asked what name the record should show for the person answering. A
role, a title or a placeholder is not a name, and a record whose judge field holds one is refused by
`exulanica/evaluation/visual_gate.py`.

**No model may score `readsAsInhabitedStreet`.** A model may not answer the question, suggest an
answer, pre-fill one, mark an option as recommended or break a tie. A model may prepare the
captures, show them, ask the question in the words below and keep the judge's words, exactly as
typed, in the private companion record described below; nothing else. A record that holds an
answer the judge did not give is not a gate record.

## What the judge looks at

Every scored run retains three captures of the product exactly as a person sees it: the
authenticated shell, the Companion and the reticle on screen, at a 1.62 m eye height, 1440 by 900
pixels.

| Capture | Shown as | Where on the route |
|---|---|---|
| `start` | Picture 1 of 3 | the first pose of the bounded route of roughly 125 m |
| `midpoint` | Picture 2 of 3 | the pose nearest the route's halfway point |
| `endpoint` | Picture 3 of 3 | the last pose of the route |

Each picture is shown **alone**, at full size, with its label, and is followed by its one
question before the next picture is shown. Pictures are never shown together, and the calibration
captures below are not shown between questions.

## The question

The same question is asked of each picture, in these plain words, and is not paraphrased:

> Is this a finished, lived-in street? Yes or no, and say why in your own words.

Directly under the question the judge is shown what each answer means. It is guidance, not more
questions, and nothing else is offered as explanation:

> A yes means: the surfaces look like real materials (brick, stone, glass, paving), not flat colour; you could name what at least three ground-floor shops or entrances are; the buildings form an unbroken street edge with no cut or hole; you can see things near (about 30 m), middle (about 100 m) and far (about 300 m). A no means it looks like a plain block mock-up.

Every ask ends with this line, so that an answer arrives with its reason:

> Pick Yes or No and type a few words why in the notes; the answer cannot be recorded without them.

The two options say what they mean, in this order, and neither is marked, recommended or
preselected:

*   **Yes, a finished, lived-in street**
*   **No, a plain block mock-up**

## How it is asked

*   One picture and one question per ask.
*   The judge's own words are taken from their reply or from the notes they add to their choice,
    exactly as typed, and kept like this:

    > The judge's own words are kept exactly as typed in a private companion record under .exulanica/judge-words/, which never enters the repository. The public record binds that companion by SHA-256 and carries, for each reply, the SHA-256 and byte count of its words in their place.

*   If an answer still arrives with no words, the picture is shown alone again and the judge is
    asked once, and only once for that picture:

    > You answered Yes. In a few words, why?

    or, for a no:

    > You answered No. In a few words, why?

    That reply is the answer's reason. It never changes the answer.
*   When the judge has already written about a picture under an earlier version of this rubric,
    its next ask carries one line above the question, and those words are kept:

    > The question now has one meaning. Pick the answer you mean. The words you already wrote about this picture are kept; add more if you like.

*   No other follow-up is asked, and none about what a word means. The guidance above is all the
    explanation there is.
*   If the judge declines to answer, the judgement stops there. Nothing is recorded as an answer,
    the question is not asked again in the same session, and no record is written.

## What counts as an answer

*   The answer is the option the judge picks: **Yes, a finished, lived-in street** is yes and
    **No, a plain block mock-up** is no.
*   A reply the judge types in place of picking an option is read by this rule and by nothing
    else:

    > A typed reply with no pick counts as no when it contains the whole word no, in any case, and does not contain the whole word yes. A typed reply never counts as yes; a yes must be picked. Any other typed reply is not an answer.

    "Whole word" means the word on its own, not inside another word such as "nobody". A typed reply
    that is not an answer, and a skipped question, stop the judgement unscored. Nothing else is
    inferred from the judge's words, by a model or by anyone else.
*   The rule has a known cost: the whole word no inside a favourable sentence reads as a no. That
    can only ever fail the key, never pass it. So every ask presents the two options, and a reply
    typed in place of a pick should stay rare.
*   A pick that the judge's own words, given right after it, may contradict is not recorded. Both
    are kept as calibration evidence: the pick in the record, the words in its private companion.
*   Every answer carries a reason in the judge's own words: the words given with it, the reply to
    its one follow-up, or, for a no, the words the judge had already written about that picture,
    each labelled with when and under which rubric version it was given. A yes needs words given
    with it. Words that are only yes or no are not a reason, and a record is not written from an
    answer without one.

## How the answers compose

*   Pictures are asked in order: 1, 2, then 3.
*   **The first no decides the key.** `readsAsInhabitedStreet` is false, the remaining pictures
    are not asked, and the record lists each of them as `not asked after a decisive no`.
*   **The key is true only when all three pictures got a picked yes.**
*   There is no score. A picture that was not asked, when no earlier picture got a no, leaves the
    key unscorable, and no record is written.

## The corridor bar

A corridor passes only with **all three pictures answered by picking yes, by the named judge, plus
every mechanical key**. Version 1 also required every one of its sub-answers to be yes for this key
to hold, versions 3 and 4 ask for more than version 2 did, and version 5 reads a typed reply only
as a no where version 4 could read one as a yes, so the bar is at least as strict as it has been.

The Flatiron baseline is the calibration a corridor is read against. If the baseline itself ever
held every key, the gate could not tell a corridor from the district it replaces: the rubric would
have to be revisited in a new reconciliation record before any corridor is scored, and until then
no corridor passes.

## What the record carries

Every record that scores this key carries, and `visual_gate.py` refuses to write one without:

*   the judge's name, exactly as above;
*   the date the judge answered;
*   the SHA-256 of this rubric file, which the record is written with, and the SHA-256 of the
    rubric the judge answered against. The two must be the same file, with one exception: an
    answer given against version 4 is read under this version, because version 4 showed the judge
    exactly the words this version shows. The record then carries both digests and labels the
    judge's reasons with version 4;
*   for each picture in order, its label and the SHA-256 of the capture shown, and either the
    answer with the option picked, when each reply was given, the SHA-256 and byte count of the
    judge's own words, the follow-up when one was asked, any earlier words carried into the ask with
    the line shown above it, the reasons the answer is recorded with and the name of the person who
    typed each reply, which must be the judge, or `not asked after a decisive no`;
*   the path, byte size and SHA-256 of its private companion record, which holds the judge's
    words and is never committed;
*   the captures, each bound by path, byte size and SHA-256.

The writer refuses a missing or placeholder judge, a missing reason in the judge's own words, a
reply that does not say when it was given, a rubric digest mismatch other than the version 4
exception above, a capture not bound by digest, a picture answered about a capture other than the
one bound, a yes key with any picture unasked, an answer given after a decisive no, a typed reply
that the rule above does not read as a no, a pick that is not one of the options, a follow-up for
an answer that already gave its reason or one not asked in the words above, carried words without
the line above the question or from a rubric version that was never fixed, a yes whose only words
are carried words, a follow-up for a picture whose earlier words are carried, any answer or reply
not typed by the judge, and a public record that would carry any of the judge's words or a quoted
part of them.

## Calibration set

The gate is anchored to the three retained rejections and the Flatiron baseline, so that a no means
the same thing each time a corridor is read against them.

| Record | Captures | Retained predecessor key and value |
|---|---|---|
| `docs/evaluation/2026-09-12-helsinki-visual-feasibility.json` | `capture-01-loading.png`, `capture-02-rejected.png` | `recognizableUrbanStreet`: false |
| `docs/evaluation/2026-09-12-helsinki-terminal-lod-successor.json` | `capture-01-terminal-loading.png`, `capture-02-terminal-rejected.png` | `recognizableUrbanScene`: false |
| `docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json` | `capture-01-route-start.png`, `capture-02-route-midpoint.png`, `capture-03-route-endpoint.png` | `recognizableMelbourneUrbanScene`: false |
| `docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json` | `start`, `midpoint`, `endpoint` | `readsAsInhabitedStreet`: scored by the judge with this rubric |

The captures live under `docs/evaluation/artifacts/<record name>/`, and each record binds them by
byte size and SHA-256.

The three rejections were scored before this rubric existed, against the recognisability of a real,
named city. Their values are anchors for a no, not rubric answers, and nothing here re-scores them.
The Flatiron baseline is the first run scored with this rubric.
