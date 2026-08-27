"""Decoders for data hidden inside invisible characters.

This module is the strongest evidence the tool produces. Everything else in
the analysis engine is a heuristic that shifts a probability; a successful
decode here is a *fact*. If a payload comes back, someone deliberately
embedded readable data in text that renders as nothing.

Three encodings are covered, all of them documented and in active use:

``unicode-tags``
    The Unicode Tags block (U+E0000-U+E007F) mirrors printable ASCII. The
    characters render as nothing in every editor, terminal and browser, but
    language-model tokenizers still read them. This is the "ASCII smuggling"
    channel behind invisible prompt injection.

``variation-selector``
    Variation selectors carry a byte each: VS1-16 (U+FE00-U+FE0F) hold values
    0-15 and the supplement (U+E0100-U+E01EF) holds 16-255. Chaining them
    after any character smuggles arbitrary bytes.

``zero-width-binary``
    Zero-width characters used as bits. Several conventions exist, so each
    plausible symbol assignment is tried and the decode is only reported when
    the result is actually text.

A decode is reported only when the recovered bytes look like real content.
Guessing wrong in the loud direction would be worse than saying nothing.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

from ..models import HiddenPayload

TAG_START = 0xE0000
TAG_END = 0xE007F
VS_LOW = (0xFE00, 0xFE0F)
VS_HIGH = (0xE0100, 0xE01EF)

#: Zero-width characters usable as binary symbols.
ZW_SYMBOLS = ("​", "‌", "‍", "⁠", "﻿")

#: Candidate bit assignments, ordered by how common they are in the wild.
_BIT_SCHEMES: Tuple[Tuple[str, str, str], ...] = (
    ("zwsp/zwnj", "​", "‌"),
    ("zwnj/zwj", "‌", "‍"),
    ("zwsp/zwj", "​", "‍"),
    ("zwsp/wj", "​", "⁠"),
    ("zwj/zwnj", "‍", "‌"),
)

_MIN_BINARY_RUN = 16
_MIN_PRINTABLE_RATIO = 0.85


def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    ok = sum(
        1
        for ch in text
        if ch.isprintable() or ch in "\n\t\r"
    )
    return ok / len(text)


def _looks_like_content(text: str) -> bool:
    """Reject decodes that are technically valid but obviously noise."""
    if len(text) < 3:
        return False
    if _printable_ratio(text) < _MIN_PRINTABLE_RATIO:
        return False
    # Require at least one alphanumeric run; pure punctuation is noise.
    return bool(re.search(r"[A-Za-z0-9؀-ۿ]{2,}", text))


# ---------------------------------------------------------------------------
# Unicode tags
# ---------------------------------------------------------------------------


def decode_tag_runs(text: str) -> List[HiddenPayload]:
    """Recover ASCII smuggled through the Unicode Tags block."""
    payloads: List[HiddenPayload] = []
    run_start: Optional[int] = None
    buffer: List[str] = []

    def flush(end: int) -> None:
        if run_start is None or not buffer:
            return
        decoded = "".join(buffer)
        payloads.append(
            HiddenPayload(
                scheme="unicode-tags",
                decoded=decoded,
                start=run_start,
                end=end,
                char_count=end - run_start,
                printable_ratio=_printable_ratio(decoded),
                note="Decoded from the Unicode Tags block. These code points "
                     "are invisible in every renderer but are read by language "
                     "models, which is what makes them an injection channel.",
            )
        )

    for idx, ch in enumerate(text):
        cp = ord(ch)
        if TAG_START <= cp <= TAG_END:
            if run_start is None:
                run_start = idx
                buffer = []
            if 0xE0020 <= cp <= 0xE007E:
                buffer.append(chr(cp - TAG_START))
            elif cp == 0xE0001:
                buffer.append("")  # language tag marker, carries no character
        else:
            if run_start is not None:
                flush(idx)
                run_start = None
                buffer = []
    if run_start is not None:
        flush(len(text))

    return [p for p in payloads if p.decoded]


# ---------------------------------------------------------------------------
# Variation selectors
# ---------------------------------------------------------------------------


def _vs_byte(cp: int) -> Optional[int]:
    if VS_LOW[0] <= cp <= VS_LOW[1]:
        return cp - VS_LOW[0]
    if VS_HIGH[0] <= cp <= VS_HIGH[1]:
        return cp - VS_HIGH[0] + 16
    return None


def decode_variation_selector_runs(text: str) -> List[HiddenPayload]:
    """Recover bytes chained as variation selectors."""
    payloads: List[HiddenPayload] = []
    run_start: Optional[int] = None
    data: List[int] = []

    def flush(end: int) -> None:
        if run_start is None or len(data) < 2:
            return
        raw = bytes(data)
        decoded: Optional[str] = None
        for encoding in ("utf-8", "latin-1"):
            try:
                candidate = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if _looks_like_content(candidate):
                decoded = candidate
                break
        if decoded is None:
            return
        payloads.append(
            HiddenPayload(
                scheme="variation-selector",
                decoded=decoded,
                start=run_start,
                end=end,
                char_count=len(data),
                printable_ratio=_printable_ratio(decoded),
                note="Decoded from a chain of variation selectors, each "
                     "carrying one byte. Renders as nothing after the "
                     "preceding character.",
            )
        )

    for idx, ch in enumerate(text):
        value = _vs_byte(ord(ch))
        if value is not None:
            if run_start is None:
                run_start = idx
                data = []
            data.append(value)
        else:
            if run_start is not None:
                flush(idx)
                run_start = None
                data = []
    if run_start is not None:
        flush(len(text))

    return payloads


# ---------------------------------------------------------------------------
# Zero-width binary
# ---------------------------------------------------------------------------


def _bits_to_text(bits: str) -> Optional[str]:
    """Try to read a bit string as 8-bit bytes, then as text."""
    usable = len(bits) - (len(bits) % 8)
    if usable < 24:  # fewer than 3 bytes is not worth reporting
        return None
    raw = bytes(
        int(bits[i : i + 8], 2) for i in range(0, usable, 8)
    )
    for encoding in ("utf-8", "ascii", "latin-1"):
        try:
            candidate = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _looks_like_content(candidate):
            return candidate
    return None


def _decode_symbol_sequence(
    symbols: Sequence[str], positions: Sequence[int], spread: bool
) -> Optional[HiddenPayload]:
    """Try every bit scheme against a sequence of zero-width characters."""
    present = set(symbols)
    best: Optional[Tuple[str, str]] = None

    for name, zero, one in _BIT_SCHEMES:
        if not present <= {zero, one}:
            continue
        bits = "".join("0" if s == zero else "1" for s in symbols)
        decoded = _bits_to_text(bits)
        if decoded:
            best = (name, decoded)
            break
        # Also try the inverted assignment; conventions differ.
        decoded = _bits_to_text(bits.translate(str.maketrans("01", "10")))
        if decoded:
            best = (f"{name} (inverted)", decoded)
            break

    if best is None:
        return None

    scheme_name, decoded = best
    return HiddenPayload(
        scheme="zero-width-binary",
        decoded=decoded,
        start=positions[0],
        end=positions[-1] + 1,
        char_count=len(symbols),
        printable_ratio=_printable_ratio(decoded),
        note=(
            f"Decoded from zero-width characters as binary ({scheme_name}), "
            + (
                "distributed through the text rather than in one run."
                if spread
                else "in a contiguous run."
            )
        ),
    )


def decode_zero_width_binary(text: str) -> List[HiddenPayload]:
    """Recover text encoded as zero-width bits.

    Two passes: contiguous runs first, then a whole-document pass for payloads
    that were deliberately spread between visible characters.
    """
    payloads: List[HiddenPayload] = []
    consumed: set = set()

    # Pass 1: contiguous runs.
    run_symbols: List[str] = []
    run_positions: List[int] = []

    def flush_run() -> None:
        if len(run_symbols) >= _MIN_BINARY_RUN:
            found = _decode_symbol_sequence(run_symbols, run_positions, spread=False)
            if found:
                payloads.append(found)
                consumed.update(run_positions)

    for idx, ch in enumerate(text):
        if ch in ZW_SYMBOLS:
            run_symbols.append(ch)
            run_positions.append(idx)
        else:
            flush_run()
            run_symbols = []
            run_positions = []
    flush_run()

    # Pass 2: symbols spread through the document.
    spread_symbols: List[str] = []
    spread_positions: List[int] = []
    for idx, ch in enumerate(text):
        if ch in ZW_SYMBOLS and idx not in consumed:
            spread_symbols.append(ch)
            spread_positions.append(idx)

    if len(spread_symbols) >= _MIN_BINARY_RUN:
        found = _decode_symbol_sequence(spread_symbols, spread_positions, spread=True)
        if found:
            payloads.append(found)

    return payloads


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def decode_payloads(text: str) -> List[HiddenPayload]:
    """Run every decoder and return whatever was actually recovered."""
    payloads: List[HiddenPayload] = []
    payloads.extend(decode_tag_runs(text))
    payloads.extend(decode_variation_selector_runs(text))
    payloads.extend(decode_zero_width_binary(text))
    payloads.sort(key=lambda p: p.start)
    return payloads


# ---------------------------------------------------------------------------
# Encoders - used by the test-suite and by `loraai forge` to build samples
# ---------------------------------------------------------------------------


def encode_tags(payload: str) -> str:
    """Encode ASCII into the Unicode Tags block (inverse of the decoder)."""
    out = []
    for ch in payload:
        cp = ord(ch)
        if 0x20 <= cp <= 0x7E:
            out.append(chr(TAG_START + cp))
        else:
            raise ValueError(f"not encodable as a tag character: {ch!r}")
    return "".join(out)


def encode_variation_selectors(payload: str) -> str:
    """Encode text as a chain of variation selectors."""
    out = []
    for byte in payload.encode("utf-8"):
        out.append(chr(VS_LOW[0] + byte) if byte < 16 else chr(VS_HIGH[0] + byte - 16))
    return "".join(out)


def encode_zero_width_binary(payload: str, scheme: str = "zwsp/zwnj") -> str:
    """Encode text as zero-width binary using one of the known schemes."""
    mapping: Dict[str, Tuple[str, str]] = {
        name: (zero, one) for name, zero, one in _BIT_SCHEMES
    }
    if scheme not in mapping:
        raise ValueError(f"unknown scheme: {scheme}")
    zero, one = mapping[scheme]
    bits = "".join(f"{b:08b}" for b in payload.encode("utf-8"))
    return "".join(zero if bit == "0" else one for bit in bits)
