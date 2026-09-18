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

**It will not derive its own rings.** When a tile carries them, the gate reads the rings the runtime
holds. A gate that derives its own scores a walk past obstacles the world does not have.

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
