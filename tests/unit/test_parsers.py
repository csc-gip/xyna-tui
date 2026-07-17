from __future__ import annotations

from xyna_tui.fixtures import extract_command_output, fixture_path, load_text, repo_root_from_here
from xyna_tui.parsers import (
    parse_applications_table,
    parse_dashboard_info,
    parse_properties_verbose,
    parse_runtime_dependencies,
    parse_workspaces_table,
)


def test_parse_workspaces_table() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "listworkspaces.txt"))
    output = extract_command_output(raw, "listworkspaces -t")

    records = parse_workspaces_table(output)

    assert len(records) == 2
    assert records[0].name == "default workspace"
    assert records[1].status == "WARNING"


def test_parse_applications_table() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "listapplications.txt"))
    output = extract_command_output(raw, "listapplications -t")

    records = parse_applications_table(output)

    assert len(records) >= 20
    running = [a for a in records if a.status == "RUNNING"]
    assert len(running) == 1
    assert running[0].name == "GuiHttp"


def test_parse_properties_verbose() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "listproperties.txt"))
    output = extract_command_output(raw, "listproperties -v")

    records = parse_properties_verbose(output)

    assert len(records) == 26
    assert any(r.name == "xyna.rmi.port.registry" for r in records)


def test_parse_runtime_dependencies() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "runtimecontextdependencies.txt"))
    output = extract_command_output(raw, "listruntimecontextdependencies")

    records = parse_runtime_dependencies(output)

    assert len(records) > 0
    assert records[0].owner.startswith("Application")


def test_parse_dashboard_info() -> None:
    raw = load_text(fixture_path(repo_root_from_here(), "status.txt"))
    uptime = extract_command_output(raw, "uptime")
    system = extract_command_output(raw, "listsysteminfo")
    version = extract_command_output(raw, "version")

    info = parse_dashboard_info(uptime, system, version)

    assert info.factory_state == "UP_AND_RUNNING"
    assert info.server_version == "10.8.0.0"
