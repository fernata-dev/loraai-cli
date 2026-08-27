"""The loraai terminal interface.

Layout: a brand bar, a sidebar of panes, and a content area. Each pane owns
one job and reads from the same shared state (``source_text``, ``analysis``),
so switching panes never re-runs work and the whole app stays in sync.

Analysis runs on a worker thread. Even though a typical document is analysed
in single-digit milliseconds, a large file should never freeze the interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.theme import Theme
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    Static,
    TextArea,
)

from .. import textio
from ..analysis import analyze as run_analysis
from ..analysis.provenance import summary_lines
from ..cleaning import clean as run_clean
from ..cleaning.rules import PROFILES
from ..config import Config
from ..diffing import diff as run_diff
from ..errors import LoraError
from ..humanize import humanize as run_humanize
from ..models import Analysis, CleanResult, HumanizeResult, Severity
from ..reports import render as render_report
from ..sanitize import one_line
from ..version import get_version
from .screens import (
    AboutScreen,
    ConfirmScreen,
    FilePickerScreen,
    HelpScreen,
    TextViewScreen,
)
from .widgets import Card, StatCard, VerdictPanel, bullet_text, kv_text, severity_text

PANES = [
    ("input", "Input", "1"),
    ("dashboard", "Dashboard", "2"),
    ("unicode", "Unicode", "3"),
    ("markers", "Markers", "4"),
    ("clean", "Clean", "5"),
    ("humanize", "Humanize", "6"),
    ("diff", "Diff", "7"),
    ("report", "Report", "8"),
    ("settings", "Settings", "9"),
]

_DARK = Theme(
    name="loraai-dark",
    primary="#8b85f0",
    secondary="#5ad6c4",
    accent="#5ad6c4",
    warning="#fbbf24",
    error="#f87171",
    success="#34d399",
    foreground="#e6e8ec",
    background="#0f1115",
    surface="#171a21",
    panel="#171a21",
    dark=True,
    variables={
        "brand": "#8b85f0",
        "brand-lighten-1": "#9d97f5",
        "text-muted": "#8b93a3",
    },
)

_LIGHT = Theme(
    name="loraai-light",
    primary="#4f46e5",
    secondary="#0d9488",
    accent="#0d9488",
    warning="#b45309",
    error="#be123c",
    success="#047857",
    foreground="#1a1d23",
    background="#ffffff",
    surface="#f4f5f8",
    panel="#f4f5f8",
    dark=False,
    variables={
        "brand": "#4f46e5",
        "brand-lighten-1": "#6366f1",
        "text-muted": "#5b6373",
    },
)


class LoraaiApp(App[None]):
    """The interactive interface."""

    CSS_PATH = "styles.tcss"
    TITLE = "loraai"
    SUB_TITLE = "text forensics & humanizer"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("f1", "help", "Help"),
        Binding("question_mark", "help", "Help", show=False),
        Binding("ctrl+r", "run_analysis", "Analyze"),
        Binding("ctrl+o", "open_file", "Open"),
        Binding("ctrl+l", "run_clean", "Clean"),
        Binding("ctrl+h", "run_humanize", "Humanize"),
        Binding("ctrl+s", "save_output", "Save"),
        Binding("ctrl+y", "copy_output", "Copy"),
        Binding("ctrl+t", "toggle_theme", "Theme"),
        Binding("f2", "about", "About", show=False),
        *[
            Binding(key, f"show_pane('{pane}')", label, show=False)
            for pane, label, key in PANES
        ],
    ]

    source_text: reactive[str] = reactive("", init=False)
    source_path: reactive[Optional[str]] = reactive(None, init=False)

    def __init__(
        self,
        config: Optional[Config] = None,
        initial_text: str = "",
        initial_path: Optional[str] = None,
    ) -> None:
        super().__init__()
        # Themes must be registered before the stylesheet is parsed, since the
        # CSS refers to their variables.
        self.register_theme(_DARK)
        self.register_theme(_LIGHT)
        self.config = config or Config()
        self._initial_text = initial_text
        self._initial_path = initial_path
        self.analysis: Optional[Analysis] = None
        self.clean_result: Optional[CleanResult] = None
        self.humanize_result: Optional[HumanizeResult] = None
        self._busy = False

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:
        with Horizontal(id="brandbar"):
            yield Static("◆ loraai", id="brandmark")
            yield Static(
                "text forensics · hidden unicode · writing analysis · humanizer",
                id="brandtag",
            )
            yield Static("no input", id="sourcechip")

        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("PANES", id="navtitle")
                yield ListView(
                    *[
                        ListItem(Label(f" {key}  {label}"), id=f"nav-{pane}")
                        for pane, label, key in PANES
                    ],
                    id="nav",
                )
            with VerticalScroll(id="content"):
                with ContentSwitcher(initial="input", id="switcher"):
                    yield from self._compose_panes()

        yield Footer()

    def _compose_panes(self) -> ComposeResult:
        # --- input ------------------------------------------------------
        with Vertical(id="input", classes="pane"):
            yield Static("INPUT", classes="pane-title")
            yield Static(
                "Paste or type text below, or load a file. Both routes feed "
                "every other pane.",
                classes="hint",
            )
            with Horizontal(classes="controls"):
                yield Input(placeholder="path/to/file.txt", id="path-field")
                yield Button("Load file", id="btn-load")
                yield Button("Browse", id="btn-browse")
            yield TextArea("", id="editor", soft_wrap=True)
            with Horizontal(classes="controls"):
                yield Button("Analyze  ^R", variant="primary", id="btn-analyze")
                yield Button("Clean  ^L", id="btn-clean-quick")
                yield Button("Humanize  ^H", id="btn-humanize-quick")
                yield Button("Clear", id="btn-clear")
            yield Card("STATUS", "Ready.", id="input-status")

        # --- dashboard --------------------------------------------------
        with Vertical(id="dashboard", classes="pane"):
            yield Static("DASHBOARD", classes="pane-title")
            yield VerdictPanel(id="verdict")
            with Horizontal(classes="statrow"):
                yield StatCard("WORDS", "-", id="s-words")
                yield StatCard("SENTENCES", "-", id="s-sentences")
                yield StatCard("HIDDEN CHARS", "-", id="s-hidden")
                yield StatCard("AI MARKERS", "-", id="s-markers")
            with Horizontal(classes="statrow"):
                yield StatCard("BURSTINESS", "-", id="s-burst")
                yield StatCard("MATTR", "-", id="s-mattr")
                yield StatCard("LANGUAGE", "-", id="s-lang")
                yield StatCard("PAYLOADS", "-", id="s-payloads")
            yield Card("PROVENANCE MARKING", "", id="dash-provenance", tone="info")
            yield Card("HOW TO READ THIS", "", id="dash-caveats")

        # --- unicode ----------------------------------------------------
        with Vertical(id="unicode", classes="pane"):
            yield Static("UNICODE FORENSICS", classes="pane-title")
            yield Static(
                "Exact detection: these characters are physically present in "
                "the input.",
                classes="hint",
            )
            yield Card("HIDDEN PAYLOADS", "No analysis yet.", id="uni-payloads")
            yield DataTable(id="uni-table", zebra_stripes=True, cursor_type="row")
            yield Card("DETAIL", "Select a row to see the full explanation.",
                       id="uni-detail")

        # --- markers ----------------------------------------------------
        with Vertical(id="markers", classes="pane"):
            yield Static("AI-WRITING MARKERS", classes="pane-title")
            yield Static(
                "Style habits that appear far more often in generated prose. "
                "Suggestive, never conclusive.",
                classes="hint",
            )
            yield DataTable(id="mark-table", zebra_stripes=True, cursor_type="row")
            yield Card("DETAIL", "Select a row to see the explanation.",
                       id="mark-detail")

        # --- clean ------------------------------------------------------
        with Vertical(id="clean", classes="pane"):
            yield Static("CLEAN", classes="pane-title")
            yield Static(
                "Remove invisible and deceptive characters. The safe profile "
                "preserves Arabic joiners, diacritics and emoji sequences.",
                classes="hint",
            )
            with Horizontal(classes="controls"):
                yield Static("Profile", classes="field-label")
                yield Select(
                    [(name, name) for name in sorted(PROFILES)],
                    value=self.config.clean.profile,
                    allow_blank=False,
                    id="clean-profile",
                )
                yield Button("Run clean", variant="primary", id="btn-clean")
                yield Button("Use as input", id="btn-clean-adopt")
            yield Card("SUMMARY", "Not run yet.", id="clean-summary")
            yield TextArea("", id="clean-output", read_only=True,
                           soft_wrap=True, classes="output-area")

        # --- humanize ---------------------------------------------------
        with Vertical(id="humanize", classes="pane"):
            yield Static("HUMANIZE", classes="pane-title")
            yield Static(
                "Rewrite to read naturally: strips invisible characters, "
                "assistant phrasing, inflated vocabulary and mechanical rhythm. "
                "Code, URLs and citations are preserved exactly.",
                classes="hint",
            )
            with Horizontal(classes="controls"):
                yield Static("Style", classes="field-label")
                yield Select(
                    [
                        ("natural", "natural"),
                        ("concise", "concise"),
                        ("professional", "professional"),
                        ("academic", "academic"),
                        ("conversational", "conversational"),
                    ],
                    value=self.config.humanize.style,
                    allow_blank=False,
                    id="hum-style",
                )
                yield Static("Intensity", classes="field-label")
                yield Select(
                    [("1 light", 1), ("2 moderate", 2), ("3 thorough", 3)],
                    value=self.config.humanize.intensity,
                    allow_blank=False,
                    id="hum-intensity",
                )
                yield Button("Run", variant="primary", id="btn-humanize")
                yield Button("Use as input", id="btn-hum-adopt")
            yield Card("SUMMARY", "Not run yet.", id="hum-summary")
            yield TextArea("", id="hum-output", read_only=True,
                           soft_wrap=True, classes="output-area")

        # --- diff -------------------------------------------------------
        with Vertical(id="diff", classes="pane"):
            yield Static("DIFF", classes="pane-title")
            yield Static(
                "Compare the current input against the latest clean or "
                "humanize result.",
                classes="hint",
            )
            with Horizontal(classes="controls"):
                yield Static("Against", classes="field-label")
                yield Select(
                    [("humanize result", "humanize"), ("clean result", "clean")],
                    value="humanize",
                    allow_blank=False,
                    id="diff-target",
                )
                yield Static("Mode", classes="field-label")
                yield Select(
                    [("word", "word"), ("line", "line"), ("char", "char")],
                    value="word",
                    allow_blank=False,
                    id="diff-mode",
                )
                yield Button("Compare", variant="primary", id="btn-diff")
            yield Card("STATISTICS", "Not run yet.", id="diff-stats")
            yield Card("CHANGES", "", id="diff-body")

        # --- report -----------------------------------------------------
        with Vertical(id="report", classes="pane"):
            yield Static("REPORT", classes="pane-title")
            yield Static(
                "Export the full analysis. HTML and JSON are self-contained "
                "and need no network.",
                classes="hint",
            )
            with Horizontal(classes="controls"):
                yield Static("Format", classes="field-label")
                yield Select(
                    [("json", "json"), ("html", "html"), ("markdown", "markdown")],
                    value="html",
                    allow_blank=False,
                    id="report-format",
                )
                yield Input(placeholder="output path…", id="report-path")
                yield Button("Export", variant="primary", id="btn-report")
                yield Button("Preview", id="btn-report-preview")
            yield Card("STATUS", "Run an analysis first.", id="report-status")

        # --- settings ---------------------------------------------------
        with Vertical(id="settings", classes="pane"):
            yield Static("SETTINGS", classes="pane-title")
            yield Card("ACTIVE CONFIGURATION", "", id="settings-body")
            yield Card("PROVIDERS", "", id="settings-providers")
            with Horizontal(classes="controls"):
                yield Button("Toggle theme  ^T", id="btn-theme")
                yield Button("About", id="btn-about")
                yield Button("Help  F1", id="btn-help")

    # -------------------------------------------------------------- setup

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Fallback values for the custom variables the stylesheet references.

        Textual resolves CSS variables when the stylesheet is parsed, which
        happens before any theme is applied. Without defaults here, a
        stylesheet referencing ``$brand`` fails to parse at startup.
        """
        return {
            "brand": "#8b85f0",
            "brand-lighten-1": "#9d97f5",
            "text-muted": "#8b93a3",
        }

    def on_mount(self) -> None:
        self.theme = (
            self.config.tui.theme
            if self.config.tui.theme in ("loraai-dark", "loraai-light")
            else "loraai-dark"
        )

        table = self.query_one("#uni-table", DataTable)
        table.add_columns("Code", "Name", "Severity", "Line:Col", "Action")

        markers_table = self.query_one("#mark-table", DataTable)
        markers_table.add_columns("Line", "Category", "Matched", "Suggestion")

        self._refresh_settings()

        if self._initial_text:
            self.query_one("#editor", TextArea).load_text(self._initial_text)
            self.source_text = self._initial_text
            self.source_path = self._initial_path
            if self._initial_path:
                self.query_one("#path-field", Input).value = self._initial_path
            self.action_run_analysis()
        else:
            self._set_status(
                "Paste text into the editor, or press Ctrl+O to open a file."
            )

    # ------------------------------------------------------------ helpers

    def _set_status(self, message: str, tone: str = "") -> None:
        self.query_one("#input-status", Card).update_body(message, tone)

    def _set_chip(self) -> None:
        chip = self.query_one("#sourcechip", Static)
        if not self.source_text:
            chip.update("no input")
            return
        label = Path(self.source_path).name if self.source_path else "direct text"
        chip.update(f"{label} · {len(self.source_text):,} chars")

    def _current_text(self) -> str:
        """The editor is the single source of truth for input."""
        return self.query_one("#editor", TextArea).text

    def _require_text(self) -> Optional[str]:
        text = self._current_text()
        if not text.strip():
            self.notify(
                "No input yet. Paste text or open a file first.",
                severity="warning",
                title="Nothing to do",
            )
            self.action_show_pane("input")
            return None
        return text

    def _language(self, fallback: str = "en") -> str:
        if self.analysis:
            language = self.analysis.source.language
        else:
            from ..unicode_data.scripts import dominant_language

            language = dominant_language(self._current_text())
        return language if language in ("en", "ar", "mixed") else fallback

    # ------------------------------------------------------------ actions

    def action_show_pane(self, pane: str) -> None:
        self.query_one("#switcher", ContentSwitcher).current = pane
        nav = self.query_one("#nav", ListView)
        for index, (name, _label, _key) in enumerate(PANES):
            if name == pane:
                nav.index = index
                break

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_about(self) -> None:
        self.push_screen(AboutScreen())

    def action_toggle_theme(self) -> None:
        self.theme = (
            "loraai-light" if self.theme == "loraai-dark" else "loraai-dark"
        )

    def action_open_file(self) -> None:
        def handle(path: Optional[str]) -> None:
            if path:
                self._load_file(path)

        self.push_screen(FilePickerScreen(), handle)

    def action_run_analysis(self) -> None:
        text = self._require_text()
        if text is None:
            return
        if self._busy:
            self.notify("Already working.", severity="warning")
            return
        self.source_text = text
        self._set_status("Analyzing…")
        self._analyze_worker(text, self.source_path)

    def action_run_clean(self) -> None:
        text = self._require_text()
        if text is None:
            return
        profile = self.query_one("#clean-profile", Select).value
        try:
            result = run_clean(text, str(profile))
        except Exception as exc:  # pragma: no cover - defensive
            self.notify(f"Clean failed: {exc}", severity="error")
            return
        self.clean_result = result
        self._render_clean(result)
        self.action_show_pane("clean")
        self.notify(
            f"Removed {sum(result.removed_counts.values())} character(s).",
            title="Clean complete",
        )

    def action_run_humanize(self) -> None:
        text = self._require_text()
        if text is None:
            return
        style = str(self.query_one("#hum-style", Select).value)
        intensity = int(self.query_one("#hum-intensity", Select).value)
        try:
            result = run_humanize(
                text,
                language=self._language(),
                style=style,
                intensity=intensity,
                clean_invisible=self.config.humanize.clean_first,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.notify(f"Humanize failed: {exc}", severity="error")
            return
        self.humanize_result = result
        self._render_humanize(result)
        self.action_show_pane("humanize")
        self.notify(
            f"AI markers {result.marker_before} → {result.marker_after}.",
            title="Humanize complete",
        )

    def _active_output(self) -> tuple[str, str]:
        """The text the save/copy actions act on, based on the visible pane."""
        current = self.query_one("#switcher", ContentSwitcher).current
        if current == "humanize" and self.humanize_result:
            return self.humanize_result.result, "humanized"
        if current == "clean" and self.clean_result:
            return self.clean_result.cleaned, "cleaned"
        if current == "report" and self.analysis:
            fmt = str(self.query_one("#report-format", Select).value)
            return render_report(self.analysis, fmt), f"report.{fmt}"
        return self._current_text(), "input"

    def action_copy_output(self) -> None:
        content, label = self._active_output()
        if not content:
            self.notify("Nothing to copy.", severity="warning")
            return
        try:
            self.copy_to_clipboard(content)
        except Exception as exc:
            self.notify(f"Clipboard unavailable: {exc}", severity="error")
            return
        self.notify(f"Copied {len(content):,} characters ({label}).")

    def action_save_output(self) -> None:
        content, label = self._active_output()
        if not content:
            self.notify("Nothing to save.", severity="warning")
            return

        default = self.query_one("#report-path", Input).value.strip()
        if not default:
            stem = Path(self.source_path).stem if self.source_path else "loraai"
            suffix = {
                "humanized": ".humanized.txt",
                "cleaned": ".cleaned.txt",
                "input": ".txt",
            }.get(label, f".{label.split('.')[-1]}")
            default = f"{stem}{suffix}"

        def handle(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                target = Path(default).expanduser()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            except OSError as exc:
                self.notify(f"Could not write: {exc}", severity="error")
                return
            self.notify(f"Wrote {target} ({len(content):,} bytes).", title="Saved")

        exists = Path(default).expanduser().exists()
        self.push_screen(
            ConfirmScreen(
                f"Save {label} to {default}?",
                "This file already exists and will be overwritten."
                if exists
                else "Set a different path on the Report pane if you want another "
                     "location.",
            ),
            handle,
        )

    # ------------------------------------------------------------- worker

    @work(thread=True, exclusive=True)
    def _analyze_worker(self, text: str, path: Optional[str]) -> None:
        self._busy = True
        try:
            loaded = textio.from_text(text)
            if path:
                loaded.source.path = path
                loaded.source.origin = "file"
            result = run_analysis(
                loaded,
                decode_hidden=self.config.analysis.decode_hidden_payloads,
                prose_from_code=self.config.analysis.prose_from_code,
            )
        except Exception as exc:
            self.call_from_thread(
                self.notify, f"Analysis failed: {exc}", severity="error"
            )
            self.call_from_thread(self._set_status, f"Analysis failed: {exc}", "danger")
            return
        finally:
            self._busy = False
        self.call_from_thread(self._render_analysis, result)

    # ------------------------------------------------------------ renders

    def _render_analysis(self, analysis: Analysis) -> None:
        self.analysis = analysis
        stats = analysis.statistics
        unicode_report = analysis.unicode

        self.query_one("#verdict", VerdictPanel).update_analysis(analysis)

        hidden = sum(
            unicode_report.class_counts.get(name, 0)
            for name in ("zero-width", "tag-character", "variation-selector",
                         "invisible-math", "invisible-format")
        )
        self.query_one("#s-words", StatCard).update_value(f"{stats.words:,}")
        self.query_one("#s-sentences", StatCard).update_value(f"{stats.sentences:,}")
        self.query_one("#s-hidden", StatCard).update_value(
            f"{hidden:,}", "bad" if hidden else "good"
        )
        self.query_one("#s-markers", StatCard).update_value(
            f"{analysis.markers.total:,}", "warn" if analysis.markers.total else "good"
        )
        self.query_one("#s-burst", StatCard).update_value(
            f"{analysis.style.burstiness:+.3f}"
        )
        self.query_one("#s-mattr", StatCard).update_value(f"{stats.moving_ttr:.3f}")
        self.query_one("#s-lang", StatCard).update_value(analysis.source.language)
        payload_count = len(unicode_report.payloads)
        self.query_one("#s-payloads", StatCard).update_value(
            str(payload_count), "bad" if payload_count else "good"
        )

        provenance = Text()
        for line in summary_lines(analysis.watermark):
            provenance.append(line + "\n")
        provenance.append(
            "\n" + analysis.watermark.statistical_watermark["common_misconception"],
            style="dim",
        )
        self.query_one("#dash-provenance", Card).update_body(provenance)

        self.query_one("#dash-caveats", Card).update_body(
            bullet_text(analysis.synthetic.caveats)
        )

        # --- unicode table ---------------------------------------------
        table = self.query_one("#uni-table", DataTable)
        table.clear()
        for finding in sorted(
            unicode_report.findings, key=lambda f: (-f.severity.rank, f.position)
        )[:400]:
            table.add_row(
                finding.code,
                one_line(finding.name, 38),
                severity_text(finding.severity),
                f"{finding.line}:{finding.column}",
                finding.recommended_action,
                key=str(finding.position),
            )

        payload_card = self.query_one("#uni-payloads", Card)
        if unicode_report.payloads:
            body = Text()
            body.append(
                "Readable data was recovered from characters that render as "
                "nothing. This is a decode, not an inference.\n\n",
                style="bold red",
            )
            for payload in unicode_report.payloads:
                body.append(f"{payload.scheme}  ", style="cyan")
                body.append(f"({payload.char_count} chars @ {payload.start})\n",
                            style="dim")
                body.append(f"  {one_line(payload.decoded, 200)}\n\n", style="bold")
            payload_card.update_body(body, "danger")
            payload_card.update_title("HIDDEN PAYLOADS — DECODED")
        else:
            payload_card.update_body(
                Text("No hidden payload decoded from invisible characters.",
                     style="green"),
                "good",
            )
            payload_card.update_title("HIDDEN PAYLOADS")

        self.query_one("#uni-detail", Card).update_body(
            kv_text(
                [
                    ("Total findings", f"{unicode_report.total:,}"),
                    ("Max severity", unicode_report.max_severity.value),
                    ("Scripts", ", ".join(unicode_report.scripts) or "-"),
                    ("Mixed-script words",
                     ", ".join(unicode_report.mixed_script_words[:6]) or "none"),
                    ("Normalization",
                     unicode_report.normalization.get("note", "-")),
                ]
            )
        )

        # --- markers table ---------------------------------------------
        markers_table = self.query_one("#mark-table", DataTable)
        markers_table.clear()
        for index, hit in enumerate(analysis.markers.hits[:400]):
            markers_table.add_row(
                str(hit.line),
                hit.category,
                one_line(hit.matched, 44),
                one_line(hit.suggestion or "-", 34),
                key=str(index),
            )
        self.query_one("#mark-detail", Card).update_body(
            kv_text(
                [
                    ("Markers", f"{analysis.markers.total:,}"),
                    ("Per 1000 words", f"{analysis.markers.density_per_1k:.1f}"),
                    ("Severity-weighted",
                     f"{analysis.markers.weighted_density_per_1k:.1f}"),
                    ("Categories",
                     ", ".join(analysis.markers.category_counts) or "-"),
                ]
            )
        )

        self.query_one("#report-status", Card).update_body(
            f"Analysis ready ({analysis.elapsed_ms:.1f} ms). Choose a format and "
            f"press Export."
        )

        self._set_chip()
        warnings = (
            "\n".join(f"! {w}" for w in analysis.warnings) if analysis.warnings else ""
        )
        self._set_status(
            f"Analyzed {stats.words:,} words in {analysis.elapsed_ms:.1f} ms. "
            f"{unicode_report.total} unicode finding(s), "
            f"{analysis.markers.total} marker(s)."
            + (f"\n\n{warnings}" if warnings else ""),
            "good" if not unicode_report.payloads else "danger",
        )
        self.action_show_pane("dashboard")

    def _render_clean(self, result: CleanResult) -> None:
        removed = sum(result.removed_counts.values())
        replaced = sum(result.replaced_counts.values())
        body = kv_text(
            [
                ("Profile", result.profile),
                ("Removed", f"{removed:,} character(s)"),
                ("Replaced", f"{replaced:,} character(s)"),
                (
                    "Semantics",
                    Text("PRESERVED", style="green")
                    if result.semantic_preserved
                    else Text("REVIEW", style="yellow"),
                ),
                ("Length", f"{len(result.original):,} → {len(result.cleaned):,}"),
            ]
        )
        if result.removed_counts:
            body.append("\n\nRemoved: ", style="dim")
            body.append(
                ", ".join(
                    f"{code}×{count}"
                    for code, count in list(result.removed_counts.items())[:12]
                )
            )
        body.append("\n\n")
        body.append_text(bullet_text(result.semantic_notes))
        self.query_one("#clean-summary", Card).update_body(
            body, "good" if result.semantic_preserved else "danger"
        )
        self.query_one("#clean-output", TextArea).load_text(result.cleaned)

    def _render_humanize(self, result: HumanizeResult) -> None:
        delta = result.marker_before - result.marker_after
        body = kv_text(
            [
                ("Provider", result.provider),
                ("Style", result.style),
                ("Intensity", str(result.intensity)),
                (
                    "AI markers",
                    Text(
                        f"{result.marker_before} → {result.marker_after}"
                        + (f"  (−{delta})" if delta > 0 else ""),
                        style="green" if delta > 0 else "dim",
                    ),
                ),
                ("Edits", f"{len(result.edits):,}"),
                ("Protected spans", f"{result.preserved_spans:,}"),
            ]
        )
        if result.edits:
            body.append("\n\nEdits\n", style="bold")
            for edit in result.edits[:12]:
                body.append(f"  {edit.category:<16}", style="cyan")
                body.append(one_line(edit.before, 30), style="red")
                body.append("  →  ", style="dim")
                body.append(f"{one_line(edit.after, 30) or '(removed)'}\n",
                            style="green")
            if len(result.edits) > 12:
                body.append(f"  … and {len(result.edits) - 12} more\n", style="dim")
        body.append("\n")
        body.append_text(bullet_text(result.notes))
        self.query_one("#hum-summary", Card).update_body(body)
        self.query_one("#hum-output", TextArea).load_text(result.result)

    def _refresh_settings(self) -> None:
        from ..humanize.providers import available_providers

        config = self.config
        self.query_one("#settings-body", Card).update_body(
            kv_text(
                [
                    ("Source", config.source_path or "built-in defaults"),
                    ("Language", config.general.language),
                    ("Max input", f"{config.general.max_bytes:,} bytes"),
                    ("Clean profile", config.clean.profile),
                    ("Humanize style", config.humanize.style),
                    ("Humanize intensity", str(config.humanize.intensity)),
                    ("Humanize provider", config.humanize.provider),
                    ("Theme", config.tui.theme),
                    ("Version", get_version()),
                ]
            )
        )
        providers = Text()
        for provider in available_providers():
            state = "configured" if provider["configured"] else "not configured"
            style = "green" if provider["configured"] else "dim"
            providers.append(f"{provider['name']:<12}", style="cyan")
            providers.append(f"{provider['model']:<30}", style="default")
            providers.append(f"{state}\n", style=style)
        providers.append(
            "\nAPI keys are read from environment variables and never written "
            "to the config file.",
            style="dim",
        )
        self.query_one("#settings-providers", Card).update_body(providers)

    # ------------------------------------------------------------- events

    def _load_file(self, path: str) -> None:
        try:
            loaded = textio.from_file(path, max_bytes=self.config.general.max_bytes)
        except LoraError as error:
            self.notify(
                f"{error.message}\n{error.hint or ''}".strip(),
                severity="error",
                title="Could not open file",
            )
            self._set_status(f"{error.message}", "danger")
            return
        self.query_one("#editor", TextArea).load_text(loaded.text)
        self.query_one("#path-field", Input).value = str(path)
        self.source_text = loaded.text
        self.source_path = loaded.source.path
        self._set_chip()
        self._set_status(
            f"Loaded {loaded.source.path} — {loaded.source.size_bytes:,} bytes, "
            f"{loaded.source.encoding}, {loaded.source.content_kind}."
        )
        self.action_run_analysis()

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        handlers = {
            "btn-analyze": self.action_run_analysis,
            "btn-clean": self.action_run_clean,
            "btn-clean-quick": self.action_run_clean,
            "btn-humanize": self.action_run_humanize,
            "btn-humanize-quick": self.action_run_humanize,
            "btn-browse": self.action_open_file,
            "btn-theme": self.action_toggle_theme,
            "btn-about": self.action_about,
            "btn-help": self.action_help,
            "btn-diff": self._do_diff,
            "btn-report": self._do_report,
            "btn-report-preview": self._do_report_preview,
            "btn-clear": self._do_clear,
            "btn-load": self._do_load_from_field,
            "btn-clean-adopt": self._adopt_clean,
            "btn-hum-adopt": self._adopt_humanize,
        }
        handler = handlers.get(event.button.id or "")
        if handler is not None:
            event.stop()
            handler()

    def _do_load_from_field(self) -> None:
        path = self.query_one("#path-field", Input).value.strip()
        if not path:
            self.notify("Enter a path, or press Browse.", severity="warning")
            return
        self._load_file(path)

    def _do_clear(self) -> None:
        self.query_one("#editor", TextArea).load_text("")
        self.query_one("#path-field", Input).value = ""
        self.source_text = ""
        self.source_path = None
        self.analysis = None
        self.clean_result = None
        self.humanize_result = None
        self.query_one("#verdict", VerdictPanel).show_empty()
        self.query_one("#uni-table", DataTable).clear()
        self.query_one("#mark-table", DataTable).clear()
        self._set_chip()
        self._set_status("Cleared.")

    def _adopt_clean(self) -> None:
        if not self.clean_result:
            self.notify("Run clean first.", severity="warning")
            return
        self.query_one("#editor", TextArea).load_text(self.clean_result.cleaned)
        self.notify("Cleaned text is now the input.")
        self.action_run_analysis()

    def _adopt_humanize(self) -> None:
        if not self.humanize_result:
            self.notify("Run humanize first.", severity="warning")
            return
        self.query_one("#editor", TextArea).load_text(self.humanize_result.result)
        self.notify("Humanized text is now the input.")
        self.action_run_analysis()

    def _do_diff(self) -> None:
        target = str(self.query_one("#diff-target", Select).value)
        mode = str(self.query_one("#diff-mode", Select).value)

        if target == "humanize":
            if not self.humanize_result:
                self.notify("Run humanize first.", severity="warning")
                return
            before, after = self.humanize_result.original, self.humanize_result.result
        else:
            if not self.clean_result:
                self.notify("Run clean first.", severity="warning")
                return
            before, after = self.clean_result.original, self.clean_result.cleaned

        result = run_diff(before, after, mode=mode,
                          label_before="original", label_after=target)
        stats = result.stats
        self.query_one("#diff-stats", Card).update_body(
            kv_text(
                [
                    ("Mode", result.mode),
                    ("Words", f"{stats.words_before:,} → {stats.words_after:,}"),
                    ("Unchanged", f"{stats.words_unchanged:,}"),
                    ("Added", Text(f"+{stats.words_added:,}", style="green")),
                    ("Removed", Text(f"−{stats.words_removed:,}", style="red")),
                    ("Similarity", f"{stats.similarity:.1%}"),
                ]
            )
        )

        body = Text()
        shown = 0
        for segment in result.segments:
            if segment.kind == "equal":
                body.append(one_line(segment.before, 300))
                continue
            if shown >= 120:
                body.append(" …", style="dim")
                break
            shown += 1
            if segment.before:
                body.append(f"[-{one_line(segment.before, 80)}-]", style="red strike")
            if segment.after:
                body.append(f"{{+{one_line(segment.after, 80)}+}}", style="green")
        self.query_one("#diff-body", Card).update_body(body)
        self.action_show_pane("diff")

    def _do_report(self) -> None:
        if not self.analysis:
            self.notify("Run an analysis first (Ctrl+R).", severity="warning")
            return
        fmt = str(self.query_one("#report-format", Select).value)
        path = self.query_one("#report-path", Input).value.strip()
        if not path:
            stem = Path(self.source_path).stem if self.source_path else "loraai"
            extension = {"markdown": "md"}.get(fmt, fmt)
            path = f"{stem}.report.{extension}"

        try:
            content = render_report(
                self.analysis, fmt,
                clean=self.clean_result, humanize=self.humanize_result,
            )
            target = Path(path).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except (OSError, ValueError) as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            self.query_one("#report-status", Card).update_body(
                f"Export failed: {exc}", "danger"
            )
            return

        self.query_one("#report-status", Card).update_body(
            f"Wrote {target} ({len(content):,} bytes, {fmt}).", "good"
        )
        self.notify(f"Wrote {target}.", title="Report exported")

    def _do_report_preview(self) -> None:
        if not self.analysis:
            self.notify("Run an analysis first (Ctrl+R).", severity="warning")
            return
        fmt = str(self.query_one("#report-format", Select).value)
        content = render_report(
            self.analysis, fmt, clean=self.clean_result, humanize=self.humanize_result
        )
        self.push_screen(
            TextViewScreen(f"Report preview ({fmt})", content[:20000])
        )

    @on(ListView.Highlighted, "#nav")
    def _on_nav(self, event: ListView.Highlighted) -> None:
        if event.item is None or not event.item.id:
            return
        pane = event.item.id.removeprefix("nav-")
        self.query_one("#switcher", ContentSwitcher).current = pane

    @on(DataTable.RowHighlighted, "#uni-table")
    def _on_unicode_row(self, event: DataTable.RowHighlighted) -> None:
        if not self.analysis or event.row_key.value is None:
            return
        position = int(event.row_key.value)
        finding = next(
            (f for f in self.analysis.unicode.findings if f.position == position), None
        )
        if finding is None:
            return
        self.query_one("#uni-detail", Card).update_body(
            kv_text(
                [
                    ("Code point", finding.code),
                    ("Name", finding.name),
                    ("Category", finding.category),
                    ("Class", finding.char_class.value),
                    ("Severity", severity_text(finding.severity)),
                    ("Position", f"offset {finding.position}, "
                                 f"line {finding.line}, column {finding.column}"),
                    ("Action", finding.recommended_action),
                    ("Context", finding.context),
                    ("Why", finding.note),
                ]
            ),
            "danger" if finding.severity.rank >= Severity.HIGH.rank else "",
        )

    @on(DataTable.RowHighlighted, "#mark-table")
    def _on_marker_row(self, event: DataTable.RowHighlighted) -> None:
        if not self.analysis or event.row_key.value is None:
            return
        index = int(event.row_key.value)
        hits = self.analysis.markers.hits
        if index >= len(hits):
            return
        hit = hits[index]
        self.query_one("#mark-detail", Card).update_body(
            kv_text(
                [
                    ("Rule", hit.rule_id),
                    ("Category", hit.category),
                    ("Severity", severity_text(hit.severity)),
                    ("Line", str(hit.line)),
                    ("Matched", one_line(hit.matched, 120)),
                    ("Suggestion", hit.suggestion or "-"),
                    ("Why", hit.explanation),
                ]
            )
        )

    @on(TextArea.Changed, "#editor")
    def _on_editor_changed(self, event: TextArea.Changed) -> None:
        self.source_text = event.text_area.text
        self._set_chip()
