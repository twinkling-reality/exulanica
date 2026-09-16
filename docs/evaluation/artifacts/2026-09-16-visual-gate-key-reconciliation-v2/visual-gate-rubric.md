# Visual gate rubric: readsAsInhabitedStreet

Status: version 2, fixed before any street geometry is generated and before any corridor is scored. Changing it needs a new reconciliation record, never an edit made after a corridor has been scored.

Rubric version: 2

Version 2 was written on 2026-09-16, on branch `lane/gate` at main `63d97d2`. At that commit
`exulanica.grammar` emits only the box proof's three integer extents, which are admitted to no
projection, and every city stage (terrain, streets, parcels, massing, facade, material,
streetlife, vitrine, premises, tile) is a record shape with a validator and no generator. No
tessellator, no tile and no drawable generated geometry exists anywhere in the repository, and no
corridor has been scored.

Key set: `exulanica.visual-gate-keys/v2`, reconciled in
`docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v2.json`, which supersedes
`docs/evaluation/2026-09-15-visual-gate-key-reconciliation.json`. Version 1 of this rubric, stated
in that record, asked three questions of each picture, nine in all. Nine answers across three
pictures proved too long to complete, and a gate whose judgement cannot be completed cannot run.
Version 2 asks one question of each picture and stops at the first no.

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

> Does this look like a real street where people live, shop and work? Yes or no, and say why in your own words.

Directly under the question the judge is shown what a yes means. It is guidance, not three more
questions, and nothing else is offered as explanation:

> A yes means: you could name what at least three ground-floor shops or entrances are; the buildings form an unbroken street edge with no cut or hole; you can see things near (about 30 m), middle (about 100 m) and far (about 300 m).

## How it is asked

*   One picture and one question per ask. The answer options are **Yes** and **No**, in that
    order, and neither is marked, recommended or preselected.
*   The judge's own words are taken from their reply or from the notes they add to their choice,
    exactly as typed, and kept like this:

    > The judge's own words are kept exactly as typed in a private companion record under .exulanica/judge-words/, which never enters the repository. The public record binds that companion by SHA-256 and carries, for each reply, the SHA-256 and byte count of its words in their place.

*   No follow-up question is asked about what a word means. The guidance above is all the
    explanation there is.
*   If the judge declines to answer, the judgement stops there. Nothing is recorded as an answer,
    the question is not asked again in the same session, and no record is written.

## What counts as an answer

*   The answer is the option the judge picks: **Yes** is yes and **No** is no.
*   A reply the judge types in place of picking an option counts only when its first word is yes
    or no. Any other reply, and a skipped question, is not an answer. Nothing is inferred from it,
    by a model or by anyone else, and the judgement stops unscored.
*   Every answer carries a reason in the judge's own words. Words that are only yes or no are an
    answer without a reason, and a record is not written from them.

## How the answers compose

*   Pictures are asked in order: 1, 2, then 3.
*   **The first no decides the key.** `readsAsInhabitedStreet` is false, the remaining pictures
    are not asked, and the record lists each of them as `not asked after a decisive no`.
*   **The key is true only when all three pictures got yes.**
*   There is no score. A picture that was not asked, when no earlier picture got a no, leaves the
    key unscorable, and no record is written.

## The corridor bar

A corridor passes only with **all three pictures answered yes by the named judge, plus every
mechanical key**. Version 1 also required every one of its sub-answers to be yes for this key to
hold, so the bar is at least as strict as it was.

The Flatiron baseline is the calibration a corridor is read against. If the baseline itself ever
held every key, the gate could not tell a corridor from the district it replaces: the rubric would
have to be revisited in a new reconciliation record before any corridor is scored, and until then
no corridor passes.

## What the record carries

Every record that scores this key carries, and `visual_gate.py` refuses to write one without:

*   the judge's name, exactly as above;
*   the date the judge answered;
*   the SHA-256 of this rubric file as the judge answered against it, which must be the rubric
    the record is written with;
*   for each picture in order, its label and the SHA-256 of the capture shown, and either the
    answer with how it was given, when it was given, the SHA-256 and byte count of the judge's own
    words and the name of the person who typed them, which must be the judge, or
    `not asked after a decisive no`;
*   the path, byte size and SHA-256 of its private companion record, which holds the judge's
    words and is never committed;
*   the captures, each bound by path, byte size and SHA-256.

The writer refuses a missing or placeholder judge, a missing reason in the judge's own words, a
reply that does not say when it was given, a rubric digest mismatch, a capture not bound by
digest, a picture answered about a capture other than the one bound, a yes key with any picture
unasked, an answer given after a decisive no, any answer not typed by the judge, and a public
record that would carry any of the judge's words or a quoted part of them.

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
