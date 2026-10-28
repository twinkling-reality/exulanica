import { el } from '../dom.js';
import { p, codeBlock, entries, source, type DocumentPage } from './elements.js';
export function selfHosting(): DocumentPage {
  return {
    title: 'Installation',
    introduction: 'Run the browser locally, then connect it to an API and a persistent database for saved worlds and model decisions.',
    sourcePath: 'docs/development-setup.md',
    chapters: [
      { key: 'prerequisites', title: 'Prerequisites', nodes: [
        entries([
          { label: 'Browser application', detail: 'Node.js 22 or newer and pnpm 10.7.1.' },
          { label: 'API', detail: 'Python 3.11 and uv.' },
          { label: 'Database', detail: 'PostgreSQL 18 with pgvector.' },
        ]),
        codeBlock('Clone Exulanica', 'git clone https://github.com/twinkling-reality/exulanica.git\ncd exulanica'),
        p('The browser, API, and workers are separate processes. The following commands run from the repository root unless a step changes directory.'),
      ] },
      { key: 'preview', title: 'Start the Browser', nodes: [
        codeBlock('Browser', 'cd web\npnpm install --frozen-lockfile\npnpm app'),
        p('Open the address printed by Vite. Adding ?preview=1 selects the read-only development fixture. The fixture also needs its locally supplied source images; a clean checkout alone does not establish a complete preview.'),
        p('For saved worlds and live models, continue with the API setup and open the application without ?preview=1.'),
      ] },
      { key: 'database', title: 'Create a Persistent Database', nodes: [
        codeBlock('Backend dependencies', 'uv sync --extra reconstruction --extra segmentation --extra pose --extra server'),
        p('Initialize a personal database in an empty, durable directory. The command creates, migrates, and starts the database on loopback, then prints connection URLs for its roles.'),
        codeBlock('Personal database', 'uv run exulanica-local-db init --directory ~/Exulanica/database\nuv run exulanica-local-db status --directory ~/Exulanica/database'),
        p('Keep the printed URLs, including their passfile parameters. Use the owner connection to publish catalogs, then the exulanica_app connection to run the API. Do not run the API with the owner role.'),
        codeBlock('Publish character catalogs', 'EXULANICA_DATABASE_URL="<owner connection URL>" \\\nEXULANICA_DATA_DIR="$HOME/Exulanica/content" \\\n  uv run exulanica-character-catalog publish --apply'),
      ] },
      { key: 'api', title: 'Configure and Start the API', nodes: [
        p('Create a long random token and two UUIDs for a workspace and actor. Replace every angle-bracket placeholder below. Keep the token private; it grants access to the named workspace.'),
        codeBlock('Local API configuration', 'export EXULANICA_DATABASE_URL="<exulanica_app connection URL>"\nexport EXULANICA_DATA_DIR="$HOME/Exulanica/content"\nexport EXULANICA_API_TOKENS=\'{"<random token>":{"workspace_id":"<workspace UUID>","actor":"<actor UUID>","permissions":["library.read","library.write","world.read","world.write","model.invoke"]}}\'\nuv run uvicorn --factory exulanica.api.app:create_app --port 8000'),
        p('The development browser proxies API requests to http://127.0.0.1:8000. Set EXULANICA_API_URL when starting the browser if your API uses another address. On an installation without browser accounts, use its developer-token entry.'),
        p('Check /readyz before using the installation. It reports missing configuration and unpublished catalogs. A running HTTP server does not establish that every optional capability is ready.'),
      ] },
      { key: 'models', title: 'Enable Models and Playback', nodes: [
        p('Model calls require a provider credential, an allowed provider origin, and a spending mode. The following is a local process-budget configuration. Set your own budget before restarting the API with these variables.'),
        codeBlock('Model configuration', 'export NEBIUS_API_KEY="<your provider key>"\nexport EXULANICA_EGRESS_ALLOWLIST=\'["https://api.tokenfactory.nebius.com"]\'\nexport EXULANICA_SPENDING=process\nexport EXULANICA_BUDGET_USD="<your budget in USD>"\nexport EXULANICA_SOCIETY_CONTROL_WORKSPACES=\'["<workspace UUID>"]\''),
        p('EXULANICA_SOCIETY_CONTROL_WORKSPACES is a JSON array of workspace ids. A bare id is refused at startup, and no society in that workspace is played. A process budget resets when the process restarts. Hosted installations should configure the shared durable spending authority. Without a provider, people can follow routines but model-dependent operations remain unavailable.'),
        el('p', {}, ['Once configured, follow ', el('a', { href: '/docs/models#docs-models-models', text: 'Choose a model' }), ' in Models and decisions.']),
      ] },
      { key: 'services', title: 'Prepare the Services Your World Needs', nodes: [entries([{ label: 'Saved catalog worlds', detail: 'Persistent database, content store and published catalogs.' }, { label: 'Generated towns', detail: 'Generated-tile preparation worker and its configured build inputs. A saved town waits until its tiles are baked.' }, { label: 'Live people and comparisons', detail: 'Playback for the workspace, comparison execution and configured model/spending services.' }, { label: 'Your own 3D assets', detail: 'Workspace asset preparation worker. Admitted content waits until a compatible preparer runs.' }, { label: 'Reconstructed places', detail: 'Source admission and the reconstruction services appropriate to the input.' }]), p('The commands above establish a local API foundation. Select and configure the workers for your workflow before expecting every creation path to run. Read /readyz and the world’s capability refusals to identify missing services.'), source('docs/deployment.md', 'Service topology, worker configuration and deployment profiles')] },
      { key: 'operations', title: 'Maintenance', nodes: [
        codeBlock('Back up and verify', 'uv run exulanica-local-db backup --directory ~/Exulanica/database\nuv run exulanica-local-db verify --directory ~/Exulanica/database'),
        p('Database backups do not include EXULANICA_DATA_DIR. Back up the content directory too, and keep copies on another disk. Use exulanica-local-db upgrade for this managed database; it backs up and rehearses the migration before applying it.'),
        el('p', {}, ['Use ', source('docs/local-database.md', 'Database restore and upgrade'), ' for the managed database’s recovery procedures.']),
        p('Google browser sign-in requires HTTPS, registered callback and return URLs, permitted browser origins, and a separate account database role. Do not expose this local token-based setup as a public sign-in service.'),
      ] },
    ],
  };
}
