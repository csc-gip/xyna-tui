from __future__ import annotations

import re
from typing import Any

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
)


def parse_box_table(raw: str) -> list[dict[str, str]]:
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    header_idx = next((i for i, line in enumerate(lines) if "│" in line and "═" not in line), None)
    if header_idx is None:
        return []

    headers = [cell.strip() for cell in lines[header_idx].split("│")]
    rows: list[dict[str, str]] = []
    for line in lines[header_idx + 1 :]:
        if "│" not in line or "═" in line:
            continue
        values = [cell.strip() for cell in line.split("│")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values)))
    return rows


def parse_workspaces_table(raw: str) -> list[WorkspaceRecord]:
    rows = parse_box_table(raw)
    if rows:
        return [
            WorkspaceRecord(
                name=row["Name"],
                revision=row["Revision"],
                status=row["Status"],
                problems=int(row["Problems"]),
                requirements=int(row["Requirements"]),
            )
            for row in rows
        ]

    records: list[WorkspaceRecord] = []
    for line in raw.splitlines():
        match = re.match(r"^(.+),\s+STATUS:\s+'([^']+)'\s*$", line.strip())
        if not match:
            continue
        records.append(
            WorkspaceRecord(
                name=match.group(1).strip(),
                revision="-",
                status=match.group(2).strip(),
                problems=0,
                requirements=0,
            )
        )
    return records


def parse_applications_table(raw: str) -> list[ApplicationRecord]:
    rows = parse_box_table(raw)
    if rows:
        return [
            ApplicationRecord(
                name=row["ApplicationName"],
                version=row["VersionName"],
                workspace=row["Workspace"],
                status=row["Status"],
                objects=int(row["Objects"]),
                revision=row["Revision"],
            )
            for row in rows
        ]

    records: list[ApplicationRecord] = []
    pattern = re.compile(
        r"^\s*'([^']+)'\s+'([^']+)'\s+\((\d+)\s+objects\s+\+\s+dependencies\),\s+STATUS:\s+'([^']+)'"
    )
    for line in raw.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        records.append(
            ApplicationRecord(
                name=match.group(1),
                version=match.group(2),
                workspace="-",
                status=match.group(4),
                objects=int(match.group(3)),
                revision="-",
            )
        )
    return records


def parse_properties_verbose(raw: str) -> list[PropertyRecord]:
    records: list[PropertyRecord] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("Name: "):
            continue
        name = _extract(r"Name:\s+(.+?)(?:\s+Value:|\s+Default value:|\s+Reader:|\s+UNUSED$)", line)
        value = _extract(r"Value:\s+'([^']*)'", line) or _extract(r"Value:\s+([^ ]+)", line)
        default = _extract(r"Default value:\s+'([^']*)'", line) or _extract(r"Default value:\s+([^ ]+)", line)
        reader = _extract(r"Reader:\s+(.+)$", line)
        records.append(
            PropertyRecord(
                name=name or "",
                value=value or "not defined",
                default_value=default or "",
                reader=reader or "",
                unused="UNUSED" in line,
            )
        )
    return records


def parse_runtime_dependencies(raw: str) -> list[DependencyRecord]:
    records: list[DependencyRecord] = []
    owner = ""
    for line in raw.splitlines():
        line = line.rstrip()
        stripped = line.strip()
        is_indented = bool(line[:1].isspace())
        if is_indented and owner:
            records.append(DependencyRecord(owner=owner, requirement=stripped))
            continue
        if (stripped.startswith("Application '") or stripped.startswith("Workspace '")) and not is_indented:
            owner = stripped
    return records


def parse_deployment_item(raw: str) -> DeploymentItemRecord:
    fields = {}
    detail_rows: list[tuple[str, str]] = []
    detail_sections: list[tuple[str, list[str]]] = []
    current_section = "General"
    current_items: list[str] = []

    def flush_section() -> None:
        nonlocal current_items
        if current_section != "General" and current_items:
            detail_sections.append((current_section, current_items))
            current_items = []

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith(":") and not re.match(r"^[A-Za-z][A-Za-z0-9 ]*\s*:\s*.*$", stripped):
            flush_section()
            current_section = stripped[:-1]
            continue
        if ":" not in line:
            if line.startswith("  "):
                item = stripped.removeprefix("- ").strip()
                detail_rows.append((current_section, item))
                current_items.append(item)
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
        if key.strip() not in {"Type", "Name", "RuntimeContext", "State"}:
            detail_rows.append((key.strip(), value.strip()))
            if current_section != "General":
                current_items.append(f"{key.strip()}: {value.strip()}")
    flush_section()
    return DeploymentItemRecord(
        item_type=fields.get("Type", ""),
        name=fields.get("Name", ""),
        runtime_context=fields.get("RuntimeContext", ""),
        state=fields.get("State", ""),
        detail_rows=detail_rows,
        detail_sections=detail_sections,
    )


def parse_trigger_table(raw: str) -> list[TriggerRecord]:
    first_table = raw.split("\n\n", 1)[0]
    rows = parse_box_table(first_table)
    return [
        TriggerRecord(
            trigger=row.get("Name", row.get("Trigger", "")),
            runtime_context=row.get("RuntimeContext", ""),
            status=row.get("Status", ""),
            instances=int(row.get("Instances", "0") or "0"),
        )
        for row in rows
    ]


def parse_filter_table(raw: str) -> list[FilterRecord]:
    first_table = raw.split("\n\n", 1)[0]
    rows = parse_box_table(first_table)
    return [
        FilterRecord(
            filter_name=row.get("FilterName", ""),
            runtime_context=row.get("RuntimeContext", ""),
            status=row.get("Status", ""),
            instances=int(row.get("Instances", "0") or "0"),
        )
        for row in rows
    ]


def parse_dashboard_info(uptime_raw: str, listsysteminfo_raw: str, version_raw: str) -> DashboardInfo:
    uptime = _extract(r"Uptime:\s*(.+)$", uptime_raw, flags=re.MULTILINE) or "unknown"
    server_version = _extract(r"Server version:\s*(.+)$", version_raw, flags=re.MULTILINE) or "unknown"
    xmom_version = _extract(r"XMOM version:\s*(.+)$", version_raw, flags=re.MULTILINE) or "unknown"
    os_info = _extract(r"Operating System:\s*(.+)$", listsysteminfo_raw, flags=re.MULTILINE) or "unknown"
    return DashboardInfo(
        factory_state="UP_AND_RUNNING",
        uptime=uptime,
        server_version=server_version,
        xmom_version=xmom_version,
        os_info=os_info,
    )


def parse_listwfs_names(raw: str) -> list[str]:
    names: list[str] = []
    for line in raw.splitlines():
        match = re.search(r"Name:\s*([^,]+),\s*deployment status:", line)
        if match:
            names.append(match.group(1).strip())
    return names


def parse_listwfs_records(raw: str) -> list[ContentItemRecord]:
    records: list[ContentItemRecord] = []
    for line in raw.splitlines():
        match = re.search(r"Name:\s*([^,]+),\s*deployment status:\s*([^\s]+)", line)
        if not match:
            continue
        records.append(
            ContentItemRecord(
                object_type="WORKFLOW",
                object_name=match.group(1).strip(),
                status=match.group(2).strip(),
            )
        )
    return records


def parse_named_name_lines(raw: str) -> list[str]:
    names: list[str] = []
    for line in raw.splitlines():
        match = re.match(r"^\s*Name:\s*(.+?)\s*$", line)
        if match:
            names.append(match.group(1).strip())
    return names


def parse_printdependencies_tree_lines(raw: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for line in raw.splitlines():
        match = re.match(r"^(?P<prefix>(?:\s*\.\s+)*)\*\s+(?P<label>.+)$", line)
        if not match:
            continue
        prefix = match.group("prefix")
        depth = prefix.count(".")
        result.append((depth, match.group("label").strip()))
    return result


def parse_workspace_details(raw: str) -> WorkspaceDetailsRecord:
    lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
    name = lines[0] if lines else ""
    state = ""
    requirements: list[str] = []

    in_requirements = False
    for line in raw.splitlines():
        striped = line.strip()
        if striped.startswith("state "):
            state = striped.replace("state", "", 1).strip()
            continue
        if striped.startswith("requires"):
            in_requirements = True
            continue
        if in_requirements and line.startswith("  ") and striped:
            requirements.append(striped)

    return WorkspaceDetailsRecord(
        name=name,
        state=state,
        requirements=requirements,
        content_by_type={},
    )


def parse_application_details(raw: str) -> ApplicationDetailsRecord:
    lines = [line.rstrip() for line in raw.splitlines()]
    non_empty = [line for line in lines if line.strip()]

    header = non_empty[0] if non_empty else ""
    parts = header.split()
    name = parts[0] if parts else ""
    version = parts[1] if len(parts) > 1 else ""

    state = ""
    sections: dict[str, int] = {}
    section_items: dict[str, list[str]] = {}
    order_entry_lines: list[str] = []

    current_section = ""
    for line in lines:
        striped = line.strip()
        if not striped:
            continue

        if striped.startswith("state "):
            state = striped.replace("state", "", 1).strip()
            continue

        if striped.endswith(":") and striped.upper() == striped:
            current_section = striped[:-1]
            sections.setdefault(current_section, 0)
            section_items.setdefault(current_section, [])
            continue

        if current_section == "ORDER ENTRY INTERFACES":
            order_entry_lines.append(striped)
            continue

        if current_section:
            sections[current_section] = sections.get(current_section, 0) + 1
            section_items.setdefault(current_section, []).append(striped)

    return ApplicationDetailsRecord(
        name=name,
        version=version,
        state=state,
        dependencies=[],
        sections=sections,
        section_items=section_items,
        order_entry_lines=order_entry_lines,
    )


def _extract(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def as_rows(items: list[Any], columns: list[str]) -> list[tuple[Any, ...]]:
    return [tuple(getattr(item, col) for col in columns) for item in items]
