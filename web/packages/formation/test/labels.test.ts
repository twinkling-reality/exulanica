import { describe, expect, it } from 'vitest';
import { rungProperties } from '@exulanica/atlas-core';

import {
  FORMATION_STAGES,
  MOCK_SCENARIOS,
  formationLabel,
  initialFormationState,
  reduceFormation,
  replayToEnd,
  rungSentence,
  withStreamState,
  type FormationState,
  type StageEvent,
} from '../src/index.js';

const CAPTURE = 'c1';

/** Every label the mock scenarios can produce, at every step, in both stream states. */
function everyLabel(): string[] {
  const out: string[] = [];
  for (const scenario of MOCK_SCENARIOS) {
    let s: FormationState = initialFormationState(CAPTURE);
    const collect = (state: FormationState): void => {
      const l = formationLabel(state);
      out.push(l.stage, l.headline, ...l.detail, l.elapsed ?? '', l.note ?? '');
    };
    collect(s);
    replayToEnd(scenario, CAPTURE, (e: StageEvent) => {
      s = reduceFormation(s, e);
      collect(s);
      collect(withStreamState(s, 'lost'));
    });
  }
  for (const rung of [1, 2, 3, 4] as const) out.push(rungSentence(rung));
  return out;
}

describe('no label ever fabricates progress', () => {
  const labels = everyLabel();

  it('never prints a percentage', () => {
    expect(labels.filter((l) => /%|percent/i.test(l))).toEqual([]);
  });

  it('never prints an estimate of time remaining', () => {
    // Word-bounded: "metadata" and "retained" both contain "eta", and neither is a promise.
    const promises = /\bremaining\b|\bETA\b|estimated time|\balmost\b|nearly done|time left|finishing up/i;
    expect(labels.filter((l) => promises.test(l))).toEqual([]);
  });

  it('never uses a banned retention word', () => {
    expect(labels.filter((l) => /immutable|WORM|tamper.?proof/i.test(l))).toEqual([]);
  });

  it('never mentions audio, voices or transcripts', () => {
    expect(labels.filter((l) => /voice|speech|transcri|conversation|audio/i.test(l))).toEqual([]);
  });
});

describe('the label set does not depend on motion', () => {
  it('takes no motion argument, so reduced motion cannot change a word', () => {
    expect(formationLabel.length).toBe(1);
  });
});

describe('elapsed time appears exactly when no fraction exists', () => {
  it('shows elapsed time for an unmeasured stage', () => {
    let s = initialFormationState(CAPTURE);
    s = reduceFormation(s, { eventId: 'a', captureId: CAPTURE, phase: 'received', stageIndex: 0, at: 0, photographs: 148 });
    s = reduceFormation(s, { eventId: 'b', captureId: CAPTURE, phase: 'reconstruction', stageIndex: 3, at: 95_000 });
    const l = formationLabel(s);
    expect(l.elapsed).toBe('1 min 35 s elapsed');
    expect(l.headline).toBe('Reconstructing surfaces. No measurable progress to report.');
  });

  it('hides elapsed time when a real fraction exists', () => {
    let s = initialFormationState(CAPTURE);
    s = reduceFormation(s, { eventId: 'a', captureId: CAPTURE, phase: 'received', stageIndex: 0, at: 0 });
    s = reduceFormation(s, {
      eventId: 'b',
      captureId: CAPTURE,
      phase: 'media_extraction',
      stageIndex: 1,
      at: 9000,
      counters: { done: 62, total: 148 },
    });
    const l = formationLabel(s);
    expect(l.elapsed).toBeNull();
    expect(l.headline).toBe('Reading images: 62 of 148.');
  });
});

describe('outcome labels state what is usable', () => {
  it('keeps the photographs available after a failure and says nothing was deleted', () => {
    let s = initialFormationState(CAPTURE);
    replayToEnd('failed', CAPTURE, (e) => {
      s = reduceFormation(s, e);
    });
    const l = formationLabel(s);
    expect(l.headline).toContain('The photographs are available.');
    expect(l.detail).toContain('148 photographs are available to open now.');
    expect(l.detail).toContain('Nothing was deleted. The originals are retained.');
  });

  it('does not offer photographs a cancelled batch no longer has', () => {
    let s = initialFormationState(CAPTURE);
    s = reduceFormation(s, { eventId: 'a', captureId: CAPTURE, phase: 'received', stageIndex: 0, at: 0, photographs: 4 });
    s = reduceFormation(s, {
      eventId: 'b',
      captureId: CAPTURE,
      phase: 'failed',
      stageIndex: 6,
      at: 1,
      outcome: { rung: 4, openQuestions: 0, photographsAvailable: 0, reason: 'cancelled' },
    });
    const l = formationLabel(s);
    expect(l.headline).toContain('The job was stopped.');
    expect(l.headline).not.toContain('The photographs are available.');
    expect(l.detail).toContain('0 photographs are available to open now.');
  });

  it('states open questions without treating zero as a finish line', () => {
    let s = initialFormationState(CAPTURE);
    s = reduceFormation(s, { eventId: 'a', captureId: CAPTURE, phase: 'ready', stageIndex: 6, at: 1, outcome: { rung: 1, openQuestions: 0, photographsAvailable: 3 } });
    expect(formationLabel(s).headline).toBe('This region is ready. Nothing is waiting on you.');
    s = reduceFormation(s, { eventId: 'b', captureId: CAPTURE, phase: 'ready', stageIndex: 6, at: 2, outcome: { rung: 1, openQuestions: 7, photographsAvailable: 3 } });
    expect(formationLabel(s).headline).toBe('This region is ready. 7 things I am unsure about.');
  });

  it('says contact was lost before it prints a stale count', () => {
    let s = initialFormationState(CAPTURE);
    s = reduceFormation(s, { eventId: 'a', captureId: CAPTURE, phase: 'camera_recovery', stageIndex: 2, at: 1, counters: { done: 91, total: 148 } });
    s = withStreamState(s, 'lost');
    expect(formationLabel(s).detail[0]).toBe(
      'Contact with the pipeline was lost. The counts below are the last ones received.',
    );
  });
});

describe('rung copy honours the one fixed constraint in product-specification.md 5.2', () => {
  it('implies free movement only for the rung that earned it', () => {
    for (const rung of [1, 2, 3, 4] as const) {
      const impliesFree = /move freely|walk anywhere|go anywhere|free movement/i.test(rungSentence(rung));
      expect(impliesFree).toBe(rungProperties(rung).impliesFreeMovement);
    }
  });
});

describe('the stage track names real pipeline stages', () => {
  it('has a label for every stage', () => {
    for (const stage of FORMATION_STAGES) {
      const s = reduceFormation(initialFormationState(CAPTURE), {
        eventId: 'a',
        captureId: CAPTURE,
        phase: stage,
        stageIndex: 0,
        at: 1,
      });
      expect(formationLabel(s).stage.length).toBeGreaterThan(0);
    }
  });
});
