from __future__ import annotations

import pytest

from xyna_tui.fixtures import FixtureNotFoundError, extract_command_output, fixture_path, load_text, repo_root_from_here


def test_extract_command_output_returns_section_until_next_prompt() -> None:
    text = """host$ x one\nline1\nline2\nhost$ x two\nline3\n"""
    out = extract_command_output(text, "one")
    assert out == "line1\nline2"


def test_extract_command_output_uses_exact_command_match() -> None:
    text = """host$ x listapplications\na\nhost$ x listapplications -t\nb\n"""
    out = extract_command_output(text, "listapplications -t")
    assert out == "b"


def test_extract_command_output_for_last_command_to_eof() -> None:
    text = """host$ x alpha\nfirst\nhost$ x beta\nsecond\nthird\n"""
    out = extract_command_output(text, "beta")
    assert out == "second\nthird"


def test_extract_command_output_raises_for_unknown_command() -> None:
    text = """host$ x alpha\nfirst\n"""
    with pytest.raises(FixtureNotFoundError):
        extract_command_output(text, "gamma")


def test_extract_command_output_with_real_fixture() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "listworkspaces.txt"))
    out = extract_command_output(raw, "listworkspaces -t")

    assert "default workspace" in out
    assert "rdcatalog_ws" in out
