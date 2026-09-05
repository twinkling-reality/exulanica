import { defineConfig } from 'vite';

/**
 * The signed-out title, Purpose, and Capabilities surfaces. The canonical Atlas is a configured
 * navigation destination, so this page pays for no renderer and composes no application state.
 */
export default defineConfig({
  build: { target: 'es2022' },
});
