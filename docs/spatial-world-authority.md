# Durable spatial world authority

Status: **IMPLEMENTED** for canonical structural snapshots, reviewed preview/apply, protected-base
compare-and-swap, deletion invalidation, deterministic ancestor fallback, and package projection.
No production snapshot has been materialized in this checkout because no authorised real corpus or
reconstruction input is present.

This is the structural half of
[ADR-0007](adr/0007-world-composition-and-customization.md). The implementation is migration
`0020_durable_spatial_authority.sql`, `exulanica/world/structure.py`,
`exulanica/world/structure_repository.py`, and the draft adapter in
`web/packages/atlas-core/src/world/persistence.ts`.

## Authority boundary

The Atlas composer still emits an engine-neutral draft. The persistence adapter combines that
draft with exact layout, neighborhood, graph, reconstruction, and evidence-binding inputs. It
quantizes positions to integer millimetres, yaw to integer microradians, scale to integer
thousandths, and slopes to integer millidegrees. It does not claim or compute an authoritative
digest.

The backend then:

1. refuses floats and non-canonical ordering;
2. validates region, element, attachment, layout, neighborhood, destination, reachability,
   collision, source-evidence, and dependency consistency;
3. derives canonical SHA-256 identities for topology, layout, placement, neighborhood, and the
   enclosing snapshot;
4. validates every evidence, capture, entity, and assertion dependency in the current workspace;
5. computes a protected structural diff;
6. writes an isolated preview; and
7. on apply, repeats validation, inserts immutable history, and moves one current pointer in the
   same transaction.

The digest encoding is the repository's existing strict JCS subset: sorted object keys, compact
UTF-8 JSON, and no IEEE-754 values. Arrays whose order is not itself semantic must arrive in the
documented canonical order. This makes independent package verification possible without agreeing
on a language-specific float printer.

## Concurrency and lineage

Every preview records three bases: the current structural snapshot, graph SHA-256, and
reconstruction SHA-256. Apply locks the workspace authority and compares both the caller's tokens
and the preview's tokens with current state. A mismatch closes the preview as stale and changes no
snapshot. The same lock is taken by tombstone invalidation, closing the dependency-check/commit
race.

Element identity is stable across snapshots. The database retains the first snapshot and semantic
owner for each element, while each snapshot records membership and placement identity. Reusing an
element id for another world, region, or relationship is refused. Moving any surviving region's
structural element set requires one explicit placement migration with a unique id, reason, before
and after digests, approver, and committed snapshot.

## Deletion and fallback

Each committed snapshot has relational dependency rows in addition to its canonical JSON. A
tombstone automatically appends invalidation rows for every covered snapshot in the same
transaction. No immutable snapshot is rewritten or deleted.

`current()` reports the literal pointer and whether deletion invalidated it.
`effective_current()` walks parent links and deterministically returns the nearest non-invalid
ancestor. If deletion covers the entire lineage, it returns no structural world; a caller must use
the non-spatial evidence/index path until reviewed recomposition commits a new current snapshot.
This is a fallback, not an attempt to regenerate deleted evidence.

## Separation from appearance

A structural apply registers its topology contract with the existing appearance authority inside
the same outer transaction. Appearance preview/apply/rollback does not write any structural table
and carries no structural fields. The live database test changes appearance and requires the
structural pointer, graph digest, and reconstruction digest to remain byte-for-byte unchanged.

## Package projection

Every spatial snapshot stores a declarative package projection containing its identity, parent,
input graph and reconstruction identities, composer compatibility, fixed-point unit, and the four
section paths with their SHA-256 digests. World Memory Package v1 consumes this projection; it does not reread a
mutable renderer scene.

## Verification

`tests/test_world_structure.py` covers canonical repeatability, embedded-digest tampering, float and
ordering refusal, required-destination reachability, and collision refusal.
`tests/test_world_structure_postgres.py` covers immutable apply, stable identity, package projection,
competing stale composers, required placement migrations, appearance separation, live evidence
binding, tombstone invalidation, and nearest-valid-ancestor fallback on PostgreSQL 18.
