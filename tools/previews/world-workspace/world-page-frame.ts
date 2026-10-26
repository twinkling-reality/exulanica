// The light pages' frame (world-page-frame.css, DESIGN's GALLERY-FIX-1026): a part that scrolls in its own column with
// its fades and track, and a row in focus kept in view within it. Any page on the frame uses these.
import './world-page-frame.css';
import { element } from './world-ui-record.ts';

/** How far beyond the row in focus a scrolling part shows, in pixels: more than a fade, so the row is never under one. */
export const IN_VIEW_SPARE_PX = 56;

/**
 * `part` made to scroll in its own column: while more lies beyond, the stylesheet fades its last or first 48 px (by
 * `data-below` and `data-above`), and a 3 px track at the column's edge shows the part in view. `update` reads it again.
 */
export function scrollingColumn(part: HTMLElement): { readonly column: HTMLElement; readonly update: () => void } {
  part.classList.add('wu-frame-scroll');
  const column = element('div', 'wu-frame-col'), track = element('div', 'wu-frame-track'), thumb = element('div', 'wu-frame-thumb');
  track.append(thumb);
  column.append(part, track);
  const update = () => {
    const { scrollTop, scrollHeight, clientHeight } = part;
    const more = scrollHeight - clientHeight > 1;
    part.dataset.above = String(more && scrollTop > 1);
    part.dataset.below = String(more && scrollTop + clientHeight < scrollHeight - 1);
    track.hidden = !more;
    if (!more) return;
    thumb.style.top = `${(scrollTop / scrollHeight) * 100}%`;
    thumb.style.height = `${(clientHeight / scrollHeight) * 100}%`;
  };
  part.addEventListener('scroll', update, { passive: true });
  return { column, update };
}

/** Scrolls `part` as little as shows `focused` whole, IN_VIEW_SPARE_PX clear above and below it (`part` positioned). */
export function keepInView(part: HTMLElement, focused: HTMLElement | null) {
  if (!focused) return;
  const top = focused.offsetTop, bottom = top + focused.offsetHeight;
  if (top - IN_VIEW_SPARE_PX < part.scrollTop) part.scrollTop = Math.max(0, top - IN_VIEW_SPARE_PX);
  else if (bottom + IN_VIEW_SPARE_PX > part.scrollTop + part.clientHeight) part.scrollTop = bottom + IN_VIEW_SPARE_PX - part.clientHeight;
}
