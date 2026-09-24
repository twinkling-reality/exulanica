/**
 * How a request names the world it reads or changes: the `world_id` query parameter every world
 * route requires. A workspace can hold several worlds and the server has no default one, so a
 * world client is constructed with the world it serves and every world request carries it.
 * `GET /worlds` lists the worlds a workspace holds.
 */
export function worldPath(path: string, worldId: string): string {
  if (worldId.length === 0) throw new TypeError('A world request needs the id of its world.');
  return `${path}${path.includes('?') ? '&' : '?'}world_id=${encodeURIComponent(worldId)}`;
}

/** A request refused before it leaves the browser, because no world is open for it to name. */
export class NoOpenWorld extends Error {
  readonly code = 'no_open_world';

  constructor(subject: string) {
    super(`No world is open, so there is no ${subject}.`);
    this.name = 'NoOpenWorld';
  }
}

/**
 * `path` in the open world. A client constructed where no world is open, as in the preview, is
 * given null, and refuses each request with `NoOpenWorld` rather than sending one the server would
 * refuse for naming no world.
 */
export function openWorldPath(path: string, worldId: string | null, subject: string): string {
  if (worldId === null) throw new NoOpenWorld(subject);
  return worldPath(path, worldId);
}
