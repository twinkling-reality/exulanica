import { build, loadConfigFromFile } from '../../../web/packages/app/node_modules/vite/dist/node/index.js';
import { fileURLToPath } from 'node:url';
import { writeFileSync, readFileSync, copyFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
const root = fileURLToPath(new URL('../../../', import.meta.url)).replace(/\/$/, '');
const here = fileURLToPath(new URL('.', import.meta.url)).replace(/\/$/, '');
process.env.VITE_ATLAS_URL = 'http://127.0.0.1:19972/?workspace=1';
const loaded = await loadConfigFromFile({ command: 'build', mode: 'production' }, root + '/web/packages/landing/vite.config.ts');
const plugin = {
  name: 'private-home-route', enforce: 'pre',
  transform(code, id) {
    if (id !== root + '/web/packages/landing/src/router.ts') return;
    const hook = '  const path = canonicalURL(url).pathname;';
    if (!code.includes(hook)) throw Error('Public home route seam changed.');
    return code.replace(hook, `  if (url.searchParams.has('workspace')) return { path: url.pathname, surface: 'not-found', title: 'Exulanica' };
  const path = canonicalURL(url).pathname.replace(/^\\/home(?=\\/|$)/, '') || '/';`);
  },
};
await build({ ...loaded.config, configFile: false, root: root + '/web/packages/landing', base: '/review-home-assets/', plugins: [plugin, ...(loaded.config.plugins || [])], build: { ...loaded.config.build, outDir: here + '/home-dist', emptyOutDir: true } });
copyFileSync(here + '/private-home.css', here + '/home-dist/private-home.css');
copyFileSync(here + '/navigation-material.css', here + '/home-dist/navigation-material.css');
writeFileSync(here + '/home-dist/private-home.js', `
function prefixLinks() {
  for (const link of document.querySelectorAll('a[href]')) {
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin || url.searchParams.has('workspace') || url.pathname === '/home' || url.pathname.startsWith('/home/')) continue;
    if (link.getAttribute('href').startsWith('#')) continue;
    url.pathname = '/home' + (url.pathname === '/' ? '' : url.pathname);
    link.href = url.href;
  }
}
new MutationObserver(prefixLinks).observe(document.body, {childList:true,subtree:true});
prefixLinks();
`);
const index = here + '/home-dist/index.html';
writeFileSync(index, readFileSync(index, 'utf8').replace('</body>', '<script type="module" src="/review-home-assets/private-home.js"></script></body>'));
writeFileSync(here + '/home-build.json', JSON.stringify({ built_at_utc: new Date().toISOString(), source: 'Current web/packages/landing source, private route adapter only', output: here + '/home-dist', index_sha256: createHash('sha256').update(readFileSync(index)).digest('hex'), entry: '/home', app: '/?workspace=1', production_sources_edited: false }, null, 2) + '\n');
