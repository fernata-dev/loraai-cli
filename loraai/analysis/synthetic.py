"""Probabilistic assessment of whether text reads as machine-generated.

How the score is built
----------------------
Each measurement contributes a **log-odds weight**: positive leans synthetic,
negative leans human, zero is neutral. The weights are summed and squashed
through a logistic function to give a score in ``[0, 1]``. This is deliberately
an additive-evidence model rather than a trained classifier, because it means
every point of the score can be traced to a named signal with a raw value
attached -- the UI shows the reader exactly why the number moved, and a reader
who disagrees with a weight can discount it.

Calibration
-----------
The thresholds below come from typical observed ranges of each measurement in
edited human prose versus default-sampled model output. They are *heuristics
chosen by hand*, not parameters fitted to a labelled corpus, and this module
says so wherever the result is displayed. A trained classifier would be more
accurate; see :class:`SyntheticDetector` for the extension point.

Deliberate scope limits
-----------------------
* Style only. Invisible characters and embedded payloads are evidence about
  *processing*, not authorship -- a human can paste a zero-width space and a
  model can emit clean ASCII -- so they are reported separately in the
  provenance section and never silently inflate this score.
* Short text is not assessable. Below roughly 50 words the measurements are
  dominated by noise, and the verdict is clamped to INCONCLUSIVE regardless of
  what the signals say.
* No claim of proof. The strongest label available is "LIKELY", and the
  caveats travel with the result into every output format.
"""

from __future__ import annotations

import math
from typing import List, Optional, Protocol

from ..models import (
    MarkerReport,
    StatisticsReport,
    StyleReport,
    Severity,
    Signal,
    SyntheticAssessment,
    Verdict,
)

#: Below this many words the measurements are noise-dominated.
MIN_WORDS_FOR_ASSESSMENT = 50
#: Above this many words every signal is on solid footing.
WORDS_FOR_GOOD_RELIABILITY = 250

_VERDICT_THRESHOLDS = (
    (0.20, Verdict.LIKELY_HUMAN),
    (0.40, Verdict.LEANS_HUMAN),
    (0.60, Verdict.INCONCLUSIVE),
    (0.80, Verdict.LEANS_SYNTHETIC),
    (1.01, Verdict.LIKELY_SYNTHETIC),
)


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _ramp(value: float, low: float, high: float, weight: float) -> float:
    """Linearly map *value* from ``[low, high]`` onto ``[0, weight]``.

    Clamped at both ends. ``low`` may exceed ``high`` to invert the direction,
    which is how "less of this means more synthetic" signals are expressed.
    """
    if low == high:
        return 0.0
    fraction = (value - low) / (high - low)
    fraction = max(0.0, min(1.0, fraction))
    return fraction * weight


class SyntheticDetector(Protocol):
    """Extension point for a real classifier.

    The heuristic engine below is the default implementation. A model-based
    detector can be dropped in without touching the CLI, TUI or report writers
    as long as it returns a :class:`SyntheticAssessment`.
    """

    name: str

    def assess(
        self,
        text: str,
        statistics: StatisticsReport,
        style: StyleReport,
        markers: MarkerReport,
        language: str,
    ) -> SyntheticAssessment:  # pragma: no cover - protocol definition
        ...


class HeuristicDetector:
    """The built-in additive-evidence detector."""

    name = "heuristic-v1"

    def assess(
        self,
        text: str,
        statistics: StatisticsReport,
        style: StyleReport,
        markers: MarkerReport,
        language: str = "en",
    ) -> SyntheticAssessment:
        assessment = SyntheticAssessment()
        signals: List[Signal] = []
        word_count = statistics.words

        if word_count == 0:
            assessment.caveats.append("No words to assess.")
            assessment.reliability = "none"
            return assessment

        # --- rhythm: the single most informative family --------------------
        if statistics.sentences >= 5:
            weight = _ramp(style.burstiness, -0.35, -0.80, 1.5)
            signals.append(
                Signal(
                    key="burstiness",
                    label="Sentence-length variation",
                    value=style.burstiness,
                    weight=weight,
                    detail=(
                        f"Burstiness {style.burstiness:+.2f}. Human prose usually "
                        f"swings between long and short sentences; values below "
                        f"-0.60 mean unusually even pacing."
                    ),
                )
            )

            cv_weight = _ramp(style.sentence_length_cv, 0.55, 0.15, 1.3)
            signals.append(
                Signal(
                    key="sentence_cv",
                    label="Sentence-length spread",
                    value=style.sentence_length_cv,
                    weight=cv_weight,
                    detail=(
                        f"Coefficient of variation {style.sentence_length_cv:.2f}. "
                        f"Edited human writing typically lands near 0.5-0.9."
                    ),
                )
            )
        else:
            assessment.caveats.append(
                "Fewer than 5 sentences: rhythm signals were not measured."
            )

        # --- AI-writing markers --------------------------------------------
        marker_weight = _ramp(markers.weighted_density_per_1k, 5.0, 30.0, 1.6)
        signals.append(
            Signal(
                key="marker_density",
                label="AI-writing tells",
                value=markers.weighted_density_per_1k,
                weight=marker_weight,
                detail=(
                    f"{markers.total} marker(s), {markers.weighted_density_per_1k:.1f} "
                    f"severity-weighted per 1000 words. Covers inflated vocabulary, "
                    f"formulaic transitions, vague attribution and stock phrasing."
                ),
            )
        )

        # An explicit assistant voice is near-conclusive on its own.
        assistant_hits = sum(
            1 for h in markers.hits if h.category == "assistant-voice"
        )
        if assistant_hits:
            signals.append(
                Signal(
                    key="assistant_voice",
                    label="Chat-assistant phrasing",
                    value=float(assistant_hits),
                    weight=min(3.0, 1.8 + 0.4 * assistant_hits),
                    detail=(
                        f"{assistant_hits} phrase(s) that only occur in "
                        f"conversational-assistant output, such as an explicit "
                        f"model self-reference or a chat sign-off."
                    ),
                )
            )

        # --- discourse scaffolding -----------------------------------------
        if word_count >= 80:
            transition_weight = _ramp(style.transition_density, 1.2, 6.0, 0.9)
            signals.append(
                Signal(
                    key="transitions",
                    label="Discourse-marker density",
                    value=style.transition_density,
                    weight=transition_weight,
                    detail=(
                        f"{style.transition_density:.1f} formal connectives per "
                        f"100 words (however, moreover, furthermore...)."
                    ),
                )
            )

        # --- structural repetition -----------------------------------------
        opener_repeats = sum(c for _, c in style.repeated_sentence_openers)
        if statistics.sentences >= 6:
            opener_weight = _ramp(
                opener_repeats / max(1, statistics.sentences), 0.15, 0.55, 0.9
            )
            signals.append(
                Signal(
                    key="repeated_openers",
                    label="Repeated sentence openings",
                    value=float(opener_repeats),
                    weight=opener_weight,
                    detail=(
                        f"{opener_repeats} sentence(s) reuse an opening pair of "
                        f"words across {statistics.sentences} sentences."
                    ),
                )
            )

        if statistics.paragraphs >= 3:
            uniformity_weight = _ramp(style.paragraph_uniformity, 0.55, 0.90, 0.8)
            signals.append(
                Signal(
                    key="paragraph_uniformity",
                    label="Paragraph-length uniformity",
                    value=style.paragraph_uniformity,
                    weight=uniformity_weight,
                    detail=(
                        f"Uniformity {style.paragraph_uniformity:.2f} across "
                        f"{statistics.paragraphs} paragraphs. Near 1.0 means every "
                        f"paragraph is close to the same length."
                    ),
                )
            )

        # --- register -------------------------------------------------------
        if language in ("en", "mixed") and word_count >= 120:
            # Absent contractions lean formal-or-generated; present ones lean
            # human. Weak in both directions: academic writing has none either.
            if style.contraction_rate <= 0.5:
                weight = 0.45
                detail = "No contractions. Common in generated and in formal prose."
            else:
                weight = -_ramp(style.contraction_rate, 1.0, 12.0, 0.7)
                detail = (
                    f"{style.contraction_rate:.1f} contractions per 1000 words - "
                    f"an informal register models reach for less readily."
                )
            signals.append(
                Signal(
                    key="contractions",
                    label="Contraction use",
                    value=style.contraction_rate,
                    weight=weight,
                    detail=detail,
                    experimental=True,
                )
            )

        # --- lexical texture -------------------------------------------------
        if word_count >= 100:
            # Very low diversity within a window suggests looping phrasing.
            diversity_weight = _ramp(statistics.moving_ttr, 0.78, 0.58, 0.7)
            signals.append(
                Signal(
                    key="lexical_diversity",
                    label="Lexical diversity (MATTR)",
                    value=statistics.moving_ttr,
                    weight=diversity_weight,
                    detail=(
                        f"Moving-average type-token ratio {statistics.moving_ttr:.2f} "
                        f"over 50-word windows. Length-stable, unlike plain TTR."
                    ),
                )
            )

            ngram_weight = _ramp(style.ngram_repetition_rate, 0.04, 0.20, 0.7)
            signals.append(
                Signal(
                    key="ngram_repetition",
                    label="Repeated phrasing",
                    value=style.ngram_repetition_rate,
                    weight=ngram_weight,
                    detail=(
                        f"{style.ngram_repetition_rate * 100:.1f}% of 4-word "
                        f"sequences occur more than once."
                    ),
                )
            )

        # --- aggregate --------------------------------------------------------
        total = sum(s.weight for s in signals)
        # Centre the logistic so a neutral signal set gives ~0.5, and damp the
        # slope so a single signal cannot swing the verdict on its own.
        assessment.score = _logistic(total * 0.85 - 0.35)
        assessment.signals = signals

        # --- reliability and clamping ------------------------------------------
        if word_count < MIN_WORDS_FOR_ASSESSMENT:
            assessment.reliability = "low"
            assessment.caveats.insert(
                0,
                f"Only {word_count} words. Below {MIN_WORDS_FOR_ASSESSMENT} words "
                f"the measurements are dominated by noise, so no verdict beyond "
                f"INCONCLUSIVE is reported.",
            )
        elif word_count < WORDS_FOR_GOOD_RELIABILITY:
            assessment.reliability = "moderate"
        else:
            assessment.reliability = "good"

        evidence = sum(abs(s.weight) for s in signals)
        assessment.confidence = min(1.0, evidence / 4.0) * (
            0.35 if assessment.reliability == "low"
            else 0.75 if assessment.reliability == "moderate"
            else 1.0
        )

        assessment.verdict = _verdict_for(assessment.score)

        # A short text gets no strong verdict unless something near-conclusive
        # fired, in which case the marker itself is the finding, not the score.
        if assessment.reliability == "low" and not assistant_hits:
            assessment.verdict = Verdict.INCONCLUSIVE

        assessment.caveats.extend(_standard_caveats(language))
        return assessment


def _verdict_for(score: float) -> Verdict:
    for threshold, verdict in _VERDICT_THRESHOLDS:
        if score < threshold:
            return verdict
    return Verdict.INCONCLUSIVE


def _standard_caveats(language: str) -> List[str]:
    caveats = [
        "This is a statistical reading of writing style, not proof of "
        "authorship. It cannot establish who or what wrote the text.",
        "Weights are hand-calibrated heuristics, not parameters fitted to a "
        "labelled corpus. Treat the score as a prompt to look closer.",
        "Non-native, heavily edited, formal and templated human writing all "
        "score higher here. A high score is not an accusation.",
        "Text written by a model and then revised by a person can score low.",
    ]
    if language == "ar":
        caveats.append(
            "Arabic thresholds are less validated than English ones; the "
            "marker rules cover common formal-register phrasing that also "
            "appears in ordinary journalism."
        )
    elif language == "mixed":
        caveats.append(
            "Mixed-script input: rhythm measurements span two writing systems "
            "with different sentence conventions, which widens the error bars."
        )
    return caveats


#: Default detector instance used by the pipeline.
DEFAULT_DETECTOR: SyntheticDetector = HeuristicDetector()


def assess(
    text: str,
    statistics: StatisticsReport,
    style: StyleReport,
    markers: MarkerReport,
    language: str = "en",
    detector: Optional[SyntheticDetector] = None,
) -> SyntheticAssessment:
    """Assess *text* with *detector* (default: the built-in heuristic)."""
    engine = detector or DEFAULT_DETECTOR
    return engine.assess(text, statistics, style, markers, language)
