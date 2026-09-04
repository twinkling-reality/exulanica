/**
 * What an island is, who decides it, and what an island may honestly carry.
 *
 * **An island is decided here, not on the server.** ADR-0005 records that whether an island is
 * one capture or a place-on-a-trip cluster is OPEN "until the real distribution of the corpus has
 * been measured", so the server returns capture ids and a grouping, and this maps them through an
 * injectable function.
 *
 * THE CORPUS HAS NOW BEEN MEASURED, so the default has changed. 80 photographs across five visits
 * to three places cluster into five scene groups of sixteen. One island per capture would be 80
 * islands, and `solveLayout` refuses more than five and says why: "a force layout whose behaviour
 * was never examined above five islands should fail loudly rather than produce a plausible-looking
 * arrangement nobody has checked". One island per scene group is five. The default is therefore
 * the group, falling back to the capture for anything the grouping did not place, which is the
 * honest answer for a photograph with no usable clock.
 *
 * The function is still injectable and the server still ships no island id, so this remains one
 * argument to have rather than a server change, which is exactly what it was kept for.
 */

import type { IslandIdRef, IslandRecord, ReconstructionRungRef } from './read-model.js';
import { type GraphPayload, toMs } from './wire.js';

/** How a capture becomes an island. See the module comment on why this is a parameter. */
export type IslandOf = (captureId: string) => IslandIdRef;

/** One clustered region as the server sends it. Named here so the helpers below can take one. */
type SceneGroupPayload = GraphPayload['scene_groups'][number];

/**
 * The default: a capture belongs to the scene group that contains it, or stands alone.
 *
 * Built from the payload rather than being a constant, because the grouping is data the server
 * computed and the mapping cannot be known without it. A capture in no group becomes its own
 * island rather than being dropped or bundled into a nearby one: a photograph the clusterer could
 * not place is a real photograph, and hiding it would be losing evidence to a layout decision.
 */
export function groupIslands(payload: GraphPayload): IslandOf {
  const byCapture = new Map<string, IslandIdRef>();
  for (const group of payload.scene_groups) {
    for (const captureId of group.capture_ids) {
      byCapture.set(captureId, group.group_id as IslandIdRef);
    }
  }
  // An operator-authorized exact set can reconstruct photographs whose honest metadata did not
  // qualify for automatic scene grouping. When every member is still ungrouped, the immutable
  // reconstruction scene is their one durable shared identity. A partially grouped set remains
  // split instead of letting the reconstruction override a measured grouping decision.
  for (const scene of payload.reconstruction_scenes) {
    if (scene.members.some((member) => byCapture.has(member.capture_id))) continue;
    for (const member of scene.members) {
      byCapture.set(member.capture_id, scene.scene_id as IslandIdRef);
    }
  }
  return (captureId) => byCapture.get(captureId) ?? (captureId as IslandIdRef);
}

/**
 * The islands, built by putting EVERY capture the groups, entities or occurrences name through
 * the same `islandOf` the occurrences went through.
 *
 * Every capture rather than one per group, and that is the whole point of the loop below. A
 * caller that injected its own function gets islands that match its own occurrences; a set
 * derived independently from the payload, or from one representative member of each group, would
 * silently disagree with the anchors placed inside it, and the symptom would be an anchor
 * rendered in a region it does not belong to, or in no region at all.
 *
 * A group's measurements describe the whole group, so an island carries them only when it IS that
 * group: one group's captures, all of them, and no others. A caller whose function splits a group
 * across islands gets pieces that report no spread, no rung and their own occurrences' times,
 * because `radius_m`, `positioned_member_count` and the rung are aggregates over the members and
 * nothing measured a subset. That is the answer a capture the grouping never placed already gets.
 */
export function buildIslands(
  payload: GraphPayload,
  islandOf: IslandOf,
): readonly IslandRecord[] {
  const capturesByIsland = new Map<IslandIdRef, string[]>();
  const groupsByIsland = new Map<IslandIdRef, SceneGroupPayload[]>();
  const spanByIsland = new Map<IslandIdRef, { first: number | null; last: number | null }>();

  const place = (captureId: string): IslandIdRef => {
    const islandId = islandOf(captureId);
    const held = capturesByIsland.get(islandId);
    if (held === undefined) capturesByIsland.set(islandId, [captureId]);
    else if (!held.includes(captureId)) held.push(captureId);
    return islandId;
  };

  // An entity's capture list is also rendered as island ids. Include it even when a malformed or
  // partial payload omitted the occurrence row, or the entity would point at a region this list
  // says does not exist. It carries no capture time of its own, so such a region remains undated.
  for (const entity of payload.entities) {
    for (const captureId of entity.capture_ids) place(captureId);
  }

  for (const group of payload.scene_groups) {
    for (const captureId of group.capture_ids) {
      const islandId = place(captureId);
      const contributing = groupsByIsland.get(islandId);
      if (contributing === undefined) groupsByIsland.set(islandId, [group]);
      else if (!contributing.includes(group)) contributing.push(group);
    }
  }

  // Reconstruction-only workspaces can have no entities, occurrences, or automatic scene group.
  // Their capture set still has to enter the island list or the layout solver receives an empty
  // world before the authenticated geometry loader gets a chance to run.
  for (const scene of payload.reconstruction_scenes) {
    for (const member of scene.members) place(member.capture_id);
  }

  // The times a region carries when no single group speaks for it. They are the times its own
  // occurrences carry rather than a group's, and a capture with no usable clock contributes
  // nothing rather than the epoch.
  for (const row of payload.occurrences) {
    const islandId = place(row.capture_id);
    const span = spanByIsland.get(islandId);
    const atMs = toMs(row.captured_at);
    spanByIsland.set(islandId, {
      first: minOf(span?.first ?? null, atMs),
      last: maxOf(span?.last ?? null, atMs),
    });
  }

  const islands: IslandRecord[] = [];
  for (const [islandId, captureIds] of capturesByIsland) {
    const group = groupWhollyIn(groupsByIsland.get(islandId), captureIds, islandId, islandOf);
    const reconstruction = payload.reconstruction_scenes.find((scene) =>
      scene.members.length === captureIds.length
      && scene.members.every((member) => islandOf(member.capture_id) === islandId)
      && captureIds.every((captureId) => scene.members.some((member) => member.capture_id === captureId))
    );
    const reconstructionPresentation = reconstruction === undefined
      ? {
          recordedSceneRung: null,
          displayedRung: 4 as const,
          displayReasons: [] as readonly string[],
          renderingSubstrate: 'source_photographs' as const,
          reconstructionSceneId: null,
        }
      : {
          recordedSceneRung: asRung(reconstruction.recorded_rung),
          displayedRung: reconstruction.displayed_rung,
          displayReasons: reconstruction.display_reasons,
          renderingSubstrate: reconstruction.rendering_substrate,
          reconstructionSceneId: reconstruction.scene_id,
        };
    if (group === undefined) {
      islands.push({
        islandId,
        captureIds,
        firstCapturedAtMs: spanByIsland.get(islandId)?.first ?? null,
        lastCapturedAtMs: spanByIsland.get(islandId)?.last ?? null,
        positionedCaptureCount: 0,
        spreadMetres: null,
        // No group speaks for this region, and the server reports rungs per group. Null is the
        // honest answer rather than a guess at rung 4.
        rung: null,
        rungCaptureCount: 0,
        ...reconstructionPresentation,
      });
      continue;
    }
    // A rung this client cannot name takes its capture count with it. The count says how much of
    // the region is behind the rung, so `rung: null` beside a count of two reads as "no rung,
    // from two captures": a measurement standing behind a claim that was never made. Null says
    // nothing here has been through reconstruction, and then nothing here has a recorded rung to
    // count. It is the same answer the branch above already gives.
    const rung = asRung(group.rung);
    islands.push({
      islandId,
      captureIds,
      firstCapturedAtMs: toMs(group.first_utc),
      lastCapturedAtMs: toMs(group.last_utc),
      positionedCaptureCount: group.positioned_member_count,
      spreadMetres: group.positioned_member_count > 0 ? group.radius_m : null,
      rung,
      rungCaptureCount: rung === null ? 0 : group.rung_capture_count,
      ...reconstructionPresentation,
    });
  }

  // Ordered by when the photographs were taken, which is the layout solver's ordering key. An
  // island with no usable clock sorts last rather than to the epoch, because sorting it first
  // would make an undated photograph the anchor of the user's spatial memory.
  return islands.sort((a, b) => {
    const left = a.firstCapturedAtMs ?? Number.POSITIVE_INFINITY;
    const right = b.firstCapturedAtMs ?? Number.POSITIVE_INFINITY;
    if (left !== right) return left - right;
    return a.islandId < b.islandId ? -1 : a.islandId > b.islandId ? 1 : 0;
  });
}

/**
 * The one group this island IS, or undefined when no single group speaks for it.
 *
 * Three ways to be undefined and they are one fact: two groups landed here, or the group that
 * landed here left members elsewhere, or something the grouping never placed landed here too. In
 * all three the island is not the group, so the group's aggregates are not this island's.
 */
function groupWhollyIn(
  contributing: readonly SceneGroupPayload[] | undefined,
  captureIds: readonly string[],
  islandId: IslandIdRef,
  islandOf: IslandOf,
): SceneGroupPayload | undefined {
  if (contributing === undefined || contributing.length !== 1) return undefined;
  const group = contributing[0]!;
  if (group.capture_ids.length !== captureIds.length) return undefined;
  return group.capture_ids.every((captureId) => islandOf(captureId) === islandId)
    ? group
    : undefined;
}

/**
 * The rung, narrowed to the four the ladder has, or null.
 *
 * Null means nothing reconstructed this region, which is a different fact from rung 4 and is not
 * flattened into it: rung 4 means reconstruction ran and found nothing to place. A value outside
 * one to four is a server this client does not understand, and reporting it as a rung would be
 * showing a label for a ladder position that does not exist.
 */
function asRung(value: number | null): ReconstructionRungRef | null {
  return value === 1 || value === 2 || value === 3 || value === 4 ? value : null;
}

function minOf(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return Math.min(a, b);
}

function maxOf(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return Math.max(a, b);
}
