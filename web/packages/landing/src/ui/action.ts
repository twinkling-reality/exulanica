import { el } from './dom.js';
import { icon } from './icons.js';

/** Compact page controls; the split invitation is reserved for application entry. */
export function action(label: string, href: string, secondary = false): HTMLAnchorElement {
  const external = /^https?:/.test(href);
  if (secondary) return el('a', {
    class: 'secondary-action', href,
    ...(external ? { 'aria-label': `${label} (external)`, title: 'Opens an external site' } : {}),
  }, [el('span', { class: 'secondary-label', text: label })]);
  return el('a', { class: 'primary-action', href }, [
    el('span', { class: 'action-label', text: label }),
    el('span', { class: 'action-icon', 'aria-hidden': 'true' }, [icon('arrow')]),
  ]);
}
