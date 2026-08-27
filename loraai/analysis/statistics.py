"""Counting metrics.

Everything here is deterministic and interpretation-free: how many, how long,
how varied. The stylometry and synthetic passes build on these numbers rather
than recomputing them.

One design note worth stating: raw type-token ratio falls as text gets longer,
which makes it useless for comparing documents of different sizes. The moving
-average TTR (MATTR) reported alongside it is length-stable, so the scoring
engine uses MATTR and keeps plain TTR only for display.
"""

from __future__ import annotations

import statistics as stats
import unicodedata
from collections import Counter
from typing import List

from ..models import StatisticsReport
from .tokenizer import paragraphs, sentences, words

#: Reading speed in words per minute, by language.
_READING_SPEED = {"en": 238, "ar": 180, "mixed": 200, "other": 200, "unknown": 220}

_MATTR_WINDOW = 50


def moving_average_ttr(tokens: List[str], window: int = _MATTR_WINDOW) -> float:
    """Length-stable lexical diversity.

    Averages the type-token ratio over every sliding window of *window*
    tokens. Unlike plain TTR this does not shrink just because the document
    is long, so it can be compared across inputs.
    """
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)

    ratios = []
    for start in range(len(tokens) - window + 1):
        chunk = tokens[start : start + window]
        ratios.append(len(set(chunk)) / window)
    return sum(ratios) / len(ratios)


def compute(text: str, language: str = "unknown") -> StatisticsReport:
    """Compute every counting metric for *text*."""
    report = StatisticsReport()
    if not text:
        return report

    report.characters = len(text)
    report.lines = text.count("\n") + 1 if text else 0

    letters = digits = punctuation = whitespace = 0
    for ch in text:
        category = unicodedata.category(ch)
        if ch.isspace():
            whitespace += 1
        elif category.startswith("L"):
            letters += 1
        elif category.startswith("N"):
            digits += 1
        elif category.startswith("P") or category.startswith("S"):
            punctuation += 1

    report.letters = letters
    report.digits = digits
    report.punctuation = punctuation
    report.whitespace = whitespace
    report.characters_no_space = report.characters - whitespace

    token_list = words(text)
    lowered = [t.lower() for t in token_list]
    report.words = len(token_list)
    report.unique_words = len(set(lowered))

    sentence_list = sentences(text)
    report.sentences = len(sentence_list)

    paragraph_list = paragraphs(text)
    report.paragraphs = len(paragraph_list)

    if token_list:
        report.word_lengths = [len(t) for t in token_list]
        report.avg_word_length = sum(report.word_lengths) / len(report.word_lengths)
        report.type_token_ratio = report.unique_words / report.words
        report.moving_ttr = moving_average_ttr(lowered)

        frequencies = Counter(lowered)
        hapax = sum(1 for count in frequencies.values() if count == 1)
        report.hapax_ratio = hapax / report.unique_words if report.unique_words else 0.0
        report.top_words = frequencies.most_common(25)

        speed = _READING_SPEED.get(language, 220)
        report.reading_time_minutes = report.words / speed

    if sentence_list:
        report.sentence_lengths = [len(words(s)) for s in sentence_list]
        lengths = [n for n in report.sentence_lengths if n > 0]
        if lengths:
            report.avg_sentence_length = sum(lengths) / len(lengths)
            report.median_sentence_length = stats.median(lengths)
            report.sentence_length_stdev = (
                stats.pstdev(lengths) if len(lengths) > 1 else 0.0
            )

    if paragraph_list:
        para_words = [len(words(p)) for p in paragraph_list]
        report.avg_paragraph_length = sum(para_words) / len(para_words)

    return report
