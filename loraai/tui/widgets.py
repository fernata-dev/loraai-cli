"""Reusable TUI widgets.

Each one owns a single presentation concern so the panes in
:mod:`loraai.tui.app` stay about layout and wiring rather than formatting.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Label, Static

from ..models import Analysis, Severity, Verdict

SEVERITY_TOKEN = {
    Severity.INFO: "$text-muted",
    Severity.LOW: "$text-muted",
    Severity.MEDIUM: "$warning",
    Severity.HIGH: "$warning",
    Severity.CRITICAL: "$error",
}

VERDICT_CLASS = {
    Verdict.LIKELY_HUMAN: "good",
    Verdict.LEANS_HUMAN: "good",
    Verdict.INCONCLUSIVE: "warn",
    Verdict.LEANS_SYNTHETIC: "warn",
    Verdict.LIKELY_SYNTHETIC: "bad",
}


class StatCard(Widget):
    """A labelled number in a bordered box."""

    def __init__(
        self,
        key: str,
        value: str = "-",
        *,
        tone: str = "",
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id)
        self._key = key
        self._value = value
        if tone:
            self.add_class(tone)

    def compose(self) -> ComposeResult:
        yield Static(self._key, classes="stat-key")
        yield Static(self._value, classes="stat-value", id=f"{self.id or 'card'}-value")

    def update_value(self, value: str, tone: str = "") -> None:
        """Set the displayed value, optionally changing the border tone."""
        self._value = value
        try:
            self.query_one(".stat-value", Static).update(value)
        except Exception:
            return
        for candidate in ("accent", "good", "warn", "bad"):
            self.remove_class(candidate)
        if tone:
            self.add_class(tone)


class VerdictPanel(Widget):
    """The headline assessment: label, meter and top signals."""

    def __init__(self, id: Optional[str] = None) -> None:
        super().__init__(id=id)
        self._analysis: Optional[Analysis] = None

    def compose(self) -> ComposeResult:
        yield Static(id="verdict-line")
        yield Static(id="verdict-meter")
        yield Static(id="verdict-signals")

    def on_mount(self) -> None:
        self.show_empty()

    def show_empty(self) -> None:
        self.query_one("#verdict-line", Static).update(
            Text("No analysis yet.", style="dim")
        )
        self.query_one("#verdict-meter", Static).update("")
        self.query_one("#verdict-signals", Static).update(
            Text("Load text on the Input pane, then press Ctrl+R.", style="dim")
        )

    def update_analysis(self, analysis: Analysis) -> None:
        """Render *analysis* into the panel."""
        self._analysis = analysis
        synth = analysis.synthetic

        for candidate in ("good", "warn", "bad"):
            self.remove_class(candidate)
        self.add_class(VERDICT_CLASS[synth.verdict])

        colour = {
            "good": "green", "warn": "yellow", "bad": "red",
        }[VERDICT_CLASS[synth.verdict]]

        line = Text()
        line.append(synth.verdict.label, style=f"bold {colour}")
        line.append(f"    score {synth.score:.2f}", style="dim")
        line.append(f"    confidence {synth.confidence:.2f}", style="dim")
        line.append(f"    reliability {synth.reliability}", style="dim")
        self.query_one("#verdict-line", Static).update(line)
        self.query_one("#verdict-meter", Static).update(meter(synth.score))

        signals = Text()
        ranked = sorted(synth.signals, key=lambda s: -abs(s.weight))[:6]
        if not ranked:
            signals.append("No signals measured (text too short).", style="dim")
        for signal in ranked:
            if signal.direction == "synthetic":
                mark, style = "▲", "red"
            elif signal.direction == "human":
                mark, style = "▼", "green"
            else:
                mark, style = "·", "dim"
            signals.append(f"{mark} ", style=style)
            signals.append(f"{signal.label:<30}", style="default")
            value = "-" if signal.value is None else f"{signal.value:>9.3f}"
            signals.append(f"{value}   ", style="dim")
            signals.append(f"{signal.weight:+.2f}\n", style=style)
        signals.rstrip()
        self.query_one("#verdict-signals", Static).update(signals)


def meter(score: float, width: int = 40) -> Text:
    """A human→synthetic position meter."""
    position = max(0, min(width - 1, int(round(score * (width - 1)))))
    bar = Text()
    bar.append("human ", style="green")
    for index in range(width):
        if index == position:
            bar.append("●", style="bold white")
        else:
            ratio = index / max(1, width - 1)
            colour = "green" if ratio < 0.34 else ("yellow" if ratio < 0.67 else "red")
            bar.append("─", style=colour)
    bar.append(" synthetic", style="red")
    return bar


def severity_text(severity: Severity) -> Text:
    """Colour a severity name."""
    colour = {
        Severity.INFO: "dim",
        Severity.LOW: "dim",
        Severity.MEDIUM: "yellow",
        Severity.HIGH: "dark_orange",
        Severity.CRITICAL: "bold red",
    }[severity]
    return Text(severity.value, style=colour)


class Card(Widget):
    """A titled block of static content."""

    def __init__(
        self,
        title: str,
        body: str | Text = "",
        *,
        tone: str = "",
        id: Optional[str] = None,
    ) -> None:
        super().__init__(id=id, classes="card" + (f" {tone}" if tone else ""))
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="card-title")
        yield Static(self._body, id=f"{self.id or 'card'}-body", classes="scrolltext")

    def update_body(self, body: str | Text, tone: str = "") -> None:
        try:
            self.query_one(".scrolltext", Static).update(body)
        except Exception:
            return
        for candidate in ("danger", "good", "info"):
            self.remove_class(candidate)
        if tone:
            self.add_class(tone)

    def update_title(self, title: str) -> None:
        self._title = title
        try:
            self.query_one(".card-title", Static).update(title)
        except Exception:
            pass


def kv_text(rows: Sequence[Tuple[str, object]], key_width: int = 22) -> Text:
    """Format label/value rows into aligned text."""
    text = Text()
    for key, value in rows:
        text.append(f"{key:<{key_width}}", style="dim")
        if isinstance(value, Text):
            text.append_text(value)
            text.append("\n")
        else:
            text.append(f"{value}\n")
    text.rstrip()
    return text


def bullet_text(items: Iterable[str], *, style: str = "dim", marker: str = "•") -> Text:
    """Format an iterable as a bullet list."""
    text = Text()
    for item in items:
        text.append(f"{marker} ", style=style)
        text.append(f"{item}\n", style=style)
    text.rstrip()
    return text
