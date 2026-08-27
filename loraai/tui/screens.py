"""Modal screens: help, about, file picker and confirmation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Static

from ..textio import TEXT_EXTENSIONS
from ..version import get_version

HELP_TEXT = """\
[b]What loraai does[/b]

  Three separate jobs, kept separate on purpose:

  [b]1. Hidden-character forensics[/b]  — exact, not guesswork
     Finds zero-width characters, Unicode tag characters, variation-selector
     byte chains, bidi overrides, homoglyphs and control characters, and
     decodes any readable payload hidden inside them. These characters are
     physically in the file, so detection and removal are certain.

  [b]2. Writing-style analysis[/b]  — probabilistic
     Measures sentence rhythm, lexical diversity, repetition, punctuation and
     a catalogue of known AI-writing tells, then combines them into a score
     with every contributing signal shown. It does not prove authorship.

  [b]3. Humanization[/b]  — rewriting
     Removes invisible characters, chat-assistant phrasing, inflated
     vocabulary, formulaic transitions and mechanical rhythm. Code, URLs,
     citations and links are preserved byte-for-byte.

[b]What it will not claim[/b]

  Modern AI text watermarks are [i]statistical[/i]: they bias which tokens the
  model picks, and add no character to the output. Detecting one needs the
  generator's secret key. No local tool can do it, this one included, and it
  says so instead of inventing a number. Deleting zero-width characters does
  not remove such a watermark — the two are unrelated mechanisms.

[b]Keyboard[/b]

  [b]Navigation[/b]
    1 … 8          jump to a pane
    tab / s-tab    move focus
    up / down      move within lists and tables

  [b]Actions[/b]
    ctrl+r         run analysis
    ctrl+o         open a file
    ctrl+l         clean the current text
    ctrl+h         humanize the current text
    ctrl+s         save the active output
    ctrl+y         copy the active output to the clipboard
    ctrl+t         switch light / dark theme

  [b]General[/b]
    f1 or ?        this help
    ctrl+p         command palette
    ctrl+q         quit

[b]Input[/b]

  Two ways in, as with the command line: type or paste directly into the
  Input pane, or load any text file. Source files are handled specially —
  forensics covers the whole file, while style metrics use comments only.
"""


class HelpScreen(ModalScreen[None]):
    """Keyboard reference and an explanation of what the tool claims."""

    BINDINGS = [
        Binding("escape,q,f1,question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Static("loraai — help", id="modal-title")
            with VerticalScroll(id="modal-body"):
                yield Static(HELP_TEXT)
            with Vertical(id="modal-actions"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class AboutScreen(ModalScreen[None]):
    """Version and provenance references."""

    BINDINGS = [Binding("escape,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        from ..analysis.provenance import REFERENCES

        body = Text()
        body.append(f"loraai {get_version()}\n\n", style="bold")
        body.append(
            "Text forensics, hidden-Unicode detection, writing analysis and "
            "humanization.\n\n"
        )
        body.append("Provenance references\n", style="bold")
        for title, url in REFERENCES:
            body.append(f"  • {title}\n")
            body.append(f"    {url}\n", style="underline")
        body.append(
            "\nWriting-style analysis is probabilistic and does not establish "
            "authorship. Statistical sampling watermarks are not detectable by "
            "any local tool.",
            style="dim",
        )

        with Vertical(id="modal"):
            yield Static("About", id="modal-title")
            with VerticalScroll(id="modal-body"):
                yield Static(body)
            with Vertical(id="modal-actions"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)


class FilteredDirectoryTree(DirectoryTree):
    """Directory tree that hides noise and non-text files."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        for path in paths:
            if path.name.startswith("."):
                continue
            if path.is_dir():
                if path.name in ("__pycache__", "node_modules", ".git", ".venv"):
                    continue
                yield path
            elif path.suffix.lower() in TEXT_EXTENSIONS or not path.suffix:
                yield path


class FilePickerScreen(ModalScreen[Optional[str]]):
    """Browse for a file, or type a path directly."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, start: Optional[str] = None) -> None:
        super().__init__()
        self._start = start or "."

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Static("Open file", id="modal-title")
            yield Input(placeholder="Type a path, or pick below…", id="path-input")
            with VerticalScroll(id="modal-body"):
                yield FilteredDirectoryTree(self._start, id="tree")
            with Vertical(id="modal-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Open", variant="primary", id="open")

    def on_mount(self) -> None:
        self.query_one("#path-input", Input).focus()

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self.dismiss(str(event.path))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open":
            value = self.query_one("#path-input", Input).value.strip()
            self.dismiss(value or None)
        else:
            self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no confirmation for anything destructive."""

    BINDINGS = [Binding("escape,n", "deny", "No"), Binding("y", "accept", "Yes")]

    def __init__(self, question: str, detail: str = "") -> None:
        super().__init__()
        self._question = question
        self._detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Static(self._question, id="modal-title")
            if self._detail:
                yield Static(Text(self._detail, style="dim"), id="modal-body")
            with Vertical(id="modal-actions"):
                yield Button("Cancel", id="no")
                yield Button("Confirm", variant="primary", id="yes")

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class TextViewScreen(ModalScreen[None]):
    """Full-screen read-only view of a long piece of text."""

    BINDINGS = [Binding("escape,q", "dismiss", "Close")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Static(self._title, id="modal-title")
            with VerticalScroll(id="modal-body"):
                yield Static(self._body)
            with Vertical(id="modal-actions"):
                yield Button("Close", variant="primary", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
