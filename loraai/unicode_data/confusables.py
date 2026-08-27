"""Homoglyph (confusable) detection.

Two complementary mechanisms are used:

1. **NFKC compatibility folding** handles the families Unicode already knows how
   to collapse: fullwidth forms, mathematical alphanumerics, circled and
   parenthesised letters, ligatures, superscripts. Deriving these from
   :mod:`unicodedata` instead of hardcoding them keeps the table small and
   correct across Unicode versions.
2. **An explicit cross-script table** handles what NFKC deliberately leaves
   alone: Cyrillic, Greek, Armenian and Cherokee letters that are visually
   identical to Latin ones but are separate characters with separate meanings.
   These are the ones used in spoofing, so they carry the higher severity.
"""

from __future__ import annotations

import unicodedata
from typing import Dict, Optional

#: Cross-script homoglyphs -> the Latin/ASCII character they imitate.
CROSS_SCRIPT: Dict[str, str] = {
    # Cyrillic uppercase
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "У": "Y", "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J",
    "Ԛ": "Q", "Ԝ": "W", "Ғ": "F", "Ԍ": "G", "Ӏ": "I",
    # Cyrillic lowercase
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w",
    "н": "h", "г": "r", "т": "t",
    # Greek uppercase
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "͸": "?",
    # Greek lowercase
    "ο": "o", "ν": "v", "ρ": "p", "ϲ": "c", "ϳ": "j",
    "ι": "i", "κ": "k", "τ": "t", "υ": "u", "γ": "y",
    "χ": "x", "α": "a", "ε": "e", "σ": "o",
    # Armenian
    "օ": "o", "ո": "n", "ս": "u", "ա": "w", "գ": "q",
    "ի": "h", "հ": "h", "ղ": "n", "յ": "j", "ռ": "n",
    "ց": "g", "ք": "f", "Օ": "O", "Ց": "S",
    # Cherokee
    "Ꭺ": "A", "Ꭼ": "E", "Ꮃ": "W", "Ꮋ": "H", "Ꮎ": "I",
    "Ꮞ": "L", "Ꭱ": "T", "Ꮢ": "P", "Ꮪ": "S", "Ꮮ": "V",
    # Latin-script lookalikes that are still distinct letters
    "ɑ": "a", "ɡ": "g", "ɩ": "i", "ı": "i", "ȷ": "j",
    "ǀ": "l", "ɪ": "i", "ʙ": "b", "ǃ": "!",
    # Roman numerals and letterlike symbols
    "Ⅰ": "I", "ⅰ": "i", "ⅼ": "l", "ℓ": "l", "K": "K",
    "Å": "A", "Ω": "O",
    # Punctuation lookalikes
    "⁄": "/", "∕": "/", "․": ".", "‚": ",", "ʼ": "'",
    "ʻ": "'", "ʹ": "'", "ʺ": '"', "ˮ": '"', "։": ":",
    "׃": ":", "∶": ":", "：": ":",
    # Arabic-Indic vs ASCII digits are NOT listed: both are legitimate digits
    # in their own right and flagging them would be noise in Arabic text.
}


def _build_compat_map() -> Dict[str, str]:
    """Derive the NFKC-foldable confusables from Unicode itself.

    Scans the ranges where compatibility variants of ASCII actually live and
    keeps any character that NFKC folds to a single ASCII alphanumeric.
    """
    mapping: Dict[str, str] = {}
    ranges = (
        (0xFF01, 0xFF5E),    # Fullwidth forms
        (0x1D400, 0x1D7FF),  # Mathematical alphanumeric symbols
        (0x2460, 0x24FF),    # Enclosed alphanumerics
        (0x1F110, 0x1F189),  # Enclosed alphanumeric supplement
        (0x2070, 0x209F),    # Super/subscripts
        (0x1D2C, 0x1D6A),    # Phonetic modifier letters
        (0xA770, 0xA78F),    # Latin extended-D fragments
    )
    for lo, hi in ranges:
        for cp in range(lo, hi + 1):
            ch = chr(cp)
            folded = unicodedata.normalize("NFKC", ch)
            if len(folded) == 1 and folded.isascii() and folded.isalnum():
                mapping[ch] = folded
    return mapping


#: Compatibility variants that fold to a single ASCII alphanumeric.
COMPAT_CONFUSABLES: Dict[str, str] = _build_compat_map()

#: Full confusable table. Cross-script entries take priority.
CONFUSABLES: Dict[str, str] = {**COMPAT_CONFUSABLES, **CROSS_SCRIPT}


def confusable_target(ch: str) -> Optional[str]:
    """Return the ASCII character *ch* imitates, or ``None``."""
    return CONFUSABLES.get(ch)


def is_cross_script_confusable(ch: str) -> bool:
    """True for the security-relevant class: a different script, same glyph."""
    return ch in CROSS_SCRIPT


def skeleton(text: str) -> str:
    """Reduce *text* to a comparison skeleton.

    Two strings with the same skeleton look alike to a reader even when their
    code points differ entirely. Used to spot spoofed words.
    """
    folded = unicodedata.normalize("NFKC", text)
    out = []
    for ch in folded:
        out.append(CONFUSABLES.get(ch, ch))
    stripped = unicodedata.normalize("NFD", "".join(out))
    return "".join(c for c in stripped if not unicodedata.combining(c)).lower()
