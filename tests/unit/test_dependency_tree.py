from __future__ import annotations

from xyna_tui.dependency_tree import (
    application_context,
    build_adjacency,
    build_dependency_tree,
    workspace_context,
)
from xyna_tui.models import DependencyRecord


def test_context_builders() -> None:
    assert workspace_context("default workspace") == "Workspace 'default workspace'"
    assert application_context("GuiHttp", "1.4.3") == "Application 'GuiHttp', Version '1.4.3'"


def test_build_adjacency_groups_and_sorts() -> None:
    records = [
        DependencyRecord(owner="A", requirement="C"),
        DependencyRecord(owner="A", requirement="B"),
        DependencyRecord(owner="A", requirement="B"),
    ]
    adjacency = build_adjacency(records)
    assert adjacency["A"] == ["B", "C"]


def test_build_dependency_tree_detects_cycle() -> None:
    records = [
        DependencyRecord(owner="A", requirement="B"),
        DependencyRecord(owner="B", requirement="C"),
        DependencyRecord(owner="C", requirement="A"),
    ]

    tree = build_dependency_tree("A", records)
    assert tree.context == "A"
    assert tree.children[0].context == "B"
    assert tree.children[0].children[0].context == "C"
    assert tree.children[0].children[0].children[0].is_cycle is True


def test_build_dependency_tree_marks_max_depth() -> None:
    records = [
        DependencyRecord(owner="A", requirement="B"),
        DependencyRecord(owner="B", requirement="C"),
        DependencyRecord(owner="C", requirement="D"),
    ]

    tree = build_dependency_tree("A", records, max_depth=2)
    leaf = tree.children[0].children[0].children[0]
    assert leaf.is_truncated is True
