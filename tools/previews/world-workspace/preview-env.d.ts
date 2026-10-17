// What the world workspace preview's own Vite server hands its modules beyond the app's vite/client types, for the
// preview type check in web/packages/app/test/world-workspace-preview.test.ts.

/** The private capture catalog, checked by front-door-server.mjs (checkedCaptureCatalog) and served as a module. */
declare module 'virtual:front-door-captures' {
  interface Capture {
    readonly entry_id: string;
    readonly world_id: string;
    readonly version_id: string;
    readonly authored_state_sha256: string;
    readonly style_version_id: string;
    readonly file: string;
  }
  const catalog: { readonly profile: 'exulanica.private-world-preview/v1'; readonly captures: readonly Capture[] };
  export default catalog;
}
