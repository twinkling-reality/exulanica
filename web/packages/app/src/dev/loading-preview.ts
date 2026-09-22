/**
 * TEMPORARY development view of the loading and failure states, so they can be looked at without
 * waiting for a slow boot or breaking the server to see a refusal.
 *
 * One state at a time, in a real `#shell`, built by the function the application calls, so the
 * product's own stylesheet behaves exactly as it does in the app. The screen `bootstrap.ts`
 * paints before `main.js` arrives is separate inline markup in that file and is deliberately not
 * reproduced here: a copy would be a second source of truth that drifts.
 */
import type { OrbState } from 'thinking-orbs/engine';
import { ApiError } from '@exulanica/graph-client';
import '@exulanica/presentation/tokens.css';
import '../style.css';
import '../appearance.css';
import '../unified-interface.css';
import '../ui/redesign.css';
import { buildStartupState, buildWorldOpeningFailure } from '../ui/startup-state.js';
import { buildThinkingStatus } from '../ui/thinking-status.js';

/** Every state the orb component offers, so the one the loading screen uses can be chosen by eye. */
const ORB_STATES: readonly OrbState[] = [
  'shaping', 'working', 'searching', 'solving', 'listening',
  'connecting', 'weaving', 'composing', 'breathing',
];

const STATES: Readonly<Record<string, () => HTMLElement>> = Object.freeze({
  loading: () => buildStartupState(),
  unauthorised: () => buildStartupState(new ApiError(401, 'unauthenticated', 'no token was presented')),
  unavailable: () => buildStartupState(new ApiError(503, 'unavailable', 'the service is not answering')),
  offline: () => buildStartupState(new TypeError('Failed to fetch')),
  // A sample of the one case that shows a second line: an error the product did not recognise,
  // rendering its own message. The text below is this page's example, not product copy.
  other: () => buildStartupState(new Error('The world topology is not configured.')),
  // What a person with one saved world sees when it does not open. The reason below is this
  // page's example, not product copy: the product shows whatever the server said.
  'no world': () => buildWorldOpeningFailure({
    reason: 'The server did not answer.',
    retry: async () => undefined,
  }),
  // The same state when trying again cannot work.
  'no world, final': () => buildWorldOpeningFailure({
    reason: 'Its source material was deleted. The saved record remains, but it cannot be opened.',
    retry: null,
  }),
});

const parameters = new URL(window.location.href).searchParams;
const requested = parameters.get('state') ?? 'loading';
const name = requested in STATES ? requested : 'loading';
const requestedOrb = parameters.get('orb') as OrbState | null;
const orb = requestedOrb !== null && ORB_STATES.includes(requestedOrb) ? requestedOrb : null;

const shell = document.getElementById('shell');
if (shell !== null) {
  shell.replaceChildren(orb === null
    ? STATES[name]!()
    : buildThinkingStatus('Opening your world', `Orb state: ${orb}`, orb));
}

const nav = document.getElementById('dev-switch');
if (nav !== null) {
  nav.append(Object.assign(document.createElement('span'), {
    textContent: 'Development preview of the loading and failure states',
  }));
  for (const key of Object.keys(STATES)) {
    const link = document.createElement('a');
    link.href = `?state=${key}`;
    link.textContent = key;
    if (orb === null && key === name) link.setAttribute('aria-current', 'page');
    nav.append(link);
  }
  for (const state of ORB_STATES) {
    const link = document.createElement('a');
    link.href = `?orb=${state}`;
    link.textContent = `orb: ${state}`;
    if (state === orb) link.setAttribute('aria-current', 'page');
    nav.append(link);
  }
}
