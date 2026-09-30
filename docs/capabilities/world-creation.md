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
reconstruct or place scene geometry. A world can also be made from the person's reviewed
photographs ([scene reconstruction](scene-reconstruction.md)), or generated as a town from a
specification. World menu, Make a world, offers the presets of the [world recipe
catalog](../../assets/catalogs/world-recipes/world-recipe.v2.json), a small town two 128 m tiles
long and a market town three long, and lets a person change a preset's values within the ranges the
[world specification](../../assets/catalogs/world-recipes/world-specification.v1.json) states: how
many tiles long the town is, how far apart its cross streets are, and the fewest and most storeys of
its buildings, each with its unit, a plain label and the measurement that set its range. The server
serves that schema, the same document the page renders (`GET /worlds/specification`), and holds
every value asked for to it before anything is generated
([`exulanica/world/world_recipes.py`](../../exulanica/world/world_recipes.py)): a value the schema
does not offer, one outside its range, and two values the schema says do not go together (a town two
tiles long needs cross streets at most 120 m apart, and one three tiles long at least 130 m) are
each refused by name with the range broken, and the page offers only what the schema allows. The
server generates the town from the city grammar for the world's own identity (`POST
/worlds/generated`,
[`exulanica/world/generated_worlds.py`](../../exulanica/world/generated_worlds.py)), keeping a seed
candidate only if its homes hold a society that can start, saves it with a receipt of how, and bakes
its tiles off the request. The application draws the town once its tiles are baked ([generated tile
runtime](../generated-tile-runtime.md#73-a-saved-worlds-own-tiles)), with its people walking from
tile to tile and its vehicles driving its streets ([served
traffic](../traffic-contract.md#served-traffic)). A generated world takes no photographs, and a
workspace holds at most three. Every kind of saved world can host people, whose choices the world's
owner can hand to open models ([people and models in a world](simulation.md)).

The largest town is three tiles long and one deep, and the schema states why for each bound.
Traffic refused all 23 towns two tiles deep that were measured, most of them for junctions whose
every approach has priority; towns four tiles long held more people than a town's society ground
admits; and the specification states the town's tick budget, 200 ms at the 95th percentile, a tenth
of the fastest play interval, within which one tick of the most people the ground admits took
171 ms on the largest walking graph the schema allows. Each bound is a range in the served schema,
so a larger town is a later version of it, waiting on what its bounds name: a society whose tick
holds more people within that budget, or a larger budget for a host that runs outside the
application's process, and a city grammar version whose towns two tiles deep lay junctions traffic
can drive.

A person can also describe the town they want in their own words: Make a world, Describe it. An
open model reads the specification the server serves and drafts a preset and values from the words
(`POST /worlds/specification/drafts`,
[`exulanica/selection/world_drafting.py`](../../exulanica/selection/world_drafting.py)). The server
checks them with the gate a person's own values pass, generates one sample town of them off the
request and says what it holds (its people, vehicles, streets and premises, labelled a sample,
because a town made from the same values draws its own identity), and names each part of the words
no value can say in the person's own words. "Use these values" puts them in the panel's controls,
where the person can change any of them; nothing is made until they make the town. A description
that asks for nothing a town can be is refused in words, with the values a town here is set by. An
agent calling the API receives the same proposal. The drafting model was chosen by a pre-registered
comparison ([record](../evaluation/2026-09-29-world-drafting-models-v2.json)).

Reviewed appearance controls and bounded language-driven appearance proposals
have preview/apply/rollback contracts. Source snapshots, alternate versions,
authored object add/move/remove/undo, bounded motion and reload/conflict recovery
have code and synthetic browser checks; the [object contract](../world-objects-contract.md) owns
them. These checks do not prove the complete saved-world journey or visual quality.

A person furnishes a world from the
[world object catalog](../../assets/catalogs/world-objects/world-object.v2.json), read by
[`exulanica/world/object_catalog.py`](../../exulanica/world/object_catalog.py): the three grey
markers, and a bench, a cafe table with two chairs, a tree in a planter, a lamp post, a market stall
and a planter seat. Each kind states its title and summary, its dimensions, the recipe its mesh is
generated from ([`exulanica/world/assets.py`](../../exulanica/world/assets.py)) and the CC0 texture
sets it is drawn in, whose maps travel inside its container at 256 texels a side; each number in a
recipe cites the street furniture catalog or a declared measurement. The Create panel lists every
kind by its title, with the chosen kind's summary under the choice and, under that, what inhabitants
do there, built only from the server's row for the kind: how many come at a time, what they do and
for how long, or that nobody uses it, as with a lamp post
([`objectUseWords`](../../web/packages/app/src/ui/object-placement.ts)). Inhabitants rest at the benches,
the planter seat and the cafe table and stop at the tree and the stall, in rows along the sides each
kind names, spaced so that turning an object never crowds two of them together; a lamp post stands
in their way and offers nothing to do. A resting person is drawn sitting on the seat of the bench,
the chair or the ledge their place has, and a visitor faces the stall's counter or the tree.

In the Create panel, "Place a small square before me" asks for the
[small square](../../assets/catalogs/world-objects/world-arrangement.v1.json): a tree between two
benches, with a market stall, a planter seat and a cafe table behind it and a lamp post at each front
corner, in front of the person and facing them. The server works out where each object goes from
where the person stands and faces, shows it before anything is written, and applies it as ordinary
object edits, one change each, so "Take back the last change" removes them one at a time, newest
first; nothing takes back the whole square in one step. In a world made from photographs it
stands on the floor declared in the region the person stands in. It is refused by name, and
nothing is written, when the world has no authored ground or declared floor there, when part of it
would stand past the edge of the ground people walk on or where people arrive, or when an object
already stands there or where people stand to use one
([`exulanica/world/arrangements.py`](../../exulanica/world/arrangements.py)).
It brings nobody in. Measured on 2026-09-24 with the deterministic
[`scripts/measure_furniture_use.py`](../../scripts/measure_furniture_use.py) (12 seeds, 30 simulated
minutes, eight inhabitants on the starter ground, the square before its arrival point), inhabitants
used 5.75 of the square's six usable objects per seed on average, against 5.17 of six when each
object is the marker of the same use at the same place.

The owned Flatiron district, built from admitted New York open data, appears only in the
development preview. Its source data and the line between source facts and renderer completion are
specified in [owned district and source admission](../owned-district-and-admission.md).

## Gaps

A generated town is one tile deep and at most three long, and its streets and uses are mixed as
version 4 of the city grammar mixes them: no value sets how many of its streets are high streets or
what share of its buildings are homes, shops or workplaces, because the specification offers no such
value, although version 5 of the grammar declares them ([generator system](../grammar-package.md#7-the-city-stages)).
A town two tiles long takes cross streets at most 120 m apart, a rule measured when the tessellator
refused a tile that did not carry the kerb a straight kerb it owns runs on into beyond the tile's
64 m margin; the tessellator draws such a straight join without that kerb, and a later version of the
specification lifts the rule. Its people follow the purposeful routine (visiting shops,
resting on benches, standing and talking), not the living society's homes and shifts. Traffic drove
20 of 20 small towns and 17 of 20 market towns measured; a town whose roads it cannot drive is still
made, without vehicles, and the page says why by the refusal's name. A town's people are compared
from the Compare view, a model deciding for a group of them within the most a comparison lets it
([what a comparison can read](../society-experiments.md#running-a-comparison)). The page still
offers Add photos in a generated world, which the server refuses by name.

A description sets only the values the specification offers; a street or shop mix, water, hills,
a particular building or a value past its range is named back as not in the town rather than
approximated. The sample's counts describe one town of the values, not the town a person makes, and
the drafting model's choice rests on twelve fixed descriptions of one specification.

Reusable real-world extraction, persistent geographic anchors, unified search
across memories/imports/creations, geometric blending and general language-driven
asset creation require the extensions in the
[composition contract](../world-composition-contract.md). A segmentation mask is
not automatically a complete editable object, and a map's display permission is
not permission to extract and remix its content.

Read [product direction](../product-direction.md) for delivery order, the
[appearance contract](../atlas-world-customization-contract.md) for supported
style operations, and the [World Memory Package](../world-memory-package.md) for
portable-state boundaries. Package verification alone does not load a
runnable world in another application.
