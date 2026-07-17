from __future__ import annotations

import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Header, Input, Static, TabbedContent, TabPane, Tree

from .dependency_tree import (
    application_context,
    build_adjacency,
    build_dependency_tree,
    workspace_context,
)
from .fixtures import repo_root_from_here
from .gateway import MockXynaGateway, TcpXynaGateway
from .models import (
    ApplicationDetailsRecord,
    ApplicationRecord,
    ContentItemRecord,
    DependencyRecord,
    ObjectSelectionRecord,
    WorkspaceDetailsRecord,
    WorkspaceRecord,
)
from .service import XynaService


class DeploymentContextRecord:
    def __init__(self, context_type: str, name: str, version: str, workspace: str, status: str) -> None:
        self.context_type = context_type
        self.name = name
        self.version = version
        self.workspace = workspace
        self.status = status


class DependencyTreeScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, root_context: str, dependency_records: list[DependencyRecord]) -> None:
        super().__init__()
        self.root_context = root_context
        self.dependency_records = dependency_records

    def compose(self) -> ComposeResult:
        yield Static(f"Dependency Tree: {self.root_context}")
        yield Tree(self.root_context, id="dependency-tree")
        yield Static("Press Esc or q to close")

    def on_mount(self) -> None:
        tree_widget = self.query_one("#dependency-tree", Tree)
        tree_widget.root.expand()
        dep_tree = build_dependency_tree(self.root_context, self.dependency_records)
        self._add_nodes(tree_widget.root, dep_tree)

    def _add_nodes(self, parent, node) -> None:
        for child in node.children:
            label = child.context
            if child.is_cycle:
                label = f"{label} [cycle]"
            elif child.is_truncated:
                label = f"{label} [max-depth]"
            branch = parent.add(label)
            if child.children and not child.is_cycle and not child.is_truncated:
                self._add_nodes(branch, child)

    def action_close(self) -> None:
        self.dismiss()


class DetailsScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield Static(self._title)
        yield Static(self._body, id="details-body")
        yield Static("Press Esc or q to close")

    def action_close(self) -> None:
        self.dismiss()


class WorkspaceDetailsScreen(ModalScreen[None]):
    CSS = """
    #workspace-summary-table { width: 36; }
    #workspace-content-items-table { width: 68; }
    #workspace-deployment-tree { min-width: 72; }
    """
    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        ("enter", "select_current", "Select"),
        ("tab", "next_table", "Next Table"),
        ("shift+tab", "previous_table", "Prev Table"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        details: WorkspaceDetailsRecord,
        dependency_records: list[DependencyRecord],
        service: XynaService,
    ) -> None:
        super().__init__()
        self.details = details
        self.dependency_records = dependency_records
        self.service = service
        self._all_content_items: list[ContentItemRecord] = []
        self._filtered_content_items: list[ContentItemRecord] = []

    def compose(self) -> ComposeResult:
        yield Static(f"Workspace Details: {self.details.name}")
        with Horizontal():
            with Vertical():
                yield Static("Summary")
                yield DataTable(id="workspace-summary-table")
            with Vertical():
                yield Static("Runtime Context Dependencies")
                yield Tree(workspace_context(self.details.name), id="workspace-dependencies-tree")
        with Horizontal():
            with Vertical():
                yield Static("Content Items")
                yield Input(placeholder="Filter items by type, name, or status", id="workspace-item-filter")
                yield DataTable(id="workspace-content-items-table")
            with Vertical():
                yield Static("Selected Item Deployment Details")
                yield Static("Selected Item: -", id="workspace-selected-item")
                yield Tree("Deployment Details", id="workspace-deployment-tree")
        yield Static("Use arrows to navigate. / focuses filter. Tab/Shift+Tab changes active widget. Esc/q closes.")

    def on_mount(self) -> None:
        summary = self.query_one("#workspace-summary-table", DataTable)
        summary.add_columns("Field", "Value")
        summary.add_row("State", self.details.state)
        summary.add_row("Requirements", str(len(self.details.requirements)))
        for obj_type in ["WORKFLOW", "DATATYPE", "EXCEPTION", "TRIGGER", "FILTER"]:
            summary.add_row(obj_type.title(), str(len(self.details.content_by_type.get(obj_type, []))))

        dep_tree_widget = self.query_one("#workspace-dependencies-tree", Tree)
        dep_tree_widget.root.expand()
        dep_tree = build_dependency_tree(workspace_context(self.details.name), self.dependency_records)
        self._add_dependency_nodes(dep_tree_widget.root, dep_tree)

        self._all_content_items = self.service.content_items(workspace_name=self.details.name)
        total_items = len(self._all_content_items)
        if total_items:
            self._render_content_items()

        summary.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "workspace-content-items-table":
            event.data_table.move_cursor(row=event.data_table.cursor_row, column=event.data_table.cursor_column)
            self._render_workspace_item_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "workspace-content-items-table":
            event.data_table.move_cursor(row=event.data_table.cursor_row, column=event.data_table.cursor_column)
            self._render_workspace_item_details()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id == "workspace-content-items-table":
            event.data_table.move_cursor(row=event.coordinate.row, column=event.coordinate.column)
            self._render_workspace_item_details()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "workspace-item-filter":
            self._render_content_items(event.value)

    def _render_content_items(self, filter_text: str = "") -> None:
        items_table = self.query_one("#workspace-content-items-table", DataTable)
        items_table.clear(columns=True)
        items_table.add_columns("Type", "Status", "Item")
        self._filtered_content_items = self._workspace_content_rows(filter_text)
        for item in self._filtered_content_items:
            items_table.add_row(self._display_object_type(item.object_type), item.status, item.object_name)
        if self._filtered_content_items:
            items_table.move_cursor(row=0, column=0)
            self._render_workspace_item_details()
        else:
            self.query_one("#workspace-selected-item", Static).update("Selected Item: -")
            self._fill_deployment_tree("#workspace-deployment-tree", None)

    def _workspace_content_rows(self, filter_text: str = "") -> list[ContentItemRecord]:
        text = filter_text.strip().lower()
        if not text:
            return list(self._all_content_items)
        return [
            item
            for item in self._all_content_items
            if text in item.object_type.lower()
            or text in self._display_object_type(item.object_type).lower()
            or text in item.object_name.lower()
            or text in item.status.lower()
        ]

    def _render_workspace_item_details(self) -> None:
        items_table = self.query_one("#workspace-content-items-table", DataTable)
        if items_table.row_count == 0:
            self.query_one("#workspace-selected-item", Static).update("Selected Item: -")
            self._fill_deployment_tree("#workspace-deployment-tree", None)
            return
        idx = items_table.cursor_row if items_table.cursor_row >= 0 else 0
        selected = self._filtered_content_items[idx]
        object_type = self._display_object_type(selected.object_type)
        object_name = selected.object_name
        self.query_one("#workspace-selected-item", Static).update(f"Selected Item: {object_type} {object_name}")
        try:
            record = self.service.deployment_item(
                object_name=object_name,
                workspace_name=self.details.name,
                verbose=True,
            )
        except Exception as exc:
            self._fill_deployment_tree("#workspace-deployment-tree", None, str(exc))
            return
        self._fill_deployment_tree("#workspace-deployment-tree", record)

    def _fill_deployment_tree(self, selector: str, record, error: str | None = None) -> None:
        tree = self.query_one(selector, Tree)
        tree.clear()
        tree.root.label = "Deployment Details"
        tree.root.expand()
        if error is not None:
            tree.root.add(f"Error: {error}")
            return
        if record is None:
            return
        info = tree.root.add("Summary")
        info.expand()
        info.add(f"Type: {record.item_type}")
        info.add(f"Name: {record.name}")
        info.add(f"Runtime Context: {record.runtime_context}")
        info.add(f"State: {record.state}")
        for section, items in record.detail_sections:
            branch = tree.root.add(section)
            branch.expand()
            for item in items:
                branch.add(item)

    def _display_object_type(self, object_type: str) -> str:
        return {
            "WORKFLOW": "WF",
            "DATATYPE": "DT",
            "EXCEPTION": "EX",
            "TRIGGER": "TR",
            "FILTER": "FI",
        }.get(object_type, object_type[:2])

    def action_select_current(self) -> None:
        focused = self.focused
        if focused is self.query_one("#workspace-content-items-table", DataTable):
            self._render_workspace_item_details()
            return

    def action_focus_filter(self) -> None:
        self.query_one("#workspace-item-filter", Input).focus()

    def _add_dependency_nodes(self, parent, node) -> None:
        if not node.children:
            return
        for child in node.children:
            label = child.context
            if child.is_cycle:
                label = f"{label} [cycle]"
            elif child.is_truncated:
                label = f"{label} [max-depth]"
            branch = parent.add(label)
            branch.expand()
            if child.children and not child.is_cycle and not child.is_truncated:
                self._add_dependency_nodes(branch, child)

    def action_next_table(self) -> None:
        tables = [
            self.query_one("#workspace-summary-table", DataTable),
            self.query_one("#workspace-item-filter", Input),
            self.query_one("#workspace-content-items-table", DataTable),
            self.query_one("#workspace-deployment-tree", Tree),
        ]
        self._cycle_focus(tables, direction=1)

    def action_previous_table(self) -> None:
        tables = [
            self.query_one("#workspace-summary-table", DataTable),
            self.query_one("#workspace-item-filter", Input),
            self.query_one("#workspace-content-items-table", DataTable),
            self.query_one("#workspace-deployment-tree", Tree),
        ]
        self._cycle_focus(tables, direction=-1)

    def _cycle_focus(self, tables: list[object], direction: int) -> None:
        focused = self.focused
        idx = tables.index(focused) if focused in tables else 0
        next_idx = (idx + direction) % len(tables)
        tables[next_idx].focus()

    def action_close(self) -> None:
        self.dismiss()


class ApplicationDetailsScreen(ModalScreen[None]):
    CSS = """
    #application-summary-table { width: 36; }
    #application-section-items-table { width: 68; }
    #application-deployment-tree { min-width: 72; }
    """
    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
        ("enter", "select_current", "Select"),
        ("tab", "next_table", "Next Table"),
        ("shift+tab", "previous_table", "Prev Table"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(
        self,
        details: ApplicationDetailsRecord,
        dependency_records: list[DependencyRecord],
        service: XynaService,
    ) -> None:
        super().__init__()
        self.details = details
        self.dependency_records = dependency_records
        self.service = service
        self._all_content_items: list[ContentItemRecord] = []
        self._filtered_content_items: list[ContentItemRecord] = []

    def compose(self) -> ComposeResult:
        yield Static(f"Application Details: {self.details.name} {self.details.version}")
        with Horizontal():
            with Vertical():
                yield Static("Summary")
                yield DataTable(id="application-summary-table")
            with Vertical():
                yield Static("Runtime Context Dependencies")
                yield Tree(application_context(self.details.name, self.details.version), id="application-dependencies-tree")
        with Horizontal():
            with Vertical():
                yield Static("Content Items")
                yield Input(placeholder="Filter items by type, name, or status", id="application-item-filter")
                yield DataTable(id="application-section-items-table")
            with Vertical():
                yield Static("Selected Item Deployment Details")
                yield Static("Selected Item: -", id="application-selected-item")
                yield Tree("Deployment Details", id="application-deployment-tree")
        yield Static("Use arrows to navigate. / focuses filter. Tab/Shift+Tab changes active widget. Esc/q closes.")

    def on_mount(self) -> None:
        dep_tree_widget = self.query_one("#application-dependencies-tree", Tree)
        dep_tree_widget.root.expand()
        dep_tree = build_dependency_tree(
            application_context(self.details.name, self.details.version),
            self.dependency_records,
        )
        self._add_dependency_nodes(dep_tree_widget.root, dep_tree)

        summary = self.query_one("#application-summary-table", DataTable)
        summary.add_columns("Field", "Value")
        summary.add_row("State", self.details.state)
        summary.add_row("Dependencies", str(len(self.details.dependencies)))
        self._all_content_items = self.service.content_items(
            application_name=self.details.name,
            version=self.details.version,
        )
        total_items = len(self._all_content_items)
        summary.add_row("Content Items", str(total_items))
        for section in ["WORKFLOW", "DATATYPE", "EXCEPTION", "TRIGGER", "FILTER"]:
            summary.add_row(section.title(), str(len(self.details.section_items.get(section, []))))
        summary.add_row("Order Entry", str(len(self.details.order_entry_lines)))

        if total_items:
            self._render_section_items()

        summary.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "application-section-items-table":
            event.data_table.move_cursor(row=event.data_table.cursor_row, column=event.data_table.cursor_column)
            self._render_application_item_details()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "application-section-items-table":
            event.data_table.move_cursor(row=event.data_table.cursor_row, column=event.data_table.cursor_column)
            self._render_application_item_details()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id == "application-section-items-table":
            event.data_table.move_cursor(row=event.coordinate.row, column=event.coordinate.column)
            self._render_application_item_details()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "application-item-filter":
            self._render_section_items(event.value)

    def _render_section_items(self, filter_text: str = "") -> None:
        items_table = self.query_one("#application-section-items-table", DataTable)
        items_table.clear(columns=True)
        items_table.add_columns("Type", "Status", "Item")
        self._filtered_content_items = self._application_content_rows(filter_text)
        for item in self._filtered_content_items:
            items_table.add_row(self._display_object_type(item.object_type), item.status, item.object_name)
        if self._filtered_content_items:
            items_table.move_cursor(row=0, column=0)
            self._render_application_item_details()
        else:
            self.query_one("#application-selected-item", Static).update("Selected Item: -")
            self._fill_deployment_tree("#application-deployment-tree", None)

    def _application_content_rows(self, filter_text: str = "") -> list[ContentItemRecord]:
        text = filter_text.strip().lower()
        if not text:
            return list(self._all_content_items)
        return [
            item
            for item in self._all_content_items
            if text in item.object_type.lower()
            or text in self._display_object_type(item.object_type).lower()
            or text in item.object_name.lower()
            or text in item.status.lower()
        ]

    def _render_application_item_details(self) -> None:
        items_table = self.query_one("#application-section-items-table", DataTable)
        if items_table.row_count == 0:
            self.query_one("#application-selected-item", Static).update("Selected Item: -")
            self._fill_deployment_tree("#application-deployment-tree", None)
            return
        idx = items_table.cursor_row if items_table.cursor_row >= 0 else 0
        selected = self._filtered_content_items[idx]
        object_type = self._display_object_type(selected.object_type)
        object_name = selected.object_name
        self.query_one("#application-selected-item", Static).update(f"Selected Item: {object_type} {object_name}")
        try:
            record = self.service.deployment_item(
                object_name=object_name,
                application_name=self.details.name,
                version=self.details.version,
                verbose=True,
            )
        except Exception as exc:
            self._fill_deployment_tree("#application-deployment-tree", None, str(exc))
            return
        self._fill_deployment_tree("#application-deployment-tree", record)

    def _fill_deployment_tree(self, selector: str, record, error: str | None = None) -> None:
        tree = self.query_one(selector, Tree)
        tree.clear()
        tree.root.label = "Deployment Details"
        tree.root.expand()
        if error is not None:
            tree.root.add(f"Error: {error}")
            return
        if record is None:
            return
        info = tree.root.add("Summary")
        info.expand()
        info.add(f"Type: {record.item_type}")
        info.add(f"Name: {record.name}")
        info.add(f"Runtime Context: {record.runtime_context}")
        info.add(f"State: {record.state}")
        for section, items in record.detail_sections:
            branch = tree.root.add(section)
            branch.expand()
            for item in items:
                branch.add(item)

    def _display_object_type(self, object_type: str) -> str:
        return {
            "WORKFLOW": "WF",
            "DATATYPE": "DT",
            "EXCEPTION": "EX",
            "TRIGGER": "TR",
            "FILTER": "FI",
        }.get(object_type, object_type[:2])

    def action_select_current(self) -> None:
        focused = self.focused
        if focused is self.query_one("#application-section-items-table", DataTable):
            self._render_application_item_details()
            return

    def action_focus_filter(self) -> None:
        self.query_one("#application-item-filter", Input).focus()

    def _add_dependency_nodes(self, parent, node) -> None:
        if not node.children:
            return
        for child in node.children:
            label = child.context
            if child.is_cycle:
                label = f"{label} [cycle]"
            elif child.is_truncated:
                label = f"{label} [max-depth]"
            branch = parent.add(label)
            branch.expand()
            if child.children and not child.is_cycle and not child.is_truncated:
                self._add_dependency_nodes(branch, child)

    def action_next_table(self) -> None:
        tables = [
            self.query_one("#application-summary-table", DataTable),
            self.query_one("#application-item-filter", Input),
            self.query_one("#application-section-items-table", DataTable),
            self.query_one("#application-deployment-tree", Tree),
        ]
        self._cycle_focus(tables, direction=1)

    def action_previous_table(self) -> None:
        tables = [
            self.query_one("#application-summary-table", DataTable),
            self.query_one("#application-item-filter", Input),
            self.query_one("#application-section-items-table", DataTable),
            self.query_one("#application-deployment-tree", Tree),
        ]
        self._cycle_focus(tables, direction=-1)

    def _cycle_focus(self, tables: list[object], direction: int) -> None:
        focused = self.focused
        idx = tables.index(focused) if focused in tables else 0
        next_idx = (idx + direction) % len(tables)
        tables[next_idx].focus()

    def action_close(self) -> None:
        self.dismiss()


class ObjectDependenciesScreen(ModalScreen[None]):
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, root_label: str, dependencies: list[tuple[int, str]]) -> None:
        super().__init__()
        self.root_label = root_label
        self.dependencies = dependencies

    def compose(self) -> ComposeResult:
        yield Static(f"Object Dependencies: {self.root_label}")
        yield Tree(self.root_label, id="object-dependency-tree")
        yield Static("Press Esc or q to close")

    def on_mount(self) -> None:
        tree = self.query_one("#object-dependency-tree", Tree)
        tree.root.expand()

        stack = {0: tree.root}
        for depth, label in self.dependencies:
            parent_depth = max(depth - 1, 0)
            parent = stack.get(parent_depth, tree.root)
            node = parent.add(label)
            stack[depth] = node

    def action_close(self) -> None:
        self.dismiss()


class ObjectSelectionScreen(ModalScreen[ObjectSelectionRecord | None]):
    BINDINGS = [
        ("enter", "choose", "Choose"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(self, title: str, objects: list[ObjectSelectionRecord]) -> None:
        super().__init__()
        self.title = title
        self.objects = objects

    def compose(self) -> ComposeResult:
        yield Static(self.title)
        yield DataTable(id="object-selection-table")
        yield Static("Select an object and press Enter. Esc/q closes.")

    def on_mount(self) -> None:
        table = self.query_one("#object-selection-table", DataTable)
        table.add_columns("Type", "Object")
        for obj in self.objects:
            table.add_row(obj.object_type, obj.object_name)
        table.focus()

    def action_choose(self) -> None:
        table = self.query_one("#object-selection-table", DataTable)
        if table.cursor_row < 0:
            self.dismiss(None)
            return
        row = table.get_row_at(table.cursor_row)
        self.dismiss(ObjectSelectionRecord(object_type=str(row[0]), object_name=str(row[1])))

    def action_close(self) -> None:
        self.dismiss(None)


class XynaTUIApplication(App[None]):
    TITLE = "Xyna Factory TUI"
    SUB_TITLE = "Dashboard, workspace, application, and property management"
    CSS = """
    #status-bar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    """
    BINDINGS = [
        ("r", "refresh_data", "Refresh"),
        ("d", "show_dependency_tree", "Dependency Tree"),
        ("i", "show_selected_details", "Details"),
        ("o", "show_object_dependencies", "Object Dependencies"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, service: XynaService) -> None:
        super().__init__()
        self.service = service
        self._workspace_records: list[WorkspaceRecord] = []
        self._application_records: list[ApplicationRecord] = []
        self._dependency_records: list[DependencyRecord] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                yield Static(id="dashboard-summary")
            with TabPane("Workspaces", id="workspaces"):
                yield DataTable(id="workspaces-table")
            with TabPane("Applications", id="applications"):
                yield DataTable(id="applications-table")
            with TabPane("Properties", id="properties"):
                yield DataTable(id="properties-table")
            with TabPane("Dependencies", id="dependencies"):
                yield Tree("Runtime Context Dependencies", id="dependencies-tree")
            with TabPane("Triggers", id="triggers"):
                yield DataTable(id="triggers-table")
            with TabPane("Filters", id="filters"):
                yield DataTable(id="filters-table")
        yield Static(id="status-bar")

    def on_mount(self) -> None:
        self.action_refresh_data()
        self._update_status_bar()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._update_status_bar(active_tab=event.tabbed_content.active)

    def _update_status_bar(self, active_tab: str | None = None) -> None:
        tab = active_tab or self.query_one(TabbedContent).active
        global_actions = "r Refresh | q Quit"

        tab_actions = {
            "workspaces": "d Dependency Tree | i Details | o Object Dependencies",
            "applications": "d Dependency Tree | i Details | o Object Dependencies",
            "dependencies": "Navigate tree with arrows",
            "dashboard": "",
            "properties": "",
            "triggers": "",
            "filters": "",
        }
        context = tab_actions.get(tab, "")
        content = f"[{tab}] {global_actions}"
        if context:
            content += f" | {context}"
        self.query_one("#status-bar", Static).update(content)

    def action_refresh_data(self) -> None:
        dashboard = self.service.dashboard()
        self.query_one("#dashboard-summary", Static).update(
            "\n".join(
                [
                    f"Factory state: {dashboard.factory_state}",
                    f"Uptime: {dashboard.uptime}",
                    f"Server version: {dashboard.server_version}",
                    f"XMOM version: {dashboard.xmom_version}",
                    f"Operating system: {dashboard.os_info}",
                ]
            )
        )

        self._workspace_records = self.service.workspaces()
        self._fill_table(
            "#workspaces-table",
            ["name", "revision", "status", "problems", "requirements"],
            self._workspace_records,
        )
        self._application_records = self.service.applications()
        self._fill_table(
            "#applications-table",
            ["name", "version", "workspace", "status", "objects", "revision"],
            self._application_records,
        )
        self._fill_table(
            "#properties-table",
            ["name", "value", "default_value", "reader", "unused"],
            self.service.properties(),
        )
        self._dependency_records = self.service.dependencies()
        self._fill_dependency_tree()

        self._fill_table(
            "#triggers-table",
            ["trigger", "runtime_context", "status", "instances"],
            self.service.triggers(),
        )
        self._fill_table(
            "#filters-table",
            ["filter_name", "runtime_context", "status", "instances"],
            self.service.filters(),
        )

    def _fill_table(self, selector: str, columns: list[str], records: list[object]) -> None:
        table = self.query_one(selector, DataTable)
        table.clear(columns=True)
        table.add_columns(*columns)
        for record in records:
            table.add_row(*(str(getattr(record, col)) for col in columns))

    def _fill_dependency_tree(self) -> None:
        tree = self.query_one("#dependencies-tree", Tree)
        tree.clear()
        tree.root.label = "Runtime Context Dependencies"
        tree.root.expand()

        adjacency = build_adjacency(self._dependency_records)
        all_owners = set(adjacency.keys())
        all_requirements = {child for children in adjacency.values() for child in children}
        roots = sorted(all_owners - all_requirements)
        if not roots:
            roots = sorted(all_owners)

        for root_context in roots:
            root_node = tree.root.add(root_context)
            root_node.expand()
            dep_tree = build_dependency_tree(root_context, self._dependency_records)
            self._add_dependency_nodes(root_node, dep_tree)

    def _add_dependency_nodes(self, parent, node) -> None:
        for child in node.children:
            label = child.context
            if child.is_cycle:
                label = f"{label} [cycle]"
            elif child.is_truncated:
                label = f"{label} [max-depth]"
            branch = parent.add(label)
            branch.expand()
            if child.children and not child.is_cycle and not child.is_truncated:
                self._add_dependency_nodes(branch, child)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        return

    def action_show_dependency_tree(self) -> None:
        tabbed = self.query_one(TabbedContent)

        if tabbed.active == "workspaces":
            context = self._selected_workspace_context()
            if not context:
                self.notify("No workspace selected", severity="warning")
                return
            self.push_screen(DependencyTreeScreen(context, self._dependency_records))
            return

        if tabbed.active == "applications":
            context = self._selected_application_context()
            if not context:
                self.notify("No application selected", severity="warning")
                return
            self.push_screen(DependencyTreeScreen(context, self._dependency_records))
            return

        self.notify("Open Workspaces or Applications to inspect dependencies", severity="information")

    def action_show_selected_details(self) -> None:
        tabbed = self.query_one(TabbedContent)
        try:
            if tabbed.active == "workspaces":
                details = self._selected_workspace_details()
                if not details:
                    self.notify("No workspace selected", severity="warning")
                    return
                self.push_screen(WorkspaceDetailsScreen(details, self._dependency_records, self.service))
                return

            if tabbed.active == "applications":
                details = self._selected_application_details()
                if not details:
                    self.notify("No application selected", severity="warning")
                    return
                self.push_screen(ApplicationDetailsScreen(details, self._dependency_records, self.service))
                return
        except Exception as exc:
            self.notify(f"Could not load details: {exc}", severity="error")
            return

        self.notify("Open Workspaces or Applications to view details", severity="information")

    def action_show_object_dependencies(self) -> None:
        tabbed = self.query_one(TabbedContent)
        try:
            if tabbed.active == "workspaces":
                if not self._workspace_records:
                    self.notify("No workspace selected", severity="warning")
                    return
                ws_table = self.query_one("#workspaces-table", DataTable)
                ws_idx = ws_table.cursor_row if ws_table.cursor_row >= 0 else 0
                ws_idx = min(ws_idx, len(self._workspace_records) - 1)
                ws = self._workspace_records[ws_idx]

                objects = self.service.objects_for_selection(workspace_name=ws.name)
                if not objects:
                    self.notify("No objects found in workspace", severity="warning")
                    return
                self.push_screen(
                    ObjectSelectionScreen(f"Select Object in Workspace {ws.name}", objects),
                    lambda selected: self._show_object_dependencies_for_workspace(ws.name, selected),
                )
                return

            if tabbed.active == "applications":
                if not self._application_records:
                    self.notify("No application selected", severity="warning")
                    return
                app_table = self.query_one("#applications-table", DataTable)
                app_idx = app_table.cursor_row if app_table.cursor_row >= 0 else 0
                app_idx = min(app_idx, len(self._application_records) - 1)
                app_rec = self._application_records[app_idx]

                objects = self.service.objects_for_selection(
                    application_name=app_rec.name,
                    version=app_rec.version,
                )
                if not objects:
                    self.notify("No objects found in application", severity="warning")
                    return
                self.push_screen(
                    ObjectSelectionScreen(
                        f"Select Object in Application {app_rec.name} {app_rec.version}",
                        objects,
                    ),
                    lambda selected: self._show_object_dependencies_for_application(
                        app_rec.name,
                        app_rec.version,
                        selected,
                    ),
                )
                return
        except Exception as exc:
            self.notify(f"Could not load object dependencies: {exc}", severity="error")
            return

        self.notify("Open Workspaces or Applications to view object dependencies", severity="information")

    def _show_object_dependencies_for_workspace(
        self,
        workspace_name: str,
        selected: ObjectSelectionRecord | None,
    ) -> None:
        if not selected:
            return
        deps = self.service.object_dependencies(
            object_name=selected.object_name,
            object_type=selected.object_type,
            workspace_name=workspace_name,
            recurse=True,
        )
        self.push_screen(ObjectDependenciesScreen(f"{selected.object_type} {selected.object_name}", deps))

    def _show_object_dependencies_for_application(
        self,
        application_name: str,
        version: str,
        selected: ObjectSelectionRecord | None,
    ) -> None:
        if not selected:
            return
        deps = self.service.object_dependencies(
            object_name=selected.object_name,
            object_type=selected.object_type,
            application_name=application_name,
            version=version,
            recurse=True,
        )
        self.push_screen(ObjectDependenciesScreen(f"{selected.object_type} {selected.object_name}", deps))

    def _selected_workspace_context(self) -> str | None:
        if not self._workspace_records:
            return None
        table = self.query_one("#workspaces-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._workspace_records) - 1)
        return workspace_context(self._workspace_records[idx].name)

    def _selected_application_context(self) -> str | None:
        if not self._application_records:
            return None
        table = self.query_one("#applications-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._application_records) - 1)
        app = self._application_records[idx]
        return application_context(app.name, app.version)

    def _selected_workspace_details(self) -> WorkspaceDetailsRecord | None:
        if not self._workspace_records:
            return None
        table = self.query_one("#workspaces-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._workspace_records) - 1)
        ws = self._workspace_records[idx]
        return self.service.workspace_details(ws.name)

    def _selected_application_details(self) -> ApplicationDetailsRecord | None:
        if not self._application_records:
            return None
        table = self.query_one("#applications-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._application_records) - 1)
        app = self._application_records[idx]
        return self.service.application_details(app.name, app.version)

def build_app(repo_root: Path | None = None, use_mock: bool | None = None) -> XynaTUIApplication:
    root = repo_root or repo_root_from_here()
    should_mock = use_mock if use_mock is not None else os.getenv("XYNA_TUI_USE_MOCK", "1") != "0"
    if should_mock:
        gateway = MockXynaGateway.from_repo_root(root)
    else:
        host = os.getenv("XYNA_TUI_HOST", "127.0.0.1")
        port = int(os.getenv("XYNA_TUI_PORT", "4242"))
        timeout = float(os.getenv("XYNA_TUI_TIMEOUT", "10"))
        gateway = TcpXynaGateway(host=host, port=port, timeout_seconds=timeout)
    service = XynaService(gateway)
    return XynaTUIApplication(service=service)


def run() -> None:
    build_app().run()


if __name__ == "__main__":
    run()
