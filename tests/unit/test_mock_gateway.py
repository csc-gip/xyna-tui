from __future__ import annotations

from xyna_tui.gateway import MockXynaGateway
from xyna_tui.fixtures import repo_root_from_here
from xyna_tui.service import XynaService


def test_mock_gateway_uses_example_outputs() -> None:
    gateway = MockXynaGateway.from_repo_root(repo_root_from_here())

    output = gateway.execute("listworkspaces -t")

    assert "default workspace" in output
    assert "rdcatalog_ws" in output


def test_service_reads_from_mock_gateway() -> None:
    gateway = MockXynaGateway.from_repo_root(repo_root_from_here())
    service = XynaService(gateway)

    assert len(service.workspaces()) == 2
    assert len(service.applications()) >= 20
    assert len(service.properties()) == 26
    assert len(service.dependencies()) > 0
    assert len(service.triggers()) == 1
    assert len(service.filters()) == 3

    ws_details = service.workspace_details("default workspace")
    assert ws_details.state == "OK"
    assert len(ws_details.requirements) == 4

    app_details = service.application_details("Base", "1.1.4")
    assert app_details.state == "STOPPED"
    assert app_details.sections["WORKFLOW"] > 0

    ws_wfs = service.workflows(workspace_name="default workspace")
    assert ws_wfs[0] == "csc.test.TestKeyInfo"

    app_wfs = service.workflows(application_name="Base", version="1.1.4")
    assert "xmcp.manualinteraction.ManualInteraction" in app_wfs

    ws_deps = service.object_dependencies(
        object_name="csc.test.TestKeyInfo",
        object_type="Workflow",
        workspace_name="default workspace",
    )
    assert ws_deps[0][1].startswith("WORKFLOW:")

    app_deps = service.object_dependencies(
        object_name="xmcp.manualinteraction.ManualInteraction",
        object_type="Workflow",
        application_name="Base",
        version="1.1.4",
    )
    assert len(app_deps) > 1
