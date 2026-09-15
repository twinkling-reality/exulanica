// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest';

import { buildCapabilities } from '../src/ui/capabilities.js';
import { buildPurpose } from '../src/ui/purpose.js';
import { buildResearch } from '../src/ui/research.js';

describe('the signed-out reading surfaces', () => {
  it.each([
    ['purpose', 'Purpose', buildPurpose],
    ['capabilities', 'Capabilities', buildCapabilities],
    ['research', 'Research', buildResearch],
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
    expect(`${purpose.textContent} ${capabilities.textContent}`).not.toMatch(/[\u2014\u2013]/);
    expect(buildResearch().textContent).not.toMatch(/[\u2014\u2013]/);
  });

  it('gives each Research position a named section and leaves the open question open', () => {
    const research = buildResearch();
    const sections = research.querySelectorAll('.capability-section');
    expect(sections).toHaveLength(3);
    for (const section of sections) {
      const heading = section.querySelector('h2');
      expect(heading?.textContent).toBeTruthy();
      expect(section.getAttribute('aria-labelledby')).toBe(heading?.id);
      expect(section.querySelectorAll('p')).toHaveLength(1);
    }
    /*
     * The page states a refusal, a measurement, and what the measurement did not settle. The last
     * one is the rule rather than a nicety: public copy may not turn an unmeasured question into a
     * delivered claim, and coverage across a personal library is the open question this page is
     * closest to over-claiming about.
     */
    expect(research.textContent).toContain('stays an open question');
  });
});
