/** One nonblocking entrance per document. Images reveal independently when decoded. */
export function enterPage(page: HTMLElement, navigation: HTMLElement, reduced: () => boolean): void {
  if (reduced() || typeof page.animate !== 'function') return;
  const elements = [navigation, ...page.querySelectorAll<HTMLElement>('.hero-heading, .hero-actions, .editorial-intro, .waitlist-gate, .docs-heading')];
  const animations = elements.map((element, index) => element.animate([
    { opacity: 0, translate: '0 8px' }, { opacity: 1, translate: '0 0' },
  ], { duration: 640, delay: index * 65, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'backwards' }));
  const finish = () => { animations.forEach(animation => animation.cancel()); observer.disconnect(); media.removeEventListener('change', finish); };
  const observer = new MutationObserver(finish);
  observer.observe(page, { attributes: true, attributeFilter: ['inert'] });
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  media.addEventListener('change', finish, { once: true });
  void Promise.all(animations.map(animation => animation.finished)).then(finish, finish);
}
