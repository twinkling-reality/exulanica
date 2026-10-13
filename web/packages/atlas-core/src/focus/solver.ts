import type { AtlasVec3 } from '../coords.js';
import { atlasVec3, dot, normalize, sub } from '../coords.js';
import type { AnchorId, IslandId } from '../ids.js';
import type { AnchorTable } from '../scene.js';
import { anchorAtlasPosition } from '../scene.js';
import type { EmphasisBuffers } from '../manifest/apply.js';
import { deriveImportance } from './importance.js';

/**
 * The focus solver. One solver, at most one target.
 *
 * RETICLE-BASED, AND THAT IS FORCED. The Pointer Lock 2.0 specification states that while
 * locked, clientX/clientY and screenX/screenY "must hold constant values as if the pointer did
 * not move at all once pointer lock was entered". There is therefore no cursor position to hover
 * with, and all world targeting is at fixed screen centre.
 * https://w3c.github.io/pointerlock/ (interaction-model.md 2.1, VERIFIED)
 *
 * The consequence for this file: the only direction it ever reads is the camera forward vector.
 * There is no screen-space input of any kind in the signature, and there must never be one.
 *
 * interaction-model.md 3.3 fixes the scoring: "scoring candidates within an interact radius and
 * an aim cone by a weighted sum of aim (0.60), distance (0.25) and importance (0.15)".
 */

export interface CameraPose {
  readonly position: AtlasVec3;
  /** Unit vector. The reticle direction. Screen centre, always. */
  readonly forward: AtlasVec3;
}

export interface FocusConfig {
  /** Atlas units. Anchors beyond this are not candidates at any aim quality. */
  readonly interactRadius: number;
  /** Half-angle of the base aim cone, radians. Widened per candidate by its subtended angle. */
  readonly coneHalfAngle: number;
  /** "A short dwell (about 90 ms) before a winner becomes focused." */
  readonly dwellMs: number;
  /** "An incumbent keeps focus unless a challenger beats it by a margin." */
  readonly incumbentMargin: number;
  /** Occlusion runs "at reduced rate, never against the point cloud". */
  readonly occlusionIntervalMs: number;
  /** How many top-scoring candidates get an occlusion test. Bounded work per check. */
  readonly occlusionCandidates: number;
}

export const DEFAULT_FOCUS_CONFIG: FocusConfig = Object.freeze({
  interactRadius: 24,
  coneHalfAngle: (7 * Math.PI) / 180,
  dwellMs: 90,
  incumbentMargin: 0.08,
  occlusionIntervalMs: 100,
  occlusionCandidates: 4,
});

const WEIGHTS = Object.freeze({ aim: 0.6, distance: 0.25, importance: 0.15 });

export interface FocusState {
  /** Index into the anchor table, or null. At most one, always. */
  readonly focusedIndex: number | null;
  /** The challenger currently accumulating dwell time. */
  readonly pendingIndex: number | null;
  readonly pendingSinceMs: number;
  /** Stage 3 Engaged: Interact was pressed and focus latches until released. */
  readonly latched: boolean;
  readonly lastOcclusionMs: number;
  readonly occluded: ReadonlySet<number>;
}

export const INITIAL_FOCUS_STATE: FocusState = Object.freeze({
  focusedIndex: null,
  pendingIndex: null,
  pendingSinceMs: 0,
  latched: false,
  lastOcclusionMs: Number.NEGATIVE_INFINITY,
  occluded: new Set<number>(),
});

export interface FocusCandidate {
  readonly index: number;
  readonly anchorId: AnchorId;
  readonly score: number;
  readonly aim: number;
  readonly distance: number;
  readonly importance: number;
}

export interface FocusResolution {
  readonly state: FocusState;
  /** The focused anchor, or null. Never more than one: "attention is single-valued" (3.1). */
  readonly focused: FocusCandidate | null;
  /** The current best candidate, which may still be serving its dwell. For debug overlays. */
  readonly best: FocusCandidate | null;
}

/** Injected visibility test against a COARSE COLLISION PROXY. Never the point cloud (3.3). */
export type VisibilityTest = (from: AtlasVec3, to: AtlasVec3) => boolean;

export interface FocusInputs {
  readonly table: AnchorTable;
  readonly emphasis: EmphasisBuffers;
  readonly camera: CameraPose;
  readonly nowMs: number;
  readonly occurrenceNormalizer: number;
  readonly config?: FocusConfig;
  readonly visible?: VisibilityTest;
}

function scoreCandidates(inputs: FocusInputs, cfg: FocusConfig): FocusCandidate[] {
  const { table, emphasis, camera } = inputs;
  const forward = normalize(camera.forward);
  const out: FocusCandidate[] = [];

  for (let i = 0; i < table.count; i += 1) {
    if (emphasis.anchorInteractable[i] === 0) continue;

    const p = anchorAtlasPosition(table, i);
    const toAnchor = sub(p, camera.position);
    const distance = Math.sqrt(dot(toAnchor, toAnchor));
    if (distance > cfg.interactRadius || distance === 0) continue;

    const cosTheta = dot(toAnchor, forward) / distance;

    // "The cone widens for very close anchors, which is what makes small nearby objects
    // selectable without pixel-precise aim." The widening is the angle the focus volume actually
    // subtends, so a large near object is easy to hit and a small far one is not.
    const subtended = Math.atan2(table.focusRadii[i]!, distance);
    const cosCone = Math.cos(Math.min(Math.PI * 0.49, cfg.coneHalfAngle + subtended));
    if (cosTheta < cosCone) continue;

    const aim = cosCone >= 1 ? 1 : (cosTheta - cosCone) / (1 - cosCone);
    const distanceScore = 1 - distance / cfg.interactRadius;
    const importance = deriveImportance(
      table.anchors[i]!,
      emphasis.anchorEmphasis[i]!,
      inputs.occurrenceNormalizer,
    );

    out.push({
      index: i,
      anchorId: table.anchorIds[i]!,
      score:
        WEIGHTS.aim * aim + WEIGHTS.distance * distanceScore + WEIGHTS.importance * importance,
      aim,
      distance,
      importance,
    });
  }

  // Deterministic ordering: score descending, table index ascending on a tie.
  out.sort((a, b) => b.score - a.score || a.index - b.index);
  return out;
}

function refreshOcclusion(
  inputs: FocusInputs,
  cfg: FocusConfig,
  candidates: readonly FocusCandidate[],
  previous: FocusState,
): { occluded: ReadonlySet<number>; lastOcclusionMs: number } {
  const visible = inputs.visible;
  if (visible === undefined) {
    return { occluded: previous.occluded, lastOcclusionMs: previous.lastOcclusionMs };
  }
  if (inputs.nowMs - previous.lastOcclusionMs < cfg.occlusionIntervalMs) {
    return { occluded: previous.occluded, lastOcclusionMs: previous.lastOcclusionMs };
  }
  const occluded = new Set<number>();
  for (const c of candidates.slice(0, cfg.occlusionCandidates)) {
    if (!visible(inputs.camera.position, anchorAtlasPosition(inputs.table, c.index))) {
      occluded.add(c.index);
    }
  }
  return { occluded, lastOcclusionMs: inputs.nowMs };
}

/**
 * Resolve focus for one frame.
 *
 * Pure: previous state in, next state out, no timers, no globals, no `performance.now()`. The
 * caller supplies `nowMs`, which is what makes the 90 ms dwell and the occlusion interval
 * testable without a clock.
 */
export function resolveFocus(inputs: FocusInputs, previous: FocusState): FocusResolution {
  const cfg = inputs.config ?? DEFAULT_FOCUS_CONFIG;

  // Stage 3 Engaged: focus latches. A latched anchor is not re-solved, so the panel does not
  // change target under the user while they are reading it.
  if (previous.latched && previous.focusedIndex !== null) {
    const i = previous.focusedIndex;
    const held: FocusCandidate = {
      index: i,
      anchorId: inputs.table.anchorIds[i]!,
      score: 1,
      aim: 1,
      distance: 0,
      importance: 1,
    };
    return { state: previous, focused: held, best: held };
  }

  const candidates = scoreCandidates(inputs, cfg);
  const occ = refreshOcclusion(inputs, cfg, candidates, previous);
  const unoccluded = candidates.filter((c) => !occ.occluded.has(c.index));

  let best = unoccluded[0] ?? null;

  // The incumbent keeps focus unless a challenger beats it by a margin. Without this the label
  // swaps between two adjacent anchors on sub-pixel camera noise.
  if (previous.focusedIndex !== null && best !== null && best.index !== previous.focusedIndex) {
    const incumbent = unoccluded.find((c) => c.index === previous.focusedIndex);
    if (incumbent !== undefined && best.score < incumbent.score + cfg.incumbentMargin) {
      best = incumbent;
    }
  }

  const bestIndex = best?.index ?? null;

  // Dwell. A winner must hold for `dwellMs` before it becomes focused, which is what stops the
  // label strobing while sweeping the view. The same dwell applies to LOSING focus, so sweeping
  // past an anchor does not flash the label off and on. The document specifies the acquire side;
  // the release side uses the same dwell.
  let focusedIndex = previous.focusedIndex;
  let pendingIndex = previous.pendingIndex;
  let pendingSinceMs = previous.pendingSinceMs;

  if (bestIndex !== previous.pendingIndex) {
    pendingIndex = bestIndex;
    pendingSinceMs = inputs.nowMs;
  }
  if (pendingIndex !== focusedIndex && inputs.nowMs - pendingSinceMs >= cfg.dwellMs) {
    focusedIndex = pendingIndex;
  }

  const focused =
    focusedIndex === null
      ? null
      : (unoccluded.find((c) => c.index === focusedIndex) ?? {
          index: focusedIndex,
          anchorId: inputs.table.anchorIds[focusedIndex]!,
          score: 0,
          aim: 0,
          distance: 0,
          importance: 0,
        });

  return {
    state: Object.freeze({
      focusedIndex,
      pendingIndex,
      pendingSinceMs,
      latched: false,
      lastOcclusionMs: occ.lastOcclusionMs,
      occluded: occ.occluded,
    }),
    focused,
    best,
  };
}

/** Interact pressed. Stage 2 Focus becomes stage 3 Engaged and focus latches. */
export function latchFocus(state: FocusState): FocusState {
  if (state.focusedIndex === null) return state;
  return Object.freeze({ ...state, latched: true });
}

/** Panel closed. Focus is released and the solver resumes. */
export function releaseFocus(state: FocusState): FocusState {
  if (!state.latched) return state;
  return Object.freeze({ ...state, latched: false });
}

/**
 * Tab cycling (interaction-model.md 2.6): "Tab cycles anchors in the current region by distance
 * and focuses each exactly as the reticle would."
 *
 * Note "by distance", not by aim: Tab is the keyboard-only route and must not require the camera
 * to be pointing anywhere in particular. WCAG 2.2 SC 2.1.1 requires all functionality to be
 * keyboard operable. https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html
 */
export function tabOrder(
  table: AnchorTable,
  emphasis: EmphasisBuffers,
  camera: CameraPose,
  islandId: IslandId,
): readonly number[] {
  const range = table.islandRange.get(islandId);
  if (range === undefined) return [];
  const [start, count] = range;
  const scored: Array<{ index: number; d: number }> = [];
  for (let i = start; i < start + count; i += 1) {
    if (emphasis.anchorInteractable[i] === 0) continue;
    const p = anchorAtlasPosition(table, i);
    const d = sub(p, camera.position);
    scored.push({ index: i, d: dot(d, d) });
  }
  scored.sort((a, b) => a.d - b.d || a.index - b.index);
  return scored.map((s) => s.index);
}

/** Focus an anchor directly, as Tab and the World Index Locate action do. Bypasses the dwell. */
export function focusDirectly(state: FocusState, index: number, nowMs: number): FocusState {
  return Object.freeze({
    ...state,
    focusedIndex: index,
    pendingIndex: index,
    pendingSinceMs: nowMs,
  });
}

/** Convenience for a caller that has a yaw and pitch rather than a vector. */
export function forwardFromYawPitch(yaw: number, pitch: number): AtlasVec3 {
  const cp = Math.cos(pitch);
  return atlasVec3(Math.sin(yaw) * cp, Math.sin(pitch), Math.cos(yaw) * cp);
}
