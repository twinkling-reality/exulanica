// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { buildCapabilities } from '../src/ui/capabilities.js';
import { buildPurpose } from '../src/ui/purpose.js';
import { buildResearch } from '../src/ui/research.js';
import { buildDevelopers } from '../src/ui/developers.js';

describe('the public reading surfaces', () => {
  it.each([['purpose', buildPurpose], ['capabilities', buildCapabilities], ['research', buildResearch], ['developers', buildDevelopers]] as const)(
    'gives %s a named, focusable page with content', (id, build) => {
      const page = build();
      expect(page.id).toBe(id);
      expect(page.getAttribute('tabindex')).toBe('-1');
      expect(page.getAttribute('aria-labelledby')).toBe(page.querySelector('h1')?.id);
      expect(page.querySelector('h1')?.textContent).toBeTruthy();
      expect(page.querySelector('p')?.textContent).toBeTruthy();
      expect(page.textContent).not.toContain('\u2014');
    },
  );
  it('connects builders to published API and outside-agent guides', () => {
    const links = [...buildDevelopers().querySelectorAll('a')].map((link) => link.getAttribute('href'));
    expect(links).toContain('/docs/agents');
    expect(links).toContain('/docs/world-api');
  });
  it('keeps the research hypothesis explicitly unresolved', () => {
    expect(buildResearch().textContent).toContain('stays an open question');
  });
});
