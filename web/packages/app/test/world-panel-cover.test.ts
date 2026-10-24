// @vitest-environment happy-dom
// The world's marks keep under the panels drawn over them (V10, tools/previews/world-workspace/character-group.ts
// panelCover): the looked-at tag, the aim mark, a line over a head and a farther name (V10b) are not drawn in a frame where they cross the chosen card, the
// question or the group (its model list included), and are drawn again where they do not. The presence that stacks the
// tag under the panels and asks this each frame (character-presence.ts) reads the page's own modules by the page's paths,
// so its stacking is proved on the page.
import { afterEach, describe, expect, it, vi } from 'vitest';

interface Box { readonly x: number; readonly y: number; readonly width: number; readonly height: number }
interface LookLabel { readonly root: HTMLElement; set(words: { name: string; doing: string | null } | null, inspectable: boolean): void; box(): Box | null }
interface Cover { crosses(box: { left: number; top: number; right: number; bottom: number }): boolean; clear(label: LookLabel): void; cover(element: HTMLElement): void }
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out of the program.
const group = async (): Promise<{
  lookLabel(options: { scale: () => number; onInspect: () => void }): LookLabel;
  panelCover(panels: () => readonly (Element | null)[]): Cover;
}> => import('../../../../tools/previews/world-workspace/' + 'character-group.ts') as never;

/** An element laid out at a box, as the page lays it out: happy-dom lays out nothing. */
function laidOut(element: HTMLElement, box: Box | null): HTMLElement {
  element.getBoundingClientRect = () => {
    const [x, y, width, height] = box ? [box.x, box.y, box.width, box.height] : [0, 0, 0, 0];
    return { x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON: () => ({}) } as DOMRect;
  };
  return element;
}

afterEach(() => { document.body.replaceChildren(); });

describe('the world\'s marks under an open panel', () => {
  // The model list of 07-chooser.jpg: 670 px wide in the middle of a 1920 by 1080 view.
  const CHOOSER = { x: 560, y: 180, width: 670, height: 700 };

  it('leaves out a tag over the open model list, and draws one beside it', async () => {
    const { lookLabel, panelCover } = await group();
    const chooser = laidOut(document.createElement('div'), CHOOSER);
    const under = panelCover(() => [chooser]);
    const label = lookLabel({ scale: () => 1, onInspect: vi.fn() });
    document.body.append(label.root);
    const words = { name: 'Ivo Wynn', doing: 'Standing a while' };
    // Ivo Wynn's tag over "With your Nebius Token Factory key" and Nemotron 3 Nano 30B's row.
    label.set(words, true);
    laidOut(label.root, { x: 760, y: 440, width: 150, height: 90 });
    under.clear(label);
    expect(label.root.hidden).toBe(true);
    // Someone to the right of the list: their tag is drawn.
    label.set(words, true);
    laidOut(label.root, { x: 1400, y: 440, width: 150, height: 90 });
    under.clear(label);
    expect(label.root.hidden).toBe(false);
    // The list put away (no box): the tag over where it stood is drawn again.
    laidOut(chooser, null);
    laidOut(label.root, { x: 760, y: 440, width: 150, height: 90 });
    under.clear(label);
    expect(label.root.hidden).toBe(false);
  });

  it('hides a line over a head and a farther name where they cross the open list, and keeps them beside it (V10b)', async () => {
    const { panelCover } = await group();
    const talk = await import('../../../../tools/previews/world-workspace/' + 'world-ui-talk.ts') as unknown as {
      speech(): { root: HTMLElement; draw(words: object): void; place(x: number, y: number): void };
      nameOver(): { root: HTMLElement; draw(words: string): void; place(x: number, y: number): void };
    };
    const chooser = laidOut(document.createElement('div'), CHOOSER);
    const under = panelCover(() => [chooser]);
    const line = talk.speech(), name = talk.nameOver();
    document.body.append(line.root, name.root);
    // A line said by someone behind the list, and a name over someone beside it.
    laidOut(line.root, { x: 700, y: 400, width: 280, height: 60 });
    laidOut(name.root, { x: 1400, y: 380, width: 120, height: 30 });
    under.cover(line.root);
    under.cover(name.root);
    expect(line.root.style.visibility).toBe('hidden');
    expect(name.root.style.visibility).toBe('');
    // The list put away: the line is drawn again.
    laidOut(chooser, null);
    under.cover(line.root);
    expect(line.root.style.visibility).toBe('');
  });

  it('hides the aim mark under a panel in the middle, keeps it beside one at the side, and shows it once the panel goes', async () => {
    const { panelCover } = await group();
    let panel: Box | null = CHOOSER;
    const shown = document.createElement('div');
    const under = panelCover(() => [laidOut(shown, panel), null]);
    // The aim mark, 16 px at the middle of the view.
    const mark = laidOut(document.createElement('div'), { x: 952, y: 532, width: 16, height: 16 });
    under.cover(mark);
    expect(mark.style.visibility).toBe('hidden');
    // A card beside someone at the left: the aim mark stays.
    panel = { x: 120, y: 300, width: 420, height: 360 };
    under.cover(mark);
    expect(mark.style.visibility).toBe('');
    panel = null;
    under.cover(mark);
    expect(mark.style.visibility).toBe('');
    // Touching edges do not cross.
    expect(under.crosses({ left: 0, top: 0, right: 10, bottom: 10 })).toBe(false);
    panel = { x: 10, y: 0, width: 10, height: 10 };
    expect(under.crosses({ left: 0, top: 0, right: 10, bottom: 10 })).toBe(false);
    expect(under.crosses({ left: 0, top: 0, right: 11, bottom: 10 })).toBe(true);
  });
});
