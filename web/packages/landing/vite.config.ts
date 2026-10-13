import { readFileSync } from 'node:fs';
import { Window } from 'happy-dom';
import { readingFiles } from './src/content/reading-catalog.js';
import { defineConfig } from 'vite';
import { ROUTES, REDIRECTS, resolveRoute } from './src/router.js';
import { routeHTML, sitemap } from './src/page-metadata.js';

function exportsForReaders(): Map<string, string> {
  const previous = globalThis.document;
  const window = new Window();
  try {
    globalThis.document = window.document as unknown as Document;
    const files = readingFiles();
    files.set('/openapi.json', readFileSync(new URL('../../../tests/snapshots/api-openapi.json', import.meta.url), 'utf8'));
    return files;
  } finally {
    if (previous) globalThis.document = previous;
    else Reflect.deleteProperty(globalThis, 'document');
    void window.happyDOM.close();
  }
}

export default defineConfig({
  build: { target: 'es2022' },
  plugins: [{
    name: 'public-page-metadata',
    enforce: 'post',
    configureServer(server) {
      const files = exportsForReaders();
      server.middlewares.use((request, response, next) => {
        const path = new URL(request.url ?? '/', 'http://localhost').pathname;
        const body = files.get(path);
        if (body === undefined) return next();
        response.setHeader('Content-Type', path.endsWith('.json') ? 'application/json; charset=utf-8' : 'text/plain; charset=utf-8');
        response.end(body);
      });
    },
    configurePreviewServer(server) {
      // Match the published _headers rules while serving the built export bytes.
      server.middlewares.use((request, response, next) => {
        const path = new URL(request.url ?? '/', 'http://localhost').pathname;
        if (path.endsWith('.md')) response.setHeader('Content-Type', 'text/plain; charset=utf-8');
        next();
      });
    },
    generateBundle(_options, bundle) {
      for (const [path, source] of exportsForReaders()) this.emitFile({ type: 'asset', fileName: path.slice(1), source });
      const index = bundle['index.html'];
      if (!index || index.type !== 'asset') throw new Error('Expected the public index document');
      const template = String(index.source);
      index.source = routeHTML(template, ROUTES[0]);
      for (const route of ROUTES.slice(1)) this.emitFile({ type: 'asset', fileName: `${route.path.slice(1)}/index.html`, source: routeHTML(template, route) });
      for (const path of Object.keys(REDIRECTS)) this.emitFile({ type: 'asset', fileName: `${path.slice(1)}/index.html`, source: routeHTML(template, resolveRoute(new URL(path, 'https://exulanica.com'))) });
      this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: sitemap() });
    },
  }],
});
