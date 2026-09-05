/** Keep module/import failures visible even when the main application's dependencies cannot run. */
const shell = document.getElementById('shell');
if (shell !== null) {
  const loading = document.createElement('p');
  loading.className = 'gate';
  loading.setAttribute('role', 'status');
  loading.textContent = 'Opening Atlas…';
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
