"""Lightweight script and language identification.

Deliberately range-based rather than model-based: the analysis engine only
needs to know which writing systems are present so it can pick correct
tokenization and cleaning rules. That question is answered exactly by code
point ranges, with no training data and no guessing.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Dict

#: (name, low, high) ordered so the common cases match early.
_SCRIPT_RANGES = (
    ("Latin", 0x0041, 0x005A),
    ("Latin", 0x0061, 0x007A),
    ("Latin", 0x00C0, 0x024F),
    ("Latin", 0x1E00, 0x1EFF),
    ("Greek", 0x0370, 0x03FF),
    ("Greek", 0x1F00, 0x1FFF),
    ("Cyrillic", 0x0400, 0x04FF),
    ("Cyrillic", 0x0500, 0x052F),
    ("Armenian", 0x0530, 0x058F),
    ("Hebrew", 0x0590, 0x05FF),
    ("Arabic", 0x0600, 0x06FF),
    ("Arabic", 0x0750, 0x077F),
    ("Arabic", 0x08A0, 0x08FF),
    ("Arabic", 0xFB50, 0xFDFF),
    ("Arabic", 0xFE70, 0xFEFF),
    ("Syriac", 0x0700, 0x074F),
    ("Thaana", 0x0780, 0x07BF),
    ("Devanagari", 0x0900, 0x097F),
    ("Bengali", 0x0980, 0x09FF),
    ("Gurmukhi", 0x0A00, 0x0A7F),
    ("Gujarati", 0x0A80, 0x0AFF),
    ("Tamil", 0x0B80, 0x0BFF),
    ("Telugu", 0x0C00, 0x0C7F),
    ("Kannada", 0x0C80, 0x0CFF),
    ("Malayalam", 0x0D00, 0x0D7F),
    ("Sinhala", 0x0D80, 0x0DFF),
    ("Thai", 0x0E00, 0x0E7F),
    ("Lao", 0x0E80, 0x0EFF),
    ("Tibetan", 0x0F00, 0x0FFF),
    ("Myanmar", 0x1000, 0x109F),
    ("Georgian", 0x10A0, 0x10FF),
    ("Hangul", 0x1100, 0x11FF),
    ("Ethiopic", 0x1200, 0x137F),
    ("Cherokee", 0x13A0, 0x13FF),
    ("Khmer", 0x1780, 0x17FF),
    ("Mongolian", 0x1800, 0x18AF),
    ("Hiragana", 0x3040, 0x309F),
    ("Katakana", 0x30A0, 0x30FF),
    ("Han", 0x3400, 0x4DBF),
    ("Han", 0x4E00, 0x9FFF),
    ("Han", 0xF900, 0xFAFF),
    ("Hangul", 0xAC00, 0xD7AF),
    ("Emoji", 0x1F300, 0x1FAFF),
    ("Emoji", 0x2600, 0x27BF),
)

#: Arabic combining marks (harakat / tashkeel). Semantically meaningful and
#: never removed by any cleaning profile.
ARABIC_DIACRITICS = frozenset(
    list(range(0x064B, 0x0653))
    + [0x0670, 0x0653, 0x0654, 0x0655, 0x0656, 0x0657, 0x0658, 0x0659,
       0x065A, 0x065B, 0x065C, 0x065D, 0x065E, 0x065F, 0x06D6, 0x06D7,
       0x06D8, 0x06D9, 0x06DA, 0x06DB, 0x06DC, 0x06DF, 0x06E0, 0x06E1,
       0x06E2, 0x06E3, 0x06E4, 0x06E7, 0x06E8, 0x06EA, 0x06EB, 0x06EC,
       0x06ED]
)

#: Arabic tatweel / kashida - a legitimate justification character.
ARABIC_TATWEEL = 0x0640


def script_of(ch: str) -> str:
    """Return the script name for a single character."""
    cp = ord(ch)
    if ch.isspace():
        return "Whitespace"
    category = unicodedata.category(ch)
    if category.startswith(("P", "S", "N", "C", "Z")):
        # Punctuation, symbols, numbers and controls are script-neutral.
        return "Common"
    for name, lo, hi in _SCRIPT_RANGES:
        if lo <= cp <= hi:
            return name
    if category.startswith("M"):
        return "Mark"
    return "Unknown"


def script_histogram(text: str) -> Dict[str, int]:
    """Count characters per script, ignoring whitespace and common symbols."""
    counter: Counter = Counter()
    for ch in text:
        name = script_of(ch)
        if name in ("Whitespace", "Common"):
            continue
        counter[name] += 1
    return dict(counter.most_common())


def is_arabic(text: str) -> bool:
    """True when Arabic is the most common script in *text*."""
    hist = script_histogram(text)
    if not hist:
        return False
    return max(hist, key=lambda k: hist[k]) == "Arabic"


def dominant_language(text: str) -> str:
    """Classify the text as ``en``, ``ar``, ``mixed``, ``other`` or ``unknown``.

    Only distinguishes what the rest of the engine actually branches on: the
    humanizer and tokenizer have separate Arabic and Latin rule sets, so those
    two get named and everything else is reported honestly as ``other``.
    """
    hist = script_histogram(text)
    total = sum(hist.values())
    if total < 8:
        return "unknown"
    arabic = hist.get("Arabic", 0) / total
    latin = hist.get("Latin", 0) / total
    if arabic >= 0.85:
        return "ar"
    if latin >= 0.85:
        return "en"
    if arabic >= 0.15 and latin >= 0.15:
        return "mixed"
    if arabic > latin:
        return "ar"
    if latin > arabic:
        return "en"
    return "other"


def is_mixed_script_word(word: str) -> bool:
    """True when one word draws letters from more than one script.

    A strong spoofing signal: legitimate words almost never mix Cyrillic and
    Latin letters, but ``pаypal`` (Cyrillic a) does.
    """
    scripts = {
        script_of(ch)
        for ch in word
        if ch.isalpha() and script_of(ch) not in ("Common", "Whitespace", "Mark")
    }
    return len(scripts) > 1
