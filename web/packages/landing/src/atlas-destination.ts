/** The deployment-owned boundary between the public landing page and the canonical Atlas app. */

export interface AtlasDestinationInput {
  readonly configured: string | undefined;
  readonly landingHref: string;
}

function webDestination(value: string, base: string): URL | null {
  try {
    const destination = new URL(value, base);
    return destination.protocol === 'http:' || destination.protocol === 'https:' ? destination : null;
  } catch {
    return null;
  }
}

/**
 * Resolve an Atlas URL without inventing a topology, in any environment.
 *
 * A deployment provides `VITE_ATLAS_URL`; it may be absolute or relative to the landing page.
 *
 * There is deliberately no development default any more. There used to be one pointing at
 * `127.0.0.1:5173`, which put an Enter Exulanica station on every developer's title screen whether
 * or not anything was serving that port, and led nowhere when nothing was. A station is shown only
 * when somebody has named a destination for it. Local work that wants the handoff says so:
 *
 *     VITE_ATLAS_URL='http://127.0.0.1:5173/?preview=1' pnpm --dir web landing
 */
export function resolveAtlasDestination(input: AtlasDestinationInput): URL | null {
  const configured = input.configured?.trim();
  if (configured === undefined || configured === '') return null;
  return webDestination(configured, input.landingHref);
}

export function atlasDestinationFromEnvironment(landingHref: string): URL | null {
  return resolveAtlasDestination({
    configured: import.meta.env.VITE_ATLAS_URL,
    landingHref,
  });
}
