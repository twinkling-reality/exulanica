import { recipeDefinition } from '../catalog.js';
import { encodeContainer } from '../container.js';
import { bakeMaps } from '../maps.js';
import {
  type BakeRequest,
  bakeRequestProblems,
  requestedMaker,
} from './request.js';

/**
 * Bake one checked request into a container. The same maker, sampling and container as a
 * published set; only the identity and the licence differ, and both come from the request.
 */
export function bakeWorkspaceRequest(candidate: unknown, licenceSha256: string): Uint8Array {
  const problems = bakeRequestProblems(candidate, licenceSha256);
  if (problems.length > 0) throw new RequestRefused(problems);
  const request = candidate as BakeRequest;
  const maker = requestedMaker(request)!;
  const definition = recipeDefinition(
    {
      setId: request.set_id,
      version: request.version,
      title: request.title,
      summary: request.summary,
      licenceId: request.licence.id,
    },
    request.recipe,
    maker,
  );
  return encodeContainer(definition, bakeMaps(definition), request.licence.sha256);
}

/** A request this package will not bake, with every reason. */
export class RequestRefused extends Error {
  readonly problems: readonly string[];

  constructor(problems: readonly string[]) {
    super(`not a bake request this package will run: ${problems.join('; ')}`);
    this.name = 'RequestRefused';
    this.problems = problems;
  }
}
