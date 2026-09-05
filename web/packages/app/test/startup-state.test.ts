// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { buildStartupState } from '../src/ui/startup-state.js';
import { ApiError } from '@exulanica/graph-client';

describe('visible Atlas startup states', () => {
  it('explains service failures plainly while preserving authorization and useful contract details', () => {
    for (const error of [new ApiError(500, 'http_500', 'Internal Server Error'),
      new TypeError('Failed to fetch'), new DOMException('Timed out', 'TimeoutError')]) {
      expect(buildStartupState(error).textContent).toContain('The Atlas service is unavailable. Please retry in a moment.');
      expect(buildStartupState(error).textContent).not.toContain('http_500');
    }
    expect(buildStartupState(new ApiError(401, 'unauthorized', 'missing token')).textContent)
      .toContain('This session is not authorized');
    expect(buildStartupState(new Error('Invalid world topology')).textContent).toContain('Invalid world topology');
  });
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
