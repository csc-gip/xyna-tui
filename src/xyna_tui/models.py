from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WorkspaceRecord:
    name: str
    revision: str
    status: str
    problems: int
    requirements: int


@dataclass(slots=True)
class ApplicationRecord:
    name: str
    version: str
    workspace: str
    status: str
    objects: int
    revision: str


@dataclass(slots=True)
class PropertyRecord:
    name: str
    value: str
    default_value: str
    reader: str
    unused: bool
    documentation: str = ""


@dataclass(slots=True)
class DependencyRecord:
    owner: str
    requirement: str


@dataclass(slots=True)
class DeploymentItemRecord:
    item_type: str
    name: str
    runtime_context: str
    state: str
    # Structured fields — tracked per state to detect differences
    errors_saved: list[str]                      # error items in SAVED state, sorted by code
    errors_deployed: list[str]                   # error items in DEPLOYED state, sorted by code
    publishes_saved: list[str]
    publishes_deployed: list[str]
    clean_deps_saved: list[str]
    clean_deps_deployed: list[str]
    interface_employments_saved: list[tuple[str, str]]
    interface_employments_deployed: list[tuple[str, str]]
    used_by_saved: list[str]
    used_by_deployed: list[str]
    # Legacy flat fields (kept for backward compatibility)
    detail_rows: list[tuple[str, str]]
    detail_sections: list[tuple[str, list[str]]]


@dataclass(slots=True)
class TriggerRecord:
    trigger: str
    runtime_context: str
    status: str
    instances: int


@dataclass(slots=True)
class FilterRecord:
    filter_name: str
    runtime_context: str
    status: str
    instances: int


@dataclass(slots=True)
class DashboardInfo:
    factory_state: str
    uptime: str
    server_version: str
    xmom_version: str
    os_info: str
    host_memory_free_kb: int | None
    host_memory_total_kb: int | None
    jvm_heap_used_kb: int | None
    jvm_heap_current_kb: int | None
    jvm_heap_max_kb: int | None
    cpu_usage_percent: float | None


@dataclass(slots=True)
class WorkspaceDetailsRecord:
    name: str
    state: str
    requirements: list[str]
    content_by_type: dict[str, list[str]]


@dataclass(slots=True)
class ApplicationDetailsRecord:
    name: str
    version: str
    state: str
    dependencies: list[str]
    sections: dict[str, int]
    section_items: dict[str, list[str]]
    order_entry_lines: list[str]


@dataclass(slots=True)
class ObjectSelectionRecord:
    object_type: str
    object_name: str


@dataclass(slots=True)
class ContentItemRecord:
    object_type: str
    object_name: str
    status: str
