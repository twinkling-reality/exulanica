# Visual gate targets

The visual gate scores a page. A **target** says which page, and everything that makes two runs of
it comparable: how the page is reached, the exact title it must show, what counts as a world being
mounted, which authentication conditions it may run under, what its record binds as the inputs that
were scored, and where the route rule's inputs come from.

Targets are declared twice and held to each other by a test: `GATE_TARGETS` in
`exulanica/evaluation/gate_keys.py`, which records may state, and `TARGETS` in
`scripts/capture_visual_gate.mjs`, which the harness may run.
`tests/test_visual_gate_targets.py` asserts the two sets are equal in both directions, so neither
can gain a page the other cannot.

## The two targets

`owned-district` is the product's own shell showing an owned district. It is the page every retained
record scored, and it is the page the Flatiron baseline failed.

`generated-tile-evaluation` is the development route that draws a baked tile: `?preview=1` and
exactly one of `tile`, `baked_tile` or `city` with coordinates. A production build has no code that
reaches it.

## What a record says

A record states its target. A record that does not state one scored the owned district, and always
did: the retained records were written before any other page could be scored, and they are
immutable, so that is the only reading that keeps them true. A record of the owned district is
byte-identical to one written before targets existed.

A baseline comparison is allowed across targets only when both records were measured by the same key
set and answered against the same rubric, and it states both targets. The keys do not know which
page they measured; what they cannot survive is a different question.

## What the gate will not do

**It will not compare against a title it cannot derive.** Each target names a symbol in the
product's own source, and the harness reads the title from there. If the symbol is gone the run
halts, because a derivation that quietly yields nothing would compare an empty expectation against
an empty title and pass.

**It will not accept a pose a run chose.** A walk pose in the URL is refused. A stated pose belongs
in a committed file, read by the gate and bound in the record by its digest. The lane a scored run
judges must never choose where the camera starts.

**It will not walk a route that nothing chose.** The route rule keeps the headings a capsule can
walk and then prefers the one with frontage on both sides. Given no collision rings it does not
fail: every heading qualifies, both tie-breaks are equal for all of them, and the answer is the
lowest heading that fits. That is a default in the costume of a decision, and a record of it would
truthfully say the rule was applied. So a page with no rings halts.

**It will not derive its own rings.** When a tile carries them, the gate reads the route obstruction
rings the runtime holds. A gate that derives its own scores a walk past obstacles the world does not
have. Those rings are the plan regions a walking capsule is kept clear of: they choose a heading,
they drop anything above head height, and they are not collision solids. Nothing in them stops a
body, so a walk that goes around a bench and a walk that passes through one look the same in a still
frame.

## The first run of the generated target, predicted before it was run

Written and committed before the harness was pointed at the development route, so the order is a
fact in the history rather than a claim in a report.

The conformance tile draws 40 entries over 2,065 triangles and carries a nav_envelope of 4,850
triangles, so a walk on it is supported. It carries no collision rings, and no generated tile can:
the container format declares exactly two projections, `render_batch` and `nav_envelope`, and the
tile runtime builds its navigation world with an empty obstacle list.

So the prediction is that the run HALTS on the ringless route, before it measures a single
mechanical key, with the message about a rule that has nothing to choose between.

If it halts somewhere else, that halt is a finding about the system and will be reported as the
reason it gave, not worked around. If it does not halt at all, something is wrong with the check
itself, and that is the more interesting result of the two.

## What that run did, measured

It halted where the prediction said, before a single mechanical key was measured, exit 3.

The page check passed on the way, which is what makes the halt mean anything: path `/`, the preview
title derived from `config.ts`, a world mounted by the shell and the canvas, and the tile runtime
reporting `tile-conformance`. The run then bound what the page had drawn, recognised by the
container's own magic rather than by its URL:

| bound | value |
| --- | --- |
| container sha256 | `48a87e1ce5c7ca78...`, 531,884 bytes |
| tile_inputs_digest | `e91381e15083e8e2...` |
| tile | x 0, y 0, lod 0, city seed `d0219dae9563...` |
| grammar | city version 2, descriptor `c82ac5e7d39e95ab...` |
| drawn | 2,065 render_batch triangles, 9 draw batches, 12 unavailable surfaces |
| look | `exulanica.generated-tile-look` version 1 |
| route obstruction rings | **0** |

Those numbers are about THAT container. The pinned tile changes when the tessellator changes, so a
figure quoted without the digest beside it silently becomes a claim about a different tile.

Three refusals were exercised on the same page, so the checks are known to fire rather than assumed
to: the owned-district target pointed at the preview page refused with `title "Exulanica", page
"Exulanica: synthetic read-only development preview"`; the generated target with no tile selector
refused for naming none of `tile`, `baked_tile`, `city`; and an undeclared target refused by name.

Two things the run found that reading had not:

**A page check that samples once races the title.** `index.html` ships `<title>Exulanica</title>`
and the app sets the real title while it starts. On the product target those agree, so nothing ever
raced; on the preview target a single early sample sees the static title and refuses a page that is
about to be correct. The refusal now names which condition failed rather than saying only that the
page was not the target, because five conditions reach that one message.

**A URL suffix is not a file type.** The development server answers a `?url` import of a tile with a
JavaScript module whose path still ends `.owd`. Read by suffix, that module decodes as a broken
container and stops the run. The scan now uses the URL only to narrow what it reads and the
container's own magic to decide, and a response that carries the magic and still fails to decode is
a broken container, which is a different fact and still stops the run.

## A definition with two readings, known and deliberately left

`completeCapsuleClearanceVerification` defines itself, in `exulanica/evaluation/gate_keys.py`, as
true only when a capsule "keeps at least 0.34 m from every drawn triangle that rises more than
0.18 m above that surface and lies outside every building exterior ring with at least 0.34 m to its
nearest edge".

That sentence has two readings:

**A.** Rings EXCLUDE triangles from the test: measure clearance only from triangles that lie outside
every building exterior ring.

**B.** Two conditions: clear of every qualifying drawn triangle, AND outside every building exterior
ring by at least 0.34 m.

**The implementation is B, and has always been B.** That can be established without reading the
implementation at all, from the key's own declared structure: its `decided_by` lists
`capsuleRingContactSamples` as one of the four values that decide it, and a pure exclusion reading
needs no ring counter whatsoever. Reading the code agrees: `measureCapsule` counts triangle contacts
against the drawn triangle table with no ring filter, and separately counts ring contacts against
the prisms, skipping any prism outside the capsule's height band.

**No retained score is affected and none moves.** The measurement has not changed, the key set
version has not changed, and the rubric digest is over `docs/visual-gate-rubric.md`, which states
nothing about capsules or clearance. Every retained record was scored by reading B, because reading
B is what the code has always done.

The sentence is left exactly as it is, on purpose. Its text is quoted verbatim by five retained,
digest-bound reconciliation records, and the gate re-checks the current text against them: changing
one word of it fails five record checks, which is those checks doing their job rather than an
obstacle. Editing it therefore needs a new reconciliation record, and a reconciliation record binds
a named human judge's calibration reply, which is a person's answer and not a thing to be
manufactured for a wording change.

This was found by building the generated-tile target, not by reviewing the product one, which is
also how the static-title hazard and the shared route-and-key ring input were found. Whoever meets
these two readings next: this was known, it was left deliberately, and the records are not suspect.
