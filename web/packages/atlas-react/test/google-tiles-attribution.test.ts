// @vitest-environment happy-dom

import { beforeEach, describe, expect, it } from 'vitest';
import {
  GoogleAttributionLedger,
  GoogleAttributionSurface,
  googleGltfMetadata,
} from '../src/playcanvas/google-tiles-attribution.js';

function glb(gltf: object): ArrayBuffer {
  const source = JSON.stringify(gltf);
  const padded = source.padEnd(Math.ceil(source.length / 4) * 4, ' ');
  const bytes = new Uint8Array(20 + padded.length);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, bytes.byteLength, true);
  view.setUint32(12, padded.length, true);
  view.setUint32(16, 0x4e4f534a, true);
  bytes.set(new TextEncoder().encode(padded), 20);
  return bytes.buffer;
}

describe('visible Google tile attribution', () => {
  beforeEach(() => document.body.replaceChildren());

  it('reads copyright metadata while rejecting external glTF resources', () => {
    expect(googleGltfMetadata(glb({
      asset: { version: '2.0', copyright: 'Source A; Source B' },
      buffers: [{ byteLength: 0 }],
    })).copyright).toEqual(['Source A', 'Source B']);
    expect(() => googleGltfMetadata(glb({
      asset: { version: '2.0' },
      buffers: [{ uri: 'external.bin' }],
    }))).toThrow('External Google tile resources');
  });

  it('deduplicates in stable first-visible tile order', () => {
    const ledger = new GoogleAttributionLedger();
    ledger.setVisible('later-id', ['B', 'Shared'], true);
    ledger.setVisible('earlier-id', ['A', 'Shared'], true);
    expect(ledger.values()).toEqual(['B', 'Shared', 'A']);
    ledger.setVisible('later-id', [], false);
    expect(ledger.values()).toEqual(['A', 'Shared']);
    ledger.setVisible('later-id', ['B'], true);
    expect(ledger.values()).toEqual(['B', 'A', 'Shared']);
  });

  it('keeps Google attribution and end-user links in a distinct surface', () => {
    const surface = new GoogleAttributionSurface(document.body);
    surface.update(true, ['Source A']);
    expect(surface.root.hidden).toBe(false);
    expect(surface.root.getAttribute('aria-label')).toBe('Google Maps attribution');
    expect(surface.root.textContent).toContain('Google Maps');
    expect(surface.root.textContent).toContain('Source A');
    expect(surface.root.textContent).toContain('not Google street collision');
    expect(Array.from(surface.root.querySelectorAll('a')).map((link) => link.href)).toEqual([
      'https://maps.google.com/help/terms_maps/',
      'https://policies.google.com/privacy',
    ]);
    surface.destroy();
    expect(document.body.children).toHaveLength(0);
  });
});
