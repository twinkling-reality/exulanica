import type { SourceMediaDescriptor } from '@exulanica/atlas-react/playcanvas';
import { el, replace } from './dom.js';

export interface ReconstructionInspectionOption {
  readonly id: string;
  readonly kind: 'source-camera' | 'between-cameras' | 'source-only';
  readonly label: string;
  readonly source: SourceMediaDescriptor | null;
}

/** A bounded camera register beside the live world. Source media keeps its existing authorization. */
export function buildReconstructionInspector(options: {
  readonly onView: (sceneId: string, viewId: string) => boolean;
  readonly onReturn: () => void;
}) {
  const root = el('aside', {
    class: 'reconstruction-inspector', hidden: true,
    'aria-label': 'Reconstruction inspection',
  });
  const title = el('h2', { text: 'Reconstruction views' });
  const disclosure = el('p', {
    text: 'Camera inspection · fitted relative scale · physical scale unverified. These views do not establish a walkable surface.',
  });
  const select = el('select', { 'aria-label': 'Inspection viewpoint' });
  const previous = el('button', { type: 'button', text: 'Previous view' });
  const next = el('button', { type: 'button', text: 'Next view' });
  const back = el('button', { type: 'button', text: 'Return to Atlas' });
  const state = el('p', { role: 'status', 'aria-live': 'polite' });
  const source = el('details', { class: 'reconstruction-inspector-source' });
  const sourceBody = el('div');
  source.append(el('summary', { text: 'Inspect original source' }), sourceBody);
  root.append(el('header', { class: 'reconstruction-inspector-header' }, [title, back]),
    disclosure, select, el('nav', {}, [previous, next]), state, source);
  let sceneId = '';
  let views: readonly ReconstructionInspectionOption[] = [];
  let restoreFocus: HTMLElement | null = null;

  function showView(index: number): void {
    const view = views[index];
    if (view === undefined) return;
    if (view.kind !== 'source-only' && !options.onView(sceneId, view.id)) {
      state.textContent = 'This view is unavailable. Return to Atlas to use its source photographs.';
      source.hidden = true;
      return;
    }
    select.selectedIndex = index;
    root.dataset.viewId = view.id;
    previous.disabled = index === 0;
    next.disabled = index === views.length - 1;
    state.textContent = view.kind === 'source-only'
      ? 'Original photograph. Reconstructed camera inspection is unavailable for this scene.'
      : view.kind === 'source-camera'
      ? 'Recovered source camera. Loaded maps use full display density without point-map fog or boundary thinning; missing members remain disclosed.'
      : 'Midpoint between consecutive recovered cameras. This is an unobserved viewpoint, not measured geometry or a validated route.';
    source.hidden = false;
    source.open = view.kind === 'source-only';
    if (view.source?.available && view.source.url !== null) {
      replace(sourceBody, [el('img', { src: view.source.url, alt: view.source.alt }),
        el('p', { text: sourceCaption(view.source.title, view.label), title: view.source.title })]);
    } else {
      replace(sourceBody, [el('p', {
        text: view.kind === 'between-cameras'
          ? 'No photograph was taken at this midpoint. Choose either adjacent source camera to inspect its original.'
          : 'The authorized original source is unavailable in this session.',
      })]);
    }
  }
  const hide = (): void => {
    root.hidden = true;
    source.open = false;
    replace(sourceBody, []);
    if (restoreFocus?.isConnected) restoreFocus.focus();
    restoreFocus = null;
  };
  const close = (): void => { options.onReturn(); hide(); };
  back.addEventListener('click', close);
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    close();
  });
  select.addEventListener('change', () => showView(select.selectedIndex));
  previous.addEventListener('click', () => showView(select.selectedIndex - 1));
  next.addEventListener('click', () => showView(select.selectedIndex + 1));
  return {
    root, hide,
    open(id: string, choices: readonly ReconstructionInspectionOption[]): boolean {
      if (choices.length === 0) return false;
      if (root.hidden) restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      sceneId = id;
      views = choices;
      const sourceOnly = choices[0]!.kind === 'source-only';
      title.textContent = sourceOnly ? 'Source photographs' : 'Reconstruction views';
      disclosure.textContent = sourceOnly
        ? 'Authorized original evidence. No reconstructed surface or measured route is implied.'
        : 'Camera inspection · fitted relative scale · physical scale unverified. These views do not establish a walkable surface.';
      select.setAttribute('aria-label', sourceOnly ? 'Source photograph' : 'Inspection viewpoint');
      root.dataset.sceneId = id;
      replace(select, choices.map((view) => el('option', { value: view.id, text: view.label })));
      root.hidden = false;
      showView(0);
      select.focus();
      return true;
    },
  };
}

/** Generated source identifiers remain metadata, while the reading label stays short. */
export function sourceCaption(title: string, fallback: string): string {
  return /^(?:(?:source|capture)[\s:_-]*)?[0-9a-f]{8}[-\s][0-9a-f]{4}[-\s][0-9a-f]{4}[-\s][0-9a-f]{4}[-\s][0-9a-f]{12}$/iu.test(title)
    ? fallback : title;
}
