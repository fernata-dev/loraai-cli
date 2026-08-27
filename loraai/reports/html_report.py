"""Self-contained HTML reports.

No external requests of any kind: all CSS is inline, there are no fonts,
scripts or images to fetch. A report can be opened from a USB stick on an
air-gapped machine and look identical.

Respects the reader's colour scheme via ``prefers-color-scheme``.
"""

from __future__ import annotations

import html
from typing import List, Optional

from ..analysis.provenance import REFERENCES
from ..models import Analysis, CleanResult, HumanizeResult, Severity, Verdict
from ..sanitize import one_line, redact_secrets
from ..version import get_version

_SEVERITY_CLASS = {
    Severity.INFO: "sev-info",
    Severity.LOW: "sev-low",
    Severity.MEDIUM: "sev-medium",
    Severity.HIGH: "sev-high",
    Severity.CRITICAL: "sev-critical",
}

_VERDICT_CLASS = {
    Verdict.LIKELY_HUMAN: "v-human",
    Verdict.LEANS_HUMAN: "v-human",
    Verdict.INCONCLUSIVE: "v-neutral",
    Verdict.LEANS_SYNTHETIC: "v-synth",
    Verdict.LIKELY_SYNTHETIC: "v-synth",
}

_CSS = """
:root {
  --bg: #ffffff; --panel: #f7f8fa; --border: #e2e5ea; --fg: #1a1d23;
  --muted: #646b78; --accent: #4f46e5;
  --human: #0f8a5f; --neutral: #b0741a; --synth: #c2344d;
  --info: #6b7280; --low: #6b7280; --medium: #b0741a;
  --high: #d4622a; --critical: #c2344d;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #262b35; --fg: #e6e8ec;
    --muted: #9aa2b1; --accent: #8b85f0;
    --human: #34d399; --neutral: #fbbf24; --synth: #f87171;
    --info: #9aa2b1; --low: #9aa2b1; --medium: #fbbf24;
    --high: #fb923c; --critical: #f87171;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--fg);
  font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
}
.wrap { max-width: 62rem; margin: 0 auto; }
header { border-bottom: 2px solid var(--border); padding-bottom: 1rem;
         margin-bottom: 2rem; }
h1 { font-size: 1.6rem; margin: 0 0 .25rem; letter-spacing: -.02em; }
h2 { font-size: 1.15rem; margin: 2.5rem 0 .85rem; padding-bottom: .4rem;
     border-bottom: 1px solid var(--border); letter-spacing: -.01em; }
h3 { font-size: .95rem; margin: 1.5rem 0 .6rem; color: var(--muted);
     text-transform: uppercase; letter-spacing: .06em; }
.sub { color: var(--muted); font-size: .875rem; }
.verdict { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem;
           background: var(--panel); border: 1px solid var(--border);
           border-left: 4px solid var(--neutral); border-radius: 8px;
           padding: 1.1rem 1.25rem; margin: 1rem 0; }
.verdict.v-human { border-left-color: var(--human); }
.verdict.v-neutral { border-left-color: var(--neutral); }
.verdict.v-synth { border-left-color: var(--synth); }
.verdict .label { font-size: 1.15rem; font-weight: 650; }
.verdict.v-human .label { color: var(--human); }
.verdict.v-neutral .label { color: var(--neutral); }
.verdict.v-synth .label { color: var(--synth); }
.meter { flex: 1 1 14rem; min-width: 12rem; height: 8px; border-radius: 999px;
         background: linear-gradient(90deg, var(--human), var(--neutral),
         var(--synth)); position: relative; }
.meter i { position: absolute; top: -4px; width: 3px; height: 16px;
           background: var(--fg); border-radius: 2px; }
.grid { display: grid; gap: .75rem;
        grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); }
.stat { background: var(--panel); border: 1px solid var(--border);
        border-radius: 8px; padding: .75rem .9rem; }
.stat .k { color: var(--muted); font-size: .72rem; text-transform: uppercase;
           letter-spacing: .06em; }
.stat .v { font-size: 1.3rem; font-weight: 620; margin-top: .15rem;
           font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; font-size: .875rem;
        margin: .5rem 0; }
.scroll { overflow-x: auto; }
th, td { text-align: left; padding: .5rem .65rem;
         border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: .74rem;
     text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; }
tbody tr:hover { background: var(--panel); }
code, .mono { font-family: var(--mono); font-size: .84em; }
td code { background: var(--panel); padding: .1rem .3rem; border-radius: 4px; }
.badge { display: inline-block; padding: .08rem .45rem; border-radius: 4px;
         font-size: .7rem; font-weight: 650; text-transform: uppercase;
         letter-spacing: .04em; border: 1px solid currentColor; }
.sev-info, .sev-low { color: var(--low); }
.sev-medium { color: var(--medium); }
.sev-high { color: var(--high); }
.sev-critical { color: var(--critical); }
.note { background: var(--panel); border: 1px solid var(--border);
        border-left: 3px solid var(--accent); border-radius: 6px;
        padding: .8rem 1rem; margin: 1rem 0; font-size: .875rem;
        color: var(--muted); }
.note strong { color: var(--fg); }
.note ul { margin: .5rem 0 0; padding-left: 1.1rem; }
.note li { margin: .25rem 0; }
.w { font-variant-numeric: tabular-nums; }
.w.pos { color: var(--synth); }
.w.neg { color: var(--human); }
.status { font-family: var(--mono); font-size: .85rem; }
.status td:first-child { color: var(--muted); }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border);
         color: var(--muted); font-size: .8rem; }
a { color: var(--accent); }
"""


def _esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def _stat(label: str, value: str) -> str:
    return f'<div class="stat"><div class="k">{_esc(label)}</div>' \
           f'<div class="v">{_esc(value)}</div></div>'


def _table(headers: List[str], rows: List[List[str]], *, raw_cols=()) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for index, cell in enumerate(row):
            cells.append(f"<td>{cell if index in raw_cols else _esc(cell)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="scroll"><table><thead><tr>'
        + head
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def render(
    analysis: Analysis,
    *,
    clean: Optional[CleanResult] = None,
    humanize: Optional[HumanizeResult] = None,
    title: str = "loraai report",
) -> str:
    """Render the analysis as a standalone HTML document."""
    source = analysis.source
    stats = analysis.statistics
    style = analysis.style
    synth = analysis.synthetic
    unicode_report = analysis.unicode
    markers = analysis.markers

    parts: List[str] = []
    parts.append(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>"
        "<div class='wrap'>"
    )

    origin = source.path or f"({source.origin} input)"
    parts.append(
        f"<header><h1>{_esc(title)}</h1>"
        f"<div class='sub'><span class='mono'>{_esc(origin)}</span> &middot; "
        f"{source.char_count:,} characters &middot; {source.language} &middot; "
        f"{source.content_kind} &middot; loraai {get_version()}</div></header>"
    )

    # -- verdict -----------------------------------------------------------
    marker_pos = max(0.0, min(1.0, synth.score)) * 100
    parts.append("<h2>Synthetic-text assessment</h2>")
    parts.append(
        f"<div class='verdict {_VERDICT_CLASS[synth.verdict]}'>"
        f"<div class='label'>{_esc(synth.verdict.label)}</div>"
        f"<div class='meter'><i style='left:calc({marker_pos:.1f}% - 1px)'></i></div>"
        f"<div class='sub'>score {synth.score:.2f} &middot; "
        f"confidence {synth.confidence:.2f} &middot; "
        f"reliability {_esc(synth.reliability)}</div></div>"
    )

    if synth.signals:
        rows = []
        for signal in sorted(synth.signals, key=lambda s: -abs(s.weight)):
            css = "pos" if signal.weight > 0.05 else ("neg" if signal.weight < -0.05 else "")
            rows.append(
                [
                    _esc(signal.label) + (" <em>(experimental)</em>" if signal.experimental else ""),
                    "-" if signal.value is None else f"{signal.value:.3f}",
                    f"<span class='w {css}'>{signal.weight:+.2f}</span>",
                    _esc(signal.detail),
                ]
            )
        parts.append(
            _table(["Signal", "Value", "Weight", "What it measures"], rows,
                   raw_cols=(0, 2))
        )

    if synth.caveats:
        items = "".join(f"<li>{_esc(c)}</li>" for c in synth.caveats)
        parts.append(
            f"<div class='note'><strong>How to read this.</strong><ul>{items}</ul></div>"
        )

    # -- provenance --------------------------------------------------------
    watermark = analysis.watermark
    parts.append("<h2>Provenance marking</h2>")
    parts.append(
        _table(
            ["Mechanism", "Status", "Locally detectable"],
            [
                ["Invisible characters",
                 watermark.invisible_characters["status"],
                 "yes - exact"],
                ["Embedded payloads",
                 watermark.embedded_payloads["status"],
                 "yes - exact"],
                ["Statistical sampling watermark",
                 watermark.statistical_watermark["status"],
                 "no"],
                ["File provenance (C2PA)",
                 watermark.file_provenance["status"],
                 "yes - when a container is present"],
            ],
        )
    )
    parts.append(
        "<div class='note'><strong>Why the third row says no.</strong> "
        + _esc(watermark.statistical_watermark["reason"])
        + " "
        + _esc(watermark.statistical_watermark["common_misconception"])
        + "</div>"
    )

    # -- unicode -----------------------------------------------------------
    parts.append("<h2>Unicode forensics</h2>")
    parts.append(
        "<div class='grid'>"
        + _stat("Findings", f"{unicode_report.total:,}")
        + _stat("Max severity", unicode_report.max_severity.value)
        + _stat("Hidden payloads", str(len(unicode_report.payloads)))
        + _stat("Scripts", str(len(unicode_report.scripts)))
        + "</div>"
    )

    if unicode_report.payloads:
        parts.append("<h3>Hidden payloads decoded</h3>")
        parts.append(
            "<div class='note'><strong>These are decodes, not guesses.</strong> "
            "Readable data was recovered from characters that render as nothing. "
            "That means deliberate embedding.</div>"
        )
        parts.append(
            _table(
                ["Scheme", "Chars", "Offset", "Decoded content"],
                [
                    [p.scheme, str(p.char_count), f"{p.start}-{p.end}",
                     f"<code>{_esc(one_line(p.decoded, 90))}</code>"]
                    for p in unicode_report.payloads
                ],
                raw_cols=(3,),
            )
        )

    if unicode_report.class_counts:
        parts.append("<h3>By class</h3>")
        parts.append(
            _table(
                ["Class", "Count"],
                [[k, f"{v:,}"] for k, v in unicode_report.class_counts.items()],
            )
        )

    notable = [
        f for f in unicode_report.findings if f.severity.rank >= Severity.MEDIUM.rank
    ][:60]
    if notable:
        parts.append("<h3>Notable findings</h3>")
        parts.append(
            _table(
                ["Code", "Name", "Severity", "Position", "Action", "Why"],
                [
                    [
                        f"<code>{_esc(f.code)}</code>",
                        _esc(f.name),
                        f"<span class='badge {_SEVERITY_CLASS[f.severity]}'>"
                        f"{_esc(f.severity.value)}</span>",
                        f"{f.line}:{f.column}",
                        _esc(f.recommended_action),
                        _esc(f.note),
                    ]
                    for f in notable
                ],
                raw_cols=(0, 2),
            )
        )

    # -- statistics --------------------------------------------------------
    parts.append("<h2>Text statistics</h2>")
    parts.append(
        "<div class='grid'>"
        + _stat("Words", f"{stats.words:,}")
        + _stat("Sentences", f"{stats.sentences:,}")
        + _stat("Paragraphs", f"{stats.paragraphs:,}")
        + _stat("Unique words", f"{stats.unique_words:,}")
        + _stat("Avg sentence", f"{stats.avg_sentence_length:.1f}")
        + _stat("Sentence SD", f"{stats.sentence_length_stdev:.1f}")
        + _stat("MATTR", f"{stats.moving_ttr:.3f}")
        + _stat("Reading time", f"{stats.reading_time_minutes:.1f} min")
        + "</div>"
    )

    parts.append("<h3>Style</h3>")
    parts.append(
        "<div class='grid'>"
        + _stat("Burstiness", f"{style.burstiness:+.3f}")
        + _stat("Sentence CV", f"{style.sentence_length_cv:.3f}")
        + _stat("Lexical density", f"{style.lexical_density:.3f}")
        + _stat("Transitions/100w", f"{style.transition_density:.2f}")
        + _stat("Contractions/1k", f"{style.contraction_rate:.1f}")
        + _stat("Em dashes/1k", f"{style.em_dash_rate:.1f}")
        + "</div>"
    )

    if style.repeated_ngrams:
        parts.append("<h3>Repeated phrasing</h3>")
        parts.append(
            _table(
                ["Phrase", "Occurrences"],
                [[f"<code>{_esc(g)}</code>", str(c)]
                 for g, c in style.repeated_ngrams[:12]],
                raw_cols=(0,),
            )
        )

    # -- markers -----------------------------------------------------------
    parts.append("<h2>AI-writing markers</h2>")
    parts.append(
        "<div class='grid'>"
        + _stat("Total", f"{markers.total:,}")
        + _stat("Per 1k words", f"{markers.density_per_1k:.1f}")
        + _stat("Weighted", f"{markers.weighted_density_per_1k:.1f}")
        + _stat("Categories", str(len(markers.category_counts)))
        + "</div>"
    )
    if markers.hits:
        parts.append(
            _table(
                ["Line", "Category", "Matched", "Suggestion"],
                [
                    [str(h.line), _esc(h.category),
                     f"<code>{_esc(one_line(h.matched, 60))}</code>",
                     _esc(h.suggestion or "-")]
                    for h in markers.hits[:80]
                ],
                raw_cols=(2,),
            )
        )

    # -- optional ----------------------------------------------------------
    if clean is not None:
        parts.append("<h2>Cleaning</h2>")
        parts.append(
            "<div class='grid'>"
            + _stat("Profile", clean.profile)
            + _stat("Changes", f"{clean.total_changes:,}")
            + _stat("Semantics", "preserved" if clean.semantic_preserved else "review")
            + "</div>"
        )
        if clean.semantic_notes:
            items = "".join(f"<li>{_esc(n)}</li>" for n in clean.semantic_notes)
            parts.append(f"<div class='note'><ul>{items}</ul></div>")

    if humanize is not None:
        parts.append("<h2>Humanization</h2>")
        parts.append(
            "<div class='grid'>"
            + _stat("Provider", humanize.provider)
            + _stat("Style", humanize.style)
            + _stat("Intensity", str(humanize.intensity))
            + _stat("Markers", f"{humanize.marker_before} → {humanize.marker_after}")
            + _stat("Edits", str(len(humanize.edits)))
            + "</div>"
        )
        if humanize.edits:
            parts.append(
                _table(
                    ["Category", "Before", "After"],
                    [[_esc(e.category), f"<code>{_esc(e.before)}</code>",
                      f"<code>{_esc(e.after)}</code>"]
                     for e in humanize.edits[:60]],
                    raw_cols=(1, 2),
                )
            )

    if analysis.warnings:
        items = "".join(f"<li>{_esc(w)}</li>" for w in analysis.warnings)
        parts.append(f"<h2>Warnings</h2><div class='note'><ul>{items}</ul></div>")

    references = "".join(
        f"<li><a href='{_esc(url)}' rel='noopener noreferrer'>{_esc(t)}</a></li>"
        for t, url in REFERENCES
    )
    parts.append(
        f"<footer><p>Generated by loraai {get_version()}. Analysis of writing "
        f"style is probabilistic and does not establish authorship.</p>"
        f"<p>Provenance references:</p><ul>{references}</ul></footer>"
    )

    parts.append("</div></body></html>")
    return redact_secrets("".join(parts))
