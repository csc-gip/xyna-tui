from __future__ import annotations

import asyncio
import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import DataTable, Header, Input, Select, Static, TabbedContent, TabPane, Tree

from .dependency_tree import (
    application_context,
    build_adjacency,
    build_dependency_tree,
    workspace_context,
)
from .fixtures import repo_root_from_here
from .gateway import MockXynaGateway, TcpXynaGateway
from .models import (
    ApplicationRecord,
    DependencyRecord,
    ObjectSelectionRecord,
    PropertyRecord,
    WorkspaceRecord,
)
from .screens import (
    ApplicationDetailsScreen,
    BusyCommandScreen,
    ConfirmScreen,
    DependencyTreeScreen,
    KeybindingsScreen,
    ObjectDependenciesScreen,
    ObjectSelectionScreen,
    PropertyDetailsScreen,
    StreamingCommandScreen,
    WorkspaceDetailsScreen,
    WorkspaceNameScreen,
    _XYNA_THEME,
)
from .service import XynaService



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
