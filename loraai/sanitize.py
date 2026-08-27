"""Making untrusted text safe to display.

Every string this tool prints may come from a hostile file. Two things must
never happen:

* An ANSI escape sequence in the input reaching the terminal, where it can
  reposition the cursor, recolour output, clear the screen, or forge a line
  that looks like the tool's own verdict.
* A bidi override reaching the terminal, where it reorders the display so what
  the reader sees differs from what the file contains -- the Trojan Source
  problem, which is exactly what this tool exists to find.

So input is escaped for display and only ever rendered through these helpers.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

#: CSI, OSC and the other ANSI escape forms.
_ANSI_RE = re.compile(
    r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07\x1B]*(?:\x07|\x1B\\))"
)

#: Bidi controls that reorder display relative to logical order.
_BIDI_CHARS = "‪‫‬‭‮⁦⁧⁨⁩"

_CONTROL_TRANSLATION = {
    ord(ch): f"<U+{ord(ch):04X}>"
    for ch in (
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"
        "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x7f"
    )
}
_CONTROL_TRANSLATION.update({ord(ch): f"<U+{ord(ch):04X}>" for ch in _BIDI_CHARS})


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences."""
    return _ANSI_RE.sub("", text)


def escape_for_terminal(text: str, *, reveal_invisible: bool = True) -> str:
    """Make *text* safe to print.

    Control characters and bidi overrides become visible ``<U+XXXX>`` tokens.
    With ``reveal_invisible``, zero-width and other invisible characters are
    shown the same way -- which is usually the point, since the user is asking
    what is hidden in their text.
    """
    if not text:
        return ""

    result = strip_ansi(text).translate(_CONTROL_TRANSLATION)

    if reveal_invisible:
        out = []
        for ch in result:
            cp = ord(ch)
            if ch in "\n\t\r":
                out.append(ch)
                continue
            category = unicodedata.category(ch)
            if category in ("Cf", "Co", "Cs", "Cn") or (
                category == "Zs" and ch != " "
            ):
                out.append(f"<U+{cp:04X}>")
            else:
                out.append(ch)
        result = "".join(out)

    return result


def one_line(text: str, limit: int = 100) -> str:
    """Collapse to a single line and truncate, for table cells."""
    collapsed = " ".join(escape_for_terminal(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def safe_lines(text: str, limit: int = 200) -> Iterable[str]:
    """Yield escaped lines, capped in count."""
    for index, line in enumerate(escape_for_terminal(text).split("\n")):
        if index >= limit:
            yield f"... ({limit}+ lines, truncated)"
            return
        yield line


def redact_secrets(text: str) -> str:
    """Mask anything that looks like a credential.

    Applied before writing reports, so a scan of a config file does not turn
    into a report that leaks the key it found.
    """
    patterns = (
        (r"\b(sk-[A-Za-z0-9_\-]{16,})\b", "sk-***REDACTED***"),
        (r"\b(sk-ant-[A-Za-z0-9_\-]{16,})\b", "sk-ant-***REDACTED***"),
        (r"\b(gh[pousr]_[A-Za-z0-9]{20,})\b", "gh*_***REDACTED***"),
        (r"\b(AKIA[0-9A-Z]{16})\b", "AKIA***REDACTED***"),
        (r"\b(AIza[0-9A-Za-z_\-]{30,})\b", "AIza***REDACTED***"),
        (
            r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?"
            r"([A-Za-z0-9_\-]{12,})['\"]?",
            r"\1=***REDACTED***",
        ),
    )
    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result)
    return result
