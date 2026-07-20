from __future__ import annotations

import os
from typing import Callable

from .gateway import XynaGateway
from .models import (
    ApplicationRecord,
    ApplicationDetailsRecord,
    ContentItemRecord,
    DashboardInfo,
    DependencyRecord,
    DeploymentItemRecord,
    FilterRecord,
    PropertyRecord,
    TriggerRecord,
    WorkspaceRecord,
    WorkspaceDetailsRecord,
    ObjectSelectionRecord,
)
from .parsers import (
    parse_applications_table,
    parse_application_details,
    parse_dashboard_info,
    parse_deployment_item,
    parse_filter_table,
    parse_listwfs_names,
    parse_listwfs_records,
    parse_named_name_lines,
    parse_properties_verbose,
    parse_printdependencies_tree_lines,
    parse_runtime_dependencies,
    parse_trigger_table,
    parse_workspaces_table,
    parse_workspace_details,
)


class XynaService:
    def __init__(self, gateway: XynaGateway) -> None:
        self.gateway = gateway
        self._deployment_state_cache: dict[tuple[str, str, str | None, str | None], str] = {}
        self._last_cpu_total: int | None = None
        self._last_cpu_idle: int | None = None

    def dashboard(self) -> DashboardInfo:
        dashboard = parse_dashboard_info(
            uptime_raw=self.gateway.execute("uptime"),
            listsysteminfo_raw=self.gateway.execute("listsysteminfo"),
            version_raw=self.gateway.execute("version"),
        )
        if dashboard.cpu_usage_percent is None:
            dashboard.cpu_usage_percent = self._sample_cpu_usage_percent()
        return dashboard

    def _sample_cpu_usage_percent(self) -> float | None:
        try:
            with open("/proc/stat", "r", encoding="utf-8") as stat_file:
                first = stat_file.readline().strip()
            if not first.startswith("cpu "):
                return self._load_average_cpu_percent()

            parts = first.split()[1:]
            values = [int(p) for p in parts]
            if len(values) < 4:
                return self._load_average_cpu_percent()

            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)

            if self._last_cpu_total is None or self._last_cpu_idle is None:
                self._last_cpu_total = total
                self._last_cpu_idle = idle
                return self._load_average_cpu_percent()

            total_delta = total - self._last_cpu_total
            idle_delta = idle - self._last_cpu_idle
            self._last_cpu_total = total
            self._last_cpu_idle = idle
            if total_delta <= 0:
                return self._load_average_cpu_percent()

            used_fraction = (total_delta - idle_delta) / total_delta
            return max(0.0, min(100.0, used_fraction * 100.0))
        except Exception:
            return self._load_average_cpu_percent()

    def _load_average_cpu_percent(self) -> float | None:
        try:
            one_min_load = os.getloadavg()[0]
            cpu_count = os.cpu_count() or 1
            return max(0.0, min(100.0, (one_min_load / cpu_count) * 100.0))
        except Exception:
            return None

    def workspaces(self) -> list[WorkspaceRecord]:
        return parse_workspaces_table(self.gateway.execute("listworkspaces -t"))

    def applications(self) -> list[ApplicationRecord]:
        return parse_applications_table(self.gateway.execute("listapplications -t"))

    def properties(self) -> list[PropertyRecord]:
        return parse_properties_verbose(self.gateway.execute("listproperties -v"))

    def dependencies(self) -> list[DependencyRecord]:
        return parse_runtime_dependencies(self.gateway.execute("listruntimecontextdependencies"))

    def deployment_item(
        self,
        object_name: str = "csc.test.TestKeyInfo",
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
        verbose: bool = False,
    ) -> DeploymentItemRecord:
        cmd = "showdeploymentitemdetails"
        if application_name:
            cmd += f' -applicationName "{application_name.replace("\"", "\\\"")}"'
        if version and version != "-":
            cmd += f' -versionName "{version.replace("\"", "\\\"")}"'
        if workspace_name:
            cmd += f' -workspaceName "{workspace_name.replace("\"", "\\\"")}"'
        if verbose:
            cmd += " -v"
        cmd += f' -objectName "{object_name.replace("\"", "\\\"")}"'
        return parse_deployment_item(self.gateway.execute(cmd))

    def triggers(self) -> list[TriggerRecord]:
        return parse_trigger_table(self.gateway.execute("listtriggers -s"))

    def filters(self) -> list[FilterRecord]:
        return parse_filter_table(self.gateway.execute("listfilters -c"))

    def workspace_details(self, workspace_name: str) -> WorkspaceDetailsRecord:
        quoted = workspace_name.replace('"', '\\"')
        raw = self.gateway.execute(f'listworkspacedetails -workspaceName "{quoted}"')
        details = parse_workspace_details(raw)
        details.content_by_type = self.content_by_type(workspace_name=workspace_name)
        return details

    def application_details(self, application_name: str, version: str | None = None) -> ApplicationDetailsRecord:
        quoted_name = application_name.replace('"', '\\"')
        cmd = f'listapplicationdetails -applicationName "{quoted_name}"'
        if version and version != "-":
            quoted_version = version.replace('"', '\\"')
            cmd += f' -versionName "{quoted_version}"'
        raw = self.gateway.execute(cmd)
        details = parse_application_details(raw)
        details.dependencies = self._runtime_dependencies_for_application(application_name, version)
        # section_items are already populated by parse_application_details
        return details

    def workflows(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> list[str]:
        cmd = "listwfs"
        if workspace_name:
            cmd += f' -workspaceName "{workspace_name.replace("\"", "\\\"")}"'
        if application_name:
            cmd += f' -applicationName "{application_name.replace("\"", "\\\"")}"'
        if version and version != "-":
            cmd += f' -versionName "{version.replace("\"", "\\\"")}"'
        raw = self.gateway.execute(cmd)
        return parse_listwfs_names(raw)

    def workflow_records(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> list[ContentItemRecord]:
        cmd = "listwfs"
        if workspace_name:
            cmd += f' -workspaceName "{workspace_name.replace("\"", "\\\"")}"'
        if application_name:
            cmd += f' -applicationName "{application_name.replace("\"", "\\\"")}"'
        if version and version != "-":
            cmd += f' -versionName "{version.replace("\"", "\\\"")}"'
        raw = self.gateway.execute(cmd)
        return parse_listwfs_records(raw)

    def datatypes(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> list[str]:
        cmd = "listdoms"
        if workspace_name:
            cmd += f' -workspaceName "{workspace_name.replace("\"", "\\\"")}"'
        if application_name:
            cmd += f' -applicationName "{application_name.replace("\"", "\\\"")}"'
        if version and version != "-":
            cmd += f' -versionName "{version.replace("\"", "\\\"")}"'
        raw = self.gateway.execute(cmd)
        return parse_named_name_lines(raw)

    def exceptions(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> list[str]:
        cmd = "listexceptions"
        if workspace_name:
            cmd += f' -workspaceName "{workspace_name.replace("\"", "\\\"")}"'
        if application_name:
            cmd += f' -applicationName "{application_name.replace("\"", "\\\"")}"'
        if version and version != "-":
            cmd += f' -versionName "{version.replace("\"", "\\\"")}"'
        raw = self.gateway.execute(cmd)
        return parse_named_name_lines(raw)

    def content_by_type(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> dict[str, list[str]]:
        # If we have an application context, use listapplicationdetails which already includes content
        if application_name:
            quoted_name = application_name.replace('"', '\\"')
            cmd = f'listapplicationdetails -applicationName "{quoted_name}"'
            if version and version != "-":
                quoted_version = version.replace('"', '\\"')
                cmd += f' -versionName "{quoted_version}"'
            raw = self.gateway.execute(cmd)
            details = parse_application_details(raw)
            result: dict[str, list[str]] = dict(details.section_items)
            
            # Add trigger and filter names if we have a full version context
            app_ctx = None
            if version and version != "-":
                app_ctx = f"Application '{application_name}', Version '{version}'"
            
            if app_ctx:
                trigger_names = sorted(
                    {t.trigger for t in self.triggers() if t.runtime_context == app_ctx}
                )
                filter_names = sorted(
                    {f.filter_name for f in self.filters() if f.runtime_context == app_ctx}
                )
                result["TRIGGER"] = trigger_names
                result["FILTER"] = filter_names
            
            return result
        
        # For workspace scope, use individual list commands since listworkspacedetails
        # doesn't include the full content list
        workflows = self.workflows(workspace_name=workspace_name)
        datatypes = self.datatypes(workspace_name=workspace_name)
        exceptions = self.exceptions(workspace_name=workspace_name)

        return {
            "WORKFLOW": workflows,
            "DATATYPE": datatypes,
            "EXCEPTION": exceptions,
            "TRIGGER": [],
            "FILTER": [],
        }

    def content_items(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> list[ContentItemRecord]:
        workflow_records = self.workflow_records(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        )
        records: list[ContentItemRecord] = list(workflow_records)

        for name in self.datatypes(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        ):
            records.append(
                ContentItemRecord(
                    object_type="DATATYPE",
                    object_name=name,
                    status=self._deployment_state_for_item(
                        object_name=name,
                        workspace_name=workspace_name,
                        application_name=application_name,
                        version=version,
                    ),
                )
            )

        for name in self.exceptions(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        ):
            records.append(
                ContentItemRecord(
                    object_type="EXCEPTION",
                    object_name=name,
                    status=self._deployment_state_for_item(
                        object_name=name,
                        workspace_name=workspace_name,
                        application_name=application_name,
                        version=version,
                    ),
                )
            )

        app_ctx = None
        if application_name and version and version != "-":
            app_ctx = f"Application '{application_name}', Version '{version}'"

        if app_ctx:
            for trigger in self.triggers():
                if trigger.runtime_context == app_ctx:
                    records.append(
                        ContentItemRecord(
                            object_type="TRIGGER",
                            object_name=trigger.trigger,
                            status=trigger.status,
                        )
                    )
            for item_filter in self.filters():
                if item_filter.runtime_context == app_ctx:
                    records.append(
                        ContentItemRecord(
                            object_type="FILTER",
                            object_name=item_filter.filter_name,
                            status=item_filter.status,
                        )
                    )
        return records

    def _deployment_state_for_item(
        self,
        object_name: str,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> str:
        cache_key = (object_name, workspace_name or "", application_name, version)
        if cache_key in self._deployment_state_cache:
            return self._deployment_state_cache[cache_key]

        try:
            item = self.deployment_item(
                object_name=object_name,
                workspace_name=workspace_name,
                application_name=application_name,
                version=version,
            )
            status = item.state or "UNKNOWN"
        except Exception:
            status = "UNKNOWN"

        self._deployment_state_cache[cache_key] = status
        return status

    def objects_for_selection(
        self,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
    ) -> list[ObjectSelectionRecord]:
        content = self.content_by_type(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        )
        records: list[ObjectSelectionRecord] = []
        type_map = {
            "WORKFLOW": "Workflow",
            "DATATYPE": "Datatype",
            "EXCEPTION": "XynaException",
            "TRIGGER": "Trigger",
            "FILTER": "Filter",
        }
        for object_type, names in content.items():
            for name in names:
                records.append(
                    ObjectSelectionRecord(
                        object_type=type_map.get(object_type, object_type),
                        object_name=name,
                    )
                )
        return records

    def _runtime_dependencies_for_application(
        self,
        application_name: str,
        version: str | None,
    ) -> list[str]:
        if not version or version == "-":
            return []
        owner = f"Application '{application_name}', Version '{version}'"
        deps = [d.requirement for d in self.dependencies() if d.owner == owner]
        return deps

    def object_dependencies(
        self,
        object_name: str,
        object_type: str,
        workspace_name: str | None = None,
        application_name: str | None = None,
        version: str | None = None,
        recurse: bool = True,
    ) -> list[tuple[int, str]]:
        cmd = "printdependencies"
        if application_name:
            cmd += f' -applicationName "{application_name.replace("\"", "\\\"")}"'
        if version and version != "-":
            cmd += f' -versionName "{version.replace("\"", "\\\"")}"'
        if workspace_name:
            cmd += f' -workspaceName "{workspace_name.replace("\"", "\\\"")}"'
        cmd += f' -object "{object_name.replace("\"", "\\\"")}"'
        cmd += f' -objectType {object_type}'
        if recurse:
            cmd += " -r"
        raw = self.gateway.execute(cmd)
        return parse_printdependencies_tree_lines(raw)

    def refresh_workspace(self, workspace_name: str, with_dependencies: bool = False) -> str:
        cmd = self._refresh_workspace_command(workspace_name, with_dependencies)
        return self.gateway.execute(cmd)

    def refresh_workspace_stream(
        self,
        workspace_name: str,
        with_dependencies: bool,
        on_chunk: Callable[[str], None],
    ) -> str:
        cmd = self._refresh_workspace_command(workspace_name, with_dependencies)
        execute_stream = getattr(self.gateway, "execute_stream", None)
        if callable(execute_stream):
            return execute_stream(cmd, on_chunk)
        output = self.gateway.execute(cmd)
        if output:
            on_chunk(output)
        return output

    def _refresh_workspace_command(self, workspace_name: str, with_dependencies: bool) -> str:
        quoted = workspace_name.replace('"', '\\"')
        cmd = f'refreshworkspace -workspace "{quoted}"'
        if with_dependencies:
            cmd += " -d"
        return cmd

    def start_application(self, application_name: str, version: str) -> str:
        quoted_name = application_name.replace('"', '\\"')
        quoted_version = version.replace('"', '\\"')
        cmd = (
            f'startapplication -applicationName "{quoted_name}" '
            f'-versionName "{quoted_version}"'
        )
        return self.gateway.execute(cmd)

    def stop_application(self, application_name: str, version: str) -> str:
        quoted_name = application_name.replace('"', '\\"')
        quoted_version = version.replace('"', '\\"')
        cmd = (
            f'stopapplication -applicationName "{quoted_name}" '
            f'-versionName "{quoted_version}"'
        )
        return self.gateway.execute(cmd)

    def create_workspace(self, workspace_name: str, revision: str | None = None) -> str:
        quoted = workspace_name.replace('"', '\\"')
        cmd = f'createworkspace -workspaceName "{quoted}"'
        if revision:
            cmd += f' -revision "{revision.replace("\"", "\\\"")}"'
        return self.gateway.execute(cmd)

    def clear_workspace(self, workspace_name: str, force: bool = True) -> str:
        quoted = workspace_name.replace('"', '\\"')
        cmd = f'clearworkspace -workspaceName "{quoted}"'
        if force:
            cmd += " -f"
        return self.gateway.execute(cmd)

    def remove_workspace(
        self,
        workspace_name: str,
        force: bool = True,
        cleanup_xmls: bool = True,
    ) -> str:
        quoted = workspace_name.replace('"', '\\"')
        cmd = f'removeworkspace -workspaceName "{quoted}"'
        if force:
            cmd += " -f"
        if cleanup_xmls:
            cmd += " -c"
        return self.gateway.execute(cmd)
