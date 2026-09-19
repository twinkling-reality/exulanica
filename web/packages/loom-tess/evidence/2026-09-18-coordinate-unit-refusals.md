# ADR-0024's refusals, each one broken and watched to fail

Measured 2026-09-18 on `lane/coordinate-unit`. The breaks ran at lane head `da6d7d95` and `9190daf2`
(the trees named per break below); the lane was then rebased onto main `2517c92f`. Each break was
planted ALONE on a committed tree, whole files were run rather than a `-k` filter, and the tree was
restored with `reset --hard` plus `clean` with the restored state printed. Harness retained beside
this record.

## What the four rules are

ADR-0024 point 2, as four cases. The order matters: the first was broken first, deliberately,
because it is the only one whose failure is silent in the other direction. A refusal that rejects
every document written before the field existed looks exactly like a working refusal until somebody
feeds it an old document.

1. a document at the OLD version, with no field, is still READ, at millimetres;
2. an unrecognised version is refused, not read as millimetres;
3. the field absent at the NEW version is refused;
4. the field present with a unit the grammar does not admit is refused.

## The breaks

| # | Break | Tests failed | Which |
| --- | --- | --- | --- |
| 1 | `declaresCoordinateUnit` returns true for every table, so every version is asked for the field | **3** | including `reads a version 2 document, which states no unit, at millimetres` |
| 2 | a version with no field and no fixed unit falls through to millimetres | 1 | `is refused for a version that neither states one nor has one fixed` |
| 3 | the field is a `choices` list rather than a `choice`, so it may be omitted | **73** | the fixture, its shape table, and every envelope and mutation case |
| 4 | the field is free `text` rather than a closed choice | 2 | the committed shape table, and the frozen-versus-live difference |
| 5 | the build's own quantum check returns instead of refusing | 1 | `refuses to BAKE a unit this build does not write` |
| 6 | the load-time guard over every version's unit is removed | 1 | `the guard refuses one that is not` |
| 7 | the producer writes `micrometre` instead of the grammar's own value | 3 | the registry, the generator and the side-of-the-road refusal |

No break passed. The count is not zero for any of them.

## Two harness faults found by running it, not by reading it

**Three breaks asked nothing and said so.** Breaks 3, 4 and 7 run Python suites, and the harness
passed a multi-file suite as ONE shell word, so `pytest` exited 4 on a path that does not exist. The
harness printed `FAILED TEST COUNT: 0` and its own warning, and the exit code was 4 rather than 1,
which is what made it legible. Re-run with the words split, the three refuse as the table shows.
A filter is a second place a check can be silently empty; so is an argument that never became one.

**One break asked nothing for a real reason, and that is the finding.** Break 6 removed the guard
that holds every grammar version this tessellator reads to stating or fixing a coordinate unit, and
the whole package still passed: 290 of 290. The test beside it asserted the PROPERTY, which stayed
true with the guard gone, and nothing asserted that the GUARD fires. A guard that has never been
seen to refuse is a claim about the tables sitting where nothing tests it, which is the oldest entry
in the project's requirements file pointed at a guard rather than at a test.

Fixed by making it a function that takes the tables (`checkEveryVersionStatesItsUnit`), called at
load over the real ones and callable in a test with a version that decides nothing. Break 6 then
fails exactly one test. The fix is committed as `9190daf2`, separately from the breaks, so the
before and after are both on the record.

## A call site nothing covers, and two attempts to cover it that failed

Breaking `checkCoordinateUnit` fails its own test. THAT DOES NOT PROVE A BAKE CALLS IT, and deleting
the call from `bakeTile` passed all 83 tests in the file. Found by breaking it rather than by
reading, after the same shape had already been found twice in this lane.

Why no test reaches it: a real bake fed `coordinate_unit: micrometre` is refused by the GRAMMAR's
closed values first, `tile.fields.coordinate_unit: is not one of ["millimetre"]`, so no input can
arrive at the build's own check with a unit to refuse. That probe is the cheap general move when a
break of a guard fails nothing: feed a real input to the real entry point and read which refusal
answers.

Two attempts to make the call provable, both measured and both failed:

1. **Have the bake report the unit it read.** It does, and that is worth keeping for its own sake,
   but it proves `coordinateUnitOf` runs rather than that the check does: the reported value is
   computed on the line before, so deleting the check leaves the report intact. 83 passed.
2. **Have the check return the unit, so the caller needs its value.** Also fails: `coordinateUnitOf`
   returns a string too, the two are interchangeable to the compiler, and typecheck exits 0 with the
   call gone.

A branded return type would settle it. It was not taken, because it is ceremony around a check that
cannot fire, and a false sense of coverage is worse than a stated gap. THE GAP IS: the call is not
covered, its absence costs nothing while every version this tessellator reads admits one unit, and
whoever adds a version admitting a second must check this path is still wired. What IS covered is
that the unit reaches the bake.

## What is vacuous today, said plainly

The build's own quantum refusal (break 5) cannot fire through a bake on any shipped grammar. Every
city version this tessellator reads either fixes millimetre or closes `coordinate_unit` to
millimetre alone, so the grammar's shape check always refuses first. It is two refusals rather than
one because they answer different questions, and the second becomes reachable the day a grammar
admits a second unit while a build still writes one. It is tested where it lives rather than end to
end, because asserting it end to end would be asserting the grammar's refusal under this one's name.
