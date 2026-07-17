from xyna_tui.gateway import MockXynaGateway
from xyna_tui.fixtures import repo_root_from_here
from xyna_tui.service import XynaService


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
