# Exulanica

A Personal World Memory Model.

**Build your own world from your life, then change what's possible inside it.**

Bring the places you remember and the worlds you imagine together. Keep what matters, change what
you wish, and create something of your own.

- [Scene Reconstruction](docs/capabilities/scene-reconstruction.md): Build 3D places from your experiences.
- [World Creation](docs/capabilities/world-creation.md): Change the look, add objects, and combine places into your own creations.
- [Companion](docs/capabilities/companion.md): Someone to share your world with, who gets to know you through what you create and experience together.
## Build With Exulanica

- [Simulation Runtime](docs/capabilities/simulation.md): Give your creations movement, interactions, and rules.
- [World API](docs/capabilities/world-api.md): Connect creation tools and applications to your world's state.
- [World Memory Package](docs/world-memory-package.md): Save a signed, verifiable description of your world, with original media excluded by default.

Each feature's documentation covers its capabilities, implementation status, and technical contracts.

## Getting Started

Requires Python 3.11, [uv](https://docs.astral.sh/uv/), Node.js 22 or newer, and pnpm 10.7.1.

```bash
uv sync
cp .env.example .env
uv run pytest
```

The tests do not call external model services. Database-backed tests require PostgreSQL;
see [development setup](docs/development-setup.md) for configuration and additional checks.

```bash
cd web
pnpm install
pnpm landing
```

To run the application preview instead:

```bash
pnpm app
```

Open [the application preview](http://127.0.0.1:5173/?preview=1).
The API and web application run separately; there is no single command that starts everything.
The backend accepts media at `POST /intake` and returns `202` for queued processing.
See [development setup](docs/development-setup.md) for the authenticated API and worker commands.

## Documentation

- [World Memory Package](docs/world-memory-package.md)
- [Development Setup](docs/development-setup.md)
- [Documentation Index](docs/README.md)

## License

Apache-2.0. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).
