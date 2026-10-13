const statistics = values => {
  const sorted = [...values].sort((a, b) => a - b);
  return { samples: sorted.length, meanMs: sorted.length ? values.reduce((a, b) => a + b, 0) / sorted.length : null,
    p95Ms: sorted.length ? sorted[Math.ceil(sorted.length * .95) - 1] : null, maximumMs: sorted.at(-1) ?? null };
};

/** Opt-in local QA: engine cadence and actual render events, never overlay work called FPS. */
export function mountFrameMeasurement(binding, root) {
  if (new URLSearchParams(location.search).get('measureFrames') !== '1') return () => {};
  const box = document.createElement('div'); box.className = 'cw-frame-check';
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Measure 10 seconds';
  const output = document.createElement('output'); output.textContent = 'QA frame measurement';
  box.append(button, output); root.append(box);
  let active = null, timer = null;
  const pose = () => ['x', 'y', 'z', 'yaw', 'pitch'].map(key => binding.controls.state[key]);
  const frame = ms => {
    if (!active || document.hidden) return;
    active.renderedThisFrame = false;
    if (active.sawFrame && Number.isFinite(ms)) active.intervals.push(ms);
    active.sawFrame = true;
  };
  const render = () => {
    if (!active || document.hidden) return;
    const now = performance.now();
    if (active.lastRender !== null) active.renders.push(now - active.lastRender);
    active.lastRender = now; active.renderCount++; active.renderedThisFrame = true;
  };
  const endFrame = () => {
    if (!active || document.hidden || !active.renderedThisFrame) return;
    const stats = binding.app.stats;
    if (Number.isFinite(stats.frame.renderTime)) active.cpuRender.push(stats.frame.renderTime);
    active.drawCalls.push(stats.drawCalls.total);
  };
  const interrupted = () => { if (active) active.interrupted = true; };
  binding.app.on('frameupdate', frame); binding.app.on('postrender', render); binding.app.on('frameend', endFrame);
  document.addEventListener('visibilitychange', interrupted);
  button.onclick = () => {
    if (active) return;
    active = { started: performance.now(), startPose: pose(), intervals: [], renders: [], cpuRender: [], drawCalls: [], renderCount: 0, lastRender: null, interrupted: document.hidden };
    button.disabled = true; output.textContent = 'Measuring… keep this tab visible'; delete root.dataset.frameMeasurement;
    timer = setTimeout(() => {
      const sample = active; active = null;
      const elapsed = performance.now() - sample.started;
      const result = { profile: 'exulanica.preview-frames/v1', measuredAt: new Date().toISOString(), elapsedMs: elapsed,
        visibilityInterrupted: sample.interrupted, engineIntervals: statistics(sample.intervals), renderIntervals: statistics(sample.renders),
        renderedFrames: sample.renderCount, renderedFramesPerSecond: sample.renderCount * 1000 / elapsed,
        cpuRenderMs: statistics(sample.cpuRender), maximumDrawCalls: Math.max(0, ...sample.drawCalls),
        viewport: [innerWidth, innerHeight], canvas: [binding.device.canvas.width, binding.device.canvas.height], devicePixelRatio,
        startPose: sample.startPose, endPose: pose(), autoRender: binding.app.autoRender,
        gpuTime: 'Not measured', presentation: 'Render submissions, not display presentation or GPU completion' };
      root.dataset.frameMeasurement = JSON.stringify(result);
      output.textContent = sample.interrupted ? 'Discard: tab visibility changed' : `${result.renderedFramesPerSecond.toFixed(1)} rendered frames/s · engine p95 ${result.engineIntervals.p95Ms?.toFixed(1)} ms`;
      button.disabled = false;
    }, 10000);
  };
  return () => { clearTimeout(timer); binding.app.off('frameupdate', frame); binding.app.off('postrender', render); binding.app.off('frameend', endFrame); document.removeEventListener('visibilitychange', interrupted); box.remove(); };
}
