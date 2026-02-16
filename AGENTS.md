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

# poe is Poe the Poet, a Python task runner
# poe integrates well with pyproject.toml

# list tasks
uv run poe

# run the test suite (quiet, stop on first failure)
uv run poe test:quick

# run tests with coverage reporting
uv run poe test:cov

# run type checks & lint (if dev deps are present)
uv run poe type
uv run poe lint
uv run poe lint:fix

# run the package (replace with your module/CLI)
uv run scrobbledb --help

```
