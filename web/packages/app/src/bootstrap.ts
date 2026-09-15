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
  const mark = document.createElement('span');
  mark.className = 'startup-mark';
  mark.setAttribute('aria-hidden', 'true');
  const copy = document.createElement('div');
  copy.className = 'startup-thinking-copy';
  const label = document.createElement('p');
  label.className = 'startup-thinking-label';
  label.textContent = 'Opening Atlas';
  const detail = document.createElement('p');
  detail.className = 'startup-thinking-detail';
  detail.textContent = 'Loading your world and its verified reconstructions…';
  copy.append(label, detail);
  loading.append(mark, copy);
  shell.replaceChildren(loading);
}

void import('./main.js').catch((error: unknown) => {
  if (shell === null) return;
  const canvas = document.getElementById('atlas');
  if (canvas !== null) canvas.hidden = true;
  shell.setAttribute('data-world-state', 'error');
  const panel = document.createElement('section');
  panel.className = 'gate';
  panel.setAttribute('role', 'alert');
  const title = document.createElement('h1');
  title.textContent = 'Atlas could not start';
  const detail = document.createElement('p');
  detail.textContent = error instanceof Error ? error.message : 'The application module could not load.';
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.textContent = 'Reload Atlas';
  retry.addEventListener('click', () => window.location.reload());
  panel.append(title, detail, retry);
  shell.replaceChildren(panel);
});

export {};
