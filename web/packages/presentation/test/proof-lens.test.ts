// The proof lens: the tier decision and the legend that makes a colour checkable.

import { describe, expect, it } from 'vitest';

import {
  DAWN_THEME,
  BLUE_HOUR_THEME,
  PROOF_TIERS,
  PROOF_TIER_LABELS,
  PROOF_TIER_SENTENCES,
  proofLensPalette,
  proofTierColor,
  proofTierIndex,
  proofTierOf,
} from '../src/index.js';

describe('what tier a region is showing', () => {
  it('calls a region drawing photographs photographed', () => {
    expect(
      proofTierOf({ substrate: 'source_photographs', drawn: true, showingGenerated: false }),
    ).toBe('photographed');
  });

  it('calls point maps and trained geometry alike reconstructed', () => {
    // The rung distinguishes them. The question the lens answers does not.
    expect(proofTierOf({ substrate: 'posed_point_maps', drawn: true, showingGenerated: false })).toBe(
      'reconstructed',
    );
    expect(proofTierOf({ substrate: 'gaussian_splats', drawn: true, showingGenerated: false })).toBe(
      'reconstructed',
    );
  });

  it('gives an undrawn region its own tier rather than a shade of reconstructed', () => {
    // A region whose area displays a more complete scene of the same photographs is showing the
    // visitor nothing about the world. Colouring it as reconstruction would be the lens telling
    // the exact lie it exists to prevent.
    expect(
      proofTierOf({ substrate: 'gaussian_splats', drawn: false, showingGenerated: false }),
    ).toBe('unavailable');
    expect(proofTierOf({ substrate: null, drawn: true, showingGenerated: false })).toBe(
      'unavailable',
    );
  });

  it('reports generated over recorded when both are in view', () => {
    // The more alarming of two true answers is the one to give.
    expect(
      proofTierOf({ substrate: 'gaussian_splats', drawn: true, showingGenerated: true }),
    ).toBe('generated');
    expect(
      proofTierOf({ substrate: 'source_photographs', drawn: true, showingGenerated: true }),
    ).toBe('generated');
  });

  it('never calls an undrawn region generated', () => {
    expect(proofTierOf({ substrate: null, drawn: false, showingGenerated: true })).toBe(
      'unavailable',
    );
  });
});

describe('the legend', () => {
  it('names every tier the lens can produce', () => {
    // A colour without a name is a claim a visitor cannot check.
    for (const tier of PROOF_TIERS) {
      expect(PROOF_TIER_LABELS[tier].length).toBeGreaterThan(0);
      expect(PROOF_TIER_SENTENCES[tier].length).toBeGreaterThan(0);
    }
    expect(Object.keys(PROOF_TIER_LABELS).sort()).toEqual([...PROOF_TIERS].sort());
    expect(Object.keys(PROOF_TIER_SENTENCES).sort()).toEqual([...PROOF_TIERS].sort());
  });

  it('says of the generated tier that it supports no claim and carries no rung', () => {
    const sentence = PROOF_TIER_SENTENCES.generated;
    expect(sentence).toContain('no claim');
    expect(sentence).toContain('no reconstruction rung');
  });

  it('does not call reconstruction evidence', () => {
    expect(PROOF_TIER_SENTENCES.reconstructed).toContain('not itself evidence');
  });
});

describe('colours', () => {
  it('gives every tier a distinct colour in both themes', () => {
    for (const theme of [DAWN_THEME, BLUE_HOUR_THEME]) {
      const colors = PROOF_TIERS.map((tier) => proofTierColor(theme, tier));
      expect(new Set(colors).size).toBe(PROOF_TIERS.length);
    }
  });

  it('packs one RGBA row per tier, in PROOF_TIERS order', () => {
    const palette = proofLensPalette(DAWN_THEME);
    expect(palette.length).toBe(PROOF_TIERS.length * 4);
    for (const tier of PROOF_TIERS) {
      const row = proofTierIndex(tier) * 4;
      expect(palette[row]).toBeGreaterThanOrEqual(0);
      expect(palette[row]).toBeLessThanOrEqual(1);
      expect(palette[row + 3]).toBeGreaterThan(0);
    }
  });

  it('emphasises generated most and unavailable least', () => {
    // The one thing a viewer must never fail to notice is that a surface was imagined.
    const palette = proofLensPalette(DAWN_THEME);
    const emphasis = (tier: (typeof PROOF_TIERS)[number]) => palette[proofTierIndex(tier) * 4 + 3]!;
    expect(emphasis('generated')).toBeGreaterThan(emphasis('photographed'));
    expect(emphasis('generated')).toBeGreaterThan(emphasis('reconstructed'));
    expect(emphasis('unavailable')).toBeLessThan(emphasis('reconstructed'));
  });
});
