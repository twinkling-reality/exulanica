# Two worlds that differ only in bindings share one tile key, and the second one faults the first

Measured 2026-09-19 by the walkable world lane, on a clean tree, for whoever takes city grammar
version 4. It belongs beside [tile-record-half-is-blocked.md](tile-record-half-is-blocked.md),
which measures what a version bump costs, because this is a second reason to spend one.

## What holds, so the finding is read at its true width

A baked tile is identified globally rather than per workspace, and that much is sound:

- `baked_tile` has no workspace column. Zero columns match `%workspace%` at migration head.
- Its identity column is `world_seed` since migration 0081.
- The tile store is content addressed. `tile_store(data_dir)` appends one namespace and the key is
  the digest, so no world appears in any path and two worlds' objects cannot collide.
- `baked_tile_id` is `uuid5(ARTIFACT_NAMESPACE, "baked_tile:<version>:<params>:<inputs>")`, and
  `tile_inputs_digest` covers the seed, so two worlds with **different seeds** take different keys.

So a second world needs neither a new database nor a new store, **provided it takes a new seed**.

## What does not hold

`tile_inputs_digest(record)` is `sha256_of_canonical(record_payload(record))` over a `TileRecord`,
and that record's fields are `city_seed`, `grammar_versions`, `coordinate_unit`, `catalog_digest`,
`tile_x`, `tile_y`, `lod`, `tile_size_mm`, `halo_radius_mm`, `ownership_rule`, `halo_rule` and
`edit_delta_digest`. **The bindings that shape the world are not among them.** And `CORRIDOR_SEED`
is a `sha256` over a fixed byte string with no dependence on `CORRIDOR_BINDINGS`, so nothing makes
a changed world take a changed seed.

That is a reading of the code. The measurement below is not: both worlds were generated.

    BASE      document 8d00b38441ff2e47  inputs cd381483fe2450a7  key abd1ec8d-3526-5a5c-9624-dc14e1c1d49a
    CHANGED BINDING: block_length_mm 140000 -> 130000
    BINDINGS  document b45d9700869b4cf9  inputs cd381483fe2450a7  key abd1ec8d-3526-5a5c-9624-dc14e1c1d49a
    SEED      document 5bd07803afd74064  inputs e25bde8323f12a8e  key e2e7965f-09c2-5ff3-972c-431003050e5f

    same seed, different bindings: documents differ? True   key the same? True
    CONTROL, different seed:       documents differ? True   key MOVED? True

**The third row is why the second one means anything.** A key computation that always returned one
value would make the first two rows look exactly like this. The control moves, so the comparison
can disagree, and the equal key is the code's answer rather than the method's.

These are the corridor's own numbers and not a synthetic case: `abd1ec8d` and `cd381483` are the
key and the inputs digest the corridor's tile (0,0) actually carries.

## The consequence is availability, not correctness, and that is the surprising half

The obvious fear is that a second world is served in place of the first. It is not. Recording a
differing container under one key is what `exulanica/migrations/0072_baked_tiles.sql` exists to
catch. Made to fire on a synthetic key, at a coordinate no bake uses:

    1  new key, bytes A           -> stored
    2  same key, bytes A again    -> identical
    3  same key, DIFFERENT bytes  -> nondeterminism_detected
    4  same key, bytes A again    -> nondeterminism_detected

    row state read back: nondeterminism_detected, fault container recorded, fault dated

**Call 4 is the one worth making.** Re-recording the *original* bytes does not clear the fault.
0072 says a fault cannot be tidied away and a faulted tile is never served, and
`exulanica/api/routes/tiles.py` turns `BakedTileFaulted` into a 409. So:

> Baking a second world under one seed shows nobody the wrong street. It takes the **first** world
> permanently off the air, and it presents as a tessellator determinism fault, which sends the
> reader to the tessellator when the cause is two worlds sharing a name.

That last clause is the reason this is worth a document rather than a line. The symptom names the
wrong component, and somebody would spend a day in `loom-tess`.

## What this asks of version 4

Put a digest of the generation bindings into the `TileRecord`, so that two worlds differing in
bindings differ in `tile_inputs_digest` and therefore in `baked_tile_id`. That is a new field on a
baked record, which moves every digest and needs a city grammar version, which is why it belongs
here and not in a lane.

Until it lands the guarantee is procedural: **a world is safe to bake once, and the same database
must not be written to by anybody varying that world's bindings under its own seed.** This project
keeps finding procedural guarantees broken, which is the argument for the field rather than for the
sentence.

## What is not established

Whether any *other* generation input is missing from the tile record the same way. Bindings were
checked because a lane met them; the question "what else shapes a document and is absent from its
record" was not asked, and answering it means enumerating `generate_city`'s inputs rather than
testing one of them.
