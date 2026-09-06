// @vitest-environment happy-dom

import { readFileSync } from 'node:fs';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { buildChrome, STATION_COLOR } from '../src/ui/chrome.js';
import { createCompanionMenuMarker, MENU_FACES } from '../src/ui/companion-menu-marker.js';

// Workspace-root relative, the way viewport-boundary.test.ts reads the stylesheet: this suite
// runs under happy-dom, where `import.meta.url` is not a file URL.
const THEME = readFileSync('packages/landing/src/themes.css', 'utf8');
const PAGE = readFileSync('packages/landing/src/style.css', 'utf8');

const STATIONS = ['path-home', 'path-enter', 'path-purpose', 'path-capabilities', 'path-resources'];

function chrome() {
  const built = buildChrome({
    atlasHref: 'https://atlas.example/session',
    onHome: vi.fn(),
    onPurpose: vi.fn(),
    onCapabilities: vi.fn(),
  });
  document.body.append(built.root);
  return built;
}

describe('the Companion in the title menu', () => {
  beforeEach(() => document.body.replaceChildren());

  it('holds every expression at once and keeps exactly one identity', () => {
    const marker = createCompanionMenuMarker();
    const lids = Array.from(marker.querySelectorAll<SVGGElement>('.companion-menu-blink'));

    expect(lids.map((lid) => lid.dataset['eye'])).toEqual(['left', 'right']);
    for (const lid of lids) {
      expect(
        Array.from(lid.querySelectorAll<SVGGElement>('.companion-menu-face'), (f) => f.dataset['face']),
      ).toEqual([...MENU_FACES]);
    }

    /*
     * One body, one eye colour, at every station. companion-appearance.ts records that a
     * saturated Companion reads as a sticker on the field and that its colour is a preference a
     * person sets, so the menu may vary what it is doing and never what it is.
     */
    expect(marker.querySelectorAll('.companion-menu-body')).toHaveLength(1);
    const inks = new Set(
      Array.from(marker.querySelectorAll('.companion-menu-eye'), (eye) => eye.getAttribute('fill')),
    );
    expect(inks.size).toBe(1);

    // Each held pose is distinct geometry, so revealing one is a real change of face.
    const poses = Array.from(
      marker.querySelectorAll('.companion-menu-blink[data-eye="left"] .companion-menu-eye'),
      (eye) => `${eye.getAttribute('y')}/${eye.getAttribute('height')}/${eye.getAttribute('transform')}`,
    );
    expect(new Set(poses).size).toBe(MENU_FACES.length);
    expect(marker.dataset['face']).toBe('neutral');
  });

  it('wears a different face at every station', () => {
    const built = chrome();
    built.setSurface('title');
    const marker = built.root.querySelector<SVGSVGElement>('.companion-menu-marker')!;

    const worn = new Map<string, string | undefined>();
    for (const id of ['path-enter', 'path-purpose', 'path-capabilities', 'path-resources']) {
      built.root.querySelector(`#${id}`)?.dispatchEvent(new PointerEvent('pointerenter'));
      worn.set(id, marker.dataset['face']);
    }
    built.setSurface('purpose');
    built.root.querySelector('#path-home')?.dispatchEvent(new PointerEvent('pointerenter'));
    worn.set('path-home', marker.dataset['face']);

    expect(worn.size).toBe(STATIONS.length);
    expect(new Set(worn.values()).size).toBe(STATIONS.length);
    for (const face of worn.values()) expect(MENU_FACES).toContain(face);
  });

  it('blinks on arrival so a pose never changes in the open', () => {
    const built = chrome();
    built.setSurface('title');
    const marker = built.root.querySelector<SVGSVGElement>('.companion-menu-marker')!;

    built.root.querySelector('#path-purpose')?.dispatchEvent(new PointerEvent('pointerenter'));
    const first = marker.dataset['arrive'];
    expect(first).toMatch(/^[ab]$/);

    built.root.querySelector('#path-capabilities')?.dispatchEvent(new PointerEvent('pointerenter'));
    // The phase has to flip, or the second arrival reuses a finished animation and never plays.
    expect(marker.dataset['arrive']).not.toBe(first);

    // The reveal is parked inside the arrival blink's shut window, not before or after it.
    expect(PAGE).toContain('transition: visibility 0s 120ms');
    const arrive = PAGE.slice(PAGE.indexOf('@keyframes companion-arrive-a'));
    expect(arrive).toContain('34%, 66% { transform: scaleY(0.05); }');
  });

  it('gives every station its own light', () => {
    const accents = [...THEME.matchAll(/--landing-station-([\w-]+):\s*(#[0-9a-f]{6})/g)];
    expect(accents).toHaveLength(STATIONS.length);
    expect(new Set(accents.map((match) => match[2])).size).toBe(STATIONS.length);

    for (const station of STATIONS) {
      expect(PAGE).toContain(`#${station}`);
      expect(PAGE).toContain(`.companion-menu-marker[data-target='${station}']`);
    }
    expect(PAGE).toContain('--companion-wake-near');
  });

  /*
   * EXPERIMENT, see STATION_COLOR in chrome.ts. The colours must come from the appearance
   * contract rather than from hexes typed into the menu, so that whatever is decided about this
   * later is decided in one place.
   */
  it('asks the appearance contract for a distinct colour at each station', () => {
    expect(Object.keys(STATION_COLOR).sort()).toEqual([...STATIONS].sort());
    expect(new Set(Object.values(STATION_COLOR)).size).toBe(STATIONS.length);

    const marker = createCompanionMenuMarker();
    expect(marker.querySelector('.companion-menu-body')?.getAttribute('fill')).toMatch(
      /^var\(--companion-body, #[0-9a-f]{6}\)$/,
    );
    for (const held of marker.querySelectorAll('.companion-menu-eye')) {
      expect(held.getAttribute('fill')).toMatch(/^var\(--companion-eye, #[0-9a-f]{6}\)$/);
    }

    const built = chrome();
    built.setSurface('title');
    const live = built.root.querySelector<SVGSVGElement>('.companion-menu-marker')!;
    const inks = new Set<string>();
    for (const id of STATIONS.slice(1)) {
      built.root.querySelector(`#${id}`)?.dispatchEvent(new PointerEvent('pointerenter'));
      inks.add(live.style.getPropertyValue('--companion-body'));
    }
    expect(inks.size).toBe(STATIONS.length - 1);
    for (const ink of inks) expect(ink).toMatch(/^#[0-9a-f]{6}$/);
  });

  /*
   * The marker stands to the left of every label, so a Companion looking straight ahead looks
   * past the entry it is marking. Every station must pull the gaze toward the text, and no two
   * stations may hold the body the same way, or the character is one pose with five captions.
   */
  it('looks toward the menu at every station and holds itself differently at each', () => {
    const postures = STATIONS.map((station) => {
      const rule = PAGE.slice(PAGE.indexOf(`.companion-menu-marker[data-target='${station}']`));
      const body = rule.slice(0, rule.indexOf('}'));
      const read = (name: string): number => {
        const found = body.match(new RegExp(`--companion-${name}:\\s*(-?[\\d.]+)`));
        expect(found, `${station} declares no --companion-${name}`).not.toBeNull();
        return Number(found![1]);
      };
      return { station, tilt: read('tilt'), x: read('gaze-x'), y: read('gaze-y') };
    });

    for (const posture of postures) {
      expect(posture.x, `${posture.station} does not look toward its label`).toBeGreaterThan(0);
    }
    const shapes = new Set(postures.map((p) => `${p.tilt}/${p.x}/${p.y}`));
    expect(shapes.size).toBe(STATIONS.length);
  });

  it('takes the station mark away from under the Companion', () => {
    const built = chrome();
    built.setSurface('title');

    const enter = built.root.querySelector<HTMLElement>('#path-enter')!;
    const purpose = built.root.querySelector<HTMLElement>('#path-purpose')!;
    expect(enter.dataset['companion']).toBe('here');

    purpose.dispatchEvent(new PointerEvent('pointerenter'));
    expect(purpose.dataset['companion']).toBe('here');
    // Exactly one mark may be standing down at a time.
    expect(enter.dataset['companion']).toBeUndefined();
    expect(built.root.querySelectorAll('[data-companion="here"]')).toHaveLength(1);

    expect(PAGE).toContain(".destination[data-companion='here']::after");
  });
});
