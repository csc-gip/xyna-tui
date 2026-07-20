from xyna_tui.gateway import MockXynaGateway
from xyna_tui.fixtures import repo_root_from_here
from xyna_tui.models import PropertyRecord
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


def test_property_list_mode_and_mutation_commands() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)

    service.properties(mode="basic")
    service.properties(mode="verbose")
    service.properties(mode="extraverbose", include_documentation=True)
    service.set_property("xyna.default.monitoringlevel", "10")
    service.reset_property("xyna.default.monitoringlevel")
    service.set_property_documentation("xyna.default.monitoringlevel", "Example doc")

    assert gateway.commands[0] == "listproperties"
    assert gateway.commands[1] == "listproperties -v"
    assert gateway.commands[2] == "listproperties -showdoc -vv"
    assert gateway.commands[3] == 'set -key "xyna.default.monitoringlevel" -value "10"'
    assert gateway.commands[4] == 'removeproperty -key "xyna.default.monitoringlevel"'
    assert gateway.commands[5] == (
        'setpropertydocumentation -key "xyna.default.monitoringlevel" '
        '-language "EN" -documentation "Example doc"'
    )


def test_property_details_prefers_get_command() -> None:
    gateway = _CaptureGateway()
    service = XynaService(gateway)

    fallback = PropertyRecord(
        name="xyna.default.monitoringlevel",
        value="20",
        default_value="5",
        reader="Reader",
        unused=False,
        documentation="",
    )

    service.property_details("xyna.default.monitoringlevel", fallback=fallback)

    assert gateway.commands[0] == 'get -key "xyna.default.monitoringlevel" -d -v -lang EN'
    assert gateway.commands[1] == 'get -key "xyna.default.monitoringlevel" -d -v -lang DE'


def test_property_details_strips_language_wrapper_from_get_payload() -> None:
    class _PropertyDetailsGateway:
        def __init__(self) -> None:
            self.commands: list[str] = []

        def execute(self, command: str) -> str:
            self.commands.append(command)
            if command.endswith("-lang EN"):
                return "Name: test.key Value: 'true' Documentation: EN: 'English doc'"
            if command.endswith("-lang DE"):
                return "Name: test.key Value: 'true' Documentation: DE: Deutscher Text"
            return ""

    gateway = _PropertyDetailsGateway()
    service = XynaService(gateway)
    fallback = PropertyRecord(
        name="test.key",
        value="true",
        default_value="-",
        reader="-",
        unused=False,
        documentation="",
    )

    details = service.property_details("test.key", fallback=fallback)
    en, de = service.split_property_documentation(details.documentation)

    assert en == "English doc"
    assert de == "Deutscher Text"


def test_property_documentation_updates_split_languages() -> None:
    service = XynaService(_CaptureGateway())

    updates = service.property_documentation_updates(
        "EN: English text\nDE: Deutscher Text\n"
    )

    assert updates == [("EN", "English text"), ("DE", "Deutscher Text")]


def test_normalize_property_documentation_trims_trailing_whitespace() -> None:
    service = XynaService(_CaptureGateway())

    normalized = service.normalize_property_documentation("EN: test   \nDE: wert\t\n\n")

    assert normalized == "EN: test\nDE: wert"


def test_split_property_documentation_by_language() -> None:
    service = XynaService(_CaptureGateway())

    en, de = service.split_property_documentation("EN: Hello\nEN: world\nDE: Hallo\nDE: Welt")

    assert en == "Hello\nworld"
    assert de == "Hallo\nWelt"


def test_split_property_documentation_removes_only_outer_wrapper_layer() -> None:
    service = XynaService(_CaptureGateway())

    en, de = service.split_property_documentation(
        "EN: ''This is a test documentation''\nDE: 'Das ist eine deutsche Doku'"
    )

    assert en == "'This is a test documentation'"
    assert de == "Das ist eine deutsche Doku"


def test_compose_property_documentation_by_language() -> None:
    service = XynaService(_CaptureGateway())

    combined = service.compose_property_documentation("Hello\nworld", "Hallo")

    assert combined == "EN: Hello\nEN: world\nDE: Hallo"
