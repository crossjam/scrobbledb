"""Tests for TUI Rich markup handling."""

import pytest
from rich.markup import escape, render


def test_info_bar_markup_escape():
    """Test that info bar strings with [/] are properly escaped."""
    # The strings that were causing MarkupError
    text_no_tracks = "[/] Filter | [r] Refresh | [q] Quit"
    text_with_nav = "Page 1/5 | [n] Next | [p] Prev | [/] Filter | [r] Refresh | [q] Quit"
    
    # These should work after escaping
    escaped_no_tracks = escape(text_no_tracks)
    escaped_with_nav = escape(text_with_nav)
    
    # Verify they can be rendered without MarkupError
    rendered_no_tracks = render(escaped_no_tracks)
    rendered_with_nav = render(escaped_with_nav)
    
    # Verify the output contains the expected keyboard shortcuts
    assert "[/]" in rendered_no_tracks.plain
    assert "[r]" in rendered_no_tracks.plain
    assert "[q]" in rendered_no_tracks.plain
    
    assert "[n]" in rendered_with_nav.plain
    assert "[p]" in rendered_with_nav.plain
    assert "[/]" in rendered_with_nav.plain
    assert "[r]" in rendered_with_nav.plain
    assert "[q]" in rendered_with_nav.plain


def test_unescaped_slash_causes_error():
    """Verify that unescaped [/] causes MarkupError as reported in the issue."""
    from rich.errors import MarkupError
    
    text_with_unescaped = "[/] Filter"
    
    # This should raise MarkupError
    with pytest.raises(MarkupError, match="has nothing to close"):
        render(text_with_unescaped)


def test_escape_function_escapes_all_brackets():
    """Test that escape() properly escapes all special bracket sequences."""
    text = "[/] Filter | [r] Refresh | [q] Quit"
    escaped = escape(text)
    
    # escape() adds backslashes before brackets
    assert r"\[" in escaped or "\\[" in escaped
    
    # Rendered text should match original (without markup interpretation)
    rendered = render(escaped)
    assert rendered.plain == text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
