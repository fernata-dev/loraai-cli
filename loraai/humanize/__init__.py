"""Humanization: rewriting text to read more naturally."""

from .engine import humanize
from .rules import ALL_STYLES, rules_for

__all__ = ["humanize", "rules_for", "ALL_STYLES"]
