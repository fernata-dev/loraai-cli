"""The analysis engine.

Passes are independent and each owns one question:

``tokenizer``           how the text divides into words, sentences, paragraphs
``statistics``          how much of everything there is
``stylometry``          rhythm, repetition, punctuation, register
``markers``             known AI-writing tells, English and Arabic
``unicode_forensics``   invisible, deceptive and control characters
``payload``             data decoded out of invisible characters
``synthetic``           the weighted assessment built from the above
``provenance``          what is and is not locally detectable
``pipeline``            runs them all and assembles one Analysis
"""

from .pipeline import analyze

__all__ = ["analyze"]
