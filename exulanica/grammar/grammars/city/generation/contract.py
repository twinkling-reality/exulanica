"""The contract the city generators consume, written down before the first generator.

Read from main at 2efdaedf on 2026-09-17, by reading the files named below rather than any
report of them. Where this module and one of those files disagree, the file wins and this module
is wrong; a generator never restates a number that a file already states, it imports or reads it.

1. THE CITY GRAMMAR, VERSION 2 (``exulanica/grammar/grammars/city/``)
=====================================================================

**What a generator is.** A stage of ``CITY_GRAMMAR`` whose ``emit(context)`` returns a
``StageEmission`` with status ``emitted`` and records, each validated by the stage's own
validators before canonical JSON digests it (``exulanica.grammar.contract.generate``). A stage
reads only its ``StageContext``: the city seed, the stage id, the resolved parameters, the
emissions of earlier stages, and the admitted city identity every record identity derives from.
Nothing else reaches it: no clock, no environment, no random source, no float, no true division
and no power operator anywhere in ``exulanica/grammar`` (``tests/test_grammar_draw.py`` scans the
source).

**Draws.** ``context.cursor(name)`` draws in ``city.<stage_id>.<name>``; a generator names one
domain per decision, so adding a decision never moves an earlier value. A bounded draw is
``minimum + (n * span >> 64)`` with a span of at most 2**32. A raw 64-bit draw never enters a
record.

**Identity.** ``context.identity(kind, owner, ordinal)`` is uuid5 over the grammar id, the city
identity, the subject kind, the owner identity and the ordinal. The owner and ordinal of every
kind are its shape's ``IdentityRule``; a side (``SIDE_CODES``) and a surface role
(``SURFACE_ROLE_CODES``) stand in for ordinals by their append-only codes.

**Parameters.** 72 are declared in ``city.v2.json``, each with a unit, a cascade level (city,
district, block, lot, building, face), the one stage that reads it, a vocabulary and a basis.
``driving_side`` is ``required``; the other 71 are ``derive``: unset, the reading stage derives a
value per subject within the declared range and the record states it. A binding sets a parameter
at its own level or a coarser one, one binding per level for the whole city, so a binding is a
city-wide statement, never a per-subject one. Only ``city.facade`` carries its parameters as
``ParameterBinding`` rows (every facade parameter, sorted, with its value and source); every other
record states the derived value in its own field.

**Records emitted, by stage.** Every kind below has a shape (fields, bounds, closed values, named
rules, identity rule, extent field) in the stage module named, and the whole table as data is
``tests/fixtures/city-v2/record-shapes.json``.

=============  ==================================================================================
terrain        ``city.terrain``: one patch per tile, exact slope field, extent exactly the tile.
districts      ``city.district``: boundary ring and ``driving_side``.
streets        ``city.street_node``, ``city.street``, ``city.street_segment``, ``city.block``,
               ``city.curb_edge``, ``city.crossing``, ``city.lane``, ``city.junction``,
               ``city.junction_approach``, ``city.lane_connection``, ``city.signal``,
               ``city.parking_space``, ``city.road_marking``.
parcels        ``city.parcel``: every lot with at least one frontage; ``memory_precinct`` lots.
massing        ``city.massing`` (tiers, storeys, roof form), ``city.rooftop_object``.
facade         ``city.facade`` (the six section 5.1 fields first), ``city.ground_bay``,
               ``city.entrance``.
material       ``city.surface_material``: one per dressed (surface, role).
streetlife     ``city.street_furniture``, ``city.street_tree``.
vitrine        ``city.vitrine``: 600 to 1500 mm deep, wholly behind glazing panels.
premises       ``city.premises``: use class, sign key and text, bays, entrances.
tile           ``city.tile``: the inputs a bake is keyed on. Not a generated subject.
=============  ==================================================================================

**Frame and units.** ``city_local``: x east, y north, z up, integer millimetres, datum z,
``metric_authored``. Rings counter-clockwise and not closed. A direction is an integer vector
with components within 1,000,000; the one angle is a texture rotation in microradians.
Proportions in millionths. Optional values are tuples of at most one item.

**What the tile document holds a generator's output to** (``document.validate_city_document``):
every record's own validator; references resolve to a carried record or an ``external`` entry of an
admitted kind; identities are their rule's derivation; catalog keys resolve and mean what the
record says (typology eras and roof families, era storey heights and cornice, roof family form,
rise and parapet, lane use widths, crossing type widths and signal, junction control and
approaches, parking kind sizes, fitout use classes, sign use class and text, typology ground and
upper floor uses); segment ends on their nodes; curb graph and corner radius (tangent points find
one centre within 2 mm); frontage line (a straight kerb piece lies ``kerb_width + footway_width``
from its block's ring, within 2 mm); camber (a level segment's kerb lines lie the camber's fall
below the crown); lanes and gutters sum to the carriageway width; stop lines outside crossing
bands; parcels in blocks, footprints in parcels, frontage curbs on the parcel's block; a facade
on every tier edge, run equal to the edge's, storeys equal to the tier's, ground band equal to the
ground storey, bays and margins summing to the run, one ground bay record per bay, openings equal
to the stated parameters; a party wall's vertices on its lot line; the era's cornice rule on top
frontage faces; entrances inside a door panel, threshold on the face at the building's base;
materials of the catalog's set, of a role the material dresses, modules scaled, every facade with
a wall material of its era; furniture and trees outside every footprint, outside crossing
extents, exclusion circles apart, kerb offsets within the class; vitrine parts from the fitout,
moved along the run only, inside the box; premises storeys within the building and signage as its
use class requires. Membership: owned by the anchor's tile, halo when the extent meets the tile
grown by 64 m; an owner-anchored record's extent lies inside its owner's in plan.

**Not enforced by the document check, and owed by the generators:** ``city_reference_closure``
(every external identity of every tile is carried by some tile of the same city), and segment
pieces no longer than 1 km (tess's facing limit).

**Catalogs** (``assets/catalogs``, loaded by ``load_city_catalogs``, digested with the texture
pins by ``catalog_digest``): 18 files, 124 entries. The generators draw keys from them and resolve
every shape a key stands for (furniture, rooftop object and fitout parts, roof family form) into
the record; a reader never looks a shape up by a key.

**The tile and its key** (``tile.py``, ``exulanica/ingest/stages/__init__.py``).
``tile_inputs_digest`` is SHA-256 over the canonical ``city.tile`` payload: the city seed, the
grammar pins (id, version, descriptor SHA-256), the catalog digest, the tile coordinate, the level
of detail, the 128 m tile, the 64 m halo, the ownership and halo rules, and ``edit_delta_digest``.
``edit_delta_digest_of`` folds an ordered edit subsequence (32-byte digests, in log order, not
sorted) into that field; the empty subsequence is ``EMPTY_EDIT_DELTA_DIGEST``. ``baked_tile_id``
is ``uuid5(ARTIFACT_NAMESPACE, "baked_tile:<version>:<params digest>:<tile_inputs_digest>")``.

2. THE TESSELLATOR (``web/packages/loom-tess``, stage ``baked_tile`` version 3)
==============================================================================

**Container** ``owd/3``, magic ``OWD3``: canonical JSON header (tile record and inputs digest,
grammars with pins, frame, subject identity and externals, every record with digest, identity and
membership, per projection its contract, triangle digest, origins, counts and entries), then per
projection int32 millimetre positions, float32 metre positions, int32 surface coordinates
(``render_batch`` only) and uint32 indices. Triangle digest
``exulanica.owd-triangle-digest/v3``. Projections materialised: ``render_batch`` and
``nav_envelope``; ``collision_proxy`` and ``pick_geometry`` have no contract yet. Level of detail
0 only. A drawn ``render_batch`` entry is a list of surfaces, each one grammar surface role, one
material (the ``city.surface_material`` for that record and role, or ``none-exists``) and one
orientation. Owned records are drawn; halo records are context and draw nothing.

**The bake is keyed and deterministic.** The Node CLI (``pnpm tess bake <document> <out>``) is the
bake; the browser build is a preview held to the same triangle digest. Two bakes under one
``baked_tile_id`` that differ are a fault; the table that records that fault is migration 0072,
this lane's.

**What draws on main:** terrain only (whole patch in ``render_batch`` as ``none-exists``;
``nav_envelope`` keeps each cell whose square meets no carried record's extent grown by the
capsule radius). Every other kind states the rule it waits on (``NEEDS`` in ``expand.ts``).

**Built and not wired** (``lane/tess-expanders`` at d3196a15): straight street rules only (a
centreline or kerb line of more than one piece draws nothing and needs ``bent_street``); a
junction's carriageway fill over each leg's strip mouth, kerb lines back to the node and corner
arcs, needing every leg's segment, curbs and node carried; the support clearance rule, carving
support triangles away from obstruction boxes grown by the capsule radius. Expander order, the
corridor's: terrain; street surfaces with kerbs and crossings; massing and facades with bays and
openings; furniture, trees, vitrines and rooftop objects. Tess waits on two grammar rules from
this lane: corner ownership, and navigation classification per record kind as data.

3. THE TILE RUNTIME (``atlas-react`` generated-tile, ``docs/generated-tile-runtime.md``)
=======================================================================================

Loads an ``owd/3`` container through ``verifyOwd`` (a full rebake of the header's records; no
second reader), refuses a frame other than ``city_local``, draws only ``render_batch`` drawn
entries, one draw per texture set plus one for every unavailable surface, by the UV rule
``u = (cos(theta) s - sin(theta) t + offset_u) / repeat_u`` with
``repeat = extent_mm * repeat_size_millionths / 10**6``, and stands the player on
``nav_envelope`` with the grammar's capsule (radius 340 mm, height 1900 mm, eye 1620 mm), support
resampled every 50 mm. The development route ``?preview=1&tile=<name>`` reads only the pinned
goldens in ``web/packages/app/src/dev/tiles``; baked corridor tiles are not repository files and
reach it only through the permission-gated route this lane declares, which the runtime lane wires.
The look is ``TILE_LOOK_V1`` in ``look.ts`` (fog onset 40 to 60 m enforced, environment probe and
contact shadow with no off switch); this lane may change its values only, with a version bump per
change, through ``validateTileLook``.

4. TEXTURES (``assets/textures/manifest.json``, ``docs/texture-package.md``)
===========================================================================

Seventeen published sets, each with a pinned SHA-256 (migrations 0065 and 0078): thirteen of class
``opaque`` (``cc0.brick-running-bond`` 1800 mm, ``cc0.carriageway-asphalt`` 2000,
``cc0.cast-concrete`` 2400, ``cc0.footway-paving`` 1800, ``cc0.kerb-stone`` 1800 by 450,
``cc0.limestone-ashlar`` 2400, ``cc0.painted-render`` 2000, ``cc0.painted-timber`` 1000,
``cc0.awning-canvas`` 1000, ``cc0.sign-panel`` 1000, ``cc0.storefront-metal`` 1000,
``cc0.tree-bark`` 1000, ``cc0.tree-pit-soil`` 900), ``cc0.float-glazing`` (class ``glazing``,
2000), ``cc0.broadleaf-foliage`` (class ``cutout``, 2000) and two of class ``decal``,
``cc0.road-paint-white`` and ``cc0.road-paint-yellow`` (1000 by 250). The material catalog
(``material.v4.json``) holds sixteen of them, each entry naming the surface roles it dresses and
whether its texture runs one way. Two of those sixteen are not reached by any record this grammar
makes today: ``cc0.road-paint-yellow`` dresses a lane marking, and ``cc0.road-paint-white`` dresses
one too besides the crossing band it paints, and no stage emits a marking record yet.
``cc0.sign-panel`` has no entry at all, because no surface role names a sign panel until the
lettering lane's records do. Terrain is now the only role no published set dresses, so a terrain
surface is the only one that carries no material record and draws as the stated unavailable
surface. Budget: 168 MB decoded texture per corridor; one 1024 set is 16,777,212 bytes as the
runtime uploads it.

5. THE VISUAL GATE (``docs/visual-gate-rubric.md`` version 5, key set
``exulanica.visual-gate-keys/v5``)
====================================================================

Nine keys: ``continuousTexturedStreetAndFacades``, ``readsAsInhabitedStreet``,
``noCutsOrFloatingGeometry``, ``usefulEyeLevelMovement``, ``completeCapsuleClearanceVerification``,
``practicalBrowserBudget``, ``companionPresent``, ``reticlePresent``,
``authenticatedShellAndAuthoredHandlersPreserved``. ``readsAsInhabitedStreet`` is judged by the
named human judge alone, one picture at a time (start, midpoint, endpoint of a route of about
125 m), with one question; the first no decides it, and a corridor passes only with three picked
yeses plus every mechanical key. The Flatiron baseline record
(``docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json``) is FAIL:
``continuousTexturedStreetAndFacades``, ``readsAsInhabitedStreet`` and
``noCutsOrFloatingGeometry`` false, the other six true. Thresholds this lane builds to: eye
1620 mm, capsule 340 mm by 1900 mm, step 180 mm, slope 12 degrees, support samples 50 mm apart,
route 125 m with at least 120 m walked and at most 340 mm lateral deviation. Melbourne's envelope:
227,173 drawn triangles, 28,247,006 transferred bytes, 167,772,160 decoded texture bytes, 87 draw
calls, 16.7 ms p95. The harness refuses any page whose title is not the product title, so it
cannot score the development tile route; that change belongs to a neutral lane.

**What the gate asks of generated records, read plainly.** Every drawn walking-surface and facade
triangle textured: a glazing, door or marking surface drawn unavailable fails
``continuousTexturedStreetAndFacades`` until its texture class renders. Every building exterior
ring edge has drawn geometry within 50 mm of its midpoint at 1 m above support. No drawn triangle
inside a building volume, so everything behind glass must be closed.

6. GAPS NAMED, AND WHERE EACH WAS ANSWERED
==========================================

* No declared parameter bounded how far a generation reaches. Answered on 2026-09-17:
  ``city_extent_x_mm`` and ``city_extent_y_mm`` (city level, read by terrain, whole tiles) and
  ``block_depth_mm`` (district level, read by streets) were added to the descriptor.
* The corner a curb's radius makes (``corners.py``: ``[curb_extent]``, ``[corner_extent]``,
  ``[junction_extent]``) and what each record kind is to a person walking (the descriptor's
  ``navigation`` table, ``[facade_clearance]``, ``[canopy_clearance]``) were stated first, for tess.
* Surface roles 25 ``canopy`` and 26 ``trunk`` were appended for a street tree's parts.
* What ``soiling_gradient_millionths`` means on glass, and how far the film reaches, were answered
  on 2026-09-17: ``surface_material`` version 2 carries ``soil_band_bottom_mm`` and
  ``soil_band_edge_mm``, stated on a glazing surface and 0 on every other role, and
  ``glazing_soil_band_bottom_mm`` and ``glazing_soil_band_edge_mm`` are derived per building. The
  record version was amended in place rather than raised, which is honest only while nothing is
  stored under it: the first bake recorded through migration 0072 freezes city version 2.
* Still open: what lies behind glazing above the ground storey; the role-to-material-class table;
  ``city_reference_closure`` over a whole generated city; segment pieces no longer than 1 km.
* A signal names traffic's signal-plan catalog by SHA-256, which the city grammar never reads, so
  the corridor's junctions are unsignalised (stop and priority controls, zebra crossings) until
  that catalog is on main.
"""

from __future__ import annotations
