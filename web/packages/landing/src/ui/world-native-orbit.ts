import { orbitPose } from './world-orbit-geometry.js';

/** The native fallback uses the same track and projection as the canvas. */
export function mountNativeWorldOrbit(root: HTMLElement) {
  const forms = [...root.querySelectorAll<HTMLElement>('.orbit-item')];
  const styles = forms.map(form => form.style.cssText);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let frame = 0, previous = 0, elapsed = 2, disposed = false;
  const draw = (now: number) => {
    frame = 0;
    if (disposed) return;
    const paused = reduced.matches || document.hidden || root.matches(':hover, :focus-within') || root.dataset.selected !== undefined;
    if (previous && !paused) elapsed += Math.min((now - previous) / 1000, .05);
    previous = now;
    const { width, height } = root.getBoundingClientRect();
    forms.forEach(form => {
      const p = orbitPose(Number(form.dataset.orbitIndex), elapsed, width, height);
      const rx = Math.hypot(p.ax, p.bx), ry = Math.hypot(p.ay, p.by);
      form.style.left = `${p.x - rx}px`; form.style.top = `${p.y - ry}px`;
      form.style.width = `${2 * rx}px`; form.style.height = `${2 * ry}px`;
      form.style.setProperty('--world-ring-projection', `matrix(${p.ax / 32},${p.ay / 32},${p.bx / 32},${p.by / 32},0,0)`);
      form.style.setProperty('--native-projection', `matrix(${p.ax / rx},${p.ay / rx},${p.bx / ry},${p.by / ry},0,0)`);
    });
    if (!reduced.matches && !document.hidden) frame = requestAnimationFrame(draw);
  };
  const redraw = () => { previous = 0; if (!disposed && !frame) frame = requestAnimationFrame(draw); };
  const resize = new ResizeObserver(redraw);
  root.classList.add('has-native-orbit'); resize.observe(root);
  reduced.addEventListener('change', redraw); document.addEventListener('visibilitychange', redraw);
  redraw();
  return { redraw, dispose() {
    disposed = true; cancelAnimationFrame(frame); resize.disconnect();
    reduced.removeEventListener('change', redraw); document.removeEventListener('visibilitychange', redraw);
    root.classList.remove('has-native-orbit');
    forms.forEach((form, index) => { form.style.cssText = styles[index]!; });
  } };
}
