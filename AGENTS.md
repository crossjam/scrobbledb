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

## ✅ Writing tests

A test that passes whether or not the fix is present is worse than no test — it
reads as coverage. Four habits, each earned from a review finding here:

- **Break it before you trust it.** Revert the fix, confirm the test fails,
  restore. A fixture has to make the right and wrong answers *different values*:
  four rows against a limit of five returns four either way.
- **Derive the set, don't type it.** For "every builder/function does X",
  discover the set programmatically and assert a floor on its size. A
  hand-written list of numeric parameters here covered 10 of 18.
- **Go through the production seam.** Call the real registration or entry point,
  not a local re-creation of it, or the test passes while production is
  misconfigured.
- **No bare `date.today()` / `datetime.now()` in assertions.** Bracket the call
  with reads on both sides and accept either, or compare instants with a
  tolerance. Otherwise it fails at midnight, on Sundays, or across a DST change.

<!-- BEGIN KATA (managed by `kata init --with-agents`) -->
## kata issue tracker

This project uses [kata](https://github.com/kenn-io/kata) as its shared issue
ledger. Run `kata quickstart` at the start of each session for the full agent
contract. The short version:

- Search before creating: `kata search "<keywords>" --agent`.
- Prefer updating existing issues over duplicates (`kata comment`, `kata label add`, `kata edit`).
- Default to `--agent` for ordinary reads and mutations; use `--json` only when a script needs structured data.
- Close only verified work: `kata close <ref> --done --message "<scope + verification>" --commit <sha>`.
- If work is incomplete, label `needs-review` and comment what remains rather than closing.
- Never `kata delete` or `kata purge` without explicit user authorization.
<!-- END KATA -->
