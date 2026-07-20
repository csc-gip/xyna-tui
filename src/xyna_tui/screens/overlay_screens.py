from __future__ import annotations

from datetime import datetime
from queue import Empty, Queue

from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Static, Tree

from ..dependency_tree import build_dependency_tree
from ..fixtures import repo_root_from_here
from ..models import DependencyRecord

_XYNA_THEME = Theme(
    name="xyna",
    primary="#FABB00",
    background="#000000",
    surface="#0d0d0d",
    panel="#1a1a1a",
    foreground="#FFFFFF",
    dark=True,
)


class DependencyTreeScreen(ModalScreen[None]):
    CSS = """
    DependencyTreeScreen {
        background: #0f1419 85%;
    }
    #dependency-tree {
        border: round $primary;
        padding: 0 1;
        background: #0f1419;
        color: #ffffff;
    }
    """
    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("q", "close", "Close", priority=True),
    ]

    def __init__(self, root_context: str, dependency_records: list[DependencyRecord]) -> None:
        super().__init__()
        self.root_context = root_context
        self.dependency_records = dependency_records

    def compose(self):
        yield Static(f"Dependency Tree: {self.root_context}")
        yield Tree(self.root_context, id="dependency-tree")
        yield Static("Press Esc or q to close")

    def on_mount(self) -> None:
        tree_widget = self.query_one("#dependency-tree", Tree)
        tree_widget.root.expand()
        dep_tree = build_dependency_tree(self.root_context, self.dependency_records)
        self._add_nodes(tree_widget.root, dep_tree)

    def _add_nodes(self, parent, node) -> None:
        for child in node.children:
            label = child.context
            if child.is_cycle:
                label = f"{label} [cycle]"
            elif child.is_truncated:
                label = f"{label} [max-depth]"
            branch = parent.add(label)
            if child.children and not child.is_cycle and not child.is_truncated:
                self._add_nodes(branch, child)

    def action_close(self) -> None:
        self.dismiss()


class ObjectDependenciesScreen(ModalScreen[None]):
    CSS = """
    ObjectDependenciesScreen {
        background: #0f1419 85%;
    }
    #object-dependency-tree {
        border: round $primary;
        padding: 0 1;
        background: #0f1419;
        color: #ffffff;
    }
    """
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, root_label: str, dependencies: list[tuple[int, str]]) -> None:
        super().__init__()
        self.root_label = root_label
        self.dependencies = dependencies

    def compose(self):
        yield Static(f"Object Dependencies: {self.root_label}")
        yield Tree(self.root_label, id="object-dependency-tree")
        yield Static("Press Esc or q to close")

    def on_mount(self) -> None:
        tree = self.query_one("#object-dependency-tree", Tree)
        tree.root.expand()

        stack = {0: tree.root}
        for depth, label in self.dependencies:
            parent_depth = max(depth - 1, 0)
            parent = stack.get(parent_depth, tree.root)
            node = parent.add(label)
            stack[depth] = node

    def action_close(self) -> None:
        self.dismiss()


class KeybindingsScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("?", "close", "Close"),
    ]
    CSS = """
    KeybindingsScreen {
        align: center middle;
    }
    #keybindings-container {
        width: 70;
        height: auto;
        max-height: 90%;
        border: round #FABB00;
        padding: 1 2;
        background: #000000;
    }
    #keybindings-title {
        text-align: center;
        color: #FABB00;
        text-style: bold;
        margin-bottom: 1;
    }
    .kb-section-header {
        color: #FABB00;
        text-style: bold;
        margin-top: 1;
    }
    """

    def compose(self):
        with ScrollableContainer(id="keybindings-container"):
            yield Static("Key Bindings", id="keybindings-title")
            yield Static("[bold]Main Screen[/bold]", classes="kb-section-header")
            yield Static(
                "  r            Refresh data\n"
                "  x            Workspace: refresh | Application: start/stop\n"
                "  Shift+X/X    Workspace: refresh and deploy\n"
                "  Ctrl+X       Workspace: refresh and deploy (fallback)\n"
                "  Ctrl+P       Command palette\n"
                "  Ctrl+Shift+P Command palette (fallback)\n"
                "  F1           Command palette (fallback)\n"
                "  n            Workspace: create\n"
                "  c            Workspace: clear\n"
                "  Delete       Workspace: remove\n"
                "  u            Property: reset to default\n"
                "  d            Show Dependency Tree\n"
                "  i            Show Item Details\n"
                "  o            Show Object Dependencies\n"
                "  /            Property: focus name filter\n"
                "  ?            Show this help\n"
                "  q            Quit"
            )
            yield Static("[bold]Workspace / Application Details[/bold]", classes="kb-section-header")
            yield Static(
                "  /            Focus filter input\n"
                "  Enter        Select current item\n"
                "  Tab          Next widget\n"
                "  Shift+Tab    Previous widget\n"
                "  Esc / q      Close screen"
            )
            yield Static("[bold]Dependency Tree / Object Dependencies[/bold]", classes="kb-section-header")
            yield Static(
                "  Arrow keys   Navigate tree\n"
                "  Esc / q      Close screen"
            )
            yield Static("[bold]Object Selection[/bold]", classes="kb-section-header")
            yield Static(
                "  Arrow keys   Navigate list\n"
                "  Enter        Confirm selection\n"
                "  Esc / q      Cancel"
            )
            yield Static("\n[dim]Press Esc or q to close[/dim]")

    def action_close(self) -> None:
        self.dismiss()


class StreamingCommandScreen(ModalScreen[None]):
    CSS = """
    StreamingCommandScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #stream-panel {
        width: 100;
        height: 28;
        max-height: 90%;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 0 1;
    }
    #stream-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #stream-output-container {
        height: 1fr;
        border: heavy #2a333d;
        margin-bottom: 1;
        background: #11161c;
    }
    #stream-output {
        color: #ffffff;
    }
    #stream-status {
        color: #ffffff;
    }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("c", "copy_output", "Copy Output"),
        ("s", "save_output", "Save Output"),
    ]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self._chunks: Queue[str] = Queue()
        self._buffer = ""
        self._done = False

    def compose(self):
        with Vertical(id="stream-panel"):
            yield Static(self.title, id="stream-title")
            with ScrollableContainer(id="stream-output-container"):
                yield Static("", id="stream-output")
            yield Static("Running...", id="stream-status")
            yield Static("c: copy output  |  s: save output  |  Esc/q: close")

    def on_mount(self) -> None:
        self.set_interval(0.1, self._drain_chunks)

    def enqueue_chunk(self, chunk: str) -> None:
        if chunk:
            self._chunks.put(chunk)

    def mark_done(self, success: bool, message: str) -> None:
        self._drain_chunks()
        color = "green" if success else "red"
        self.query_one("#stream-status", Static).update(
            f"[{color}]{message}[/{color}]  Press Esc/q to close"
        )
        self._done = True

    def _drain_chunks(self) -> None:
        updated = False
        while True:
            try:
                chunk = self._chunks.get_nowait()
            except Empty:
                break
            normalized = chunk.replace("\r", "")
            if normalized:
                self._buffer += normalized
                if not self._buffer.endswith("\n"):
                    self._buffer += "\n"
                updated = True
        if updated:
            self.query_one("#stream-output", Static).update(self._buffer.rstrip())
            self.query_one("#stream-output-container", ScrollableContainer).scroll_end(animate=False)

    def action_copy_output(self) -> None:
        text = self._buffer.rstrip()
        if not text:
            self.notify("No output to copy", severity="warning")
            return
        copy_fn = getattr(self.app, "copy_to_clipboard", None)
        if callable(copy_fn):
            copy_fn(text)
            self.notify("Output copied to clipboard", severity="information")
            return
        self.notify("Clipboard copy is not available in this environment", severity="warning")

    def action_save_output(self) -> None:
        text = self._buffer.rstrip()
        if not text:
            self.notify("No output to save", severity="warning")
            return
        root = repo_root_from_here()
        out_dir = root / "test-results" / "stream-logs"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        file_path = out_dir / f"stream-{ts}.log"
        file_path.write_text(text + "\n", encoding="utf-8")
        self.notify(f"Saved output to {file_path}", severity="information")

    def action_close(self) -> None:
        self.dismiss()


class BusyCommandScreen(ModalScreen[None]):
    CSS = """
    BusyCommandScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #busy-panel {
        width: 54;
        height: auto;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #busy-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    """
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self._spinner = ["|", "/", "-", "\\"]
        self._spinner_idx = 0
        self._done = False

    def compose(self):
        with Vertical(id="busy-panel"):
            yield Static(self.title, id="busy-title")
            yield Static("| Waiting for factory response...", id="busy-status")

    def on_mount(self) -> None:
        self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        if self._done:
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner)
        frame = self._spinner[self._spinner_idx]
        self.query_one("#busy-status", Static).update(f"{frame} Waiting for factory response...")

    def mark_done(self, success: bool, message: str) -> None:
        self._done = True
        color = "green" if success else "red"
        self.query_one("#busy-status", Static).update(
            f"[{color}]{message}[/{color}]  Press Esc/q to close"
        )

    def action_close(self) -> None:
        self.dismiss()
