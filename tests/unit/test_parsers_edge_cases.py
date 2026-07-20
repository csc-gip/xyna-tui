from __future__ import annotations

from xyna_tui.parsers import (
    parse_applications_table,
    parse_box_table,
    parse_dashboard_info,
    parse_deployment_item,
    parse_filter_table,
    parse_listwfs_names,
    parse_printdependencies_tree_lines,
    parse_workspaces_table,
    parse_properties_verbose,
    parse_runtime_dependencies,
    parse_trigger_table,
)


def test_parse_box_table_returns_empty_without_header() -> None:
    assert parse_box_table("plain text\nno table") == []


def test_parse_properties_verbose_handles_not_defined_and_reader() -> None:
    raw = (
        "Name: a.b.c Value: not defined Default value: 'x'  Reader: XynaFactory 'Comp'\n"
        "Name: d.e.f  UNUSED\n"
    )
    rows = parse_properties_verbose(raw)

    assert len(rows) == 2
    assert rows[0].name == "a.b.c"
    assert rows[0].value == "not"
    assert rows[0].default_value == "x"
    assert rows[0].reader == "XynaFactory 'Comp'"
    assert rows[1].unused is True


def test_parse_runtime_dependencies_ignores_orphan_indented_lines() -> None:
    raw = "  Application 'X', Version '1.0'\nWorkspace 'W'\n  Application 'A', Version '1.0'\n"
    rows = parse_runtime_dependencies(raw)

    assert len(rows) == 1
    assert rows[0].owner == "Workspace 'W'"


def test_parse_deployment_item_partial_fields() -> None:
    raw = "Type : Workflow\nName: abc.Def\n"
    item = parse_deployment_item(raw)

    assert item.item_type == "Workflow"
    assert item.name == "abc.Def"
    assert item.runtime_context == ""
    assert item.detail_rows == []
    assert item.detail_sections == []
    assert item.errors_saved == []
    assert item.errors_deployed == []
    assert item.publishes_saved == []
    assert item.publishes_deployed == []
    assert item.clean_deps_saved == []
    assert item.clean_deps_deployed == []
    assert item.interface_employments_saved == []
    assert item.interface_employments_deployed == []
    assert item.used_by_saved == []
    assert item.used_by_deployed == []


def test_parse_deployment_item_verbose_sections() -> None:
    raw = (
        "Type : Workflow\n"
        "Name: abc.Def\n"
        "RuntimeContext: Workspace 'W'\n"
        "State: DEPLOYED\n\n"
        "Interfaces abc.Def publishes in DEPLOYED state:\n"
        "  - WORKFLOW abc.Def\n"
    )
    item = parse_deployment_item(raw)

    assert item.state == "DEPLOYED"
    assert item.detail_rows == [("Interfaces abc.Def publishes in DEPLOYED state", "WORKFLOW abc.Def")]
    assert item.detail_sections == [(
        "Interfaces abc.Def publishes in DEPLOYED state",
        ["WORKFLOW abc.Def"],
    )]
    assert item.publishes_deployed == ["WORKFLOW abc.Def"]
    assert item.publishes_saved == []
    assert item.errors_deployed == []
    assert item.errors_saved == []


def test_parse_deployment_item_invalid_with_errors() -> None:
    raw = (
        "Type                : Workflow\n"
        "Name                : a.b.Wf\n"
        "RuntimeContext      : Workspace 'ws'\n"
        "State               : INVALID\n\n"
        "Interfaces a.b.Wf publishes in SAVED state:\n"
        "  - WORKFLOW a.b.Wf\n\n"
        "Interfaces a.b.Wf publishes in DEPLOYED state:\n"
        "  - WORKFLOW a.b.Wf\n\n"
        "Interfaces a.b.Wf uses in SAVED state:\n"
        "  - (7913) a.b.X must be of type UNKNOWN String\n"
        "  - DATATYPE a.b.Dep\n"
        "  - InterfaceEmployment in DATATYPE x.Param:\n"
        "    UNKNOWN boolean force\n\n"
        "Interfaces a.b.Wf uses in DEPLOYED state:\n"
        "  - (7913) a.b.X must be of type UNKNOWN String\n"
        "  - DATATYPE a.b.Dep\n"
        "  - InterfaceEmployment in DATATYPE x.Param:\n"
        "    UNKNOWN boolean force\n\n"
        "Objects that use a.b.Wf in SAVED state:\n"
        "  - a.b.Caller\n\n"
        "Objects that use a.b.Wf in DEPLOYED state:\n"
        "  - a.b.Caller\n"
    )
    item = parse_deployment_item(raw)

    assert item.state == "INVALID"
    # errors sorted by code number (7913 < 14716 etc)
    assert item.errors_saved == ["(7913) a.b.X must be of type UNKNOWN String"]
    assert item.errors_deployed == ["(7913) a.b.X must be of type UNKNOWN String"]
    # publishes identical in both states
    assert item.publishes_saved == ["WORKFLOW a.b.Wf"]
    assert item.publishes_deployed == ["WORKFLOW a.b.Wf"]
    # clean deps identical in both states
    assert item.clean_deps_saved == ["DATATYPE a.b.Dep"]
    assert item.clean_deps_deployed == ["DATATYPE a.b.Dep"]
    # employment identical in both states — context is the type name
    assert item.interface_employments_saved == [("x.Param", "UNKNOWN boolean force")]
    assert item.interface_employments_deployed == [("x.Param", "UNKNOWN boolean force")]
    # used_by identical in both states
    assert item.used_by_saved == ["a.b.Caller"]
    assert item.used_by_deployed == ["a.b.Caller"]


def test_parse_trigger_and_filter_table_first_block_only() -> None:
    trigger_raw = (
        "Id │ Trigger │ Name │ RuntimeContext │ Status │ Instances\n"
        "═══╪═════════╪══════╪════════════════╪════════╪══════════\n"
        "1  │ TClass   │ T1   │ RC             │ OK     │ 2\n\n"
        "Id │ Instance │ StartParameter\n"
    )
    filter_raw = (
        "Id │ FilterName │ RuntimeContext │ Status │ Instances\n"
        "═══╪════════════╪════════════════╪════════╪══════════\n"
        "1  │ F1         │ RC             │ OK     │ 1\n\n"
        "Id │ Instance │ ConfigurationParameter\n"
    )

    t_rows = parse_trigger_table(trigger_raw)
    f_rows = parse_filter_table(filter_raw)

    assert len(t_rows) == 1
    assert t_rows[0].trigger == "T1"
    assert len(f_rows) == 1
    assert f_rows[0].filter_name == "F1"


def test_parse_dashboard_info_unknown_fallbacks() -> None:
    info = parse_dashboard_info("", "", "")
    assert info.uptime == "unknown"
    assert info.server_version == "unknown"
    assert info.xmom_version == "unknown"
    assert info.os_info == "unknown"


def test_parse_workspaces_plain_text_fallback() -> None:
    raw = "default workspace, STATUS: 'OK'\nrdcatalog_ws, STATUS: 'WARNING'\n"
    rows = parse_workspaces_table(raw)
    assert len(rows) == 2
    assert rows[0].name == "default workspace"
    assert rows[1].status == "WARNING"


def test_parse_applications_plain_text_fallback() -> None:
    raw = (
        "RuntimeApplications:\n"
        "  'Base' '1.1.4' (109 objects + dependencies), STATUS: 'STOPPED' - ''\n"
        "  'GuiHttp' '1.4.3' (632 objects + dependencies), STATUS: 'RUNNING' - ''\n"
    )
    rows = parse_applications_table(raw)
    assert len(rows) == 2
    assert rows[0].name == "Base"
    assert rows[1].status == "RUNNING"


def test_parse_listwfs_names() -> None:
    raw = (
        "Listing deployment status information for 2 elements...\n"
        "        Name: a.b.Wf1, deployment status: DEPLOYED\n"
        "        Name: c.d.Wf2, deployment status: DEPLOYED_STOPPED\n"
    )
    assert parse_listwfs_names(raw) == ["a.b.Wf1", "c.d.Wf2"]


def test_parse_printdependencies_tree_lines() -> None:
    raw = (
        "Found the following dependency tree:\n"
        "* WORKFLOW: root\n"
        " . * ORDERTYPE: child1\n"
        " .  . * WORKFLOW: child2\n"
    )
    rows = parse_printdependencies_tree_lines(raw)
    assert rows == [
        (0, "WORKFLOW: root"),
        (1, "ORDERTYPE: child1"),
        (2, "WORKFLOW: child2"),
    ]
