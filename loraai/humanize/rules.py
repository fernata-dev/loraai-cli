"""Transformation rules for the offline humanizer.

Scope and honesty
-----------------
These rules improve naturalness by removing the stylistic habits catalogued in
:mod:`loraai.analysis.markers`: inflated vocabulary, formulaic scaffolding,
chat-assistant voice, mechanical sentence rhythm. That is a genuine and
measurable improvement to prose.

It is **not** a detector-evasion tool and is not described as one anywhere in
this codebase. Removing invisible characters is exact; removing style markers
is real but bounded; and neither touches a statistical sampling watermark,
which lives in token choice rather than in any character or phrase. See
:mod:`loraai.analysis.provenance`.

Every rule is reversible in the sense that the original is always retained and
a diff is always available -- the humanizer never overwrites without showing
its work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Pattern, Tuple

from ..analysis.markers import ar_pattern

ALL_STYLES = frozenset(
    {"natural", "concise", "professional", "academic", "conversational"}
)
INFORMAL_STYLES = frozenset({"natural", "conversational"})
FORMAL_STYLES = frozenset({"professional", "academic"})


@dataclass(frozen=True)
class Substitution:
    """A regex-driven text substitution."""

    rule_id: str
    category: str
    pattern: Pattern[str]
    replacement: str | Callable[[re.Match], str]
    #: Lowest intensity at which this rule fires (1 = always, 3 = only at max).
    min_intensity: int = 1
    #: Styles this rule applies to.
    styles: FrozenSet[str] = ALL_STYLES
    description: str = ""


def _sub(
    rule_id: str,
    category: str,
    pattern: str,
    replacement: str | Callable[[re.Match], str],
    *,
    min_intensity: int = 1,
    styles: FrozenSet[str] = ALL_STYLES,
    flags: int = re.IGNORECASE,
    description: str = "",
) -> Substitution:
    return Substitution(
        rule_id, category, re.compile(pattern, flags), replacement,
        min_intensity, styles, description,
    )


def _match_case(source: str, target: str) -> str:
    """Give *target* the capitalisation pattern of *source*."""
    if not source or not target:
        return target
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[0].isupper():
        return target[0].upper() + target[1:]
    return target


def _cased(target: str) -> Callable[[re.Match], str]:
    """Replacement callable that preserves the matched text's case."""

    def replace(match: re.Match) -> str:
        return _match_case(match.group(0), target)

    return replace


# ---------------------------------------------------------------------------
# Vocabulary simplification (English)
# ---------------------------------------------------------------------------

_VOCAB_EN: Tuple[Tuple[str, str], ...] = (
    (r"\bdelve into\b", "look at"),
    (r"\bdelve\b", "dig in"),
    (r"\bleverage(?=\s)\b", "use"),
    (r"\bleverages\b", "uses"),
    (r"\bleveraged\b", "used"),
    (r"\bleveraging\b", "using"),
    (r"\butilize\b", "use"),
    (r"\butilizes\b", "uses"),
    (r"\butilized\b", "used"),
    (r"\butilizing\b", "using"),
    (r"\bfacilitate\b", "help"),
    (r"\bfacilitates\b", "helps"),
    (r"\ba myriad of\b", "many"),
    (r"\bmyriad of\b", "many"),
    (r"\ba myriad\b", "many"),
    (r"\bmyriad\b", "many"),
    (r"\bplethora of\b", "plenty of"),
    (r"\bmeticulously\b", "carefully"),
    (r"\bmeticulous\b", "careful"),
    (r"\bseamlessly\b", "smoothly"),
    (r"\bseamless\b", "smooth"),
    (r"\bpivotal\b", "key"),
    (r"\bparamount\b", "critical"),
    (r"\bintricate\b", "complicated"),
    (r"\bmultifaceted\b", "complex"),
    (r"\bnuanced\b", "subtle"),
    (r"\bprofound\b", "deep"),
    (r"\bunwavering\b", "steady"),
    (r"\binvaluable\b", "valuable"),
    (r"\btransformative\b", "major"),
    (r"\bcutting[- ]edge\b", "advanced"),
    (r"\bstate[- ]of[- ]the[- ]art\b", "advanced"),
    (r"\bgame[- ]?chang(?:er|ing)\b", "turning point"),
    (r"\bembark on\b", "start"),
    (r"\bembark upon\b", "start"),
    (r"\bfoster\b", "encourage"),
    (r"\bfosters\b", "encourages"),
    (r"\bfostering\b", "encouraging"),
    (r"\bharness\b", "use"),
    (r"\bharnessing\b", "using"),
    (r"\bgarner\b", "get"),
    (r"\bgarnered\b", "got"),
    (r"\belevate\b", "raise"),
    (r"\bunderscore\b", "show"),
    (r"\bunderscores\b", "shows"),
    (r"\bunderscoring\b", "showing"),
    (r"\bexemplif(?:y|ies)\b", "shows"),
    (r"\bencompass(?:es)?\b", "covers"),
    (r"\bendeavor\b", "effort"),
    (r"\bcommence\b", "start"),
    (r"\bsubsequently\b", "then"),
    (r"\bprior to\b", "before"),
    (r"\bin order to\b", "to"),
    (r"\bdue to the fact that\b", "because"),
    (r"\bwith regard to\b", "about"),
    (r"\bin terms of\b", "for"),
    (r"\ba wide (?:range|array|variety) of\b", "many"),
    (r"\bthe realm of\b", ""),
    (r"\bthe world of\b", ""),
    (r"\bthe landscape of\b", ""),
    (r"\bit is worth noting that\b", ""),
    (r"\bit'?s worth noting that\b", ""),
    (r"\bit is important to note that\b", ""),
    (r"\bit'?s important to note that\b", ""),
    (r"\bit should be noted that\b", ""),
    (r"\bneedless to say,?\s*", ""),
    (r"\bwhen it comes to\b", "for"),
    (r"\bat the end of the day\b", "in the end"),
    (r"\bin today'?s (?:fast[- ]paced |modern |digital |ever[- ]evolving )?world,?\s*", ""),
    (r"\bin the ever[- ]evolving (?:landscape|world) of\b", "in"),
    (r"\bstands as a testament to\b", "shows"),
    (r"\bis a testament to\b", "shows"),
    (r"\ba testament to\b", "proof of"),
    (r"\bstands as\b", "is"),
    (r"\bserves as\b", "is"),
    (r"\bplays? an? (?:crucial|vital|key|significant|pivotal) role in\b", "matters for"),
    (r"\bplays? an? (?:crucial|vital|key|significant|pivotal) role\b", "matters"),
    (r"\bboasts\b", "has"),
    (r"\bever[- ]evolving\b", "changing"),
    (r"\bfast[- ]paced\b", "busy"),
    (r"\bvibrant\b", "lively"),
    (r"\bbustling\b", "busy"),
    (r"\bholistic\b", "overall"),
    (r"\brobust\b", "solid"),
    (r"\bresonates? with\b", "connects with"),
    (r"\bnavigat(?:e|ing) the (?:complexities|challenges|landscape) of\b", "handling"),
    (r"\bdive deeper into\b", "look closer at"),
    (r"\bdive into\b", "look at"),
    (r"\blet'?s explore\b", "here is"),
    (r"\bin the realm of\b", "in"),
    (r"\brich tapestry of\b", "mix of"),
    (r"\btapestry of\b", "mix of"),
    # Each replacement has to drop straight into the slot the original filled.
    # A separable phrasal verb such as "put to work" needs its object in the
    # middle and would produce "put to work these capabilities", so the
    # alternatives here are all single verbs or inseparable phrases.
    (r"\brapidly evolving\b", "changing"),
    (r"\brapidly changing\b", "changing"),
    # Tolerant of an adjective or two in the middle, because an earlier rule
    # in this table may already have rewritten one ("rapidly evolving" ->
    # "changing") and a fixed phrase would then no longer match.
    (r"\bin today'?s\s+(?:[\w-]+\s+){0,2}(?:landscape|era|age|climate|environment),?\s*", ""),
    (r"\bpav(?:e|es|ing) the way for\b", "leading to"),
    (r"\bpaved the way for\b", "led to"),
    (r"\bshowcase\b", "show"),
    (r"\bshowcases\b", "shows"),
    (r"\bshowcasing\b", "showing"),
    (r"\bstreamline\b", "simplify"),
    (r"\bstreamlines\b", "simplifies"),
    (r"\bstreamlining\b", "simplifying"),
    (r"\bparadigm shift\b", "shift"),
    (r"\bparadigm\b", "model"),
    (r"\bunprecedented\b", "new"),
    (r"\btremendous\b", "huge"),
    (r"\bunlock\b", "release"),
    (r"\bunlocks\b", "releases"),
    (r"\bunlocking\b", "releasing"),
    (r"\brealms\b", "areas"),
    (r"\brealm\b", "area"),
    (r"\bnavigate\b", "handle"),
    (r"\bnavigates\b", "handles"),
    (r"\bnavigating\b", "handling"),
    (r"\bspearhead(?:s|ing)?\b", "lead"),
    (r"\bbespoke\b", "custom"),
    (r"\bsynerg(?:y|ies)\b", "overlap"),
    (r"\bactionable insights?\b", "advice"),
    (r"\bkey takeaways?\b", "main point"),
    (r"\bdeep dive\b", "close look"),
    (r"\bmoving forward,?\s*", ""),
    (r"\bthat being said,?\s*", "still, "),
    (r"\bcannot be (?:overstated|understated)\b", "matters"),
)

VOCABULARY_EN: List[Substitution] = [
    _sub(
        f"hum.vocab.{index}",
        "vocabulary",
        pattern,
        _cased(replacement) if replacement else "",
        min_intensity=1 if replacement == "" else 2,
        description=f"Simplify to {replacement!r}" if replacement else "Remove filler",
    )
    for index, (pattern, replacement) in enumerate(_VOCAB_EN)
]

# ---------------------------------------------------------------------------
# Assistant voice removal - always applied, every style and intensity
# ---------------------------------------------------------------------------

ASSISTANT_VOICE: List[Substitution] = [
    _sub(
        "hum.assistant.opener",
        "assistant-voice",
        r"(?:^|\n)[ \t]*(?:Great|Excellent|Fantastic|Wonderful|Perfect|Good)\s+"
        r"(?:question|point|catch|observation|idea)[!.]?\s*",
        "\n",
        description="Remove chat-assistant compliment opener",
    ),
    _sub(
        "hum.assistant.ack",
        "assistant-voice",
        r"(?:^|\n)[ \t]*(?:Certainly|Absolutely|Of course|Sure thing|Sure)[!,.]\s*",
        "\n",
        description="Remove acknowledgement opener",
    ),
    _sub(
        "hum.assistant.selfref",
        "assistant-voice",
        r"\bAs an AI(?:\s+language)?(?:\s+model)?,?\s*",
        "",
        description="Remove model self-reference",
    ),
    _sub(
        "hum.assistant.nopinion",
        "assistant-voice",
        r"\b(?:I|As an AI,? I)\s+(?:don'?t|do not)\s+have\s+"
        r"(?:personal\s+|real[- ]time\s+)?(?:opinions|feelings|beliefs|access)"
        r"[^.!?\n]*[.!?]\s*",
        "",
        description="Remove model capability disclaimer",
    ),
    _sub(
        "hum.assistant.signoff",
        "assistant-voice",
        r"(?:^|\n|(?<=[.!?])\s)[ \t]*(?:I hope (?:this|that) helps|Hope (?:this|that) helps|"
        r"Let me know if you(?:'d| would)?\s+(?:have|need|like|want)[^.!?\n]*|"
        r"Feel free to (?:ask|reach out)[^.!?\n]*)[.!]?\s*",
        " ",
        description="Remove chat sign-off",
    ),
    _sub(
        "hum.assistant.summary_header",
        "assistant-voice",
        r"(?:^|\n|(?<=[.!?])\s)[ \t]*(?:In conclusion|To sum up|To summarize|"
        r"In summary|Overall|All in all)[,:]\s*",
        " ",
        description="Remove formulaic conclusion header",
    ),
]

# ---------------------------------------------------------------------------
# Transition scaffolding
# ---------------------------------------------------------------------------

TRANSITIONS: List[Substitution] = [
    _sub(
        "hum.transition.moreover",
        "transition",
        r"(?:^|\n)([ \t]*)(?:Moreover|Furthermore|Additionally|In addition)\s*,\s*",
        lambda m: f"\n{m.group(1)}",
        min_intensity=1,
        description="Drop additive discourse marker at paragraph start",
    ),
    _sub(
        "hum.transition.inline_moreover",
        "transition",
        r"(?<=[.!?])\s+(?:Moreover|Furthermore|Additionally)\s*,\s*",
        " ",
        min_intensity=2,
        description="Drop additive discourse marker mid-paragraph",
    ),
    _sub(
        "hum.transition.consequently",
        "transition",
        r"\b(?:Consequently|Subsequently|Accordingly)\s*,\s*",
        _cased("So "),
        min_intensity=2,
        styles=INFORMAL_STYLES | {"professional"},
        description="Replace formal consequence marker",
    ),
    _sub(
        "hum.transition.nevertheless",
        "transition",
        r"\b(?:Nevertheless|Nonetheless)\s*,\s*",
        _cased("Still, "),
        min_intensity=2,
        styles=INFORMAL_STYLES | {"professional"},
        description="Replace formal contrast marker",
    ),
    _sub(
        "hum.transition.ultimately",
        "transition",
        r"\bUltimately,\s*",
        "",
        min_intensity=2,
        description="Drop 'Ultimately' scaffolding",
    ),
]

# ---------------------------------------------------------------------------
# Structural repairs
# ---------------------------------------------------------------------------

STRUCTURE: List[Substitution] = [
    _sub(
        "hum.structure.participial",
        "structure",
        r",\s+(?:highlighting|underscoring|showcasing|reflecting|emphasizing|"
        r"demonstrating|illustrating|signaling|cementing|solidifying)\s+"
        r"(?:the\s+)?[^.!?\n]{3,60}(?=[.!?])",
        "",
        min_intensity=2,
        description="Remove trailing participial pseudo-analysis",
    ),
    _sub(
        "hum.structure.hedge_stack",
        "hedging",
        r"\b(may|might|could|can)\s+(?:potentially|possibly|perhaps|arguably)\b",
        lambda m: m.group(1),
        min_intensity=1,
        description="Collapse stacked hedges to one",
    ),
    _sub(
        "hum.structure.vague_attribution",
        "attribution",
        r"\b(?:Experts?|Researchers?|Studies|Scientists?|Analysts?|Critics?|"
        r"Observers?)\s+"
        r"(?:say|says|said|suggest|suggests|believe|believes|argue|argues|"
        r"note|notes|show|shows|indicate|indicates)\s+(?:that\s+)?",
        "",
        min_intensity=3,
        description="Remove vague appeal to authority (claim is kept)",
    ),
    _sub(
        "hum.structure.negative_parallelism",
        "structure",
        r"\b(?P<lead>(?:is|are|was|were|be|been)\s+)?"
        r"not\s+(?:just|only|merely|simply)\s+"
        r"(?P<first>[^.!?;]{2,70}?)\s*,?\s+but(?:\s+also)?\s+"
        r"(?P<second>[^.!?;]{2,90})",
        lambda m: f"{m.group('lead') or ''}{m.group('second').strip()}",
        min_intensity=2,
        description="Keep the second half of \"not just X, but Y\"",
    ),
    _sub(
        "hum.structure.negative_parallelism_its",
        "structure",
        r"\bit'?s\s+not\s+(?:about\s+)?(?P<first>[^.!?;]{2,60}?)\s*,\s*"
        r"it'?s\s+(?P<second>[^.!?;]{2,80})",
        lambda m: f"it's {m.group('second').strip()}",
        min_intensity=2,
        description="Collapse \"it's not X, it's Y\" to the claim itself",
    ),
    _sub(
        "hum.structure.impersonal_authority",
        "attribution",
        r"\bit\s+(?:is|was)\s+(?:widely|generally|commonly|often)\s+"
        r"(?:believed|accepted|known|understood|regarded|thought)\s+that\s+",
        "",
        min_intensity=2,
        description="Remove consensus attributed to nobody (claim is kept)",
    ),
    _sub(
        "hum.structure.em_dash",
        "punctuation",
        r"\s+[—–]\s+",
        ", ",
        min_intensity=2,
        description="Replace em dash with a comma",
    ),
    _sub(
        "hum.structure.very",
        "vocabulary",
        r"\b(?:very|really|quite|extremely|incredibly)\s+(?=\w)",
        "",
        min_intensity=3,
        styles=frozenset({"concise", "professional", "academic"}),
        description="Drop intensifier adverbs",
    ),
]

# ---------------------------------------------------------------------------
# Contractions - informal styles only
# ---------------------------------------------------------------------------

_CONTRACTIONS: Tuple[Tuple[str, str], ...] = (
    (r"\bdo not\b", "don't"), (r"\bdoes not\b", "doesn't"),
    (r"\bdid not\b", "didn't"), (r"\bis not\b", "isn't"),
    (r"\bare not\b", "aren't"), (r"\bwas not\b", "wasn't"),
    (r"\bwere not\b", "weren't"), (r"\bhave not\b", "haven't"),
    (r"\bhas not\b", "hasn't"), (r"\bhad not\b", "hadn't"),
    (r"\bwill not\b", "won't"), (r"\bwould not\b", "wouldn't"),
    (r"\bshould not\b", "shouldn't"), (r"\bcould not\b", "couldn't"),
    (r"\bcannot\b", "can't"), (r"\bcan not\b", "can't"),
    (r"\bit is\b", "it's"), (r"\bthat is\b", "that's"),
    (r"\bthere is\b", "there's"), (r"\bwhat is\b", "what's"),
    (r"\bthey are\b", "they're"), (r"\bwe are\b", "we're"),
    (r"\byou are\b", "you're"), (r"\bI am\b", "I'm"),
    (r"\bI will\b", "I'll"), (r"\bwe will\b", "we'll"),
    (r"\bI have\b", "I've"), (r"\bwe have\b", "we've"),
    (r"\byou have\b", "you've"), (r"\blet us\b", "let's"),
)

CONTRACTIONS: List[Substitution] = [
    _sub(
        f"hum.contraction.{index}",
        "register",
        pattern,
        _cased(replacement),
        min_intensity=2,
        styles=INFORMAL_STYLES,
        description=f"Contract to {replacement!r}",
    )
    for index, (pattern, replacement) in enumerate(_CONTRACTIONS)
]

# ---------------------------------------------------------------------------
# Arabic
# ---------------------------------------------------------------------------

#: Arabic phrases to rewrite, written as plain text. Each is compiled through
#: :func:`~loraai.analysis.markers.ar_pattern`, the same builder the detector
#: uses, so anything the analysis flags is something the humanizer can repair.
#: ``{}`` marks a place where intervening words are allowed.
_AR_PHRASE_SUBSTITUTIONS: Tuple[Tuple[str, str], ...] = (
    ("في عالم اليوم", ""),
    ("في عالمنا المعاصر", ""),
    ("تجدر الإشارة إلى أن", ""),
    ("من الجدير بالذكر أن", ""),
    ("لا بد من الإشارة إلى أن", ""),
    ("في الختام", ""),
    ("وفي نهاية المطاف", ""),
    ("خلاصة القول", ""),
    ("علاوة على ذلك", ""),
    ("بالإضافة إلى ذلك", "كذلك"),
    ("بشكل عام", ""),
    ("يلعب{}دورا حاسما", "مهم"),
    ("تلعب{}دورا حاسما", "مهمة"),
    ("يلعب{}دورا محوريا", "مهم"),
    ("يعد من أهم", "من أهم"),
    ("تعد من أهم", "من أهم"),
    ("مما يسلط الضوء على", "ويظهر"),
    ("مما يعكس", "ويظهر"),
    ("مما يبرز", "ويظهر"),
    ("يفتح آفاقا واسعة", "يتيح فرصا"),
    ("نقلة نوعية", "تغييرا"),
    ("ثورة حقيقية", "تغييرا كبيرا"),
    ("آمل أن يكون هذا مفيدا", ""),
    ("لا تتردد في السؤال", ""),
    ("بصفتي نموذج ذكاء اصطناعي", ""),
    ("شهدت السنوات الأخيرة", "مؤخرا"),
)

#: Trailing comma/period and surrounding space are absorbed when a phrase is
#: deleted outright, so removal does not leave orphaned punctuation.
_AR_TRAILING = r"[،,.]?\s*"

#: The gap in a ``{}`` phrase is *captured*, not discarded. In
#: "yal'ab <SUBJECT> dawran hasiman", the subject sits inside the gap, and
#: dropping it would delete the sentence's content rather than its padding.
_AR_GAP = r"([^.،؟!\n]{0,40})"


def _build_arabic_substitutions() -> Tuple[Tuple[str, str], ...]:
    """Compile the Arabic phrase table into (pattern, replacement) pairs.

    Gapped phrases put the captured gap back in front of the replacement,
    which is the correct word order once the verb phrase is dropped: Arabic
    "plays <X> a crucial role" becomes "<X> is important".
    """
    built = []
    for phrase, replacement in _AR_PHRASE_SUBSTITUTIONS:
        gapped = "{}" in phrase
        pattern = ar_pattern(phrase, gap=_AR_GAP) + _AR_TRAILING
        if gapped:
            # Keep the captured content; append the replacement after it.
            target = r"\1 " + replacement + " " if replacement else r"\1 "
        else:
            target = (replacement + " ") if replacement else ""
        built.append((pattern, target))
    return tuple(built)


_AR_SUBSTITUTIONS: Tuple[Tuple[str, str], ...] = _build_arabic_substitutions()

ARABIC: List[Substitution] = [
    _sub(
        f"hum.ar.{index}",
        "phrase",
        pattern,
        replacement,
        min_intensity=1 if replacement == "" else 2,
        flags=0,
        description="Arabic phrasing cleanup",
    )
    for index, (pattern, replacement) in enumerate(_AR_SUBSTITUTIONS)
]


def rules_for(language: str, style: str, intensity: int) -> List[Substitution]:
    """Select the active rule set for a language, style and intensity."""
    # STRUCTURE comes before VOCABULARY_EN deliberately. A structural rule
    # removes a whole clause; a vocabulary rule rewrites one word inside it.
    # With vocabulary first, "underscoring" became "showing" before the
    # participial rule - whose pattern lists "underscoring" - could match, so
    # the trailing clause survived every intensity.
    pool: List[Substitution] = list(ASSISTANT_VOICE)
    if language == "ar":
        pool += ARABIC
    elif language == "mixed":
        pool += ARABIC + STRUCTURE + VOCABULARY_EN + TRANSITIONS + CONTRACTIONS
    else:
        pool += STRUCTURE + VOCABULARY_EN + TRANSITIONS + CONTRACTIONS

    return [
        rule
        for rule in pool
        if rule.min_intensity <= intensity and style in rule.styles
    ]
