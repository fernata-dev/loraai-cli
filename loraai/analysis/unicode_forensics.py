"""The Unicode forensics pass.

Walks the text once, classifies every suspicious code point, decodes any
hidden payloads, checks for homoglyph spoofing and mixed scripts, and reports
how the text behaves under normalization.

Unlike the stylometric passes, everything here is deterministic and
verifiable: a finding is a code point at an offset, not an opinion.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..models import CharClass, CharFinding, Severity, UnicodeReport
from ..unicode_data.confusables import (
    confusable_target,
    is_cross_script_confusable,
    skeleton,
)
from ..unicode_data.invisible import (
    ARABIC_JOINERS,
    classify_codepoint,
    in_joiner_context,
    in_variation_base_context,
)
from ..unicode_data.scripts import is_mixed_script_word, script_histogram
from .payload import decode_payloads
from .tokenizer import compute_line_starts, line_of, word_spans

#: Cap on individually reported findings. Counts stay exact above this.
MAX_FINDINGS = 5000

_CONTEXT_RADIUS = 28


def _visible(ch: str) -> str:
    """Render one character safely for display inside a context snippet."""
    cp = ord(ch)
    if ch == "\n":
        return "\\n"
    if ch == "\t":
        return "\\t"
    if ch == "\r":
        return "\\r"
    if classify_codepoint(cp) is not None and not ch.isprintable():
        return f"<U+{cp:04X}>"
    if not ch.isprintable():
        return f"<U+{cp:04X}>"
    return ch


def _context(text: str, position: int) -> str:
    """A short, terminal-safe window around *position* with the target marked."""
    start = max(0, position - _CONTEXT_RADIUS)
    end = min(len(text), position + _CONTEXT_RADIUS + 1)
    parts = []
    for idx in range(start, end):
        if idx == position:
            parts.append(f"[{_visible(text[idx])}]")
        else:
            parts.append(_visible(text[idx]))
    snippet = "".join(parts)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _joiner_is_legitimate(text: str, index: int) -> bool:
    """Decide whether a ZWNJ/ZWJ at *index* is doing real work.

    Legitimate when it sits between characters of a script that uses joining
    control -- Arabic, Hebrew, Indic, Thai, Khmer -- or inside an emoji
    sequence. Anywhere else (between Latin letters, at a boundary) it is
    decoration at best and a marker at worst.
    """
    before = text[index - 1] if index > 0 else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    if not before or not after:
        return False
    return in_joiner_context(ord(before)) and in_joiner_context(ord(after))


def _variation_selector_is_legitimate(text: str, index: int) -> bool:
    """Decide whether the variation selector at *index* is selecting a glyph.

    It is legitimate only directly after a character that has variants to pick
    from. The spec for these codepoints has always been marked
    context_sensitive, but nothing evaluated the context, so VS15 and VS16 were
    trusted wherever they appeared - including after a full stop, where the
    only thing they can be doing is carrying a byte.
    """
    if index == 0:
        return False
    base = text[index - 1]
    # A selector after another selector extends a sequence that was itself
    # either legitimate or not; walk back to the real base character.
    scan_at = index - 1
    while scan_at > 0 and 0xFE00 <= ord(text[scan_at]) <= 0xFE0F:
        scan_at -= 1
        base = text[scan_at]
    return in_variation_base_context(ord(base))


def _analyse_normalization(text: str) -> Dict[str, object]:
    """Report how the text changes under each normalization form."""
    forms = {}
    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        normalized = unicodedata.normalize(form, text)
        forms[form] = {
            "identical": normalized == text,
            "length_delta": len(normalized) - len(text),
        }
    already = unicodedata.is_normalized("NFC", text)
    return {
        "is_nfc": already,
        "forms": forms,
        "note": (
            "Text is already NFC-normalized."
            if already
            else "Text is not NFC-normalized; the same characters may compare "
                 "unequal against normalized copies."
        ),
    }


def _scan_confusables(
    text: str, line_starts: List[int]
) -> Tuple[List[CharFinding], List[str]]:
    """Find homoglyphs and words that mix scripts."""
    findings: List[CharFinding] = []
    mixed_words: List[str] = []

    for start, _end, token in word_spans(text):
        if not is_mixed_script_word(token):
            continue
        mixed_words.append(token)
        for offset, ch in enumerate(token):
            if not is_cross_script_confusable(ch):
                continue
            position = start + offset
            line, column = line_of(text, position, line_starts)
            target = confusable_target(ch)
            findings.append(
                CharFinding(
                    codepoint=ord(ch),
                    position=position,
                    line=line,
                    column=column,
                    char_class=CharClass.CONFUSABLE,
                    severity=Severity.HIGH,
                    context=_context(text, position),
                    note=(
                        f"Homoglyph inside a mixed-script word {token!r}: looks "
                        f"identical to {target!r} but is a different character. "
                        f"Reads as {skeleton(token)!r}."
                    ),
                    recommended_action="replace",
                    replacement=target,
                )
            )
    return findings, mixed_words


def scan(text: str, *, decode_hidden: bool = True) -> UnicodeReport:
    """Run the full Unicode forensics pass over *text*."""
    report = UnicodeReport()
    if not text:
        report.notes.append("Empty input; nothing to scan.")
        return report

    line_starts = compute_line_starts(text)
    class_counts: Counter = Counter()
    codepoint_counts: Counter = Counter()
    truncated = False

    for position, ch in enumerate(text):
        cp = ord(ch)
        # Fast path: plain ASCII letters, digits and common punctuation.
        if 0x20 <= cp <= 0x7E or cp in (0x09, 0x0A, 0x0D):
            continue

        spec = classify_codepoint(cp)
        if spec is None:
            continue

        severity = spec.severity
        note = spec.note
        action = spec.safe_action

        # Variation selectors: a byte channel unless they follow a character
        # that actually has glyph variants.
        if 0xFE00 <= cp <= 0xFE0F:
            if _variation_selector_is_legitimate(text, position):
                severity = Severity.INFO
                action = "keep"
                note = ("Variation selector directly after a character that "
                        "has glyph variants, so it is selecting one.")
            else:
                severity = Severity.HIGH
                action = "remove"
                note = ("Variation selector after a character with no glyph "
                        "variants to select. Nothing to do here but carry a "
                        "byte - this is a steganographic channel.")

        # Context-sensitive joiners: decide per occurrence.
        if cp in ARABIC_JOINERS:
            if _joiner_is_legitimate(text, position):
                severity = Severity.INFO
                action = "keep"
                note = (
                    f"{note} Here it sits between characters of a script that "
                    "uses joining control, so it is doing legitimate work."
                )
            else:
                severity = Severity.HIGH
                action = "remove"
                note = (
                    f"{note} Here it is NOT between joining-script characters, "
                    "so it carries no typographic meaning."
                )

        class_counts[spec.char_class.value] += 1
        codepoint_counts[f"U+{cp:04X}"] += 1

        if len(report.findings) < MAX_FINDINGS:
            line, column = line_of(text, position, line_starts)
            report.findings.append(
                CharFinding(
                    codepoint=cp,
                    position=position,
                    line=line,
                    column=column,
                    char_class=spec.char_class,
                    severity=severity,
                    context=_context(text, position),
                    note=note,
                    recommended_action=action,
                    replacement=spec.replacement or None,
                )
            )
        else:
            truncated = True

        if severity.rank > report.max_severity.rank:
            report.max_severity = severity

    confusable_findings, mixed_words = _scan_confusables(text, line_starts)
    for finding in confusable_findings:
        class_counts[finding.char_class.value] += 1
        codepoint_counts[finding.code] += 1
        if len(report.findings) < MAX_FINDINGS:
            report.findings.append(finding)
        else:
            truncated = True
        if finding.severity.rank > report.max_severity.rank:
            report.max_severity = finding.severity

    report.findings.sort(key=lambda f: f.position)
    report.class_counts = dict(class_counts.most_common())
    report.codepoint_counts = dict(codepoint_counts.most_common())
    report.mixed_script_words = sorted(set(mixed_words))
    report.scripts = script_histogram(text)
    report.normalization = _analyse_normalization(text)

    if decode_hidden:
        report.payloads = decode_payloads(text)
        if report.payloads:
            report.max_severity = Severity.CRITICAL
            report.notes.append(
                f"{len(report.payloads)} hidden payload(s) decoded from "
                "invisible characters. This is deliberate embedding, not an "
                "artefact of ordinary text."
            )

    if truncated:
        report.notes.append(
            f"Finding list truncated at {MAX_FINDINGS} entries; the counts "
            "above remain exact for the whole input."
        )

    if len(report.scripts) > 2:
        report.notes.append(
            "Three or more scripts present. Expected in multilingual text, "
            "worth a look otherwise."
        )

    return report


def severity_breakdown(report: UnicodeReport) -> Dict[str, int]:
    """Count findings by severity, for summary displays."""
    counter: Counter = Counter(f.severity.value for f in report.findings)
    return {
        level.value: counter.get(level.value, 0)
        for level in Severity
        if counter.get(level.value, 0)
    }
