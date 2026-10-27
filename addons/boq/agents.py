"""Which AIs BOQ (and BOM, which shares this dialog) offers to write the
document and to research standards.

Used to be read straight off prism_terminal.core.agents.CATEGORIES — the
"brains" + "content" categories for the writer picker, "research" for the
research picker. That dict is shared by every add-on (Leads, Content,
Visual, ...), so a change meant only for BOQ's two pickers rippled into all
of them. These two lists are BOQ's own, touched by nothing outside this
folder.

WRITER and RESEARCH below started as today's sets, carried over unchanged by
that split. Since then: Claude was added to RESEARCH (2026-10-20) — it was
already in WRITER, and the owner wants it available to research standards
too. Consensus, WolframAlpha, Semantic Scholar, NotebookLM and LAZYCOOK were
then dropped from RESEARCH (2026-10-20, owner's call: not useful for BOQ's
standards-research job — a general academic/citation/symbolic-math research
tool isn't what checking a building-code or materials standard needs). They
are untouched everywhere else; this only takes them off BOQ's own picker.
ChatGPT was then added to RESEARCH too (2026-10-20). "Groq" was then added
to WRITER (2026-10-20) — unlike every other name here, it is not a browser
agent: addons/boq/dialog.py routes it to addons/boq/workers.py:BoqGroqWorker,
a direct core.router.groq_chat call, the same one-Groq-key-in-Settings path
STEP's Ask already uses. Because it is a plain API call with no file
upload, picking Groq cannot see an attached template or notes file — BOQ's
writer picker blocks that combination with a clear message rather than
silently writing from the figures alone. "Grok" was then added to WRITER
too (2026-10-20) — a real browser-agent registry entry
(prism_terminal/core/agents.py:AGENT_REGISTRY["Grok"]), selectors verified
live against grok.com that same day, the normal AutomationWorker path like
Claude/ChatGPT/Kimi (no BOQ-side special-casing needed, unlike Groq).
"DeepSeek" was then added to WRITER too (2026-10-20), once the owner had
logged into chat.deepseek.com themselves — same real, live-verified
registry entry pattern as Grok, textarea/response/submit selectors
confirmed against the real site. Unlike Grok's, no busy_selector or
regenerate_selector were found (see the long comment on the registry entry
itself for why) — it still works, just falls back to the engine's generic
"text stopped growing" wait instead of watching a dedicated stop button.
"Gemini" was then added to WRITER too (2026-10-20) — a NEW, separate
registry entry (prism_terminal/core/agents.py:AGENT_REGISTRY["Gemini"]),
not the existing "Google Gemini" one, which is permanently tagged
elsewhere in that file as an image-generation tool; reusing it here would
have asked the writer stage to draw a picture of a bill of quantities
instead of writing one. Selectors verified live the same way as Grok and
DeepSeek. This closed out every writer agent from the owner's original
list of seven.

WRITER was pruned to exactly six, 2026-10-25 (item 24a): Claude, Grok,
Kimi 2.6, DeepSeek, Gemini, ChatGPT — the owner's own words, "keep
claude, grok, kimi, deepseek, gemini, chatgpt ONLY". Perplexity,
LAZYCOOK, Jasper, Copy.ai, Writesonic never had a real automation profile
built for BOQ's write-up job in the first place (item 1's own table) and
are dropped for good. Groq-inhouse is ALSO dropped here, confirmed with
the owner directly after item 3 (its whole premise — a second agent
converting Groq's text-only answer into the real file) was superseded by
this same instruction, not assumed either way: see BOQ-CHANGES-TODO.md
item 3's "superseded" note. This replaces item 3's original seven-agent
ordering where the two disagree.

FALLBACK_ORDER (2026-10-21) is item 2's fallback chain: the owner's own
words, "when those errors occur which agent should be used as a fallback
(claude/kimi)". Same shape as addons/step/dialog.py's FALLBACK_ORDER, not
core.agents.alternatives_for() — that resolves candidates by CATEGORY, and
BOQ's stage keys ("format", "recheck", "followup") are not categories, so
it would silently find nothing for any of them. A flat, explicit tuple
sidesteps that entirely. Whichever agent was already tried (the primary
pick, or an earlier fallback) is skipped when the chain is walked — see
addons/boq/dialog.py's _fallback_chain().
"""
from __future__ import annotations

WRITER = ["Claude", "Grok", "Kimi 2.6", "DeepSeek", "Gemini", "ChatGPT"]

RESEARCH = ["Perplexity", "ChatGPT", "Claude"]

FALLBACK_ORDER = ("Claude", "Kimi 2.6")
