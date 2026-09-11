import * as pc from 'playcanvas';
import type { AnchorTable, EmphasisBuffers, IslandId } from '@exulanica/atlas-core';
import {
  DEFAULT_FOCUS_CONFIG,
  MAX_CAPTIONS,
  MAX_EDGE_CHEVRONS,
  MAX_FOCUS_LABELS,
  rendersAsPresenceMarker,
} from '@exulanica/atlas-core';
import {
  resolveInteractionAffordance,
  type InteractionAffordanceStage,
} from './interaction-affordance.js';

/**
 * Screen-space anchors, projected manually from world positions into PRE-ALLOCATED DOM nodes.
 *
 * Three rules from the interaction model are structural here rather than aspirational:
 *
 *   1. HARD CAPS. One focus label, six pinned callouts, four edge chevrons. The nodes are
 *      allocated once at construction to exactly those counts and are then only ever shown,
 *      hidden and transformed. Nothing in `update` can create a node, so the overlay cannot grow
 *      into an inventory screen no matter what the scene contains.
 *   2. NO PER-FRAME REACT. This module owns raw DOM and writes `transform` and `opacity` inside
 *      the render loop. React would re-render only when the SET of overlay elements changes,
 *      which is a transition event, not a frame event. There is no React import in this file and
 *      there must not be one.
 *   3. AT MOST ONE LABEL. Attention is single-valued, so the focus label is a single node driven
 *      by the single winner the focus solver returns.
 *
 * And one product rule that lands here and nowhere else: PEOPLE ARE NOT BAKED INTO GEOMETRY. A
 * person anchor is drawn as a time-anchored presence marker carrying a timestamp, visibly a
 * citation rather than a reconstruction, and the point cloud has already discarded the person
 * points (see `semantics.ts`). The marker is the only place a person appears in the Atlas.
 *
 * The overlay is also the accessibility surface, because canvas content is invisible to screen
 * readers. Nodes carry real roles and text.
 */

export interface OverlayCounts {
  readonly focusLabels: number;
  readonly callouts: number;
  readonly chevrons: number;
  readonly presenceMarkers: number;
}

interface Node {
  readonly root: HTMLDivElement;
  visible: boolean;
}

function makeNode(className: string, parent: HTMLElement): Node {
  const root = document.createElement('div');
  root.className = className;
  root.style.position = 'absolute';
  root.style.left = '0';
  root.style.top = '0';
  root.style.willChange = 'transform';
  root.style.display = 'none';
  root.style.pointerEvents = 'none';
  parent.appendChild(root);
  return { root, visible: false };
}

function show(node: Node, x: number, y: number, opacity: number): void {
  if (!node.visible) {
    node.root.style.display = '';
    node.visible = true;
  }
  node.root.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
  node.root.style.opacity = opacity.toFixed(3);
}

function hide(node: Node): void {
  if (node.visible) {
    node.root.style.display = 'none';
    node.visible = false;
  }
}

export interface OverlayFrame {
  readonly table: AnchorTable;
  readonly emphasis: EmphasisBuffers;
  readonly camera: pc.CameraComponent;
  readonly cameraPosition: Readonly<{ x: number; y: number; z: number }>;
  readonly traversalActive: boolean;
  /** Best reticle candidate before the focus dwell has settled. */
  readonly candidateIndex: number | null;
  /** Islands whose source body is currently drawn. A prompt may only belong to one of these. */
  readonly presentIslands: ReadonlySet<IslandId>;
  /** Distance is present only while the settled focus is still the current candidate. */
  readonly focusedDistance: number | null;
  readonly focusedIndex: number | null;
  readonly widthCss: number;
  readonly heightCss: number;
  /** Epoch milliseconds for the anchor whose presence marker is being stamped. */
  readonly capturedAt: number;
  readonly renderOrigin: readonly [number, number, number];
  /**
   * The visitor is looking into one photograph drawn in an unmeasured arrangement, from near
   * where it was taken, and E would open it. Yields to an anchor's own prompt, which is the more
   * specific thing under the reticle.
   */
  readonly photographPrompt?: boolean;
}

export class AnchorOverlay {
  readonly root: HTMLDivElement;
  private readonly interactionSigil: Node;
  private readonly focusLabel: Node;
  private readonly photographLabel: Node;
  private readonly callouts: Node[];
  private readonly chevrons: Node[];
  private readonly markers: Node[];

  private readonly vp = new pc.Mat4();
  private readonly p = new pc.Vec4();

  private lastCounts: OverlayCounts = {
    focusLabels: 0,
    callouts: 0,
    chevrons: 0,
    presenceMarkers: 0,
  };

  /**
   * @param markerBudget how many presence markers may exist. Not one of the three documented
   * caps, because a presence marker is world content rather than a callout, but it is still a
   * fixed pool: the overlay never allocates during a frame.
   */
  constructor(parent: HTMLElement, markerBudget = 12) {
    this.root = document.createElement('div');
    this.root.className = 'exulanica-overlay';
    this.root.setAttribute('role', 'region');
    this.root.setAttribute('aria-label', 'Atlas anchors');
    this.root.style.position = 'absolute';
    this.root.style.inset = '0';
    this.root.style.pointerEvents = 'none';
    parent.appendChild(this.root);

    this.interactionSigil = makeNode('ov-sigil', this.root);
    this.interactionSigil.root.setAttribute('aria-hidden', 'true');
    this.focusLabel = makeNode('ov-focus', this.root);
    this.focusLabel.root.setAttribute('role', 'status');
    this.focusLabel.root.setAttribute('aria-live', 'polite');
    this.focusLabel.root.replaceChildren(
      Object.assign(document.createElement('span'), {
        className: 'ov-focus-key',
        textContent: 'E',
      }),
      Object.assign(document.createElement('span'), {
        className: 'ov-focus-verb',
        textContent: 'Interact',
      }),
    );
    // The same key-and-verb prompt as an anchor's, so pressing E reads as one gesture wherever it
    // is offered. Never shown at the same time as the anchor prompt, so the one-focus-label cap
    // still holds.
    this.photographLabel = makeNode('ov-focus', this.root);
    this.photographLabel.root.dataset['stage'] = 'label';
    this.photographLabel.root.setAttribute('role', 'status');
    this.photographLabel.root.setAttribute('aria-live', 'polite');
    this.photographLabel.root.setAttribute('aria-label', 'Press E to open this photograph');
    this.photographLabel.root.replaceChildren(
      Object.assign(document.createElement('span'), { className: 'ov-focus-key', textContent: 'E' }),
      // One short verb: the label stage reveals at most 5.5rem of it (style.css), sized for
      // "Interact". The visitor is already looking at the photograph; the accessible name says it.
      Object.assign(document.createElement('span'), { className: 'ov-focus-verb', textContent: 'Open' }),
    );
    this.callouts = Array.from({ length: MAX_CAPTIONS }, () => makeNode('ov-callout', this.root));
    this.chevrons = Array.from({ length: MAX_EDGE_CHEVRONS }, () =>
      makeNode('ov-chevron', this.root),
    );
    this.markers = Array.from({ length: markerBudget }, () => makeNode('ov-marker', this.root));

    if (MAX_FOCUS_LABELS !== 1) {
      throw new Error('the overlay is built around exactly one focus label');
    }
  }

  get counts(): OverlayCounts {
    return this.lastCounts;
  }

  /**
   * Project one atlas position. Returns null when the point is behind the camera.
   *
   * Done by hand rather than through a helper that mounts a DOM element per instance: the common
   * React-three helper allocates a wrapper element per anchor and documents blurriness in its
   * transform mode, which is correct for one or two elements and wrong for hundreds.
   */
  private project(
    x: number,
    y: number,
    z: number,
    w: number,
    h: number,
  ): { sx: number; sy: number; depth: number } | null {
    this.p.set(x, y, z, 1);
    this.vp.transformVec4(this.p, this.p);
    if (this.p.w <= 1e-6) return null;
    const inv = 1 / this.p.w;
    return {
      sx: (this.p.x * inv * 0.5 + 0.5) * w,
      sy: (1 - (this.p.y * inv * 0.5 + 0.5)) * h,
      depth: this.p.w,
    };
  }

  update(frame: OverlayFrame): void {
    const { table, emphasis, camera, widthCss: w, heightCss: h, renderOrigin } = frame;
    this.vp.mul2(camera.projectionMatrix, camera.viewMatrix);
    const proposed = frame.traversalActive
      ? (frame.candidateIndex ?? this.nearestOnScreenInteractable(frame, w, h))
      : null;
    // An interaction prompt is a claim that there is something there. If the anchor's island is
    // not resident it has no source body in the world, and the marker would be a prompt floating
    // over empty ground with nothing to explain it.
    const signalIndex = proposed !== null && this.hasVisibleSource(frame, proposed)
      ? proposed
      : null;
    const affordance = resolveInteractionAffordance({
      signalIndex,
      candidateIndex: frame.candidateIndex,
      focusedIndex: frame.focusedIndex,
      focusedDistance: frame.focusedDistance,
    });

    let calloutUsed = 0;
    let chevronUsed = 0;
    let markerUsed = 0;
    let focusUsed = 0;
    let sigilUsed = 0;

    // Candidates in table order, which is deterministic across both bindings, so the two
    // renderers put the same anchors in the same six slots.
    for (let i = 0; i < table.count; i += 1) {
      if (emphasis.anchorLabelable[i] === 0) continue;

      const anchor = table.anchors[i]!;
      const px = table.atlasPositions[i * 3]!;
      const py = table.atlasPositions[i * 3 + 1]!;
      const pz = table.atlasPositions[i * 3 + 2]!;
      const projected = this.project(
        px - renderOrigin[0],
        py - renderOrigin[1],
        pz - renderOrigin[2],
        w,
        h,
      );
      const scalar = emphasis.anchorEmphasis[i]!;

      if (projected === null) continue;
      const onScreen =
        projected.sx >= 0 && projected.sx <= w && projected.sy >= 0 && projected.sy <= h;

      if (i === signalIndex && affordance !== 'hidden' && onScreen) {
        // The marker stays above the world point. The key prompt remains lower-right of the
        // reticle, preserving the authored centre-clear targeting geometry.
        show(this.interactionSigil, projected.sx - 7, projected.sy - 34, 0.82);
        sigilUsed = 1;
        if (
          i === frame.candidateIndex &&
          (affordance === 'key' || affordance === 'label')
        ) {
          this.prepareFocusPrompt(table, i, affordance);
          show(this.focusLabel, projected.sx + 18, projected.sy + 14, 1);
          focusUsed += 1;
        }
        continue;
      }

      // A timestamp is world content, but it is not ambient scenery. Reveal presence markers only
      // when a view has deliberately promoted the anchor; neutral dates scattered across the
      // horizon make an archival landscape read like a debug overlay.
      if (
        rendersAsPresenceMarker(anchor) &&
        scalar >= 0.7 &&
        onScreen &&
        markerUsed < this.markers.length
      ) {
        const node = this.markers[markerUsed]!;
        node.root.textContent = new Date(frame.capturedAt).toISOString().slice(0, 10);
        node.root.dataset['linkState'] = anchor.linkState;
        node.root.dataset['provenance'] = anchor.provenance;
        show(node, projected.sx - 14, projected.sy - 34, Math.max(0.35, scalar));
        markerUsed += 1;
        continue;
      }

      if (!onScreen) {
        if (chevronUsed < MAX_EDGE_CHEVRONS) {
          // Clamp to an inset rounded rect and rotate toward the true direction.
          const inset = 28;
          const cx = w / 2;
          const cy = h / 2;
          const dx = projected.sx - cx;
          const dy = projected.sy - cy;
          const scale = Math.min(
            (w / 2 - inset) / Math.max(Math.abs(dx), 1e-3),
            (h / 2 - inset) / Math.max(Math.abs(dy), 1e-3),
          );
          const node = this.chevrons[chevronUsed]!;
          node.root.style.setProperty('--angle', `${Math.atan2(dy, dx).toFixed(3)}rad`);
          show(node, cx + dx * scale, cy + dy * scale, 0.75);
          chevronUsed += 1;
        }
        continue;
      }

      // Neutral anchors remain world matter, not ambient captions. A label is earned by focus or
      // by explicit view emphasis; generic object-kind callouts create a competing dashboard.
    }

    if (focusUsed === 0) hide(this.focusLabel);
    // Lower right of the reticle, where an anchor's prompt sits, so the centre stays clear.
    if (focusUsed === 0 && frame.traversalActive && frame.photographPrompt === true) {
      show(this.photographLabel, w / 2 + 18, h / 2 + 14, 1);
      focusUsed = 1;
    } else {
      hide(this.photographLabel);
    }
    if (sigilUsed === 0) hide(this.interactionSigil);
    for (let i = calloutUsed; i < this.callouts.length; i += 1) hide(this.callouts[i]!);
    for (let i = chevronUsed; i < this.chevrons.length; i += 1) hide(this.chevrons[i]!);
    for (let i = markerUsed; i < this.markers.length; i += 1) hide(this.markers[i]!);

    this.lastCounts = {
      focusLabels: focusUsed,
      callouts: calloutUsed,
      chevrons: chevronUsed,
      presenceMarkers: markerUsed,
    };
  }

  /**
   * Discovery is spatial, not a hover effect. Pick one nearby on-screen interactable even before
   * it enters the narrow aim cone; the focus solver remains the sole authority for showing E.
   */
  private nearestOnScreenInteractable(frame: OverlayFrame, w: number, h: number): number | null {
    const limitSq = DEFAULT_FOCUS_CONFIG.interactRadius ** 2;
    let nearestIndex: number | null = null;
    let nearestDistanceSq = Number.POSITIVE_INFINITY;

    for (let i = 0; i < frame.table.count; i += 1) {
      if (frame.emphasis.anchorInteractable[i] === 0) continue;
      if (!this.hasVisibleSource(frame, i)) continue;
      const offset = i * 3;
      const x = frame.table.atlasPositions[offset]!;
      const y = frame.table.atlasPositions[offset + 1]!;
      const z = frame.table.atlasPositions[offset + 2]!;
      const dx = x - frame.cameraPosition.x;
      const dy = y - frame.cameraPosition.y;
      const dz = z - frame.cameraPosition.z;
      const distanceSq = dx * dx + dy * dy + dz * dz;
      if (distanceSq > limitSq || distanceSq >= nearestDistanceSq) continue;

      const projected = this.project(x, y, z, w, h);
      if (
        projected === null ||
        projected.sx < 0 || projected.sx > w ||
        projected.sy < 0 || projected.sy > h
      ) continue;

      nearestIndex = i;
      nearestDistanceSq = distanceSq;
    }

    return nearestIndex;
  }

  private hasVisibleSource(frame: OverlayFrame, index: number): boolean {
    const anchor = frame.table.anchors[index];
    return anchor !== undefined && frame.presentIslands.has(anchor.islandId);
  }

  /** Visible copy remains one verb; memory and provenance belong to the opened evidence surface. */
  private prepareFocusPrompt(
    table: AnchorTable,
    index: number,
    stage: Extract<InteractionAffordanceStage, 'key' | 'label'>,
  ): void {
    const a = table.anchors[index]!;
    const kind = `${a.kind.slice(0, 1).toUpperCase()}${a.kind.slice(1)}`;
    const name = a.entityId === null ? `Unidentified ${a.kind}` : `${kind} in this memory`;
    this.focusLabel.root.dataset['stage'] = stage;
    this.focusLabel.root.setAttribute('aria-label', `Press E to interact with ${name}`);
  }

  destroy(): void {
    this.root.remove();
  }
}
