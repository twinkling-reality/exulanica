# Naming

Where the names in this repository come from, and what each one is allowed to mean. Recorded because
the origins existed only in the author's head: a search of this tree on 2026-09-18 for the roots of
the project's own name returned nothing.

This document does not enumerate withdrawn names. See the documentation standard for the scan that
refuses one.

## Exulanica, the project

Stated by the author, 2026-09-18, and recorded here on that authority rather than derived from
anything in the tree.

| Part | Source |
| --- | --- |
| exulansis | a coined term for the ache of a story that cannot be conveyed to anyone who was not there |
| Lagunica | the kingdom in Re:Zero, as the author spells it in the coinage |

The two halves are the project in one word: a world built to be inhabited, and the difficulty of
carrying what happened inside it back out to someone else. The name predates every architectural
decision recorded in `docs/adr/` and is not up for revision.

## Ortelium, the world substrate

Chosen 2026-09-18 to replace `atlas` in package and document names.

| Part | Source |
| --- | --- |
| Ortelius | Abraham Ortelius, 1527 to 1598, who published `Theatrum Orbis Terrarum` in 1570 |
| -ium | the Latinate abstract ending, matching the author's existing coinages |

`Theatrum Orbis Terrarum` is generally held to be the first modern atlas. It precedes by
twenty-five years the 1595 collection in which Mercator applied the word "atlas" to a book of maps.

So the name is not a synonym for the word it replaces. IT NAMES THE WORK THE WORD WAS COINED TO
SUCCEED. A substrate that holds generated worlds is named for the first person to bind a world into
one volume, before the common noun for doing so existed.

### Rejected, and why

| Candidate | Reason |
| --- | --- |
| Mercator | The Mercator projection is the standard example of a map that distorts while looking authoritative. This project's discipline is refusing to report what it has not measured, so the association works against it |
| Ecumene | Apt in meaning, the inhabited world, and it matches the judged key `readsAsInhabitedStreet`. Rejected on how it reads on the page |
| Mundarium | A world-keeping place, legible without a footnote. Held as the alternative if Ortelium ever needs one |
| Tesserium | Names the mechanism, a world of tiles, rather than the goal |

## Scope of the rename

The name is decided. The rename is separate work and is not done.

| Subject | State |
| --- | --- |
| Package names `atlas-core`, `atlas-react` | Not renamed |
| Documents named `atlas-*` | Not renamed |
| The identity of a generated world, stored as `city_seed` | A separate decision, briefed, not done |

A trademark and namespace check has not been run. Nothing here asserts the name is free to use.

## Convention

| Rule | Meaning |
| --- | --- |
| A coined name is a fusion | A proper noun with a claim on the subject, plus a Latinate ending |
| A grammar's own vocabulary is content | `city.facade` and `city.entrance` are the city grammar's words for city things, and a second world kind brings its own |
| An identity that crosses grammars takes one name | Generic code reads one field whatever grammar produced the tile |
| A kind is not carried by a second field | A tile states the grammar it pins, and that grammar states its subject kind |
