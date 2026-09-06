// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { createGradientForms } from '../src/ui/gradient-forms/index.js';
import { layoutForms } from '../src/ui/gradient-forms/geometry.js';
import { HOME_FORMS } from '../src/ui/gradient-forms/presets.js';

describe('gradient form geometry and reusable instances', () => {
  it('keeps the home artwork still and uses filter-free grain with clear interiors', () => {
    const art = createGradientForms(HOME_FORMS).element;
    expect(art.dataset['motion']).toBe('still');
    expect(art.querySelector('filter, feTurbulence')).toBeNull();
    expect(art.querySelector('pattern circle')).not.toBeNull();
    expect(art.querySelectorAll('radialGradient')).toHaveLength(6);
    for (const gradient of art.querySelectorAll('radialGradient')) {
      expect(gradient.lastElementChild?.getAttribute('stop-opacity')).toBe('0');
    }
    expect(art.querySelector('[id$="-rim"]')).toBeNull();
  });

  /*
   * The home artwork paints once and is never invalidated again.
   *
   * It is drawn at 120vw and the informational surfaces scale it by 2.5, which on a 1728 by 996
   * retina viewport is about 93 megapixels of device pixels carrying a clip path, an alpha mask
   * and a soft-light grain. A per-field drift was built here and removed after it made the page
   * flicker on the Purpose surface: nothing inside a form may animate. The color cross-fade is
   * the one sanctioned motion because it changes an opacity on a layer that is already
   * rasterized. This test states that so the next attempt starts from the measurement.
   */
  it('gives the home artwork no per-element animation hook to invalidate it with', () => {
    const art = createGradientForms(HOME_FORMS).element;
    expect(art.querySelectorAll('.gradient-forms-field')).toHaveLength(0);
    for (const node of art.querySelectorAll('[style]')) {
      expect(node.getAttribute('style'), `${node.tagName} carries a styling hook`).toBe(
        'mask-type:alpha',
      );
    }
    expect(
      new Set(Array.from(art.querySelectorAll('[class]'), (node) => node.getAttribute('class'))),
    ).toEqual(new Set(['gradient-forms-base', 'gradient-forms-grain']));
  });

  it('places attached rims at their exact requested gap and never intersects other forms', () => {
    const { forms } = layoutForms(HOME_FORMS.forms);
    expect(forms).toHaveLength(2);
    expect(forms[1]?.attach?.gap).toBe(8);
    for (const form of forms) {
      for (const other of forms) {
        if (other.id === form.id) continue;
        expect(Math.hypot(form.x - other.x, form.y - other.y) + 1e-6).toBeGreaterThanOrEqual(form.radius + other.radius);
      }
      if (form.attach) {
        const parent = forms.find((item) => item.id === form.attach?.to)!;
        expect(Math.hypot(form.x - parent.x, form.y - parent.y) - form.radius - parent.radius).toBeCloseTo(form.attach.gap);
      }
    }
  });

  it('rejects a collision with a non-parent circle', () => {
    expect(() => layoutForms([
      { id: 'a', radius: 10, light: 0 },
      { id: 'b', radius: 10, light: 0, attach: { to: 'a', angle: 0, gap: 1 } },
      { id: 'c', radius: 10, light: 0, attach: { to: 'b', angle: 180, gap: 1 } },
    ])).toThrow('intersect');
  });

  it('keeps independent SVG references valid when multiple variants appear on the same page', () => {
    const a = createGradientForms(HOME_FORMS);
    const b = createGradientForms({ ...HOME_FORMS, forms: [HOME_FORMS.forms[0]!], materials: { upper: HOME_FORMS.materials!['upper']! }, motion: 'still' });
    const idsA = new Set(Array.from(a.element.querySelectorAll('[id]'), (node) => node.id));
    for (const node of b.element.querySelectorAll('[id]')) expect(idsA.has(node.id)).toBe(false);
    for (const root of [a.element, b.element]) {
      for (const node of root.querySelectorAll('[fill], [mask], [clip-path], [filter]')) {
        for (const attr of ['fill', 'mask', 'clip-path', 'filter']) {
          const match = node.getAttribute(attr)?.match(/^url\(#(.+)\)$/);
          if (match) expect(root.querySelector(`[id="${match[1]}"]`)).not.toBeNull();
        }
      }
      expect(root.getAttribute('aria-hidden')).toBe('true');
    }
    expect(a.element.getAttribute('viewBox')).not.toBe(b.element.getAttribute('viewBox'));
    expect(b.element.dataset['motion']).toBe('still');
  });

  it('renders equivalent geometry independently of the chosen art unit scale', () => {
    const a = createGradientForms(HOME_FORMS);
    const factor = 0.01;
    const scaled = HOME_FORMS.forms.map((form) => ({
      ...form,
      radius: form.radius * factor,
      ...(form.attach ? { attach: { ...form.attach, gap: form.attach.gap * factor } } : {}),
    }));
    const b = createGradientForms({ ...HOME_FORMS, forms: scaled });
    const original = a.element.getAttribute('viewBox')!.split(' ').map(Number);
    const resized = b.element.getAttribute('viewBox')!.split(' ').map(Number);
    resized.forEach((value, i) => expect(value / factor).toBeCloseTo(original[i]!));
  });

  it('preserves distinct geometry and falloff per color and rejects malformed fields atomically', () => {
    const art = createGradientForms(HOME_FORMS);
    const gradients = Array.from(art.element.querySelectorAll('radialGradient'));
    expect(new Set(gradients.map((g) => g.getAttribute('gradientTransform'))).size).toBe(6);
    const before = art.element.outerHTML;
    const field = HOME_FORMS.materials!['upper']![0]!;
    expect(() => art.update({ ...HOME_FORMS, materials: { upper: [{ ...field, spread: [0, 1] }] } })).toThrow();
    expect(() => art.update({ ...HOME_FORMS, materials: { upper: [{ ...field, falloff: [{ at: 0.8, opacity: 1 }, { at: 0.2, opacity: 0 }] }] } })).toThrow();
    expect(art.element.outerHTML).toBe(before);
  });

  it('updates one instance atomically and leaves existing art intact on invalid input', () => {
    const art = createGradientForms(HOME_FORMS);
    const element = art.element;
    const before = element.outerHTML;
    expect(() => art.update({ ...HOME_FORMS, texture: -1 })).toThrow();
    // Happy DOM's CSS.supports always returns true; exercise the browser rejection contract.
    vi.stubGlobal('CSS', { supports: () => false });
    try {
      expect(() => art.update({ ...HOME_FORMS, palette: ['not-a-color', 'green', 'blue'] })).toThrow();
    } finally {
      vi.unstubAllGlobals();
    }
    expect(element.outerHTML).toBe(before);
    art.update({ ...HOME_FORMS, palette: ['red', 'green', 'blue'], motion: 'still', strength: 0.3 });
    expect(art.element).toBe(element);
    expect(element.querySelector('stop[stop-color="red"]')).not.toBeNull();
    expect(element.dataset['motion']).toBe('still');
  });
});
