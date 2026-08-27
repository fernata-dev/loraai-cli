"""Unicode reference tables used by the forensics and cleaning engines."""

from .invisible import (
    CharSpec,
    ARABIC_JOINERS,
    BIDI_CONTROLS,
    TAG_BLOCK,
    VARIATION_SELECTORS,
    ZERO_WIDTH,
    classify_codepoint,
    is_anomalous,
    iter_specs,
)
from .confusables import CONFUSABLES, skeleton, confusable_target
from .scripts import script_of, script_histogram, dominant_language, is_mixed_script_word

__all__ = [
    "CharSpec",
    "ARABIC_JOINERS",
    "BIDI_CONTROLS",
    "TAG_BLOCK",
    "VARIATION_SELECTORS",
    "ZERO_WIDTH",
    "classify_codepoint",
    "is_anomalous",
    "iter_specs",
    "CONFUSABLES",
    "skeleton",
    "confusable_target",
    "script_of",
    "script_histogram",
    "dominant_language",
    "is_mixed_script_word",
]
