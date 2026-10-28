import { el } from './dom.js';
import { action } from './action.js';
import { USE_CASES, type UseCase } from '../content/use-cases.js';
import { withSectionAtmosphere } from './ambient-field.js';
import '../site-pages.css';
import '../product.css';
import '../feature-pages.css';
import '../use-cases.css';

export function buildUseCases(): HTMLElement {
  const directory = el('nav', { class: 'journey-rows', 'aria-label': 'Use case journeys' }, USE_CASES.map(item => {
    const titleId = `use-case-link-${item.key}`;
    return el('a', { class: 'journey-row use-case-destination', href: `/use-cases/${item.key}`, 'aria-labelledby': titleId }, [
      el('h2', { id: titleId, text: item.title }),
      el('p', { text: item.summary }),
      el('span', { class: 'row-label' }, [
        'Open',
        el('span', { class: 'row-label-mark', text: '↗', 'aria-hidden': 'true' }),
      ]),
    ]);
  }));
  return withSectionAtmosphere(el('section', {
    id: 'use-cases',
    class: 'pane site-pane feature-pane use-cases-pane',
    tabindex: '-1',
    'aria-labelledby': 'use-cases-title',
  }, [
    el('article', { class: 'site-page journey-index' }, [
      el('h1', { id: 'use-cases-title', text: 'Use Cases' }),
      directory,
    ]),
  ]), 'use-cases');
}

function guideLinks(item: UseCase): HTMLElement {
  return el('nav', { class: 'use-case-guides', 'aria-label': `${item.title} documentation` }, [
    action(item.action, item.href, true),
    ...item.guides.map(guide => action(guide.title, guide.href, true)),
  ]);
}

export function buildUseCase(item: UseCase): HTMLElement {
  const id = `use-case-${item.key}`;
  const back = action('Use Cases', '/use-cases', true);
  back.classList.add('use-case-back');
  const intro = el('div', { class: item.image ? 'task-intro has-figure' : 'task-intro' }, [
    el('div', { class: 'task-copy' }, [
      el('h1', { id: `${id}-title`, text: item.title }),
      el('p', { text: item.introduction }),
    ]),
  ]);
  if (item.image) {
    intro.append(el('figure', { class: 'task-figure' }, [
      el('img', { src: item.image, alt: item.alt ?? '', width: '1280', height: '860', loading: 'lazy' }),
      el('figcaption', { text: item.caption ?? '' }),
    ]));
  }
  return withSectionAtmosphere(el('section', {
    id,
    class: `pane site-pane feature-pane use-case-pane use-case-${item.key}-pane`,
    tabindex: '-1',
    'aria-labelledby': `${id}-title`,
  }, [
    el('article', { class: 'site-page task-sheet' }, [
      back,
      intro,
      el('ol', { class: 'task-steps' }, item.steps.map((step, index) => el('li', {}, [
        el('span', { class: 'task-index', text: String(index + 1), 'aria-hidden': 'true' }),
        el('h2', { text: step.title }),
        el('p', { text: step.copy }),
      ]))),
      guideLinks(item),
      el('p', { class: 'use-case-scope', id: `${id}-scope`, text: item.availability }),
    ]),
  ]), 'use-cases');
}
