import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['packages/*/test/**/*.test.ts'],
    environment: 'node',
    // No test reaches a host that is not this machine: the reach is refused and the test failed by name.
    setupFiles: ['./vitest.setup.ts'],
    // The design tokens are read as text by token-values.ts (a ?raw import); without this the
    // test runner hands every stylesheet over empty.
    css: { include: [/ui\/system\/tokens\.css/] },
  },
});
