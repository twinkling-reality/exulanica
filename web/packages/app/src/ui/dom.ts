/**
 * A three-function DOM helper.
 *
 * `landing` has one of these and this package may not import it: the boundary contract keeps the
 * signed-out surface free of everything this package depends on, and inverting that to share
 * twenty lines would put a renderer in the landing page's dependency graph. Duplicating a helper
 * with no rules in it is the cheaper of the two, and it is recorded here so the duplication is a
 * decision rather than an oversight.
 */

type Attributes = Record<string, string | number | boolean | undefined>;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Attributes = {},
  children: readonly (Node | string)[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === false) continue;
    if (key === 'text') node.textContent = String(value);
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  node.append(...children);
  return node;
}

/**
 * Set a node's words only when they differ. Writing the same words again replaces the text node,
 * which a live region announces as news; a status that is redrawn every second would repeat itself.
 */
export function setText(node: Node, text: string): void {
  if (node.textContent !== text) node.textContent = text;
}

export function clear(node: Element): void {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** Replace a node's children in one step, so a re-render cannot leave half the old view behind. */
export function replace(node: Element, children: readonly (Node | string)[]): void {
  clear(node);
  node.append(...children);
}

/**
 * A command and the key that runs it, in that order.
 *
 * The key comes FIRST because that is the order every one of these reads in: the badge is the
 * thing you scan for, and the words tell you what it does. Three surfaces used to bake the key
 * into the label as trailing text ("Dismiss  ?"), which meant the same object was a styled badge
 * in one place and two spaces and a letter in another. There is one of these now, and a surface
 * that needs a command action asks for it here rather than describing one again.
 */
export function commandAction(key: string, label: string): readonly Node[] {
  return [
    el('kbd', { text: key }),
    el('span', { class: 'command-action-label', text: label }),
  ];
}
