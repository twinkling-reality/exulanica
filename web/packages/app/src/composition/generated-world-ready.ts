/**
 * Announced on the shell once every tile of a generated world the page is waiting for is baked,
 * so the page opens the world again in place (`../main.ts`): a reload would lose a session that
 * lives only in this page. A module of its own so the page's entry imports no tile code.
 */
export const GENERATED_WORLD_READY_EVENT = 'exulanica:generated-world-ready';
