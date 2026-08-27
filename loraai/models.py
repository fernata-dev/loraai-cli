"""Shared result types.

Everything the analysis engine produces is a plain dataclass with a
``to_dict()`` method, so the CLI, TUI, JSON reports and HTML reports all
consume the same structures and no renderer needs to reach into internals.
"""

from __future__ import annotations

import enum
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class Severity(enum.Enum):
    """How much a finding should worry the reader."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    def __lt__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


_SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class CharClass(enum.Enum):
    """Taxonomy for anomalous characters. Drives cleaning policy and display."""

    ZERO_WIDTH = "zero-width"
    BIDI_CONTROL = "bidi-control"
    BIDI_OVERRIDE = "bidi-override"
    TAG_CHARACTER = "tag-character"
    VARIATION_SELECTOR = "variation-selector"
    INVISIBLE_MATH = "invisible-math"
    INVISIBLE_FORMAT = "invisible-format"
    EXOTIC_WHITESPACE = "exotic-whitespace"
    LINE_SEPARATOR = "line-separator"
    CONTROL = "control"
    PRIVATE_USE = "private-use"
    DEPRECATED = "deprecated"
    CONFUSABLE = "confusable"
    NONCHARACTER = "noncharacter"
    REPLACEMENT = "replacement"
    TYPOGRAPHIC = "typographic"


class Verdict(enum.Enum):
    """Coarse label for the synthetic-text assessment.

    Deliberately hedged. These are linguistic observations, not proof of
    authorship -- see ``loraai.analysis.synthetic`` for the reasoning.
    """

    LIKELY_HUMAN = "likely-human"
    LEANS_HUMAN = "leans-human"
    INCONCLUSIVE = "inconclusive"
    LEANS_SYNTHETIC = "leans-synthetic"
    LIKELY_SYNTHETIC = "likely-synthetic"

    @property
    def label(self) -> str:
        return _VERDICT_LABELS[self]


_VERDICT_LABELS = {
    Verdict.LIKELY_HUMAN: "LIKELY HUMAN-WRITTEN",
    Verdict.LEANS_HUMAN: "LEANS HUMAN-WRITTEN",
    Verdict.INCONCLUSIVE: "INCONCLUSIVE",
    Verdict.LEANS_SYNTHETIC: "LEANS AI-ASSISTED",
    Verdict.LIKELY_SYNTHETIC: "LIKELY AI-GENERATED",
}


@dataclass
class SourceInfo:
    """Provenance and shape of the analysed input."""

    origin: str = "text"  # text | file | stdin
    path: Optional[str] = None
    encoding: str = "utf-8"
    had_bom: bool = False
    size_bytes: int = 0
    char_count: int = 0
    content_kind: str = "prose"  # prose | code | markup | data
    language: str = "unknown"  # en | ar | mixed | unknown
    script_mix: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origin": self.origin,
            "path": self.path,
            "encoding": self.encoding,
            "had_bom": self.had_bom,
            "size_bytes": self.size_bytes,
            "char_count": self.char_count,
            "content_kind": self.content_kind,
            "language": self.language,
            "script_mix": dict(self.script_mix),
        }


@dataclass
class CharFinding:
    """One anomalous character at one position."""

    codepoint: int
    position: int
    line: int
    column: int
    char_class: CharClass
    severity: Severity
    context: str = ""
    note: str = ""
    recommended_action: str = "remove"  # remove | replace | keep | review
    replacement: Optional[str] = None

    @property
    def char(self) -> str:
        return chr(self.codepoint)

    @property
    def code(self) -> str:
        return f"U+{self.codepoint:04X}"

    @property
    def name(self) -> str:
        """Unicode name, with sensible fallbacks for unnamed code points."""
        try:
            return unicodedata.name(chr(self.codepoint))
        except ValueError:
            return _FALLBACK_NAMES.get(self.codepoint, _range_name(self.codepoint))

    @property
    def category(self) -> str:
        return unicodedata.category(chr(self.codepoint))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codepoint": self.codepoint,
            "code": self.code,
            "name": self.name,
            "category": self.category,
            "class": self.char_class.value,
            "severity": self.severity.value,
            "position": self.position,
            "line": self.line,
            "column": self.column,
            "context": self.context,
            "note": self.note,
            "recommended_action": self.recommended_action,
            "replacement": self.replacement,
        }


_FALLBACK_NAMES = {
    0x00: "NULL",
    0x01: "START OF HEADING",
    0x02: "START OF TEXT",
    0x03: "END OF TEXT",
    0x07: "BELL",
    0x08: "BACKSPACE",
    0x09: "CHARACTER TABULATION",
    0x0A: "LINE FEED",
    0x0B: "LINE TABULATION",
    0x0C: "FORM FEED",
    0x0D: "CARRIAGE RETURN",
    0x1B: "ESCAPE",
    0x7F: "DELETE",
    0x85: "NEXT LINE",
    0xE0001: "LANGUAGE TAG",
}


def _range_name(cp: int) -> str:
    """Describe an unnamed code point by the block it falls in."""
    if 0xE0020 <= cp <= 0xE007F:
        return f"TAG {chr(cp - 0xE0000)!r}" if cp != 0xE007F else "CANCEL TAG"
    if 0xE0100 <= cp <= 0xE01EF:
        return f"VARIATION SELECTOR-{cp - 0xE0100 + 17}"
    if 0xE000 <= cp <= 0xF8FF:
        return "PRIVATE USE CHARACTER"
    if 0xF0000 <= cp <= 0x10FFFD:
        return "SUPPLEMENTARY PRIVATE USE CHARACTER"
    if 0x00 <= cp <= 0x1F or 0x80 <= cp <= 0x9F:
        return "CONTROL CHARACTER"
    return "UNNAMED CHARACTER"


@dataclass
class HiddenPayload:
    """Decoded content recovered from an invisible-character encoding.

    This is the strongest evidence the tool produces: it is not a heuristic
    but an actual decode. A non-empty payload means someone deliberately
    embedded data in the text.
    """

    scheme: str  # unicode-tags | variation-selector | zero-width-binary
    decoded: str
    start: int
    end: int
    char_count: int
    printable_ratio: float
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scheme": self.scheme,
            "decoded": self.decoded,
            "start": self.start,
            "end": self.end,
            "char_count": self.char_count,
            "printable_ratio": round(self.printable_ratio, 4),
            "note": self.note,
        }


@dataclass
class UnicodeReport:
    """Everything the Unicode forensics pass found."""

    findings: List[CharFinding] = field(default_factory=list)
    payloads: List[HiddenPayload] = field(default_factory=list)
    class_counts: Dict[str, int] = field(default_factory=dict)
    codepoint_counts: Dict[str, int] = field(default_factory=dict)
    scripts: Dict[str, int] = field(default_factory=dict)
    mixed_script_words: List[str] = field(default_factory=list)
    normalization: Dict[str, Any] = field(default_factory=dict)
    max_severity: Severity = Severity.INFO
    notes: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.findings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_findings": self.total,
            "max_severity": self.max_severity.value,
            "class_counts": dict(self.class_counts),
            "codepoint_counts": dict(self.codepoint_counts),
            "scripts": dict(self.scripts),
            "mixed_script_words": list(self.mixed_script_words),
            "normalization": dict(self.normalization),
            "hidden_payloads": [p.to_dict() for p in self.payloads],
            "findings": [f.to_dict() for f in self.findings],
            "notes": list(self.notes),
        }


@dataclass
class Signal:
    """One piece of evidence in the synthetic-text assessment.

    ``weight`` is a log-odds contribution: positive leans synthetic, negative
    leans human, zero is neutral. Keeping the raw measurement alongside the
    weight means the UI can always show *why* a score moved.
    """

    key: str
    label: str
    value: Optional[float]
    weight: float
    detail: str = ""
    experimental: bool = False

    @property
    def direction(self) -> str:
        if self.weight > 0.05:
            return "synthetic"
        if self.weight < -0.05:
            return "human"
        return "neutral"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": None if self.value is None else round(self.value, 4),
            "weight": round(self.weight, 4),
            "direction": self.direction,
            "detail": self.detail,
            "experimental": self.experimental,
        }


@dataclass
class SyntheticAssessment:
    """Probabilistic judgement about whether text reads as machine-generated."""

    verdict: Verdict = Verdict.INCONCLUSIVE
    score: float = 0.5  # 0.0 = human-like, 1.0 = synthetic-like
    confidence: float = 0.0  # how much evidence supports the score at all
    signals: List[Signal] = field(default_factory=list)
    reliability: str = "low"  # low | moderate | good
    caveats: List[str] = field(default_factory=list)

    @property
    def supporting(self) -> List[Signal]:
        return sorted(
            (s for s in self.signals if s.direction == "synthetic"),
            key=lambda s: -s.weight,
        )

    @property
    def opposing(self) -> List[Signal]:
        return sorted(
            (s for s in self.signals if s.direction == "human"), key=lambda s: s.weight
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "label": self.verdict.label,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "reliability": self.reliability,
            "signals": [s.to_dict() for s in self.signals],
            "caveats": list(self.caveats),
        }


@dataclass
class WatermarkReport:
    """Honest status for each *distinct* provenance-marking technology.

    These are three genuinely different things and conflating them is the most
    common mistake in this problem space, so they are reported separately.
    """

    invisible_characters: Dict[str, Any] = field(default_factory=dict)
    embedded_payloads: Dict[str, Any] = field(default_factory=dict)
    statistical_watermark: Dict[str, Any] = field(default_factory=dict)
    file_provenance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invisible_characters": dict(self.invisible_characters),
            "embedded_payloads": dict(self.embedded_payloads),
            "statistical_watermark": dict(self.statistical_watermark),
            "file_provenance": dict(self.file_provenance),
        }


@dataclass
class StatisticsReport:
    """Counting metrics. Deterministic, script-aware, no interpretation."""

    characters: int = 0
    characters_no_space: int = 0
    letters: int = 0
    digits: int = 0
    punctuation: int = 0
    whitespace: int = 0
    words: int = 0
    unique_words: int = 0
    sentences: int = 0
    paragraphs: int = 0
    lines: int = 0
    avg_word_length: float = 0.0
    avg_sentence_length: float = 0.0
    median_sentence_length: float = 0.0
    sentence_length_stdev: float = 0.0
    avg_paragraph_length: float = 0.0
    type_token_ratio: float = 0.0
    moving_ttr: float = 0.0
    hapax_ratio: float = 0.0
    reading_time_minutes: float = 0.0
    sentence_lengths: List[int] = field(default_factory=list)
    word_lengths: List[int] = field(default_factory=list)
    top_words: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "characters": self.characters,
            "characters_no_space": self.characters_no_space,
            "letters": self.letters,
            "digits": self.digits,
            "punctuation": self.punctuation,
            "whitespace": self.whitespace,
            "words": self.words,
            "unique_words": self.unique_words,
            "sentences": self.sentences,
            "paragraphs": self.paragraphs,
            "lines": self.lines,
            "avg_word_length": round(self.avg_word_length, 3),
            "avg_sentence_length": round(self.avg_sentence_length, 3),
            "median_sentence_length": round(self.median_sentence_length, 3),
            "sentence_length_stdev": round(self.sentence_length_stdev, 3),
            "avg_paragraph_length": round(self.avg_paragraph_length, 3),
            "type_token_ratio": round(self.type_token_ratio, 4),
            "moving_ttr": round(self.moving_ttr, 4),
            "hapax_ratio": round(self.hapax_ratio, 4),
            "reading_time_minutes": round(self.reading_time_minutes, 2),
            "sentence_lengths": list(self.sentence_lengths),
            "top_words": [list(t) for t in self.top_words],
        }


@dataclass
class StyleReport:
    """Stylometric measurements: rhythm, diversity, repetition, punctuation."""

    burstiness: float = 0.0
    sentence_length_cv: float = 0.0
    word_length_cv: float = 0.0
    paragraph_uniformity: float = 0.0
    lexical_density: float = 0.0
    vocabulary_richness: float = 0.0
    punctuation_profile: Dict[str, int] = field(default_factory=dict)
    punctuation_entropy: float = 0.0
    comma_rate: float = 0.0
    em_dash_rate: float = 0.0
    semicolon_rate: float = 0.0
    repeated_ngrams: List[Any] = field(default_factory=list)
    repeated_sentence_openers: List[Any] = field(default_factory=list)
    ngram_repetition_rate: float = 0.0
    function_word_profile: Dict[str, float] = field(default_factory=dict)
    contraction_rate: float = 0.0
    passive_hits: int = 0
    transition_density: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "burstiness": round(self.burstiness, 4),
            "sentence_length_cv": round(self.sentence_length_cv, 4),
            "word_length_cv": round(self.word_length_cv, 4),
            "paragraph_uniformity": round(self.paragraph_uniformity, 4),
            "lexical_density": round(self.lexical_density, 4),
            "vocabulary_richness": round(self.vocabulary_richness, 4),
            "punctuation_profile": dict(self.punctuation_profile),
            "punctuation_entropy": round(self.punctuation_entropy, 4),
            "comma_rate": round(self.comma_rate, 4),
            "em_dash_rate": round(self.em_dash_rate, 4),
            "semicolon_rate": round(self.semicolon_rate, 4),
            "ngram_repetition_rate": round(self.ngram_repetition_rate, 4),
            "repeated_ngrams": [list(t) for t in self.repeated_ngrams],
            "repeated_sentence_openers": [list(t) for t in self.repeated_sentence_openers],
            "function_word_profile": {
                k: round(v, 5) for k, v in self.function_word_profile.items()
            },
            "contraction_rate": round(self.contraction_rate, 4),
            "passive_hits": self.passive_hits,
            "transition_density": round(self.transition_density, 4),
        }


@dataclass
class MarkerHit:
    """One occurrence of a known AI-writing tell."""

    rule_id: str
    category: str
    matched: str
    position: int
    line: int
    severity: Severity
    suggestion: str = ""
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "matched": self.matched,
            "position": self.position,
            "line": self.line,
            "severity": self.severity.value,
            "suggestion": self.suggestion,
            "explanation": self.explanation,
        }


@dataclass
class MarkerReport:
    """Aggregate of AI-writing tells found in the text."""

    hits: List[MarkerHit] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)
    density_per_1k: float = 0.0
    #: Density with each hit scaled by severity. A stray em dash and an
    #: explicit "as an AI language model" are both "one hit" by count but are
    #: nothing alike as evidence, so the scorer uses this instead.
    weighted_density_per_1k: float = 0.0

    @property
    def total(self) -> int:
        return len(self.hits)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "density_per_1k_words": round(self.density_per_1k, 3),
            "weighted_density_per_1k_words": round(self.weighted_density_per_1k, 3),
            "category_counts": dict(self.category_counts),
            "hits": [h.to_dict() for h in self.hits],
        }


@dataclass
class Analysis:
    """The complete result of analysing one input."""

    source: SourceInfo = field(default_factory=SourceInfo)
    statistics: StatisticsReport = field(default_factory=StatisticsReport)
    style: StyleReport = field(default_factory=StyleReport)
    unicode: UnicodeReport = field(default_factory=UnicodeReport)
    markers: MarkerReport = field(default_factory=MarkerReport)
    synthetic: SyntheticAssessment = field(default_factory=SyntheticAssessment)
    watermark: WatermarkReport = field(default_factory=WatermarkReport)
    warnings: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        from .version import REPORT_SCHEMA_VERSION, get_version

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "loraai_version": get_version(),
            "source": self.source.to_dict(),
            "statistics": self.statistics.to_dict(),
            "style": self.style.to_dict(),
            "unicode": self.unicode.to_dict(),
            "ai_markers": self.markers.to_dict(),
            "synthetic_signal": self.synthetic.to_dict(),
            "provenance_marking": self.watermark.to_dict(),
            "warnings": list(self.warnings),
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


@dataclass
class CleanChange:
    """A single edit the cleaner made or would make."""

    action: str  # removed | replaced
    codepoint: int
    position: int
    replacement: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "code": f"U+{self.codepoint:04X}",
            "position": self.position,
            "replacement": self.replacement,
            "reason": self.reason,
        }


@dataclass
class CleanResult:
    """Outcome of a cleaning pass."""

    original: str
    cleaned: str
    changes: List[CleanChange] = field(default_factory=list)
    removed_counts: Dict[str, int] = field(default_factory=dict)
    replaced_counts: Dict[str, int] = field(default_factory=dict)
    preserved_counts: Dict[str, int] = field(default_factory=dict)
    semantic_preserved: bool = True
    semantic_notes: List[str] = field(default_factory=list)
    profile: str = "safe"

    @property
    def changed(self) -> bool:
        return self.original != self.cleaned

    @property
    def total_changes(self) -> int:
        return len(self.changes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile,
            "changed": self.changed,
            "total_changes": self.total_changes,
            "removed": dict(self.removed_counts),
            "replaced": dict(self.replaced_counts),
            "preserved": dict(self.preserved_counts),
            "semantic_preserved": self.semantic_preserved,
            "semantic_notes": list(self.semantic_notes),
            "original_length": len(self.original),
            "cleaned_length": len(self.cleaned),
        }


@dataclass
class HumanizeEdit:
    """One transformation applied by the humanizer."""

    rule_id: str
    category: str
    before: str
    after: str
    position: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "before": self.before,
            "after": self.after,
            "position": self.position,
        }


@dataclass
class HumanizeResult:
    """Outcome of a humanization pass."""

    original: str
    result: str
    edits: List[HumanizeEdit] = field(default_factory=list)
    provider: str = "offline"
    style: str = "natural"
    intensity: int = 2
    marker_before: int = 0
    marker_after: int = 0
    notes: List[str] = field(default_factory=list)
    preserved_spans: int = 0

    @property
    def changed(self) -> bool:
        return self.original != self.result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "style": self.style,
            "intensity": self.intensity,
            "changed": self.changed,
            "edit_count": len(self.edits),
            "markers_before": self.marker_before,
            "markers_after": self.marker_after,
            "preserved_spans": self.preserved_spans,
            "edits": [e.to_dict() for e in self.edits],
            "notes": list(self.notes),
        }
