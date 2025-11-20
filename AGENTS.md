# AGENTS.md

> A concise brief for AI coding agents working on this repository.  
> This project is a **Python package** managed with **uv** and tested with **pytest**.

---

## 🧭 Quick Start

You should never need to activate a virtualenv for this project
directly. Let uv handle it. Almost everything package or Python
related should start with ‘uv run‘ . There may be named tasks provided
by the ‘poe‘ package that simplify some things like running linting or
type checking.

```bash
# set up environment from pyproject + uv.lock
uv sync

# run the test suite (quiet, stop on first failure)
uv run pytest -q -x

# run tests with coverage reporting
uv run pytest --cov=./src/copyedit_ai --cov-report=html

# run type checks & lint (if dev deps are present)
uv run ty src/copyedit_ai
uv run ruff check src tests
uv run ruff format src tests

# run the package (replace with your module/CLI)
uv run python -m copyedit_ai --help

# poe is Poe the Poet, a Python task runner
# poe integrates well with pyproject.toml

# list tasks
poe
```
