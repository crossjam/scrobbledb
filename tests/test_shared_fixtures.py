"""
Tests for the fixtures in `tests/conftest.py` themselves.

Plugin isolation can only be observed across two tests, and an ordering
between two tests of this suite is not something to rely on. So each check
runs a small session of its own in a subprocess, with this suite's real
conftest copied in, and a control run without it shows the session would
otherwise fail.
"""

from pathlib import Path

import pytest

pytest.importorskip("datasette")

CONFTEST = Path(__file__).with_name("conftest.py")

#: The first test registers the plugin the way `serve` does and leaves it
#: there; the second only passes if that registration did not survive.
LEAKY_SESSION = """
from datasette.plugins import pm

from scrobbledb import datasette_plugin


def test_registers_and_walks_away():
    pm.register(datasette_plugin, name="scrobbledb")
    assert pm.is_registered(datasette_plugin)


def test_starts_without_it():
    assert not pm.is_registered(datasette_plugin)
"""


def run_session(pytester, monkeypatch, *, with_conftest):
    if with_conftest:
        pytester.makeconftest(CONFTEST.read_text())
        # The conftest imports its data from the `tests` package.
        monkeypatch.setenv("PYTHONPATH", str(CONFTEST.parent.parent))
    pytester.makepyfile(test_session=LEAKY_SESSION)
    return pytester.runpytest_subprocess("-p", "no:cacheprovider")


def test_a_registration_does_not_leak_into_the_next_test(pytester, monkeypatch):
    run_session(pytester, monkeypatch, with_conftest=True).assert_outcomes(passed=2)


def test_without_the_fixture_it_would(pytester, monkeypatch):
    """The control: the session above is one that can fail."""
    result = run_session(pytester, monkeypatch, with_conftest=False)
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*test_starts_without_it*"])
