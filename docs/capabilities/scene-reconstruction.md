# Scene reconstruction

Build 3D places from the media associated with your experiences.

Reconstruction supplies the starting places in a personal world. Names confirmed by the user
connect people and objects across experiences. Reconstruction remains linked to its source;
rendered geometry does not establish historical facts.

## Implementation

The current intake supports still images. Reconstruction quality and available movement depend
on source coverage and the resulting artifact. Broader media support is separate work.

Single-image depth produces a partial surface, not a complete explorable place. Multi-image pose
recovery and scene-specific Gaussian training exist, with retained scene evidence; their presence
does not prove coherent coverage for a new source set. Training a scene is distinct from training
or integrating a general world-generation model. The roadmap's usable-place milestone still
requires an actual source-to-viewer demonstration and visual acceptance.

See [reconstruction operations](../scene-reconstruction-operations.md),
[identity and evidence](../domain-and-evidence-model.md), and the
[product roadmap](../product-direction.md).
