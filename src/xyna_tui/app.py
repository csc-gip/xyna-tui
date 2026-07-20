from __future__ import annotations

import asyncio
from datetime import datetime
import os
from queue import Empty, Queue
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import DataTable, Header, Input, Select, Static, TabbedContent, TabPane, TextArea, Tree

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
    DeploymentItemRecord,
    ObjectSelectionRecord,
    PropertyRecord,
    WorkspaceDetailsRecord,
    WorkspaceRecord,
)
from .service import XynaService

_STATE_COLORS: dict[str, str] = {
    "DEPLOYED": "green",
    "INVALID": "red",
    "SAVED": "yellow",
}


def _render_deployment_tree(
    tree: Tree,
    record: DeploymentItemRecord | None,
    error: str | None = None,
) -> None:
    """Populate *tree* with structured deployment-item data."""
    tree.clear()
    tree.root.label = "Deployment Details"
    tree.root.expand()

    if error is not None:
        err_node = tree.root.add("[red]Error loading details[/red]")
        err_node.add(error)
        return
    if record is None:
        return

    state_color = _STATE_COLORS.get(record.state, "white")
    is_ok = record.state == "DEPLOYED" and not record.errors_deployed and not record.errors_saved

    # ── Summary ──────────────────────────────────────────────────────────────
    summary = tree.root.add("[bold]Summary[/bold]")
    summary.expand()
    summary.add(f"Type    : {record.item_type}")
    summary.add(f"State   : [{state_color}]{record.state}[/{state_color}]")
    summary.add(f"Context : {record.runtime_context}")

    # ── Issues (only when there are errors) ──────────────────────────────────
    all_errors = record.errors_saved + record.errors_deployed
    if all_errors:
        # Check if SAVED and DEPLOYED differ
        saved_set = set(record.errors_saved)
        deployed_set = set(record.errors_deployed)
        states_differ = saved_set != deployed_set

        n_errors = len(set(all_errors))  # unique count
        plural = "s" if n_errors != 1 else ""
        issues = tree.root.add(
            f"[red bold]\u26a0  Issues ({n_errors} error{plural})[/red bold]"
        )
        issues.expand()

        if states_differ:
            # Show SAVED errors
            if record.errors_saved:
                saved_node = issues.add("[yellow]SAVED state[/yellow]")
                saved_node.expand()
                for err in record.errors_saved:
                    saved_node.add(f"[red]{err}[/red]")
            # Show DEPLOYED errors
            if record.errors_deployed:
                deployed_node = issues.add("[green]DEPLOYED state[/green]")
                deployed_node.expand()
                for err in record.errors_deployed:
                    deployed_node.add(f"[red]{err}[/red]")
        else:
            # States are same, show as single list (already sorted by code)
            for err in record.errors_deployed or record.errors_saved:
                issues.add(f"[red]{err}[/red]")

    # ── Published Interfaces ─────────────────────────────────────────────────
    publishes = list(set(record.publishes_saved + record.publishes_deployed))
    if publishes:
        pub = tree.root.add(f"Published Interfaces ({len(publishes)})")
        if is_ok:
            pub.expand()
        for p in sorted(publishes):
            pub.add(p)

    # ── Dependencies ─────────────────────────────────────────────────────────
    all_deps = record.clean_deps_saved + record.clean_deps_deployed
    all_emps = record.interface_employments_saved + record.interface_employments_deployed
    n_deps = len(set(all_deps)) + len(set(all_emps))
    if n_deps > 0:
        dep = tree.root.add(f"Dependencies ({n_deps})")
        if is_ok:
            dep.expand()
        for d in sorted(set(all_deps)):
            dep.add(d)
        for ctx, sig in sorted(set(all_emps)):
            emp = dep.add(f"[dim]via[/dim] {ctx}")
            emp.add(sig)

    # ── Used By ──────────────────────────────────────────────────────────────
    used_by = list(set(record.used_by_saved + record.used_by_deployed))
    if used_by:
        used = tree.root.add(f"Used By ({len(used_by)})")
        if is_ok:
            used.expand()
        for u in sorted(used_by):
            used.add(u)


class DeploymentContextRecord:
    def __init__(self, context_type: str, name: str, version: str, workspace: str, status: str) -> None:
        self.context_type = context_type
        self.name = name
        self.version = version
        self.workspace = workspace
        self.status = status


class DependencyTreeScreen(ModalScreen[None]):
    CSS = """
    DependencyTreeScreen {
        background: #0f1419 85%;
    }
    #dependency-tree {
        border: round $primary;
        padding: 0 1;
        background: #0f1419;
        color: #ffffff;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("q", "close", "Close", priority=True),
    ]

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

    def action_close(self) -> None:
        self.dismiss()


class WorkspaceDetailsScreen(ModalScreen[None]):
    CSS = """
    WorkspaceDetailsScreen {
        layout: vertical;
        background: #0f1419 85%;
        color: #ffffff;
    }
    #ws-top-row {
        height: 1fr;
        margin-bottom: 1;
    }
    #ws-bottom-row {
        height: 2fr;
    }
    #ws-top-summary-panel {
        width: 30%;
    }
    #ws-top-deps-panel {
        width: 70%;
    }
    #ws-bottom-items-panel {
        width: 35%;
    }
    #ws-bottom-detail-panel {
        width: 65%;
    }
    #ws-top-summary-panel,
    #ws-top-deps-panel,
    #ws-bottom-items-panel,
    #ws-bottom-detail-panel {
        border: round $primary;
        background: #0f1419;
        padding: 0 1;
    }
    #workspace-summary-table,
    #workspace-content-items-table,
    #workspace-deployment-tree,
    #workspace-dependencies-tree {
        color: #ffffff;
        background: #11161c;
    }
    #workspace-item-filter {
        margin-bottom: 1;
        background: #11161c;
        color: #ffffff;
        border: tall $primary;
    }
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
        with Horizontal(id="ws-top-row"):
            with Vertical(id="ws-top-summary-panel"):
                yield Static("Summary")
                yield DataTable(id="workspace-summary-table")
            with Vertical(id="ws-top-deps-panel"):
                yield Static("Runtime Context Dependencies")
                yield Tree(workspace_context(self.details.name), id="workspace-dependencies-tree")
        with Horizontal(id="ws-bottom-row"):
            with Vertical(id="ws-bottom-items-panel"):
                yield Static("Content Items")
                yield Input(placeholder="Filter items by type, name, or status", id="workspace-item-filter")
                yield DataTable(id="workspace-content-items-table")
            with Vertical(id="ws-bottom-detail-panel"):
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
        _render_deployment_tree(self.query_one(selector, Tree), record, error)

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
    ApplicationDetailsScreen {
        layout: vertical;
        background: #0f1419 85%;
        color: #ffffff;
    }
    #app-top-row {
        height: 1fr;
        margin-bottom: 1;
    }
    #app-bottom-row {
        height: 2fr;
    }
    #app-top-summary-panel {
        width: 30%;
    }
    #app-top-deps-panel {
        width: 70%;
    }
    #app-bottom-items-panel {
        width: 35%;
    }
    #app-bottom-detail-panel {
        width: 65%;
    }
    #app-top-summary-panel,
    #app-top-deps-panel,
    #app-bottom-items-panel,
    #app-bottom-detail-panel {
        border: round $primary;
        background: #0f1419;
        padding: 0 1;
    }
    #application-summary-table,
    #application-section-items-table,
    #application-deployment-tree,
    #application-dependencies-tree {
        color: #ffffff;
        background: #11161c;
    }
    #application-item-filter {
        margin-bottom: 1;
        background: #11161c;
        color: #ffffff;
        border: tall $primary;
    }
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
        with Horizontal(id="app-top-row"):
            with Vertical(id="app-top-summary-panel"):
                yield Static("Summary")
                yield DataTable(id="application-summary-table")
            with Vertical(id="app-top-deps-panel"):
                yield Static("Runtime Context Dependencies")
                yield Tree(application_context(self.details.name, self.details.version), id="application-dependencies-tree")
        with Horizontal(id="app-bottom-row"):
            with Vertical(id="app-bottom-items-panel"):
                yield Static("Content Items")
                yield Input(placeholder="Filter items by type, name, or status", id="application-item-filter")
                yield DataTable(id="application-section-items-table")
            with Vertical(id="app-bottom-detail-panel"):
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
        _render_deployment_tree(self.query_one(selector, Tree), record, error)

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
    CSS = """
    ObjectDependenciesScreen {
        background: #0f1419 85%;
    }
    #object-dependency-tree {
        border: round $primary;
        padding: 0 1;
        background: #0f1419;
        color: #ffffff;
    }
    """
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


_XYNA_THEME = Theme(
    name="xyna",
    primary="#FABB00",
    background="#000000",
    surface="#0d0d0d",
    panel="#1a1a1a",
    foreground="#FFFFFF",
    dark=True,
)


class KeybindingsScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("?", "close", "Close"),
    ]
    CSS = """
    KeybindingsScreen {
        align: center middle;
    }
    #keybindings-container {
        width: 70;
        height: auto;
        max-height: 90%;
        border: round #FABB00;
        padding: 1 2;
        background: #000000;
    }
    #keybindings-title {
        text-align: center;
        color: #FABB00;
        text-style: bold;
        margin-bottom: 1;
    }
    .kb-section-header {
        color: #FABB00;
        text-style: bold;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="keybindings-container"):
            yield Static("Key Bindings", id="keybindings-title")
            yield Static("[bold]Main Screen[/bold]", classes="kb-section-header")
            yield Static(
                "  r            Refresh data\n"
                "  x            Workspace: refresh | Application: start/stop\n"
                "  Shift+X/X    Workspace: refresh and deploy\n"
                "  Ctrl+X       Workspace: refresh and deploy (fallback)\n"
                "  Ctrl+P       Command palette\n"
                "  Ctrl+Shift+P Command palette (fallback)\n"
                "  F1           Command palette (fallback)\n"
                "  n            Workspace: create\n"
                "  c            Workspace: clear\n"
                "  Delete       Workspace: remove\n"
                "  u            Property: reset to default\n"
                "  d            Show Dependency Tree\n"
                "  i            Show Item Details\n"
                "  o            Show Object Dependencies\n"
                "  /            Property: focus name filter\n"
                "  ?            Show this help\n"
                "  q            Quit"
            )
            yield Static("[bold]Workspace / Application Details[/bold]", classes="kb-section-header")
            yield Static(
                "  /            Focus filter input\n"
                "  Enter        Select current item\n"
                "  Tab          Next widget\n"
                "  Shift+Tab    Previous widget\n"
                "  Esc / q      Close screen"
            )
            yield Static("[bold]Dependency Tree / Object Dependencies[/bold]", classes="kb-section-header")
            yield Static(
                "  Arrow keys   Navigate tree\n"
                "  Esc / q      Close screen"
            )
            yield Static("[bold]Object Selection[/bold]", classes="kb-section-header")
            yield Static(
                "  Arrow keys   Navigate list\n"
                "  Enter        Confirm selection\n"
                "  Esc / q      Cancel"
            )
            yield Static("\n[dim]Press Esc or q to close[/dim]")

    def action_close(self) -> None:
        self.dismiss()


class StreamingCommandScreen(ModalScreen[None]):
    CSS = """
    StreamingCommandScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #stream-panel {
        width: 100;
        height: 28;
        max-height: 90%;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 0 1;
    }
    #stream-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #stream-output-container {
        height: 1fr;
        border: heavy #2a333d;
        margin-bottom: 1;
        background: #11161c;
    }
    #stream-output {
        color: #ffffff;
    }
    #stream-status {
        color: #ffffff;
    }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("c", "copy_output", "Copy Output"),
        ("s", "save_output", "Save Output"),
    ]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self._chunks: Queue[str] = Queue()
        self._buffer = ""
        self._done = False

    def compose(self) -> ComposeResult:
        with Vertical(id="stream-panel"):
            yield Static(self.title, id="stream-title")
            with ScrollableContainer(id="stream-output-container"):
                yield Static("", id="stream-output")
            yield Static("Running...", id="stream-status")
            yield Static("c: copy output  |  s: save output  |  Esc/q: close")

    def on_mount(self) -> None:
        self.set_interval(0.1, self._drain_chunks)

    def enqueue_chunk(self, chunk: str) -> None:
        if chunk:
            self._chunks.put(chunk)

    def mark_done(self, success: bool, message: str) -> None:
        self._drain_chunks()
        color = "green" if success else "red"
        self.query_one("#stream-status", Static).update(
            f"[{color}]{message}[/{color}]  Press Esc/q to close"
        )
        self._done = True

    def _drain_chunks(self) -> None:
        updated = False
        while True:
            try:
                chunk = self._chunks.get_nowait()
            except Empty:
                break
            normalized = chunk.replace("\r", "")
            if normalized:
                self._buffer += normalized
                if not self._buffer.endswith("\n"):
                    self._buffer += "\n"
                updated = True
        if updated:
            self.query_one("#stream-output", Static).update(self._buffer.rstrip())
            self.query_one("#stream-output-container", ScrollableContainer).scroll_end(animate=False)

    def action_copy_output(self) -> None:
        text = self._buffer.rstrip()
        if not text:
            self.notify("No output to copy", severity="warning")
            return
        copy_fn = getattr(self.app, "copy_to_clipboard", None)
        if callable(copy_fn):
            copy_fn(text)
            self.notify("Output copied to clipboard", severity="information")
            return
        self.notify("Clipboard copy is not available in this environment", severity="warning")

    def action_save_output(self) -> None:
        text = self._buffer.rstrip()
        if not text:
            self.notify("No output to save", severity="warning")
            return
        root = repo_root_from_here()
        out_dir = root / "test-results" / "stream-logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        file_path = out_dir / f"stream-{ts}.log"
        file_path.write_text(text + "\n", encoding="utf-8")
        self.notify(f"Saved output to {file_path}", severity="information")

    def action_close(self) -> None:
        self.dismiss()


class BusyCommandScreen(ModalScreen[None]):
    CSS = """
    BusyCommandScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #busy-panel {
        width: 54;
        height: auto;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #busy-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    """
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self._spinner = ["|", "/", "-", "\\"]
        self._spinner_idx = 0
        self._done = False

    def compose(self) -> ComposeResult:
        with Vertical(id="busy-panel"):
            yield Static(self.title, id="busy-title")
            yield Static("| Waiting for factory response...", id="busy-status")

    def on_mount(self) -> None:
        self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        if self._done:
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner)
        frame = self._spinner[self._spinner_idx]
        self.query_one("#busy-status", Static).update(f"{frame} Waiting for factory response...")

    def mark_done(self, success: bool, message: str) -> None:
        self._done = True
        color = "green" if success else "red"
        self.query_one("#busy-status", Static).update(
            f"[{color}]{message}[/{color}]  Press Esc/q to close"
        )

    def action_close(self) -> None:
        self.dismiss()


class ConfirmScreen(ModalScreen[bool]):
    CSS = """
    ConfirmScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #confirm-panel {
        width: 72;
        max-width: 90%;
        height: auto;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #confirm-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("enter", "confirm", "Yes"),
        ("escape", "cancel", "No"),
        ("q", "cancel", "No"),
    ]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.title = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-panel"):
            yield Static(self.title, id="confirm-title")
            yield Static(self.message)
            yield Static("\nPress y/Enter to confirm, n/Esc to cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class WorkspaceNameScreen(ModalScreen[str | None]):
    CSS = """
    WorkspaceNameScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #workspace-name-panel {
        width: 80;
        max-width: 90%;
        height: auto;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #workspace-name-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #workspace-name-input {
        margin-top: 1;
    }
    """
    BINDINGS = [
        Binding("enter", "submit", "Create", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("q", "cancel", "Cancel", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="workspace-name-panel"):
            yield Static("Create workspace", id="workspace-name-title")
            yield Static("Enter workspace name:")
            yield Input(placeholder="workspace name", id="workspace-name-input")
            yield Static("Enter: create  |  Esc/q: cancel")

    def on_mount(self) -> None:
        self.query_one("#workspace-name-input", Input).focus()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one("#workspace-name-input", Input).value.strip()
        if not value:
            self.notify("Workspace name must not be empty", severity="warning")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PropertyDetailsScreen(ModalScreen[tuple[str, str, str] | None]):
    CSS = """
    PropertyDetailsScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #property-details-panel {
        width: 110;
        max-width: 95%;
        height: auto;
        max-height: 90%;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #property-details-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #property-value-input {
        margin: 1 0;
    }
    #property-documentation-en-input,
    #property-documentation-de-input {
        height: 6;
        margin-top: 1;
        border: tall $primary;
        background: #11161c;
        color: #ffffff;
    }
    #property-meta {
        color: #dfe7ef;
    }
    #property-doc-en-label,
    #property-doc-de-label {
        margin-top: 1;
    }
    """
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+g", "cancel", "Cancel", priority=True),
        Binding("tab", "next_field", "Next Field", priority=True),
        Binding("shift+tab", "previous_field", "Previous Field", priority=True),
    ]

    def __init__(self, record: PropertyRecord, documentation_en: str = "", documentation_de: str = "") -> None:
        super().__init__()
        self.record = record
        self.documentation_en = documentation_en
        self.documentation_de = documentation_de

    def compose(self) -> ComposeResult:
        default_text = self.record.default_value or "-"
        reader_text = self.record.reader or "-"
        unused_text = "yes" if self.record.unused else "no"
        value_text = "" if self.record.value == "not defined" else self.record.value
        with ScrollableContainer(id="property-details-panel"):
            yield Static(f"Property Details: {self.record.name}", id="property-details-title")
            yield Static(
                f"Reader: {reader_text}\nDefault: {default_text}\nUnused: {unused_text}",
                id="property-meta",
            )
            yield Static("Value")
            yield Input(value=value_text, placeholder="property value", id="property-value-input")
            yield Static("Documentation (EN)", id="property-doc-en-label")
            yield TextArea(
                self.documentation_en,
                id="property-documentation-en-input",
                soft_wrap=True,
                tab_behavior="focus",
            )
            yield Static("Documentation (DE)", id="property-doc-de-label")
            yield TextArea(
                self.documentation_de,
                id="property-documentation-de-input",
                soft_wrap=True,
                tab_behavior="focus",
            )
            yield Static("Ctrl+S: save  |  Tab/Shift+Tab: switch field  |  Esc/Ctrl+G: cancel")

    def on_mount(self) -> None:
        self.query_one("#property-value-input", Input).focus()

    def action_next_field(self) -> None:
        self._cycle_focus(direction=1)

    def action_previous_field(self) -> None:
        self._cycle_focus(direction=-1)

    def _cycle_focus(self, direction: int) -> None:
        fields = [
            self.query_one("#property-value-input", Input),
            self.query_one("#property-documentation-en-input", TextArea),
            self.query_one("#property-documentation-de-input", TextArea),
        ]
        focused = self.focused
        idx = fields.index(focused) if focused in fields else 0
        fields[(idx + direction) % len(fields)].focus()

    def action_save(self) -> None:
        value = self.query_one("#property-value-input", Input).value
        documentation_en = self.query_one("#property-documentation-en-input", TextArea).text
        documentation_de = self.query_one("#property-documentation-de-input", TextArea).text
        self.dismiss((value, documentation_en, documentation_de))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ObjectSelectionScreen(ModalScreen[ObjectSelectionRecord | None]):
    CSS = """
    ObjectSelectionScreen {
        background: #0f1419 85%;
    }
    #object-selection-table {
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 0 1;
    }
    """
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
    Screen {
        background: #11161c;
        color: #ffffff;
    }

    Static {
        color: #ffffff;
    }

    Header {
        background: $primary;
        color: $background;
        text-style: bold;
    }

    TabbedContent {
        background: #11161c;
        color: #ffffff;
    }

    TabPane {
        padding: 0;
        background: #11161c;
        color: #ffffff;
    }

    Tabs {
        background: #0f1419;
        color: #ffffff;
    }

    Tabs Tab {
        color: #dfe7ef;
        background: #1a232c;
    }

    Tabs Tab.-active {
        background: $primary;
        color: #000000;
        text-style: bold;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $foreground;
        padding: 0 1;
    }
    #dashboard-grid {
        grid-size: 2;
        grid-columns: 3fr 2fr;
        grid-gutter: 1 2;
        padding: 1;
        height: 1fr;
    }

    .dashboard-panel {
        border: round $primary;
        background: #0f1419;
        padding: 0 1;
    }

    .dashboard-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }

    #dashboard-metrics,
    #dashboard-problems {
        color: #ffffff;
    }

    DataTable {
        color: #ffffff;
        background: #11161c;
        border: round $primary;
    }

    #properties-panel {
        layout: vertical;
        padding: 1;
    }

    #properties-toolbar {
        height: auto;
        margin-bottom: 1;
    }

    #properties-mode-select {
        width: 24;
        margin-right: 1;
    }

    #property-name-filter,
    #property-value-filter {
        width: 1fr;
        margin-right: 1;
    }

    Tree {
        color: #ffffff;
        background: #11161c;
        border: round $primary;
    }

    Input {
        background: #11161c;
        color: #ffffff;
        border: tall $primary;
    }
    """
    BINDINGS = [
        Binding("r", "refresh_data", "Refresh"),
        Binding("ctrl+p", "command_palette", "Command Palette", priority=True),
        Binding("ctrl+shift+p", "command_palette", "Command Palette", priority=True),
        Binding("f1", "command_palette", "Command Palette", priority=True),
        Binding("slash", "focus_primary_filter", "Focus Filter"),
        Binding("x", "execute_primary_action", "Execute Action"),
        Binding("shift+x", "execute_secondary_action", "Execute Secondary Action"),
        Binding("X", "execute_secondary_action", "Execute Secondary Action"),
        Binding("ctrl+x", "execute_secondary_action", "Execute Secondary Action"),
        Binding("n", "workspace_create", "Create Workspace"),
        Binding("c", "workspace_clear", "Clear Workspace"),
        Binding("delete", "workspace_remove", "Remove Workspace"),
        Binding("u", "property_reset", "Reset Property"),
        Binding("d", "show_dependency_tree", "Dependency Tree"),
        Binding("i", "show_selected_details", "Details"),
        Binding("o", "show_object_dependencies", "Object Dependencies"),
        Binding("?", "show_keybindings", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, service: XynaService) -> None:
        super().__init__()
        self.service = service
        self._workspace_records: list[WorkspaceRecord] = []
        self._application_records: list[ApplicationRecord] = []
        self._dependency_records: list[DependencyRecord] = []
        self._property_records: list[PropertyRecord] = []
        self._filtered_property_records: list[PropertyRecord] = []
        self._property_list_mode = "verbose"

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                with Grid(id="dashboard-grid"):
                    with Vertical(classes="dashboard-panel"):
                        yield Static("System Health", classes="dashboard-title")
                        yield Static(id="dashboard-metrics")
                    with Vertical(classes="dashboard-panel"):
                        yield Static("Problem Radar", classes="dashboard-title")
                        yield Static(id="dashboard-problems")
            with TabPane("Workspaces", id="workspaces"):
                yield DataTable(id="workspaces-table")
            with TabPane("Applications", id="applications"):
                yield DataTable(id="applications-table")
            with TabPane("Properties", id="properties"):
                with Vertical(id="properties-panel"):
                    with Horizontal(id="properties-toolbar"):
                        yield Select(
                            [("List", "basic"), ("Values (-v)", "verbose"), ("All (-vv)", "extraverbose")],
                            value="verbose",
                            allow_blank=False,
                            id="properties-mode-select",
                        )
                        yield Input(placeholder="Filter by property name", id="property-name-filter")
                        yield Input(placeholder="Filter by property value", id="property-value-filter")
                    yield DataTable(id="properties-table")
            with TabPane("Dependencies", id="dependencies"):
                yield Tree("Runtime Context Dependencies", id="dependencies-tree")
            with TabPane("Triggers", id="triggers"):
                yield DataTable(id="triggers-table")
            with TabPane("Filters", id="filters"):
                yield DataTable(id="filters-table")
        yield Static(id="status-bar")

    def on_mount(self) -> None:
        self.register_theme(_XYNA_THEME)
        self.theme = "xyna"
        self.action_refresh_data()
        self._update_status_bar()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._update_status_bar(active_tab=event.tabbed_content.active)

    def _update_status_bar(self, active_tab: str | None = None) -> None:
        tab = active_tab or self.query_one(TabbedContent).active
        global_actions = "r Refresh | q Quit"

        tab_actions = {
            "workspaces": "x Refresh | X Refresh and Deploy | n Create | c Clear | Del Remove | d Dependency Tree | i Details | o Object Dependencies",
            "applications": "x Start/Stop Application | d Dependency Tree | i Details | o Object Dependencies",
            "properties": "i Details/Edit | u Reset | / Focus Name Filter",
            "dependencies": "Navigate tree with arrows",
            "dashboard": "",
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
        self._refresh_properties_data()
        self._dependency_records = self.service.dependencies()
        self._fill_dependency_tree()

        trigger_records = self.service.triggers()
        self._fill_table(
            "#triggers-table",
            ["trigger", "runtime_context", "status", "instances"],
            trigger_records,
        )
        filter_records = self.service.filters()
        self._fill_table(
            "#filters-table",
            ["filter_name", "runtime_context", "status", "instances"],
            filter_records,
        )

        self._render_dashboard_summary(
            dashboard,
            self._workspace_records,
            self._application_records,
            trigger_records,
            filter_records,
        )

    def _refresh_properties_data(self) -> None:
        self._property_records = self.service.properties(mode=self._property_list_mode)
        self._render_properties_table()

    def _render_properties_table(self) -> None:
        name_filter = self.query_one("#property-name-filter", Input).value.strip().lower()
        value_filter = self.query_one("#property-value-filter", Input).value.strip().lower()
        self._filtered_property_records = [
            record
            for record in self._property_records
            if (not name_filter or name_filter in record.name.lower())
            and (not value_filter or value_filter in record.value.lower())
        ]

        columns = ["name", "value", "default_value", "reader", "unused"]
        self._fill_table("#properties-table", columns, self._filtered_property_records)

    def _render_dashboard_summary(
        self,
        dashboard,
        workspaces: list[WorkspaceRecord],
        applications: list[ApplicationRecord],
        triggers,
        filters,
    ) -> None:
        host_mem_percent = self._memory_used_percent(dashboard.host_memory_free_kb, dashboard.host_memory_total_kb)
        jvm_heap_percent = self._memory_used_percent(
            free_value=None,
            total_value=dashboard.jvm_heap_current_kb,
            used_value=dashboard.jvm_heap_used_kb,
        )

        cpu_text = "n/a"
        cpu_bar = self._ascii_meter(None)
        if dashboard.cpu_usage_percent is not None:
            cpu_text = f"{dashboard.cpu_usage_percent:.1f}%"
            cpu_bar = self._ascii_meter(dashboard.cpu_usage_percent)

        host_mem_text = "n/a"
        host_mem_bar = self._ascii_meter(None)
        if host_mem_percent is not None and dashboard.host_memory_total_kb is not None:
            host_used = dashboard.host_memory_total_kb - (dashboard.host_memory_free_kb or 0)
            host_mem_text = f"{host_used:,}/{dashboard.host_memory_total_kb:,} kB ({host_mem_percent:.1f}%)"
            host_mem_bar = self._ascii_meter(host_mem_percent)

        jvm_heap_text = "n/a"
        jvm_heap_bar = self._ascii_meter(None)
        if (
            jvm_heap_percent is not None
            and dashboard.jvm_heap_used_kb is not None
            and dashboard.jvm_heap_current_kb is not None
            and dashboard.jvm_heap_max_kb is not None
        ):
            jvm_heap_text = (
                f"{dashboard.jvm_heap_used_kb:,}/{dashboard.jvm_heap_current_kb:,} kB "
                f"({jvm_heap_percent:.1f}%), max {dashboard.jvm_heap_max_kb:,} kB"
            )
            jvm_heap_bar = self._ascii_meter(jvm_heap_percent)

        metrics_lines = [
            f"[bold]Factory state:[/bold] {dashboard.factory_state}",
            f"[bold]Uptime:[/bold] {dashboard.uptime}",
            f"[bold]Server version:[/bold] {dashboard.server_version}",
            f"[bold]XMOM version:[/bold] {dashboard.xmom_version}",
            f"[bold]Operating system:[/bold] {dashboard.os_info}",
            "",
            "[bold #FABB00]CPU usage[/bold #FABB00]",
            f"  {cpu_bar} {cpu_text}",
            "[bold #FABB00]Host memory used[/bold #FABB00]",
            f"  {host_mem_bar} {host_mem_text}",
            "[bold #FABB00]Java heap used[/bold #FABB00]",
            f"  {jvm_heap_bar} {jvm_heap_text}",
        ]
        self.query_one("#dashboard-metrics", Static).update("\n".join(metrics_lines))

        bad_workspaces = [
            ws for ws in workspaces if ws.problems > 0 or self._is_problem_status(ws.status)
        ]
        bad_applications = [app for app in applications if self._is_problem_status(app.status)]
        bad_triggers = [tr for tr in triggers if self._is_problem_status(tr.status)]
        bad_filters = [fl for fl in filters if self._is_problem_status(fl.status)]

        problem_lines = [
            "[bold #FABB00]Problematic items[/bold #FABB00]",
            self._format_problem_block(
                "Workspaces",
                [f"{ws.name} ({ws.status}, problems={ws.problems})" for ws in bad_workspaces],
            ),
            self._format_problem_block(
                "Applications",
                [f"{app.name} {app.version} ({app.status})" for app in bad_applications],
            ),
            self._format_problem_block(
                "Triggers",
                [f"{tr.trigger} ({tr.status})" for tr in bad_triggers],
            ),
            self._format_problem_block(
                "Filters",
                [f"{fl.filter_name} ({fl.status})" for fl in bad_filters],
            ),
        ]
        self.query_one("#dashboard-problems", Static).update("\n\n".join(problem_lines))

    def _ascii_meter(self, percent: float | None, width: int = 24) -> str:
        if percent is None:
            return "[" + (" " * width) + "]"
        clamped = max(0.0, min(100.0, percent))
        filled = int(round((clamped / 100.0) * width))
        return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"

    def _memory_used_percent(
        self,
        free_value: int | None,
        total_value: int | None,
        used_value: int | None = None,
    ) -> float | None:
        if total_value is None or total_value <= 0:
            return None
        used = used_value
        if used is None:
            if free_value is None:
                return None
            used = total_value - free_value
        return max(0.0, min(100.0, (used / total_value) * 100.0))

    def _is_problem_status(self, status: str) -> bool:
        text = status.strip().upper()
        if not text:
            return False
        if text in {"RUNNING", "DEPLOYED", "UP_AND_RUNNING", "OK", "ACTIVE"}:
            return False
        return any(token in text for token in ("WARN", "INVALID", "ERROR", "FAIL", "PROBLEM"))

    def _format_problem_block(self, title: str, entries: list[str], max_items: int = 8) -> str:
        if not entries:
            return f"[bold]{title}[/bold]: none"
        clipped = entries[:max_items]
        lines = [f"[bold]{title}[/bold] ({len(entries)}):"]
        lines.extend(f"  - {entry}" for entry in clipped)
        if len(entries) > max_items:
            lines.append(f"  - ... and {len(entries) - max_items} more")
        return "\n".join(lines)

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

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in {"property-name-filter", "property-value-filter"}:
            self._render_properties_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "properties-mode-select":
            self._property_list_mode = str(event.value)
            self._refresh_properties_data()

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

            if tabbed.active == "properties":
                prop = self._selected_property_record()
                if not prop:
                    self.notify("No property selected", severity="warning")
                    return
                details = self.service.property_details(prop.name, fallback=prop)
                doc_en, doc_de = self.service.split_property_documentation(details.documentation)
                self.push_screen(
                    PropertyDetailsScreen(details, documentation_en=doc_en, documentation_de=doc_de),
                    lambda result: self._on_property_details_saved(details, result),
                )
                return
        except Exception as exc:
            self.notify(f"Could not load details: {exc}", severity="error")
            return

        self.notify("Open Workspaces, Applications, or Properties to view details", severity="information")

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

    def action_focus_primary_filter(self) -> None:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active == "properties":
            self.query_one("#property-name-filter", Input).focus()
            return
        self.notify("Filter shortcut is available on the Properties tab", severity="information")

    def action_show_keybindings(self) -> None:
        self.push_screen(KeybindingsScreen())

    async def action_execute_primary_action(self) -> None:
        tabbed = self.query_one(TabbedContent)

        if tabbed.active == "workspaces":
            await self._refresh_selected_workspace(with_dependencies=False)
            return

        if tabbed.active == "applications":
            await self._toggle_selected_application()
            return

        self.notify("Primary action is available on Workspaces/Applications", severity="information")

    async def action_execute_secondary_action(self) -> None:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active == "workspaces":
            await self._refresh_selected_workspace(with_dependencies=True)
            return
        self.notify("Secondary action is available on Workspaces tab", severity="information")

    def action_workspace_create(self) -> None:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active != "workspaces":
            self.notify("Create workspace is available on Workspaces tab", severity="information")
            return
        self.push_screen(WorkspaceNameScreen(), self._on_workspace_create_name)

    def action_workspace_clear(self) -> None:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active != "workspaces":
            self.notify("Clear workspace is available on Workspaces tab", severity="information")
            return
        ws = self._selected_workspace_record()
        if ws is None:
            self.notify("No workspace selected", severity="warning")
            return
        self.push_screen(
            ConfirmScreen(
                "Clear workspace",
                f"Clear workspace '{ws.name}'?\nThis removes triggers, filters and XMOM objects.",
            ),
            lambda confirmed: self._on_workspace_clear_confirmation(ws, confirmed),
        )

    def _on_workspace_create_name(self, name: str | None) -> None:
        if not name:
            return
        asyncio.create_task(self._run_workspace_create(name))

    async def _run_workspace_create(self, name: str) -> None:
        modal = BusyCommandScreen(f"createworkspace {name}")
        self.push_screen(modal)
        try:
            await asyncio.to_thread(self.service.create_workspace, name)
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Create workspace failed: {exc}")

    def _on_workspace_clear_confirmation(self, ws: WorkspaceRecord, confirmed: bool) -> None:
        if not confirmed:
            return
        asyncio.create_task(self._run_workspace_clear(ws))

    async def _run_workspace_clear(self, ws: WorkspaceRecord) -> None:
        modal = BusyCommandScreen(f"clearworkspace {ws.name}")
        self.push_screen(modal)
        try:
            await asyncio.to_thread(self.service.clear_workspace, ws.name)
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Clear workspace failed: {exc}")

    def action_workspace_remove(self) -> None:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active != "workspaces":
            self.notify("Remove workspace is available on Workspaces tab", severity="information")
            return
        ws = self._selected_workspace_record()
        if ws is None:
            self.notify("No workspace selected", severity="warning")
            return
        self.push_screen(
            ConfirmScreen(
                "Remove workspace",
                f"Remove workspace '{ws.name}'?\nThis operation cannot be undone.",
            ),
            lambda confirmed: self._on_workspace_remove_confirmation(ws, confirmed),
        )

    def _on_workspace_remove_confirmation(self, ws: WorkspaceRecord, confirmed: bool) -> None:
        if not confirmed:
            return
        asyncio.create_task(self._run_workspace_remove(ws))

    async def _run_workspace_remove(self, ws: WorkspaceRecord) -> None:
        modal = BusyCommandScreen(f"removeworkspace {ws.name}")
        self.push_screen(modal)
        try:
            await asyncio.to_thread(self.service.remove_workspace, ws.name)
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Remove workspace failed: {exc}")

    async def _refresh_selected_workspace(self, with_dependencies: bool) -> None:
        ws = self._selected_workspace_record()
        if ws is None:
            self.notify("No workspace selected", severity="warning")
            return

        title = f"Refresh workspace {ws.name}"
        if with_dependencies:
            title = f"Refresh and deploy workspace {ws.name}"
        modal = StreamingCommandScreen(title)
        self.push_screen(modal)
        try:
            await asyncio.to_thread(
                self.service.refresh_workspace_stream,
                ws.name,
                with_dependencies,
                modal.enqueue_chunk,
            )
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Workspace refresh failed: {exc}")

    async def _toggle_selected_application(self) -> None:
        if not self._application_records:
            self.notify("No application selected", severity="warning")
            return
        table = self.query_one("#applications-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._application_records) - 1)
        app = self._application_records[idx]

        is_running = app.status.strip().upper() == "RUNNING"
        action_name = "stopapplication" if is_running else "startapplication"
        modal = BusyCommandScreen(f"{action_name} {app.name} {app.version}")
        self.push_screen(modal)
        try:
            if is_running:
                await asyncio.to_thread(self.service.stop_application, app.name, app.version)
            else:
                await asyncio.to_thread(self.service.start_application, app.name, app.version)
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Application action failed: {exc}")

    def _selected_workspace_record(self) -> WorkspaceRecord | None:
        if not self._workspace_records:
            return None
        table = self.query_one("#workspaces-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._workspace_records) - 1)
        return self._workspace_records[idx]

    def _selected_property_record(self) -> PropertyRecord | None:
        if not self._filtered_property_records:
            return None
        table = self.query_one("#properties-table", DataTable)
        idx = table.cursor_row if table.cursor_row >= 0 else 0
        idx = min(idx, len(self._filtered_property_records) - 1)
        return self._filtered_property_records[idx]

    def _on_property_details_saved(
        self,
        original: PropertyRecord,
        result: tuple[str, str, str] | None,
    ) -> None:
        if result is None:
            return
        value, documentation_en, documentation_de = result
        asyncio.create_task(self._run_property_update(original, value, documentation_en, documentation_de))

    async def _run_property_update(
        self,
        original: PropertyRecord,
        value: str,
        documentation_en: str,
        documentation_de: str,
    ) -> None:
        modal = BusyCommandScreen(f"set property {original.name}")
        self.push_screen(modal)
        try:
            original_value = "" if original.value == "not defined" else original.value
            normalized_new_doc = self.service.normalize_property_documentation(
                self.service.compose_property_documentation(documentation_en, documentation_de)
            )
            normalized_original_doc = self.service.normalize_property_documentation(original.documentation)
            if value != original_value:
                await asyncio.to_thread(self.service.set_property, original.name, value)
            if normalized_new_doc != normalized_original_doc:
                await asyncio.to_thread(
                    self.service.set_property_documentation,
                    original.name,
                    self.service.normalize_property_documentation(documentation_en),
                    "EN",
                )
                await asyncio.to_thread(
                    self.service.set_property_documentation,
                    original.name,
                    self.service.normalize_property_documentation(documentation_de),
                    "DE",
                )
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Property update failed: {exc}")

    def action_property_reset(self) -> None:
        tabbed = self.query_one(TabbedContent)
        if tabbed.active != "properties":
            self.notify("Reset property is available on the Properties tab", severity="information")
            return
        prop = self._selected_property_record()
        if prop is None:
            self.notify("No property selected", severity="warning")
            return
        asyncio.create_task(self._run_property_reset(prop.name))

    async def _run_property_reset(self, property_name: str) -> None:
        modal = BusyCommandScreen(f"reset property {property_name}")
        self.push_screen(modal)
        try:
            details = await asyncio.to_thread(self.service.property_details, property_name)
            if not details.default_value:
                modal.mark_done(False, "Reset failed: property has no default value")
                return
            await asyncio.to_thread(self.service.reset_property, property_name)
            self.action_refresh_data()
            modal.dismiss()
        except Exception as exc:
            modal.mark_done(False, f"Reset property failed: {exc}")

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
    should_mock = use_mock if use_mock is not None else os.getenv("XYNA_TUI_USE_MOCK", "0") != "0"
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
    build_app(use_mock=False).run()


if __name__ == "__main__":
    run()
