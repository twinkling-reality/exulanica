/** The deployment-owned boundary between the public landing page and whoever holds the list. */

export interface WaitlistDestinationInput {
  readonly configured: string | undefined;
  readonly development: boolean;
  readonly landingHref: string;
}

/** Hosts where an unencrypted endpoint is a developer's own machine rather than the open wire. */
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);

/**
 * Resolve the waitlist endpoint, or nothing at all.
 *
 * Two rules separate this from the Atlas handoff, and both are deliberate.
 *
 * There is no development default. The Atlas default points a visitor at a port on their own
 * machine, which is harmless when it is missing. A waitlist default would post somebody's email
 * address to whatever happened to be listening, so an unconfigured build says the list is not open
 * instead of guessing at one.
 *
 * The endpoint must be https, because the request carries an email address. The one exception is a
 * loopback host in development, so the form can be exercised end to end against a local stub
 * without a certificate. Anything else resolves to null and the surface says so.
 */
export function resolveWaitlistDestination(input: WaitlistDestinationInput): URL | null {
  const configured = input.configured?.trim();
  if (configured === undefined || configured === '') return null;

  let endpoint: URL;
  try {
    endpoint = new URL(configured, input.landingHref);
  } catch {
    return null;
  }

  if (endpoint.protocol === 'https:') return endpoint;
  if (endpoint.protocol === 'http:' && input.development && LOOPBACK.has(endpoint.hostname)) {
    return endpoint;
  }
  return null;
}

export function waitlistDestinationFromEnvironment(landingHref: string): URL | null {
  return resolveWaitlistDestination({
    configured: import.meta.env.VITE_WAITLIST_URL,
    development: import.meta.env.DEV,
    landingHref,
  });
}
