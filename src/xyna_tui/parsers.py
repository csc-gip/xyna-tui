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


def parse_properties(raw: str) -> list[PropertyRecord]:
    records: list[PropertyRecord] = []
    current: PropertyRecord | None = None

    for raw_line in raw.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("Listing information for "):
            continue
        if stripped.startswith("Name: "):
            if current is not None:
                records.append(current)
            current = PropertyRecord(
                name=_extract_property_field(stripped, "Name:") or "",
                value=_normalize_property_value(_extract_property_field(stripped, "Value:")),
                default_value=_normalize_property_value(_extract_property_field(stripped, "Default value:")),
                reader=_extract_property_field(stripped, "Reader:") or "",
                unused="UNUSED" in stripped,
                documentation=_normalize_property_documentation(
                    _extract_property_field(stripped, "Documentation:") or ""
                ),
            )
            continue
        if current is not None and current.documentation:
            current.documentation = _append_property_documentation_line(current.documentation, stripped)

    if current is not None:
        records.append(current)
    return records


def parse_properties_verbose(raw: str) -> list[PropertyRecord]:
    return parse_properties(raw)


def _extract_property_field(line: str, marker: str) -> str | None:
    markers = [" Value:", " Default value:", " Documentation:", " Reader:", "  UNUSED"]
    try:
        start = line.index(marker) + len(marker)
    except ValueError:
        return None

    end = len(line)
    for next_marker in markers:
        if next_marker.strip() == marker.strip():
            continue
        idx = line.find(next_marker, start)
        if idx != -1:
            end = min(end, idx)
    return line[start:end].strip()


def _normalize_property_value(value: str | None) -> str:
    if value is None:
        return ""
    text = value.strip()
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text


def _append_property_documentation_line(current: str, line: str) -> str:
    cleaned = _normalize_property_documentation_line(line)
    if not cleaned:
        return current
    return f"{current}\n{cleaned}" if current else cleaned


def _normalize_property_documentation(text: str) -> str:
    lines = [_normalize_property_documentation_line(line) for line in text.splitlines()]
    normalized = [line for line in lines if line]
    return "\n".join(normalized)


def _normalize_property_documentation_line(line: str) -> str:
    stripped = line.rstrip()
    compact = stripped.strip()
    # Wrapped metadata fragments are not part of documentation content.
    if not compact:
        return ""
    if compact.startswith("Reader:"):
        return ""
    if compact in {"UNUSED", "' UNUSED", '" UNUSED'}:
        return ""
    compact = re.sub(r"\s+UNUSED$", "", compact)
    if compact in {"'", '"'}:
        return ""
    return compact.strip()


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
    # ── regex helpers ──────────────────────────────────────────────────────
    _PUB_SEC = re.compile(r"^Interfaces .+ publishes in (SAVED|DEPLOYED) state:$")
    _USE_SEC = re.compile(r"^Interfaces .+ uses in (SAVED|DEPLOYED) state:$")
    _UBY_SEC = re.compile(r"^Objects that use .+ in (SAVED|DEPLOYED) state:$")
    _ERROR = re.compile(r"^\(\d+\)\s+.+")
    _ERROR_CODE = re.compile(r"^\((\d+)\)")
    _DEP = re.compile(r"^(DATATYPE|WORKFLOW|EXCEPTION)\s+(\S+)")
    _EMP = re.compile(r"^InterfaceEmployment in (?:DATATYPE|WORKFLOW|EXCEPTION)\s+(\S+):$")

    # ── legacy state ───────────────────────────────────────────────────────
    fields: dict[str, str] = {}
    detail_rows: list[tuple[str, str]] = []
    detail_sections: list[tuple[str, list[str]]] = []
    current_section = "General"
    current_items: list[str] = []

    def flush_section() -> None:
        nonlocal current_items
        if current_section != "General" and current_items:
            detail_sections.append((current_section, list(current_items)))
            current_items = []

    # ── per-state structured state ─────────────────────────────────────────
    errors_by_state: dict[str, set[str]] = {"SAVED": set(), "DEPLOYED": set()}
    deps_by_state: dict[str, set[str]] = {"SAVED": set(), "DEPLOYED": set()}
    pub_by_state: dict[str, set[str]] = {"SAVED": set(), "DEPLOYED": set()}
    emp_by_state: dict[str, set[tuple[str, str]]] = {"SAVED": set(), "DEPLOYED": set()}
    uby_by_state: dict[str, set[str]] = {"SAVED": set(), "DEPLOYED": set()}

    sec_type = "general"  # "publishes" | "uses" | "used_by"
    sec_state = ""        # "SAVED" | "DEPLOYED"
    pending_emp: str | None = None  # employment context awaiting signature line

    def _sort_errors(error_set: set[str]) -> list[str]:
        """Sort error strings by their error code (number in parentheses)."""
        def sort_key(e: str) -> tuple[int, str]:
            m = _ERROR_CODE.match(e)
            code = int(m.group(1)) if m else 999999
            return (code, e)
        return sorted(error_set, key=sort_key)

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            pending_emp = None
            continue

        is_item = line.startswith("  - ")
        is_cont = line.startswith("    ") and not line.startswith("  - ")

        # ── Employment continuation (4-space indent, no dash) ──────────────
        if pending_emp is not None and is_cont:
            emp = (pending_emp, stripped)
            emp_by_state[sec_state].add(emp)
            current_items.append(f"  {stripped}")
            detail_rows.append((current_section, stripped))
            pending_emp = None
            continue
        if pending_emp is not None:
            pending_emp = None

        # ── Section headers (col-0, end with ":") ─────────────────────────
        if not line[:1].isspace() and stripped.endswith(":"):
            flush_section()
            current_section = stripped[:-1]
            m_pub = _PUB_SEC.match(stripped)
            m_use = _USE_SEC.match(stripped)
            m_uby = _UBY_SEC.match(stripped)
            if m_pub:
                sec_type = "publishes"
                sec_state = m_pub.group(1)
            elif m_use:
                sec_type = "uses"
                sec_state = m_use.group(1)
            elif m_uby:
                sec_type = "used_by"
                sec_state = m_uby.group(1)
            else:
                sec_type = "general"
                sec_state = ""
            continue

        # ── Header key-value pairs (col-0, contains ":") ──────────────────
        if not line[:1].isspace() and ":" in line:
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            fields[key] = value
            if key not in {"Type", "Name", "RuntimeContext", "State"}:
                detail_rows.append((key, value))
                if current_section != "General":
                    current_items.append(f"{key}: {value}")
            continue

        # ── List items ("  - ...") ─────────────────────────────────────────
        if is_item:
            item = stripped[2:].strip()  # strip leading "- "
            detail_rows.append((current_section, item))
            current_items.append(item)

            if sec_type == "publishes":
                pub_by_state[sec_state].add(item)

            elif sec_type == "uses":
                if _ERROR.match(item):
                    errors_by_state[sec_state].add(item)
                elif _EMP.match(item):
                    m = _EMP.match(item)
                    pending_emp = m.group(1) if m else None
                elif _DEP.match(item):
                    m = _DEP.match(item)
                    dep_key = f"{m.group(1)} {m.group(2)}" if m else item
                    deps_by_state[sec_state].add(dep_key)

            elif sec_type == "used_by":
                uby_by_state[sec_state].add(item)
            continue

        # ── Bare non-indented text (edge cases) ────────────────────────────
        if not line[:1].isspace() and ":" not in line:
            detail_rows.append((current_section, stripped))
            current_items.append(stripped)

    flush_section()
    
    return DeploymentItemRecord(
        item_type=fields.get("Type", ""),
        name=fields.get("Name", ""),
        runtime_context=fields.get("RuntimeContext", ""),
        state=fields.get("State", ""),
        errors_saved=_sort_errors(errors_by_state["SAVED"]),
        errors_deployed=_sort_errors(errors_by_state["DEPLOYED"]),
        publishes_saved=sorted(pub_by_state["SAVED"]),
        publishes_deployed=sorted(pub_by_state["DEPLOYED"]),
        clean_deps_saved=sorted(deps_by_state["SAVED"]),
        clean_deps_deployed=sorted(deps_by_state["DEPLOYED"]),
        interface_employments_saved=sorted(emp_by_state["SAVED"]),
        interface_employments_deployed=sorted(emp_by_state["DEPLOYED"]),
        used_by_saved=sorted(uby_by_state["SAVED"]),
        used_by_deployed=sorted(uby_by_state["DEPLOYED"]),
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

    host_mem_match = re.search(
        r"([\d,]+)\s*kB free memory\s*/\s*([\d,]+)\s*kB total memory",
        listsysteminfo_raw,
    )
    host_memory_free_kb = _to_int(host_mem_match.group(1)) if host_mem_match else None
    host_memory_total_kb = _to_int(host_mem_match.group(2)) if host_mem_match else None

    jvm_heap_match = re.search(
        r"([\d,]+)\s*kB actively occupied by objects within heap",
        listsysteminfo_raw,
    )
    jvm_heap_current_match = re.search(
        r"([\d,]+)\s*kB current total heap size",
        listsysteminfo_raw,
    )
    jvm_heap_max_match = re.search(
        r"([\d,]+)\s*kB max heap size",
        listsysteminfo_raw,
    )

    cpu_usage_match = re.search(
        r"CPU(?:\s+usage|\s+load)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*%",
        listsysteminfo_raw,
        flags=re.IGNORECASE,
    )
    cpu_usage_percent = float(cpu_usage_match.group(1)) if cpu_usage_match else None

    return DashboardInfo(
        factory_state="UP_AND_RUNNING",
        uptime=uptime,
        server_version=server_version,
        xmom_version=xmom_version,
        os_info=os_info,
        host_memory_free_kb=host_memory_free_kb,
        host_memory_total_kb=host_memory_total_kb,
        jvm_heap_used_kb=_to_int(jvm_heap_match.group(1)) if jvm_heap_match else None,
        jvm_heap_current_kb=_to_int(jvm_heap_current_match.group(1)) if jvm_heap_current_match else None,
        jvm_heap_max_kb=_to_int(jvm_heap_max_match.group(1)) if jvm_heap_max_match else None,
        cpu_usage_percent=cpu_usage_percent,
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


def parse_problem_items(raw: str) -> list[ContentItemRecord]:
    """Extract problematic deployment items from workspace/application details output.
    
    Looks for the "has problems:" section with items formatted as:
      deployment item state
        name: <name>
        type: <type>
        state: <DEPLOYED|SAVED|INVALID>
    """
    items: list[ContentItemRecord] = []
    in_problems = False
    current_item_name = ""
    current_item_type = ""
    current_item_state = ""
    
    for line in raw.splitlines():
        stripped = line.strip()
        
        # Detect "has problems:" section
        if stripped == "has problems:":
            in_problems = True
            continue
        
        if not in_problems:
            continue
        
        # Stop if we hit a section that's not indented (end of problems)
        if stripped and not line.startswith(" "):
            break
        
        # Parse deployment item state blocks
        if stripped == "deployment item state":
            # Save previous item if any
            if current_item_name and current_item_type and current_item_state:
                items.append(ContentItemRecord(
                    object_type=current_item_type,
                    object_name=current_item_name,
                    status=current_item_state,
                ))
            current_item_name = ""
            current_item_type = ""
            current_item_state = ""
            continue
        
        # Extract fields
        if stripped.startswith("name:"):
            current_item_name = stripped.replace("name:", "").strip()
        elif stripped.startswith("type:"):
            current_item_type = stripped.replace("type:", "").strip()
        elif stripped.startswith("state:"):
            current_item_state = stripped.replace("state:", "").strip()
    
    # Don't forget the last item
    if current_item_name and current_item_type and current_item_state:
        items.append(ContentItemRecord(
            object_type=current_item_type,
            object_name=current_item_name,
            status=current_item_state,
        ))
    
    return items


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


def _to_int(value: str) -> int:
    return int(value.replace(",", "").strip())


def as_rows(items: list[Any], columns: list[str]) -> list[tuple[Any, ...]]:
    return [tuple(getattr(item, col) for col in columns) for item in items]
