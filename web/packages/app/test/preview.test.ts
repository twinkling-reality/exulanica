// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { decodeOpm } from '@exulanica/atlas-react/playcanvas';
import { adaptSnapshot, ExulanicaClient, type OccurrenceRecord } from '@exulanica/graph-client';

import {
  applicationTitle,
  isAtlasPreview,
  previewCredentials,
} from '../src/config.js';
import { previewApiResponse } from '../src/dev/preview-api.js';
import { PREVIEW_GRAPH } from '../src/dev/preview-graph.js';
import { PREVIEW_SOURCE_MEDIA } from '../src/dev/preview-media.js';
import { EvidenceCache } from '../src/evidence.js';
import { buildScene } from '../src/scene.js';
import { buildDetail } from '../src/ui/detail.js';
import { buildWorldIndex } from '../src/ui/world-index.js';

describe('Atlas development preview', () => {
  it('requires both an explicit query and a development build', () => {
    expect(isAtlasPreview('?preview=1', true)).toBe(true);
    expect(isAtlasPreview('?preview=0', true)).toBe(false);
    expect(isAtlasPreview('?preview=1', false)).toBe(false);
  });

  it('uses an isolated endpoint and a non-user preview credential', () => {
    expect(previewCredentials('http://127.0.0.1:5173')).toEqual({
      baseUrl: 'http://127.0.0.1:5173/preview-api',
      token: 'atlas-preview-read-only',
    });
  });

  it('adapts the typed payload into a drawable multi-region Atlas', () => {
    const snapshot = adaptSnapshot(PREVIEW_GRAPH);
    const built = buildScene(snapshot);
    expect(snapshot.entities).toHaveLength(6);
    expect(snapshot.islands).toHaveLength(4);
    expect(built.scene.islands).toHaveLength(4);
    expect(built.omitted).toHaveLength(0);
  });

  it('uses backend-valid UUID shapes and server-reachable link states', () => {
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/;
    const ids = [
      ...PREVIEW_GRAPH.entities.flatMap((entity) => [
        entity.entity_id,
        ...entity.capture_ids,
        ...entity.assertions.flatMap((assertion) => [
          assertion.assertion_id,
          ...assertion.support_span_ids,
        ]),
        ...entity.history.map((event) => event.event_id),
      ]),
      ...PREVIEW_GRAPH.occurrences.flatMap((occurrence) => [
        occurrence.occurrence_id,
        occurrence.capture_id,
        occurrence.primary_span_id,
      ]),
      ...PREVIEW_GRAPH.proposals.map((proposal) => proposal.proposal_id),
      ...PREVIEW_GRAPH.scene_groups.map((group) => group.group_id),
    ];
    expect(ids.every((id) => uuid.test(id))).toBe(true);
    expect(
      PREVIEW_GRAPH.occurrences.every(
        (occurrence) =>
          (occurrence.entity_id === null && occurrence.link_state === null) ||
          occurrence.link_state === 'confirmed' ||
          occurrence.link_state === 'auto_provisional',
      ),
    ).toBe(true);
    expect(PREVIEW_GRAPH.proposals.every((proposal) => proposal.outcome === 'surfaced')).toBe(true);
    expect(PREVIEW_GRAPH.state_version).toBeGreaterThanOrEqual(PREVIEW_GRAPH.occurrences.length);
  });

  it('serves only preview reads and refuses every mutation method', () => {
    expect(previewApiResponse('GET', '/graph').statusCode).toBe(200);
    expect(previewApiResponse('GET', '/formation').body).toEqual([]);
    expect(previewApiResponse('GET', '/evidence/example').statusCode).toBe(404);
    const available = [...PREVIEW_SOURCE_MEDIA.values()].find((source) => source.available)!;
    expect(previewApiResponse('GET', `/evidence/${available.evidenceRef}`)).toMatchObject({
      statusCode: 200,
      contentType: 'image/jpeg',
    });
    expect(previewApiResponse('GET', '/identity').statusCode).toBe(404);
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      const decision = previewApiResponse(method, '/identity/confirm');
      expect(decision.statusCode).toBe(403);
      expect(decision.body).toMatchObject({ code: 'preview_read_only' });
    }
  });

  it('identifies the synthetic read-only preview without permanent world chrome', () => {
    expect(applicationTitle(true)).toContain('development preview');
    expect(applicationTitle(true)).toContain('synthetic');
    expect(applicationTitle(true)).toContain('read-only');
    expect(applicationTitle(false)).toBe('Exulanica');
  });

  it('omits naming and disables evidence before either can make a request', () => {
    const evidenceBytes = vi.fn(async () => new Blob());
    const detail = buildDetail(
      new EvidenceCache({ evidenceBytes }),
      { onClose: vi.fn(), onName: vi.fn(), onEvidenceOpened: vi.fn(), onLocate: vi.fn() },
      { preview: true },
    );
    const occurrence: OccurrenceRecord = {
      occurrenceId: 'preview-occurrence',
      anchorId: 'preview-occurrence',
      islandId: 'preview-region',
      kind: 'object',
      entityId: null,
      linkState: 'proposed',
      confidence: 'low',
      evidence: ['preview-span'],
      capturedAtMs: 1_744_464_280_000,
    };

    detail.showOccurrence(occurrence);
    expect(detail.root.querySelector('.name-offer')).toBeNull();
    expect(detail.root.querySelector('.preview-read-only-note')?.textContent).toContain('read-only');
    const evidence = detail.root.querySelector<HTMLButtonElement>('.citation-open');
    expect(evidence?.disabled).toBe(true);
    evidence?.click();
    expect(evidenceBytes).not.toHaveBeenCalled();
  });

  it('does not promise source photographs from the synthetic Index', () => {
    const snapshot = adaptSnapshot(PREVIEW_GRAPH);
    const indexPane = buildWorldIndex(
      { onEntity: vi.fn(), onOccurrence: vi.fn(), onSearch: vi.fn() },
      { preview: true },
    );
    indexPane.render(snapshot, '', null);
    const note = indexPane.root.querySelector('.rail-note')?.textContent ?? '';
    expect(note).toContain('synthetic');
    expect(note).toContain('unavailable');
    expect(note).not.toContain('opens the photograph');
  });
});


describe('Current client and retained preview bytes', () => {
  it('uses the real client masked route for available and deliberately unavailable sources', async () => {
    const calls: string[] = [];
    const client = new ExulanicaClient({
      baseUrl: 'http://atlas-preview.local', token: 'atlas-preview-read-only',
      fetch: async (input, init) => {
        const path = new URL(String(input)).pathname;
        calls.push(path);
        const decision = previewApiResponse(init?.method ?? 'GET', path);
        const bytes = decision.assetPath === undefined
          ? JSON.stringify(decision.body)
          : Uint8Array.from(readFileSync(`packages/app/public/${decision.assetPath}`));
        return new Response(bytes, {
          status: decision.statusCode,
          headers: { 'content-type': decision.contentType ?? 'application/json' },
        });
      },
    });
    const available = [...PREVIEW_SOURCE_MEDIA.values()].find((source) => source.available)!;
    const unavailable = [...PREVIEW_SOURCE_MEDIA.values()].find((source) => !source.available)!;
    const image = await client.evidenceBytes(available.evidenceRef);
    const expected = readFileSync('packages/app/public/fixtures/memory/glasshouse-courtyard.jpg');
    expect(new Uint8Array(await image.arrayBuffer())).toEqual(Uint8Array.from(expected));
    expect(image.type).toBe('image/jpeg');
    await expect(client.evidenceBytes(unavailable.evidenceRef)).rejects.toMatchObject({
      status: 404, code: 'preview_evidence_unavailable',
    });
    expect(calls).toEqual([
      `/evidence/${available.evidenceRef}/masked`, `/evidence/${unavailable.evidenceRef}/masked`,
    ]);
    expect(previewApiResponse('GET', `/evidence/${available.evidenceRef}`)).toEqual(
      previewApiResponse('GET', `/evidence/${available.evidenceRef}/masked`),
    );
  });

  it('refuses malformed and unknown routes without throwing or enabling writes', () => {
    const available = [...PREVIEW_SOURCE_MEDIA.values()].find((source) => source.available)!;
    for (const path of ['/evidence/%', '/evidence/%2F', '/evidence/unknown/masked',
      `/evidence/${available.evidenceRef}/masked/extra`, `/evidence/${available.evidenceRef}/region`,
      `/evidence/${available.evidenceRef}/masked/`, 'http://[']) {
      expect(previewApiResponse('GET', path).statusCode).toBe(404);
      for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
        expect(previewApiResponse(method, path).statusCode).toBe(403);
      }
    }
  });

  it('decodes the migrated checked-in OPM with unchanged metadata and payload', () => {
    const bytes = Uint8Array.from(readFileSync('packages/app/public/fixtures/memory/glasshouse-courtyard.opm'));
    const decoded = decodeOpm(bytes.buffer);
    expect(decoded.header.pointCount).toBe(190570);
    expect(decoded.header.sourceImage).toEqual({ width: 1280, height: 960 });
    expect(decoded.header.modelImage).toEqual({ width: 512, height: 384 });
    expect(decoded.header.colorAlpha).toBe('support');
    expect(decoded.planarContiguous).toBe(true);
    expect(decoded.packedByteOffset).toBe(1296);
    const headerLength = new DataView(bytes.buffer).getUint32(4, true);
    const raw = new TextDecoder().decode(bytes.subarray(8, 8 + headerLength));
    const legacyHeader = new TextEncoder().encode(raw.replace('"format":"exulanica-point-map"', '"format":"orimera-point-map"'));
    const restored = bytes.slice();
    new DataView(restored.buffer).setUint32(4, legacyHeader.length, true);
    restored.fill(32, 8, 1296);
    restored.set(legacyHeader, 8);
    // Reconstructing the exact reviewed old hash proves every other field and payload byte stayed.
    expect(createHash('sha256').update(restored).digest('hex')).toBe(
      '3d6712872eb05bd8b012b3f1e1ddf90cce17fe669fcd8b4360354d1909d096e2',
    );
    expect(() => decodeOpm(restored.buffer)).toThrow('unexpected .opm format field');
  });
});
