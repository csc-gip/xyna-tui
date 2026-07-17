from __future__ import annotations

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

    def dashboard(self) -> DashboardInfo:
        return parse_dashboard_info(
            uptime_raw=self.gateway.execute("uptime"),
            listsysteminfo_raw=self.gateway.execute("listsysteminfo"),
            version_raw=self.gateway.execute("version"),
        )

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
        content = self.content_by_type(application_name=application_name, version=version)
        for obj_type, names in content.items():
            if not names:
                continue
            details.section_items[obj_type] = names
            details.sections[obj_type] = len(names)
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
        workflows = self.workflows(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        )
        datatypes = self.datatypes(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        )
        exceptions = self.exceptions(
            workspace_name=workspace_name,
            application_name=application_name,
            version=version,
        )

        app_ctx = None
        if application_name and version and version != "-":
            app_ctx = f"Application '{application_name}', Version '{version}'"

        trigger_names: list[str] = []
        filter_names: list[str] = []
        if app_ctx:
            trigger_names = sorted(
                {t.trigger for t in self.triggers() if t.runtime_context == app_ctx}
            )
            filter_names = sorted(
                {f.filter_name for f in self.filters() if f.runtime_context == app_ctx}
            )

        return {
            "WORKFLOW": workflows,
            "DATATYPE": datatypes,
            "EXCEPTION": exceptions,
            "TRIGGER": trigger_names,
            "FILTER": filter_names,
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
