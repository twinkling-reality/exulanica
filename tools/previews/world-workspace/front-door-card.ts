// What a world's card offers on the workspace's front door: Open and Details only. The app's Your worlds also offers
// View values, its button and its V, whose details lead to the shell's own Create, a way back into the shell; the front
// door leaves it out. Kept apart from front-door.ts so a test can run it on the app's own Your worlds.

/** Takes View values off Your worlds at `root`: its button and its note, and V, except while a person types in a field. */
export function offerOpenAndDetailsOnly(root: HTMLElement): void {
  root.querySelector('.your-worlds-values')?.remove();
  root.querySelector('#your-worlds-values-why')?.remove();
  root.addEventListener('keydown', (event) => {
    const typing = (event.target as HTMLElement | null)?.closest?.('input, textarea, select, [contenteditable="true"]');
    if ((event.key === 'v' || event.key === 'V') && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey && !typing) event.stopImmediatePropagation();
  }, true);
}
