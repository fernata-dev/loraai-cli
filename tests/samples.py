"""Sample text used across the test-suite.

Kept in one place so the same corpus exercises the analysis engine, the
cleaner, the humanizer and the CLI, and so a change in expectations is a
change in one file.
"""

from __future__ import annotations

ZWSP = "​"
ZWNJ = "‌"
ZWJ = "‍"
WJ = "⁠"
BOM = "﻿"
RLO = "‮"
PDF = "‬"
RLI = "⁧"
PDI = "⁩"
NBSP = " "

#: Prose with the rhythm and vocabulary typical of generated text.
AI_STYLE = """\
Artificial intelligence is transforming the modern workplace in profound ways. \
It enables organizations to streamline their operations effectively. Moreover, \
it enhances productivity across all departments significantly. Furthermore, it \
reduces operational costs in a meaningful manner. Additionally, it improves \
decision making processes throughout the organization.

Machine learning stands as a critical component of this transformation. It \
allows systems to learn from vast amounts of data. Moreover, it adapts to \
changing market conditions seamlessly. Furthermore, it delivers actionable \
insights consistently to stakeholders. Additionally, it scales effectively \
across the entire enterprise.

Experts say that the landscape of business intelligence is evolving rapidly. \
Companies must delve into these intricate technologies. It is important to \
note that adoption requires careful planning. Organizations should embark on \
this journey with realistic expectations. Ultimately, success depends on \
robust implementation strategies.
"""

#: Prose with the irregular rhythm and informal register of human writing.
HUMAN_STYLE = """\
I got a dog last March. Rescue, mostly terrier, allegedly.

The shelter told me he was calm. He is not calm. On day three he ate a shoe, \
my shoe, the good one, and then looked at me like I had wronged him somehow. \
Maybe I had. I'd left it out.

We walk at six now. I hate six. He does not hate six; he vibrates at six, \
standing by the door with his whole body going, and it's very hard to be \
annoyed at something that happy about a sidewalk.

Anyway. Two years in, I can report the shoe situation has stabilized. Mostly. \
He got a slipper in November but I think we both agreed not to discuss it.
"""

ARABIC_PROSE = """\
اشتريت كلبا في شهر مارس الماضي. من الملجأ، ويقولون إنه من فصيلة التيرير.

قالوا لي إنه هادئ الطبع. هو ليس هادئا على الإطلاق. في اليوم الثالث أكل حذائي، \
الحذاء الجيد تحديدا، ثم نظر إلي وكأنني أنا من أخطأ في حقه. ربما كان محقا، فأنا \
من تركه هناك.

نمشي الآن في السادسة صباحا. أكره السادسة. أما هو فيرتجف من الفرح عندها، يقف \
عند الباب وجسده كله يتحرك، ومن الصعب أن تغضب من كائن سعيد إلى هذا الحد بمجرد \
رؤية الرصيف.
"""

AI_STYLE_ARABIC = """\
في عالم اليوم سريع التطور، يلعب الذكاء الاصطناعي دورا حاسما في تشكيل مستقبل \
الأعمال. علاوة على ذلك، فإنه يتيح للمؤسسات تحسين عملياتها. بالإضافة إلى ذلك، \
فإنه يعزز الإنتاجية بشكل كبير.

تجدر الإشارة إلى أن التعلم الآلي يعد من أهم مكونات هذا التحول. علاوة على ذلك، \
فإنه يتكيف مع الظروف المتغيرة. بالإضافة إلى ذلك، فإنه يقدم رؤى قيمة، مما يسلط \
الضوء على أهميته البالغة.

في الختام، يمثل هذا التحول نقلة نوعية حقيقية. آمل أن يكون هذا مفيدا.
"""

#: Arabic carrying tashkeel, a legitimate ZWNJ, and an RTL mark.
ARABIC_WITH_MARKS = f"مَرْحَبًا بِكَ{ZWNJ}فِي الْعَالَمِ‏ الْعَرَبِيِّ"

PYTHON_SOURCE = '''\
"""A module docstring that reads like ordinary prose about the module."""

import os


# This comment explains why the constant exists in the first place.
LIMIT = 10


def compute(values):
    """Return the total, ignoring anything above the limit."""
    return sum(v for v in values if v <= LIMIT)
'''

MARKDOWN_SOURCE = """\
# Heading

Some prose with a [link](https://example.com/page) and `inline_code()` in it.

```python
x = leverage(1)  # must survive untouched
```

More prose after the fence. See https://example.org/docs for details.
"""
