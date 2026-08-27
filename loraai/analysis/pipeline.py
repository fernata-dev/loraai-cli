"""The analysis orchestrator.

Runs every pass over one input and assembles a single :class:`Analysis`.
The CLI, TUI and report writers all call this and nothing deeper, so adding a
pass here makes it appear everywhere at once.
"""

from __future__ import annotations

import time
from typing import Optional

from ..models import Analysis
from ..textio import LoadedText, extract_prose
from . import markers as markers_module
from . import provenance
from . import statistics as statistics_module
from . import stylometry as stylometry_module
from . import unicode_forensics
from .synthetic import SyntheticDetector, assess


def analyze(
    loaded: LoadedText,
    *,
    detector: Optional[SyntheticDetector] = None,
    decode_hidden: bool = True,
    prose_from_code: bool = True,
) -> Analysis:
    """Run the full analysis over *loaded*.

    Source code is handled specially: the Unicode forensics pass still runs
    over the whole file -- a bidi override hidden in a string literal is
    exactly what matters there -- while the writing-style passes run over the
    extracted comments and docstrings, because brace density is not prose
    rhythm.
    """
    started = time.perf_counter()
    result = Analysis(source=loaded.source)
    text = loaded.text

    if not text:
        # Still build the provenance report: every renderer reads it
        # unconditionally, and "nothing found" is the correct answer here.
        result.watermark = provenance.build(result.unicode, loaded.source.path)
        result.warnings.append("Input is empty.")
        result.elapsed_ms = (time.perf_counter() - started) * 1000
        return result

    # Unicode forensics always sees the raw input.
    result.unicode = unicode_forensics.scan(text, decode_hidden=decode_hidden)
    result.watermark = provenance.build(result.unicode, loaded.source.path)

    # Style passes see prose. For code, that means the comments.
    prose = text
    if prose_from_code and loaded.source.content_kind == "code":
        extracted = extract_prose(text, loaded.source.path)
        if extracted.strip():
            prose = extracted
            result.warnings.append(
                "Source file: writing-style metrics were computed from "
                f"comments and docstrings only ({len(extracted)} of "
                f"{len(text)} characters). Unicode forensics covered the "
                "whole file."
            )
        else:
            result.warnings.append(
                "Source file with no comments found; writing-style metrics "
                "are not meaningful here and were skipped."
            )
            prose = ""

    language = loaded.source.language
    if prose:
        result.statistics = statistics_module.compute(prose, language)
        result.style = stylometry_module.compute(prose, language)
        result.markers = markers_module.scan(prose, language)
        result.synthetic = assess(
            prose,
            result.statistics,
            result.style,
            result.markers,
            language,
            detector=detector,
        )

    if loaded.source.had_bom:
        result.warnings.append(
            "Input carried a byte order mark; it was consumed during decoding."
        )
    if loaded.source.language == "unknown" and result.statistics.words:
        result.warnings.append(
            "Language could not be determined confidently; English rules were "
            "used for style analysis."
        )

    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result
