# Repository Guidelines

Always reply in Chinese-simplified.
Pay attention to any type of data structure, code style, project organization, testing practices, and development workflows mentioned in the files.

## Project Structure & Module Organization

- Python-first layout aimed at a single-exchange, event-driven trading loop. Proposed paths: `config/` for YAML/JSON configs, `data/` for historical samples, `engine/runner.py` as the main event loop, `market/` for data clients and models, `strategy/` for concrete strategies, `risk/` for guards, `broker/` for exchange or mock order adapters, `utils/` for shared helpers, and `main.py` as the entrypoint.
- Keep tests alongside code (`engine/tests/test_runner.py`) or in a top-level `tests/` mirror. Place fixtures under `tests/fixtures/`.
- Use `README.md` for user-facing run steps and `ROADMAP_V1.md` (现有文件) for scope decisions.

## Build, Test, and Development Commands

- Create a virtual env: `python -m venv .venv` then `source .venv/bin/activate` (or `Scripts\\activate` on Windows).
- Install deps (once `requirements.txt` exists): `pip install -r requirements.txt`.
- Run the app locally (example): `python main.py --config config/config.example.yml`.
- Run tests (pytest recommended): `pytest` or `pytest path/to/test_file.py`.
- Lint/format if configured: `ruff check .` and `black .`.

## Coding Style & Naming Conventions

- Follow PEP8 with 4-space indentation; prefer type hints on public functions and dataclasses for simple models.
- Modules and packages: lowercase with underscores (`risk/manager.py`); classes in `CamelCase`; functions/variables in `snake_case`.
- Log with structured, single-line messages that include symbol and order ids; avoid print.
- Keep configuration keys lowercase with hyphen-free words (e.g., `symbol`, `bar_interval`).

## Testing Guidelines

- Use pytest-style tests named `test_*.py`; test classes should start with `Test` and avoid side effects.
- Add unit tests for strategy logic, risk checks, and broker adapters; include a minimal mock market feed fixture.
- Aim for repeatable, offline tests; gate any live-exchange tests behind markers (e.g., `@pytest.mark.live`) and skip by default.

## Commit & Pull Request Guidelines

- Commits should be small, imperative, and scoped (e.g., `Add mock broker adapter`, `Refine MA crossover tests`); group refactors separately from behavior changes.
- In PRs, include: purpose, key changes, test results (`pytest`/lint output), and any config or data updates. Attach logs or sample output for trading loop changes.
- Link to issues/tasks when available and call out known limitations or follow-ups in a short checklist.

## Security & Configuration Tips

- Never commit API keys; use environment variables or `config/config.local.yml` in `.gitignore`.
- Validate external data before use; cap position sizes and set sane defaults in configs to prevent runaway trades in simulation or future live modes.
