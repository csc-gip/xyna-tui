from __future__ import annotations

from xyna_tui.fixtures import extract_command_output, fixture_path, load_text, repo_root_from_here
from xyna_tui.parsers import parse_application_details, parse_workspace_details


def test_parse_workspace_details_from_fixture() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "listws-details.txt"))
    out = extract_command_output(raw, 'listworkspacedetails -workspaceName "default workspace"')

    details = parse_workspace_details(out)

    assert details.name == "default workspace"
    assert details.state == "OK"
    assert len(details.requirements) == 4
    assert details.content_by_type == {}
    assert details.requirements[0].startswith("Application 'SSH'")


def test_parse_application_details_from_fixture() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "listappdetails.txt"))
    out = extract_command_output(raw, "listapplicationdetails -applicationName Base")

    details = parse_application_details(out)

    assert details.name == "Base"
    assert details.version == "1.1.4"
    assert details.state == "STOPPED"
    assert details.dependencies == []
    assert details.sections["WORKFLOW"] > 0
    assert details.sections["DATATYPE"] > 0
    assert details.sections["EXCEPTION"] > 0
    assert details.sections["ORDER ENTRY INTERFACES"] == 0
    assert "WORKFLOW" in details.section_items
    assert details.section_items["WORKFLOW"][0].startswith("xmcp.manualinteraction")
    assert len(details.order_entry_lines) > 0
