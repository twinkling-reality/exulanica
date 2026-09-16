// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { companionAppearanceConfiguration } from '@exulanica/presentation';
import { buildCompanionStage } from '../src/ui/companion-stage.js';

afterEach(() => {
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

function mediaQuery(reducedMotion: boolean): MediaQueryList {
  return {
    matches: reducedMotion,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => true),
  } satisfies MediaQueryList;
}

describe('the geometric Companion stage', () => {
  it('can be built detached for one-time docking in the encounter toolbar', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery(false));
    const stage = buildCompanionStage();
    expect(stage.root.isConnected).toBe(false);
    stage.dispose();
  });

  it('renders one silhouette and two slit eyes with no robot anatomy or second renderer', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery(false));
    const parent = document.createElement('div');
    document.body.append(parent);
    const stage = buildCompanionStage({ parent });

    expect(stage.root.dataset['renderer']).toBe('svg');
    expect(stage.root.querySelector('.companion-avatar')).toBeInstanceOf(SVGElement);
    expect(stage.root.querySelectorAll('.companion-avatar-body')).toHaveLength(1);
    expect(stage.root.querySelectorAll('.companion-avatar-eye')).toHaveLength(2);
    expect(stage.root.querySelector('canvas')).toBeNull();
    expect(stage.root.querySelector('[class*="arm"], [class*="leg"], [class*="mouth"]')).toBeNull();

    stage.show();
    expect(stage.visible()).toBe(true);
    expect(stage.root.hasAttribute('data-ready')).toBe(true);
    stage.hide();
    expect(stage.visible()).toBe(false);
  });

  it('applies only verified shape, colour, and expression choices', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery(false));
    const parent = document.createElement('div');
    document.body.append(parent);
    const stage = buildCompanionStage({ parent });
    stage.setAppearance(companionAppearanceConfiguration({
      body: 'cloud', color: 'periwinkle', face: 'curious',
    }));

    expect(stage.root.dataset['shape']).toBe('cloud');
    expect(stage.root.dataset['color']).toBe('periwinkle');
    expect(stage.root.dataset['face']).toBe('curious');
    expect(stage.root.getAttribute('aria-label')).toContain('periwinkle cloud');
    expect(stage.root.querySelector('.companion-avatar-body')?.getAttribute('fill')).toBe('#637ff2');
  });

  it('uses three dots for working and freezes motion under reduced motion', () => {
    const media = mediaQuery(true);
    vi.spyOn(window, 'matchMedia').mockReturnValue(media);
    const parent = document.createElement('div');
    document.body.append(parent);
    const stage = buildCompanionStage({ parent });

    stage.setState('working');
    stage.show();
    expect(stage.root.dataset['state']).toBe('working');
    expect(stage.root.hasAttribute('data-reduced-motion')).toBe(true);
    expect(stage.root.querySelectorAll('.companion-avatar-dot')).toHaveLength(3);

    stage.dispose();
    expect(media.removeEventListener).toHaveBeenCalledOnce();
  });

  it('lets the slit eyes follow the pointer without moving the silhouette', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery(false));
    const parent = document.createElement('div');
    document.body.append(parent);
    const stage = buildCompanionStage({ parent });
    vi.spyOn(stage.root, 'getBoundingClientRect').mockReturnValue({
      left: 500, top: 80, width: 200, height: 200,
      right: 700, bottom: 280, x: 500, y: 80, toJSON: () => ({}),
    });

    stage.show();
    window.dispatchEvent(new PointerEvent('pointermove', { clientX: 1000, clientY: 500 }));
    expect(stage.root.querySelector('.companion-avatar-gaze')?.getAttribute('transform'))
      .toMatch(/^translate\(/);
    expect(stage.root.querySelector('.companion-avatar-body')?.hasAttribute('transform')).toBe(false);
  });
});
