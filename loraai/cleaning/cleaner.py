"""The cleaning engine.

Removes invisible and deceptive characters while guaranteeing that visible
content survives. Every edit is recorded, so a dry run can show exactly what
would change before anything is written.

The correctness property that matters
-------------------------------------
After a ``safe`` clean, the sequence of letters, digits and combining marks in
the output must be identical to the input. That is checked, not assumed: see
:func:`verify_semantics`. Arabic diacritics are combining marks, so this
property is what makes the tool safe to point at Arabic text.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import List, Optional, Tuple

from ..models import CleanChange, CleanResult
from ..unicode_data.confusables import confusable_target, is_cross_script_confusable
from ..unicode_data.invisible import ARABIC_JOINERS, classify_codepoint
from ..unicode_data.scripts import is_mixed_script_word
from ..analysis.tokenizer import word_spans
from ..analysis.unicode_forensics import (_joiner_is_legitimate,
                                          _variation_selector_is_legitimate)
from .rules import DEFAULT_PROFILE, TYPOGRAPHY_MAP, CleanProfile, get_profile


def _semantic_signature(text: str) -> str:
    """The part of *text* a reader actually sees.

    Letters, digits and combining marks, in order. Whitespace and punctuation
    are excluded because whitespace normalisation legitimately changes them.

    Variation selectors are category Mn, so they would be counted here as if
    they were combining accents. They are not: an accent changes what a reader
    sees and a variation selector does not. Counting them made removing one
    look like a loss of content, which is why they used to survive every
    profile even when they were plainly carrying bytes.
    """
    return "".join(
        ch for ch in text
        if unicodedata.category(ch)[0] in ("L", "N", "M")
        and not (0xFE00 <= ord(ch) <= 0xFE0F
                 or 0xE0100 <= ord(ch) <= 0xE01EF)
    )


def verify_semantics(original: str, cleaned: str) -> Tuple[bool, List[str]]:
    """Check that cleaning did not change any visible content.

    Returns ``(ok, notes)``. This is the guarantee that makes the safe profile
    safe to run unattended on text in a script you cannot read.
    """
    notes: List[str] = []
    before = _semantic_signature(original)
    after = _semantic_signature(cleaned)

    if before == after:
        notes.append(
            f"Letter, digit and combining-mark sequence identical "
            f"({len(before)} characters) before and after."
        )
        return True, notes

    # Locate the first divergence so the report can point at it.
    limit = min(len(before), len(after))
    index = next((i for i in range(limit) if before[i] != after[i]), limit)
    notes.append(
        f"Visible content changed at position {index} of the letter sequence "
        f"({len(before)} characters before, {len(after)} after)."
    )
    if index < limit:
        notes.append(
            f"First difference: {before[index]!r} (U+{ord(before[index]):04X}) "
            f"became {after[index]!r} (U+{ord(after[index]):04X})."
        )
    return False, notes


def _arabic_marks_preserved(original: str, cleaned: str) -> Tuple[bool, str]:
    """Confirm Arabic diacritics survived, and say so explicitly."""
    def count_marks(text: str) -> int:
        return sum(1 for ch in text if unicodedata.combining(ch))

    before, after = count_marks(original), count_marks(cleaned)
    if before == after:
        return True, f"Combining marks preserved ({before})."
    return False, f"Combining marks changed: {before} before, {after} after."


def clean(
    text: str,
    profile: str | CleanProfile = DEFAULT_PROFILE,
    *,
    tidy_whitespace: Optional[bool] = None,
    normalize_form: Optional[str] = None,
) -> CleanResult:
    """Clean *text* according to *profile*.

    ``tidy_whitespace`` and ``normalize_form`` override the profile defaults
    when given.
    """
    policy = get_profile(profile) if isinstance(profile, str) else profile
    result = CleanResult(original=text, cleaned=text, profile=policy.name)

    if not text:
        result.semantic_notes.append("Empty input; nothing to clean.")
        return result

    removed: Counter = Counter()
    replaced: Counter = Counter()
    preserved: Counter = Counter()
    changes: List[CleanChange] = []

    # --- confusables need word context, so resolve them up front ----------
    confusable_positions = {}
    if policy.fix_confusables:
        for start, _end, token in word_spans(text):
            if not is_mixed_script_word(token):
                continue
            for offset, ch in enumerate(token):
                if is_cross_script_confusable(ch):
                    target = confusable_target(ch)
                    if target:
                        confusable_positions[start + offset] = target

    out: List[str] = []
    for position, ch in enumerate(text):
        cp = ord(ch)

        if position in confusable_positions:
            target = confusable_positions[position]
            out.append(target)
            replaced[f"U+{cp:04X}"] += 1
            changes.append(
                CleanChange("replaced", cp, position, target, "homoglyph repaired")
            )
            continue

        spec = classify_codepoint(cp)
        if spec is None:
            if policy.normalize_typography and ch in TYPOGRAPHY_MAP:
                target = TYPOGRAPHY_MAP[ch]
                out.append(target)
                replaced[f"U+{cp:04X}"] += 1
                changes.append(
                    CleanChange("replaced", cp, position, target, "typography straightened")
                )
                continue
            out.append(ch)
            continue

        char_class = spec.char_class.value

        # --- joiners: legitimacy depends on neighbours -------------------
        if cp in ARABIC_JOINERS:
            legitimate = _joiner_is_legitimate(text, position)
            if policy.strip_all_joiners or (
                policy.strip_orphan_joiners and not legitimate
            ):
                removed[f"U+{cp:04X}"] += 1
                changes.append(
                    CleanChange(
                        "removed", cp, position, "",
                        "joiner not between joining-script characters"
                        if not legitimate
                        else "joiner removed by profile",
                    )
                )
                continue
            preserved[f"U+{cp:04X}"] += 1
            out.append(ch)
            continue

        # --- bidi: isolates are correct usage, overrides never are -------
        if char_class == "bidi-control":
            if policy.strip_all_bidi:
                removed[f"U+{cp:04X}"] += 1
                changes.append(
                    CleanChange("removed", cp, position, "", "bidi control (aggressive)")
                )
                continue
            if policy.strip_orphan_joiners and cp in (0x202A, 0x202B, 0x202C):
                removed[f"U+{cp:04X}"] += 1
                changes.append(
                    CleanChange("removed", cp, position, "", "deprecated bidi embedding")
                )
                continue
            preserved[f"U+{cp:04X}"] += 1
            out.append(ch)
            continue

        # --- variation selectors: keep the ones selecting a glyph --------
        # VS15 and VS16 used to be preserved unconditionally, which let a
        # selector sitting after a full stop through every profile including
        # aggressive. What matters is the character in front of it.
        if char_class == "variation-selector":
            if _variation_selector_is_legitimate(text, position):
                preserved[f"U+{cp:04X}"] += 1
                out.append(ch)
                continue
            removed[f"U+{cp:04X}"] += 1
            changes.append(
                CleanChange("removed", cp, position, "",
                            "variation selector after a character with no "
                            "glyph variants to select")
            )
            continue

        if char_class in policy.remove_classes:
            removed[f"U+{cp:04X}"] += 1
            changes.append(CleanChange("removed", cp, position, "", spec.note))
            continue

        if char_class in policy.replace_classes:
            target = spec.replacement or " "
            out.append(target)
            replaced[f"U+{cp:04X}"] += 1
            changes.append(CleanChange("replaced", cp, position, target, spec.note))
            continue

        preserved[f"U+{cp:04X}"] += 1
        out.append(ch)

    cleaned = "".join(out)

    # --- post-processing --------------------------------------------------
    form = normalize_form if normalize_form is not None else policy.normalize_form
    if form:
        normalized = unicodedata.normalize(form, cleaned)
        if normalized != cleaned:
            cleaned = normalized
            result.semantic_notes.append(f"Applied {form} normalisation.")

    do_tidy = tidy_whitespace if tidy_whitespace is not None else policy.tidy_whitespace
    if do_tidy:
        cleaned = _tidy(cleaned)

    result.cleaned = cleaned
    result.changes = changes
    result.removed_counts = dict(removed.most_common())
    result.replaced_counts = dict(replaced.most_common())
    result.preserved_counts = dict(preserved.most_common())

    ok, notes = verify_semantics(text, cleaned)
    arabic_ok, arabic_note = _arabic_marks_preserved(text, cleaned)
    result.semantic_preserved = ok and arabic_ok
    result.semantic_notes.extend(notes)
    result.semantic_notes.append(arabic_note)

    if policy.fix_confusables and confusable_positions:
        result.semantic_notes.append(
            f"{len(confusable_positions)} homoglyph(s) replaced; visible "
            "characters changed intentionally."
        )

    return result


def _tidy(text: str) -> str:
    """Collapse redundant whitespace without touching content.

    Blank-line runs are capped at one, matching the humanizer's repair pass so
    the two never fight over the same document.
    """
    lines = [line.rstrip() for line in text.split("\n")]

    tidied: List[str] = []
    blank_run = 0
    for line in lines:
        if not line:
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        # Collapse runs of spaces, but leave leading indentation alone.
        stripped = line.lstrip(" \t")
        indent = line[: len(line) - len(stripped)]
        while "  " in stripped:
            stripped = stripped.replace("  ", " ")
        tidied.append(indent + stripped)

    return "\n".join(tidied).strip("\n")


def preview(result: CleanResult, limit: int = 12) -> List[str]:
    """Human-readable summary lines of what changed."""
    lines: List[str] = []
    for code, count in list(result.removed_counts.items())[:limit]:
        lines.append(f"remove   {code} x{count}")
    for code, count in list(result.replaced_counts.items())[:limit]:
        lines.append(f"replace  {code} x{count}")
    hidden = len(result.removed_counts) + len(result.replaced_counts) - len(lines)
    if hidden > 0:
        lines.append(f"... and {hidden} more distinct code point(s)")
    return lines
