import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

/**
 * TEST-ONLY dev server for the generated tile material bench. Never built.
 *
 * The committed texture sets are served straight from `assets/textures` through Vite's `/@fs/`
 * route, so the bench reads exactly the bytes the manifest pins. PlayCanvas is pinned to its release
 * build for the reason `../../vite.config.ts` gives.
 */
const here = dirname(fileURLToPath(import.meta.url));
const repository = resolve(here, '../../../../..');
const textures = resolve(repository, 'assets/textures');

export default defineConfig({
  root: here,
  define: { __TEXTURE_ROOT__: JSON.stringify(`/@fs${textures}`) },
  server: {
    port: 5191,
    strictPort: true,
    fs: { strict: true, allow: [resolve(repository, 'web'), textures] },
  },
  resolve: {
    alias: { playcanvas: 'playcanvas/build/playcanvas/src/index.js' },
  },
  optimizeDeps: { exclude: ['playcanvas'] },
});
