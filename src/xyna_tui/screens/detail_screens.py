from __future__ import annotations

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static, Tree

from ..dependency_tree import application_context, build_dependency_tree, workspace_context
from ..models import (
    ApplicationDetailsRecord,
    ContentItemRecord,
    DependencyRecord,
    DeploymentItemRecord,
    WorkspaceDetailsRecord,
)
from ..service import XynaService

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

    def compose(self):
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
            event.data_table.move_cursor(row=event.data_table.cursor_row, column=event.data_table.cursor_column)
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

    def compose(self):
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
            event.data_table.move_cursor(row=event.data_table.cursor_row, column=event.data_table.cursor_column)
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
