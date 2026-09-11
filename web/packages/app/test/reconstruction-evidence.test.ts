// @vitest-environment happy-dom
/**
 * Click-to-evidence, as the inspector renders it.
 *
 * Three things this checks that would each be a real defect if they broke.
 *
 * A point whose COLMAP track is longer than the sample retained here MUST show both numbers. The
 * pose stage keeps at most 4096 observations per image, so a point forty photographs observed can
 * arrive holding fourteen. A panel that said "14 photographs" would be lying by omission about the
 * one thing the visitor is asking, and `observationSentence` in atlas-core is used verbatim here
 * precisely so the two cannot drift.
 *
 * A null pick is an answer and has to be shown as one. Sparse points are sparse; a plain surface
 * genuinely has no recorded observation near the cursor, and keeping the previous pick on screen
 * would attribute one surface's photographs to another.
 *
 * Every listed photograph carries its consent state, and today that state says a screening receipt
 * reviewed a whole photograph and recorded nothing about any person in it.
 */
import { describe, expect, it } from 'vitest';
import { observationSentence } from '@exulanica/atlas-core';
import { buildReconstructionInspector } from '../src/ui/reconstruction-inspector.js';
import { consentSentence } from '../src/observations-api.js';

function inspector() {
  return buildReconstructionInspector({ onView: () => true, onReturn: () => {} });
}

const CONSENT = Object.freeze({
  basis: 'human-screening-receipt',
  screening: Object.freeze({
    state: 'screened',
    method: 'human_review',
    eligibility: 'eligible',
    namedHumanReviewer: true,
    sensitiveRegionCount: 0,
  }),
  personConsent: 'unavailable',
  personConsentReason: 'No per-person presentation consent layer is present in this build.',
});

describe('the inspector evidence panel', () => {
  it('states the full track length beside the retained count when they differ', () => {
    // The real bowl scene holds 213 such points; this is one of them, point 44, whose track is 16
    // and whose retained sample is 14.
    const sentence = observationSentence({
      point: { pointId: 44, world: [0, 0, 0], trackLength: 16, observationsRetained: 14 },
      pixelDistance: 12,
      depth: 3,
      projection: 'pinhole-approximation',
    });
    expect(sentence).toContain('16 photographs observed this point');
    expect(sentence).toContain('14 photographs of them are retained here');

    const panel = inspector();
    panel.showEvidence({
      kind: 'hit', sentence, pointId: 44, pixelDistance: 12, meanReprojectionErrorPx: 0.37,
      projection: 'pinhole-approximation',
      photographs: [{
        captureId: '01a0722b-7552-73c5-9a78-75c512dbe29f',
        title: null, label: 'Photograph 1', url: null, alt: 'An original photograph.',
        available: false, x: 2679.1, y: 1630.2,
        consentSentence: consentSentence(CONSENT),
      }],
    });
    const state = panel.root.querySelector('.reconstruction-evidence-state')!;
    // Verbatim. Not a reworded version that happens to contain both numbers today.
    expect(state.textContent).toBe(sentence);
    expect(panel.root.querySelector('.reconstruction-evidence-detail')!.textContent)
      .toContain('nearest point COLMAP actually recorded, not the surface under the pointer');
    expect(panel.root.querySelector('.reconstruction-evidence-detail')!.textContent)
      .toContain('distortion model this projection approximates as a pinhole');
  });

  it('says both numbers are the same one when the track was fully retained', () => {
    const sentence = observationSentence({
      point: { pointId: 1, world: [0, 0, 0], trackLength: 3, observationsRetained: 3 },
      pixelDistance: 4, depth: 2, projection: 'pinhole',
    });
    expect(sentence).toBe('3 photographs observed this point.');
  });

  it('shows a null pick as a real answer rather than keeping the previous one', () => {
    const panel = inspector();
    panel.showEvidence({
      kind: 'hit', sentence: '3 photographs observed this point.', pointId: 1, pixelDistance: 4,
      meanReprojectionErrorPx: 0.4, projection: 'pinhole', photographs: [{
        captureId: 'capture-a', title: 'A photograph', label: 'Photograph 1', url: null,
        alt: 'An original photograph.', available: false, x: 1, y: 2,
        consentSentence: consentSentence(CONSENT),
      }],
    });
    expect(panel.root.querySelectorAll('.reconstruction-evidence-photograph')).toHaveLength(1);

    panel.showEvidence({ kind: 'miss', toleranceSourcePx: 45.3, canvasPx: 8 });
    expect(panel.root.querySelector<HTMLElement>('.reconstruction-evidence')!.dataset.evidence).toBe('miss');
    expect(panel.root.querySelector('.reconstruction-evidence-state')!.textContent)
      .toBe('No recorded observation is within reach of that click.');
    expect(panel.root.querySelector('.reconstruction-evidence-detail')!.textContent)
      .toContain('within 8 screen pixels (45 pixels of the original photograph)');
    // The previous pick is gone, not left standing beside a message about a different place.
    expect(panel.root.querySelectorAll('.reconstruction-evidence-photograph')).toHaveLength(0);
  });

  it('clears the previous answer the moment a new click goes to the server', () => {
    // The pick runs on the server now, so there is a gap between a click and its answer. The
    // previous point's photographs must not stand through that gap as the answer to this click.
    const panel = inspector();
    panel.showEvidence({
      kind: 'hit', sentence: '3 photographs observed this point.', pointId: 1, pixelDistance: 4,
      meanReprojectionErrorPx: 0.4, projection: 'pinhole', photographs: [{
        captureId: 'capture-a', title: 'A photograph', label: 'Photograph 1', url: null,
        alt: 'An original photograph.', available: false, x: 1, y: 2,
        consentSentence: consentSentence(CONSENT),
      }],
    });
    panel.showEvidence({ kind: 'resolving' });
    expect(panel.root.querySelector<HTMLElement>('.reconstruction-evidence')!.dataset.evidence)
      .toBe('resolving');
    expect(panel.root.querySelector('.reconstruction-evidence-state')!.textContent)
      .toBe('Finding the recorded point nearest that click.');
    expect(panel.root.querySelector('.reconstruction-evidence-detail')!.textContent).toBe('');
    expect(panel.root.querySelectorAll('.reconstruction-evidence-photograph')).toHaveLength(0);
  });

  it('carries each photograph consent state and never reports absent people', () => {
    const sentence = consentSentence(CONSENT);
    expect(sentence).toContain('Screened by a named human reviewer');
    expect(sentence).toContain('No per-person presentation consent is recorded');
    expect(sentence).toContain('not a decision about anyone in it');
    // The exact confusion the World Read bundle's release block exists to prevent.
    expect(sentence).not.toContain('no people');

    const panel = inspector();
    panel.showEvidence({
      kind: 'hit', sentence: '2 photographs observed this point.', pointId: 7, pixelDistance: 9,
      meanReprojectionErrorPx: 0.51, projection: 'pinhole', photographs: [
        { captureId: 'capture-a', title: 'Bowl, from the left', label: 'Photograph 1', url: null,
          alt: 'An original photograph.', available: false, x: 10, y: 20,
          consentSentence: sentence },
        { captureId: 'capture-b', title: null, label: 'Photograph 2', url: null,
          alt: 'An original photograph.', available: false, x: 30, y: 40,
          consentSentence: sentence },
      ],
    });
    const listed = [...panel.root.querySelectorAll<HTMLElement>('.reconstruction-evidence-photograph')];
    expect(listed.map((item) => item.dataset.captureId)).toEqual(['capture-a', 'capture-b']);
    for (const item of listed) {
      expect(item.querySelector('.reconstruction-evidence-consent')!.textContent).toBe(sentence);
      expect(item.querySelector('.reconstruction-evidence-unavailable')!.textContent)
        .toBe('The authorized original is not loaded in this session.');
    }
    expect(listed[0]!.querySelector('.reconstruction-evidence-title')!.textContent).toBe('Bowl, from the left');
    expect(listed[1]!.querySelector('.reconstruction-evidence-title')!.textContent).toBe('Photograph 2');
    expect(listed[0]!.querySelector('.reconstruction-evidence-where')!.textContent)
      .toBe('Recorded at 10, 20 in this photograph.');
  });

  it('refuses a midpoint rather than inverting a projection no camera stood behind', () => {
    const panel = inspector();
    panel.showEvidence({
      kind: 'unsupported',
      reason: 'This is a midpoint between two photographs, not a photograph. No camera stood here, '
        + 'so there is no calibrated projection to invert. Choose either adjacent source camera.',
    });
    expect(panel.root.querySelector<HTMLElement>('.reconstruction-evidence')!.dataset.evidence)
      .toBe('unsupported');
    expect(panel.root.querySelector('.reconstruction-evidence-state')!.textContent)
      .toContain('No camera stood here');
    expect(panel.root.querySelectorAll('.reconstruction-evidence-photograph')).toHaveLength(0);
  });

  it('names the sample bound before a visitor has clicked anything', () => {
    const panel = inspector();
    panel.showEvidence({ kind: 'ready', pointCount: 15005, retainedPerImage: 4096 });
    const state = panel.root.querySelector('.reconstruction-evidence-state')!.textContent!;
    expect(state).toContain('15,005 recorded points');
    expect(state).toContain('at most 4,096 per photograph');
  });

  it('clears its answer when the inspector closes', () => {
    const panel = inspector();
    panel.showEvidence({ kind: 'ready', pointCount: 10, retainedPerImage: 4096 });
    panel.hide();
    expect(panel.root.querySelector<HTMLElement>('.reconstruction-evidence')!.dataset.evidence)
      .toBe('unsupported');
  });
});
