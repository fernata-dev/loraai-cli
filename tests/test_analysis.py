"""Tokenization, statistics, stylometry, markers and the synthetic assessment."""

from __future__ import annotations

import pytest

from loraai import textio
from loraai.analysis import analyze
from loraai.analysis import markers as markers_module
from loraai.analysis import statistics as statistics_module
from loraai.analysis import stylometry as stylometry_module
from loraai.analysis import synthetic as synthetic_module
from loraai.analysis.tokenizer import (
    paragraphs,
    protected_spans,
    sentences,
    words,
)
from loraai.models import Verdict

from .samples import (
    AI_STYLE,
    AI_STYLE_ARABIC,
    ARABIC_PROSE,
    HUMAN_STYLE,
    MARKDOWN_SOURCE,
    PYTHON_SOURCE,
)


class TestTokenizer:
    def test_contractions_stay_whole(self):
        assert words("don't stop") == ["don't", "stop"]

    def test_hyphenated_words_stay_whole(self):
        assert words("state-of-the-art") == ["state-of-the-art"]

    def test_decimals_are_one_token(self):
        assert words("costs 3.50 today") == ["costs", "3.50", "today"]

    def test_arabic_words(self):
        assert words("مرحبا بك في العالم") == ["مرحبا", "بك", "في", "العالم"]

    def test_abbreviations_do_not_split_sentences(self):
        assert len(sentences("Dr. Smith went home. He slept.")) == 2

    def test_decimal_does_not_split(self):
        assert len(sentences("It cost 3.50 in total.")) == 1

    def test_arabic_question_mark_splits(self):
        assert len(sentences("مرحبا بك. كيف حالك؟ أنا بخير.")) == 3

    def test_ellipsis_followed_by_lowercase_does_not_split(self):
        assert len(sentences("Wait... it continues here.")) == 1

    def test_paragraphs_split_on_blank_lines(self):
        assert len(paragraphs("one\n\ntwo\n\n\nthree")) == 3

    def test_empty_input(self):
        assert words("") == []
        assert sentences("") == []
        assert paragraphs("") == []

    def test_protected_spans_cover_urls_and_code(self):
        text = "See https://a.b/c and `code()` and [x](https://d.e)."
        kinds = {kind for _s, _e, kind in protected_spans(text)}
        assert {"url", "inline_code", "md_link"} <= kinds

    def test_protected_spans_do_not_overlap(self):
        spans = protected_spans(MARKDOWN_SOURCE)
        for (s1, e1, _), (s2, _e2, _) in zip(spans, spans[1:]):
            assert e1 <= s2


class TestStatistics:
    def test_counts(self):
        report = statistics_module.compute("One two. Three four five.", "en")
        assert report.words == 5
        assert report.sentences == 2
        assert report.unique_words == 5

    def test_mattr_is_length_stable(self):
        short = statistics_module.compute(" ".join(f"w{i}" for i in range(60)), "en")
        long = statistics_module.compute(" ".join(f"w{i}" for i in range(600)), "en")
        # Plain TTR collapses with length; MATTR should not.
        assert long.moving_ttr > 0.9
        assert abs(short.moving_ttr - long.moving_ttr) < 0.15

    def test_arabic_letters_are_counted(self):
        report = statistics_module.compute(ARABIC_PROSE, "ar")
        assert report.letters > 100
        assert report.words > 30

    def test_empty_text(self):
        report = statistics_module.compute("", "en")
        assert report.words == 0
        assert report.type_token_ratio == 0.0

    def test_serialisable(self):
        report = statistics_module.compute(HUMAN_STYLE, "en")
        assert isinstance(report.to_dict()["words"], int)


class TestStylometry:
    def test_uniform_text_has_low_burstiness(self):
        uniform = " ".join(["One two three four five." for _ in range(10)])
        varied = "Short. " + "A rather considerably longer sentence with many more words in it than the previous one. " * 3 + "Tiny."
        assert stylometry_module.compute(uniform, "en").burstiness < \
               stylometry_module.compute(varied, "en").burstiness

    def test_ai_style_has_more_transitions(self):
        ai = stylometry_module.compute(AI_STYLE, "en")
        human = stylometry_module.compute(HUMAN_STYLE, "en")
        assert ai.transition_density > human.transition_density

    def test_human_style_has_more_contractions(self):
        ai = stylometry_module.compute(AI_STYLE, "en")
        human = stylometry_module.compute(HUMAN_STYLE, "en")
        assert human.contraction_rate > ai.contraction_rate

    def test_repeated_openers_detected(self):
        style = stylometry_module.compute(AI_STYLE, "en")
        assert style.repeated_sentence_openers

    def test_empty_text(self):
        style = stylometry_module.compute("", "en")
        assert style.burstiness == 0.0


class TestMarkers:
    def test_ai_style_scores_higher_than_human(self):
        ai = markers_module.scan(AI_STYLE, "en")
        human = markers_module.scan(HUMAN_STYLE, "en")
        assert ai.weighted_density_per_1k > human.weighted_density_per_1k * 3

    def test_assistant_voice_is_critical(self):
        report = markers_module.scan(
            "As an AI language model, I cannot help with that request.", "en"
        )
        assert any(h.category == "assistant-voice" for h in report.hits)

    def test_arabic_markers(self):
        report = markers_module.scan(AI_STYLE_ARABIC, "ar")
        assert report.total >= 5
        assert any(h.category == "assistant-voice" for h in report.hits)

    def test_arabic_matches_with_and_without_tashkeel(self):
        plain = markers_module.scan("في عالم اليوم نعيش بسرعة", "ar")
        marked = markers_module.scan("في عالمِ اليومِ نعيشُ بسرعة", "ar")
        assert plain.total == marked.total == 1

    def test_human_prose_is_clean(self):
        assert markers_module.scan(
            "I went to the shop. It was closed. I walked home again.", "en"
        ).total == 0

    def test_rate_gated_rule_needs_bulk(self):
        # A single em dash in long text should not fire the rate-gated rule.
        text = "word " * 400 + "— once"
        assert not any(
            h.rule_id == "en.punctuation.em_dash"
            for h in markers_module.scan(text, "en").hits
        )

    def test_weighted_density_respects_severity(self):
        critical = markers_module.scan("As an AI language model, hello there.", "en")
        assert critical.weighted_density_per_1k > critical.density_per_1k


class TestSyntheticAssessment:
    def _assess(self, text, language="en"):
        stats = statistics_module.compute(text, language)
        style = stylometry_module.compute(text, language)
        marks = markers_module.scan(text, language)
        return synthetic_module.assess(text, stats, style, marks, language)

    def test_ai_style_scores_above_human_style(self):
        assert self._assess(AI_STYLE).score > self._assess(HUMAN_STYLE).score

    def test_ai_style_verdict(self):
        assert self._assess(AI_STYLE).verdict in (
            Verdict.LEANS_SYNTHETIC, Verdict.LIKELY_SYNTHETIC
        )

    def test_human_style_verdict(self):
        assert self._assess(HUMAN_STYLE).verdict in (
            Verdict.LIKELY_HUMAN, Verdict.LEANS_HUMAN, Verdict.INCONCLUSIVE
        )

    def test_short_text_is_never_given_a_strong_verdict(self):
        result = self._assess("AI is great. It helps a lot.")
        assert result.verdict is Verdict.INCONCLUSIVE
        assert result.reliability == "low"
        assert any("50 words" in c for c in result.caveats)

    def test_caveats_always_present(self):
        result = self._assess(AI_STYLE)
        assert len(result.caveats) >= 4
        assert any("not proof of authorship" in c for c in result.caveats)

    def test_every_signal_carries_its_measurement(self):
        for signal in self._assess(AI_STYLE).signals:
            assert signal.label and signal.detail
            assert signal.direction in ("synthetic", "human", "neutral")

    def test_empty_text(self):
        result = self._assess("")
        assert result.reliability == "none"

    def test_detector_is_swappable(self):
        class AlwaysHuman:
            name = "stub"

            def assess(self, text, statistics, style, markers, language):
                from loraai.models import SyntheticAssessment

                return SyntheticAssessment(verdict=Verdict.LIKELY_HUMAN, score=0.0)

        stats = statistics_module.compute(AI_STYLE, "en")
        style = stylometry_module.compute(AI_STYLE, "en")
        marks = markers_module.scan(AI_STYLE, "en")
        result = synthetic_module.assess(
            AI_STYLE, stats, style, marks, "en", detector=AlwaysHuman()
        )
        assert result.verdict is Verdict.LIKELY_HUMAN


class TestPipeline:
    def test_full_analysis(self):
        result = analyze(textio.from_text(AI_STYLE))
        assert result.statistics.words > 100
        assert result.synthetic.signals
        assert result.elapsed_ms >= 0

    def test_source_code_uses_comments_for_style(self, tmp_text_file):
        path = tmp_text_file(PYTHON_SOURCE, "module.py")
        result = analyze(textio.from_file(path))
        assert result.source.content_kind == "code"
        assert any("comments and docstrings" in w for w in result.warnings)
        # Style metrics come from the prose, so word count is far below the file.
        assert result.statistics.words < len(PYTHON_SOURCE.split())

    def test_markdown_is_analysed_as_prose(self, tmp_text_file):
        path = tmp_text_file(MARKDOWN_SOURCE, "doc.md")
        result = analyze(textio.from_file(path))
        assert result.source.content_kind == "markup"

    def test_empty_input_is_handled(self):
        result = analyze(textio.from_text(""))
        assert "empty" in result.warnings[0].lower()

    def test_arabic_pipeline(self):
        result = analyze(textio.from_text(ARABIC_PROSE))
        assert result.source.language == "ar"
        assert result.statistics.words > 30

    def test_unicode_forensics_covers_whole_code_file(self, tmp_text_file):
        tainted = PYTHON_SOURCE.replace("import os", "import os  # ‮gnirts")
        path = tmp_text_file(tainted, "evil.py")
        result = analyze(textio.from_file(path))
        assert any(f.code == "U+202E" for f in result.unicode.findings)
