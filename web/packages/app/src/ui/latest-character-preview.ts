/** Coalesce edits and serialize expensive builds. Older results never replace newer drafts. */
export function createLatestCharacterPreview<Recipe, Result>(options: {
  build(recipe: Recipe): Promise<Result>;
  ready(result: Result): void;
  pending(): void;
  failed(error: unknown): void;
  delay?: number;
}) {
  let revision = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let latest: { recipe: Recipe; revision: number; settled: boolean } | undefined;
  let running = false;
  let disposed = false;
  async function pump() {
    if (disposed || running || !latest?.settled) return;
    const request = latest;
    latest = undefined;
    running = true;
    try {
      const result = await options.build(request.recipe);
      if (!disposed && request.revision === revision) options.ready(result);
    } catch (error) {
      if (!disposed && request.revision === revision) options.failed(error);
    } finally {
      running = false;
      void pump();
    }
  }
  function cancel() {
    revision++;
    clearTimeout(timer);
    latest = undefined;
  }
  return {
    request(recipe: Recipe) {
      if (disposed) return;
      clearTimeout(timer);
      latest = { recipe, revision: ++revision, settled: false };
      options.pending();
      timer = setTimeout(() => {
        if (latest) latest.settled = true;
        void pump();
      }, options.delay ?? 400);
    },
    cancel,
    dispose() { cancel(); disposed = true; },
  };
}
