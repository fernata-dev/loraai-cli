"""Stylometric measurement: rhythm, repetition, punctuation, register.

These are the signals that separate the *texture* of writing from its content.
None of them identifies an author or proves a generator on its own -- they are
inputs to a weighted assessment, and each is reported with its raw value so a
reader can disagree with the weighting.

The single most informative measure here is burstiness: the tendency of human
prose to swing between long and short sentences. Text produced by a model
sampling near its mode tends to regress toward a comfortable middle length,
which shows up as low variance.
"""

from __future__ import annotations

import math
import re
import statistics as stats
from collections import Counter
from typing import Dict, List, Sequence, Tuple

from ..models import StyleReport
from .tokenizer import paragraphs, sentences, words

#: Discourse markers that models overuse as paragraph glue.
TRANSITIONS_EN = frozenset(
    """
    however moreover furthermore additionally consequently therefore thus
    nevertheless nonetheless accordingly hence subsequently ultimately
    notably importantly significantly essentially fundamentally
    """.split()
)

TRANSITIONS_AR = (
    "علاوة على ذلك",
    "بالإضافة إلى ذلك",
    "ومع ذلك",
    "في الختام",
    "وبالتالي",
    "من ناحية أخرى",
    "وفي المقابل",
    "الجدير بالذكر",
    "ومن الجدير بالذكر",
    "بشكل عام",
    "في نهاية المطاف",
)

#: High-frequency function words. Their relative rates are a stable authorial
#: fingerprint and shift measurably in generated text.
FUNCTION_WORDS_EN = (
    "the a an and or but if while of to in for on with at by from as that "
    "this these those it its is are was were be been being have has had do "
    "does did not no we you they he she i our your their his her them us"
).split()

FUNCTION_WORDS_AR = (
    "في من على إلى عن مع هذا هذه ذلك التي الذي كان كانت قد لا ما هو هي "
    "أن إن كل بعض عند بين حيث لكن أو و ثم"
).split()

_PASSIVE_EN = re.compile(
    r"\b(?:is|are|was|were|be|been|being|get|gets|got)\s+"
    r"(?:\w+ly\s+)?\w+(?:ed|en|wn|ne|de|nt)\b",
    re.IGNORECASE,
)

_CONTRACTION = re.compile(r"\b\w+['’](?:t|s|re|ve|ll|d|m)\b", re.IGNORECASE)

_TRACKED_PUNCTUATION = ",.;:!?—–-()[]{}\"'…«»؛،؟"


def _coefficient_of_variation(values: Sequence[float]) -> float:
    """Standard deviation over mean. Scale-free measure of spread."""
    usable = [v for v in values if v > 0]
    if len(usable) < 2:
        return 0.0
    mean = sum(usable) / len(usable)
    if mean == 0:
        return 0.0
    return stats.pstdev(usable) / mean


def burstiness(lengths: Sequence[int]) -> float:
    """Burstiness coefficient in ``[-1, 1]``.

    ``(sigma - mu) / (sigma + mu)``. Values near -1 mean every sentence is the
    same length; values above 0 mean the text swings widely. Human prose
    typically lands between -0.6 and -0.1; heavily regularised text sits lower.
    """
    usable = [float(v) for v in lengths if v > 0]
    if len(usable) < 3:
        return 0.0
    mean = sum(usable) / len(usable)
    sigma = stats.pstdev(usable)
    if mean + sigma == 0:
        return 0.0
    return (sigma - mean) / (sigma + mean)


def shannon_entropy(counts: Sequence[int]) -> float:
    """Entropy in bits over a count distribution."""
    total = sum(counts)
    if total <= 0:
        return 0.0
    entropy = 0.0
    for count in counts:
        if count <= 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def repeated_ngrams(
    tokens: Sequence[str], n: int = 4, min_count: int = 2, limit: int = 15
) -> List[Tuple[str, int]]:
    """Word n-grams that occur more than once, most frequent first."""
    if len(tokens) < n:
        return []
    grams = Counter(
        " ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)
    )
    repeated = [(gram, count) for gram, count in grams.items() if count >= min_count]
    repeated.sort(key=lambda item: (-item[1], item[0]))
    return repeated[:limit]


def repeated_openers(
    sentence_list: Sequence[str], limit: int = 10
) -> List[Tuple[str, int]]:
    """Opening bigrams reused across sentences.

    Models fall into rhythmic habits -- every third sentence starting "This
    means" or "It is important" -- more readily than people do.
    """
    openers: Counter = Counter()
    for sentence in sentence_list:
        tokens = words(sentence)
        if len(tokens) >= 2:
            openers[" ".join(t.lower() for t in tokens[:2])] += 1
    repeated = [(opener, count) for opener, count in openers.items() if count >= 2]
    repeated.sort(key=lambda item: (-item[1], item[0]))
    return repeated[:limit]


def _transition_density(text: str, tokens: Sequence[str], language: str) -> float:
    """Discourse markers per 100 words."""
    if not tokens:
        return 0.0
    hits = 0
    if language in ("ar", "mixed"):
        lowered_text = text
        for phrase in TRANSITIONS_AR:
            hits += lowered_text.count(phrase)
    if language in ("en", "mixed", "unknown", "other"):
        lowered = [t.lower() for t in tokens]
        hits += sum(1 for t in lowered if t in TRANSITIONS_EN)
    return hits / len(tokens) * 100


def compute(text: str, language: str = "unknown") -> StyleReport:
    """Compute the full stylometric profile of *text*."""
    report = StyleReport()
    if not text.strip():
        return report

    token_list = words(text)
    lowered = [t.lower() for t in token_list]
    sentence_list = sentences(text)
    paragraph_list = paragraphs(text)
    word_count = len(token_list)

    # --- rhythm -----------------------------------------------------------
    sentence_lengths = [len(words(s)) for s in sentence_list]
    report.burstiness = burstiness(sentence_lengths)
    report.sentence_length_cv = _coefficient_of_variation(sentence_lengths)
    report.word_length_cv = _coefficient_of_variation([len(t) for t in token_list])

    paragraph_lengths = [len(words(p)) for p in paragraph_list]
    if len(paragraph_lengths) >= 3:
        cv = _coefficient_of_variation(paragraph_lengths)
        # 1.0 means every paragraph is the same size.
        report.paragraph_uniformity = max(0.0, 1.0 - min(cv, 1.0))

    # --- diversity --------------------------------------------------------
    if word_count:
        unique = len(set(lowered))
        report.vocabulary_richness = unique / math.sqrt(word_count)
        function_words = (
            FUNCTION_WORDS_AR if language == "ar" else FUNCTION_WORDS_EN
        )
        if language == "mixed":
            function_words = FUNCTION_WORDS_EN + FUNCTION_WORDS_AR
        function_set = set(function_words)
        content = sum(1 for t in lowered if t not in function_set)
        report.lexical_density = content / word_count

        frequencies = Counter(lowered)
        report.function_word_profile = {
            w: frequencies.get(w, 0) / word_count for w in function_words[:30]
        }

    # --- punctuation ------------------------------------------------------
    punctuation_counts: Counter = Counter(
        ch for ch in text if ch in _TRACKED_PUNCTUATION
    )
    report.punctuation_profile = dict(punctuation_counts.most_common())
    report.punctuation_entropy = shannon_entropy(list(punctuation_counts.values()))

    if word_count:
        per_1k = 1000 / word_count
        report.comma_rate = (
            punctuation_counts.get(",", 0) + punctuation_counts.get("،", 0)
        ) * per_1k
        report.em_dash_rate = (
            punctuation_counts.get("—", 0) + punctuation_counts.get("–", 0)
        ) * per_1k
        report.semicolon_rate = (
            punctuation_counts.get(";", 0) + punctuation_counts.get("؛", 0)
        ) * per_1k
        report.contraction_rate = len(_CONTRACTION.findall(text)) * per_1k

    # --- repetition -------------------------------------------------------
    report.repeated_ngrams = repeated_ngrams(lowered, n=4)
    report.repeated_sentence_openers = repeated_openers(sentence_list)
    if len(lowered) >= 4:
        total_grams = len(lowered) - 3
        repeated_total = sum(count for _, count in report.repeated_ngrams)
        report.ngram_repetition_rate = (
            repeated_total / total_grams if total_grams else 0.0
        )

    # --- register ---------------------------------------------------------
    if language in ("en", "mixed", "unknown", "other"):
        report.passive_hits = len(_PASSIVE_EN.findall(text))
    report.transition_density = _transition_density(text, token_list, language)

    return report
