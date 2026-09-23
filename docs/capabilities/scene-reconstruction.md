# Scene reconstruction

Build 3D places from the media associated with your experiences.

Reconstruction is one way to supply places for a personal world; authored and synthetic creation
are independent paths. Names confirmed by the user
connect people and objects across experiences. Reconstruction remains linked to its source;
rendered geometry does not establish historical facts.

## Implementation

Intake supports still images. Reconstruction quality and available movement depend
on source coverage and the resulting artifact. Broader media support is separate work.

Single-image depth produces a partial surface, not a complete explorable place. Multi-image pose
recovery and scene-specific Gaussian training exist, with retained scene evidence; their presence
does not prove coherent coverage for a new source set. Training a scene is distinct from training
or integrating a general world-generation model. The usable-place demonstration
requires an actual source-to-viewer demonstration and visual acceptance.

Reconstruction does not fill what the camera never saw. A model may not invent a walkable floor,
an unseen back, or a completed room and present it as recovered geometry. Generated receipts can
exist as labeled, non-citable metadata; the renderer does not draw those bytes as the place.
The [quality contract](../reconstruction-quality-gate.md) defines validation. The decision and
rejected alternatives are in [adr/0008-generated-geometry.md](../adr/0008-generated-geometry.md).

See [reconstruction operations](../scene-reconstruction-operations.md),
[identity and evidence](../domain-and-evidence-model.md), and the
[product roadmap](../product-direction.md).
