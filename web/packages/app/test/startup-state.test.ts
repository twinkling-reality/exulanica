// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildStartupState } from '../src/ui/startup-state.js';
import { ApiError } from '@exulanica/graph-client';

const FAILURES: readonly unknown[] = [
  new ApiError(401, 'unauthorized', 'missing token'),
  new ApiError(500, 'http_500', 'Internal Server Error'),
  new TypeError('Failed to fetch'),
  new DOMException('Timed out', 'TimeoutError'),
  new Error('Invalid world topology'),
  'a thrown string',
];

describe('what somebody sees before their world is on the screen', () => {
  it('says what happened once, and never says it twice', () => {
    for (const error of [new ApiError(500, 'http_500', 'Internal Server Error'),
      new TypeError('Failed to fetch'), new DOMException('Timed out', 'TimeoutError')]) {
      const view = buildStartupState(error);
      expect(view.querySelector('h1')?.textContent).toBe('Exulanica is not answering right now.');
      expect(view.textContent).not.toContain('http_500');
      // One statement and one action: no wordmark, and no second line repeating the first.
      expect(view.querySelector('.gate-wordmark')).toBeNull();
      expect(view.querySelector('.gate-note')).toBeNull();
      expect(view.querySelectorAll('p, h1')).toHaveLength(1);
    }
    const signedOut = buildStartupState(new ApiError(401, 'unauthorized', 'missing token'));
    expect(signedOut.querySelector('h1')?.textContent).toBe('You are not signed in to this world.');
    expect(signedOut.querySelectorAll('p, h1')).toHaveLength(1);
    // Reloading a signed-out session lands on the sign-in screen, so the label says so.
    expect(signedOut.querySelector('button')?.textContent).toBe('Sign in');
  });

  it('keeps an unrecognised failure\'s own message, which the statement cannot carry', () => {
    const view = buildStartupState(new Error('Invalid world topology'));
    expect(view.querySelector('h1')?.textContent).toBe('Your world could not be loaded.');
    expect(view.querySelector('.gate-note')?.textContent).toBe('Invalid world topology');
    expect(view.querySelector('button')?.textContent).toBe('Try again');
    // A thrown value with nothing to say adds no empty line.
    expect(buildStartupState('a thrown string').querySelector('.gate-note')).toBeNull();
  });

  it('names the product and never the runtime behind it', () => {
    // frontier-roadmap.md: public surfaces say Exulanica; Atlas is an internal runtime name and
    // must not appear as though it were a second product.
    for (const error of [undefined, ...FAILURES]) {
      expect(buildStartupState(error).textContent ?? '').not.toMatch(/\bAtlas\b/u);
    }
    // Where the copy has to name the thing that is not answering, it names the product.
    expect(buildStartupState(new TypeError('Failed to fetch')).textContent).toContain('Exulanica');
  });

  it('shows the orb while loading and one styled action when it fails', () => {
    const loading = buildStartupState();
    expect(loading.getAttribute('role')).toBe('status');
    expect(loading.textContent).toContain('Opening your world');
    expect(loading.classList.contains('startup-thinking')).toBe(true);
    expect(loading.querySelector('canvas.thinking-orb')).not.toBeNull();
    // Nothing else: the second line used to describe machinery to somebody with no photographs.
    expect(loading.querySelector('.startup-thinking-detail')).toBeNull();

    const failure = buildStartupState(new Error('The world topology is not configured.'));
    expect(failure.getAttribute('role')).toBe('alert');
    expect(failure.textContent).toContain('The world topology is not configured.');
    const action = failure.querySelector('button')!;
    expect(action.textContent).toBe('Try again');
    expect(failure.querySelector('.gate-wordmark')).toBeNull();
    // The same pill the sign-in screen uses, rather than whatever the browser draws by default.
    expect(action.classList.contains('gate-action')).toBe(true);
    const css = readFileSync(`${process.cwd()}/packages/app/src/style.css`, 'utf8');
    expect(css).toContain('.gate-action {');
  });

  it('does not hide loading or errors behind the narrow-viewport world restriction', () => {
    const css = readFileSync(`${process.cwd()}/packages/app/src/style.css`, 'utf8');
    const selector = css.match(/(#shell > :not\(\.viewport-boundary\)[^{]*)\{/u)![1]!.trim();
    const shell = document.createElement('div');
    shell.id = 'shell';
    const loading = buildStartupState();
    const failure = buildStartupState(new Error('API unavailable'));
    shell.append(loading, failure);
    expect(loading.matches(selector)).toBe(false);
    expect(failure.matches(selector)).toBe(false);
  });

  it('keeps only the light loading surface visible while world chrome boots', () => {
    const css = readFileSync(`${process.cwd()}/packages/app/src/style.css`, 'utf8');
    const bootstrap = readFileSync(`${process.cwd()}/packages/app/src/bootstrap.ts`, 'utf8');
    expect(css).toContain(
      '#shell[data-booting] > :not(.gate):not(.startup-thinking)',
    );
    expect(css).toContain('#shell[data-booting] > .startup-thinking');
    // The pre-module screen is read as source because importing it would run it, and running it
    // fetches `main.js`, which is the whole application. What is asserted is what it may depend
    // on and what it says, which is all this file exists to keep true.
    // DEPENDENCY-FREE. It is the only code that runs before `main.js` is fetched, so it is the
    // only code that can speak when that fetch fails, and anything it imported would be gone too.
    const staticImports = [...bootstrap.matchAll(/^import .*$/gmu)].map((match) => match[0]);
    expect(staticImports.filter((line) => !line.endsWith(".css';"))).toEqual([]);
    expect(bootstrap).not.toContain("from './ui/startup-state");
    // ONE LABEL, and the words `buildThinkingStatus` opens with, so the handover from this file
    // to the application changes nothing on the screen.
    expect(bootstrap).toContain("label.className = 'startup-thinking-label'");
    expect(bootstrap).toContain("label.textContent = 'Opening your world'");
    expect(buildStartupState().querySelector('.startup-thinking-label')?.textContent)
      .toBe('Opening your world');
    expect(bootstrap).not.toContain('startup-thinking-detail');
    // NO MARK. The application draws one from `thinking-orbs`, inside the bundle this screen
    // covers the absence of, so a second one here would be replaced milliseconds later and an
    // arriving person would watch two different loading screens rather than one.
    expect(bootstrap).not.toContain('startup-mark');
    expect(css).not.toContain('.startup-mark');
    // ONE SENTENCE AND ONE ACTION, wearing the same pill as every other refusal, and naming the
    // product rather than the runtime behind it.
    expect(bootstrap).toContain("title.textContent = 'Exulanica could not start'");
    expect(bootstrap).toContain("action.className = 'gate-action'");
    expect(bootstrap).not.toMatch(/\bAtlas\b/u);

    const shell = document.createElement('div');
    shell.id = 'shell';
    shell.dataset['booting'] = '';
    const loading = buildStartupState();
    const menu = document.createElement('section');
    menu.className = 'world-menu';
    const companion = document.createElement('section');
    companion.className = 'companion-encounter';
    shell.append(menu, companion, loading);

    const hiddenSelector =
      '#shell[data-booting] > :not(.gate):not(.startup-thinking)';
    expect(menu.matches(hiddenSelector)).toBe(true);
    expect(companion.matches(hiddenSelector)).toBe(true);
    expect(loading.matches(hiddenSelector)).toBe(false);
  });
});
