# Plan: Document scrobbledb CLI

## Goal
Produce comprehensive, user-friendly documentation for the scrobbledb CLI covering setup, configuration, and all available commands/subcommands.

## Steps
1. **Audit CLI surface**: Review `src/scrobbledb/cli.py`, command modules (e.g., `commands/stats.py`, `export.py`, `sql.py`), and README to list all commands, options, defaults, and behaviors.
2. **Outline documentation structure**: Decide on sections (installation/setup, configuration/authentication, command reference grouped by command, examples, troubleshooting) and choose file location (likely README expansion plus dedicated CLI guide under `docs/` or similar).
3. **Draft documentation content**: Write thorough descriptions for each command/subcommand, including option explanations, defaults, and example invocations for common workflows.
4. **Cross-check accuracy**: Verify descriptions against code (option defaults, behaviors) and adjust for clarity. Ensure references to paths (XDG dirs) and environment setup are correct.
5. **Polish and integrate**: Add navigation links, formatting, and update README to point to the new CLI documentation. Run tests or linters if applicable.

## Future improvements
- CI now runs `poe docs:cli` followed by a diff check in the QA workflow to prevent cog-generated help from drifting. Keep this guard in place when adjusting the documentation toolchain.
