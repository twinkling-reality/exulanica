/**
 * Announced on the shell when a generated world the page is waiting for can be opened again, every
 * tile baked or one failed, so the page opens it again in place (`../main.ts`) and draws it or says
 * why not: a reload would lose a session that lives only in this page. It names the entry it is
 * for (`GeneratedWorldReady`). A module of its own so the page's entry imports no tile code.
 */
export const GENERATED_WORLD_READY_EVENT = 'exulanica:generated-world-ready';

/** Marks the words saying why a generated world is not drawn yet: `baking` or `failed`. */
export const GENERATED_WORLD_WAITING_ATTRIBUTE = 'data-generated-world-waiting';

/** What the ready event carries: the entry whose world can be opened again. */
export interface GeneratedWorldReady {
  readonly entryId: string;
}
