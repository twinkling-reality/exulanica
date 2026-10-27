// What the world's capture handler (contextual-world.ts) does with a key while nothing is open and
// build mode has passed it on (DESIGN's specification, section 9, and rulings K1, K2 and K8). Pure,
// so every key's fate is checked (verify-world-corners.mjs):
// - 'move': the renderer's own movement keys go on to it (W A S D, arrows, Shift, F; Space and C only
//   while flying);
// - 'inspect', 'leave', 'play', 'history': the workspace's own keys; 'bring-in': P where nobody lives
//   yet and the clock's corner offers to bring people in (K13); 'data': X where the data view works
//   (world-data-view.ts); E inspects nobody while the talking scene shows, since the reticle and the
//   look tag are hidden under it;
// - 'pass': Tab moves the focus, and Enter presses a focused corner prompt, as anywhere;
// - 'quiet': a combination with Cmd, Ctrl or Alt the workspace does not use goes no further (the old
//   shell's Cmd+K palette included) but keeps the browser's own shortcut (no preventDefault);
// - 'silence': any other key goes no further and does nothing (the old shell's K, I, M, O, R, G,
//   Backspace and ? among them, and H, P and X where History, the clock or the data view is not there).

const MOVING = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight']);

/**
 * `state`: { flying, clock, history, bringIn, scene, data } where clock says whether the world has a clock to
 * play (people live there), history whether H opens History here, bringIn whether the clock's corner
 * offers to bring people in, scene whether the talking scene shows and data whether the data view works
 * here; `onPrompt` whether the key's target is a corner prompt (a button).
 */
export function worldKey(event, state, onPrompt = false) {
  if (event.metaKey || event.ctrlKey || event.altKey) return 'quiet';
  if (MOVING.has(event.code) || event.code === 'KeyF') return 'move';
  if (state.flying && (event.code === 'Space' || event.code === 'KeyC')) return 'move';
  if (event.code === 'KeyE') return event.repeat || state.scene ? 'silence' : 'inspect';
  if (event.code === 'Escape') return event.repeat ? 'silence' : 'leave';
  if (event.code === 'KeyP') return event.repeat ? 'silence' : state.clock ? 'play' : state.bringIn ? 'bring-in' : 'silence';
  if (event.code === 'KeyH') return state.history && !event.repeat ? 'history' : 'silence';
  if (event.code === 'KeyX') return state.data && !event.repeat ? 'data' : 'silence';
  if (event.code === 'Tab' || (event.code === 'Enter' && onPrompt)) return 'pass';
  return 'silence';
}

/** Keys whose hint, when pressed, brings the faded hints back for a while (section 5.2). */
export function wakesHints(event) {
  return !event.metaKey && !event.ctrlKey && !event.altKey
    && ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft', 'ShiftRight', 'KeyF', 'KeyE', 'KeyB', 'KeyP', 'KeyH', 'Space', 'KeyC'].includes(event.code);
}
