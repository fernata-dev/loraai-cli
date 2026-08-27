"""Cleaning.

The property under test throughout: cleaning removes invisible characters and
leaves every visible one alone. That is what makes it safe to run on text in a
script the operator cannot read.
"""

from __future__ import annotations

import unicodedata

import pytest

from loraai.analysis.payload import decode_payloads, encode_tags
from loraai.cleaning import clean, get_profile, verify_semantics
from loraai.cleaning.rules import PROFILES

from .samples import (
    ARABIC_PROSE,
    ARABIC_WITH_MARKS,
    BOM,
    HUMAN_STYLE,
    NBSP,
    PDF,
    RLO,
    WJ,
    ZWJ,
    ZWNJ,
    ZWSP,
)

PROFILE_NAMES = sorted(PROFILES)


def visible(text: str) -> str:
    """Letters, digits and combining marks - what a reader actually sees."""
    return "".join(c for c in text if unicodedata.category(c)[0] in ("L", "N", "M"))


class TestRemoval:
    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_zero_width_space_is_removed(self, profile):
        result = clean(f"hello{ZWSP}world", profile)
        assert ZWSP not in result.cleaned
        assert result.cleaned == "helloworld"

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_tag_characters_are_removed(self, profile):
        text = "visible" + encode_tags("hidden payload")
        result = clean(text, profile)
        assert result.cleaned == "visible"
        assert decode_payloads(result.cleaned) == []

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_bidi_override_is_removed(self, profile):
        result = clean(f"a{RLO}b", profile)
        assert RLO not in result.cleaned

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_control_characters_are_removed(self, profile):
        result = clean("before\x1b[31mafter", profile)
        assert "\x1b" not in result.cleaned

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_bom_and_word_joiner_are_removed(self, profile):
        result = clean(f"a{BOM}b{WJ}c", profile)
        assert result.cleaned == "abc"

    def test_nbsp_becomes_a_plain_space(self):
        result = clean(f"a{NBSP}b", "safe")
        assert result.cleaned == "a b"


class TestArabicSafety:
    """These are the tests that matter most for correctness."""

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_arabic_prose_is_untouched(self, profile):
        result = clean(ARABIC_PROSE, profile)
        assert visible(result.cleaned) == visible(ARABIC_PROSE)
        assert result.semantic_preserved

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_diacritics_survive(self, profile):
        result = clean(ARABIC_WITH_MARKS, profile)
        before = sum(1 for c in ARABIC_WITH_MARKS if unicodedata.combining(c))
        after = sum(1 for c in result.cleaned if unicodedata.combining(c))
        assert before == after > 0
        assert result.semantic_preserved

    def test_safe_profile_keeps_arabic_joiner(self):
        result = clean(f"بك{ZWNJ}في", "safe")
        assert ZWNJ in result.cleaned

    def test_safe_profile_removes_orphan_joiner_in_latin(self):
        # The safe profile is conservative; standard strips a joiner that is
        # doing no work.
        assert ZWNJ not in clean(f"ab{ZWNJ}cd", "standard").cleaned

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_emoji_zwj_sequences_survive(self, profile):
        family = f"\U0001F468{ZWJ}\U0001F469{ZWJ}\U0001F467"
        assert clean(family, profile).cleaned == family

    @pytest.mark.parametrize("profile", PROFILE_NAMES)
    def test_emoji_variation_selector_survives(self, profile):
        assert clean("❤️", profile).cleaned == "❤️"


class TestSemanticVerification:
    def test_identical_text_verifies(self):
        ok, notes = verify_semantics("hello", "hello")
        assert ok and notes

    def test_changed_letter_fails_verification(self):
        ok, notes = verify_semantics("hello", "hallo")
        assert not ok
        assert "changed" in notes[0]

    def test_whitespace_change_still_verifies(self):
        ok, _ = verify_semantics("a  b", "a b")
        assert ok

    @pytest.mark.parametrize("profile", ["safe", "standard"])
    def test_conservative_profiles_always_preserve(self, profile):
        for sample in (ARABIC_PROSE, HUMAN_STYLE, f"x{ZWSP}y{RLO}z"):
            assert clean(sample, profile).semantic_preserved


class TestProfiles:
    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="Unknown cleaning profile"):
            clean("x", "nuclear")

    def test_profiles_are_ordered_by_thoroughness(self):
        text = f"a{ZWSP}b{NBSP}c{ZWNJ}d ‘quoted’ e"
        counts = [clean(text, name).total_changes for name in ("safe", "standard", "aggressive")]
        assert counts[0] <= counts[1] <= counts[2]

    def test_aggressive_straightens_typography(self):
        result = clean("“quoted” — dash… ", "aggressive")
        assert '"quoted"' in result.cleaned
        assert "..." in result.cleaned

    def test_aggressive_repairs_homoglyphs(self):
        result = clean("log in at pаypal", "aggressive")
        assert "paypal" in result.cleaned
        assert any("homoglyph" in n for n in result.semantic_notes)

    def test_safe_does_not_repair_homoglyphs(self):
        assert "pаypal" in clean("log in at pаypal", "safe").cleaned

    def test_get_profile(self):
        assert get_profile("safe").name == "safe"


class TestOutput:
    def test_output_is_valid_utf8(self):
        for profile in PROFILE_NAMES:
            for sample in (ARABIC_PROSE, HUMAN_STYLE, f"x{ZWSP}{RLO}y"):
                encoded = clean(sample, profile).cleaned.encode("utf-8")
                assert encoded.decode("utf-8")

    def test_empty_input(self):
        result = clean("", "safe")
        assert result.cleaned == ""
        assert not result.changed

    def test_clean_text_is_unchanged(self):
        assert not clean(HUMAN_STYLE, "safe").changed

    def test_changes_are_recorded_with_positions(self):
        result = clean(f"ab{ZWSP}cd", "safe")
        assert result.changes[0].position == 2
        assert result.changes[0].action == "removed"

    def test_serialisable(self):
        payload = clean(f"a{ZWSP}b", "safe").to_dict()
        assert payload["total_changes"] == 1
        assert payload["semantic_preserved"] is True

    def test_tidy_whitespace_collapses_runs(self):
        result = clean("a   b\n\n\n\n\nc   ", "standard")
        assert "   " not in result.cleaned
        assert "\n\n\n" not in result.cleaned
