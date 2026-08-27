"""Cleaning profiles.

Three profiles, differing only in how much benefit of the doubt they give a
character that *might* be doing legitimate work:

``safe``
    Removes only what has no legitimate use anywhere: tag characters,
    variation-selector supplements, zero-width spaces and word joiners,
    control characters, bidi overrides, noncharacters. Normalises exotic
    whitespace to a plain space. Preserves Arabic and Indic joiners, bidi
    isolates, emoji selectors, and every combining mark. This is the default
    because silently corrupting someone's Arabic is worse than leaving one
    ambiguous character in place.

``standard``
    Adds: joiners outside a script that uses them, deprecated bidi
    embeddings, NFC normalisation, whitespace tidying.

``aggressive``
    Adds: every bidi control, every non-emoji variation selector, private-use
    characters, straightened typography, and homoglyph repair. Changes visible
    characters, so it reports semantic preservation as REVIEW rather than PASS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass(frozen=True)
class CleanProfile:
    """A named cleaning policy."""

    name: str
    description: str
    #: Character classes removed outright.
    remove_classes: FrozenSet[str] = field(default_factory=frozenset)
    #: Character classes replaced with their spec replacement.
    replace_classes: FrozenSet[str] = field(default_factory=frozenset)
    #: Remove ZWNJ/ZWJ that are not between joining-script characters.
    strip_orphan_joiners: bool = False
    #: Remove ZWNJ/ZWJ even where they are doing legitimate work.
    strip_all_joiners: bool = False
    #: Remove every bidi control, including isolates.
    strip_all_bidi: bool = False
    #: Replace homoglyphs with the character they imitate.
    fix_confusables: bool = False
    #: Straighten curly quotes, dashes and ellipses to ASCII.
    normalize_typography: bool = False
    #: Unicode normalisation form applied at the end, or ``None``.
    normalize_form: str | None = None
    #: Collapse repeated spaces, strip trailing whitespace, cap blank lines.
    tidy_whitespace: bool = False


#: Classes that are invisible and never legitimate. Removed by every profile.
_ALWAYS_REMOVE = frozenset(
    {
        "zero-width",
        "tag-character",
        "invisible-math",
        "invisible-format",
        "control",
        "bidi-override",
        "noncharacter",
    }
)

_ALWAYS_REPLACE = frozenset({"exotic-whitespace", "line-separator"})

SAFE = CleanProfile(
    name="safe",
    description=(
        "Remove what is never legitimate; preserve anything that might be "
        "doing real work. Semantics guaranteed intact."
    ),
    remove_classes=_ALWAYS_REMOVE,
    replace_classes=_ALWAYS_REPLACE,
    strip_orphan_joiners=False,
)

STANDARD = CleanProfile(
    name="standard",
    description=(
        "Safe, plus joiners outside their script, deprecated bidi embeddings, "
        "NFC normalisation and whitespace tidying."
    ),
    remove_classes=_ALWAYS_REMOVE | {"variation-selector"},
    replace_classes=_ALWAYS_REPLACE,
    strip_orphan_joiners=True,
    normalize_form="NFC",
    tidy_whitespace=True,
)

AGGRESSIVE = CleanProfile(
    name="aggressive",
    description=(
        "Everything standard does, plus all bidi controls, private-use "
        "characters, straightened typography and homoglyph repair. Changes "
        "visible characters."
    ),
    remove_classes=_ALWAYS_REMOVE | {"variation-selector", "private-use", "deprecated"},
    replace_classes=_ALWAYS_REPLACE,
    strip_orphan_joiners=True,
    strip_all_bidi=True,
    fix_confusables=True,
    normalize_typography=True,
    normalize_form="NFC",
    tidy_whitespace=True,
)

PROFILES = {p.name: p for p in (SAFE, STANDARD, AGGRESSIVE)}

DEFAULT_PROFILE = "safe"


def get_profile(name: str) -> CleanProfile:
    """Look up a profile by name."""
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"Unknown cleaning profile {name!r}. "
            f"Available: {', '.join(sorted(PROFILES))}"
        ) from None


#: Typography straightening applied by the aggressive profile. Kept separate
#: from the anomaly table because these characters are perfectly valid -- they
#: are only normalised on explicit request.
TYPOGRAPHY_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "―": "-", "−": "-",
    "‐": "-", "‑": "-",
    "…": "...",
    "«": '"', "»": '"',
    "‹": "'", "›": "'",
    "ʼ": "'", "ʻ": "'",
}
