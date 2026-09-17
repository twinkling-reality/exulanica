/**
 * The capsule radius the nav_envelope carve keeps clear is the city grammar's own. The descriptor
 * states it as text until lane 20 adds it as a structured integer field; this test fails when that
 * text changes, so the constant cannot silently disagree with the claim it serves.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CAPSULE_RADIUS_MM } from '../src/core/expand.js';
import { CITY_DESCRIPTOR_PATH } from './grammar-table-sources.js';

const STATEMENT =
  'Clear space for a capsule of 340 mm radius and 1900 mm height, eye at 1620 mm, which is what the visual gate measures.';

describe('the capsule clearance the nav_envelope carve keeps', () => {
  it('is the radius the city descriptor states for nav_envelope', () => {
    const descriptor = JSON.parse(readFileSync(CITY_DESCRIPTOR_PATH, 'utf8')) as {
      projections: { projection: string; preserved: { property: string; statement: string }[] }[];
    };
    const nav = descriptor.projections.find((projection) => projection.projection === 'nav_envelope')!;
    const clearance = nav.preserved.find((row) => row.property === 'capsule_clearance');
    expect(clearance?.statement).toBe(STATEMENT);
    expect(Number(/(\d+) mm radius/.exec(STATEMENT)![1])).toBe(CAPSULE_RADIUS_MM);
  });
});
