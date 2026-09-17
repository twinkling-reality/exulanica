import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  generatedDressing,
  generatedRecordSubjectV2,
  type GeneratedRecordEntry,
  type GeneratedTileReferenceV2,
} from '@exulanica/atlas-core';
import { bakeTile, decodeOwd, type DecodedOwd } from '@exulanica/loom-tess/core';

// Relative to web/, where the suite runs.
const GOLDEN = 'packages/app/src/dev/tiles/tile-conformance.owd';
const CITY_V2 = '../tests/fixtures/city-v2/tile-document.json';
const sha256 = async (bytes: Uint8Array): Promise<string> => createHash('sha256').update(bytes).digest('hex');

interface Outcome {
  readonly kind: string;
  readonly membership: string;
  readonly state: string;
  readonly hasExtent: boolean;
  readonly subjectId: string | null;
  readonly bounded: boolean;
  readonly reason: string | null;
}

/** Every record of a decoded container, read through contract v2 exactly as a tile runtime would. */
function readThroughContract(owd: DecodedOwd): readonly Outcome[] {
  const { header } = owd;
  const batch = header.projections.find(projection => projection.name === 'render_batch');
  if (batch === undefined) throw new Error('the container has no render_batch projection');
  return header.records.map((record, index) => {
    const grammar = header.grammars[record.grammar]!;
    const tile: GeneratedTileReferenceV2 = {
      tileX: header.tile.fields['tile_x'] as number,
      tileY: header.tile.fields['tile_y'] as number,
      lod: header.tile.fields['lod'] as number,
      inputsDigest: header.tile_inputs_digest,
      grammarId: grammar.grammar_id,
      grammarVersion: grammar.grammar_version,
      frameName: grammar.frame.name,
      subjectIdentity: grammar.subject_identity,
    };
    const raw = batch.entries[index]!;
    let entry: GeneratedRecordEntry;
    if (raw.state === 'drawn') {
      const material = raw.material;
      entry = {
        state: 'drawn',
        extentMm: raw.extent_mm,
        material: material === undefined || material.state !== 'record'
          ? { state: 'none-exists' }
          : { state: 'record', record: header.records[material.record]! },
      };
    } else if (raw.state === 'unavailable') {
      entry = { state: 'unavailable', needs: raw.needs };
    } else {
      entry = { state: raw.state };
    }
    const payload = { kind: record.kind, version: record.version, fields: record.fields };
    const result = generatedRecordSubjectV2(tile, {
      record: payload, membership: record.membership, entry, drawnSeparately: false, availability: 'available',
    });
    return {
      kind: record.kind, membership: record.membership, state: raw.state,
      hasExtent: Object.hasOwn(record.fields, 'extent'),
      subjectId: result.subject?.subjectId ?? null,
      bounded: result.subject?.bounds != null,
      reason: result.reason,
    };
  });
}

function expectContract(outcomes: readonly Outcome[]): void {
  for (const outcome of outcomes) {
    if (outcome.membership === 'halo') {
      expect(outcome, 'a halo record has no subject').toMatchObject({ subjectId: null, state: 'halo' });
    } else if (outcome.state === 'drawn') {
      expect(outcome.subjectId, `${outcome.kind} is owned and drawn`).toMatch(/^generated:city\.[a-z_]+:[0-9a-f-]{36}$/);
      expect(outcome.bounded, `${outcome.kind} has a drawn extent, so a box`).toBe(true);
    } else if (!outcome.hasExtent) {
      expect(outcome.subjectId, `${outcome.kind} states no extent`).toBeNull();
    } else {
      expect(outcome, `${outcome.kind} is owned and not drawn`).toMatchObject({ bounded: false, reason: null });
    }
  }
  const ids = outcomes.flatMap(outcome => outcome.subjectId === null ? [] : [outcome.subjectId]);
  expect(new Set(ids).size).toBe(ids.length);
}

/** What tess's owd/2 draws of the fixture today, pinned so a change here is a deliberate one. */
function expectToday(outcomes: readonly Outcome[]): void {
  const count = (test: (outcome: Outcome) => boolean) => outcomes.filter(test).length;
  expect(outcomes).toHaveLength(174);
  expect(outcomes.filter(outcome => outcome.state === 'drawn').map(outcome => [outcome.kind, outcome.bounded]))
    .toEqual([['city.terrain', true]]);
  expect(count(outcome => outcome.membership === 'halo' && outcome.subjectId === null)).toBe(3);
  expect(count(outcome => outcome.state === 'unavailable' && outcome.subjectId !== null && !outcome.bounded)).toBe(61);
  expect(count(outcome => outcome.state === 'not_in_projection' && outcome.hasExtent && !outcome.bounded)).toBe(24);
  expect(count(outcome => outcome.membership === 'owned' && !outcome.hasExtent && outcome.subjectId === null)).toBe(85);
}
describe('generated subject contract v2 over real city v2 containers', () => {
  it('reads tess\'s owd/2 development golden: every owned drawn record a subject, every halo record none', () => {
    const outcomes = readThroughContract(decodeOwd(new Uint8Array(readFileSync(GOLDEN))));
    expectContract(outcomes);
    expectToday(outcomes);
  });

  it('reads the city v2 fixture tile baked by tess, and lists every dressing under a subject that exists', async () => {
    const { container } = await bakeTile(new Uint8Array(readFileSync(CITY_V2)), sha256);
    const owd = decodeOwd(container);
    const outcomes = readThroughContract(owd);
    expectContract(outcomes);
    expectToday(outcomes);
    expect(outcomes).toEqual(readThroughContract(decodeOwd(new Uint8Array(readFileSync(GOLDEN)))));
    const subjects = new Set(outcomes.flatMap(outcome => outcome.subjectId === null ? [] : [outcome.subjectId]));
    const dressings = owd.header.records.filter(record => record.kind === 'city.surface_material');
    expect(dressings.length).toBeGreaterThan(0);
    for (const record of dressings) {
      const dressing = generatedDressing({ kind: record.kind, version: record.version, fields: record.fields });
      expect(subjects.has(dressing.dressesSubjectId), `${record.fields['role'] as string} dresses a listed subject`).toBe(true);
    }
  }, 120_000);
});
