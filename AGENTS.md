# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Start with `README.md`; contracts and profile examples are in `docs/api-and-profiles.md`.
- Run `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, and `.venv/bin/mypy voice_eval` before delivery.
- Treat C1-C3 from the credential-free evaluator as candidate signals with UNKNOWN verdicts. Only a schema/evidence-validated judge or explicit human assessment may make semantic claims. C4 and trusted-reference WER are deterministic.
- Keep real recordings, transcripts, provider responses, SQLite data, and credentials out of Git.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
