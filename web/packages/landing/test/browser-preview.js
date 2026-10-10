// Development-only browser fixture, excluded from the production entry.
// Exercises the real landing composition without sending subscriptions.
const scenario = new URLSearchParams(location.search).get('scenario') ?? 'normal';
const media = window.matchMedia.bind(window);
if (scenario === 'reduced') window.matchMedia = query => {
  const result = media(query);
  if (query === '(prefers-reduced-motion: reduce)') Object.defineProperty(result, 'matches', { value: true });
  return result;
};
const NativeImage = window.Image;
if (scenario === 'slow' || scenario === 'failed') window.Image = class extends NativeImage {
  set src(value) { setTimeout(() => { super.src = scenario === 'failed' ? '/worlds/missing-test-capture.jpg' : value; }, scenario === 'slow' ? 5000 : 0); }
};
history.replaceState(null, '', '/');
await import('../src/main.ts');
const controls = document.createElement('aside');
controls.setAttribute('aria-label', 'Browser verification');
controls.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:30;background:white;border:1px solid #aaa;padding:8px;max-width:370px;font:12px/1.5 monospace';
const report = document.createElement('output');
report.style.cssText = 'display:block;white-space:pre-wrap;max-height:160px;overflow:auto';
controls.append(report);
const log = line => report.textContent = line;
function button(label, run) { const b = document.createElement('button'); b.textContent = label; b.onclick = run; controls.prepend(b); }
const choice = () => document.querySelector('#home-market-town');
const panel = () => document.querySelector('#home-preview');
const root = () => document.querySelector('.world-portals');
button('Hover bridge', async () => {
  choice().dispatchEvent(new PointerEvent('pointerenter', {pointerType:'mouse'}));
  const rect = choice().getBoundingClientRect();
  const center = [rect.x + rect.width / 2, rect.y + rect.height / 2];
  choice().dispatchEvent(new PointerEvent('pointerleave', {pointerType:'mouse'}));
  setTimeout(() => panel().dispatchEvent(new PointerEvent('pointerenter', {pointerType:'mouse'})), 250);
  setTimeout(() => {
    const rect = choice().getBoundingClientRect();
    const held = Math.abs(center[0] - rect.x - rect.width / 2) < .1 && Math.abs(center[1] - rect.y - rect.height / 2) < .1;
    log(`Hover bridge: ${!panel().hidden && held ? 'PASS' : 'FAIL'}\nPanel visible: ${!panel().hidden}; orbit center held: ${held}.`);
  }, 850);
});
button('Touch selection', () => {
  document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
  choice().dispatchEvent(new PointerEvent('pointerenter', {pointerType:'touch'}));
  const untouched = panel().hidden;
  choice().click();
  choice().dispatchEvent(new PointerEvent('pointerleave', {pointerType:'touch'}));
  setTimeout(() => log(`Touch selection: ${untouched && !panel().hidden ? 'PASS' : 'FAIL'}\nTap opens; panel stays pinned.`), 700);
});
button('Lose WebGL', () => {
  root().querySelector('canvas').getContext('webgl').getExtension('WEBGL_lose_context').loseContext();
  setTimeout(() => log(`Context loss: ${!root().classList.contains('has-optics') && choice().offsetWidth > 0 ? 'PASS' : 'FAIL'}\nNative world controls retained.`), 100);
});
button('Check readiness', () => {
  const assets = performance.getEntriesByType('resource').filter(r=>r.name.endsWith('.jpg'));
  log(`${scenario}: GPU ${root().classList.contains('has-optics') ? 'ready' : 'fallback'}\nReduced: ${document.documentElement.dataset.reducedMotion}\n${assets.map(r=>`${r.name.split('/').pop()}: ${r.duration.toFixed(1)}ms, ${r.transferSize} transferred bytes`).join('\n')}`);
});
button('Cold / cached assets', async () => {
  const samples = [];
  for (const cache of ['reload', 'force-cache']) {
    const start = performance.now();
    await Promise.all(['/worlds/market-town.jpg', '/worlds/small-town.jpg'].map(async src => {
      const response = await fetch(src, {cache});
      const bitmap = await createImageBitmap(await response.blob()); bitmap.close();
    }));
    samples.push(`${cache}: ${(performance.now() - start).toFixed(1)}ms including decode`);
  }
  log(samples.join('\n'));
});
button('Check rest', () => {
  const before = choice().style.cssText;
  setTimeout(() => log(`Rest: ${before === choice().style.cssText ? 'stationary' : 'moving'}\nReduced: ${document.documentElement.dataset.reducedMotion}`), 1000);
});
log(`Scenario: ${scenario}. Inputs are synthetic browser events. Reduced mode overrides the media query in JavaScript; OS preference is unchanged.`);
document.body.append(controls);

button('Navigation hover', () => {
  const trigger = document.querySelector('#menu-explore');
  const panel = document.querySelector('#panel-explore');
  trigger.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }));
  const opened = !panel.hidden;
  const startOpacity = getComputedStyle(panel).opacity;
  const duration = getComputedStyle(panel).animationDuration;
  trigger.dispatchEvent(new PointerEvent('pointerleave', { pointerType: 'mouse' }));
  setTimeout(() => panel.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' })), 150);
  setTimeout(() => log(`Navigation hover: ${opened && !panel.hidden ? 'PASS' : 'FAIL'}\nOpens without click and stays open across the pointer gap.\nPanel opacity ${startOpacity} → ${getComputedStyle(panel).opacity}; duration ${duration}; reduced ${document.documentElement.dataset.reducedMotion}.`), 600);
});
