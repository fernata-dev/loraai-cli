<div align="center">

```
 ██╗      ██████╗ ██████╗  █████╗      █████╗ ██╗
 ██║     ██╔═══██╗██╔══██╗██╔══██╗    ██╔══██╗██║
 ██║     ██║   ██║██████╔╝███████║    ███████║██║
 ██║     ██║   ██║██╔══██╗██╔══██║    ██╔══██║██║
 ███████╗╚██████╔╝██║  ██║██║  ██║    ██║  ██║██║
 ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝
```

**Text forensics, hidden-Unicode detection, AI-writing analysis and humanization.**

A terminal application with a full TUI and a scriptable CLI.

</div>

---

## What it does

Three jobs, kept deliberately separate because they have very different levels of certainty:

| | What it is | How certain |
|---|---|---|
| **Hidden-character forensics** | Finds zero-width characters, Unicode tag characters, variation-selector byte chains, bidi overrides, homoglyphs and control characters — and **decodes any readable payload hidden inside them**. | **Exact.** These characters are physically in the file. |
| **Writing-style analysis** | Measures sentence rhythm, lexical diversity, repetition, punctuation and ~100 known AI-writing tells, then combines them into a score showing every contributing signal. | **Probabilistic.** Suggestive, never proof. |
| **Humanization** | Rewrites text to read naturally: strips invisible characters, chat-assistant phrasing, inflated vocabulary, formulaic transitions and mechanical rhythm. | **Deterministic** rewriting; optional LLM paraphrase. |

Arabic and English are both first-class throughout.

---

## The honest part: AI watermarks

This is where most tools in this space overclaim, so here is the position plainly.

**"AI watermark" means at least four unrelated things.** loraai reports them separately:

**1. Invisible characters** — zero-width spaces, tag characters, variation selectors.
→ **Fully detectable and removable, with certainty.** They are in the byte stream. `loraai inspect` finds every one; `loraai clean` removes them.

**2. Embedded payloads** — readable data encoded *into* those characters.
→ **Fully decodable.** loraai decodes three schemes: the Unicode Tags block, variation-selector byte chains, and zero-width binary. A successful decode is proof of deliberate embedding, not a heuristic. This is the channel used for invisible prompt injection.

**3. Statistical sampling watermarks** — a bias in *which tokens the model chose* during generation.
→ **Not detectable by any local tool, including this one.**

**4. File provenance (C2PA)** — signed manifests inside media containers.
→ **Detectable when present.** loraai reports the signature; validating the cryptographic signature needs the C2PA toolchain.

### Why #3 cannot be detected locally

Anthropic began marking Claude's text output on **2 August 2026**, to meet EU AI Act Article 50 transparency obligations, applied worldwide rather than only in the EU. Public technical analysis — since confirmed by Anthropic — identifies the mechanism as a variant of **SynthID-Text** (Google DeepMind, *Nature*, 2024): it biases the token **sampling** step through tournament sampling. **Nothing is added to the text.** The signal lives in the sequence of tokens itself, and recovering it requires the generator's secret key and scoring functions. No public detector has been released.

Two consequences follow, and loraai states both in every output format:

> **Deleting zero-width characters does NOT remove a statistical watermark.** They are unrelated mechanisms. Vendors deliberately avoided invisible characters *precisely because* a find-and-replace defeats them.

> **Any tool claiming to detect Anthropic's text watermark locally is guessing.** So loraai does not claim it. It prints `NOT DETECTABLE BY ANY LOCAL ENGINE` and explains why.

Because a sampling watermark lives in the specific token sequence, substantive rewriting degrades it while copy-paste and formatting changes do not. loraai makes no claim about *how much* rewriting suffices, because without a detector that is unmeasurable.

**References**

- [Anthropic — How Claude's text watermarking works](https://www.anthropic.com/news/claude-text-watermark)
- [Anthropic Help — How Claude marks AI-generated content](https://support.claude.com/en/articles/16266773-how-claude-marks-ai-generated-content)
- [SynthID-Text — *Nature*, 2024](https://www.nature.com/articles/s41586-024-08025-4)
- [EU AI Act, Article 50](https://artificialintelligenceact.eu/article/50/)

---

## Install

```bash
git clone https://github.com/procp039-pixel/loraai-cli
cd loraai-cli
./install.sh
```

The installer detects your OS, validates Python **3.10+**, creates an isolated virtual environment, links `loraai` onto your `PATH`, and then **verifies the install actually works** before reporting success.

```bash
./install.sh --dev        # editable install from this checkout
./install.sh --prefix ~/opt/loraai
./install.sh --uninstall
```

Or with pip:

```bash
pip install -e .
```

Both `loraai` and `python -m loraai` work.

---

## Quick start

```bash
loraai                                  # open the TUI
loraai analyze -f article.md            # full analysis of a file
loraai analyze -t "some text here"      # analyse text directly
cat article.md | loraai analyze         # analyse piped input

loraai inspect -f doc.txt               # hidden-character forensics only
loraai clean -f doc.txt --in-place      # strip invisible characters
loraai humanize -f draft.md -I 3        # rewrite to read naturally
loraai report -f doc.md --format html -o report.html
loraai doctor                           # verify the environment
```

Every command that takes text accepts it three ways — `--text`, `--file`, or piped stdin.

---

## The TUI

`loraai` with no arguments opens the interactive interface.

```
┌ ◆ loraai   text forensics · hidden unicode · writing analysis · humanizer ┐
├──────────┬───────────────────────────────────────────────────────────────┤
│ 1 Input  │  LIKELY AI-GENERATED   score 0.84   confidence 0.44           │
│ 2 Dash…  │  human ─────────────────────●──────────── synthetic           │
│ 3 Unicode│  ▲ AI-writing tells            257.353   +1.60                │
│ 4 Markers│  ▲ Sentence-length spread        0.436   +0.37                │
│ 5 Clean  │                                                               │
│ 6 Human… │  ┌ WORDS ┐ ┌ SENTENCES ┐ ┌ HIDDEN CHARS ┐ ┌ AI MARKERS ┐      │
│ 7 Diff   │  │  68   │ │     8     │ │      20      │ │     17     │      │
│ 8 Report │  └───────┘ └───────────┘ └──────────────┘ └────────────┘      │
│ 9 Setti… │                                                               │
├──────────┴───────────────────────────────────────────────────────────────┤
│ ^q Quit  f1 Help  ^r Analyze  ^o Open  ^l Clean  ^h Humanize  ^s Save    │
└──────────────────────────────────────────────────────────────────────────┘
```

**Panes** — Input, Dashboard, Unicode, Markers, Clean, Humanize, Diff, Report, Settings.

**Keys**

| | |
|---|---|
| `1`–`9` | jump to a pane |
| `ctrl+r` | run analysis |
| `ctrl+o` | open a file (browser or typed path) |
| `ctrl+l` / `ctrl+h` | clean / humanize |
| `ctrl+s` / `ctrl+y` | save / copy the active output |
| `ctrl+t` | light ⇄ dark theme |
| `f1` | help |
| `ctrl+q` | quit |

Analysis runs on a worker thread, so the interface never blocks. The TUI works over SSH and needs no terminal-specific behaviour beyond standard ANSI.

---

## Unicode forensics

```bash
loraai inspect -f suspicious.txt
```

Detects and classifies:

- **Zero-width** — U+200B, U+200C, U+200D, U+2060, U+FEFF, soft hyphen, Hangul fillers
- **Unicode tag characters** (U+E0000–U+E007F) — the ASCII-smuggling / invisible prompt-injection channel
- **Variation selectors** — including the supplement (U+E0100–U+E01EF), a documented steganographic byte channel
- **Bidi controls** — isolates and embeddings (usually legitimate) vs. **overrides** (the Trojan Source attack, always critical)
- **Homoglyphs** — 1000+ confusables, cross-script (Cyrillic/Greek/Armenian/Cherokee) and compatibility variants, with mixed-script word detection
- **Invisible math operators**, interlinear annotation, noncharacters, private-use characters
- **Control characters** — including `ESC`, which can rewrite or spoof terminal output
- **Exotic whitespace** — NBSP and the full set of Unicode spaces
- **Normalization drift** — how the text behaves under NFC/NFD/NFKC/NFKD

Every finding carries its code point, Unicode name, category, class, severity, exact line and column, a terminal-safe context snippet, and a recommended action.

### Hidden payload decoding

The headline capability. loraai decodes three schemes:

```
╭─  HIDDEN PAYLOAD DECODED  ───────────────────────────────────────────╮
│   Scheme         Chars   Offset    Decoded content                   │
│   unicode-tags      45   657-702   IGNORE ALL PREVIOUS INSTRUCTIONS  │
│                                                                      │
│  This is a decode, not an inference. Readable data was recovered     │
│  from characters that render as nothing, which means deliberate      │
│  embedding.                                                          │
╰──────────────────────────────────────────────────────────────────────╯
```

A decode either succeeds or it does not — there is no probability involved. Decoders only report a result when the recovered bytes actually read as text, so clean documents and legitimate emoji ZWJ sequences produce nothing.

---

## Cleaning

```bash
loraai clean -f doc.txt --dry-run       # show what would change
loraai clean -f doc.txt -o clean.txt
loraai clean -f doc.txt --in-place      # writes a .bak first
loraai clean -t "text" --quiet-text     # print only the result
```

Three profiles:

| Profile | Behaviour |
|---|---|
| `safe` *(default)* | Removes only what is never legitimate: tag characters, variation-selector supplements, zero-width spaces, word joiners, control characters, bidi overrides, noncharacters. Normalises exotic whitespace to a plain space. **Preserves** Arabic and Indic joiners, bidi isolates, emoji sequences, and every combining mark. |
| `standard` | Adds: joiners outside a script that uses them, deprecated bidi embeddings, NFC normalisation, whitespace tidying. |
| `aggressive` | Adds: all bidi controls, private-use characters, straightened typography, homoglyph repair. Changes visible characters, so it reports semantics as *review* rather than *pass*. |

### The correctness guarantee

After a `safe` clean, **the sequence of letters, digits and combining marks in the output is identical to the input.** This is verified, not assumed — every run reports it:

```
Semantics  PRESERVED
• Letter, digit and combining-mark sequence identical (556 characters) before and after.
• Combining marks preserved (11).
```

Arabic diacritics are combining marks, which is exactly what makes this safe to run unattended on text in a script you cannot read.

---

## Arabic support

Arabic is not an afterthought here:

- **Diacritics (tashkeel) are never removed** by any profile — they are combining marks, protected by the guarantee above.
- **ZWNJ/ZWJ are context-checked per occurrence.** Between Arabic letters they are doing real typographic work and are kept; between Latin letters they carry no meaning and are removed.
- **Marker rules are diacritic- and spelling-tolerant.** `في عالم اليوم` and `في عالمِ اليومِ` both match, and alef/teh-marbuta/alef-maksura variants are treated as equivalent — so one rule covers every real spelling.
- **The humanizer preserves sentence content.** Arabic rewrite rules capture what sits between verb and object rather than discarding it: `يلعب الذكاء الاصطناعي دورا حاسما` becomes `الذكاء الاصطناعي مهم`, not `مهم`.
- **Tokenization, sentence splitting and reading-speed** all branch on script.

---

## Humanization

```bash
loraai humanize -f draft.md -I 3 --diff
loraai humanize -t "text" -s academic --quiet-text
```

Removes, offline and deterministically:

- chat-assistant phrasing (`Great question!`, `As an AI language model`, `I hope this helps!`)
- inflated vocabulary (`delve` → `look at`, `leverage` → `use`, `meticulous` → `careful`, ~90 more)
- formulaic scaffolding (`Moreover,`, `In conclusion,`, `It is important to note that`)
- trailing participial pseudo-analysis (`, highlighting the importance of…`)
- vague attribution (`Experts say that…`)
- stacked hedging, em-dash overuse
- mechanical rhythm — over-long sentences are split at natural joins to restore variation

**Styles** `natural` · `concise` · `professional` · `academic` · `conversational`
**Intensity** `1` light · `2` moderate · `3` thorough

### What is preserved

Code fences, inline code, URLs, emails, markdown links, images and citations come through **byte-identical**. A safety net flags any rewrite that drops more than a third of the words, so an over-matching rule can never quietly gut a document. The original is always retained and a diff is always available.

### Optional LLM paraphrase

Rule-based rewriting cannot genuinely paraphrase. For that, point it at a model:

```bash
export ANTHROPIC_API_KEY=...
loraai humanize -f draft.md --provider anthropic
```

Providers: `anthropic`, `openai`, `openrouter`, `ollama` (local). **API keys are read from environment variables and are never written to the config file.** The text being rewritten is delivered inside a delimited block with an explicit instruction to treat its contents as data — text being humanized is exactly the kind of text that might carry an injected instruction, often invisibly, which is why the cleaning pass runs first.

> The humanizer is a writing-quality tool. It reduces measurable style markers, which is real and verifiable. It is **not** a detector-evasion tool, and it does not affect statistical watermarking.

---

## Analysis methodology

The synthetic-text score is an **additive-evidence model**, not a trained classifier. Each measurement contributes a log-odds weight; the sum is squashed through a logistic function. This means **every point of the score traces to a named signal with its raw value attached** — you can see exactly why the number moved and discount a weight you disagree with.

Signals include sentence-length **burstiness** and coefficient of variation, severity-weighted AI-marker density, discourse-marker density, repeated sentence openers, paragraph uniformity, contraction rate, MATTR (length-stable lexical diversity), and 4-gram repetition.

**Deliberate limits, all enforced in code:**

- **Style only.** Invisible characters are evidence about *processing*, not authorship — a human can paste a zero-width space and a model can emit clean ASCII — so they are reported separately and never silently inflate the score.
- **Short text is not assessable.** Below 50 words the verdict is clamped to `INCONCLUSIVE` regardless of what the signals say.
- **No claim of proof.** The strongest label available is `LIKELY`, and the caveats travel with the result into every output format.

```
This is a statistical reading of writing style, not proof of authorship.
Weights are hand-calibrated heuristics, not parameters fitted to a labelled corpus.
Non-native, heavily edited, formal and templated human writing all score higher here.
Text written by a model and then revised by a person can score low.
```

A trained classifier would be more accurate. `SyntheticDetector` is the extension point — a model-based detector drops in without touching the CLI, TUI or report writers.

---

## Reports

```bash
loraai report -f doc.md --format json -o report.json
loraai report -f doc.md --format html -o report.html
loraai report -f doc.md --format markdown
loraai report --schema
```

**JSON** is versioned (`schema_version`) and additive — new keys may appear, existing keys keep their meaning.

```json
{
  "schema_version": "1.0",
  "loraai_version": "1.0.0",
  "source": {}, "statistics": {}, "style": {},
  "unicode": {}, "ai_markers": {},
  "synthetic_signal": {}, "provenance_marking": {},
  "warnings": []
}
```

**HTML** is fully self-contained — no fonts, scripts, images or stylesheets are fetched. It respects `prefers-color-scheme` and opens correctly on an air-gapped machine.

Anything resembling a credential is redacted before a report is written, so scanning a config file does not produce a report that leaks the key it found.

---

## Configuration

```bash
loraai config path      # where it lives
loraai config init      # write a commented default
loraai config show      # the resolved configuration
```

`~/.config/loraai/config.toml`, with sections for `general`, `analysis`, `clean`, `humanize` and `tui`. Layered in increasing precedence: built-in defaults → config file → environment → command-line flags. Every layer is optional; the tool works with no configuration at all.

**API keys are never stored in the config file** — only the *name* of the environment variable to read. A loraai config file is safe to commit.

---

## Security

Input is treated as hostile throughout:

- **ANSI escape sequences are stripped** before anything reaches the terminal. A file cannot reposition your cursor, clear your screen, or forge a line that looks like loraai's own verdict.
- **Bidi overrides are rendered visible** as `<U+202E>` rather than being allowed to reorder the display — the Trojan Source problem is exactly what this tool exists to find.
- **Path, size and encoding are validated** before any read; binary files, oversized inputs and undecodable data are rejected with clear messages.
- **Secrets are redacted** from all report output.
- **Prompt injection is contained** when an LLM provider is used: the text is delimited and explicitly framed as data.
- **Destructive operations are explicit** — `--in-place` writes a `.bak` first, and `--dry-run` shows every change before anything is written.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Generic error |
| `2` | Input error — missing file, binary data, no input, contradictory input |
| `3` | Configuration error |
| `4` | Provider error — unconfigured or unreachable |
| `5` | `--fail-on` severity threshold reached (for CI) |
| `130` | Interrupted |

```bash
# Fail a CI job if any file carries a high-severity hidden character
loraai inspect -f "$FILE" --fail-on high
```

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                       # 360+ tests
loraai doctor                # includes a real engine self-test
```

`loraai doctor` does not merely check that imports resolved — it runs the engine against a sample with four known-planted marker classes and a known payload, and verifies all of them come back and that cleaning preserves semantics.

**Layout**

```
loraai/
├── analysis/      tokenizer, statistics, stylometry, markers,
│                  unicode_forensics, payload, synthetic, provenance, pipeline
├── cleaning/      profile-driven cleaner with semantic verification
├── humanize/      offline rule engine + optional LLM providers
├── diffing/       line, word and character comparison
├── reports/       json, html, markdown writers
├── cli/           click command group, rich rendering, doctor
├── tui/           textual application, widgets, screens, stylesheet
├── unicode_data/  invisible-character catalog, confusables, scripts
├── textio.py      input, encoding detection, prose extraction
├── sanitize.py    terminal-safe rendering, secret redaction
├── models.py      shared result types
└── config.py      layered configuration
```

The analysis engine has no dependency on the CLI or TUI, so it is usable directly:

```python
from loraai import textio
from loraai.analysis import analyze

result = analyze(textio.from_file("article.md"))
print(result.synthetic.verdict.label)
print(len(result.unicode.payloads), "hidden payload(s)")
```

---

## Known limitations

- **Statistical watermarks are not detectable.** By design, and by the physics of the mechanism. See above.
- **The synthetic score is heuristic**, not trained. Formal, templated and non-native human writing scores higher. Treat it as a prompt to look closer, never as a verdict about a person.
- **Arabic thresholds are less validated than English ones.** The Arabic marker rules cover formal-register phrasing that also appears in ordinary journalism.
- **Language coverage** for style analysis is English and Arabic. Unicode forensics is language-independent and works on any script.
- **Offline humanization cannot paraphrase.** It removes stylistic tells; genuine restructuring needs a provider.
- **BOM-less UTF-16 detection** relies on trial decoding. Exotic legacy encodings beyond CP1256 are not attempted.

---

## Roadmap

- A trained classifier behind the existing `SyntheticDetector` interface
- More languages for style analysis (French, Spanish, German)
- Batch/recursive directory scanning with a summary report
- Pre-commit hook and GitHub Action for hidden-character CI gating
- C2PA signature *validation*, not just detection

---

<div align="dir=rtl">

## ملخص بالعربية

**loraai** أداة سطر أوامر لتحليل النصوص وكشف العلامات المخفية داخلها.

**ثلاث وظائف، ودرجات يقين مختلفة:**

1. **كشف الأحرف المخفية — يقين تام.** تجد الأداة أحرف العرض الصفري (zero-width)، وأحرف Unicode Tags، ومحددات التنويع، وأحرف قلب الاتجاه، والأحرف المتشابهة بصريا. وتفك تشفير أي بيانات مخبأة داخلها فعليا — وهذا ليس تخمينا، بل فك تشفير حقيقي.

2. **تحليل أسلوب الكتابة — احتمالي.** تقيس الأداة إيقاع الجمل، وتنوع المفردات، والتكرار، وحوالي 100 علامة معروفة لأسلوب الذكاء الاصطناعي، ثم تعرض النتيجة مع كل إشارة ساهمت فيها. **هذا ليس دليلا على من كتب النص.**

3. **التحويل إلى نص بشري.** تزيل الأداة الأحرف المخفية، وعبارات المساعد الآلي، والمفردات المتضخمة، وأدوات الربط النمطية، والإيقاع الآلي للجمل.

**بخصوص العلامة المائية التي وضعتها Anthropic:**

بدأت الشركة في 2 أغسطس 2026 بوضع علامة على مخرجات Claude النصية، امتثالا للمادة 50 من قانون الذكاء الاصطناعي الأوروبي. لكن **الآلية ليست أحرفا مخفية** — بل علامة إحصائية في اختيار الكلمات أثناء التوليد (على غرار SynthID-Text). لا يُضاف أي حرف إلى النص.

النتيجة المهمة:

> **حذف الأحرف المخفية لا يزيل العلامة الإحصائية.** الآليتان مختلفتان تماما. وأي أداة تدّعي كشف العلامة الإحصائية محليا فهي تخمّن. لذلك **لا تدّعي loraai ذلك**، بل تكتب صراحة أن كشفها محليا غير ممكن، وتشرح السبب.

**دعم العربية كامل:** التشكيل لا يُحذف أبدا، وعلامات الوصل تُفحص حسب السياق (تُحفظ بين الحروف العربية وتُزال بين الحروف اللاتينية)، وقواعد الكشف تتعامل مع النص المشكول وغير المشكول، ومع اختلافات كتابة الألف والتاء المربوطة.

</div>

---

## License

MIT — see [LICENSE](LICENSE).
