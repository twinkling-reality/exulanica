// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { animateSurface, replaceSurface } from '../src/ui/surface-motion.js';

afterEach(() => { document.body.replaceChildren(); delete document.documentElement.dataset['motion']; });

it('reduced motion replaces content immediately without animation or moving focus', () => {
  document.documentElement.dataset['motion'] = 'reduced';
  const root = document.createElement('main');
  const field = document.createElement('textarea');
  document.body.append(root);
  const animate = vi.fn();
  root.animate = animate;
  replaceSurface(root, [field]);
  field.focus();
  expect(root.firstChild).toBe(field);
  expect(document.activeElement).toBe(field);
  expect(animate).not.toHaveBeenCalled();
});

it('interruption cancels the old completion and lets only the latest transition finish', async () => {
  document.documentElement.dataset['motion'] = 'full';
  const root = document.createElement('main');
  const pending: { finish(): void; cancel: ReturnType<typeof vi.fn> }[] = [];
  root.animate = vi.fn(() => {
    let finish!: () => void;
    let reject!: (reason: Error) => void;
    const finished = new Promise<void>((resolve, fail) => { finish = resolve; reject = fail; });
    const cancel = vi.fn(() => reject(new Error('cancelled')));
    pending.push({ finish, cancel });
    return { finished, cancel } as unknown as Animation;
  });
  const entering = animateSurface(root, 'enter');
  const leaving = animateSurface(root, 'leave');
  expect(pending[0]!.cancel).toHaveBeenCalledOnce();
  pending[1]!.finish();
  expect(await entering).toBe(false);
  expect(await leaving).toBe(true);
});
