// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';

import { buildCapabilities } from '../src/ui/capabilities.js';
import { buildPurpose } from '../src/ui/purpose.js';

describe('the signed-out reading surfaces', () => {
  it.each([
    ['purpose', 'Purpose', buildPurpose],
    ['capabilities', 'Capabilities', buildCapabilities],
  ] as const)('keeps %s accessible with a named page', (id, name, build) => {
    const page = build();
    expect(page.id).toBe(id);
    const heading = page.querySelector('h1');
    expect(heading?.textContent).toBe(name);
    expect(heading?.classList.contains('sr-only')).toBe(true);
    expect(page.getAttribute('aria-labelledby')).toBe(heading?.id);
    expect(page.querySelector('hr, strong, em, a')).toBeNull();
  });

  it('keeps Purpose uninterrupted and gives each Capabilities outcome a named section', () => {
    const purpose = buildPurpose();
    const capabilities = buildCapabilities();
    expect(purpose.querySelectorAll('p')).toHaveLength(1);
    expect(purpose.querySelector('h2')).toBeNull();
    const sections = capabilities.querySelectorAll('.capability-section');
    expect(sections).toHaveLength(2);
    for (const section of sections) {
      const heading = section.querySelector('h2');
      expect(heading?.textContent).toBeTruthy();
      expect(section.getAttribute('aria-labelledby')).toBe(heading?.id);
      expect(section.querySelectorAll('p')).toHaveLength(1);
    }
    expect(capabilities.textContent).toContain('World Memory Package');
    expect(`${purpose.textContent} ${capabilities.textContent}`).not.toMatch(/[—–]/);
  });
});
