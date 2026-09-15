/**
 * The stylesheet is imported for its side effect so that Vite bundles and hashes it. `types` is
 * empty in this package's tsconfig on purpose (nothing here should silently pick up ambient Node
 * or DOM-adjacent globals), so the module shape is declared here rather than pulled in wholesale.
 */
declare module '*.css';

interface ImportMetaEnv {
  readonly DEV: boolean;
  readonly VITE_ATLAS_URL?: string;
  readonly VITE_WAITLIST_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
