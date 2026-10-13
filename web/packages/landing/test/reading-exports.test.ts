// @vitest-environment happy-dom
import { resolve } from 'node:path';
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { API_SCHEMA } from '../src/content/api-schema.js';
import { AGENT_EXAMPLE } from '../src/content/agent-example.js';
import { readingFiles } from '../src/content/reading-catalog.js';
import { buildDocumentation } from '../src/ui/documentation.js';

// These are generated website URLs, not files in the repository's docs directory.
const agentsMarkdown = new URL('https://exulanica.com/docs/agents.md').pathname;
const objectsMarkdown = new URL('https://exulanica.com/docs/world-api/objects.md').pathname;

afterEach(() => vi.restoreAllMocks());
describe('public reading exports', () => {
  it('copies the same complete Markdown that is published without page controls', async () => {
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    const files = readingFiles();
    for (const [path, page] of [
      ['/docs/agents', buildDocumentation('agents')],
      ['/docs/world-api', buildDocumentation('world-api')],
      ['/docs/world-api/objects', buildDocumentation('world-api-objects')],
    ] as const) {
      page.querySelector<HTMLButtonElement>('.reading-tools button')!.click();
      await Promise.resolve();
      expect(write).toHaveBeenLastCalledWith(files.get(`${path}.md`));
      expect(page.querySelector('.reading-status')!.textContent).toBe('Markdown copied');
      expect(files.get(`${path}.md`)).not.toContain('Copy Page');
    }
    expect(files.get(agentsMarkdown)).toContain(AGENT_EXAMPLE.trim());
    expect(files.get(objectsMarkdown)).toContain('`base_state_sha256`');
    for (const path of files.keys()) {
      if (path.endsWith('.md')) expect(files.get('/llms.txt')).toContain(path);
    }
  });
  it('does not report clipboard success when copying fails', async () => {
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('denied'));
    const page = buildDocumentation('agents');
    page.querySelector<HTMLButtonElement>('.reading-tools button')!.click();
    await Promise.resolve();
    expect(page.querySelector('.reading-status')!.textContent).toContain('Copy blocked');
    expect(page.querySelector('.reading-tools a')!.getAttribute('href')).toBe(agentsMarkdown);
  });
  it('replaces a prior success with truthful feedback when a later copy fails', async () => {
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValueOnce().mockRejectedValueOnce(new Error('denied'));
    const page = buildDocumentation('agents');
    const copy = page.querySelector<HTMLButtonElement>('.reading-button-group > button')!;
    copy.click();
    expect(copy.disabled).toBe(true);
    copy.click();
    expect(write).toHaveBeenCalledTimes(1);
    await Promise.resolve();
    expect(copy.textContent).toBe('Copied');
    copy.click();
    await Promise.resolve();
    expect(copy.textContent).toBe('Copy Page');
    expect(copy.disabled).toBe(false);
    expect(copy.dataset.copyState).toBe('error');
    expect(page.querySelector('.reading-status')!.textContent).toContain('Copy blocked');
    const example = page.querySelector<HTMLButtonElement>('.docs-copy')!;
    write.mockResolvedValueOnce().mockRejectedValueOnce(new Error('denied'));
    example.click();
    await Promise.resolve();
    expect(example.textContent).toBe('Copied');
    example.click();
    await Promise.resolve();
    expect(example.textContent).toBe('Copy');
    expect(example.dataset.copyState).toBe('error');
    expect(page.querySelector('.docs-copy-status')!.textContent).toBe('Select the code to copy it.');
  });
  it('opens page actions by keyboard, moves between exports and dismisses to the trigger', () => {
    const page = buildDocumentation('agents');
    document.body.append(page);
    const trigger = page.querySelector<HTMLButtonElement>('.reading-menu-toggle')!;
    const menu = page.querySelector<HTMLElement>('.reading-menu')!;
    const items = [...menu.querySelectorAll<HTMLElement>('[role="menuitem"]')];
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(menu.hidden).toBe(false);
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(items[0]);
    items[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    expect(document.activeElement).toBe(items[1]);
    items[1]!.dispatchEvent(new FocusEvent('focusout', { relatedTarget: null, bubbles: true }));
    expect(menu.hidden).toBe(false);
    items[1]!.dispatchEvent(new MouseEvent('click', { metaKey: true, bubbles: true }));
    expect(menu.hidden).toBe(false);
    expect(document.activeElement).toBe(items[1]);
    items[1]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    expect(document.activeElement).toBe(items[2]);
    expect(items[2]!.getAttribute('download')).toBe('agents.md');
    items[2]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(menu.hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);
    trigger.click();
    document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
    expect(menu.hidden).toBe(true);
    page.remove();
  });
  it('keeps published API schemas and the runnable agent example aligned with their source', () => {
    const spec = JSON.parse(readFileSync(resolve(__dirname, '../../../../tests/snapshots/api-openapi.json'), 'utf8'));
    for (const [path, methods] of Object.entries(API_SCHEMA.paths)) {
      for (const [method, operation] of Object.entries(methods)) expect(operation).toEqual(spec.paths[path][method]);
    }
    for (const [name, schema] of Object.entries(API_SCHEMA.schemas)) expect(schema).toEqual(spec.components.schemas[name]);
    expect(AGENT_EXAMPLE).toBe(readFileSync(resolve(__dirname, '../../../../bridges/agents/examples/quickstart.py'), 'utf8'));
  });
});
