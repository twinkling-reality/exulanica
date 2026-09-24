import { say } from './copy.js';

export const FIRST_USE_GUIDANCE_KEY = 'exulanica.atlas.first-use.v3';

/** What the retired four-state orientation wrote. A device that finished it is not greeted again. */
export const RETIRED_FIRST_USE_GUIDANCE_KEY = 'exulanica.atlas.first-use.v2';

export type FirstUsePhase = 'new' | 'greeted' | 'done';
export type FirstUseMode = 'traverse' | 'converse';

export interface FirstUsePromptAction {
  readonly label: string;
  readonly key?: string;
  /**
   * A real control and what it does. With `key` as well, the key cap names the key that already
   * does the same thing; the control calls the action itself and never simulates the key. An entry
   * without `activate` is orientation text, never a control.
   */
  readonly activate?: 'summon-companion' | 'dismiss';
}

export interface FirstUsePrompt {
  /**
   * What this prompt is.
   *
   * The host used to recognise the welcome by comparing its exact sentence, which made the words
   * load-bearing: rewriting them silently changed behaviour elsewhere on the screen. Required,
   * because a prompt without one would make that check silently false again, which is exactly how
   * the reload defect this replaces stayed hidden.
   */
  readonly kind: 'welcome' | 'orientation';
  readonly statement: string;
  readonly actions: readonly FirstUsePromptAction[];
  readonly compact?: boolean;
}

interface FirstUseStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface FirstUseGuidanceOptions {
  /**
   * Whether the server says this world has been built in: an authored edit or an attached
   * photograph. Device storage cannot answer it, because the same person on a new device is not
   * a new person, and this is the difference between greeting somebody and talking over them.
   */
  readonly worldHasContent?: () => boolean;
}

export interface FirstUseGuidance {
  phase(): FirstUsePhase;
  prompt(mode: FirstUseMode): FirstUsePrompt | null;
  observeMode(mode: FirstUseMode): boolean;
  observeMovement(): boolean;
  complete(): boolean;
}

const PHASES = new Set<string>(['new', 'greeted', 'done']);

function readPhase(storage: FirstUseStorage): FirstUsePhase {
  try {
    const stored = storage.getItem(FIRST_USE_GUIDANCE_KEY);
    if (stored !== null && PHASES.has(stored)) return stored as FirstUsePhase;
    return storage.getItem(RETIRED_FIRST_USE_GUIDANCE_KEY) === 'complete' ? 'done' : 'new';
  } catch {
    return 'new';
  }
}

/**
 * Everything the product says to somebody who has just arrived, under three rules.
 *
 * ONE VOICE. Guidance speaks through the Companion's surface. Chrome labels what it does and
 * says nothing else.
 *
 * ONE THING AT A TIME. At most one prompt exists, so nothing has to compete for the same moment.
 * The previous version could offer a welcome, a Companion invitation and a movement list as three
 * different states of the same card, and the world title animated underneath all of them.
 *
 * IT FOLLOWS WHAT SOMEBODY DID. Arriving earns a greeting, entering the world earns a word about
 * moving, and moving ends it. Each happens once. Progress is saved on the device and there are no
 * timers, route locks, invented completion metrics, or graph writes.
 */
export function createFirstUseGuidance(
  storage: FirstUseStorage,
  options: FirstUseGuidanceOptions = {},
): FirstUseGuidance {
  let phase = readPhase(storage);
  const worldHasContent = options.worldHasContent ?? ((): boolean => false);

  const setPhase = (next: FirstUsePhase): boolean => {
    if (phase === next) return false;
    phase = next;
    try {
      storage.setItem(FIRST_USE_GUIDANCE_KEY, next);
    } catch {
      // Storage refusal must not turn optional orientation into a boot failure.
    }
    return true;
  };

  const welcome: FirstUsePrompt = Object.freeze({
    kind: 'welcome',
    statement: say('firstUse.welcome'),
    actions: Object.freeze([
      { label: say('firstUse.startBuilding'), activate: 'summon-companion' as const },
      { key: 'Esc', label: say('firstUse.dismiss'), activate: 'dismiss' as const },
    ]),
  });

  const orientation: FirstUsePrompt = Object.freeze({
    kind: 'orientation',
    statement: say('firstUse.orientation'),
    // Text only: the pointer is locked while this shows, so nothing on it could be clicked.
    actions: Object.freeze([
      { key: 'W A S D', label: say('firstUse.walk') },
      { key: 'X', label: say('firstUse.callCompanion') },
      { key: 'Esc', label: say('firstUse.dismiss') },
    ]),
  });

  return {
    phase: () => phase,
    prompt(mode) {
      if (phase === 'done') return null;
      // Somebody whose world already holds something is not new, whatever this device remembers.
      if (mode === 'converse') return phase === 'new' && !worldHasContent() ? welcome : null;
      return orientation;
    },
    observeMode(mode) {
      // Entering the world answers the greeting: it is no longer a thing waiting to be read.
      return mode === 'traverse' && phase === 'new' ? setPhase('greeted') : false;
    },
    observeMovement() {
      // Moving is what the orientation asked for, so there is nothing left to say.
      return setPhase('done');
    },
    complete() {
      return setPhase('done');
    },
  };
}
