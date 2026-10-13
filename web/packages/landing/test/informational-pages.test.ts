// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest';
import { buildTitle } from '../src/ui/title.js';
import { buildUseCases, buildUseCase } from '../src/ui/use-cases.js';
import { USE_CASES } from '../src/content/use-cases.js';
import { buildChrome } from '../src/ui/chrome.js';
import { buildProduct, buildProductCapabilities } from '../src/ui/product.js';
import { buildJournal, buildJournalArticle } from '../src/ui/journal.js';
import { buildDocumentation } from '../src/ui/documentation.js';
import { DOCUMENTS } from '../src/ui/docs/catalog.js';
import { JOURNAL } from '../src/content/journal.js';
import { readingFiles } from '../src/content/reading-catalog.js';
import { resolveRoute } from '../src/router.js';

afterEach(() => document.body.replaceChildren());
const pages = () => [buildTitle(), buildUseCases(), ...USE_CASES.map(buildUseCase), buildProduct(), buildProductCapabilities(), buildJournal(), ...JOURNAL.map(buildJournalArticle), ...DOCUMENTS.map(doc => buildDocumentation(doc.key))];
describe('the public site', () => {
  it('keeps journey routes, headings, return navigation and guide paths consistent', () => {
    const directory = buildUseCases().querySelector('nav[aria-label="Use case journeys"]')!;
    const destinations = directory.querySelectorAll<HTMLAnchorElement>('a');
    expect(destinations).toHaveLength(USE_CASES.length);
    for (const item of USE_CASES) {
      const page = buildUseCase(item);
      const link = [...destinations].find(link => link.pathname === `/use-cases/${item.key}`)!;
      expect(resolveRoute(new URL(link.href)).surface).toBe(page.id);
      expect(link.querySelector('h2')?.textContent).toBe(page.querySelector('h1')?.textContent);
      expect(page.getAttribute('aria-labelledby')).toBe(page.querySelector('h1')?.id);
      const back = page.querySelector<HTMLAnchorElement>('a[href="/use-cases"]')!;
      expect(resolveRoute(new URL(back.href)).surface).toBe('use-cases');
      const guides = page.querySelector(`nav[aria-label="${item.title} documentation"]`)!;
      expect([...guides.querySelectorAll('a')].map(link => link.getAttribute('href'))).toEqual([item.href,...item.guides.map(guide => guide.href)]);
      expect(page.querySelectorAll('h1')).toHaveLength(1);
    }
  });
  it('has valid page, local link and fragment destinations with no retired navigation', () => {
    const exports = readingFiles();
    exports.set('/openapi.json', '');
    const surfaces = pages();
    document.body.append(...surfaces);
    for (const page of surfaces) {
      expect(page.getAttribute('aria-labelledby')).toBe(page.querySelector('h1')?.id);
      expect(page.querySelector('form, input[type="email"]')).toBeNull();
    }
    const navigation = buildChrome().root;
    document.body.append(navigation);
    for (const page of [...surfaces, navigation]) {
      for (const link of page.querySelectorAll<HTMLAnchorElement>('a[href^="/"]')) {
        if (exports.has(link.pathname)) continue;
        expect(resolveRoute(new URL(link.href)).surface).not.toBe('not-found');
        expect(['/worlds','/developers','/research','/roadmap','/waitlist']).not.toContain(link.pathname);
        if (link.hash) expect(document.getElementById(link.hash.slice(1))).not.toBeNull();
      }
    }
    const ids = [...document.querySelectorAll('[id]')].map(node => node.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
