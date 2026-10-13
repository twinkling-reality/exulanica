// @vitest-environment happy-dom
import template from '../index.html?raw';
import { describe, expect, it } from 'vitest';
import { ROUTES } from '../src/router.js';
import { pageMetadata, routeHTML, sitemap } from '../src/page-metadata.js';
describe('direct-link metadata', () => {
  it('gives each canonical route its own title, description, and canonical URL', () => {
    for (const route of ROUTES) {
      const html = new DOMParser().parseFromString(routeHTML(template, route), 'text/html');
      const data = pageMetadata(route);
      expect(html.title).toBe(data.title);
      expect(html.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(data.canonical);
      for (const name of ['description','og:description','twitter:description']) expect(html.querySelector(`meta[name="${name}"],meta[property="${name}"]`)?.getAttribute('content')).toBe(data.description);
      expect(sitemap()).toContain(`<loc>${data.canonical}</loc>`);
    }
    expect(sitemap()).not.toMatch(/roadmap|waitlist|journal/);
  });
});
