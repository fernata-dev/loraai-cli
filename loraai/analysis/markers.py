"""Detection of AI-writing tells: the vocabulary, phrasing and structural
habits that large language models fall into.

What this is
------------
A curated ruleset over *style*, not content. Each rule describes a habit that
appears far more often in generated prose than in human writing: inflated
abstract nouns, discourse-marker scaffolding, negative parallelism, trailing
participial "analysis", vague attribution, and so on.

What this is not
----------------
Proof. A careful human writer can trip several of these rules, and a model
told to write plainly can trip none. Marker density is one input among many
to the assessment in :mod:`loraai.analysis.synthetic`, weighted accordingly.

Rules carry a ``suggestion`` because the humanizer in :mod:`loraai.humanize`
consumes this same table -- detection and repair stay in sync by construction.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Pattern, Sequence

from ..models import MarkerHit, MarkerReport, Severity
from .tokenizer import compute_line_starts, line_of, words


@dataclass(frozen=True)
class MarkerRule:
    """One detectable writing habit."""

    rule_id: str
    category: str
    pattern: Pattern[str]
    severity: Severity
    suggestion: str
    explanation: str
    language: str = "en"  # en | ar | any
    #: When set, hits are only reported if the rule fires at least this often
    #: per 1000 words. Used for habits that are only a tell in bulk.
    min_rate_per_1k: float = 0.0
    #: Replacement used by the humanizer. ``None`` means "needs rewriting",
    #: not "delete"; the humanizer skips those unless an LLM provider is set.
    replacement: Optional[str] = None


def _rule(
    rule_id: str,
    category: str,
    pattern: str,
    severity: Severity,
    suggestion: str,
    explanation: str,
    *,
    language: str = "en",
    flags: int = re.IGNORECASE,
    min_rate_per_1k: float = 0.0,
    replacement: Optional[str] = None,
) -> MarkerRule:
    return MarkerRule(
        rule_id=rule_id,
        category=category,
        pattern=re.compile(pattern, flags),
        severity=severity,
        suggestion=suggestion,
        explanation=explanation,
        language=language,
        min_rate_per_1k=min_rate_per_1k,
        replacement=replacement,
    )


#: Arabic combining marks plus tatweel, which may appear between any two
#: letters without changing the word.
_AR_SKIPPABLE = r"[\u064B-\u0652\u0670\u0640]*"

#: Orthographic variants that Arabic writers use interchangeably. Matching
#: them as classes means one rule covers every spelling of a phrase instead of
#: needing an entry per variant.
_AR_EQUIVALENTS = {
    "\u0627": "[\u0627\u0623\u0625\u0622]",   # alef forms
    "\u0623": "[\u0627\u0623\u0625\u0622]",
    "\u0625": "[\u0627\u0623\u0625\u0622]",
    "\u0622": "[\u0627\u0623\u0625\u0622]",
    "\u0629": "[\u0629\u0647]",                 # teh marbuta / heh
    "\u0647": "[\u0629\u0647]",
    "\u0649": "[\u0649\u064A]",                 # alef maksura / yeh
    "\u064A": "[\u0649\u064A]",
}


def ar_pattern(phrase: str, gap: str = "") -> str:
    """Build a diacritic- and spelling-tolerant regex for an Arabic phrase.

    Arabic text in the wild may or may not carry tashkeel, may use tatweel for
    justification, and spells alef and teh-marbuta inconsistently. Matching a
    literal string would miss most real occurrences, so each phrase is compiled
    into a pattern that tolerates all three.

    ``gap`` is inserted at ``{}`` placeholders in *phrase*, allowing rules like
    "yal'ab ... dawran hasiman" to match with words in between.
    """
    parts = []
    for chunk in phrase.split("{}"):
        piece = []
        for ch in chunk:
            if ch == " ":
                piece.append(r"\s+")
                continue
            piece.append(_AR_EQUIVALENTS.get(ch, re.escape(ch)))
            piece.append(_AR_SKIPPABLE)
        parts.append("".join(piece))
    return gap.join(parts)


# ---------------------------------------------------------------------------
# English rules
# ---------------------------------------------------------------------------

_EN_VOCABULARY = [
    ("delve", "look at", "A near-signature word: rare in human prose, common in generated text."),
    ("tapestry", "mix", "Inflated metaphor used as filler."),
    ("testament to", "shows", "Formulaic praise construction."),
    ("realm of", "area of", "Inflated register for an ordinary noun."),
    ("landscape of", "state of", "Abstract-noun filler."),
    ("underscore[sd]?", "shows", "Overused emphasis verb."),
    ("pivotal", "key", "Inflated intensifier."),
    ("crucial", "important", "Overused intensifier."),
    ("seamless(?:ly)?", "smooth", "Marketing register."),
    ("leverage[sd]?", "use", "Corporate register where a plain verb works."),
    ("harness(?:es|ed|ing)?", "use", "Inflated verb."),
    ("myriad", "many", "Inflated quantifier."),
    ("plethora", "plenty", "Inflated quantifier."),
    ("paramount", "most important", "Inflated intensifier."),
    ("intricate", "detailed", "Inflated adjective."),
    ("multifaceted", "complex", "Abstract filler adjective."),
    ("holistic", "overall", "Vague adjective."),
    ("meticulous(?:ly)?", "careful", "Inflated adjective."),
    ("vibrant", "lively", "Promotional adjective."),
    ("bustling", "busy", "Travel-brochure register."),
    ("unwavering", "steady", "Promotional adjective."),
    ("invaluable", "very useful", "Inflated adjective."),
    ("cutting[- ]edge", "advanced", "Marketing register."),
    ("game[- ]?changer", "big change", "Marketing cliche."),
    ("transformative", "major", "Inflated adjective."),
    ("robust", "strong", "Overused technical-sounding adjective."),
    ("nuanced", "subtle", "Inflated adjective."),
    ("profound", "deep", "Inflated intensifier."),
    ("embark(?:ing|ed)? on", "start", "Inflated verb phrase."),
    ("navigat(?:e|ing|es) the", "handle", "Overused metaphor."),
    ("foster(?:ing|ed|s)?", "encourage", "Inflated verb."),
    ("elevate[sd]?", "improve", "Marketing register."),
    ("resonate[sd]?", "connect", "Inflated verb."),
    ("garner(?:ed|ing|s)?", "get", "Inflated verb."),
    ("boast(?:s|ed|ing)?", "has", "Promotional verb."),
    ("stands? as", "is", "Inflated copula."),
    ("serves? as", "is", "Inflated copula."),
    ("plays? a (?:crucial|vital|key|significant|pivotal) role", "matters", "Formulaic importance claim."),
    ("rich (?:history|tapestry|tradition|heritage)", "long history", "Promotional cliche."),
    ("ever[- ]evolving", "changing", "Cliche modifier."),
    ("fast[- ]paced", "busy", "Cliche modifier."),
    ("in today's .{0,24}world", "today", "Stock essay opener."),
    ("it is (?:important|worth|crucial) to note that", "", "Empty throat-clearing."),
    ("it'?s (?:important|worth|crucial) to note that", "", "Empty throat-clearing."),
    ("when it comes to", "for", "Filler transition."),
    ("at the end of the day", "in the end", "Conversational filler cliche."),
    ("dive (?:in|into|deeper)", "look at", "Overused metaphor."),
    ("let'?s explore", "here is", "Presentational filler."),
    ("in conclusion", "", "Formulaic closer; the last paragraph is already the conclusion."),
    ("myriad", "many", "Inflated quantifier."),
    ("to sum(?: it)? up", "", "Formulaic closer."),
    ("in summary", "", "Formulaic closer."),
    ("the world of", "", "Empty noun-phrase padding."),
    ("a wide (?:range|array|variety) of", "many", "Padding quantifier."),
    ("a myriad of", "many", "Padding quantifier."),
]

RULES_EN: List[MarkerRule] = [
    _rule(
        f"en.vocab.{re.sub(r'[^a-z]+', '_', word.lower()).strip('_')}",
        "vocabulary",
        rf"\b{word}\b",
        Severity.MEDIUM,
        replacement_text,
        explanation,
        replacement=replacement_text or None,
    )
    for word, replacement_text, explanation in _EN_VOCABULARY
]

RULES_EN += [
    _rule(
        "en.structure.negative_parallelism",
        "structure",
        r"\b(?:it'?s|this is|that'?s|they'?re|he'?s|she'?s)\s+not\s+(?:just|only|merely|simply)\b[^.!?\n]{2,80}?[,;]?\s*(?:it'?s|they'?re|but)\b",
        Severity.HIGH,
        "State the positive claim directly.",
        "Negative parallelism ('not just X, it's Y') is one of the most "
        "reliable structural tells in generated prose.",
    ),
    _rule(
        "en.structure.not_only_but_also",
        "structure",
        r"\bnot only\b[^.!?\n]{2,90}?\bbut also\b",
        Severity.MEDIUM,
        "Split into two sentences, or drop one half.",
        "A balanced-clause construction models reach for far more often than "
        "people do.",
    ),
    _rule(
        "en.structure.participial_analysis",
        "structure",
        r",\s+(?:highlighting|underscoring|showcasing|reflecting|emphasizing|"
        r"demonstrating|illustrating|signaling|marking|cementing|solidifying|"
        r"ensuring|allowing|enabling|providing|offering|making it)\b",
        Severity.HIGH,
        "End the sentence, or state the consequence as its own clause.",
        "A trailing participial phrase that restates the sentence as if it "
        "were analysis. Adds length, not information.",
    ),
    _rule(
        "en.attribution.vague",
        "attribution",
        r"\b(?:experts?|researchers?|studies|scientists?|analysts?|critics?|"
        r"observers?|many people|some people|industry leaders?)\s+"
        r"(?:say|says|said|believe|believes|suggest|suggests|argue|argues|"
        r"note|notes|agree|agrees|show|shows|indicate|indicates)\b",
        Severity.HIGH,
        "Name the source, or drop the claim.",
        "Vague attribution: authority is invoked without anyone specific "
        "behind it.",
    ),
    _rule(
        "en.attribution.widely_regarded",
        "attribution",
        r"\b(?:is|are)\s+(?:widely|generally|often|commonly)\s+"
        r"(?:regarded|considered|recognized|acknowledged|seen|viewed|known)\b",
        Severity.MEDIUM,
        "Say who regards it that way.",
        "Passive consensus-claiming with no identifiable source.",
    ),
    _rule(
        "en.hedge.stack",
        "hedging",
        r"\b(?:may|might|could|can)\s+(?:potentially|possibly|perhaps|arguably)\b",
        Severity.MEDIUM,
        "Pick one hedge, or commit to the claim.",
        "Stacked hedging dilutes a sentence to nothing.",
    ),
    _rule(
        "en.assistant.sycophancy",
        "assistant-voice",
        r"(?:^|\n|(?<=[.!?])\s)\s*(?:Great|Excellent|Fantastic|Wonderful|Perfect|Good)\s+"
        r"(?:question|point|catch|observation|idea)\b[!.]?",
        Severity.CRITICAL,
        "Delete.",
        "Chat-assistant opener. Unambiguous artefact of a conversational model.",
        replacement="",
    ),
    _rule(
        "en.assistant.disclaimer",
        "assistant-voice",
        r"\bas an AI(?: language)?(?: model)?\b|"
        r"\bI (?:don'?t|do not) have (?:personal |real-time )?"
        r"(?:opinions|feelings|beliefs|access)\b|"
        r"\bI'?m (?:just )?an AI\b",
        Severity.CRITICAL,
        "Delete.",
        "Explicit model self-reference.",
        replacement="",
    ),
    _rule(
        "en.assistant.closing_offer",
        "assistant-voice",
        r"(?:^|\n|(?<=[.!?])\s)\s*(?:I hope this helps|Hope that helps|Let me know if you"
        r"(?:'d| would)? (?:have|need|like)|Feel free to (?:ask|reach out))"
        r"[^\n]*",
        Severity.CRITICAL,
        "Delete.",
        "Chat-assistant sign-off.",
        replacement="",
    ),
    _rule(
        "en.assistant.certainly",
        "assistant-voice",
        r"(?:^|\n|(?<=[.!?])\s)\s*(?:Certainly|Absolutely|Of course|Sure)[!,.]\s*",
        Severity.HIGH,
        "Delete.",
        "Chat-assistant acknowledgement opener.",
        replacement="",
    ),
    _rule(
        "en.punctuation.em_dash",
        "punctuation",
        r"\s*[—–]\s*",
        Severity.LOW,
        " - ",
        "Em-dash density well above typical human usage. Individually fine; "
        "in bulk it is a recognisable habit.",
        min_rate_per_1k=6.0,
        replacement=", ",
    ),
    _rule(
        "en.structure.rule_of_three",
        "structure",
        r"\b(\w+(?:\s+\w+){0,2}),\s+(\w+(?:\s+\w+){0,2}),\s+and\s+(\w+(?:\s+\w+){0,2})\b",
        Severity.LOW,
        "Use two items, or four.",
        "Three-item lists are natural occasionally and mechanical in bulk.",
        min_rate_per_1k=3.0,
    ),
    _rule(
        "en.transition.paragraph_glue",
        "transition",
        r"(?:^|\n)\s*(?:Moreover|Furthermore|Additionally|Consequently|"
        r"Nevertheless|Nonetheless|Subsequently|Ultimately|Notably|Importantly)"
        r"\s*,",
        Severity.MEDIUM,
        "Start with the subject instead.",
        "Formal discourse markers used as paragraph scaffolding.",
        min_rate_per_1k=2.0,
        replacement="",
    ),
]

# ---------------------------------------------------------------------------
# Arabic rules
# ---------------------------------------------------------------------------

_AR_PHRASES = [
    ("في عالم اليوم", "اليوم", "افتتاحية إنشائية نمطية."),
    ("في عالمنا المعاصر", "اليوم", "افتتاحية إنشائية نمطية."),
    ("في ظل التطور السريع", "مع التطور", "عبارة نمطية مكررة."),
    ("تجدر الإشارة إلى أن", "", "حشو استهلالي بلا معنى مضاف."),
    ("من الجدير بالذكر أن", "", "حشو استهلالي بلا معنى مضاف."),
    ("لا بد من الإشارة إلى", "", "حشو استهلالي."),
    ("يلعب{}دورا حاسما", "مهم", "صيغة نمطية لتأكيد الأهمية."),
    ("تلعب{}دورا حاسما", "مهم", "صيغة نمطية لتأكيد الأهمية."),
    ("يلعب{}دورا محوريا", "مهم", "صيغة نمطية لتأكيد الأهمية."),
    ("تلعب{}دورا محوريا", "مهم", "صيغة نمطية لتأكيد الأهمية."),
    ("يعد من أهم", "من أهم", "صيغة تفضيل نمطية."),
    ("تعد من أهم", "من أهم", "صيغة تفضيل نمطية."),
    ("يعتبر من أبرز", "من أبرز", "صيغة تفضيل نمطية."),
    ("تعتبر من أبرز", "من أبرز", "صيغة تفضيل نمطية."),
    ("في الختام", "", "خاتمة نمطية؛ الفقرة الأخيرة خاتمة أصلا."),
    ("وفي نهاية المطاف", "", "خاتمة نمطية."),
    ("خلاصة القول", "", "خاتمة نمطية."),
    ("بشكل عام", "", "حشو تعميمي."),
    ("بشكل كبير", "كثيرا", "حشو توكيدي."),
    ("بشكل ملحوظ", "بوضوح", "حشو توكيدي."),
    ("مما يسلط الضوء على", "ويظهر", "تحليل سطحي ملحق بالجملة."),
    ("مما يعكس", "ويظهر", "تحليل سطحي ملحق بالجملة."),
    ("مما يبرز", "ويظهر", "تحليل سطحي ملحق بالجملة."),
    ("مما يجعله", "فهو", "تحليل سطحي ملحق بالجملة."),
    ("شهدت السنوات الأخيرة", "مؤخرا", "افتتاحية نمطية."),
    ("يشهد العالم", "", "افتتاحية نمطية."),
    ("علاوة على ذلك", "كذلك", "أداة ربط نمطية مكررة."),
    ("بالإضافة إلى ذلك", "كذلك", "أداة ربط نمطية مكررة."),
    ("ومن ناحية أخرى", "لكن", "أداة ربط نمطية."),
    ("نسيجا غنيا", "مزيجا", "استعارة مضخمة."),
    ("ثورة حقيقية", "تغييرا", "مبالغة ترويجية."),
    ("نقلة نوعية", "تغييرا", "مبالغة ترويجية."),
    ("يفتح آفاقا واسعة", "يتيح", "مبالغة ترويجية."),
]

RULES_AR: List[MarkerRule] = [
    _rule(
        f"ar.phrase.{idx}",
        "phrase",
        ar_pattern(phrase, gap=r"[^.\u060C\u061F!\n]{0,40}"),
        Severity.MEDIUM,
        replacement_text,
        explanation,
        language="ar",
        flags=0,
        replacement=replacement_text or None,
    )
    for idx, (phrase, replacement_text, explanation) in enumerate(_AR_PHRASES)
]

RULES_AR += [
    _rule(
        "ar.structure.negative_parallelism",
        "structure",
        ar_pattern("لا يقتصر") + r"(?:\s*(?:الأمر|الموضوع))?\s*"
        + ar_pattern("على") + r"[^.،؟!\n]{2,80}?" + ar_pattern("بل"),
        Severity.HIGH,
        "اذكر الفكرة مباشرة.",
        "بنية «لا يقتصر على... بل» من أوضح العلامات التركيبية للنص المولّد.",
        language="ar",
        flags=0,
    ),
    _rule(
        "ar.attribution.vague",
        "attribution",
        r"(?:يقول|يرى|يؤكد|يشير|يعتقد)\s+(?:الخبراء|الباحثون|المختصون|"
        r"العلماء|المحللون|الكثيرون|البعض)",
        Severity.HIGH,
        "سمِّ المصدر أو احذف العبارة.",
        "إسناد غامض إلى سلطة بلا مصدر محدد.",
        language="ar",
        flags=0,
    ),
    _rule(
        "ar.assistant.voice",
        "assistant-voice",
        r"بصفتي (?:نموذج|ذكاء اصطناعي)|أنا نموذج ذكاء اصطناعي|"
        r"آمل أن (?:يكون هذا|أكون قد) (?:مفيدا|ساعدت)|"
        r"لا تتردد في (?:السؤال|طرح)",
        Severity.CRITICAL,
        "احذف العبارة.",
        "صيغة مساعد محادثة صريحة.",
        language="ar",
        flags=0,
        replacement="",
    ),
]

ALL_RULES: List[MarkerRule] = RULES_EN + RULES_AR


#: How much each severity tier counts as evidence. A low-severity habit like
#: a single em dash is real but weak; an explicit assistant disclaimer is not.
SEVERITY_EVIDENCE_WEIGHT = {
    Severity.INFO: 0.0,
    Severity.LOW: 0.25,
    Severity.MEDIUM: 1.0,
    Severity.HIGH: 1.5,
    Severity.CRITICAL: 2.5,
}


def rules_for(language: str) -> List[MarkerRule]:
    """Select the rule subset appropriate for *language*."""
    if language == "ar":
        return [r for r in ALL_RULES if r.language in ("ar", "any")]
    if language == "mixed":
        return ALL_RULES
    return [r for r in ALL_RULES if r.language in ("en", "any")]


def scan(
    text: str, language: str = "en", *, rules: Optional[Sequence[MarkerRule]] = None
) -> MarkerReport:
    """Find every AI-writing tell in *text*."""
    report = MarkerReport()
    if not text.strip():
        return report

    active = list(rules) if rules is not None else rules_for(language)
    word_count = max(1, len(words(text)))
    line_starts = compute_line_starts(text)
    per_1k = 1000 / word_count

    hits: List[MarkerHit] = []
    for rule in active:
        matches = list(rule.pattern.finditer(text))
        if not matches:
            continue
        # Rate-gated rules only count when the habit shows up in bulk.
        if rule.min_rate_per_1k and len(matches) * per_1k < rule.min_rate_per_1k:
            continue
        for match in matches:
            line, _column = line_of(text, match.start(), line_starts)
            hits.append(
                MarkerHit(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    matched=match.group().strip(),
                    position=match.start(),
                    line=line,
                    severity=rule.severity,
                    suggestion=rule.suggestion,
                    explanation=rule.explanation,
                )
            )

    hits.sort(key=lambda h: h.position)
    report.hits = hits
    report.category_counts = dict(Counter(h.category for h in hits).most_common())
    report.density_per_1k = len(hits) * per_1k
    report.weighted_density_per_1k = (
        sum(SEVERITY_EVIDENCE_WEIGHT[h.severity] for h in hits) * per_1k
    )
    return report
