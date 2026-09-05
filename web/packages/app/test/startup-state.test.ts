// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildStartupState } from '../src/ui/startup-state.js';

describe('visible Atlas startup states', () => {
  it('shows loading before requests finish and an actionable failure if startup rejects', () => {
    const loading = buildStartupState();
    expect(loading.getAttribute('role')).toBe('status');
    expect(loading.textContent).toContain('Loading the library');
    const failure = buildStartupState(new Error('The world topology is not configured.'));
    expect(failure.getAttribute('role')).toBe('alert');
    expect(failure.textContent).toContain('The world topology is not configured.');
    expect(failure.querySelector('button')!.textContent).toBe('Retry opening Atlas');
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
});
