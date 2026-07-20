from __future__ import annotations

from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static, TextArea

from ..models import ObjectSelectionRecord, PropertyRecord


class ConfirmScreen(ModalScreen[bool]):
    CSS = """
    ConfirmScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #confirm-panel {
        width: 72;
        max-width: 90%;
        height: auto;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #confirm-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    """
    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("enter", "confirm", "Yes"),
        ("escape", "cancel", "No"),
        ("q", "cancel", "No"),
    ]

    def __init__(self, title: str, message: str) -> None:
        super().__init__()
        self.title = title
        self.message = message

    def compose(self):
        with Vertical(id="confirm-panel"):
            yield Static(self.title, id="confirm-title")
            yield Static(self.message)
            yield Static("\nPress y/Enter to confirm, n/Esc to cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class WorkspaceNameScreen(ModalScreen[str | None]):
    CSS = """
    WorkspaceNameScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #workspace-name-panel {
        width: 80;
        max-width: 90%;
        height: auto;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #workspace-name-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #workspace-name-input {
        margin-top: 1;
    }
    """
    BINDINGS = [
        Binding("enter", "submit", "Create", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("q", "cancel", "Cancel", priority=True),
    ]

    def compose(self):
        with Vertical(id="workspace-name-panel"):
            yield Static("Create workspace", id="workspace-name-title")
            yield Static("Enter workspace name:")
            yield Input(placeholder="workspace name", id="workspace-name-input")
            yield Static("Enter: create  |  Esc/q: cancel")

    def on_mount(self) -> None:
        self.query_one("#workspace-name-input", Input).focus()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one("#workspace-name-input", Input).value.strip()
        if not value:
            self.notify("Workspace name must not be empty", severity="warning")
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PropertyDetailsScreen(ModalScreen[tuple[str, str, str] | None]):
    CSS = """
    PropertyDetailsScreen {
        background: #0f1419 85%;
        align: center middle;
    }
    #property-details-panel {
        width: 110;
        max-width: 95%;
        height: auto;
        max-height: 90%;
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 1 2;
    }
    #property-details-title {
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #property-value-input {
        margin: 1 0;
    }
    #property-documentation-en-input,
    #property-documentation-de-input {
        height: 6;
        margin-top: 1;
        border: tall $primary;
        background: #11161c;
        color: #ffffff;
    }
    #property-meta {
        color: #dfe7ef;
    }
    #property-doc-en-label,
    #property-doc-de-label {
        margin-top: 1;
    }
    """
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+g", "cancel", "Cancel", priority=True),
        Binding("tab", "next_field", "Next Field", priority=True),
        Binding("shift+tab", "previous_field", "Previous Field", priority=True),
    ]

    def __init__(self, record: PropertyRecord, documentation_en: str = "", documentation_de: str = "") -> None:
        super().__init__()
        self.record = record
        self.documentation_en = documentation_en
        self.documentation_de = documentation_de

    def compose(self):
        default_text = self.record.default_value or "-"
        reader_text = self.record.reader or "-"
        unused_text = "yes" if self.record.unused else "no"
        value_text = "" if self.record.value == "not defined" else self.record.value
        with ScrollableContainer(id="property-details-panel"):
            yield Static(f"Property Details: {self.record.name}", id="property-details-title")
            yield Static(
                f"Reader: {reader_text}\nDefault: {default_text}\nUnused: {unused_text}",
                id="property-meta",
            )
            yield Static("Value")
            yield Input(value=value_text, placeholder="property value", id="property-value-input")
            yield Static("Documentation (EN)", id="property-doc-en-label")
            yield TextArea(
                self.documentation_en,
                id="property-documentation-en-input",
                soft_wrap=True,
                tab_behavior="focus",
            )
            yield Static("Documentation (DE)", id="property-doc-de-label")
            yield TextArea(
                self.documentation_de,
                id="property-documentation-de-input",
                soft_wrap=True,
                tab_behavior="focus",
            )
            yield Static("Ctrl+S: save  |  Tab/Shift+Tab: switch field  |  Esc/Ctrl+G: cancel")

    def on_mount(self) -> None:
        self.query_one("#property-value-input", Input).focus()

    def action_next_field(self) -> None:
        self._cycle_focus(direction=1)

    def action_previous_field(self) -> None:
        self._cycle_focus(direction=-1)

    def _cycle_focus(self, direction: int) -> None:
        fields = [
            self.query_one("#property-value-input", Input),
            self.query_one("#property-documentation-en-input", TextArea),
            self.query_one("#property-documentation-de-input", TextArea),
        ]
        focused = self.focused
        idx = fields.index(focused) if focused in fields else 0
        fields[(idx + direction) % len(fields)].focus()

    def action_save(self) -> None:
        value = self.query_one("#property-value-input", Input).value
        documentation_en = self.query_one("#property-documentation-en-input", TextArea).text
        documentation_de = self.query_one("#property-documentation-de-input", TextArea).text
        self.dismiss((value, documentation_en, documentation_de))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ObjectSelectionScreen(ModalScreen[ObjectSelectionRecord | None]):
    CSS = """
    ObjectSelectionScreen {
        background: #0f1419 85%;
    }
    #object-selection-table {
        border: round $primary;
        background: #0f1419;
        color: #ffffff;
        padding: 0 1;
    }
    """
    BINDINGS = [
        ("enter", "choose", "Choose"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(self, title: str, objects: list[ObjectSelectionRecord]) -> None:
        super().__init__()
        self.title = title
        self.objects = objects

    def compose(self):
        yield Static(self.title)
        yield DataTable(id="object-selection-table")
        yield Static("Select an object and press Enter. Esc/q closes.")

    def on_mount(self) -> None:
        table = self.query_one("#object-selection-table", DataTable)
        table.add_columns("Type", "Object")
        for obj in self.objects:
            table.add_row(obj.object_type, obj.object_name)
        table.focus()

    def action_choose(self) -> None:
        table = self.query_one("#object-selection-table", DataTable)
        if table.cursor_row < 0:
            self.dismiss(None)
            return
        row = table.get_row_at(table.cursor_row)
        self.dismiss(ObjectSelectionRecord(object_type=str(row[0]), object_name=str(row[1])))

    def action_close(self) -> None:
        self.dismiss(None)
