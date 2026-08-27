"""Catalog of invisible, format, and otherwise suspicious code points.

Scope note
----------
Characters listed here are *invisible or deceptive*, not merely unusual. Every
entry carries an explicit cleaning policy for both the conservative ("safe")
and the thorough ("aggressive") profile, because several of these characters
are load-bearing in real writing:

* ``U+200C``/``U+200D`` control letter joining in Arabic, Persian and Indic
  scripts, and hold emoji ZWJ sequences together. Removing them blindly
  corrupts text. They are context-checked at cleaning time, never blanket-removed.
* ``U+00A0`` and friends are legitimate typography; the safe profile normalises
  them to a plain space rather than deleting them.
* Bidi *isolates* are how correct mixed Arabic/Latin text is written. Bidi
  *overrides* are the Trojan Source attack. They get different severities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, Optional

from ..models import CharClass, Severity

KEEP = "keep"
REMOVE = "remove"
REPLACE = "replace"
REVIEW = "review"


@dataclass(frozen=True)
class CharSpec:
    """Cleaning and reporting policy for one code point."""

    codepoint: int
    char_class: CharClass
    severity: Severity
    safe_action: str
    aggressive_action: str
    replacement: str = ""
    note: str = ""
    #: True when the character has legitimate uses that depend on neighbours,
    #: so the cleaner must inspect context before touching it.
    context_sensitive: bool = False

    @property
    def code(self) -> str:
        return f"U+{self.codepoint:04X}"


def _spec(
    cp: int,
    cls: CharClass,
    sev: Severity,
    safe: str,
    aggressive: str,
    replacement: str = "",
    note: str = "",
    context_sensitive: bool = False,
) -> CharSpec:
    return CharSpec(cp, cls, sev, safe, aggressive, replacement, note, context_sensitive)


# --------------------------------------------------------------------------
# Zero-width and invisible formatting characters
# --------------------------------------------------------------------------

ZERO_WIDTH: Dict[int, CharSpec] = {
    0x200B: _spec(
        0x200B, CharClass.ZERO_WIDTH, Severity.HIGH, REMOVE, REMOVE,
        note="Zero-width space. No legitimate role in ordinary prose; the "
             "single most common carrier for invisible marking.",
    ),
    0x200C: _spec(
        0x200C, CharClass.ZERO_WIDTH, Severity.LOW, KEEP, REVIEW,
        note="Zero-width non-joiner. Semantically required in Arabic, Persian "
             "and Indic text. Removed only when not adjacent to a script that uses it.",
        context_sensitive=True,
    ),
    0x200D: _spec(
        0x200D, CharClass.ZERO_WIDTH, Severity.LOW, KEEP, REVIEW,
        note="Zero-width joiner. Required by emoji sequences and Indic/Arabic "
             "shaping. Removed only outside those contexts.",
        context_sensitive=True,
    ),
    0x2060: _spec(
        0x2060, CharClass.ZERO_WIDTH, Severity.HIGH, REMOVE, REMOVE,
        note="Word joiner. Invisible; occasionally used for line-break control, "
             "frequently used as a hidden marker.",
    ),
    0xFEFF: _spec(
        0xFEFF, CharClass.ZERO_WIDTH, Severity.HIGH, REMOVE, REMOVE,
        note="Zero-width no-break space / byte order mark. Invisible when it "
             "appears mid-text; a classic marking carrier.",
    ),
    0x00AD: _spec(
        0x00AD, CharClass.ZERO_WIDTH, Severity.MEDIUM, REMOVE, REMOVE,
        note="Soft hyphen. Invisible unless a line breaks at that point.",
    ),
    0x180E: _spec(
        0x180E, CharClass.ZERO_WIDTH, Severity.HIGH, REMOVE, REMOVE,
        note="Mongolian vowel separator. Zero-width in modern Unicode.",
    ),
    0x115F: _spec(
        0x115F, CharClass.ZERO_WIDTH, Severity.MEDIUM, REVIEW, REMOVE,
        note="Hangul choseong filler. Renders as blank.",
    ),
    0x1160: _spec(
        0x1160, CharClass.ZERO_WIDTH, Severity.MEDIUM, REVIEW, REMOVE,
        note="Hangul jungseong filler. Renders as blank.",
    ),
    0x3164: _spec(
        0x3164, CharClass.ZERO_WIDTH, Severity.HIGH, REMOVE, REMOVE,
        note="Hangul filler. Renders as blank and is widely abused to pad text.",
    ),
    0xFFA0: _spec(
        0xFFA0, CharClass.ZERO_WIDTH, Severity.HIGH, REMOVE, REMOVE,
        note="Halfwidth Hangul filler. Renders as blank.",
    ),
}

# Invisible mathematical operators - valid inside MathML, never in prose.
INVISIBLE_MATH: Dict[int, CharSpec] = {
    0x2061: _spec(0x2061, CharClass.INVISIBLE_MATH, Severity.HIGH, REMOVE, REMOVE,
                  note="Function application. Invisible math operator."),
    0x2062: _spec(0x2062, CharClass.INVISIBLE_MATH, Severity.HIGH, REMOVE, REMOVE,
                  note="Invisible times. Invisible math operator."),
    0x2063: _spec(0x2063, CharClass.INVISIBLE_MATH, Severity.HIGH, REMOVE, REMOVE,
                  note="Invisible separator. Invisible math operator."),
    0x2064: _spec(0x2064, CharClass.INVISIBLE_MATH, Severity.HIGH, REMOVE, REMOVE,
                  note="Invisible plus. Invisible math operator."),
}

# --------------------------------------------------------------------------
# Bidirectional controls
# --------------------------------------------------------------------------

BIDI_CONTROLS: Dict[int, CharSpec] = {
    0x200E: _spec(0x200E, CharClass.BIDI_CONTROL, Severity.LOW, KEEP, REVIEW,
                  note="Left-to-right mark. Legitimate in mixed-direction text.",
                  context_sensitive=True),
    0x200F: _spec(0x200F, CharClass.BIDI_CONTROL, Severity.LOW, KEEP, REVIEW,
                  note="Right-to-left mark. Legitimate in Arabic and Hebrew text.",
                  context_sensitive=True),
    0x061C: _spec(0x061C, CharClass.BIDI_CONTROL, Severity.LOW, KEEP, REVIEW,
                  note="Arabic letter mark. Legitimate in Arabic text layout.",
                  context_sensitive=True),
    0x2066: _spec(0x2066, CharClass.BIDI_CONTROL, Severity.MEDIUM, KEEP, REVIEW,
                  note="Left-to-right isolate. Correct modern way to nest "
                       "mixed-direction runs.", context_sensitive=True),
    0x2067: _spec(0x2067, CharClass.BIDI_CONTROL, Severity.MEDIUM, KEEP, REVIEW,
                  note="Right-to-left isolate. Correct modern way to nest "
                       "mixed-direction runs.", context_sensitive=True),
    0x2068: _spec(0x2068, CharClass.BIDI_CONTROL, Severity.MEDIUM, KEEP, REVIEW,
                  note="First strong isolate.", context_sensitive=True),
    0x2069: _spec(0x2069, CharClass.BIDI_CONTROL, Severity.MEDIUM, KEEP, REVIEW,
                  note="Pop directional isolate. Closes an isolate.",
                  context_sensitive=True),
    0x202A: _spec(0x202A, CharClass.BIDI_CONTROL, Severity.MEDIUM, REVIEW, REMOVE,
                  note="Left-to-right embedding. Deprecated in favour of isolates."),
    0x202B: _spec(0x202B, CharClass.BIDI_CONTROL, Severity.MEDIUM, REVIEW, REMOVE,
                  note="Right-to-left embedding. Deprecated in favour of isolates."),
    0x202C: _spec(0x202C, CharClass.BIDI_CONTROL, Severity.MEDIUM, REVIEW, REMOVE,
                  note="Pop directional formatting. Closes an embedding or override."),
    0x202D: _spec(0x202D, CharClass.BIDI_OVERRIDE, Severity.CRITICAL, REMOVE, REMOVE,
                  note="Left-to-right override. Forces display order to differ from "
                       "logical order - the Trojan Source source-code attack."),
    0x202E: _spec(0x202E, CharClass.BIDI_OVERRIDE, Severity.CRITICAL, REMOVE, REMOVE,
                  note="Right-to-left override. Forces display order to differ from "
                       "logical order - the Trojan Source source-code attack."),
}

# --------------------------------------------------------------------------
# Exotic whitespace and line separators
# --------------------------------------------------------------------------

_WHITESPACE_NOTES = {
    0x00A0: "No-break space. Legitimate typography; normalised, not deleted.",
    0x1680: "Ogham space mark.",
    0x2000: "En quad.",
    0x2001: "Em quad.",
    0x2002: "En space.",
    0x2003: "Em space.",
    0x2004: "Three-per-em space.",
    0x2005: "Four-per-em space.",
    0x2006: "Six-per-em space.",
    0x2007: "Figure space.",
    0x2008: "Punctuation space.",
    0x2009: "Thin space.",
    0x200A: "Hair space.",
    0x202F: "Narrow no-break space.",
    0x205F: "Medium mathematical space.",
    0x3000: "Ideographic space.",
}

EXOTIC_WHITESPACE: Dict[int, CharSpec] = {
    cp: _spec(
        cp, CharClass.EXOTIC_WHITESPACE,
        Severity.LOW if cp in (0x00A0, 0x202F, 0x2009) else Severity.MEDIUM,
        REPLACE, REPLACE, replacement=" ", note=note,
    )
    for cp, note in _WHITESPACE_NOTES.items()
}

LINE_SEPARATORS: Dict[int, CharSpec] = {
    0x0085: _spec(0x0085, CharClass.LINE_SEPARATOR, Severity.MEDIUM, REPLACE, REPLACE,
                  replacement="\n", note="Next line (C1 control)."),
    0x2028: _spec(0x2028, CharClass.LINE_SEPARATOR, Severity.MEDIUM, REPLACE, REPLACE,
                  replacement="\n", note="Line separator."),
    0x2029: _spec(0x2029, CharClass.LINE_SEPARATOR, Severity.MEDIUM, REPLACE, REPLACE,
                  replacement="\n\n", note="Paragraph separator."),
}

# --------------------------------------------------------------------------
# Interlinear annotation and other invisible format controls
# --------------------------------------------------------------------------

INVISIBLE_FORMAT: Dict[int, CharSpec] = {
    0xFFF9: _spec(0xFFF9, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                  note="Interlinear annotation anchor. Not for plain text."),
    0xFFFA: _spec(0xFFFA, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                  note="Interlinear annotation separator. Not for plain text."),
    0xFFFB: _spec(0xFFFB, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                  note="Interlinear annotation terminator. Not for plain text."),
    0x110BD: _spec(0x110BD, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Kaithi number sign. Invisible format character."),
    0x110CD: _spec(0x110CD, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Kaithi number sign above. Invisible format character."),
    0x1D173: _spec(0x1D173, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol begin beam. Invisible format character."),
    0x1D174: _spec(0x1D174, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol end beam. Invisible format character."),
    0x1D175: _spec(0x1D175, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol begin tie. Invisible format character."),
    0x1D176: _spec(0x1D176, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol end tie. Invisible format character."),
    0x1D177: _spec(0x1D177, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol begin slur. Invisible format character."),
    0x1D178: _spec(0x1D178, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol end slur. Invisible format character."),
    0x1D179: _spec(0x1D179, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol begin phrase. Invisible format character."),
    0x1D17A: _spec(0x1D17A, CharClass.INVISIBLE_FORMAT, Severity.HIGH, REMOVE, REMOVE,
                   note="Musical symbol end phrase. Invisible format character."),
}

# --------------------------------------------------------------------------
# Range-based blocks
# --------------------------------------------------------------------------

#: Unicode Tags block. U+E0020..U+E007E mirror printable ASCII 0x20..0x7E and
#: render as nothing anywhere, while language models still tokenize them. This
#: is the "ASCII smuggling" channel used for invisible prompt injection.
TAG_BLOCK = (0xE0000, 0xE007F)

#: Variation Selectors. VS1-16 are legitimate on emoji and CJK ideographs;
#: the supplement VS17-256 is a documented steganographic byte channel.
VARIATION_SELECTORS = (0xFE00, 0xFE0F)
VARIATION_SELECTORS_SUPPLEMENT = (0xE0100, 0xE01EF)

PRIVATE_USE_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))

#: Joiners that Arabic, Persian and Indic scripts genuinely need.
ARABIC_JOINERS = frozenset({0x200C, 0x200D})

#: Scripts in whose company ZWNJ/ZWJ are legitimate rather than suspicious.
JOINER_CONTEXT_RANGES = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x08A0, 0x08FF),  # Arabic Extended-A
    (0xFB50, 0xFDFF),  # Arabic Presentation Forms-A
    (0xFE70, 0xFEFF),  # Arabic Presentation Forms-B
    (0x0590, 0x05FF),  # Hebrew
    (0x0900, 0x0DFF),  # Devanagari .. Sinhala
    (0x0E00, 0x0E7F),  # Thai
    (0x1780, 0x17FF),  # Khmer
    (0x1F300, 0x1FAFF),  # Emoji (ZWJ sequences)
    (0x2600, 0x27BF),  # Misc symbols and dingbats (emoji)
    (0xFE0F, 0xFE0F),  # Emoji variation selector
)


def _merged_table() -> Dict[int, CharSpec]:
    table: Dict[int, CharSpec] = {}
    for group in (
        ZERO_WIDTH,
        INVISIBLE_MATH,
        BIDI_CONTROLS,
        EXOTIC_WHITESPACE,
        LINE_SEPARATORS,
        INVISIBLE_FORMAT,
    ):
        table.update(group)
    return table


SPEC_TABLE: Dict[int, CharSpec] = _merged_table()


def _in_ranges(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def in_joiner_context(cp: int) -> bool:
    """True when *cp* belongs to a script where ZWNJ/ZWJ carry meaning."""
    return _in_ranges(cp, JOINER_CONTEXT_RANGES)


def classify_codepoint(cp: int) -> Optional[CharSpec]:
    """Return the :class:`CharSpec` for *cp*, or ``None`` if it looks ordinary.

    Explicit table entries win; the remaining cases are decided by block.
    """
    spec = SPEC_TABLE.get(cp)
    if spec is not None:
        return spec

    if TAG_BLOCK[0] <= cp <= TAG_BLOCK[1]:
        return _spec(
            cp, CharClass.TAG_CHARACTER, Severity.CRITICAL, REMOVE, REMOVE,
            note="Unicode tag character. Renders as nothing but is read by "
                 "language models - the ASCII smuggling / invisible prompt "
                 "injection channel.",
        )

    if VARIATION_SELECTORS[0] <= cp <= VARIATION_SELECTORS[1]:
        # VS16 (emoji presentation) and VS15 (text presentation) are normal.
        legitimate = cp in (0xFE0E, 0xFE0F)
        return _spec(
            cp, CharClass.VARIATION_SELECTOR,
            Severity.LOW if legitimate else Severity.MEDIUM,
            KEEP if legitimate else REVIEW,
            KEEP if legitimate else REMOVE,
            note="Emoji presentation selector." if legitimate else
                 "Variation selector outside emoji use. Can encode hidden bytes.",
            context_sensitive=True,
        )

    if VARIATION_SELECTORS_SUPPLEMENT[0] <= cp <= VARIATION_SELECTORS_SUPPLEMENT[1]:
        return _spec(
            cp, CharClass.VARIATION_SELECTOR, Severity.CRITICAL, REMOVE, REMOVE,
            note="Variation selector supplement. Almost never legitimate in "
                 "text and is a documented steganographic byte channel.",
        )

    if _in_ranges(cp, PRIVATE_USE_RANGES):
        return _spec(
            cp, CharClass.PRIVATE_USE, Severity.MEDIUM, REVIEW, REMOVE,
            note="Private use area. Meaning is undefined outside its "
                 "originating application; renders inconsistently.",
        )

    # Noncharacters: U+FDD0..U+FDEF and the last two of every plane.
    if 0xFDD0 <= cp <= 0xFDEF or (cp & 0xFFFE) == 0xFFFE:
        return _spec(
            cp, CharClass.NONCHARACTER, Severity.HIGH, REMOVE, REMOVE,
            note="Unicode noncharacter. Permanently reserved and invalid for "
                 "interchange.",
        )

    if cp == 0xFFFD:
        return _spec(
            cp, CharClass.REPLACEMENT, Severity.MEDIUM, REVIEW, REVIEW,
            note="Replacement character. Marks data already lost to a decoding "
                 "error somewhere upstream.",
        )

    # C0 and C1 controls, excluding tab / newline / carriage return.
    if (0x00 <= cp <= 0x1F and cp not in (0x09, 0x0A, 0x0D)) or 0x7F <= cp <= 0x9F:
        severity = Severity.CRITICAL if cp == 0x1B else Severity.HIGH
        note = (
            "Escape character. Start of an ANSI terminal escape sequence; can "
            "rewrite or spoof terminal output."
            if cp == 0x1B
            else "Control character with no meaning in text."
        )
        return _spec(cp, CharClass.CONTROL, severity, REMOVE, REMOVE, note=note)

    return None


def is_anomalous(cp: int) -> bool:
    """True when *cp* has a catalog entry worth reporting."""
    return classify_codepoint(cp) is not None


def iter_specs() -> Iterator[CharSpec]:
    """Iterate every explicitly tabulated code point (for docs and tests)."""
    for cp in sorted(SPEC_TABLE):
        yield SPEC_TABLE[cp]
