# Plan to Implement Track Browsing TUI (Issue #18)

_Generated: 2025-11-25_

## Background

Currently, browsing scrobbles in scrobbledb requires using the search function, which forces users to provide a search term. To enhance usability, a Track Browsing Text-based User Interface (TUI) is needed to allow exploring the database without always searching.

Two possible approaches:
- **Hijack `search`**: Allowing null or '*' queries to retrieve all records, unfiltered.
- **Full TUI browser**: Build a richer, interactive interface, potentially using [`rich`](https://github.com/Textualize/rich) or [`textual`](https://github.com/Textualize/textual).

This plan focuses on implementing a full-featured TUI browser for user-friendly navigation and exploration.

## Goals

- Enable non-search-based browsing of scrobbles.
- Provide basic filtering, sorting, and column selection in the TUI.
- Ensure compatibility with SQLite backend.
- Focus on usability and responsiveness, even with substantial datasets.

## Implementation Checklist

- [x] **Evaluate TUI Frameworks**
  - Assess `rich` and `textual` for feature completeness, community support, and integration ease.
  - Decide on the framework; likely candidate: `textual` for more interactive capabilities.

- [x] **Design TUI Interface**
  - Sketch layout for table-based browsing with selectable columns (artist, track, album, timestamp, etc.).
  - Plan navigation (scrolling, paging, optional searching/filtering).

- [x] **Implement Data Adapter**
  - Build SQLite query adapter supporting retrieval, paging, and simple filters.
  - Test adapter for performance with large volumes of scrobbles.

- [x] **Build the Core Browser**
  - Create initial TUI window with table display.
  - Add interactivity: keyboard navigation, row selection, expanding details.

- [x] **Add Filtering and Sorting**
  - Implement interface controls for filtering by columns, sorting records.

- [ ] **Configure Column Selection**
  - Allow toggling visible columns for the user.

- [x] **Integrate with Application**
  - Add command or entry point to launch the TUI from the main app or CLI.

- [x] **Testing**
  - Write unit tests for data retrieval and adapter.
  - Implement integration test: launch TUI and verify correct rendering.
  - Add manual testing instructions: usability, navigation, edge-case handling.

- [x] **Documentation**
  - Update README or CLI help to instruct users how to launch and use the browser.
  - Provide screenshots or gifs if feasible.

---

## Framework Evaluation

### Candidates Considered

- **Rich:** Excellent for rendering tables, markdown, and beautiful terminal output. However, it does not provide interactive navigation or widget composition required for a browsing TUI.
- **Textual:** Built on top of Rich, Textual offers a robust platform for interactive TUIs. Supports keyboard/mouse navigation, dynamic layouts, and can render tables and other widgets using Rich.

### Decision

For implementing an interactive scrobble browser, **Textual** is the preferred framework. It provides:
- Interactive table navigation
- Layout customization (panels, modals, popups)
- Rich rendering capabilities
- Good support for extensibility

**Rich** will be used for rendering components within Textual, but not for interactive browsing.

---

## TUI Evaluation

### Rich vs. Textual

**Rich**
- **Purpose:** Library focused on rendering beautiful formatting in the terminal — tables, syntax highlighting, progress bars, markdown, tracebacks, etc.
- **Usage:** You use it to print styled output (e.g., rich tables) in standard terminal scripts and CLIs.
- **Interactivity:** Not interactive — output is static, updated only when printed.
- **Typical use:** Fancy print/output in Python command-line scripts.

**Textual**
- **Purpose:** Library for building full-featured, interactive terminal user interfaces (TUIs), like dashboards, browsers, file explorers, etc. Uses Rich for rendering widgets.
- **Usage:** You create components/widgets (buttons, tables, modals, layouts) that the user can interact with, similar to web UIs but inside the terminal.
- **Interactivity:** Highly interactive — supports keyboard and even mouse/touch (on supported terminals).
- **Typical use:** Building terminal apps with screens, navigation, user input.

#### Relationship
- **Textual was built on top of Rich** — it uses Rich components for pretty rendering.
- **Rich** is for non-interactive output.
- **Textual** builds a “mini app” inside your terminal that users can navigate.

#### Status
- The team behind Rich and Textual (Textualize) recently announced a shutdown. But both libraries remain popular and open-source. Many projects still rely on them.

#### Which to choose?
- If you need only pretty-printed tables/output: **Rich**.
- If you want a navigable, interactive browser: **Textual**.

---

_This evaluation was completed before starting the main implementation checklist (2025-11-25)._

## Future Considerations

- Look for existing Rich/Textual SQLite viewer and consider reuse to avoid reinventing.
- Evaluate more advanced features (e.g., inline editing, exporting, detail popups).

---

### Next Steps

- [X] Create a new branch for implementation (e.g., `feature/track-browse-tui`).
- [X]  Start with framework evaluation and TUI layout prototyping.
- [X] Progress through checklist above.

## Implementation Summary (2025-11-25)

The Track Browsing TUI has been implemented with the following components:

### New Files
- `src/scrobbledb/browse.py` - ScrobbleDataAdapter for database queries with filtering, sorting, and pagination
- `src/scrobbledb/tui.py` - Textual-based TUI application (ScrobbleBrowser)
- `tests/test_data_adapter.py` - Comprehensive tests for the data adapter

### Changes
- `pyproject.toml` - Added `textual>=0.85.0` as a dependency
- `src/scrobbledb/cli.py` - Added `browse` command to launch the TUI

### Usage
```bash
# Browse all tracks in the default database
scrobbledb browse

# Browse a specific database
scrobbledb browse /path/to/database.db
```

### Keyboard Shortcuts
- `/` - Focus the filter input
- `Escape` - Clear filter
- `n` - Next page
- `p` - Previous page  
- `r` - Refresh data
- `q` - Quit

