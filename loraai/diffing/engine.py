"""Text comparison.

Three granularities, because they answer different questions: line diff for
"what sections changed", word diff for "what wording changed", character diff
for "did an invisible character move". The last one matters here more than it
would in a general diff tool -- a zero-width space is invisible in a word diff
and obvious in a character diff.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from ..analysis.tokenizer import words

_WORD_SPLIT = None  # tokenization is delegated to the shared tokenizer


@dataclass
class DiffSegment:
    """One aligned run between the two texts."""

    kind: str  # equal | insert | delete | replace
    before: str = ""
    after: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "before": self.before, "after": self.after}


@dataclass
class DiffStats:
    """Counts describing the size of the change."""

    words_before: int = 0
    words_after: int = 0
    words_added: int = 0
    words_removed: int = 0
    words_unchanged: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    chars_before: int = 0
    chars_after: int = 0
    similarity: float = 0.0

    @property
    def words_changed(self) -> int:
        return self.words_added + self.words_removed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "words_before": self.words_before,
            "words_after": self.words_after,
            "words_added": self.words_added,
            "words_removed": self.words_removed,
            "words_unchanged": self.words_unchanged,
            "words_changed": self.words_changed,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
            "similarity": round(self.similarity, 4),
        }


@dataclass
class DiffResult:
    """A complete comparison."""

    mode: str
    segments: List[DiffSegment] = field(default_factory=list)
    stats: DiffStats = field(default_factory=DiffStats)
    unified: str = ""
    label_before: str = "before"
    label_after: str = "after"

    @property
    def changed(self) -> bool:
        return any(s.kind != "equal" for s in self.segments)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "changed": self.changed,
            "labels": {"before": self.label_before, "after": self.label_after},
            "stats": self.stats.to_dict(),
            "segments": [s.to_dict() for s in self.segments],
        }


def _tokenize_words_with_space(text: str) -> List[str]:
    """Split into words *and* the whitespace between them.

    Keeping the separators as tokens means the diff can be reassembled into
    readable text rather than a bag of words.
    """
    tokens: List[str] = []
    buffer: List[str] = []
    in_space = False
    for ch in text:
        is_space = ch.isspace()
        if buffer and is_space != in_space:
            tokens.append("".join(buffer))
            buffer = []
        buffer.append(ch)
        in_space = is_space
    if buffer:
        tokens.append("".join(buffer))
    return tokens


def _build_segments(
    before_tokens: Sequence[str], after_tokens: Sequence[str], join: str = ""
) -> List[DiffSegment]:
    matcher = difflib.SequenceMatcher(None, before_tokens, after_tokens, autojunk=False)
    segments: List[DiffSegment] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        before = join.join(before_tokens[i1:i2])
        after = join.join(after_tokens[j1:j2])
        segments.append(DiffSegment(kind=tag, before=before, after=after))
    return segments


def _compute_stats(before: str, after: str, segments: Iterable[DiffSegment]) -> DiffStats:
    stats = DiffStats()
    before_words = words(before)
    after_words = words(after)
    stats.words_before = len(before_words)
    stats.words_after = len(after_words)
    stats.chars_before = len(before)
    stats.chars_after = len(after)

    matcher = difflib.SequenceMatcher(
        None, [w.lower() for w in before_words], [w.lower() for w in after_words],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            stats.words_unchanged += i2 - i1
        elif tag == "delete":
            stats.words_removed += i2 - i1
        elif tag == "insert":
            stats.words_added += j2 - j1
        else:  # replace
            stats.words_removed += i2 - i1
            stats.words_added += j2 - j1

    before_lines = before.splitlines()
    after_lines = after.splitlines()
    line_matcher = difflib.SequenceMatcher(None, before_lines, after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in line_matcher.get_opcodes():
        if tag in ("delete", "replace"):
            stats.lines_removed += i2 - i1
        if tag in ("insert", "replace"):
            stats.lines_added += j2 - j1

    stats.similarity = difflib.SequenceMatcher(
        None, before, after, autojunk=False
    ).ratio()
    return stats


def diff(
    before: str,
    after: str,
    *,
    mode: str = "word",
    label_before: str = "before",
    label_after: str = "after",
    context_lines: int = 3,
) -> DiffResult:
    """Compare two texts.

    ``mode`` is ``line``, ``word`` or ``char``.
    """
    if mode not in ("line", "word", "char"):
        raise ValueError(f"Unknown diff mode {mode!r}; use line, word or char.")

    result = DiffResult(mode=mode, label_before=label_before, label_after=label_after)

    if mode == "line":
        before_tokens = before.splitlines(keepends=True)
        after_tokens = after.splitlines(keepends=True)
        result.segments = _build_segments(before_tokens, after_tokens)
    elif mode == "word":
        result.segments = _build_segments(
            _tokenize_words_with_space(before), _tokenize_words_with_space(after)
        )
    else:
        result.segments = _build_segments(list(before), list(after))

    result.stats = _compute_stats(before, after, result.segments)
    result.unified = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=label_before,
            tofile=label_after,
            lineterm="",
            n=context_lines,
        )
    )
    return result


def summary(result: DiffResult) -> List[Tuple[str, str]]:
    """Label/value pairs for a compact stats table."""
    stats = result.stats
    return [
        ("Words before", f"{stats.words_before:,}"),
        ("Words after", f"{stats.words_after:,}"),
        ("Unchanged", f"{stats.words_unchanged:,}"),
        ("Added", f"{stats.words_added:,}"),
        ("Removed", f"{stats.words_removed:,}"),
        ("Lines +/-", f"+{stats.lines_added:,} / -{stats.lines_removed:,}"),
        ("Similarity", f"{stats.similarity:.1%}"),
    ]
