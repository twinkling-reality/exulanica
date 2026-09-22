/**
 * The screen before the application exists, and the screen when it never will.
 *
 * This file is the only code that runs before `main.js` is fetched, so it is the only code that
 * can say anything when that fetch fails. It therefore imports nothing but stylesheets, and it
 * draws nothing that needs a module: the animated mark the loaded application shows is drawn from
 * `thinking-orbs`, which is inside the bundle this screen exists to cover the absence of. A
 * second, different mark drawn here in CSS would be replaced by the real one milliseconds later,
 * so an arriving person would watch two loading screens rather than one.
 *
 * ONE LABEL, and the same words `buildThinkingStatus` opens with, so the handover from this file
 * to the application changes nothing on the screen. The line it replaces described the machinery
 * ("verified reconstructions") to somebody who has not added a photograph yet.
 */

import '@exulanica/presentation/tokens.css';
import './style.css';
import './appearance.css';
import './unified-interface.css';
import './ui/object-placement.css';
import './ui/environment-selection.css';
import './ui/scene-segments.css';
import './ui/redesign.css';
import './ui/character-studio.css';
import './ui/companion-layout.css';

window.addEventListener('beforeunload', () => {
  document.documentElement.setAttribute('data-reloading', '');
});
window.addEventListener('pageshow', () => {
  document.documentElement.removeAttribute('data-reloading');
});

/** Keep module/import failures visible even when the main application's dependencies cannot run. */
const shell = document.getElementById('shell');
if (shell !== null) {
  const loading = document.createElement('section');
  loading.className = 'startup-thinking';
  loading.setAttribute('role', 'status');
  const copy = document.createElement('div');
  copy.className = 'startup-thinking-copy';
  const label = document.createElement('p');
  label.className = 'startup-thinking-label';
  label.textContent = 'Opening your world';
  copy.append(label);
  loading.append(copy);
  shell.replaceChildren(loading);
}

void import('./main.js').catch((error: unknown) => {
  // The bundle is missing or unreadable. Nothing on the screen can act on which of those it was,
  // so the screen says the one thing that is true and the console keeps the address.
  console.error(error);
  if (shell === null) return;
  const canvas = document.getElementById('atlas');
  if (canvas !== null) canvas.hidden = true;
  shell.setAttribute('data-world-state', 'error');
  const panel = document.createElement('section');
  panel.className = 'gate';
  panel.setAttribute('role', 'alert');
  const title = document.createElement('h1');
  title.textContent = 'Exulanica could not start';
  const action = document.createElement('button');
  action.type = 'button';
  action.className = 'gate-action';
  action.textContent = 'Try again';
  action.addEventListener('click', () => window.location.reload());
  panel.append(title, action);
  shell.replaceChildren(panel);
});

export {};
