# Scene reconstruction

Build 3D places from photographs of a real place: one way to build a world.

Reconstruction and authoring from the catalogs are independent ways to build a world; neither
depends on the other. A reconstructed place stays linked to the photographs it came from, and
rendered geometry does not establish historical facts.

## Making a world from your photographs

1. Add photographs from inside the world, or upload them to `POST /intake`. Each is admitted under
   the rights the person grants, and a human review decides which are eligible
   ([personal admission](../personal-admission.md)).
2. Choose **Make a world from my photographs**, offered in the photo drawer and under the list of
   saved worlds. The server chooses the reviewed photographs, joins the ones that show the same place
   into one region per place, and opens the new saved world. A reviewed photograph that belongs to
   no scene group is left out and counted, and every refusal is shown by name
   ([which photographs a world is composed from](../saved-world-entry.md#which-photographs-a-personal-source-world-is-composed-from)).
3. Photographs reviewed later join the world's places only after the person confirms a preview of
   what they add and what the world keeps
   ([adding photographs to a made world](../saved-world-entry.md#adding-photographs-to-a-made-world)).
4. Each region is drawn with a declared floor about 24 metres across, which placed objects and the
   small square stand on. The world's people live on the floor of one region, and the world's owner
   can choose the models that decide for them ([people and models in a world](simulation.md)).

## What reconstruction recovers

Intake supports still images. Reconstruction quality and available movement depend on source
coverage and the resulting artifact. Broader media support is separate work.

Single-image depth produces a partial surface, not a complete explorable place. Multi-image pose
recovery and scene-specific Gaussian training exist, with retained scene evidence; their presence
does not prove coherent coverage for a new source set. Training a scene is distinct from training
or integrating a general world-generation model. A usable place needs an actual source-to-viewer
demonstration and visual acceptance.

Several photographs taken from about one spot, turning between shots, join into one view you can
look around in from where you stood. The turns between them are measured from the photographs, each
one keeps its own depth estimate, and the join is refused by name when the photographs were taken
metres apart, overlap too little, or show a changed scene. You cannot walk round to the far side of
anything, the result has no measured metric scale, and a photograph whose file does not state its
lens stays a separate photograph. Stepping away from where you stood flattens the view towards a
print rather than stretching it. The joined view is drawn in a saved world made from your own
sources; a starter world does not draw photographs as places. See
[photographs joined from one standpoint](../scene-reconstruction-operations.md#photographs-joined-from-one-standpoint).

Reconstruction does not fill what the camera never saw. A model may not invent a walkable floor,
an unseen back, or a completed room and present it as recovered geometry; the declared floor a
region is drawn with is a floor the world declares, never a photograph posing as ground. Generated
receipts can exist as labeled, non-citable metadata; the renderer does not draw those bytes as the
place. The [quality gate](../scene-reconstruction-operations.md#5-quality-gate-and-recorded-rung) defines validation. The decision
and rejected alternatives are in [adr/0008-generated-geometry.md](../adr/0008-generated-geometry.md).

See [reconstruction operations](../scene-reconstruction-operations.md),
[identity and evidence](../domain-and-evidence-model.md), and
[product direction](../product-direction.md).
