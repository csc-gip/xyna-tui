from xyna_tui.gateway import MockXynaGateway
from xyna_tui.fixtures import repo_root_from_here
from xyna_tui.service import XynaService


class _CaptureGateway:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def execute(self, command: str) -> str:
        self.commands.append(command)
        return "ok"


def _service() -> XynaService:
    return XynaService(MockXynaGateway.from_repo_root(repo_root_from_here()))


def test_workspace_details_contains_split_content_and_dependencies() -> None:
    service = _service()

    details = service.workspace_details("default workspace")

    assert details.requirements
    assert "WORKFLOW" in details.content_by_type
    assert "DATATYPE" in details.content_by_type
    assert "EXCEPTION" in details.content_by_type
    assert details.content_by_type["WORKFLOW"]


def test_application_details_contains_runtime_dependencies() -> None:
    service = _service()

    details = service.application_details("Base", "1.1.4")

    assert details.dependencies == []
    assert details.section_items.get("WORKFLOW")


def test_objects_for_selection_includes_mapped_types() -> None:
    service = _service()

    objects = service.objects_for_selection(application_name="Base", version="1.1.4")

    assert objects
    object_types = {obj.object_type for obj in objects}
    assert "Workflow" in object_types
    assert "Datatype" in object_types
    assert "XynaException" in object_types


def test_content_items_include_status_for_datatypes() -> None:
    service = _service()

    items = service.content_items(workspace_name="default workspace")

    datatype = next(item for item in items if item.object_type == "DATATYPE")
    assert datatype.status


def test_refresh_workspace_command_building() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)

    service.refresh_workspace('default workspace', with_dependencies=False)
    service.refresh_workspace('default workspace', with_dependencies=True)

    assert gateway.commands[0] == 'refreshworkspace -workspace "default workspace"'
    assert gateway.commands[1] == 'refreshworkspace -workspace "default workspace" -d'


def test_application_start_stop_command_building() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)

    service.start_application("Base", "1.1.4")
    service.stop_application("Base", "1.1.4")

    assert gateway.commands[0] == 'startapplication -applicationName "Base" -versionName "1.1.4"'
    assert gateway.commands[1] == 'stopapplication -applicationName "Base" -versionName "1.1.4"'


def test_refresh_workspace_stream_uses_fallback_execute() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)
    chunks: list[str] = []

    result = service.refresh_workspace_stream(
        "default workspace",
        with_dependencies=True,
        on_chunk=chunks.append,
    )

    assert result == "ok"
    assert chunks == ["ok"]
    assert gateway.commands[0] == 'refreshworkspace -workspace "default workspace" -d'


def test_workspace_create_clear_remove_command_building() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)

    service.create_workspace("new workspace")
    service.clear_workspace("new workspace")
    service.remove_workspace("new workspace")

    assert gateway.commands[0] == 'createworkspace -workspaceName "new workspace"'
    assert gateway.commands[1] == 'clearworkspace -workspaceName "new workspace" -f'
    assert gateway.commands[2] == 'removeworkspace -workspaceName "new workspace" -f -c'


def test_workspace_create_command_allows_names_with_spaces() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)

    service.create_workspace("team alpha workspace")

    assert gateway.commands[0] == 'createworkspace -workspaceName "team alpha workspace"'
