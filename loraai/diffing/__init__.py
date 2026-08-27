"""Text comparison at line, word and character granularity."""

from .engine import DiffResult, DiffSegment, DiffStats, diff, summary

__all__ = ["diff", "summary", "DiffResult", "DiffSegment", "DiffStats"]
