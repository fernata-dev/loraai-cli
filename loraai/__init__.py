"""loraai - text forensics, hidden-Unicode detection, writing analysis and
humanization.

Quick start
-----------
::

    from loraai import textio
    from loraai.analysis import analyze

    loaded = textio.from_file("article.md")
    result = analyze(loaded)
    print(result.synthetic.verdict.label)
    print(result.unicode.total, "unicode finding(s)")

Three things this package is careful about:

* **Invisible characters** are detected and removed *exactly* -- they are
  present in the byte stream, so this is not guesswork.
* **Writing style** is assessed *probabilistically*, and the result always
  travels with its caveats. It never claims to prove authorship.
* **Statistical sampling watermarks** are reported as undetectable locally,
  because they are. See :mod:`loraai.analysis.provenance`.
"""

from .version import __version__, get_version

__all__ = ["__version__", "get_version"]
