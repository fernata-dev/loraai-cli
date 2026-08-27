"""Provenance marking: what can be detected locally, and what cannot.

Why this module exists
----------------------
"AI watermark" refers to at least four unrelated technologies, and conflating
them is how tools end up making claims they cannot support. They are reported
separately here, each with an honest local-detectability status:

1. **Invisible characters** -- zero-width spaces, tag characters, variation
   selectors. Fully detectable and removable locally with certainty, because
   they are literally present in the byte stream. Handled by
   :mod:`loraai.analysis.unicode_forensics`.

2. **Embedded payloads** -- readable data encoded in those characters. Also
   fully detectable: a decode either succeeds or it does not. Handled by
   :mod:`loraai.analysis.payload`.

3. **Statistical sampling watermarks** -- a bias in *which tokens were chosen*
   during generation. Nothing is added to the text; the signal lives in the
   sequence itself. Detection requires the generator's secret key and its
   scoring functions. **This is not locally detectable, by anyone, without
   those secrets.** Reported as such.

4. **File-level provenance metadata** -- C2PA manifests attached to media
   files. Detectable when the container is present, and detected here.

The state of the art, as of this release
----------------------------------------
Anthropic began marking Claude's text output on 2 August 2026 to meet EU AI Act
Article 50 transparency obligations, applied worldwide rather than only in the
EU. Public technical analysis, subsequently confirmed by Anthropic, identifies
the text mechanism as a variant of SynthID-Text (Google DeepMind, *Nature*,
2024), which biases the token *sampling* step via tournament sampling rather
than inserting any character into the output. Anthropic separately attaches
C2PA signed provenance to supported image formats.

Two consequences follow, and this tool states both plainly:

* Deleting zero-width characters does **not** remove a statistical watermark.
  They are unrelated mechanisms. A tool that claims otherwise is wrong.
* No public detector for Anthropic's text watermark has been released. Any
  local tool claiming to detect or verify it -- including this one -- would be
  guessing. So this one does not claim it.

References
----------
* https://www.anthropic.com/news/claude-text-watermark
* https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content
* https://www.nature.com/articles/s41586-024-08025-4 (SynthID-Text)
* https://artificialintelligenceact.eu/article/50/ (EU AI Act Article 50)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models import Severity, UnicodeReport, WatermarkReport

#: Byte signatures that indicate a C2PA manifest inside a media container.
_C2PA_SIGNATURES = (
    b"c2pa",
    b"jumbf",
    b"urn:uuid:",
    b"c2pa.assertions",
    b"contentauth",
)

REFERENCES = [
    ("Anthropic - How Claude's text watermarking works",
     "https://www.anthropic.com/news/claude-text-watermark"),
    ("Anthropic Help - How Claude marks AI-generated content",
     "https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content"),
    ("SynthID-Text (Nature, 2024) - the published mechanism",
     "https://www.nature.com/articles/s41586-024-08025-4"),
    ("EU AI Act, Article 50 - transparency obligations",
     "https://artificialintelligenceact.eu/article/50/"),
]


def _invisible_section(unicode_report: UnicodeReport) -> Dict[str, Any]:
    """Status for mechanism 1: characters physically present in the text."""
    carriers = {
        code: count
        for code, count in unicode_report.codepoint_counts.items()
        if code in ("U+200B", "U+200C", "U+200D", "U+2060", "U+FEFF", "U+00AD")
    }
    tag_count = unicode_report.class_counts.get("tag-character", 0)
    vs_count = unicode_report.class_counts.get("variation-selector", 0)
    zw_count = unicode_report.class_counts.get("zero-width", 0)
    total = tag_count + vs_count + zw_count

    return {
        "detectable_locally": True,
        "status": "PRESENT" if total else "NONE FOUND",
        "confidence": "certain",
        "method": "Direct code-point inspection of every character.",
        "total_carriers": total,
        "zero_width": zw_count,
        "tag_characters": tag_count,
        "variation_selectors": vs_count,
        "carrier_breakdown": carriers,
        "removable": True,
        "note": (
            "These characters are physically present in the text, so their "
            "detection and removal are exact rather than probabilistic. "
            "Removing them does not affect any statistical watermark - the two "
            "are unrelated mechanisms."
        ),
    }


def _payload_section(unicode_report: UnicodeReport) -> Dict[str, Any]:
    """Status for mechanism 2: data decoded out of invisible characters."""
    payloads = unicode_report.payloads
    return {
        "detectable_locally": True,
        "status": "DECODED" if payloads else "NONE FOUND",
        "confidence": "certain",
        "method": (
            "Decoding of the Unicode Tags block, variation-selector byte "
            "chains, and zero-width binary encodings."
        ),
        "count": len(payloads),
        "payloads": [p.to_dict() for p in payloads],
        "note": (
            "A successful decode is proof of deliberate embedding, not a "
            "heuristic. Invisible text that a language model still reads is "
            "the standard prompt-injection channel."
            if payloads
            else "No readable data was recovered from invisible characters."
        ),
    }


def _statistical_section() -> Dict[str, Any]:
    """Status for mechanism 3: the sampling watermark. Honestly: unknown."""
    return {
        "detectable_locally": False,
        "status": "NOT DETECTABLE BY ANY LOCAL ENGINE",
        "confidence": "n/a",
        "reason": (
            "Sampling watermarks add nothing to the text. The signal is a bias "
            "in which tokens were selected during generation, recoverable only "
            "with the generator's secret key and scoring functions. No public "
            "detector has been released for Anthropic's implementation."
        ),
        "known_deployments": [
            {
                "vendor": "Anthropic (Claude)",
                "since": "2026-08-02",
                "mechanism": "SynthID-Text-style token-sampling watermark "
                             "(tournament sampling), confirmed by the vendor.",
                "scope": "Models launched on or after 2 August 2026, applied "
                         "worldwide, including via third-party cloud access.",
                "driver": "EU AI Act Article 50 transparency obligations.",
                "public_detector": "Not released at time of writing; an API "
                                   "has been announced without a date.",
            },
            {
                "vendor": "Google (Gemini)",
                "since": "2024",
                "mechanism": "SynthID-Text, published in Nature 2024.",
                "scope": "Gemini text output.",
                "driver": "Voluntary provenance commitments.",
                "public_detector": "Partial; via Google's own tooling only.",
            },
        ],
        "common_misconception": (
            "Deleting zero-width or invisible characters does NOT remove a "
            "statistical watermark. Vendors deliberately avoided invisible "
            "characters precisely because a find-and-replace defeats them."
        ),
        "what_does_degrade_it": (
            "Because the watermark lives in the specific token sequence, "
            "substantive rewriting - genuine paraphrase, restructuring, "
            "translation - degrades the signal, while copy-paste, formatting "
            "changes and light edits do not. This tool makes no claim about "
            "how much rewriting is sufficient, because without a detector that "
            "is unmeasurable."
        ),
        "references": [{"title": t, "url": u} for t, u in REFERENCES],
    }


def _file_provenance_section(path: Optional[str]) -> Dict[str, Any]:
    """Status for mechanism 4: C2PA manifests in media containers."""
    section: Dict[str, Any] = {
        "detectable_locally": True,
        "status": "NOT APPLICABLE",
        "method": "Container scan for C2PA/JUMBF manifest signatures.",
        "note": (
            "C2PA provenance is attached to media containers such as PNG, JPEG "
            "and SVG. Plain text files have no container to carry it."
        ),
    }
    if not path:
        return section

    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".tiff", ".pdf"):
        return section

    try:
        # A manifest lives near the start of the container; 256 KiB is ample
        # and bounds the read on large media.
        with file_path.open("rb") as handle:
            head = handle.read(262144)
    except OSError as exc:
        section["status"] = "UNREADABLE"
        section["note"] = f"Could not read the file to check: {exc}"
        return section

    lowered = head.lower()
    found = sorted({sig.decode() for sig in _C2PA_SIGNATURES if sig in lowered})
    section["status"] = "MANIFEST SIGNATURE FOUND" if found else "NO MANIFEST FOUND"
    section["signatures"] = found
    section["note"] = (
        "A C2PA/JUMBF signature is present in the container. This tool reports "
        "its presence only - validating the cryptographic signature requires "
        "the c2pa toolchain."
        if found
        else "No C2PA manifest signature found in the first 256 KiB."
    )
    return section


def build(
    unicode_report: UnicodeReport, source_path: Optional[str] = None
) -> WatermarkReport:
    """Assemble the provenance report for one input."""
    return WatermarkReport(
        invisible_characters=_invisible_section(unicode_report),
        embedded_payloads=_payload_section(unicode_report),
        statistical_watermark=_statistical_section(),
        file_provenance=_file_provenance_section(source_path),
    )


def summary_lines(report: WatermarkReport) -> List[str]:
    """One-line-per-mechanism summary for compact displays."""
    return [
        f"Invisible characters   {report.invisible_characters['status']}",
        f"Embedded payloads      {report.embedded_payloads['status']}",
        f"Statistical watermark  {report.statistical_watermark['status']}",
        f"File provenance        {report.file_provenance['status']}",
    ]
