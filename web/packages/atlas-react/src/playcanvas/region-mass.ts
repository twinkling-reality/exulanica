/**
 * What a region looks like from above.
 *
 * The Atlas Map has always been the right camera and an empty picture. It is the same scene at a
 * 55 degree vantage, exactly as `interaction-model.md` 6.2 specifies, but a region had no vertical
 * form, so an oblique view of four flat placements showed a flat plane with four labels on it. The
 * angle was never the problem; there was nothing up there to see.
 *
 * The obvious fix is a plinth or a platform under each region, and the retired
 * `atlas-visual-language.md` 4 (revision 47f9f7d3; `atlas-spatial-architecture.md` 2 keeps
 * the rule)
 * rejects exactly that, correctly: a disc under a memory is scenery, it asserts an edge the data
 * does not have, and it makes the Map a diagram of the renderer rather than of the person's life.
 *
 * So the mass is not a container for the evidence. **It is the evidence.** One standing mark per
 * anchor, at the anchor's own position, converted through the single legal local-to-atlas
 * conversion. A region holding three detections is three marks; one holding two hundred is a
 * dense block you can read from altitude. Height carries link state and colour carries provenance,
 * which are the two things the semantic dictionary already says those channels mean, so nothing
 * here is decoration standing in for knowledge. The count is the shape.
 *
 * It exists only at the Map vantage. From the ground the same anchors are already the entity
 * glyphs and the source apertures, and a second standing copy of them would be the duplicate
 * readable body that composition rule 2 forbids.
 */

import * as pc from 'playcanvas';
import { atlasMapPose, localToAtlas, type AtlasScene, type IslandId } from '@exulanica/atlas-core';
import type { WorldArtProfile } from '@exulanica/presentation';

export interface RegionMass {
  readonly entity: pc.Entity;
  setMapActive(active: boolean): void;
  applyProfile(profile: WorldArtProfile): void;
  destroy(): void;
}

/**
 * How tall a mark stands, as a fraction of the Map's own altitude.
 *
 * Not a fixed number of atlas units. `atlasMapPose` climbs to one and a half times the spread of
 * the world, so a library of four regions is viewed from 28 units and a wider one from 557, and
 * anything authored in absolute units is either a skyline in the first or a single pixel in the
 * second. It was a single pixel: the geometry was correct, in the frustum, in the right layer and
 * facing the camera, and invisible, which is the most expensive kind of correct. Sizing from the
 * vantage means a mark subtends the same angle in any world.
 *
 * Confirmed evidence stands full height and unresolved evidence stands short, so a region that is
 * mostly guesses looks unfinished from above, which is true.
 */
const MARK_HEIGHT_OF_ALTITUDE = 0.13;
const MARK_WIDTH_OF_HEIGHT = 0.34;
const UNRESOLVED_SCALE = 0.48;

/**
 * How wide a region's cluster is allowed to spread at the Map vantage.
 *
 * A region is about three units across and the layout puts regions hundreds of units apart, so at
 * the altitude that fits the whole world a region is a point and its evidence is one smudge behind
 * its own label. `interaction-model.md` 6.2 makes the Map a representation tier override rather
 * than a camera move, and this is that override: the arrangement of a region's evidence is kept
 * exactly and only its scale is opened up, so the cluster reads as a mass without any mark moving
 * relative to its neighbours. Nothing here changes a position anything else uses; the ground view
 * draws the same anchors at their own spacing.
 */
const CLUSTER_SPREAD_OF_ALTITUDE = 0.14;

/**
 * Provenance is hue plus shape, so the mass takes its colour from the derived provenance roles.
 *
 * The reading-strength roles rather than the mark-strength ones. Mark strength exists to keep a
 * small dot on a plate bright, and it is the wrong register for a solid form standing on a pale
 * field at distance: `captureMark` is a light grey-green, most anchors are capture provenance, and
 * the whole map came out the colour of the ground it stood on.
 */
const PROVENANCE_ROLE = Object.freeze({
  user: 'user',
  capture: 'capture',
  inference: 'inference',
  external: 'external',
} as const);

type ProvenanceKey = keyof typeof PROVENANCE_ROLE;

const provenanceKey = (value: string): ProvenanceKey =>
  (value === 'user' || value === 'capture' || value === 'inference' || value === 'external'
    ? value
    : 'inference');

/**
 * Build the mass. It stays enabled for the life of the scene and hides per mesh instance.
 *
 * Not by toggling the entity. A render component created under a disabled entity never registers
 * its mesh instances with a layer, and enabling it afterwards does not register them either: the
 * geometry exists, the scene graph reads correctly, the counts are right, and nothing draws. The
 * mirror of that is equally quiet, so `enabled` is left alone entirely and visibility is switched
 * on the instances, which is independent of layer membership.
 */
export function createRegionMass(
  device: pc.GraphicsDevice,
  scene: AtlasScene,
  profile: WorldArtProfile,
  /**
   * Regions already drawn as measured relief by `region-relief.ts`.
   *
   * They are skipped rather than drawn underneath. Composition rule 2 forbids a duplicate
   * readable body, and a stack of marks standing inside the surface those same detections were
   * recovered from is exactly that: one region saying its own size twice, in two vocabularies,
   * at the same vantage.
   */
  reconstructed: ReadonlySet<IslandId> = new Set(),
): RegionMass {
  const altitude = atlasMapPose(scene).position.y;
  const markHeight = altitude * MARK_HEIGHT_OF_ALTITUDE;
  const markWidth = markHeight * MARK_WIDTH_OF_HEIGHT;
  const entity = new pc.Entity('atlas-region-mass');
  const instances: pc.MeshInstance[] = [];

  const mesh = pc.Mesh.fromGeometry(
    device,
    new pc.BoxGeometry({ halfExtents: new pc.Vec3(0.5, 0.5, 0.5) }),
  );
  const materials = new Map<ProvenanceKey, pc.StandardMaterial>();
  const materialFor = (key: ProvenanceKey): pc.StandardMaterial => {
    const existing = materials.get(key);
    if (existing !== undefined) return existing;
    const material = new pc.StandardMaterial();
    /*
     * Lit and matte. The scene's directional light lives outside the world environment the Map
     * hides, so a lit material is lit here too.
     */
    material.useLighting = true;
    material.gloss = 0;
    material.metalness = 0;
    // The Map's ambient is the same near-white the field is, so an ambient-lit mass comes out the
    // colour of the ground it stands on. Black ambient leaves the directional light to model the
    // form and the fill to carry the provenance hue.
    material.ambient = new pc.Color(0, 0, 0);
    /*
     * No fog.
     *
     * The world's fog is tuned for a person standing in the field and it begins early. The Map
     * looks at the whole Atlas from hundreds of units up, which is deep into full fog, so every
     * mass was blended almost entirely into the haze and arrived the colour of the sky. That is
     * why nothing about this material appeared to do anything: the fill was being replaced after
     * it was computed. Atmospheric perspective is a depth cue for a first-person view; a map is a
     * diagram and reads at one value.
     */
    material.useFog = false;
    materials.set(key, material);
    return material;
  };

  for (const island of scene.islands) {
    if (reconstructed.has(island.islandId)) continue;
    // One factor per region, from its own footprint, so a dense region and a sparse one open up
    // by the same amount and their relative sizes survive.
    const footprint = Math.max(0.5, island.footprintRadiusLocal * island.placement.scale);
    const spread = (altitude * CLUSTER_SPREAD_OF_ALTITUDE) / footprint;
    const centre = island.placement.position;
    for (const anchor of island.anchors) {
      // Rejected and revoked links are not evidence of anything and must not add mass.
      if (anchor.linkState === 'rejected' || anchor.linkState === 'revoked') continue;
      const key = provenanceKey(anchor.provenance);
      const at = localToAtlas(island.placement, anchor.local);
      const confirmed = anchor.linkState === 'confirmed';
      const height = markHeight * (confirmed ? 1 : UNRESOLVED_SCALE);
      const mark = new pc.Entity(`region-mass:${anchor.anchorId}`);
      // Grounded at y = 0 and standing up, so the top edge is the reading and the base is the
      // position. Anchors carry their own height in local space; the map is about where, not how
      // high, so the mark starts at the field.
      mark.setLocalPosition(
        centre.x + (at.x - centre.x) * spread,
        height / 2,
        centre.z + (at.z - centre.z) * spread,
      );
      mark.setLocalScale(markWidth, height, markWidth);
      const instance = new pc.MeshInstance(mesh, materialFor(key), mark);
      instance.castShadow = false;
      instance.receiveShadow = false;
      instance.visible = false;
      mark.addComponent('render', { meshInstances: [instance] });
      entity.addChild(mark);
      instances.push(instance);
    }
  }

  const applyProfile = (next: WorldArtProfile): void => {
    for (const [key, material] of materials) {
      const hex = next.ui.colors[PROVENANCE_ROLE[key]];
      const colour = new pc.Color();
      colour.fromString(hex);
      // Diffuse black so ambient cannot wash the fill out, and the colour carried entirely by
      // emissive. Held below 1 because the camera tone-maps, and a fully bright emissive under
      // ACES desaturates toward white, which is how a diagram loses the hue that is its content.
      material.diffuse = colour;
      material.emissive = colour;
      material.emissiveIntensity = 0.3;
      material.update();
    }
  };
  applyProfile(profile);

  return {
    entity,
    setMapActive(active) {
      for (const instance of instances) instance.visible = active;
    },
    applyProfile,
    destroy() {
      for (const material of materials.values()) material.destroy();
      materials.clear();
      mesh.destroy();
      entity.destroy();
    },
  };
}
