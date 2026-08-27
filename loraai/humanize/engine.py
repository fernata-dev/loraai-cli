"""The offline humanizer.

Rewrites text to read more naturally by removing the stylistic habits that
mark generated prose, while guaranteeing that certain spans -- code, URLs,
emails, citations, markdown links -- come through byte-identical.

Method
------
1. Strip invisible characters via the cleaning engine.
2. Split the text into protected and rewritable segments. Only the latter are
   touched, so a URL is never "simplified" and a code fence is never reflowed.
3. Apply the substitution rules for the chosen language, style and intensity.
4. Vary sentence rhythm by splitting over-long sentences at natural joins.
5. Repair the punctuation and capitalisation that step 3 disturbs.
6. Re-measure AI-writing markers so the caller sees the before/after delta.

Every step is recorded as a :class:`~loraai.models.HumanizeEdit`, and the
original is always retained.

What it does not do
-------------------
It does not invent facts, reorder arguments, or paraphrase meaning -- those
need a language model, available through :mod:`loraai.humanize.providers`.
It also does not defeat statistical watermarking; see
:mod:`loraai.analysis.provenance` for why that is a different problem.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..analysis import markers as markers_module
from ..analysis.tokenizer import protected_spans, sentences, words
from ..cleaning.cleaner import clean
from ..models import HumanizeEdit, HumanizeResult
from .rules import Substitution, rules_for

#: Sentences longer than this are candidates for splitting.
LONG_SENTENCE_WORDS = 28

#: Retaining less than this share of the original words means a rule
#: over-matched and ate content, so the result is flagged loudly.
CONTENT_LOSS_THRESHOLD = 0.65

#: Natural break points, tried in order.
_SPLIT_POINTS = (
    re.compile(r",\s+(and|but|so|yet)\s+", re.IGNORECASE),
    re.compile(r";\s+"),
    re.compile(r",\s+(which|while|although|whereas)\s+", re.IGNORECASE),
)

#: Where a lowercase letter should be capitalised after a deletion. Limited to
#: real sentence boundaries and paragraph starts: capitalising after *any*
#: newline would wreck soft-wrapped prose and list items.
_SENTENCE_START = re.compile(r"([.!?][\"')\]]?[ \t]+|\n[ \t]*\n[ \t]*)([a-z])")


def _segments(text: str) -> List[Tuple[str, bool]]:
    """Split into ``(chunk, rewritable)`` pairs.

    Protected spans come back with ``rewritable=False`` and are passed through
    untouched.
    """
    spans = protected_spans(text)
    if not spans:
        return [(text, True)]

    result: List[Tuple[str, bool]] = []
    cursor = 0
    for start, end, _kind in spans:
        if start > cursor:
            result.append((text[cursor:start], True))
        result.append((text[start:end], False))
        cursor = end
    if cursor < len(text):
        result.append((text[cursor:], True))
    return result


def _apply_rules(
    text: str, rules: List[Substitution]
) -> Tuple[str, List[HumanizeEdit]]:
    """Apply every rule in turn, recording what each one changed."""
    edits: List[HumanizeEdit] = []
    current = text

    for rule in rules:
        matches = list(rule.pattern.finditer(current))
        if not matches:
            continue

        # Record before rewriting so offsets refer to real text.
        for match in matches[:20]:
            before = match.group(0)
            after = (
                rule.replacement(match)
                if callable(rule.replacement)
                else rule.replacement
            )
            if before == after:
                continue
            edits.append(
                HumanizeEdit(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    before=before.strip()[:80],
                    after=after.strip()[:80],
                    position=match.start(),
                )
            )
        current = rule.pattern.sub(rule.replacement, current)

    return current, edits


def _vary_rhythm(text: str, intensity: int) -> Tuple[str, List[HumanizeEdit]]:
    """Split over-long sentences to widen sentence-length variation.

    Uniform sentence length is the strongest single rhythm signal in generated
    prose. Splitting at a coordinating conjunction preserves meaning exactly
    while restoring variation.
    """
    if intensity < 2:
        return text, []

    edits: List[HumanizeEdit] = []
    result = text

    for sentence in sentences(text):
        token_count = len(words(sentence))
        if token_count <= LONG_SENTENCE_WORDS:
            continue

        for pattern in _SPLIT_POINTS:
            match = pattern.search(sentence)
            if not match:
                continue
            # Only split near the middle; a split at the very edge just makes
            # one tiny fragment and one still-long sentence.
            relative = match.start() / len(sentence)
            if not 0.3 <= relative <= 0.75:
                continue

            head = sentence[: match.start()].rstrip(" ,;")
            tail = sentence[match.end() :].lstrip()
            if not head or not tail or len(words(tail)) < 4:
                continue

            tail = tail[0].upper() + tail[1:]
            rebuilt = f"{head}. {tail}"
            if rebuilt == sentence:
                continue

            result = result.replace(sentence, rebuilt, 1)
            edits.append(
                HumanizeEdit(
                    rule_id="hum.rhythm.split",
                    category="rhythm",
                    before=sentence[:80],
                    after=rebuilt[:80],
                )
            )
            break

    return result, edits


def _repair(text: str) -> str:
    """Fix the punctuation and spacing that deletions leave behind."""
    result = text

    # Space before punctuation, doubled punctuation, orphaned separators.
    result = re.sub(r"[ \t]+([,.;:!?])", r"\1", result)
    result = re.sub(r"([,;:])\1+", r"\1", result)
    result = re.sub(r"\.{4,}", "...", result)
    result = re.sub(r"(?<![.!?])\.\s*\.(?!\.)", ".", result)
    result = re.sub(r"^[ \t]*[,;:]\s*", "", result, flags=re.MULTILINE)
    result = re.sub(r"([.!?])\s*,", r"\1", result)

    # Collapse horizontal whitespace without disturbing indentation. Trailing
    # space is only stripped before a newline: a chunk can end mid-line, right
    # before a protected span, and that space is a word separator.
    result = re.sub(r"(?<=\S)[ \t]{2,}", " ", result)
    result = re.sub(r"[ \t]+(?=\n)", "", result)

    # Cap blank-line runs at one.
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Re-capitalise sentence starts left lowercase by a deletion.
    result = _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), result)

    return result


def _repair_outside_protected(text: str) -> str:
    """Run :func:`_repair` on the rewritable parts only.

    Repair collapses whitespace and fixes capitalisation, both of which would
    corrupt a code fence. Protected spans are re-derived here rather than
    reused, because the rule pass has already changed the offsets.
    """
    pieces = []
    for chunk, rewritable in _segments(text):
        pieces.append(_repair(chunk) if rewritable else chunk)
    result = "".join(pieces).strip()
    # Capitalise the very first letter, once, on the joined result.
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


def humanize(
    text: str,
    *,
    language: str = "en",
    style: str = "natural",
    intensity: int = 2,
    clean_invisible: bool = True,
    clean_profile: str = "standard",
) -> HumanizeResult:
    """Rewrite *text* to read more naturally.

    Parameters
    ----------
    language
        ``en``, ``ar`` or ``mixed``. Selects the rule set.
    style
        ``natural``, ``concise``, ``professional``, ``academic`` or
        ``conversational``. Gates which rules apply -- contractions are
        skipped for academic prose, for instance.
    intensity
        1 (conservative) to 3 (thorough).
    clean_invisible
        Strip invisible characters first. On by default: text full of
        zero-width markers is not "human" in any useful sense.
    """
    intensity = max(1, min(3, int(intensity)))
    result = HumanizeResult(
        original=text, result=text, style=style, intensity=intensity,
        provider="offline",
    )

    if not text.strip():
        result.notes.append("Empty input; nothing to rewrite.")
        return result

    before_markers = markers_module.scan(text, language)
    result.marker_before = before_markers.total

    working = text
    if clean_invisible:
        # tidy_whitespace is disabled deliberately: it operates on the whole
        # document and would collapse significant spacing inside code fences,
        # which the rest of this module goes to some length to protect.
        cleaned = clean(text, clean_profile, tidy_whitespace=False)
        if cleaned.changed:
            working = cleaned.cleaned
            removed = sum(cleaned.removed_counts.values())
            replaced = sum(cleaned.replaced_counts.values())
            result.edits.append(
                HumanizeEdit(
                    rule_id="hum.clean.invisible",
                    category="unicode",
                    before=f"{removed} invisible + {replaced} exotic character(s)",
                    after="removed / normalised",
                )
            )
            result.notes.append(
                f"Removed {removed} invisible and normalised {replaced} exotic "
                f"character(s) before rewriting."
            )

    rules = rules_for(language, style, intensity)
    if not rules:
        result.notes.append(
            f"No rules apply for language={language!r} style={style!r}."
        )

    pieces: List[str] = []
    all_edits: List[HumanizeEdit] = []
    protected_count = 0

    for chunk, rewritable in _segments(working):
        if not rewritable:
            pieces.append(chunk)
            protected_count += 1
            continue
        rewritten, edits = _apply_rules(chunk, rules)
        pieces.append(rewritten)
        all_edits.extend(edits)

    combined = "".join(pieces)

    # Rhythm variation runs on the joined text, but only where nothing is
    # protected -- splitting a sentence that contains a code span is unsafe.
    if not protected_count:
        combined, rhythm_edits = _vary_rhythm(combined, intensity)
        all_edits.extend(rhythm_edits)
    elif intensity >= 2:
        result.notes.append(
            "Sentence-rhythm variation skipped: the text contains protected "
            "spans (code, links or citations) that must not be resplit."
        )

    combined = _repair_outside_protected(combined)

    result.result = combined
    result.edits.extend(all_edits)
    result.preserved_spans = protected_count
    result.marker_after = markers_module.scan(combined, language).total

    if not result.changed:
        result.notes.append("No applicable patterns found; text left unchanged.")

    # Safety net: rule-based rewriting should trim padding, not content. A
    # large drop means a rule over-matched, and the user needs to know before
    # they overwrite anything.
    before_words = len(words(text))
    after_words = len(words(combined))
    if before_words:
        retained = after_words / before_words
        if retained < CONTENT_LOSS_THRESHOLD:
            result.notes.append(
                f"WARNING: word count fell from {before_words} to {after_words} "
                f"({retained:.0%} retained). Review the diff before accepting "
                f"this rewrite."
            )

    result.notes.append(
        "Style markers were reduced. This improves how naturally the text "
        "reads; it is not a guarantee about any particular detector, and it "
        "does not affect statistical watermarking."
    )
    return result
