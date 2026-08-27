"""Unicode forensics: detection must be exact, and Arabic must survive."""

from __future__ import annotations

import pytest

from loraai.analysis.unicode_forensics import scan, severity_breakdown
from loraai.models import CharClass, Severity
from loraai.unicode_data.confusables import (
    confusable_target,
    is_cross_script_confusable,
    skeleton,
)
from loraai.unicode_data.invisible import classify_codepoint
from loraai.unicode_data.scripts import (
    dominant_language,
    is_mixed_script_word,
    script_histogram,
)

from .samples import ARABIC_PROSE, ARABIC_WITH_MARKS, BOM, HUMAN_STYLE, NBSP, PDF, RLO, WJ, ZWJ, ZWNJ, ZWSP


class TestZeroWidth:
    def test_zwsp_is_found(self):
        report = scan(f"hello{ZWSP}world")
        assert report.total == 1
        assert report.findings[0].codepoint == 0x200B
        assert report.findings[0].char_class is CharClass.ZERO_WIDTH
        assert report.findings[0].recommended_action == "remove"

    def test_word_joiner_and_bom_are_found(self):
        report = scan(f"a{WJ}b{BOM}c")
        codes = {f.code for f in report.findings}
        assert codes == {"U+2060", "U+FEFF"}

    def test_soft_hyphen_is_found(self):
        report = scan("soft­hyphen")
        assert report.findings[0].code == "U+00AD"

    @pytest.mark.parametrize("cp", [0x200B, 0x2060, 0xFEFF, 0x180E, 0x3164])
    def test_known_zero_width_characters_are_catalogued(self, cp):
        spec = classify_codepoint(cp)
        assert spec is not None
        assert spec.safe_action == "remove"

    def test_clean_text_yields_nothing(self):
        report = scan("Perfectly ordinary ASCII text, with punctuation!")
        assert report.total == 0
        assert report.max_severity is Severity.INFO


class TestArabicSafety:
    """The property that makes this tool safe to point at Arabic."""

    def test_joiner_between_arabic_letters_is_legitimate(self):
        report = scan(f"بك{ZWNJ}في")
        assert report.total == 1
        finding = report.findings[0]
        assert finding.code == "U+200C"
        assert finding.severity is Severity.INFO
        assert finding.recommended_action == "keep"

    def test_joiner_between_latin_letters_is_suspicious(self):
        report = scan(f"ab{ZWNJ}cd")
        finding = report.findings[0]
        assert finding.severity is Severity.HIGH
        assert finding.recommended_action == "remove"

    def test_emoji_zwj_sequence_is_not_flagged_as_suspicious(self):
        family = f"\U0001F468{ZWJ}\U0001F469{ZWJ}\U0001F467"
        report = scan(family)
        assert all(f.severity is Severity.INFO for f in report.findings)

    def test_arabic_prose_is_clean(self):
        report = scan(ARABIC_PROSE)
        assert report.total == 0

    def test_diacritics_are_never_flagged(self):
        report = scan(ARABIC_WITH_MARKS)
        # Only the joiner and the RTL mark, both benign here.
        assert all(f.severity.rank <= Severity.MEDIUM.rank for f in report.findings)
        assert not any(0x064B <= f.codepoint <= 0x0652 for f in report.findings)


class TestBidi:
    def test_override_is_critical(self):
        report = scan(f"text{RLO}reversed{PDF}")
        override = next(f for f in report.findings if f.code == "U+202E")
        assert override.severity is Severity.CRITICAL
        assert override.char_class is CharClass.BIDI_OVERRIDE

    def test_isolates_are_not_critical(self):
        report = scan("start⁧arabic⁩end")
        assert all(f.severity.rank < Severity.CRITICAL.rank for f in report.findings)


class TestConfusables:
    def test_cyrillic_homoglyph_in_latin_word(self):
        report = scan("log in at pаypal now")  # Cyrillic а
        confusables = [f for f in report.findings if f.char_class is CharClass.CONFUSABLE]
        assert len(confusables) == 1
        assert confusables[0].replacement == "a"
        assert "pаypal" in report.mixed_script_words

    def test_pure_latin_word_is_not_flagged(self):
        report = scan("log in at paypal now")
        assert not [f for f in report.findings if f.char_class is CharClass.CONFUSABLE]

    def test_skeleton_collapses_lookalikes(self):
        assert skeleton("pаypal") == skeleton("paypal")
        assert skeleton("ＡＢＣ") == "abc"

    def test_cross_script_detection(self):
        assert is_cross_script_confusable("а")  # Cyrillic
        assert not is_cross_script_confusable("a")  # Latin
        assert confusable_target("Ο") == "O"  # Greek omicron

    def test_mixed_script_word(self):
        assert is_mixed_script_word("pаypal")
        assert not is_mixed_script_word("paypal")
        assert not is_mixed_script_word("مرحبا")


class TestControlAndExotic:
    def test_escape_character_is_critical(self):
        report = scan("before\x1b[31mafter")
        escape = next(f for f in report.findings if f.codepoint == 0x1B)
        assert escape.severity is Severity.CRITICAL

    def test_nbsp_is_replaced_not_removed(self):
        report = scan(f"a{NBSP}b")
        finding = report.findings[0]
        assert finding.recommended_action == "replace"
        assert finding.replacement == " "

    def test_tag_characters_are_critical(self):
        report = scan("x\U000E0041y")
        assert report.findings[0].char_class is CharClass.TAG_CHARACTER
        assert report.findings[0].severity is Severity.CRITICAL

    def test_variation_selector_supplement_is_critical(self):
        report = scan("x\U000E0100y")
        assert report.findings[0].severity is Severity.CRITICAL

    def test_emoji_variation_selector_is_benign(self):
        report = scan("❤️")
        assert all(f.severity is Severity.LOW for f in report.findings)


class TestReportShape:
    def test_positions_are_accurate(self):
        text = f"line one\nline{ZWSP}two"
        finding = scan(text).findings[0]
        assert finding.line == 2
        assert text[finding.position] == ZWSP

    def test_context_is_terminal_safe(self):
        report = scan(f"before\x1b[31m{ZWSP}after")
        for finding in report.findings:
            assert "\x1b" not in finding.context

    def test_severity_breakdown(self):
        report = scan(f"{ZWSP}\x1b")
        breakdown = severity_breakdown(report)
        assert breakdown.get("critical") == 1
        assert breakdown.get("high") == 1

    def test_scripts_and_language(self):
        assert dominant_language(ARABIC_PROSE) == "ar"
        assert dominant_language(HUMAN_STYLE) == "en"
        assert "Arabic" in script_histogram(ARABIC_PROSE)

    def test_normalization_is_reported(self):
        report = scan("café")  # decomposed é
        assert report.normalization["is_nfc"] is False

    def test_empty_input(self):
        report = scan("")
        assert report.total == 0
        assert report.notes
