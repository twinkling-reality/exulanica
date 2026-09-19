/**
 * The capsule radius the nav_envelope carve keeps clear is the city grammar's own: the integer
 * measures its descriptor's nav_envelope contract states for capsule_clearance, carried into the
 * generated grammar table. Nothing in core restates the number.
 *
 * Every version this tessellator reads is checked, against its OWN descriptor, because the measure
 * a carve keeps is a property of the version a tile was written in and not of the newest one.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { GRAMMAR_TABLES } from '../src/core/record-shapes.js';
import { cityTableSources } from './grammar-table-sources.js';

describe('the capsule clearance the nav_envelope carve keeps', () => {
  const sources = cityTableSources();

  it('is checked for every grammar version this tessellator reads', () => {
    expect(sources.map((source) => source.version)).toEqual(
      GRAMMAR_TABLES.map((table) => table.grammar_version),
    );
  });

  it.each(sources)('is the measure city v$version states for nav_envelope', (source) => {
    const descriptor = JSON.parse(readFileSync(source.descriptor, 'utf8')) as {
      projections: { projection: string; preserved: { property: string; measures?: Record<string, number> }[] }[];
    };
    const nav = descriptor.projections.find((projection) => projection.projection === 'nav_envelope')!;
    const clearance = nav.preserved.find((row) => row.property === 'capsule_clearance')!;
    expect(clearance.measures).toBeDefined();
    const table = GRAMMAR_TABLES.find((candidate) => candidate.grammar_version === source.version)!;
    expect(table.measures.nav_envelope?.capsule_clearance).toEqual(clearance.measures);
    expect(table.measures.nav_envelope?.capsule_clearance?.radius_mm).toBeGreaterThan(0);
  });
});
