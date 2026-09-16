// @vitest-environment happy-dom
import * as pc from 'playcanvas';
import { describe, expect, it } from 'vitest';
import { AnchorOverlay } from '../src/playcanvas/anchor-overlay.js';

/** An overlay frame with no anchors at all, so the only prompt that can appear is the photograph's. */
function frame(overrides: { photographPrompt?: boolean; memoryPrompt?: boolean; traversalActive?: boolean }) {
  return {
    table: { count: 0, anchors: [], atlasPositions: new Float32Array(0) },
    emphasis: { anchorLabelable: new Uint8Array(0), anchorEmphasis: new Float32Array(0) },
    camera: { projectionMatrix: new pc.Mat4(), viewMatrix: new pc.Mat4() },
    cameraPosition: { x: 0, y: 0, z: 0 },
    traversalActive: overrides.traversalActive ?? true,
    candidateIndex: null,
    presentIslands: new Set(),
    focusedDistance: null,
    focusedIndex: null,
    widthCss: 800,
    heightCss: 600,
    capturedAt: 0,
    renderOrigin: [0, 0, 0] as const,
    ...(overrides.photographPrompt === undefined ? {} : { photographPrompt: overrides.photographPrompt }),
    ...(overrides.memoryPrompt === undefined ? {} : { memoryPrompt: overrides.memoryPrompt }),
  } as unknown as Parameters<AnchorOverlay['update']>[0];
}

const labelled = (overlay: AnchorOverlay, ariaLabel: string) =>
  Array.from(overlay.root.querySelectorAll<HTMLElement>('.ov-focus'))
    .find((node) => node.getAttribute('aria-label') === ariaLabel)!;
const prompt = (overlay: AnchorOverlay) => labelled(overlay, 'Press E to open this photograph');
const memoryPrompt = (overlay: AnchorOverlay) => labelled(overlay, 'Press E to open this memory');

describe('the open-photograph prompt', () => {
  it('offers E beside the reticle while the visitor looks into a photograph, and says what E does', () => {
    const overlay = new AnchorOverlay(document.body);
    overlay.update(frame({ photographPrompt: true }));
    const node = prompt(overlay);
    expect(node.style.display).not.toBe('none');
    expect(node.getAttribute('aria-label')).toBe('Press E to open this photograph');
    expect(node.style.transform).toBe('translate3d(418.0px, 314.0px, 0)');
    expect(overlay.counts.focusLabels).toBe(1);
  });

  it('is gone when the visitor looks away or is not walking', () => {
    const overlay = new AnchorOverlay(document.body);
    overlay.update(frame({ photographPrompt: true }));
    overlay.update(frame({ photographPrompt: false }));
    expect(prompt(overlay).style.display).toBe('none');
    overlay.update(frame({ photographPrompt: true, traversalActive: false }));
    expect(prompt(overlay).style.display).toBe('none');
    expect(overlay.counts.focusLabels).toBe(0);
  });
});

/*
 * The landmark carries no anchor, so the reticle never settles on it and the visitor never gets a
 * focus label for it. Standing inside the memory is the whole condition, which is why this prompt
 * needs no aim: over a district a ray toward a landmark meets a facade first.
 */
describe('the open-memory prompt', () => {
  it('offers E beside the reticle while the visitor stands inside a memory', () => {
    const overlay = new AnchorOverlay(document.body);
    overlay.update(frame({ memoryPrompt: true }));
    const node = memoryPrompt(overlay);
    expect(node.style.display).not.toBe('none');
    expect(node.style.transform).toBe('translate3d(418.0px, 314.0px, 0)');
    expect(overlay.counts.focusLabels).toBe(1);
  });

  it('is gone on leaving the memory or on leaving traversal', () => {
    const overlay = new AnchorOverlay(document.body);
    overlay.update(frame({ memoryPrompt: true }));
    overlay.update(frame({ memoryPrompt: false }));
    expect(memoryPrompt(overlay).style.display).toBe('none');
    overlay.update(frame({ memoryPrompt: true, traversalActive: false }));
    expect(memoryPrompt(overlay).style.display).toBe('none');
  });

  it('yields the one prompt slot to a photograph under the reticle', () => {
    const overlay = new AnchorOverlay(document.body);
    overlay.update(frame({ photographPrompt: true, memoryPrompt: true }));
    expect(prompt(overlay).style.display).not.toBe('none');
    expect(memoryPrompt(overlay).style.display).toBe('none');
    expect(overlay.counts.focusLabels).toBe(1);
  });
});
