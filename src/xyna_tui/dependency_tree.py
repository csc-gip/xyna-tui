from __future__ import annotations

from dataclasses import dataclass, field

from .models import DependencyRecord


@dataclass(slots=True)
class DependencyNode:
    context: str
    children: list["DependencyNode"] = field(default_factory=list)
    is_cycle: bool = False
    is_truncated: bool = False


def workspace_context(name: str) -> str:
    return f"Workspace '{name}'"


def application_context(name: str, version: str) -> str:
    return f"Application '{name}', Version '{version}'"


def build_adjacency(records: list[DependencyRecord]) -> dict[str, list[str]]:
    adjacency: dict[str, set[str]] = {}
    for record in records:
        adjacency.setdefault(record.owner, set()).add(record.requirement)
    return {owner: sorted(children) for owner, children in adjacency.items()}


def build_dependency_tree(
    root_context: str,
    records: list[DependencyRecord],
    max_depth: int = 20,
) -> DependencyNode:
    adjacency = build_adjacency(records)

    def _build(current: str, path: set[str], depth: int) -> DependencyNode:
        node = DependencyNode(context=current)
        if depth >= max_depth:
            node.children.append(
                DependencyNode(context="...", is_truncated=True)
            )
            return node

        for child in adjacency.get(current, []):
            if child in path:
                node.children.append(DependencyNode(context=child, is_cycle=True))
                continue
            child_node = _build(child, path | {child}, depth + 1)
            node.children.append(child_node)
        return node

    return _build(root_context, {root_context}, 0)
