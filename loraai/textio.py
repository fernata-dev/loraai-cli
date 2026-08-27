"""Input acquisition: text, files and stdin.

Handles the unglamorous parts that decide whether a tool is pleasant or
infuriating: encoding detection, BOM handling, binary rejection, size limits,
and telling prose apart from source code so the analysis engine does not
report on brace density as if it were writing style.
"""

from __future__ import annotations

import io
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .errors import BinaryFileError, FileAccessError, FileTooLargeError, InputError
from .models import SourceInfo
from .unicode_data.scripts import dominant_language, script_histogram

#: Default ceiling on a single input. Overridable via configuration.
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

#: Encodings tried in order. utf-8-sig first so a BOM is consumed, not kept.
_ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "utf-16", "utf-32", "cp1256", "latin-1")

TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".rst", ".org", ".adoc",
    ".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".yaml", ".yml", ".toml", ".ini",
    ".html", ".htm", ".xml", ".svg", ".xhtml",
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt", ".go", ".rs",
    ".rb", ".php", ".swift", ".scala", ".sh", ".bash", ".zsh", ".fish",
    ".sql", ".r", ".lua", ".pl", ".vim", ".el", ".tex", ".bib",
    ".log", ".conf", ".cfg", ".env", ".gitignore", ".dockerfile",
}

_CODE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php",
    ".swift", ".scala", ".sh", ".bash", ".zsh", ".fish", ".sql", ".r", ".lua",
    ".pl", ".vim", ".el",
}
_MARKUP_EXTENSIONS = {".html", ".htm", ".xml", ".svg", ".xhtml", ".md", ".markdown",
                      ".rst", ".adoc", ".tex"}
_DATA_EXTENSIONS = {".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".yaml", ".yml",
                    ".toml", ".ini", ".conf", ".cfg"}


@dataclass
class LoadedText:
    """Text plus everything known about where it came from."""

    text: str
    source: SourceInfo

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()


def _detect_content_kind(path: Optional[Path], text: str) -> str:
    """Classify input as prose, code, markup or data."""
    if path is not None:
        suffix = path.suffix.lower()
        if suffix in _CODE_EXTENSIONS:
            return "code"
        if suffix in _DATA_EXTENSIONS:
            return "data"
        if suffix in _MARKUP_EXTENSIONS:
            return "markup"
        if suffix in TEXT_EXTENSIONS:
            return "prose"

    # No usable extension: judge by shape.
    sample = text[:4000]
    if not sample.strip():
        return "prose"

    stripped = sample.lstrip()
    if stripped[:1] in "{[" and stripped.rstrip()[-1:] in "}]":
        return "data"

    code_signals = len(
        re.findall(
            r"(?m)^\s*(?:def |class |function |import |from |#include|package |"
            r"public |private |const |let |var |func |fn |use )",
            sample,
        )
    )
    brace_density = (sample.count("{") + sample.count("}") + sample.count(";")) / max(
        1, len(sample)
    )
    if code_signals >= 3 or brace_density > 0.02:
        return "code"
    if re.search(r"(?m)^\s*(?:#{1,6}\s|\* |- |\d+\. )", sample) or "<" in sample[:200]:
        return "markup"
    return "prose"


#: BOM -> codec. Checked longest-first: the UTF-32 LE BOM starts with the
#: UTF-16 LE BOM, so testing in the wrong order decodes UTF-32 as UTF-16 and
#: yields plausible-looking garbage instead of an error.
_BOM_CODECS = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)

#: Wide codecs tried when a file has NUL bytes but no BOM.
_WIDE_CODECS = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")


def _bom_codec(data: bytes) -> Optional[str]:
    """Return the codec a leading byte order mark names, if any."""
    for bom, codec in _BOM_CODECS:
        if data.startswith(bom):
            return codec
    return None


def _is_plausible_text(text: str) -> bool:
    """True when a decode produced something that reads as text.

    Used to tell BOM-less UTF-16 from genuine binary: both contain NULs, but
    only one of them decodes into printable characters.
    """
    if not text:
        return False
    sample = text[:4096]
    printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\t\r")
    if printable / len(sample) < 0.95:
        return False
    return any(ch.isalpha() for ch in sample)


def _wide_codec(data: bytes) -> Optional[str]:
    """Find a UTF-16/32 codec that decodes *data* into plausible text.

    A byte-pattern heuristic is not enough here: UTF-16 Arabic contains almost
    no NUL bytes while UTF-16 ASCII is half NULs, so the pattern varies with
    the script. Attempting the decode and inspecting the result works for both.
    """
    for codec in _WIDE_CODECS:
        try:
            candidate = data.decode(codec)
        except (UnicodeDecodeError, LookupError):
            continue
        if _is_plausible_text(candidate):
            return codec
    return None


def _looks_binary(data: bytes) -> bool:
    """Heuristic binary check: NUL bytes, or too many undecodable bytes."""
    if not data:
        return False
    if b"\x00" in data[:8192]:
        # NULs mean binary unless this is wide-encoded text.
        return _bom_codec(data) is None and _wide_codec(data) is None
    sample = data[:8192]
    # Count bytes that never appear in text of any encoding we support.
    control = sum(
        1
        for b in sample
        if b < 0x09 or (0x0E <= b < 0x20 and b != 0x1B) or b == 0x7F
    )
    return control / len(sample) > 0.10


def _decode(data: bytes, path: Optional[Path]) -> Tuple[str, str, bool]:
    """Decode *data*, returning ``(text, encoding, had_bom)``.

    A byte order mark is authoritative and is honoured first. Failing that, a
    wide encoding is attempted for anything containing NULs, and only then the
    ordinary single-byte candidates.
    """
    bom_codec = _bom_codec(data)
    had_bom = bom_codec is not None

    ordered: List[str] = []
    if bom_codec:
        ordered.append(bom_codec)
    elif b"\x00" in data[:8192]:
        wide = _wide_codec(data)
        if wide:
            ordered.append(wide)
    ordered.extend(e for e in _ENCODING_CANDIDATES if e not in ordered)

    errors: List[str] = []
    for encoding in ordered:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        # latin-1 never fails, so only accept it as a genuine last resort.
        if encoding == "latin-1" and _looks_binary(data):
            break
        # utf-8-sig is the codec used to strip a BOM; without one the file is
        # plain utf-8 and reporting otherwise would just confuse the reader.
        if encoding == "utf-8-sig" and not had_bom:
            encoding = "utf-8"
        # A BOM-directed wide decode leaves the mark in the string.
        if had_bom and text.startswith("\ufeff"):
            text = text[1:]
        return text, encoding, had_bom

    where = f" ({path})" if path else ""
    raise BinaryFileError(
        f"Could not decode input as text{where}.",
        hint="The file appears to be binary. loraai works on text; try "
             "extracting the text first.",
    )


def _build_source(
    text: str,
    *,
    origin: str,
    path: Optional[Path],
    encoding: str,
    had_bom: bool,
    size_bytes: int,
) -> SourceInfo:
    scripts = script_histogram(text)
    return SourceInfo(
        origin=origin,
        path=str(path) if path else None,
        encoding=encoding,
        had_bom=had_bom,
        size_bytes=size_bytes,
        char_count=len(text),
        content_kind=_detect_content_kind(path, text),
        language=dominant_language(text),
        script_mix=scripts,
    )


def from_text(text: str) -> LoadedText:
    """Wrap a literal string as an input."""
    if text is None:
        raise InputError("No text supplied.")
    return LoadedText(
        text=text,
        source=_build_source(
            text,
            origin="text",
            path=None,
            encoding="utf-8",
            had_bom=False,
            size_bytes=len(text.encode("utf-8")),
        ),
    )


def from_file(path: os.PathLike | str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> LoadedText:
    """Read and decode a file."""
    file_path = Path(path).expanduser()

    try:
        resolved = file_path.resolve(strict=True)
    except FileNotFoundError:
        raise FileAccessError(
            f"File not found: {file_path}",
            hint="Check the path, or pass the text directly with --text.",
        ) from None
    except OSError as exc:
        raise FileAccessError(f"Cannot access {file_path}: {exc}") from None

    if resolved.is_dir():
        raise FileAccessError(
            f"{resolved} is a directory, not a file.",
            hint="Point at a single file.",
        )
    if not resolved.is_file():
        raise FileAccessError(f"{resolved} is not a regular file.")

    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise FileAccessError(f"Cannot stat {resolved}: {exc}") from None

    if size > max_bytes:
        raise FileTooLargeError(
            f"{resolved} is {size / 1_048_576:.1f} MB, over the "
            f"{max_bytes / 1_048_576:.0f} MB limit.",
            hint="Raise the limit with --max-bytes, or split the file.",
        )

    try:
        data = resolved.read_bytes()
    except PermissionError:
        raise FileAccessError(
            f"Permission denied reading {resolved}.",
            hint="Check the file's permissions.",
        ) from None
    except OSError as exc:
        raise FileAccessError(f"Cannot read {resolved}: {exc}") from None

    if _looks_binary(data):
        raise BinaryFileError(
            f"{resolved} looks like a binary file.",
            hint="loraai analyses text. Extract the text content first.",
        )

    text, encoding, had_bom = _decode(data, resolved)
    return LoadedText(
        text=text,
        source=_build_source(
            text,
            origin="file",
            path=resolved,
            encoding=encoding,
            had_bom=had_bom,
            size_bytes=size,
        ),
    )


def from_stdin(*, max_bytes: int = DEFAULT_MAX_BYTES) -> LoadedText:
    """Read the whole of stdin."""
    if sys.stdin is None:
        raise InputError("No stdin available.")
    if sys.stdin.isatty():
        raise InputError(
            "No piped input on stdin.",
            hint="Pipe text in, or use --text / --file.",
        )

    buffer = getattr(sys.stdin, "buffer", None)
    data = buffer.read(max_bytes + 1) if buffer else sys.stdin.read().encode("utf-8")

    if len(data) > max_bytes:
        raise FileTooLargeError(
            f"stdin exceeded the {max_bytes / 1_048_576:.0f} MB limit."
        )
    if not data:
        raise InputError(
            "Nothing arrived on stdin.",
            hint="Pipe text in, or use --text \"...\" / --file PATH.",
        )
    if _looks_binary(data):
        raise BinaryFileError("stdin looks like binary data, not text.")

    text, encoding, had_bom = _decode(data, None)
    return LoadedText(
        text=text,
        source=_build_source(
            text,
            origin="stdin",
            path=None,
            encoding=encoding,
            had_bom=had_bom,
            size_bytes=len(data),
        ),
    )


def resolve(
    text: Optional[str] = None,
    file: Optional[str] = None,
    *,
    use_stdin: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> LoadedText:
    """Pick exactly one input source and load it.

    Enforces that the caller supplied one and only one, with an error message
    that says what to do instead rather than just what went wrong.
    """
    supplied = [
        name
        for name, value in (("--text", text), ("--file", file), ("stdin", use_stdin))
        if value
    ]
    if len(supplied) > 1:
        raise InputError(
            f"More than one input given ({', '.join(supplied)}).",
            hint="Use exactly one of --text, --file, or piped stdin.",
        )
    if not supplied:
        raise InputError(
            "No input given.",
            hint="Use --text \"...\", --file PATH, or pipe text on stdin.",
        )

    if use_stdin:
        return from_stdin(max_bytes=max_bytes)
    if file:
        return from_file(file, max_bytes=max_bytes)
    return from_text(text or "")


def stdin_has_data() -> bool:
    """True when stdin is a pipe or file rather than a terminal."""
    try:
        return sys.stdin is not None and not sys.stdin.isatty()
    except (ValueError, io.UnsupportedOperation):
        return False


# ---------------------------------------------------------------------------
# Prose extraction from source code
# ---------------------------------------------------------------------------

_COMMENT_PATTERNS = {
    "hash": re.compile(r"(?m)#(?!\!)(.*)$"),
    "slash": re.compile(r"(?m)//(.*)$"),
    "block": re.compile(r"/\*(.*?)\*/", re.DOTALL),
    "html": re.compile(r"<!--(.*?)-->", re.DOTALL),
    "docstring": re.compile(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', re.DOTALL),
    "dash": re.compile(r"(?m)--(.*)$"),
}

_LANGUAGE_COMMENTS = {
    ".py": ("hash", "docstring"),
    ".pyi": ("hash", "docstring"),
    ".rb": ("hash",),
    ".sh": ("hash",), ".bash": ("hash",), ".zsh": ("hash",), ".fish": ("hash",),
    ".r": ("hash",), ".pl": ("hash",),
    ".yaml": ("hash",), ".yml": ("hash",), ".toml": ("hash",),
    ".js": ("slash", "block"), ".jsx": ("slash", "block"),
    ".ts": ("slash", "block"), ".tsx": ("slash", "block"),
    ".mjs": ("slash", "block"), ".cjs": ("slash", "block"),
    ".c": ("slash", "block"), ".h": ("slash", "block"),
    ".cpp": ("slash", "block"), ".hpp": ("slash", "block"), ".cc": ("slash", "block"),
    ".cs": ("slash", "block"), ".java": ("slash", "block"),
    ".kt": ("slash", "block"), ".go": ("slash", "block"), ".rs": ("slash", "block"),
    ".swift": ("slash", "block"), ".scala": ("slash", "block"),
    ".php": ("slash", "block", "hash"),
    ".sql": ("dash", "block"), ".lua": ("dash",),
    ".html": ("html",), ".htm": ("html",), ".xml": ("html",), ".svg": ("html",),
    ".css": ("block",),
}


def extract_prose(text: str, path: Optional[str] = None) -> str:
    """Pull the natural-language parts out of source code.

    Returns comments and docstrings joined by newlines. Analysing a source file
    as if it were an essay produces nonsense; analysing its comments is often
    exactly what the user meant.
    """
    suffix = Path(path).suffix.lower() if path else ""
    kinds = _LANGUAGE_COMMENTS.get(suffix)
    if kinds is None:
        kinds = ("hash", "slash", "block", "docstring")

    pieces: List[str] = []
    for kind in kinds:
        pattern = _COMMENT_PATTERNS[kind]
        for match in pattern.finditer(text):
            for group in match.groups():
                if group and group.strip():
                    pieces.append(group.strip())
    return "\n".join(pieces)
