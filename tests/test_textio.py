"""Input handling: files, text, stdin, encodings and error paths."""

from __future__ import annotations

import io
import sys

import pytest

from loraai import textio
from loraai.errors import BinaryFileError, FileAccessError, FileTooLargeError, InputError

from .samples import ARABIC_PROSE, HUMAN_STYLE, MARKDOWN_SOURCE, PYTHON_SOURCE


class TestFromText:
    def test_basic(self):
        loaded = textio.from_text("hello world")
        assert loaded.text == "hello world"
        assert loaded.source.origin == "text"

    def test_language_detection(self):
        assert textio.from_text(ARABIC_PROSE).source.language == "ar"
        assert textio.from_text(HUMAN_STYLE).source.language == "en"

    def test_empty(self):
        assert textio.from_text("").is_empty


class TestFromFile:
    def test_utf8(self, tmp_text_file):
        path = tmp_text_file(ARABIC_PROSE, "arabic.txt")
        loaded = textio.from_file(path)
        assert loaded.text == ARABIC_PROSE
        assert loaded.source.encoding == "utf-8"
        assert not loaded.source.had_bom

    def test_bom_is_consumed_and_reported(self, tmp_path):
        path = tmp_path / "bom.txt"
        path.write_bytes(b"\xef\xbb\xbfhello")
        loaded = textio.from_file(path)
        assert loaded.text == "hello"
        assert loaded.source.had_bom

    @pytest.mark.parametrize(
        "encoding",
        ["utf-8", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le",
         "utf-32-be", "cp1256"],
    )
    def test_wide_and_legacy_encodings(self, tmp_path, encoding):
        """Every supported encoding must decode, BOM or no BOM.

        The wide encodings are the interesting case: they contain NUL bytes,
        which the binary check has to distinguish from actual binary data.
        """
        sample = "مرحبا بالعالم Hello world"
        path = tmp_path / f"{encoding}.txt"
        path.write_bytes(sample.encode(encoding))
        loaded = textio.from_file(path)
        assert loaded.text == sample
        assert "\x00" not in loaded.text

    def test_utf32_is_not_mistaken_for_utf16(self, tmp_path):
        # The UTF-32 LE BOM begins with the UTF-16 LE BOM, so a naive codec
        # order decodes it into garbage rather than failing.
        path = tmp_path / "u32.txt"
        path.write_bytes("Hello world".encode("utf-32"))
        loaded = textio.from_file(path)
        assert loaded.text == "Hello world"
        assert loaded.source.encoding.startswith("utf-32")

    @pytest.mark.parametrize(
        "blob",
        [bytes(range(256)) * 40, b"\x00" * 4096, b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20],
    )
    def test_binary_is_still_rejected(self, tmp_path, blob):
        path = tmp_path / "blob.bin"
        path.write_bytes(blob)
        with pytest.raises(BinaryFileError):
            textio.from_file(path)

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileAccessError) as excinfo:
            textio.from_file(tmp_path / "nope.txt")
        assert excinfo.value.hint

    def test_directory_rejected(self, tmp_path):
        with pytest.raises(FileAccessError, match="directory"):
            textio.from_file(tmp_path)

    def test_binary_rejected(self, tmp_path):
        path = tmp_path / "blob.bin"
        path.write_bytes(bytes(range(256)) * 40)
        with pytest.raises(BinaryFileError):
            textio.from_file(path)

    def test_size_limit(self, tmp_text_file):
        path = tmp_text_file("x" * 5000)
        with pytest.raises(FileTooLargeError, match="limit"):
            textio.from_file(path, max_bytes=100)

    @pytest.mark.parametrize(
        "name,kind",
        [
            ("a.py", "code"),
            ("a.js", "code"),
            ("a.md", "markup"),
            ("a.html", "markup"),
            ("a.json", "data"),
            ("a.csv", "data"),
            ("a.txt", "prose"),
        ],
    )
    def test_content_kind_from_extension(self, tmp_text_file, name, kind):
        assert textio.from_file(tmp_text_file("content here", name)).source.content_kind == kind


class TestResolve:
    def test_rejects_two_sources(self):
        with pytest.raises(InputError, match="More than one"):
            textio.resolve(text="a", file="b")

    def test_rejects_no_source(self):
        with pytest.raises(InputError) as excinfo:
            textio.resolve()
        assert "--text" in excinfo.value.hint

    def test_text_source(self):
        assert textio.resolve(text="hi").text == "hi"

    def test_file_source(self, tmp_text_file):
        path = tmp_text_file("from file")
        assert textio.resolve(file=path).text == "from file"


class TestStdin:
    def test_reads_piped_input(self, monkeypatch):
        class PipedStdin:
            def __init__(self, payload: bytes) -> None:
                self.buffer = io.BytesIO(payload)

            def isatty(self) -> bool:
                return False

        monkeypatch.setattr(sys, "stdin", PipedStdin(b"piped text"))
        assert textio.from_stdin().text == "piped text"

    def test_rejects_binary_on_stdin(self, monkeypatch):
        class PipedStdin:
            def __init__(self, payload: bytes) -> None:
                self.buffer = io.BytesIO(payload)

            def isatty(self) -> bool:
                return False

        monkeypatch.setattr(sys, "stdin", PipedStdin(bytes(range(256)) * 40))
        with pytest.raises(BinaryFileError):
            textio.from_stdin()

    def test_tty_is_an_error(self, monkeypatch):
        class Tty:
            def isatty(self):
                return True

        monkeypatch.setattr(sys, "stdin", Tty())
        with pytest.raises(InputError, match="No piped input"):
            textio.from_stdin()


class TestProseExtraction:
    def test_python_comments_and_docstrings(self):
        prose = textio.extract_prose(PYTHON_SOURCE, "module.py")
        assert "module docstring" in prose
        assert "why the constant exists" in prose
        assert "import os" not in prose

    def test_c_style_comments(self):
        source = "int x = 1; // explain the thing\n/* block comment here */\n"
        prose = textio.extract_prose(source, "a.c")
        assert "explain the thing" in prose
        assert "block comment here" in prose

    def test_html_comments(self):
        prose = textio.extract_prose("<p>x</p><!-- a note -->", "a.html")
        assert "a note" in prose

    def test_no_comments_yields_empty(self):
        assert textio.extract_prose("x = 1\ny = 2\n", "a.py").strip() == ""
