from __future__ import annotations

import shlex
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import re

from .fixtures import extract_command_output, fixture_path, load_text


class XynaGateway(Protocol):
    def execute(self, command: str) -> str:
        """Execute command and return raw output (without status token)."""


@dataclass(slots=True)
class TcpXynaGateway:
    host: str = "127.0.0.1"
    port: int = 4242
    timeout_seconds: float = 10.0

    _group_sep: bytes = b"\x1d"
    _record_sep: bytes = b"\x1e"
    _eot: bytes = b"\x04"

    def execute(self, command: str) -> str:
        tokens = shlex.split(command)
        if not tokens:
            raise ValueError("Command must not be empty")

        payload = self._encode_call(tokens)
        response = self._send_payload(payload)
        body, status = self._split_response(response)

        if status in {
            "ENDOFSTREAM_SUCCESS",
            "ENDOFSTREAM_SILENT",
            "ENDOFSTREAM_SUCCESS_BUT_NO_CHANGE",
            "ENDOFSTREAM_STATUS_UP_AND_RUNNING",
        }:
            return body.strip()
        raise RuntimeError(f"Xyna command failed: {status or 'UNKNOWN_STATUS'}")

    def _encode_call(self, tokens: list[str]) -> bytes:
        head = tokens[0].encode("utf-8")
        args = [token.encode("utf-8") for token in tokens[1:]]
        payload = head + self._group_sep
        if args:
            # Match fast_factory_call framing: args are RS-separated and end with RS.
            payload += self._record_sep.join(args) + self._record_sep
        payload += self._group_sep + self._eot
        return payload

    def _send_payload(self, payload: bytes) -> str:
        chunks: list[bytes] = []
        with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
            sock.settimeout(self.timeout_seconds)
            sock.sendall(payload)
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                if self._eot in chunk:
                    before_eot, _, _ = chunk.partition(self._eot)
                    chunks.append(before_eot)
                    break
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", errors="replace")

    def _split_response(self, text: str) -> tuple[str, str]:
        marker = "ENDOFSTREAM_"
        idx = text.rfind(marker)
        if idx == -1:
            return text, ""
        body = text[:idx]
        status = text[idx:].strip().splitlines()[-1]
        return body, status


@dataclass(slots=True)
class MockXynaGateway:
    _fixtures: dict[str, str]

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "MockXynaGateway":
        fixture_map = {
            "uptime": ("status.txt", "uptime"),
            "listsysteminfo": ("status.txt", "listsysteminfo"),
            "version": ("status.txt", "version"),
            "listworkspaces -t": ("listworkspaces.txt", "listworkspaces -t"),
            "listapplications -t": ("listapplications.txt", "listapplications -t"),
            "listproperties -v": ("listproperties.txt", "listproperties -v"),
            "listruntimecontextdependencies": (
                "runtimecontextdependencies.txt",
                "listruntimecontextdependencies",
            ),
            "showdeploymentitemdetails -objectName csc.test.TestKeyInfo": (
                "showdeploymentitemdetails.txt",
                "showdeploymentitemdetails -objectName csc.test.TestKeyInfo",
            ),
            "showdeploymentitemdetails -v -objectName \"csc.test.TestKeyInfo\"": (
                "showdeploymentitemdetails.txt",
                "showdeploymentitemdetails -v -objectName csc.test.TestKeyInfo",
            ),
            "showdeploymentitemdetails -workspaceName \"default workspace\" -objectName \"csc.test.TestKeyInfo\"": (
                "deployment-context.txt",
                'showdeploymentitemdetails -workspaceName "default workspace" -objectName csc.test.TestKeyInfo',
            ),
            "showdeploymentitemdetails -applicationName \"Base\" -versionName \"1.1.4\" -objectName \"xmcp.manualinteraction.ManualInteraction\"": (
                "deployment-context.txt",
                "showdeploymentitemdetails -applicationName Base -versionName 1.1.4 -objectName xmcp.manualinteraction.ManualInteraction",
            ),
            "listtriggers -s": ("trigger-filter.txt", "listtriggers -s"),
            "listfilters -c": ("trigger-filter.txt", "listfilters -c"),
            "listapplicationdetails -applicationName \"Base\"": (
                "listappdetails.txt",
                "listapplicationdetails -applicationName Base",
            ),
            "listapplicationdetails -applicationName \"Base\" -versionName \"1.1.4\"": (
                "listappdetails.txt",
                "listapplicationdetails -applicationName Base",
            ),
            "listworkspacedetails -workspaceName \"default workspace\"": (
                "listws-details.txt",
                'listworkspacedetails -workspaceName "default workspace"',
            ),
            "listwfs -workspaceName \"default workspace\"": (
                "object-deps.txt",
                'listwfs -workspaceName "default workspace"',
            ),
            "listwfs -applicationName \"Base\" -versionName \"1.1.4\"": (
                "object-deps.txt",
                "listwfs -applicationName Base -versionName 1.1.4",
            ),
            "printdependencies -workspaceName \"default workspace\" -object \"csc.test.TestKeyInfo\" -objectType Workflow -r": (
                "object-deps.txt",
                'printdependencies -workspaceName "default workspace" -object csc.test.TestKeyInfo -objectType Workflow -r',
            ),
            "printdependencies -applicationName \"Base\" -versionName \"1.1.4\" -object \"xmcp.manualinteraction.ManualInteraction\" -objectType Workflow -r": (
                "object-deps.txt",
                "printdependencies -applicationName Base -versionName 1.1.4 -object xnwh.persistence.Query -objectType Workflow -r",
            ),
            "listdoms -workspaceName \"default workspace\"": (
                "scope-content.txt",
                'listdoms -workspaceName "default workspace"',
            ),
            "listdoms -applicationName \"Base\" -versionName \"1.1.4\"": (
                "scope-content.txt",
                "listdoms -applicationName Base -versionName 1.1.4",
            ),
            "listexceptions -workspaceName \"default workspace\"": (
                "scope-content.txt",
                'listexceptions -workspaceName "default workspace"',
            ),
            "listexceptions -applicationName \"Base\" -versionName \"1.1.4\"": (
                "scope-content.txt",
                "listexceptions -applicationName Base -versionName 1.1.4",
            ),
        }

        resolved: dict[str, str] = {}
        for key, (filename, cmd) in fixture_map.items():
            raw = load_text(fixture_path(repo_root, filename))
            resolved[key] = extract_command_output(raw, cmd)
        return cls(_fixtures=resolved)

    def execute(self, command: str) -> str:
        if command not in self._fixtures:
            if command.startswith("showdeploymentitemdetails"):
                is_verbose = " -v" in command or command.endswith(" -v")
                ws_match = re.search(r'-workspaceName\s+"([^"]+)"', command)
                app_match = re.search(r'-applicationName\s+"([^"]+)"', command)
                ver_match = re.search(r'-versionName\s+"([^"]+)"', command)
                obj_match = re.search(r'-objectName\s+"([^"]+)"', command)
                object_name = obj_match.group(1) if obj_match else "csc.test.TestKeyInfo"
                if app_match and ver_match:
                    runtime_context = f"Application '{app_match.group(1)}', Version '{ver_match.group(1)}'"
                elif ws_match:
                    runtime_context = f"Workspace '{ws_match.group(1)}'"
                else:
                    runtime_context = "Workspace 'default workspace'"
                lines = [
                    "Type                : Workflow",
                    f"Name                : {object_name}",
                    f"RuntimeContext      : {runtime_context}",
                    "State               : DEPLOYED",
                ]
                if is_verbose:
                    lines.extend(
                        [
                            "",
                            f"Interfaces {object_name} publishes in DEPLOYED state:",
                            f"  - WORKFLOW {object_name}",
                            "",
                            f"Objects that use {object_name} in DEPLOYED state:",
                        ]
                    )
                return "\n".join(lines)
            raise KeyError(f"No mock fixture for command: {command}")
        return self._fixtures[command]
