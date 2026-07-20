from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, Input, Static, TabbedContent, Tree

from xyna_tui.app import build_app
from xyna_tui.fixtures import repo_root_from_here


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

        dashboard = app.query_one("#dashboard-summary", Static)
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


