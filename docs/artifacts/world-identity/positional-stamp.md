# Position zero is not the value you mean, and one-member sets hide the difference

Three fields of the city tile record are closed sets: `coordinate_unit`, `ownership_rule` and
`halo_rule`. Until 2026-09-19 both producers in this repository stamped them by taking position
zero of the admissible set. Each set has one member, so the stamp was correct and nothing could
have told you it was correct for the wrong reason.

`coordinate_unit` is four hours older than the fix. ADR-0024 landed it as a DECLARED field at city
grammar version 3, specifically so a reader stops assuming a unit, and the generator that stamps
it onto every tile took it from `COORDINATE_UNITS[0]`.

## Why no test could have caught it

A positional stamp is a legal member of the closed set by construction. It passes
`shapes.choice` validation, it is the right type, and every reader downstream succeeds on it. And
while a set has ONE MEMBER, `SET[0]` and the named value ARE THE SAME VALUE, so no assertion over
this tree can separate the two forms: it is a fixture whose values make the right answer and the
wrong answer coincide.

The identity-addressed form was already in the same expression. Two lines above where
`tile_record` took three values by position, it names `CITY_GRAMMAR.key.grammar_id` and
`.grammar_version`. The right shape sat beside the wrong one.

## The two-armed break, and what it measured

`docs/artifacts/world-identity/positional-stamp.py.txt`, run once per arm from a committed tree.
It adds a second admissible entry FIRST in each tuple, then asks each producer what it stamps.

Each arm is told which commit it is and REFUSES TO RUN unless `git rev-parse HEAD` is that commit,
because an arm that labels itself rather than checking is how this project once got ten perfectly
consistent green runs out of one tree measured twice. The two arms are provably different trees:
they carry different commits AND different `tile.py` digests, both printed.

    arm      commit     tile.py digest
    before   0a7cda92   1fea34f9f575ecbd8579a173bd53e32154fd43028709f3b2a45385ff4cd20eb7
    after    e7123589   9c6ed93c8db347686853140c6b753449fffd26c15d034f7f3cf1f37a02e10aa6

With `nanolitre`, `by_lottery` and `by_vibe` admitted first:

                            before (position zero)      after (the value named)
    generator unit          nanolitre                   millimetre
    generator ownership     by_lottery                  anchor_floor_division
    generator halo          by_vibe                     extent_meets_grown_square
    fixture unit            nanolitre                   millimetre
    fixture ownership       anchor_floor_division       anchor_floor_division
    fixture halo            extent_meets_grown_square   extent_meets_grown_square

**Six of the eight values the before arm was asked came back invented.** Nothing raised. Every one
of them is a legal member of its set.

**The two fixture rows that did NOT move are a finding rather than a gap**, and they are why both
producers were asked rather than one. The fixture builder had ONE positional read, the unit, and
wrote the other two as string literals. So a run that had asked only the fixture would have found
one fault of three and reported the other two fields as sound. The generator is where all three
were, and a test over either producer says nothing about the other. Both now have their own
assertion, in `tests/test_grammar_city_fixture.py` and `tests/test_corridor_generation.py`.

## What the fix is, and what it does not buy

Each pair now states the value a producer writes and derives the admissible set from it:

    WRITTEN_COORDINATE_UNIT   -> COORDINATE_UNITS
    ANCHOR_FLOOR_DIVISION     -> OWNERSHIP_RULES
    EXTENT_MEETS_GROWN_SQUARE -> HALO_RULES

**Measured inert.** The fixture was regenerated with `tests/fixtures/city-v2/build_fixture.py` and
came back byte-identical: `tile-document.json` at 49be7eff98247649e1276b9c6ef5c441be9ad3289b220ba
8135ce7e87aad8e77 and 132,778 bytes, `record-shapes.json` at 35603f3d7e5831de00dcd2e0ce9deca98faf
84354274253aa384d50a7cbcfdb5, both the same as before the change. No digest of anything moves, so
nothing is rebaked.

**The assertions added do not cover this.** They fail the day a set gains an entry, which is the
day the question matters, and they send whoever adds one to the reasoning. They cannot tell the
two forms apart today, for the same reason nothing could: the values coincide. The run above is
the only thing that has ever separated them, and it is retained for that reason. THE GAP CLOSES
ITSELF ON THE DAY A SET GAINS A SECOND MEMBER, AND THAT IS NOT THE SAME AS BEING COVERED NOW.
