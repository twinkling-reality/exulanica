import { DOCUMENTS } from './ui/docs/catalog.js';
import { USE_CASES } from './content/use-cases.js';
import { JOURNAL } from './content/journal.js';
import { ROUTES, type Route } from './router.js';
const hasMarkdown = (route: Route): boolean => route.path === '/docs' || route.path.startsWith('/docs/') || route.path.startsWith('/blog/');
const DESCRIPTIONS: Readonly<Record<string, string>> = {
  '/': 'Worlds for AI Agents. Create places and inhabitants, shape how they interact, and hand supported roles to open models.',
  '/product': 'Worlds for AI Agents. Build a place, choose open models for the roles the engine registers, and keep its state and recorded decisions.',
  '/product/capabilities': 'Worlds, agents, open models, experiments, and your own agent. Open models for minds. Open source only for the Apache-2.0 software.',
  '/use-cases': 'Agent Experiments, Worldbuilding, and Agent Development.',
  '/blog': 'This site does not publish a blog.',
  '/docs': 'Run Exulanica, work with the World API, and connect outside agents through Python or MCP.',
  '/docs/worlds': 'Create a saved world, place supported objects, and reopen its saved state.',
  '/docs/self-hosting': 'Try the browser preview, or configure a persistent installation with an API, a PostgreSQL database, and a content store. Browser accounts are optional.',
  '/docs/world-api': 'Read and edit versioned worlds, discover supported operations, and handle authorization and validation failures.',
  '/docs/agents': 'Connect an outside agent to authorized turns using an owner-issued key, Python, or MCP.',
};
export function pageMetadata(route: Route): { title: string; description: string; canonical: string } {
  const post = JOURNAL.find(item => route.path === `/blog/${item.slug}`);
  return { title: route.title, description: USE_CASES.find(item => route.path === `/use-cases/${item.key}`)?.summary ?? post?.description ?? DOCUMENTS.find(item => route.path === item.href)?.description ?? DESCRIPTIONS[route.path] ?? 'This address does not match a page on Exulanica.', canonical: `https://exulanica.com${route.path}` };
}
export function updatePageMetadata(route: Route): void {
  const data = pageMetadata(route);
  document.title = data.title;
  document.querySelector('link[data-reading-alternate]')?.remove();
  if (hasMarkdown(route)) {
    const alternate = document.createElement('link');
    alternate.rel = 'alternate'; alternate.type = 'text/plain'; alternate.title = 'Markdown';
    alternate.href = `${route.path}.md`; alternate.dataset.readingAlternate = '';
    document.head.append(alternate);
  }
  document.querySelector('link[rel="canonical"]')?.setAttribute('href', data.canonical);
  for (const [selector, content] of [
    ['meta[name="description"]', data.description], ['meta[property="og:description"]', data.description], ['meta[name="twitter:description"]', data.description],
    ['meta[property="og:title"]', data.title], ['meta[name="twitter:title"]', data.title], ['meta[property="og:url"]', data.canonical],
    ['meta[property="og:type"]', route.path.startsWith('/blog/') ? 'article' : 'website'],
  ]) document.querySelector(selector!)?.setAttribute('content', content!);
}
const escape = (value: string) => value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
/** Shared by build output and the browser; direct links have their own share metadata. */
export function routeHTML(template: string, route: Route): string {
  const data = pageMetadata(route);
  const alternate = hasMarkdown(route) ? `<link rel="alternate" type="text/plain" title="Markdown" data-reading-alternate href="${escape(route.path)}.md">` : '';
  return template.replace('</head>', `${alternate}</head>`).replace(/<title>.*?<\/title>/, `<title>${escape(data.title)}</title>`)
    .replace(/(<link rel="canonical" href=")[^"]+/, `$1${escape(data.canonical)}`)
    .replace(/(<meta\s+(?:name|property)="(?:description|og:description|twitter:description)"\s+content=")[^"]+/, `$1${escape(data.description)}`)
    .replace(/(<meta\s+(?:name|property)="(?:og:description|twitter:description)"\s+content=")[^"]+/g, `$1${escape(data.description)}`)
    .replace(/(<meta (?:property|name)="(?:og:title|twitter:title)" content=")[^"]+/g, `$1${escape(data.title)}`)
    .replace(/(<meta property="og:url" content=")[^"]+/, `$1${escape(data.canonical)}`)
    .replace(/(<meta property="og:type" content=")[^"]+/, `$1${route.path.startsWith('/blog/') ? 'article' : 'website'}`);
}
export const sitemap = () => `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${ROUTES.map(route => `<url><loc>${pageMetadata(route).canonical}</loc></url>`).join('')}</urlset>\n`;
