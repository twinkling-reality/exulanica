import { describe, expect, it } from 'vitest';

import {
  MOCK_SCENARIOS,
  formationLabel,
  formationLabelLine,
  initialFormationState,
  reduceFormation,
  replayToEnd,
  withStreamState,
  type FormationState,
  type StageEvent,
  type StreamState,
} from '../src/index.js';

/**
 * The upload card's words for a batch the queue has received and nothing has reported on since.
 *
 * The card prints the stage, the headline and every detail line together. With no worker reporting,
 * a batch stays at `received` while its photographs are already openable, so the headline may say
 * only what the queue knows: that the upload arrived, and that no stage has reported since. Each
 * state the card can see at that stage is written out here in full.
 */

const CAPTURE = 'c1';
const STREAMS: readonly StreamState[] = ['connecting', 'live', 'lost'];

/** What the upload card prints for a state (composition/personal-intake.ts). */
const card = (state: FormationState): string => formationLabelLine(formationLabel(state));

const received = (photographs?: number): FormationState =>
  reduceFormation(initialFormationState(CAPTURE), {
    eventId: 'a', captureId: CAPTURE, phase: 'received', stageIndex: 0, at: 0,
    ...(photographs === undefined ? {} : { photographs }),
  });

describe('a received batch is described by what the queue knows', () => {
  it('before any event arrives', () => {
    expect(card(initialFormationState(CAPTURE))).toBe(
      'Upload received Photographs received. No count reported yet. Connecting to the pipeline.',
    );
  });

  it('with a count, live', () => {
    expect(card(received(4))).toBe(
      'Upload received Received 4 photographs. No processing stage has reported yet. '
        + '4 photographs are available to open now.',
    );
    expect(card(received(1))).toBe(
      'Upload received Received 1 photograph. No processing stage has reported yet. '
        + '1 photograph is available to open now.',
    );
  });

  it('with a count, after contact is lost', () => {
    expect(card(withStreamState(received(4), 'lost'))).toBe(
      'Upload received Received 4 photographs. No processing stage has reported yet. '
        + 'Contact with the pipeline was lost. The counts below are the last ones received. '
        + '4 photographs are available to open now.',
    );
  });

  it('without a count, in every stream state', () => {
    for (const stream of STREAMS) {
      const text = card(withStreamState(received(), stream));
      expect(text).toContain('Photographs received. No count reported yet.');
      expect(text).not.toMatch(/available to open/);
    }
  });
});

describe('no card the stream can produce contradicts its own "available to open now"', () => {
  it('never calls openable photographs unprocessed or uncounted', () => {
    const offenders: string[] = [];
    const look = (state: FormationState): void => {
      for (const stream of STREAMS) {
        const text = card(withStreamState(state, stream));
        if (/not yet (processed|counted)/i.test(text)) offenders.push(text);
      }
    };
    for (const photographs of [undefined, 1, 4]) look(received(photographs));
    for (const scenario of MOCK_SCENARIOS) {
      let s: FormationState = initialFormationState(CAPTURE);
      look(s);
      replayToEnd(scenario, CAPTURE, (event: StageEvent) => {
        s = reduceFormation(s, event);
        look(s);
      });
    }
    expect(offenders).toEqual([]);
  });
});
