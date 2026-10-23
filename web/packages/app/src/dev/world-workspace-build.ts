// The world workspace (tools/previews/world-workspace) in the app's production build. Its development server
// (serve.mjs) edits main.ts, environment-selection.ts and bootstrap.ts as Vite serves them (seams.mjs); a build
// applies the same edits, so a hosted deployment serves the workspace a person's own install shows, not the
// app's shell. Its front door's private captures exist only on a development host: a build holds none, and each
// card shows the picture the browser kept of its world.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { Plugin } from 'vite';

interface Seams { patchSource(file: string, code: string, here: string): string | null }
interface Captures {
  readCaptureCatalog(directory: string | null): unknown;
  capturesModule(catalog: unknown): { resolveId(source: string): string | null; load(id: string): string | null };
}

/** The plugin, for the repository at `repository`; build only, as the development server applies its own. */
export function worldWorkspaceBuild(repository: string): Plugin {
  const here = resolve(repository, 'tools/previews/world-workspace');
  // Plain JavaScript outside this package, loaded by path as the preview's tests load it.
  const module = async <T>(name: string): Promise<T> => import(/* @vite-ignore */ pathToFileURL(resolve(here, name)).href) as Promise<T>;
  let seams: Seams | null = null;
  let captures: ReturnType<Captures['capturesModule']> | null = null;
  return {
    name: 'world-workspace-build',
    apply: 'build',
    enforce: 'pre',
    async buildStart() {
      seams = await module<Seams>('seams.mjs');
      const server = await module<Captures>('front-door-server.mjs');
      captures = server.capturesModule(server.readCaptureCatalog(null));
    },
    resolveId: (source) => captures?.resolveId(source) ?? null,
    load: (id) => captures?.load(id) ?? null,
    transform(code, id) {
      return seams !== null && id.startsWith(repository + '/') ? seams.patchSource(id.slice(repository.length + 1), code, here) : null;
    },
  };
}
