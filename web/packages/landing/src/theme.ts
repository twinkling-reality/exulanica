/** Public interface preference; artwork and authored world lighting remain independent. */
export type PublicTheme = 'light' | 'dark';
export const PUBLIC_THEME_KEY = 'exulanica.public.theme.v1';

export function createPublicTheme() {
  let current: PublicTheme = 'light';
  try { if (localStorage.getItem(PUBLIC_THEME_KEY) === 'dark') current = 'dark'; } catch { /* Storage may be disabled. */ }
  const listeners = new Set<(theme: PublicTheme) => void>();
  const apply = (): void => {
    document.documentElement.dataset['theme'] = `landing-${current}`;
    document.documentElement.dataset['ground'] = current;
    document.documentElement.style.colorScheme = current;
    listeners.forEach(listener => listener(current));
  };
  const changed = (event: StorageEvent): void => {
    if (event.key !== PUBLIC_THEME_KEY && event.key !== null) return;
    current = event.newValue === 'dark' ? 'dark' : 'light';
    apply();
  };
  window.addEventListener('storage', changed);
  apply();
  return {
    toggle(): void {
      current = current === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(PUBLIC_THEME_KEY, current); } catch { /* Keep the session choice usable. */ }
      apply();
    },
    subscribe(listener: (theme: PublicTheme) => void): () => void {
      listeners.add(listener);
      listener(current);
      return () => { listeners.delete(listener); };
    },
    dispose(): void { window.removeEventListener('storage', changed); listeners.clear(); },
  };
}
