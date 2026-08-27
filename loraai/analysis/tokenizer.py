"""Script-aware tokenization.

Whitespace splitting is wrong often enough to matter here: English
contractions are one word, Arabic prefixes are not separate words, and
sentence boundaries differ between the two scripts. Every statistic in the
engine is only as good as this module, so it is kept explicit and testable
rather than delegated to a regex one-liner.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, Sequence, Tuple

#: Sentence terminators across the scripts we support.
LATIN_TERMINATORS = ".!?"
ARABIC_TERMINATORS = "؟۔"  # ARABIC QUESTION MARK, ARABIC FULL STOP
CJK_TERMINATORS = "。！？"
ALL_TERMINATORS = LATIN_TERMINATORS + ARABIC_TERMINATORS + CJK_TERMINATORS

#: Abbreviations that end in a period without ending a sentence.
_ABBREVIATIONS = frozenset(
    """
    mr mrs ms dr prof sr jr st rev hon gen col capt lt sgt
    inc ltd co corp dept univ assn bros
    e.g i.e etc vs cf al viz approx est
    jan feb mar apr jun jul aug sep sept oct nov dec
    mon tue wed thu fri sat sun
    fig eq ref sec ch vol no pp ed eds
    a.m p.m u.s u.k e.u
    """.split()
)

#: A word token. Order matters: a number with separators ("3.50", "1,000") is
#: matched first so it stays one token, then any run of letters and digits
#: with optional internal apostrophes or hyphens. Letters and digits must be
#: allowed to mix -- "COVID19", "H2O" and "GPT4" are single words, and
#: splitting them wrecks both the word count and the vocabulary measures.
_WORD_RE = re.compile(
    r"\d+(?:[.,]\d+)+"
    r"|[^\W_]+(?:['’ʼ\-][^\W_]+)*",
    re.UNICODE,
)

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")

# Spans that must survive rewriting untouched: fenced code, inline code, URLs,
# emails, markdown links, citations, numbers with units.
_PROTECTED_PATTERNS = (
    ("fence", re.compile(r"```.*?```", re.DOTALL)),
    ("fence", re.compile(r"~~~.*?~~~", re.DOTALL)),
    ("inline_code", re.compile(r"`[^`\n]+`")),
    ("url", re.compile(r"https?://[^\s<>\"')\]]+")),
    ("url", re.compile(r"\bwww\.[^\s<>\"')\]]+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("md_link", re.compile(r"\[[^\]\n]*\]\([^)\n]*\)")),
    ("md_image", re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")),
    ("citation", re.compile(r"\[\d+(?:[,\-–]\s*\d+)*\]")),
    ("html_tag", re.compile(r"</?[a-zA-Z][^>\n]*>")),
    ("indent_code", re.compile(r"^(?: {4}|\t).*$", re.MULTILINE)),
)


def words(text: str) -> List[str]:
    """Extract word tokens, keeping contractions and hyphenated words whole."""
    return _WORD_RE.findall(text)


def word_spans(text: str) -> List[Tuple[int, int, str]]:
    """Like :func:`words` but returns ``(start, end, token)`` triples."""
    return [(m.start(), m.end(), m.group()) for m in _WORD_RE.finditer(text)]


def _is_abbreviation(chunk: str) -> bool:
    tail = chunk.rstrip()
    if not tail.endswith("."):
        return False
    last = tail[:-1].split()[-1] if tail[:-1].split() else ""
    stripped = last.strip("([{\"'").lower()
    if stripped in _ABBREVIATIONS:
        return True
    # Single initial, e.g. "J." in "J. Smith".
    if len(stripped) == 1 and stripped.isalpha():
        return True
    # Dotted acronym such as "U.S.A."
    if re.fullmatch(r"(?:[a-z]\.)+[a-z]", stripped):
        return True
    return False


def sentences(text: str) -> List[str]:
    """Split *text* into sentences.

    Handles abbreviations, decimal numbers, ellipses, quoted terminators and
    Arabic punctuation. Falls back to line boundaries for text that has no
    terminators at all, so headline-style input still yields useful counts.
    """
    if not text.strip():
        return []

    result: List[str] = []
    start = 0
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if ch not in ALL_TERMINATORS:
            i += 1
            continue

        # Collapse runs of terminators ("?!", "...") into one boundary.
        j = i
        while j + 1 < n and text[j + 1] in ALL_TERMINATORS:
            j += 1

        candidate = text[start : j + 1]

        # A period between digits is a decimal point, not a boundary.
        if (
            ch == "."
            and i > 0
            and text[i - 1].isdigit()
            and j + 1 < n
            and text[j + 1].isdigit()
        ):
            i = j + 1
            continue

        if ch == "." and j == i and _is_abbreviation(candidate):
            i = j + 1
            continue

        # An ellipsis followed by a lowercase word is a pause, not a boundary.
        if ch == "." and j > i:
            after = j + 1
            while after < n and text[after].isspace():
                after += 1
            if after < n and text[after].islower():
                i = j + 1
                continue

        # Absorb trailing closing quotes and brackets into this sentence.
        k = j + 1
        while k < n and text[k] in "\"')]}”’»":
            k += 1

        # A boundary needs whitespace, end of text, or a newline after it.
        if k < n and not text[k].isspace():
            i = j + 1
            continue

        chunk = text[start:k].strip()
        if chunk:
            result.append(chunk)
        start = k
        i = k

    tail = text[start:].strip()
    if tail:
        result.append(tail)

    if not result:
        return []

    # Text with no terminators at all (headings, lists, poetry): use lines.
    if len(result) == 1 and "\n" in result[0]:
        lines = [ln.strip() for ln in result[0].split("\n") if ln.strip()]
        if len(lines) > 1:
            return lines

    return result


def paragraphs(text: str) -> List[str]:
    """Split on blank lines, dropping empties."""
    return [p.strip() for p in _PARAGRAPH_RE.split(text) if p.strip()]


def syllable_estimate(word: str) -> int:
    """Rough English syllable count, used only for readability metrics."""
    word = word.lower()
    vowels = "aeiouy"
    count = 0
    previous_was_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not previous_was_vowel:
            count += 1
        previous_was_vowel = is_vowel
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def strip_diacritics(text: str) -> str:
    """Remove combining marks. For comparison only - never for output."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def protected_spans(text: str) -> List[Tuple[int, int, str]]:
    """Find spans that any rewriting pass must leave byte-identical.

    Returns non-overlapping ``(start, end, kind)`` triples sorted by position.
    Earlier patterns win on conflict, so a URL inside a code fence is reported
    once as part of the fence.
    """
    spans: List[Tuple[int, int, str]] = []
    for kind, pattern in _PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), kind))

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: List[Tuple[int, int, str]] = []
    for start, end, kind in spans:
        if merged and start < merged[-1][1]:
            # Overlaps the previous span: extend it rather than nesting.
            prev_start, prev_end, prev_kind = merged[-1]
            if end > prev_end:
                merged[-1] = (prev_start, end, prev_kind)
            continue
        merged.append((start, end, kind))
    return merged


def line_of(text: str, position: int, line_starts: Sequence[int] | None = None) -> Tuple[int, int]:
    """Return the 1-based ``(line, column)`` for a character offset."""
    if line_starts is None:
        line_starts = compute_line_starts(text)
    lo, hi = 0, len(line_starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_starts[mid] <= position:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1, position - line_starts[lo] + 1


def compute_line_starts(text: str) -> List[int]:
    """Offsets at which each line begins. Computed once, reused per finding."""
    starts = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            starts.append(idx + 1)
    return starts
