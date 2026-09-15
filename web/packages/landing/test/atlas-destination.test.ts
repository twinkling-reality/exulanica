import { describe, expect, it } from 'vitest';

import { resolveAtlasDestination } from '../src/atlas-destination.js';

const landingHref = 'https://exulanica.example/welcome';

describe('the canonical Atlas handoff', () => {
  it('uses an absolute deployment destination exactly', () => {
    const destination = resolveAtlasDestination({
      configured: 'https://atlas.exulanica.example/session',
      landingHref,
    });
    expect(destination?.href).toBe('https://atlas.exulanica.example/session');
  });

  it('supports a same-origin deployment path', () => {
    const destination = resolveAtlasDestination({
      configured: '/atlas',
      landingHref,
    });
    expect(destination?.href).toBe('https://exulanica.example/atlas');
  });

  /*
   * There was a development default pointing at `127.0.0.1:5173`. It put an Enter Exulanica
   * station on the title screen of every local checkout whether or not anything served that port,
   * which is the one thing this module exists to avoid. Local work asks for the handoff by name.
   */
  it('invents no destination in development either', () => {
    expect(
      resolveAtlasDestination({ configured: undefined, landingHref: 'http://127.0.0.1:5174/' }),
    ).toBeNull();
  });

  it('does not invent a production destination', () => {
    expect(
      resolveAtlasDestination({ configured: undefined, landingHref }),
    ).toBeNull();
  });

  it('rejects non-web destinations', () => {
    expect(
      resolveAtlasDestination({
        configured: 'javascript:alert(1)',
        landingHref,
      }),
    ).toBeNull();
  });
});
