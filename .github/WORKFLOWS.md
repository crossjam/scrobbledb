# GitHub Actions Workflows

This document describes the GitHub Actions workflows configured for this project.

## Overview

The project uses modern GitHub Actions workflows with:
- **uv** for fast, reliable Python package management
- **Python 3.11, 3.12, 3.13** (the project requires 3.11+)
- **poe** (Poe the Poet) task runner for consistent QA checks
- Latest action versions (checkout@v4, setup-python@v5, etc.)

## Workflows

### `qa.yml` - Continuous Integration

**Triggers:** Runs on every push to any branch and on all pull requests

**Purpose:** Ensures code quality and correctness across supported Python versions

**Steps:**
1. **Setup**: Checks out code, sets up Python, installs uv with caching
2. **Install dependencies**: Runs `uv sync` to install project dependencies
3. **Docs consistency**: Runs `poe docs:cli` and fails if cog regenerates any files under `docs/commands`
4. **Linting**: Runs `poe lint` (ruff check)
5. **Type checking**: Runs `poe type` (ty type checker)
6. **Security audit**: Runs `poe audit` (pip-audit for vulnerabilities)
   - Set to `continue-on-error: true` to not block builds on audit warnings
7. **Tests**: Runs `poe test` (pytest with verbose output)

**Python versions tested:** 3.11, 3.12, 3.13

**Matrix strategy:** `fail-fast: false` ensures all Python versions are tested even if one fails

### `publish.yml` - PyPI Publishing

**Triggers:** Runs when a GitHub release is published

**Purpose:** Builds and publishes the package to PyPI

**Architecture:**
This workflow uses a two-job architecture for security best practices:

1. **Build job:**
   - Builds the package with `uv build`
   - Uploads the distribution packages as artifacts

2. **Publish job:**
   - Downloads the built artifacts
   - Publishes to PyPI using trusted publishing (no API tokens needed!)

**Trusted Publishing:**
This workflow uses PyPI's trusted publishing feature which is more secure than API tokens:
- No secrets to manage or rotate
- Automatic verification through OIDC (OpenID Connect)
- Requires configuring the "pypi" environment in GitHub and setting up the publisher on PyPI

## Migration Notes

### Changes from Previous Setup

**Before (legacy):**
- Python 3.6, 3.7, 3.8 (all EOL)
- Poetry 1.0.0b3 (beta from 2019)
- actions/checkout@v1, setup-python@v1
- Only ran pytest
- Manual PyPI token management

**After (current):**
- Python 3.11, 3.12, 3.13 (current supported versions)
- uv (modern, fast package manager)
- actions/checkout@v4, setup-python@v5, setup-uv@v4
- Full QA suite: lint, type check, security audit, tests
- Trusted publishing (no tokens needed)

### Setting up Trusted Publishing

To enable trusted publishing for PyPI:

1. **On PyPI:**
   - Go to your project's settings on PyPI
   - Navigate to "Publishing" → "Add a new publisher"
   - Configure:
     - PyPI Project Name: `scrobbledb`
     - Owner: `crossjam`
     - Repository name: `scrobbledb`
     - Workflow name: `publish.yml`
     - Environment name: `pypi`

2. **On GitHub:**
   - Go to repository Settings → Environments
   - Create an environment named `pypi`
   - (Optional) Add protection rules like requiring reviewers

### Local Development Equivalents

The CI workflow steps can be run locally using the same commands:

```bash
# Setup (first time)
uv sync

# Run the same checks as CI
uv run poe lint          # Linting
uv run poe type          # Type checking
uv run poe audit         # Security audit
uv run poe test          # Tests

# Or run all checks at once
uv run poe qa            # Runs all of the above
```

## Maintenance

### Updating Python Versions

When updating supported Python versions:

1. Update `requires-python` in `pyproject.toml`
2. Update the matrix in `.github/workflows/qa.yml`
3. Consider updating the Python version used for building in `publish.yml`

### Updating Actions

To update action versions:

```yaml
# Check for updates at:
# - https://github.com/actions/checkout/releases
# - https://github.com/actions/setup-python/releases
# - https://github.com/astral-sh/setup-uv/releases
# - https://github.com/pypa/gh-action-pypi-publish/releases
```

### Troubleshooting

**If tests fail in CI but pass locally:**
- Ensure your local Python version matches one of the CI matrix versions
- Run `uv sync` to ensure dependencies are up to date
- Check if there are platform-specific issues (CI runs on Ubuntu)

**If publishing fails:**
- Verify trusted publishing is configured correctly on PyPI
- Check that the `pypi` environment exists in GitHub settings
- Ensure the workflow has `id-token: write` permission

**If security audit fails:**
- Review the audit output to understand the vulnerability
- Update the affected package if possible
- If a false positive or unavoidable, document why `continue-on-error: true` is acceptable

## Resources

- [uv documentation](https://docs.astral.sh/uv/)
- [GitHub Actions documentation](https://docs.github.com/en/actions)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
- [Poe the Poet documentation](https://poethepoet.natn.io/)
