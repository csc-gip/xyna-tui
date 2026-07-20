from __future__ import annotations

from pathlib import Path

import pytest
from textual.binding import Binding
from textual.widgets import DataTable, Input, Select, Static, TabbedContent, Tree

from xyna_tui.app import build_app
from xyna_tui.fixtures import repo_root_from_here
from xyna_tui.models import PropertyRecord


def _assert_screenshot(app, output_dir: Path, name: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{name}.svg"
    if file_path.exists():
        file_path.unlink()
    saved = Path(app.save_screenshot(filename=file_path.name, path=str(output_dir)))
    assert saved.exists()
    assert "<svg" in saved.read_text(encoding="utf-8")
    return saved


@pytest.mark.asyncio
async def test_app_loads_mock_data() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()

        dashboard = app.query_one("#dashboard-metrics", Static)
        assert "UP_AND_RUNNING" in str(dashboard.render())

        workspaces = app.query_one("#workspaces-table", DataTable)
        applications = app.query_one("#applications-table", DataTable)
        properties = app.query_one("#properties-table", DataTable)

        assert workspaces.row_count == 2
        assert applications.row_count >= 20
        assert properties.row_count == 26


@pytest.mark.asyncio
async def test_refresh_action_keeps_data_loaded() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("r")
        await pilot.pause()

        dependencies = app.query_one("#dependencies-tree", Tree)

        pending = list(dependencies.root.children)
        count = 0
        while pending:
            node = pending.pop()
            count += 1
            pending.extend(node.children)
        assert count > 10


@pytest.mark.asyncio
async def test_dependency_tree_popup_from_workspace_and_application() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "workspaces"
        await pilot.pause()
        app.action_show_dependency_tree()
        await pilot.pause()
        tree = app.screen.query_one("#dependency-tree", Tree)
        assert "Workspace 'default workspace'" in str(tree.root.label)
        await pilot.press("escape")

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_dependency_tree()
        await pilot.pause()
        tree = app.screen.query_one("#dependency-tree", Tree)
        assert "Application 'Base', Version '1.1.4'" in str(tree.root.label)


@pytest.mark.asyncio
async def test_details_popup_from_workspace_and_application() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "workspaces"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()
        ws_summary = app.screen.query_one("#workspace-summary-table", DataTable)
        ws_deps = app.screen.query_one("#workspace-dependencies-tree", Tree)
        ws_items = app.screen.query_one("#workspace-content-items-table", DataTable)
        ws_deployment = app.screen.query_one("#workspace-deployment-tree", Tree)
        assert ws_summary.row_count >= 6
        assert len(ws_deps.root.children) >= 1
        assert ws_items.row_count >= 1
        workspace_item_types = {str(ws_items.get_row_at(i)[0]) for i in range(min(ws_items.row_count, 120))}
        assert "WF" in workspace_item_types
        assert "DT" in workspace_item_types
        assert str(ws_items.get_row_at(0)[1]) != ""
        assert len(ws_deployment.root.children) >= 2
        await pilot.press("escape")

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()
        app_deps = app.screen.query_one("#application-dependencies-tree", Tree)
        app_summary = app.screen.query_one("#application-summary-table", DataTable)
        app_items = app.screen.query_one("#application-section-items-table", DataTable)
        app_deployment = app.screen.query_one("#application-deployment-tree", Tree)
        assert "Application 'Base', Version '1.1.4'" in str(app_deps.root.label)
        assert app_summary.row_count >= 6
        assert app_items.row_count > 0
        application_item_types = {str(app_items.get_row_at(i)[0]) for i in range(min(app_items.row_count, 120))}
        assert "WF" in application_item_types
        assert "DT" in application_item_types
        assert str(app_items.get_row_at(0)[1]) != ""
        assert len(app_deployment.root.children) >= 2


@pytest.mark.asyncio
async def test_details_tab_focus_switching() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()

        assert app.screen.focused.id == "application-summary-table"
        await pilot.press("tab")
        await pilot.pause()
        assert app.screen.focused.id == "application-item-filter"
        await pilot.press("tab")
        await pilot.pause()
        assert app.screen.focused.id == "application-section-items-table"
        await pilot.press("tab")
        await pilot.pause()
        assert app.screen.focused.id == "application-deployment-tree"
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.screen.focused.id == "application-section-items-table"


@pytest.mark.asyncio
async def test_enter_selects_item_in_details_view() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()

        items = app.screen.query_one("#application-section-items-table", DataTable)
        selected = app.screen.query_one("#application-selected-item", Static)

        before = str(selected.render())

        items.focus()
        items.move_cursor(row=1, column=0)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        after = str(selected.render())
        assert after != before
        assert after.startswith("Selected Item: WF ")


@pytest.mark.asyncio
async def test_item_filter_reduces_application_item_list() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()

        filter_input = app.screen.query_one("#application-item-filter", Input)
        items = app.screen.query_one("#application-section-items-table", DataTable)
        before = items.row_count

        await pilot.press("/")
        await pilot.pause()
        assert app.screen.focused.id == "application-item-filter"
        await pilot.press("d", "e", "p", "l", "o", "y", "e", "d", "_", "s", "t", "o", "p", "p", "e", "d")
        await pilot.pause()

        after = items.row_count
        assert after > 0
        assert after < before
        assert all("DEPLOYED_STOPPED" in str(items.get_row_at(i)[1]) for i in range(after))


@pytest.mark.asyncio
async def test_workspace_item_filter_is_focusable_and_filters() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "workspaces"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()

        items = app.screen.query_one("#workspace-content-items-table", DataTable)
        before = items.row_count

        await pilot.press("/")
        await pilot.pause()
        assert app.screen.focused.id == "workspace-item-filter"
        await pilot.press("D", "T")
        await pilot.pause()

        after = items.row_count
        assert after > 0
        assert after < before
        assert all(str(items.get_row_at(i)[0]) == "DT" for i in range(after))


@pytest.mark.asyncio
async def test_workspace_item_cursor_moves_to_deeper_visible_rows() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "workspaces"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()

        items = app.screen.query_one("#workspace-content-items-table", DataTable)
        items.focus()
        target_row = min(25, items.row_count - 1)
        items.move_cursor(row=target_row, column=0)
        await pilot.pause()

        assert items.cursor_row == target_row


@pytest.mark.asyncio
async def test_object_dependencies_popup_from_workspace_and_application() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        tabs.active = "workspaces"
        await pilot.pause()
        app.action_show_object_dependencies()
        await pilot.pause()
        app.screen.action_choose()
        await pilot.pause()
        tree = app.screen.query_one("#object-dependency-tree", Tree)
        assert "Workflow csc.test.TestKeyInfo" in str(tree.root.label)
        await pilot.press("escape")

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_object_dependencies()
        await pilot.pause()
        app.screen.action_choose()
        await pilot.pause()
        tree = app.screen.query_one("#object-dependency-tree", Tree)
        assert "Workflow xmcp.manualinteraction.ManualInteraction" in str(tree.root.label)


@pytest.mark.asyncio
async def test_capture_view_screenshots() -> None:
    root = repo_root_from_here()
    output_dir = root / "test-results" / "screenshots"
    app = build_app(root, use_mock=True)

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)

        dashboard = _assert_screenshot(app, output_dir, "dashboard")
        assert dashboard.name == "dashboard.svg"

        tabs.active = "workspaces"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()
        workspace_details = _assert_screenshot(app, output_dir, "workspace-details")
        assert workspace_details.name == "workspace-details.svg"
        await pilot.press("escape")

        tabs.active = "applications"
        await pilot.pause()
        app.action_show_selected_details()
        await pilot.pause()
        application_details = _assert_screenshot(app, output_dir, "application-details")
        assert application_details.name == "application-details.svg"
        await pilot.press("escape")

        app.action_show_dependency_tree()
        await pilot.pause()
        dependency_tree = _assert_screenshot(app, output_dir, "application-dependency-tree")
        assert dependency_tree.name == "application-dependency-tree.svg"


def test_workspace_action_keybindings_are_registered() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)
    bindings = {binding.key: binding.action for binding in app.BINDINGS if isinstance(binding, Binding)}

    assert bindings["ctrl+p"] == "command_palette"
    assert bindings["ctrl+shift+p"] == "command_palette"
    assert bindings["f1"] == "command_palette"
    assert bindings["n"] == "workspace_create"
    assert bindings["c"] == "workspace_clear"
    assert bindings["delete"] == "workspace_remove"


@pytest.mark.asyncio
async def test_workspace_actions_call_service_methods() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    calls: dict[str, str] = {}
    refresh_count = 0
    selected_workspace_name = ""

    def _fake_create_workspace(name: str) -> None:
        calls["create"] = name

    def _fake_clear_workspace(name: str) -> None:
        calls["clear"] = name

    def _fake_remove_workspace(name: str) -> None:
        calls["remove"] = name

    def _fake_refresh_data() -> None:
        nonlocal refresh_count
        refresh_count += 1

    def _fake_push_screen(screen, callback=None):  # type: ignore[no-untyped-def]
        screen_id = type(screen).__name__
        if screen_id == "WorkspaceNameScreen" and callback is not None:
            callback("copilot e2e workspace")
            return
        if screen_id == "ConfirmScreen" and callback is not None:
            callback(True)
            return
        if screen_id == "BusyCommandScreen":
            return
        return None

    async with app.run_test() as pilot:
        app.service.create_workspace = _fake_create_workspace  # type: ignore[method-assign]
        app.service.clear_workspace = _fake_clear_workspace  # type: ignore[method-assign]
        app.service.remove_workspace = _fake_remove_workspace  # type: ignore[method-assign]
        app.action_refresh_data = _fake_refresh_data  # type: ignore[method-assign]
        app.push_screen = _fake_push_screen  # type: ignore[method-assign]

        await pilot.pause()
        tabs = app.query_one(TabbedContent)
        tabs.active = "workspaces"
        await pilot.pause()

        table = app.query_one("#workspaces-table", DataTable)
        table.move_cursor(row=0, column=0)
        selected_workspace_name = app._workspace_records[0].name

        app.action_workspace_create()
        app.action_workspace_clear()
        app.action_workspace_remove()
        await pilot.pause()

    assert calls["create"] == "copilot e2e workspace"
    assert calls["clear"] == selected_workspace_name
    assert calls["remove"] == selected_workspace_name
    assert refresh_count == 3


@pytest.mark.asyncio
async def test_workspace_create_modal_accepts_names_with_spaces() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    calls: list[str] = []

    def _fake_create_workspace(name: str) -> None:
        calls.append(name)

    def _fake_refresh_data() -> None:
        return None

    app.service.create_workspace = _fake_create_workspace  # type: ignore[method-assign]
    app.action_refresh_data = _fake_refresh_data  # type: ignore[method-assign]

    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)
        tabs.active = "workspaces"
        await pilot.pause()

        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one("#workspace-name-input", Input).has_focus

        await pilot.press("a", "l", "p", "h", "a", "space", "b", "e", "t", "a")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert calls == ["alpha beta"]


@pytest.mark.asyncio
async def test_properties_filters_and_mode_switching() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    calls: list[str] = []
    basic_records = [
        PropertyRecord(name="alpha.property", value="", default_value="", reader="Reader A", unused=False),
        PropertyRecord(name="beta.property", value="", default_value="", reader="Reader B", unused=False),
    ]
    verbose_records = [
        PropertyRecord(name="alpha.property", value="localhost", default_value="", reader="Reader A", unused=False),
        PropertyRecord(name="beta.property", value="false", default_value="true", reader="Reader B", unused=False),
    ]

    def _fake_properties(mode: str = "verbose", include_documentation: bool = False):
        calls.append(mode)
        return basic_records if mode == "basic" else verbose_records

    async with app.run_test() as pilot:
        app.service.properties = _fake_properties  # type: ignore[method-assign]
        app.action_refresh_data()
        await pilot.pause()

        tabs = app.query_one(TabbedContent)
        tabs.active = "properties"
        await pilot.pause()

        table = app.query_one("#properties-table", DataTable)
        assert table.row_count == 2

        name_filter = app.query_one("#property-name-filter", Input)
        name_filter.value = "beta"
        await pilot.pause()
        assert table.row_count == 1
        assert str(table.get_row_at(0)[0]) == "beta.property"

        name_filter.value = ""
        value_filter = app.query_one("#property-value-filter", Input)
        value_filter.value = "localhost"
        await pilot.pause()
        assert table.row_count == 1
        assert str(table.get_row_at(0)[0]) == "alpha.property"

        value_filter.value = ""
        mode_select = app.query_one("#properties-mode-select", Select)
        mode_select.value = "basic"
        await pilot.pause()
        assert calls[-1] == "basic"


@pytest.mark.asyncio
async def test_property_details_modal_updates_value_and_documentation() -> None:
    app = build_app(repo_root_from_here(), use_mock=True)

    property_record = PropertyRecord(
        name="xyna.default.monitoringlevel",
        value="20",
        default_value="5",
        reader="XynaFactory 'MonitoringDispatcher'",
        unused=False,
        documentation="Old doc",
    )
    updates: list[tuple[str, str, str]] = []
    refresh_count = 0

    def _fake_properties(mode: str = "verbose", include_documentation: bool = False):
        return [property_record]

    def _fake_property_details(name: str, fallback: PropertyRecord | None = None) -> PropertyRecord:
        assert name == property_record.name
        return property_record

    def _fake_set_property(name: str, value: str) -> None:
        updates.append(("value", name, value))

    def _fake_set_property_documentation(name: str, documentation: str, language: str = "EN") -> None:
        updates.append((f"documentation:{language}", name, documentation))

    def _fake_refresh_data() -> None:
        nonlocal refresh_count
        refresh_count += 1

    async with app.run_test() as pilot:
        app.service.properties = _fake_properties  # type: ignore[method-assign]
        app.service.property_details = _fake_property_details  # type: ignore[method-assign]
        app.service.set_property = _fake_set_property  # type: ignore[method-assign]
        app.service.set_property_documentation = _fake_set_property_documentation  # type: ignore[method-assign]
        app.action_refresh_data = _fake_refresh_data  # type: ignore[method-assign]
        app._refresh_properties_data()
        await pilot.pause()

        tabs = app.query_one(TabbedContent)
        tabs.active = "properties"
        await pilot.pause()

        table = app.query_one("#properties-table", DataTable)
        table.move_cursor(row=0, column=0)

        app.action_show_selected_details()
        await pilot.pause()
        app.screen.dismiss(("10", "New doc", "Neuer Text"))
        await pilot.pause()

    assert updates == [
        ("value", "xyna.default.monitoringlevel", "10"),
        ("documentation:EN", "xyna.default.monitoringlevel", "New doc"),
        ("documentation:DE", "xyna.default.monitoringlevel", "Neuer Text"),
    ]
    assert refresh_count == 1


