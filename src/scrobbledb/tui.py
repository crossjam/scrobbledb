"""
Textual TUI application for browsing scrobbles.

Provides an interactive terminal interface for navigating through
listening history with filtering and sorting capabilities.
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    Select,
)
from textual.binding import Binding
from textual import on
from sqlite_utils import Database

from .browse import ScrobbleDataAdapter


class ScrobbleBrowser(App):
    """A Textual app for browsing scrobbles."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 1;
        grid-rows: auto 1fr auto;
    }

    #controls {
        height: auto;
        padding: 1;
        background: $surface;
        border-bottom: solid $primary;
    }

    #controls-row {
        height: auto;
        align: left middle;
    }

    #filter-column-select {
        width: 18;
        margin-right: 1;
    }

    #filter-input {
        width: 35;
        margin-right: 2;
    }

    #sort-select {
        width: 25;
        margin-right: 2;
    }

    #status {
        width: auto;
        color: $text-muted;
    }

    #table-container {
        height: 100%;
    }

    DataTable {
        height: 100%;
    }

    #info-bar {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "focus_filter", "Filter"),
        Binding("escape", "clear_filter", "Clear Filter"),
        Binding("n", "next_page", "Next Page"),
        Binding("p", "prev_page", "Prev Page"),
    ]

    SORT_OPTIONS = [
        ("Most Played", "plays_desc"),
        ("Least Played", "plays_asc"),
        ("Recently Played", "last_played_desc"),
        ("Oldest Played", "last_played_asc"),
        ("Artist A-Z", "artist_asc"),
        ("Artist Z-A", "artist_desc"),
        ("Track A-Z", "track_asc"),
        ("Track Z-A", "track_desc"),
        ("Album A-Z", "album_asc"),
        ("Album Z-A", "album_desc"),
    ]

    FILTER_COLUMN_OPTIONS = [
        ("All", "all"),
        ("Artist", "artist"),
        ("Album", "album"),
        ("Track", "track"),
    ]

    def __init__(self, db_path: str):
        """Initialize the browser with a database path."""
        super().__init__()
        self.db_path = db_path
        self.db = Database(db_path)
        self.adapter = ScrobbleDataAdapter(self.db)
        self.current_page = 0
        self.page_size = 50
        self.filter_text = ""
        self.filter_column = "all"
        self.sort_by = "last_played_desc"
        self.total_count = 0

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        with Container(id="controls"):
            with Horizontal(id="controls-row"):
                yield Select(
                    options=self.FILTER_COLUMN_OPTIONS,
                    value="all",
                    id="filter-column-select",
                    allow_blank=False,
                )
                yield Input(
                    placeholder="Filter...",
                    id="filter-input",
                )
                yield Select(
                    options=self.SORT_OPTIONS,
                    value="last_played_desc",
                    id="sort-select",
                    allow_blank=False,
                )
                yield Label("", id="status")

        with Container(id="table-container"):
            yield DataTable(id="tracks-table")

        yield Static("", id="info-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize the data table when the app starts."""
        table = self.query_one("#tracks-table", DataTable)
        table.cursor_type = "row"

        # Add columns
        table.add_column("Artist", width=25)
        table.add_column("Album", width=25)
        table.add_column("Track", width=30)
        table.add_column("Plays", width=8)
        table.add_column("Last Played", width=18)

        # Load initial data
        self.load_data()

    def load_data(self) -> None:
        """Load data into the table based on current filters and pagination."""
        table = self.query_one("#tracks-table", DataTable)
        table.clear()

        # Get total count
        self.total_count = self.adapter.get_total_count(
            filter_text=self.filter_text if self.filter_text else None,
            filter_column=self.filter_column,
        )

        # Get tracks for current page
        offset = self.current_page * self.page_size
        tracks = self.adapter.get_tracks(
            offset=offset,
            limit=self.page_size,
            filter_text=self.filter_text if self.filter_text else None,
            filter_column=self.filter_column,
            sort_by=self.sort_by,
        )

        # Add rows to table
        for track in tracks:
            last_played = track["last_played"]
            if last_played:
                # Format the datetime if it's a string
                if isinstance(last_played, str) and "T" in last_played:
                    last_played = last_played.replace("T", " ")[:16]
                elif isinstance(last_played, str):
                    last_played = last_played[:16]
            else:
                last_played = "-"

            table.add_row(
                track["artist_name"][:25] if track["artist_name"] else "-",
                track["album_title"][:25] if track["album_title"] else "-",
                track["track_title"][:30] if track["track_title"] else "-",
                str(track["play_count"]),
                last_played,
            )

        # Update status
        self.update_status()

    def update_status(self) -> None:
        """Update the status display."""
        status = self.query_one("#status", Label)
        info_bar = self.query_one("#info-bar", Static)

        start = self.current_page * self.page_size + 1
        end = min((self.current_page + 1) * self.page_size, self.total_count)
        total_pages = (self.total_count + self.page_size - 1) // self.page_size if self.total_count > 0 else 1

        if self.total_count > 0:
            status.update(f"Showing {start}-{end} of {self.total_count} tracks")
            info_bar.update(
                f"Page {self.current_page + 1}/{total_pages} | "
                f"[n] Next | [p] Prev | [/] Filter | [r] Refresh | [q] Quit"
            )
        else:
            status.update("No tracks found")
            info_bar.update(
                "[/] Filter | [r] Refresh | [q] Quit"
            )

    @on(Input.Submitted, "#filter-input")
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        """Handle filter input submission (press Enter to filter)."""
        self.filter_text = event.value.strip()
        self.current_page = 0
        self.load_data()

    @on(Input.Changed, "#filter-input")
    def on_filter_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes.

        Only filters on empty input (clearing the filter) or after 3+ characters
        to reduce database queries during typing. For immediate filtering,
        press Enter.
        """
        new_filter = event.value.strip()
        # Only auto-filter when clearing (empty) or when we have enough characters
        # to make a meaningful filter. This reduces database load during typing.
        if new_filter == "" or len(new_filter) >= 3:
            self.filter_text = new_filter
            self.current_page = 0
            self.load_data()

    @on(Select.Changed, "#filter-column-select")
    def on_filter_column_changed(self, event: Select.Changed) -> None:
        """Handle filter column selection change."""
        self.filter_column = str(event.value)
        self.current_page = 0
        # Only reload if there's an active filter
        if self.filter_text:
            self.load_data()

    @on(Select.Changed, "#sort-select")
    def on_sort_changed(self, event: Select.Changed) -> None:
        """Handle sort selection change."""
        self.sort_by = str(event.value)
        self.current_page = 0
        self.load_data()

    def action_refresh(self) -> None:
        """Refresh the data."""
        self.load_data()

    def action_focus_filter(self) -> None:
        """Focus the filter input."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.focus()

    def action_clear_filter(self) -> None:
        """Clear the filter and refresh."""
        filter_input = self.query_one("#filter-input", Input)
        filter_input.value = ""
        self.filter_text = ""
        self.current_page = 0
        self.load_data()

    def action_next_page(self) -> None:
        """Go to the next page."""
        total_pages = (self.total_count + self.page_size - 1) // self.page_size if self.total_count > 0 else 1
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.load_data()

    def action_prev_page(self) -> None:
        """Go to the previous page."""
        if self.current_page > 0:
            self.current_page -= 1
            self.load_data()


def run_browser(db_path: str) -> None:
    """
    Run the scrobble browser TUI.

    Args:
        db_path: Path to the SQLite database
    """
    app = ScrobbleBrowser(db_path)
    app.run()
