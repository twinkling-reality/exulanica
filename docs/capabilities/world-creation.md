# World creation

Create a persistent world from imagination, personal media or permitted imports. Shape its
architecture, landscape and aesthetic, then add objects, inhabitants and supported behavior.
The goal includes familiar places, dream landscapes and fantasy worlds with their own rules
and sense of time. These are product requirements, not a claim that every creation tool exists.

Returning users open their saved world. A person without one begins in an owned starter space,
with naming, media intake and creation inside the workspace. Direct controls and the Companion,
an AI partner for exploring and creating, use the same supported editing operations.

Sources can be combined without losing their origins. For example, an imported Icelandic
landscape, personal media and a fictional castle can belong to one authored world. Moving them
beside each other does not change real geographic relationships or establish a personal visit.
The [composition contract](../world-composition-contract.md) defines this target journey.

## Existing capability

[Authored starter worlds](../saved-world-entry.md) provide a source-independent starting space.
Reference photographs can be attached without replacing authored edits; attachment alone does not
reconstruct or place scene geometry.

Reviewed appearance controls and bounded language-driven appearance proposals
have preview/apply/rollback contracts. Source snapshots, alternate versions,
authored object add/move/remove/undo, bounded motion and reload/conflict recovery
have code and synthetic browser checks. See the
[object contract](../world-objects-contract.md) and the saved-world evaluation
(`2026-09-12-world-browser`, a local-only evaluation record a clone does not contain).
These checks do not prove the complete saved-world journey or visual quality.

A person furnishes a world from the
[world object catalog](../../assets/catalogs/world-objects/world-object.v2.json), read by
[`exulanica/world/object_catalog.py`](../../exulanica/world/object_catalog.py): the three grey
markers, and a bench, a cafe table with two chairs, a tree in a planter, a lamp post, a market stall
and a planter seat. Each kind states its title and summary, its dimensions, the recipe its mesh is
generated from ([`exulanica/world/assets.py`](../../exulanica/world/assets.py)) and the CC0 texture
sets it is drawn in, whose maps travel inside its container at 256 texels a side; each number in a
recipe cites the street furniture catalog or a declared measurement. The Create panel lists every
kind by its title, with the chosen kind's summary under the choice. Inhabitants rest at the benches,
the planter seat and the cafe table and stop at the tree and the stall, in rows along the sides each
kind names, spaced so that turning an object never crowds two of them together; a lamp post stands
in their way and offers nothing to do. A resting person is drawn sitting on the seat of the bench,
the chair or the ledge their place has, and a visitor faces the stall's counter or the tree.

"Place a small square before me" asks for the
[small square](../../assets/catalogs/world-objects/world-arrangement.v1.json): a tree between two
benches, with a market stall, a planter seat and a cafe table behind it and a lamp post at each front
corner, in front of the person and facing them. The server works out where each object goes from
where the person stands and faces, shows it before anything is written, and applies it as ordinary
object edits, one change each, so "Take back the last change" removes them one at a time, newest
first; nothing takes back the whole square in one step. It is refused by name, and nothing is
written, when the world has no authored ground, when part of it would stand past the edge of the
ground people walk on or where people arrive, or when an object already stands there or where
people stand to use one ([`exulanica/world/arrangements.py`](../../exulanica/world/arrangements.py)).
It brings nobody in. Measured on 2026-09-24 with the deterministic
[`scripts/measure_furniture_use.py`](../../scripts/measure_furniture_use.py) (12 seeds, 30 simulated
minutes, eight inhabitants on the starter ground, the square before its arrival point), inhabitants
used 5.75 of the square's six usable objects per seed on average, against 5.17 of six when each
object is the marker of the same use at the same place.

The bounded Flatiron implementation, its admitted source data, and the line between source facts
and renderer completion are specified in
[owned district and source admission](../owned-district-and-admission.md).

## Gaps

Reusable real-world extraction, persistent geographic anchors, unified search
across memories/imports/creations, geometric blending and general language-driven
asset creation require the extensions in the
[composition contract](../world-composition-contract.md). A segmentation mask is
not automatically a complete editable object, and a map's display permission is
not permission to extract and remix its content. The Earth prototype is
an incomplete visualization path rather than a validated detailed environment.

Read the [product roadmap](../product-direction.md) for delivery order, the
[appearance contract](../atlas-world-customization-contract.md) for supported
style operations, and the [World Memory Package](../world-memory-package.md) for
portable-state boundaries. Package verification alone does not load a
runnable world in another application.
