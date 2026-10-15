// What the world's capture handler (contextual-world.ts) does with a key while nothing is open and
// build mode has passed it on (DESIGN's specification, section 9, and rulings K1, K2 and K8). Pure,
// so every key's fate is checked (verify-world-corners.mjs):
// - 'move': the renderer's own movement keys go on to it (W A S D, arrows, Shift, F; Space and C only
//   while flying);
// - 'inspect', 'leave', 'play': the workspace's own keys;
// - 'pass': Tab moves the focus, and Enter presses a focused corner prompt, as anywhere;
// - 'quiet': a combination with Cmd, Ctrl or Alt the workspace does not use goes no further (the old
//   shell's Cmd+K palette included) but keeps the browser's own shortcut (no preventDefault);
// - 'silence': any other key goes no further and does nothing (the old shell's H, K, I, M, O, R, G,
//   P, Backspace and ? among them).

const MOVING = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight']);

/**
 * `state`: { flying, clock } where clock says whether the world has a clock to play (people live
 * there); `onPrompt` whether the key's target is a corner prompt (a button).
 */
export function worldKey(event, state, onPrompt = false) {
  if (event.metaKey || event.ctrlKey || event.altKey) return 'quiet';
  if (MOVING.has(event.code) || event.code === 'KeyF') return 'move';
  if (state.flying && (event.code === 'Space' || event.code === 'KeyC')) return 'move';
  if (event.code === 'KeyE') return event.repeat ? 'silence' : 'inspect';
  if (event.code === 'Escape') return event.repeat ? 'silence' : 'leave';
  if (event.code === 'KeyP') return state.clock && !event.repeat ? 'play' : 'silence';
  if (event.code === 'Tab' || (event.code === 'Enter' && onPrompt)) return 'pass';
  return 'silence';
}

/** Keys whose hint, when pressed, brings the faded hints back for a while (section 5.2). */
export function wakesHints(event) {
  return !event.metaKey && !event.ctrlKey && !event.altKey
    && ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft', 'ShiftRight', 'KeyF', 'KeyE', 'KeyB', 'KeyP', 'Space', 'KeyC'].includes(event.code);
}
