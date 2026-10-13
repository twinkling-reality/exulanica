/** One decorative companion follows attention within each navigation disclosure. */
import {
  companionAppearanceConfiguration, companionAvatarBlueprint, DEFAULT_COMPANION,
  type CompanionColorVariant,
} from '@exulanica/presentation/companion';

let instance = 0;

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attributes: Record<string, string> = {}): SVGElementTagNameMap[K] {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

export interface MenuCompanion {
  readonly root: SVGSVGElement;
  setOpen(open: boolean): void;
}

export function createMenuCompanion(panel: HTMLElement, rows: readonly HTMLAnchorElement[], color: CompanionColorVariant): MenuCompanion {
  const appearance = companionAppearanceConfiguration({ body: DEFAULT_COMPANION.bodyVariant, color, face: 'wide' });
  const blueprint = companionAvatarBlueprint(appearance);
  const id = `menu-companion-${++instance}`;
  const root = svg('svg', { class: 'menu-companion', viewBox: blueprint.viewBox, 'aria-hidden': 'true', focusable: 'false' });
  const defs = svg('defs');
  const light = svg('radialGradient', { id, cx: '32%', cy: '26%', r: '74%' });
  for (const [offset, tone] of [
    ['0%', `color-mix(in oklab, ${appearance.bodyColor} 25%, white)`],
    ['32%', `color-mix(in oklab, ${appearance.bodyColor} 65%, white)`],
    ['65%', appearance.bodyColor],
    ['88%', `color-mix(in oklab, ${appearance.bodyColor} 68%, #182449)`],
    ['100%', `color-mix(in oklab, ${appearance.bodyColor} 78%, #cdeefa)`],
  ] as const) light.append(svg('stop', { offset, 'stop-color': tone }));
  const sheen = svg('radialGradient', { id: `${id}-sheen`, cx: '33%', cy: '19%', r: '45%' });
  sheen.append(svg('stop', { offset: '0%', 'stop-color': 'white', 'stop-opacity': '.55' }),
    svg('stop', { offset: '100%', 'stop-color': 'white', 'stop-opacity': '0' }));
  defs.append(light, sheen);
  const drift = svg('g', { class: 'menu-companion-drift' });
  const figure = svg('g', { class: 'menu-companion-figure' });
  figure.append(svg('path', { class: 'menu-companion-body', d: blueprint.bodyPath, fill: `url(#${id})` }),
    svg('path', { class: 'menu-companion-sheen', d: blueprint.bodyPath, fill: `url(#${id}-sheen)` }));
  const gaze = svg('g', { class: 'menu-companion-gaze' });
  const eyes = svg('g', { class: 'menu-companion-eyes', fill: appearance.eyeColor });
  for (const [x, y, width, height, rotation] of [blueprint.eyePose.left, blueprint.eyePose.right]) {
    eyes.append(svg('rect', {
      x: String(x), y: String(y), width: String(width), height: String(height), rx: String(width / 2),
      transform: `rotate(${rotation} ${x + width / 2} ${y + height / 2})`,
    }));
  }
  gaze.append(eyes); figure.append(gaze); drift.append(figure); root.append(defs, drift);

  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const size = 24;
  const clamp = (value: number, low: number, high: number): number => Math.max(low, Math.min(high, value));
  let opened = false;
  let hovered: HTMLAnchorElement | null = null;
  let focused: HTMLAnchorElement | null = null;
  let mode: 'pointer' | 'keyboard' = 'pointer';
  let frame = 0;
  let previousTime = 0;
  let elapsed = 0;
  let pointer: { x: number; y: number } | null = null;
  let bounds = new DOMRect();
  let targetY = 0;
  let x = 0, y = 0, vx = 0, vy = 0;
  let attending = false;

  const render = (): void => {
    root.style.setProperty('--companion-x', `${x.toFixed(2)}px`);
    root.style.setProperty('--companion-y', `${y.toFixed(2)}px`);
    const gazeX = mode === 'keyboard' && attending ? -1 : pointer
      ? clamp((pointer.x - bounds.right + size / 2 - x) / 100, -1, 1) : Math.sin(elapsed * .7) * .35;
    const gazeY = pointer ? clamp((pointer.y - bounds.top - y - size / 2) / 80, -1, 1) : 0;
    root.style.setProperty('--gaze-x', `${gazeX * 24}px`);
    root.style.setProperty('--gaze-y', `${gazeY * 18}px`);
    root.style.setProperty('--attention-turn', `${clamp(vx * .7 + gazeX * 5, -9, 9)}deg`);
  };
  const animate = (time: number): void => {
    if (!opened || motion.matches) return;
    const dt = previousTime ? Math.min((time - previousTime) / 1000, .032) : 1 / 60;
    previousTime = time;
    elapsed += dt;
    const travel = Math.max(0, bounds.height - size);
    // A bounded, continuous idle path stays in the empty margin beside the labels.
    const desiredY = attending ? targetY : travel / 2 + Math.sin(elapsed * .8) * Math.min(22, travel / 2);
    const desiredX = attending ? -2 : Math.sin(elapsed * .55) * 5;
    // Retain velocity when attention changes so the character steers instead of restarting.
    vx += ((desiredX - x) * 75 - vx * 17) * dt;
    vy += ((desiredY - y) * 75 - vy * 17) * dt;
    x += vx * dt;
    y = clamp(y + vy * dt, 0, travel);
    render();
    frame = requestAnimationFrame(animate);
  };
  const position = (): void => {
    if (!opened) return;
    const active = mode === 'keyboard' ? focused ?? hovered : hovered ?? focused;
    bounds = root.parentElement!.getBoundingClientRect();
    const rowBounds = active?.getBoundingClientRect();
    const travel = Math.max(0, bounds.height - size);
    // Measure the row, not its index: wrapping and additional links remain valid.
    targetY = clamp(rowBounds ? rowBounds.top + rowBounds.height / 2 - bounds.top - size / 2 : travel / 2, 0, travel);
    attending = Boolean(active);
    root.dataset.state = attending ? 'attending' : 'resting';
    root.style.setProperty('--companion-target-y', `${targetY}px`);
    if (motion.matches) { x = 0; y = targetY; vx = vy = 0; render(); }
  };
  const changeMotion = (): void => {
    cancelAnimationFrame(frame); frame = 0; previousTime = 0;
    position();
    if (opened && !motion.matches) frame = requestAnimationFrame(animate);
  };
  const observer = new ResizeObserver(position);
  for (const row of rows) {
    row.addEventListener('pointerenter', event => {
      if (event.pointerType !== 'mouse' || !opened) return;
      hovered = row; mode = 'pointer'; position();
    });
    row.addEventListener('pointerleave', () => { if (hovered === row) hovered = null; position(); });
    row.addEventListener('focus', () => { focused = row; mode = 'keyboard'; position(); });
    row.addEventListener('blur', () => { if (focused === row) focused = null; position(); });
  }
  panel.addEventListener('pointermove', event => {
    if (event.pointerType !== 'mouse' || !opened) return;
    pointer = { x: event.clientX, y: event.clientY };
    if (mode !== 'pointer') { mode = 'pointer'; position(); }
  });
  panel.addEventListener('pointerleave', event => {
    if (event.pointerType !== 'mouse') return;
    hovered = null; pointer = null; mode = focused ? 'keyboard' : 'pointer'; position();
  });
  return {
    root,
    setOpen(open) {
      if (opened === open) return;
      opened = open;
      if (open) {
        observer.observe(panel);
        motion.addEventListener('change', changeMotion);
        position();
        x = 0; y = targetY; vx = vy = 0; previousTime = 0;
        render();
        if (!motion.matches) frame = requestAnimationFrame(animate);
      } else {
        observer.disconnect(); cancelAnimationFrame(frame); frame = 0;
        motion.removeEventListener('change', changeMotion);
        hovered = null; focused = null; pointer = null; mode = 'pointer';
        root.dataset.state = 'resting';
      }
    },
  };
}
