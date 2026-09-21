export const FIRST_USE_GUIDANCE_KEY = 'exulanica.atlas.first-use.v2';

export type FirstUsePhase = 'arrival' | 'traversal' | 'companion' | 'complete';
export type FirstUseMode = 'traverse' | 'converse';

export interface FirstUsePromptAction {
  readonly label: string;
  readonly key?: string;
  /** A real surface action. Key-labelled entries remain orientation, never simulated controls. */
  readonly activate?: 'summon-companion';
}

export interface FirstUsePrompt {
  readonly statement: string;
  readonly actions: readonly FirstUsePromptAction[];
  readonly compact?: boolean;
}

interface FirstUseStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export interface FirstUseGuidance {
  phase(): FirstUsePhase;
  prompt(mode: FirstUseMode): FirstUsePrompt | null;
  observeMode(mode: FirstUseMode): boolean;
  observeMovement(): boolean;
  complete(): boolean;
}

const PHASES = new Set<FirstUsePhase>(['arrival', 'traversal', 'companion', 'complete']);

function readPhase(storage: FirstUseStorage): FirstUsePhase {
  try {
    const stored = storage.getItem(FIRST_USE_GUIDANCE_KEY) as FirstUsePhase | null;
    return stored !== null && PHASES.has(stored) ? stored : 'arrival';
  } catch {
    return 'arrival';
  }
}

/**
 * A four-state orientation, not a tour. Progress follows demonstrated actions and is saved on the
 * device; there are no timers, route locks, invented completion metrics, or graph writes.
 */
export function createFirstUseGuidance(storage: FirstUseStorage): FirstUseGuidance {
  let phase = readPhase(storage);
  let showingArrival = true;

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

  return {
    phase: () => phase,
    prompt(mode) {
      if (showingArrival && mode === 'converse') {
        return Object.freeze({
          statement: 'Welcome to Exulanica',
          actions: Object.freeze([{
            label: 'Start building',
            activate: 'summon-companion' as const,
          }]),
        });
      }
      if (phase === 'complete') return null;
      if (phase === 'companion') {
        return Object.freeze({
          statement: 'Welcome to Exulanica',
          actions: Object.freeze([
            { key: 'X', label: 'Call your Unnamed Companion' },
            { key: 'Esc', label: 'Dismiss' },
          ]),
        });
      }
      if (mode === 'converse') return null;
      if (phase === 'traversal') {
        return Object.freeze({
          statement: 'Welcome to Exulanica',
          actions: Object.freeze([
            { key: 'W A S D', label: 'Move' },
            { key: 'X', label: 'Call your Unnamed Companion' },
            { key: 'Esc', label: 'Dismiss' },
          ]),
        });
      }
      return Object.freeze({
        statement: 'Welcome to Exulanica',
        actions: Object.freeze([
          { key: 'X', label: 'Call your Unnamed Companion' },
          { key: 'Esc', label: 'Dismiss' },
        ]),
      });
    },
    observeMode(mode) {
      if (mode === 'traverse') showingArrival = false;
      return mode === 'traverse' && phase === 'arrival' ? setPhase('traversal') : false;
    },
    observeMovement() {
      return phase === 'arrival' || phase === 'traversal' ? setPhase('companion') : false;
    },
    complete() {
      showingArrival = false;
      return setPhase('complete');
    },
  };
}
