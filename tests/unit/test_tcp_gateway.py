from __future__ import annotations

import pytest

from xyna_tui.gateway import TcpXynaGateway


def test_encode_call_without_args() -> None:
    gw = TcpXynaGateway()
    payload = gw._encode_call(["status"])
    assert payload == b"status\x1d\x1d\x04"


def test_encode_call_with_args() -> None:
    gw = TcpXynaGateway()
    payload = gw._encode_call(["set", "-key", "a", "-value", "b"])
    assert payload == b"set\x1d-key\x1ea\x1e-value\x1eb\x1e\x1d\x04"


def test_encode_call_with_spaced_argument() -> None:
    gw = TcpXynaGateway()
    payload = gw._encode_call(["createworkspace", "-workspaceName", "alpha beta"])
    assert payload == b"createworkspace\x1d-workspaceName\x1ealpha beta\x1e\x1d\x04"


def test_split_response_with_status() -> None:
    gw = TcpXynaGateway()
    body, status = gw._split_response("out line\nENDOFSTREAM_SUCCESS")
    assert body == "out line\n"
    assert status == "ENDOFSTREAM_SUCCESS"


def test_split_response_without_status() -> None:
    gw = TcpXynaGateway()
    body, status = gw._split_response("plain output")
    assert body == "plain output"
    assert status == ""


def test_execute_raises_for_empty_command() -> None:
    gw = TcpXynaGateway()
    with pytest.raises(ValueError):
        gw.execute("   ")


def test_execute_success_uses_send_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(self: TcpXynaGateway, payload: bytes) -> str:
        assert payload.startswith(b"status")
        return "Status: up\nENDOFSTREAM_SUCCESS"

    monkeypatch.setattr(TcpXynaGateway, "_send_payload", fake_send)
    gw = TcpXynaGateway()
    assert gw.execute("status") == "Status: up"


def test_execute_accepts_status_prefix_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(self: TcpXynaGateway, payload: bytes) -> str:
        assert payload.startswith(b"status")
        return "Status: up\nENDOFSTREAM_STATUS_UP_AND_RUNNING_SINCE_123"

    monkeypatch.setattr(TcpXynaGateway, "_send_payload", fake_send)
    gw = TcpXynaGateway()
    assert gw.execute("status") == "Status: up"


@pytest.mark.parametrize(
    "status",
    [
        "ENDOFSTREAM_UNKNOWN_COMMAND",
        "ENDOFSTREAM_REJECTED",
        "ENDOFSTREAM_GENERAL_ERROR",
    ],
)
def test_execute_raises_on_non_success_status(
    status: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_send(self: TcpXynaGateway, _: bytes) -> str:
        return f"error\n{status}"

    monkeypatch.setattr(TcpXynaGateway, "_send_payload", fake_send)
    gw = TcpXynaGateway()
    with pytest.raises(RuntimeError):
        gw.execute("status")
