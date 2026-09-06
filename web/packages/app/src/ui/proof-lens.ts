/**
 * The proof lens, on the app's side of the renderer boundary.
 *
 * `@exulanica/presentation` decides two things and this file decides neither: which tier a region
 * is showing (`proofTierOf`) and what colour a tier wears (`proofLensPalette`, four RGBA rows
 * indexed by `proofTierIndex`). What is left, and it is all that is left, is joining those to the
 * regions the renderer knows about and handing the result across as numbers.
 *
 * WHY THE JOIN IS HERE AND NOT IN THE BINDING. The renderer knows which islands exist and which
 * geometry loaded; it does not know which scene a region chose to draw, whether another scene over
 * the same photographs was passed over, or whether a model generated any of it. Those are graph
 * facts, and the app is the one place that holds the graph, the theme and the renderer at once.
 * Pushing the tier decision down would mean teaching `atlas-react` about scenes and generations,
 * which is exactly what `pnpm boundaries` and ADR-0003 exist to prevent.
 *
 * WHAT THIS FILE MUST NEVER DO is change anything. `proofLensIslandColors` is a pure function of
 * its arguments: it reads the rung disclosures and returns a map. It writes no scene, promotes no
 * rung, and touches no receipt, which is what makes the lens a way of looking rather than a claim.
 * `test/proof-lens-toggle.test.ts` asserts that by toggling and comparing.
 */

import type { IslandId } from '@exulanica/atlas-core';
import type { ProofLensColor } from '@exulanica/atlas-react/playcanvas';
import {
  proofLensPalette,
  proofTierIndex,
  proofTierOf,
  type PresentationTheme,
  type ProofTier,
} from '@exulanica/presentation';
import type { ReconstructionRungDisclosure } from './status.js';

/** Which region draws which scene, as the app already resolved it for the loader. */
export type IslandOfScene = (sceneId: string) => IslandId | undefined;

/**
 * The tier one scene is showing, from exactly the fields the status panel's sentence reads.
 *
 * One function, called by both, so the colour in the world and the words in the panel cannot come
 * apart: `proofTierDisclosure` in `status.ts` calls `proofTierOf` on the same three fields.
 */
export function proofTierForScene(scene: ReconstructionRungDisclosure): ProofTier {
  return proofTierOf({
    substrate: scene.renderingSubstrate,
    drawn: scene.drawn ?? true,
    showingGenerated: scene.showingGenerated ?? false,
  });
}

/**
 * One resolved RGBA per region, for `AtlasBinding.setProofLens`.
 *
 * A scene whose region cannot be resolved contributes nothing rather than a default: the binding
 * leaves an island the map omits uncoloured, and an uncoloured island is the honest state for a
 * region this build cannot connect to a scene at all.
 *
 * When two current scenes name the same region, the drawn one wins. That is not a tie-break for
 * neatness: the not-drawn scene's tier is `unavailable`, and letting it overwrite the region that
 * is actually drawing reconstruction would make the lens report an absence over a present surface.
 */
export function proofLensIslandColors(
  scenes: readonly ReconstructionRungDisclosure[],
  islandOf: IslandOfScene,
  theme: PresentationTheme,
): ReadonlyMap<IslandId, ProofLensColor> {
  const palette = proofLensPalette(theme);
  const colors = new Map<IslandId, ProofLensColor>();
  const drawnIslands = new Set<IslandId>();
  for (const scene of scenes) {
    const islandId = islandOf(scene.sceneId);
    if (islandId === undefined) continue;
    const drawn = scene.drawn ?? true;
    if (!drawn && drawnIslands.has(islandId)) continue;
    if (drawn) drawnIslands.add(islandId);
    const row = proofTierIndex(proofTierForScene(scene)) * 4;
    colors.set(islandId, Object.freeze([
      palette[row]!,
      palette[row + 1]!,
      palette[row + 2]!,
      palette[row + 3]!,
    ]) as ProofLensColor);
  }
  return colors;
}
