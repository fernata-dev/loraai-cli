"""Rich rendering for the command line.

All display goes through here so the visual language stays consistent across
commands, and so every piece of untrusted input passes through
:mod:`loraai.sanitize` on its way to the terminal exactly once.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ..analysis.provenance import REFERENCES
from ..diffing.engine import DiffResult
from ..models import (
    Analysis,
    CleanResult,
    HumanizeResult,
    Severity,
    UnicodeReport,
    Verdict,
)
from ..sanitize import one_line
from ..version import get_version

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

BRAND = "#8b85f0"
BRAND_DIM = "#6c66c9"
ACCENT = "#5ad6c4"
HUMAN = "#34d399"
NEUTRAL = "#fbbf24"
SYNTH = "#f87171"
MUTED = "#8b93a3"

SEVERITY_STYLE = {
    Severity.INFO: MUTED,
    Severity.LOW: MUTED,
    Severity.MEDIUM: NEUTRAL,
    Severity.HIGH: "#fb923c",
    Severity.CRITICAL: SYNTH,
}

VERDICT_STYLE = {
    Verdict.LIKELY_HUMAN: HUMAN,
    Verdict.LEANS_HUMAN: HUMAN,
    Verdict.INCONCLUSIVE: NEUTRAL,
    Verdict.LEANS_SYNTHETIC: "#fb923c",
    Verdict.LIKELY_SYNTHETIC: SYNTH,
}

_LOGO = r"""
 ██╗      ██████╗ ██████╗  █████╗      █████╗ ██╗
 ██║     ██╔═══██╗██╔══██╗██╔══██╗    ██╔══██╗██║
 ██║     ██║   ██║██████╔╝███████║    ███████║██║
 ██║     ██║   ██║██╔══██╗██╔══██║    ██╔══██║██║
 ███████╗╚██████╔╝██║  ██║██║  ██║    ██║  ██║██║
 ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝
"""

_GRADIENT = ["#6c66c9", "#7a73dd", "#8b85f0", "#9d97f5", "#5ad6c4", "#5ad6c4"]


def make_console(*, no_color: bool = False, quiet: bool = False) -> Console:
    """Build the shared console."""
    return Console(
        no_color=no_color,
        highlight=False,
        soft_wrap=False,
        quiet=quiet,
        emoji=False,
    )


def banner(console: Console, *, compact: bool = False) -> None:
    """Print the wordmark."""
    if compact:
        console.print(
            Text.assemble(
                ("loraai", f"bold {BRAND}"),
                ("  ", ""),
                (f"v{get_version()}", MUTED),
            )
        )
        return

    lines = [line for line in _LOGO.strip("\n").split("\n")]
    art = Text()
    for index, line in enumerate(lines):
        art.append(line + "\n", style=_GRADIENT[min(index, len(_GRADIENT) - 1)])
    art.rstrip()

    subtitle = Text.assemble(
        ("text forensics", ACCENT),
        ("  ·  ", MUTED),
        ("hidden-unicode detection", ACCENT),
        ("  ·  ", MUTED),
        ("writing analysis", ACCENT),
        ("  ·  ", MUTED),
        ("humanizer", ACCENT),
    )
    console.print(Align.left(Group(art, Text(""), Align.center(subtitle))))
    console.print()


def _bar(value: float, width: int = 28) -> Text:
    """A left-to-right human→synthetic meter."""
    position = max(0, min(width - 1, int(round(value * (width - 1)))))
    bar = Text()
    for index in range(width):
        if index == position:
            bar.append("●", style=f"bold {_score_style(value)}")
        else:
            ratio = index / max(1, width - 1)
            colour = HUMAN if ratio < 0.34 else (NEUTRAL if ratio < 0.67 else SYNTH)
            bar.append("─", style=colour)
    return bar


def _score_style(score: float) -> str:
    if score < 0.4:
        return HUMAN
    if score < 0.6:
        return NEUTRAL
    return SYNTH


def _kv_table(rows: Sequence[Tuple[str, Any]], *, key_style: str = MUTED) -> Table:
    table = Table(box=None, show_header=False, pad_edge=False, padding=(0, 2, 0, 0))
    table.add_column(style=key_style, no_wrap=True)
    table.add_column(style="default")
    for key, value in rows:
        table.add_row(str(key), str(value))
    return table


def section(title: str, renderable: RenderableType, *, style: str = BRAND) -> Panel:
    """Wrap a renderable in the standard section panel."""
    return Panel(
        renderable,
        title=Text(f" {title} ", style=f"bold {style}"),
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(1, 2),
    )


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


def render_verdict(analysis: Analysis) -> Panel:
    """The headline assessment panel."""
    synth = analysis.synthetic
    style = VERDICT_STYLE[synth.verdict]

    header = Text.assemble(
        (synth.verdict.label, f"bold {style}"),
        ("   ", ""),
        (f"score {synth.score:.2f}", MUTED),
        ("   ", ""),
        (f"confidence {synth.confidence:.2f}", MUTED),
        ("   ", ""),
        (f"reliability {synth.reliability}", MUTED),
    )

    meter = Text.assemble(
        ("human ", HUMAN), _bar(synth.score), (" synthetic", SYNTH)
    )

    body: List[RenderableType] = [header, Text(""), meter]

    if synth.signals:
        table = Table(
            box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False,
            header_style=f"bold {MUTED}", padding=(0, 1),
        )
        table.add_column("Signal", no_wrap=True)
        table.add_column("Value", justify="right", no_wrap=True)
        table.add_column("Weight", justify="right", no_wrap=True)
        table.add_column("Leans", no_wrap=True)
        for signal in sorted(synth.signals, key=lambda s: -abs(s.weight)):
            if signal.direction == "synthetic":
                mark, colour = "▲", SYNTH
            elif signal.direction == "human":
                mark, colour = "▼", HUMAN
            else:
                mark, colour = "·", MUTED
            label = signal.label + (" *" if signal.experimental else "")
            table.add_row(
                label,
                "-" if signal.value is None else f"{signal.value:.3f}",
                Text(f"{signal.weight:+.2f}", style=colour),
                Text(f"{mark} {signal.direction}", style=colour),
            )
        body.extend([Text(""), table])
        if any(s.experimental for s in synth.signals):
            body.append(Text("* experimental signal", style=MUTED))

    return section("SYNTHETIC-TEXT ASSESSMENT", Group(*body), style=style)


def render_caveats(analysis: Analysis) -> Optional[Panel]:
    """The always-on honesty panel."""
    caveats = analysis.synthetic.caveats
    if not caveats:
        return None
    text = Text()
    for caveat in caveats:
        text.append("• ", style=NEUTRAL)
        text.append(caveat + "\n", style=MUTED)
    text.rstrip()
    return section("HOW TO READ THIS", text, style=NEUTRAL)


# --------------------------------------------------------------------------
# Unicode
# --------------------------------------------------------------------------


def render_payloads(report: UnicodeReport) -> Optional[Panel]:
    """Decoded hidden payloads - the strongest finding the tool can make."""
    if not report.payloads:
        return None

    table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
    table.add_column("Scheme", no_wrap=True, style=ACCENT)
    table.add_column("Chars", justify="right", no_wrap=True)
    table.add_column("Offset", no_wrap=True, style=MUTED)
    table.add_column("Decoded content")
    for payload in report.payloads:
        table.add_row(
            payload.scheme,
            str(payload.char_count),
            f"{payload.start}-{payload.end}",
            Text(one_line(payload.decoded, 70), style=f"bold {SYNTH}"),
        )

    note = Text(
        "\nThis is a decode, not an inference. Readable data was recovered from "
        "characters that render as nothing, which means deliberate embedding.",
        style=MUTED,
    )
    return section("HIDDEN PAYLOAD DECODED", Group(table, note), style=SYNTH)


def render_unicode(report: UnicodeReport, *, limit: int = 20) -> Panel:
    """Unicode forensics summary and findings."""
    if not report.total:
        return section(
            "UNICODE FORENSICS",
            Text("No invisible, deceptive or control characters found.", style=HUMAN),
            style=HUMAN,
        )

    summary = _kv_table(
        [
            ("Findings", f"{report.total:,}"),
            ("Max severity", Text(report.max_severity.value.upper(),
                                  style=SEVERITY_STYLE[report.max_severity])),
            ("Hidden payloads", str(len(report.payloads))),
            ("Scripts", ", ".join(report.scripts) or "-"),
        ]
    )

    classes = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
    classes.add_column("Class", no_wrap=True)
    classes.add_column("Count", justify="right", no_wrap=True)
    for name, count in report.class_counts.items():
        classes.add_row(name, f"{count:,}")

    findings = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
    findings.add_column("Code", no_wrap=True, style=ACCENT)
    findings.add_column("Name", no_wrap=True)
    findings.add_column("Sev", no_wrap=True)
    findings.add_column("Pos", justify="right", no_wrap=True, style=MUTED)
    findings.add_column("Action", no_wrap=True)

    shown = sorted(
        report.findings, key=lambda f: (-f.severity.rank, f.position)
    )[:limit]
    for finding in shown:
        findings.add_row(
            finding.code,
            one_line(finding.name, 34),
            Text(finding.severity.value, style=SEVERITY_STYLE[finding.severity]),
            f"{finding.line}:{finding.column}",
            finding.recommended_action,
        )

    body: List[RenderableType] = [summary, Text(""), classes, Text(""), findings]
    if report.total > limit:
        body.append(
            Text(f"\n... and {report.total - limit:,} more finding(s).", style=MUTED)
        )
    if report.mixed_script_words:
        body.append(
            Text(
                "\nMixed-script words: "
                + ", ".join(one_line(w, 24) for w in report.mixed_script_words[:8]),
                style=NEUTRAL,
            )
        )
    for note in report.notes:
        body.append(Text(f"\n{note}", style=MUTED))

    return section(
        "UNICODE FORENSICS", Group(*body), style=SEVERITY_STYLE[report.max_severity]
    )


def render_provenance(analysis: Analysis) -> Panel:
    """The four-mechanism provenance table."""
    watermark = analysis.watermark
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
    table.add_column("Mechanism", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detectable locally", no_wrap=True)

    rows = [
        ("Invisible characters", watermark.invisible_characters["status"], True),
        ("Embedded payloads", watermark.embedded_payloads["status"], True),
        ("Statistical watermark", watermark.statistical_watermark["status"], False),
        ("File provenance (C2PA)", watermark.file_provenance["status"], True),
    ]
    for name, status, detectable in rows:
        found = status not in ("NONE FOUND", "NOT APPLICABLE", "NO MANIFEST FOUND")
        if not detectable:
            status_style = MUTED
        else:
            status_style = SYNTH if found else HUMAN
        table.add_row(
            name,
            Text(status, style=status_style),
            Text("yes — exact" if detectable else "no", style=HUMAN if detectable else MUTED),
        )

    explanation = Text()
    explanation.append("\nWhy the third row says no. ", style=f"bold {NEUTRAL}")
    explanation.append(
        watermark.statistical_watermark["reason"] + " ", style=MUTED
    )
    explanation.append(
        watermark.statistical_watermark["common_misconception"], style=MUTED
    )

    return section("PROVENANCE MARKING", Group(table, explanation), style=BRAND)


# --------------------------------------------------------------------------
# Statistics and markers
# --------------------------------------------------------------------------


def render_statistics(analysis: Analysis) -> Panel:
    """Counting and stylometric metrics side by side."""
    stats = analysis.statistics
    style = analysis.style

    left = _kv_table(
        [
            ("Characters", f"{stats.characters:,}"),
            ("Words", f"{stats.words:,}"),
            ("Unique words", f"{stats.unique_words:,}"),
            ("Sentences", f"{stats.sentences:,}"),
            ("Paragraphs", f"{stats.paragraphs:,}"),
            ("Reading time", f"{stats.reading_time_minutes:.1f} min"),
        ]
    )
    right = _kv_table(
        [
            ("Avg sentence", f"{stats.avg_sentence_length:.1f} words"),
            ("Sentence SD", f"{stats.sentence_length_stdev:.1f}"),
            ("Burstiness", f"{style.burstiness:+.3f}"),
            ("MATTR", f"{stats.moving_ttr:.3f}"),
            ("Lexical density", f"{style.lexical_density:.3f}"),
            ("Transitions/100w", f"{style.transition_density:.2f}"),
        ]
    )

    columns = Table(box=None, show_header=False, pad_edge=False, padding=(0, 4, 0, 0))
    columns.add_column()
    columns.add_column()
    columns.add_row(left, right)
    return section("TEXT STATISTICS", columns, style=ACCENT)


def render_markers(analysis: Analysis, *, limit: int = 15) -> Panel:
    """AI-writing tells."""
    markers = analysis.markers
    if not markers.total:
        return section(
            "AI-WRITING MARKERS",
            Text("No known AI-writing tells found.", style=HUMAN),
            style=HUMAN,
        )

    summary = _kv_table(
        [
            ("Markers", f"{markers.total:,}"),
            ("Per 1000 words", f"{markers.density_per_1k:.1f}"),
            ("Severity-weighted", f"{markers.weighted_density_per_1k:.1f}"),
            ("Categories", ", ".join(markers.category_counts) or "-"),
        ]
    )

    table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
    table.add_column("Line", justify="right", no_wrap=True, style=MUTED)
    table.add_column("Category", no_wrap=True)
    table.add_column("Matched")
    table.add_column("Suggestion", style=MUTED)

    for hit in markers.hits[:limit]:
        table.add_row(
            str(hit.line),
            Text(hit.category, style=SEVERITY_STYLE[hit.severity]),
            Text(one_line(hit.matched, 44)),
            one_line(hit.suggestion or "-", 30),
        )

    body: List[RenderableType] = [summary, Text(""), table]
    if markers.total > limit:
        body.append(Text(f"\n... and {markers.total - limit:,} more.", style=MUTED))
    return section("AI-WRITING MARKERS", Group(*body), style=NEUTRAL)


def render_source(analysis: Analysis) -> Panel:
    """Provenance of the input itself."""
    source = analysis.source
    return section(
        "SOURCE",
        _kv_table(
            [
                ("Origin", source.origin),
                ("Path", source.path or "-"),
                ("Encoding", source.encoding + (" + BOM" if source.had_bom else "")),
                ("Kind", source.content_kind),
                ("Language", source.language),
                ("Size", f"{source.size_bytes:,} bytes / {source.char_count:,} chars"),
                ("Scripts", ", ".join(f"{k} {v}" for k, v in
                                      list(source.script_mix.items())[:5]) or "-"),
            ]
        ),
        style=MUTED,
    )


def render_warnings(analysis: Analysis) -> Optional[Panel]:
    if not analysis.warnings:
        return None
    text = Text()
    for warning in analysis.warnings:
        text.append("! ", style=NEUTRAL)
        text.append(warning + "\n", style=MUTED)
    text.rstrip()
    return section("NOTES", text, style=NEUTRAL)


# --------------------------------------------------------------------------
# Clean / humanize / diff
# --------------------------------------------------------------------------


def render_clean(result: CleanResult, *, dry_run: bool = False) -> Panel:
    """Cleaning summary."""
    removed = sum(result.removed_counts.values())
    replaced = sum(result.replaced_counts.values())
    preserved = sum(result.preserved_counts.values())

    summary = _kv_table(
        [
            ("Profile", result.profile),
            ("Removed", f"{removed:,} character(s)"),
            ("Replaced", f"{replaced:,} character(s)"),
            ("Preserved", f"{preserved:,} character(s)"),
            (
                "Semantics",
                Text("PRESERVED", style=HUMAN)
                if result.semantic_preserved
                else Text("REVIEW", style=NEUTRAL),
            ),
            ("Length", f"{len(result.original):,} → {len(result.cleaned):,}"),
        ]
    )

    body: List[RenderableType] = [summary]

    if result.removed_counts or result.replaced_counts:
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
        table.add_column("Action", no_wrap=True)
        table.add_column("Code", no_wrap=True, style=ACCENT)
        table.add_column("Count", justify="right", no_wrap=True)
        for code, count in list(result.removed_counts.items())[:14]:
            table.add_row(Text("remove", style=SYNTH), code, str(count))
        for code, count in list(result.replaced_counts.items())[:14]:
            table.add_row(Text("replace", style=NEUTRAL), code, str(count))
        body.extend([Text(""), table])

    if result.semantic_notes:
        notes = Text()
        for note in result.semantic_notes:
            notes.append("\n• ", style=MUTED)
            notes.append(note, style=MUTED)
        body.append(notes)

    if dry_run:
        body.append(Text("\nDry run — nothing was written.", style=f"bold {NEUTRAL}"))

    title = "CLEAN (DRY RUN)" if dry_run else "CLEAN"
    return section(title, Group(*body), style=HUMAN if result.semantic_preserved else NEUTRAL)


def render_humanize(result: HumanizeResult) -> Panel:
    """Humanization summary."""
    delta = result.marker_before - result.marker_after
    summary = _kv_table(
        [
            ("Provider", result.provider),
            ("Style", result.style),
            ("Intensity", str(result.intensity)),
            (
                "AI markers",
                Text(
                    f"{result.marker_before} → {result.marker_after}"
                    + (f"  (−{delta})" if delta > 0 else ""),
                    style=HUMAN if delta > 0 else MUTED,
                ),
            ),
            ("Edits", f"{len(result.edits):,}"),
            ("Protected spans", f"{result.preserved_spans:,}"),
        ]
    )

    body: List[RenderableType] = [summary]

    if result.edits:
        table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {MUTED}")
        table.add_column("Category", no_wrap=True)
        table.add_column("Before")
        table.add_column("", no_wrap=True, style=MUTED)
        table.add_column("After")
        for edit in result.edits[:16]:
            table.add_row(
                Text(edit.category, style=ACCENT),
                Text(one_line(edit.before, 34), style=SYNTH),
                "→",
                Text(one_line(edit.after, 34) or "(removed)", style=HUMAN),
            )
        body.extend([Text(""), table])
        if len(result.edits) > 16:
            body.append(Text(f"\n... and {len(result.edits) - 16} more edit(s).",
                             style=MUTED))

    if result.notes:
        notes = Text()
        for note in result.notes:
            style = NEUTRAL if note.startswith("WARNING") else MUTED
            notes.append("\n• ", style=style)
            notes.append(note, style=style)
        body.append(notes)

    return section("HUMANIZE", Group(*body), style=BRAND)


def render_diff(result: DiffResult, *, limit: int = 60) -> Panel:
    """Inline diff with colour."""
    stats = result.stats
    summary = _kv_table(
        [
            ("Mode", result.mode),
            ("Words", f"{stats.words_before:,} → {stats.words_after:,}"),
            ("Unchanged", f"{stats.words_unchanged:,}"),
            ("Added", Text(f"+{stats.words_added:,}", style=HUMAN)),
            ("Removed", Text(f"−{stats.words_removed:,}", style=SYNTH)),
            ("Lines", f"+{stats.lines_added:,} / −{stats.lines_removed:,}"),
            ("Similarity", f"{stats.similarity:.1%}"),
        ]
    )

    # Deletions and insertions are bracketed as well as coloured: a word diff
    # with colour alone becomes unreadable the moment it is piped to a file or
    # viewed on a terminal without colour support.
    inline = Text()
    shown = 0
    for segment in result.segments:
        if segment.kind == "equal":
            inline.append(one_line(segment.before, 200))
            continue
        if shown >= limit:
            inline.append(" …", style=MUTED)
            break
        shown += 1
        if segment.before:
            inline.append(
                f"[-{one_line(segment.before, 120)}-]", style=f"{SYNTH} strike"
            )
        if segment.after:
            inline.append(f"{{+{one_line(segment.after, 120)}+}}", style=HUMAN)

    return section("DIFF", Group(summary, Text(""), inline), style=ACCENT)


def render_references() -> Panel:
    """Sources for the provenance claims, so the reader can check them."""
    text = Text()
    for title, url in REFERENCES:
        text.append(f"• {title}\n", style="default")
        text.append(f"  {url}\n", style=f"underline {ACCENT}")
    text.rstrip()
    return section("REFERENCES", text, style=MUTED)


def render_full(
    analysis: Analysis, *, verbose: bool = False, limit: int = 20
) -> List[RenderableType]:
    """The default `analyze` view, in reading order."""
    blocks: List[RenderableType] = [render_verdict(analysis)]

    payloads = render_payloads(analysis.unicode)
    if payloads is not None:
        blocks.append(payloads)

    blocks.append(render_unicode(analysis.unicode, limit=limit))
    blocks.append(render_markers(analysis, limit=limit))
    blocks.append(render_statistics(analysis))
    blocks.append(render_provenance(analysis))

    if verbose:
        blocks.append(render_source(analysis))
        blocks.append(render_references())

    warnings = render_warnings(analysis)
    if warnings is not None:
        blocks.append(warnings)

    caveats = render_caveats(analysis)
    if caveats is not None:
        blocks.append(caveats)

    return blocks
