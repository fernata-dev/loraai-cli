"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from loraai.analysis.payload import (
    encode_tags,
    encode_variation_selectors,
    encode_zero_width_binary,
)

@pytest.fixture
def tag_payload_text():
    """Cover text with an ASCII payload smuggled through the Tags block."""
    return "Normal visible text. " + encode_tags("SECRET-PAYLOAD-123") + " More text."


@pytest.fixture
def vs_payload_text():
    """Cover text with bytes chained as variation selectors."""
    return "Emoji here \U0001F600" + encode_variation_selectors("vs-secret-42") + " end."


@pytest.fixture
def zw_payload_text():
    """Cover text with a zero-width binary payload."""
    return "Plain sentence." + encode_zero_width_binary("zw-secret") + " Tail."


@pytest.fixture
def tmp_text_file(tmp_path):
    """Factory writing a UTF-8 file and returning its path."""

    def make(content: str, name: str = "sample.txt") -> str:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    return make
