# BOQ add-on — changes to make

Noted down 2026-10-20, from the owner, not yet implemented. Read this file
before any BOQ work and check off / update it as items land — do not delete
an item just because related code was touched; only check it off once the
exact behaviour below is true in `addons/boq/`.

## 1. Writer and research agent lists

**Writer (write-up) agents must include:** Groq-inhouse, Claude, Gemini,
ChatGPT, Grok, Kimi, DeepSeek.

**Research agents must include:** Perplexity, ChatGPT, Claude.

- [x] Module separated (2026-10-20): BOQ's writer/research picker pools now
      live in `addons/boq/agents.py` (`WRITER`, `RESEARCH`), not the engine's
      shared `prism_terminal/core/agents.py:CATEGORIES`. `addons/boq/dialog.py`
      reads only from that file now, so editing BOQ's lists can no longer
      change what Leads/Content/Visual offer. This was a pure move — list
      content is unchanged, both BOQ test files + BOQ pricing tests pass
      (55/55). The actual content change below is still **not done**.
- [x] Content done (2026-10-21) — see the three jobs below, all shipped.

Checked each requested writer agent against what the engine can actually
drive (`prism_terminal/core/agents.py`, `core/router.py`, `core/automation.py`):

| Agent | Exists today? | What adding it means |
|---|---|---|
| Claude | yes (browser automation) | add to `addons/boq/agents.py:WRITER` |
| ChatGPT | yes (browser automation) | already there |
| Kimi 2.6 | yes (browser automation) | already there |
| Google Gemini | yes, but only wired for *image* output (`visual` category) | needs checking/building a text-writing automation profile for it, not just a list add |
| Groq-inhouse | not an "agent" at all — Groq is called directly via `core/router.py:groq_chat`, API-key based, no browser, the same path STEP's Ask/Edit uses (`prism_terminal/core/stepfile.py:ask_prompt`) | needs a new BOQ prompt + a new code path in `addons/boq/dialog.py`/`workers.py` that calls `router.groq_chat` directly, parallel to STEP's — not a picker-list entry |
| Grok | no integration anywhere in the repo | a whole new browser-automation profile in `core/automation.py` (site quirks, selectors, login) from scratch |
| DeepSeek | no integration anywhere in the repo | same as Grok — new automation profile from scratch |

So this item is really three different-sized jobs:
  1. Trivial — add Claude to `WRITER` (ChatGPT, Kimi 2.6 already present);
     add ChatGPT + Claude to `RESEARCH` (Perplexity already present).
     - [x] **Done (2026-10-20).** `RESEARCH` is now
           `["Perplexity", "ChatGPT", "Claude"]` — Claude added, then
           Consensus/WolframAlpha/Semantic Scholar/NotebookLM/LAZYCOOK
           dropped (owner's call: not useful for a standards-research job),
           then ChatGPT added. `WRITER` already had Claude + ChatGPT, so it
           was untouched. 55/55 BOQ+BOM tests pass throughout.
  2. Medium — give Gemini a text-writing automation profile, not just image.
  3. Large — build real Grok and DeepSeek automation from nothing, and wire
     Groq in-house as its own direct-API code path for BOQ.
     - [x] **Groq in-house done (2026-10-20).** Owner's call: build the
           backend before adding the name, not the other way round. Added
           `addons/boq/workers.py:BoqGroqWorker` — a direct
           `core.router.groq_chat` call (the same one-key path STEP's Ask
           already uses), not browser automation. `"Groq"` is now in
           `addons/boq/agents.py:WRITER`. Because it has no file upload,
           `addons/boq/dialog.py` refuses rather than silently drops a file
           in every path that could reach it with one: no API key configured
           (checked at submit), an attached template/notes file (checked at
           submit), a priced reference CSV (checked at write time, since
           pricing can be filled in after submit), "Verify and remake"
           (always sends the drawing file — refused before the consent
           popup even opens, both from the Recheck button and from the
           follow-up window's quick action), and a typed follow-up with its
           own attached file (the authoritative check, inside
           `_send_followup` itself). 7 new tests in
           `tests/test_boq_dialog.py::GroqInHouseIsADirectCallNotABrowserAgent`,
           62/62 BOQ+BOM tests pass.
     - [x] **Grok done (2026-10-20).** A real
           `prism_terminal/core/agents.py:AGENT_REGISTRY["Grok"]` entry —
           an actual browser agent, not an API shortcut like Groq, so it
           needs no special-casing in `addons/boq/dialog.py` at all; it
           goes through the ordinary `AutomationWorker` path exactly like
           Claude/ChatGPT/Kimi. Selectors (`textarea_selector`,
           `response_selector`, `submit_selector`, `busy_selector`,
           `regenerate_selector`) were verified LIVE against grok.com,
           not guessed — the owner's own account, via Claude in Chrome,
           both a quick exchange and a longer one to catch the
           mid-generation "Stop model response" state. One live finding:
           a one-time, non-dismissible age-confirmation modal blocked the
           very first message on this account — the owner supplied their
           birth year in chat and gave explicit OK for it to be entered;
           it does not reappear afterwards and is not part of the chat DOM
           automation touches. "Grok" added to
           `addons/boq/agents.py:WRITER`. 3 new tests in
           `tests/test_boq_dialog.py::GrokIsARealRegisteredBrowserAgent`.
           282/282 BOQ+BOM+STEP+registry tests pass.
     - [x] **DeepSeek done (2026-10-20).** The owner logged into
           chat.deepseek.com themselves, then selectors were verified LIVE
           the same way as Grok's. This app has no `data-testid` attributes
           at all (unlike grok.com) — its own design-system class names
           (`ds-button`, `ds-markdown`, …) are what the three selectors key
           off instead. One real trap caught live: a SECOND, unrelated
           element also matches `.ds-button--circle` once a conversation is
           tall enough to show a floating "scroll to newest message"
           control above the composer — `submit_selector` explicitly
           excludes it (`:not(.ds-button--floating)`), or a long
           conversation's next message would click "scroll" instead of
           sending. Two fields were deliberately left UNSET rather than
           guessed: `busy_selector` (the send button reads
           `ds-button--disabled` whether the box is merely empty or a reply
           is actively streaming — checked repeatedly, including with "Deep
           thinking" on to widen the window — no class or icon distinguishes
           the two) and `regenerate_selector` (no distinct control found
           near a finished answer). Neither is required — `_GENERIC` has no
           default for either, so DeepSeek falls back to the engine's own
           generic "text stopped growing" wait, same as Perplexity and
           Kimi 2.6 already do. "DeepSeek" added to
           `addons/boq/agents.py:WRITER`. 3 new tests in
           `tests/test_boq_dialog.py::DeepSeekIsARealRegisteredBrowserAgent`.
           288/288 BOQ+BOM+STEP+registry tests pass.

**Gemini done (2026-10-21).** A SEPARATE `AGENT_REGISTRY["Gemini"]` text
entry, not a change to the existing `"Google Gemini"` image-maker one —
`core.agents._MAKES` permanently tags `"Google Gemini"` as an image tool
at module load, so reusing it for text would have made every BOQ write-up
run look like an image request. Selectors verified live the same way as
Grok/DeepSeek; confirmed directly that `is_maker()` is `False` for the
new "Gemini" entry and still `True` for "Google Gemini". "Gemini" added
to `addons/boq/agents.py:WRITER`.

All seven writer agents from the owner's original 2026-10-20 list are
now in `WRITER`, item 1 is fully done.

Housekeeping note: live-verifying Grok and DeepSeek left a few real test
conversations in the owner's own chat history on both sites ("What is
2+2?", a suspension-bridge question, a train-meeting word problem, etc.) —
harmless, but real clutter on a real account; mention to the owner in case
they want them deleted.

## 2. Follow-up flow: per-stage agent control + fallbacks

Wanted: a follow-up window like Prism core's, showing the work as a flow —
and letting the owner control, per run:
  - which agent verifies/remakes the drawing,
  - which agent handles a plain follow-up,
  - the fallback chain when the chosen agent can't answer (e.g. ChatGPT's
    memory limit causing an error mid-job) — specifically Claude and Kimi as
    fallback candidates.

- [x] **Done (2026-10-21).** The owner showed two screenshots of Prism
      core's own Run screen (`widgets/output_panel.py`'s `RunHeader` +
      `StageCard`, wired in `main_window.py`) and asked for the same look
      and the same Skip/Use fallback/Stop controls on BOQ's follow-up and
      "Verify and remake" calls — a live window, not just an error popup.

What shipped:
  - **`addons/boq/run_dialog.py`** (new) — `BoqRunDialog`, a small modal
    reusing `StageCard` directly (same status badges, timeline dot, live
    elapsed clock the real Run screen uses — not a reimplementation) for
    the one job BOQ is ever doing, with Skip / Use fallback / Stop and a
    Close button that only unlocks once the run is actually over.
  - **`addons/boq/agents.py`**: `FALLBACK_ORDER = ("Claude", "Kimi 2.6")`
    — the owner's own words, "when those errors occur which agent should
    be used as a fallback (claude/kimi)". Same flat-tuple shape as
    `addons/step/dialog.py`'s own `FALLBACK_ORDER`, deliberately NOT
    `core.agents.alternatives_for()` — that resolves by CATEGORY, and
    BOQ's stage keys (`"format"`, `"recheck"`, `"followup"`) aren't
    categories, so it would silently find nothing for any of them. Caught
    by re-reading `AGENT_REGISTRY`'s `_fallback_signal`/`alternatives_for`
    path before building anything on top of it.
  - **`addons/boq/dialog.py`**: `_send_followup`'s browser-agent branch
    (Groq's own direct-API branch is untouched, unaffected, no live
    window — there's no tab to hand to a fallback tool) now goes through
    `_start_followup_run`, which builds the chain (chosen agent first,
    then whichever of `FALLBACK_ORDER` it isn't already), opens the
    dialog, and reuses the SAME `StageCard` across every attempt — the
    same way a real failover in the core Run screen swaps a card's agent
    in place rather than stacking a new one. A failure auto-advances to
    the next agent; the dialog's buttons map to: Skip → the real, already
    -working `worker.skip()` (generic, not stage-name-dependent — verified
    by reading `workers.py`'s `AutomationWorker.run()`, which already
    wires `should_stop`/`skip_signal` into every `automation.run()` call
    regardless of `custom_stages`); Stop → the real `worker.skip()`'s
    sibling `worker.stop()`; Use fallback → BOQ's own stop-current
    -then-start-next (NOT `worker.use_fallback()`, which hits the same
    `alternatives_for` gap as the automatic path would have). A token
    counter guards against a stopped worker's late signal overwriting a
    newer attempt's result.
  - **Scope, stated plainly**: this covers "Verify and remake" and
    follow-ups, matching the owner's own wording ("while the followup,
    there should be window..."). The very first "Write" call
    (`_write()`) is untouched — no live window, no fallback chain — a
    deliberate boundary, not an oversight.
  - **Agent choice**: the owner's complaint was "the first agent that i
    select is the only one that gets the original dwg file to verify the
    readings, i dont have the freedom to choose" — solved by the fallback
    chain and the "Use fallback" button rather than a second persistent
    picker cluttering the main screen for an action used occasionally. No
    separate "Verify with" / "Follow up with" dropdowns were added.
  - **`widgets/agents_panel.py`**: three new `STAGE_COPY` entries
    (`"format"`, `"recheck"`, `"followup"`) so `StageCard` shows readable
    titles/icons for BOQ's stages instead of the generic grid-icon
    fallback — the same shared, cross-add-on dict `"analysis"` (not a
    pipeline category either) was already added to, so this follows an
    established pattern rather than starting a new one.
  - **A real, caught-live bug**: the first implementation called
    `BoqRunDialog.exec()` unconditionally from `_send_followup`, which
    hung the three EXISTING follow-up tests solid — their mocked worker
    never fires a signal, so the real modal never got a reason to close.
    Killed the hung run, fixed it the way `FollowupDialog`'s own tests
    already do: every test that reaches this path now patches
    `addons.boq.run_dialog.BoqRunDialog` with a fake whose `.exec()`
    returns immediately.
  - Tests: 9 in `tests/test_boq_dialog.py::TheFollowUpFlowHasALiveWindow
    AndAFallbackChain` (chain construction, automatic retry, chain
    exhaustion, success, skip, stop, manual fallback, the stale-signal
    guard) + 9 in the new `tests/test_boq_run_dialog.py` (the real,
    unmocked `BoqRunDialog` itself — construction, every state
    transition, the close-mid-run-asks-to-stop behaviour). 306/306 across
    BOQ+BOM+STEP+registry+the new file, re-run clean after the hang fix.

Both items from the owner's 2026-10-20 list are now done.

## 3. Writer list, in order — and Groq-inhouse's real job is stage one of two

Noted 2026-10-21, from the owner, not yet implemented. **Revised 2026-10-21**
— the owner caught that DeepSeek was accidentally dropped from the first
write-up, and redefined what "Groq-inhouse must handle files" actually
means once told it's not realistic (see below).

**Writer (write-up) agents must be, in this exact order:**
Groq-inhouse, Claude, ChatGPT, Gemini, Kimi, Grok, DeepSeek.
(DeepSeek's exact position wasn't specified beyond "include it" — appended
at the end here; confirm with the owner if it belongs somewhere else in the
order.)

This REPLACES the current `addons/boq/agents.py:WRITER` list, which today is
`["Perplexity", "ChatGPT", "Claude", "Groq", "Grok", "DeepSeek", "Gemini",
"LAZYCOOK", "Jasper", "Copy.ai", "Kimi 2.6", "Writesonic"]`. To match, this
item drops Perplexity, LAZYCOOK, Jasper, Copy.ai, Writesonic from `WRITER`
entirely, and reorders the seven survivors to the exact sequence above (the
combo box is built straight from the list, so order in the file is order on
screen).

**Groq-inhouse's job, redefined — a two-stage pipeline, not file-handling:**
the owner accepted that Groq-inhouse can't realistically read a drawing file
or a sample-format `.docx` (no file input on its API path). Revised ask:
Groq-inhouse makes a **text-only BOQ from the measured figures** — nothing
more — and that text is then handed to a SECOND, user-chosen agent (any of
ChatGPT, Claude, Gemini, Kimi, DeepSeek, Grok) whose job is to turn that text
into the real output file, in whichever format the user picked (`.docx` or
`.csv`).

- [x] **Stage one may already work as-is, for the plain case.** Checked
      `addons/boq/dialog.py`: when Groq is chosen and there is no attached
      template/notes file, `_write()` already runs `BoqGroqWorker` on the
      measured-figures text and gets a text answer back — item 1's own
      refusal only fires when a FILE is attached, not for the ordinary
      figures-only case. So "Groq-inhouse produces a text BOQ from the
      measurements" is likely already true today; needs a real run to
      confirm rather than assuming.
- [x] **Superseded, 2026-10-25 — not building stage two.** Item 24a's
      owner-confirmed writer list ("Claude, Grok, Kimi, DeepSeek, Gemini,
      ChatGPT ONLY") drops Groq-inhouse from the writer picker entirely.
      With no Groq-inhouse "stage one" output left to convert, this
      item's whole premise is gone — asked the owner directly rather than
      building a pipeline for an agent about to be removed; confirmed
      drop it. No code written for this item.

## 4. A follow-up's new file never replaces the old one shown to the owner

Noted 2026-10-21, from the owner, not yet implemented. Reported with two
screenshots. **Corrected 2026-10-21** — the first write-up of this item
mischaracterized it as "produced a `.docx` instead of a `.csv`"; that is
NOT what was reported. The actual report:

**What happened:** the first run produced `boq_quantities_1792531109.csv`,
shown in the follow-up window's "What Prism produced" card (1 item, the
`.csv`). The owner then sent a follow-up instruction asking for a `.docx`
file instead. It ran, invoked Claude, and (per the owner) completed —
**a new file WAS generated by the follow-up run** — but the follow-up
window, reopened afterward, **still fetches and shows the old
`boq_quantities_1792531109.csv`**, never surfacing the new file the
follow-up just made.

- [x] **Done (2026-10-21).** Root cause, once traced: nothing in
      `addons/boq/dialog.py` ever tracked an AI-produced file at all — not
      a bug specific to follow-ups. `_offer_followup()`'s artifacts list
      was hardcoded to `self.csv_path`, the LOCALLY measured quantities
      CSV made once before any AI runs, because that was the only file
      path the dialog had ever held onto. A new `self._deliverable_path`
      is now set from `AutomationWorker(files_out=...)` — a caller-owned
      list the engine already appends every harvested file to (the same
      mechanism `addons/step/dialog.py:_on_drafted` uses) — wired into the
      write-up, recheck and follow-up calls alike. Whatever comes back is
      copied into the run's own Artifacts folder via `CB.config.
      save_artifact` and shown FIRST in the follow-up window, ahead of
      (not instead of) the measured CSV. 2 new tests.

## 5. "Verify and remake" produces no file at all, in any format

Noted 2026-10-21, from the owner. **Done (2026-10-21).**

**What happened:** pressing "Verify and remake" and letting it run produced
no output file whatsoever — not a `.csv`, not a `.docx`, nothing.

**Also requested:** a dedicated control to choose the output file format
the owner wants.

What shipped:
  - A **"File format" picker** next to "Write with" — Let the tool decide
    (default) / Word (.docx) / CSV / PDF.
  - Root cause: `VERIFY_PROMPT` only ever asked the agent to check figures
    against the drawing, never to produce a file — so there was never
    anything for the engine's own file-harvesting to find, format picker
    or not. Picking a format now appends one line to the prompt AND
    promotes the stage to a `file`-kind step in the engine's own contract
    system (`prism_terminal/core/contract.py`'s `_WRITING_STAGES`, which
    `"recheck"`/`"followup"` were missing from entirely) — that system
    already re-asks once for the file and, worst case, writes the
    document itself out of the tool's own text, the same guarantee a
    fresh write-up already had. Groq (in-house) is excluded: no browser
    page, so no file to produce.
  - 3 new tests (default adds nothing to the prompt, a chosen format adds
    the request line, Groq never receives it).

## 6. "Verify and remake"'s progress window underestimates how long it takes

Noted 2026-10-21, from the owner. **Done (2026-10-21).**

**What happened:** the live progress window for "Verify and remake" (the
`BoqRunDialog` from item 2) read as if the step was short, but a real run
— the agent has to read the drawing itself — can take on the order of 20
minutes to come back with an answer, with nothing on screen saying that
was normal.

What shipped:
  - `AutomationWorker` gains a raw `min_wait` passthrough, independent of
    the existing `followup=True` (which already raises the ceiling to
    `automation.FOLLOWUP_MIN_WAIT`, 8 minutes, for any follow-up) — a
    caller that knows ONE particular stage is heavier can raise the floor
    further without changing what `followup=True` otherwise does. BOQ's
    "recheck" now gets a 20-minute floor; a plain "followup" keeps the
    8-minute one.
  - Both recheck and follow-up now pass `followup=True` where neither did
    before — they previously got the SAME short, generic wait ceiling as
    any other stage.
  - `BoqRunDialog` takes an optional `note`, shown on the card up front:
    "{agent} is reading the drawing itself, not just answering from
    memory — this can take up to 20 minutes." for recheck specifically.
  - 4 new tests (the wait floor for each stage, the note for each stage).

Items 4-6 share one more fix, needed for the format picker and the real
wait ceiling to reach the engine at all: `AutomationWorker`'s `query`
argument for recheck/followup was a short internal label
(`"recheck — <doc>"`), never the actual prompt text — so the engine's own
`wants_file()` scan (which decides whether a stage owes a file) could
never see a chosen format or the words "make it a docx" even typed
directly into a follow-up. The real prompt is passed as `query` now.

Tests: 19 new across `tests/test_boq_dialog.py` (14) and the earlier
`tests/test_boq_run_dialog.py` (unchanged this round). Full BOQ+BOM+STEP+
run_dialog suite green, plus a sweep of Gerber/Reel/Motion/email/
worker_mandate since `workers.py` and `core/contract.py` are shared by
every add-on, not just BOQ.

All six items from the owner's 2026-10-20/21 list are now done, except
item 3's "stage two" (handing Groq-inhouse's text answer to a second,
user-chosen agent for file conversion) — still open, tracked above.

## 7. "Verify and remake" opened a fresh window instead of continuing the one already on screen

Noted 2026-10-22, from the owner. **Done (2026-10-22).**

**What happened:** after a BOQ is written (without the drawing ever
touching the AI — the engine is handed the measured figures only), the
owner's usual move is "Verify and remake": send the DWG file itself so an
agent can check the measured quantities against it. Instead of carrying
on in the live-progress window the ordinary follow-up (or the write-up
itself) was already shown in, pressing it — or running a plain
follow-up, then "Verify and remake" straight after — popped a brand new
`BoqRunDialog` window each time. The owner wanted this to work the way
Prism core's own Run screen does: ONE window for the session, carried
from job to job, not a fresh one per click — the two genuinely different
DWG-sending moments ("Recheck with drawing," before the main pipeline
even runs, versus "Verify and remake" after a BOQ already exists) were
never the issue; the window itself was the thing resetting.

What shipped:
  - **`addons/boq/run_dialog.py`**: `BoqRunDialog.restart(title, stage,
    agent, note="")` — undoes a prior `finish_*()` lock, swaps in a fresh
    `StageCard` for the new stage/agent (a stale "done"/"error" card
    redrawn as "running" would still carry the old job's timeline dot and
    elapsed clock, so a new one replaces it via the stored layout
    reference, `self._card_row`, rather than reusing the old widget), and
    re-enables Skip / Use fallback / Stop while relocking Close.
  - **`addons/boq/dialog.py`**: `self._fu_dialog` is now initialised once
    in `__init__` (`None`) and kept for the life of the dialog.
    `_start_followup_run` builds a `BoqRunDialog` only the FIRST time;
    every later call — a second follow-up, "Verify and remake" after one,
    a follow-up after a recheck, any order — calls `restart()` on the
    SAME instance instead.
  - **`.exec()` → `.show()` + `.raise_()` + `.activateWindow()`**: the old
    code's modal `.exec()` enters its own blocking event loop and only
    returns once the window closes, so the same instance could never be
    reused for a later job without destroying it first. `setModal(True)`
    (already set in `__init__`) keeps the BOQ dialog from being clicked
    underneath it either way — this is the same non-blocking pattern
    `main_window.py` uses for its one, app-lifetime `OutputPanel`.
  - Tests: 3 in `tests/test_boq_dialog.py::TheLiveWindowIsReusedAcrossFollowUps`
    (verify-and-remake after a follow-up reuses the window and not a
    second one; a third call restarts again rather than building a
    third; the window is shown, never exec()'d, so no test can hang) + 4
    in `tests/test_boq_run_dialog.py::RestartReusesTheWindowForTheNextJob`
    (restart undoes a lock, swaps the card, drops the old note, and can
    finish again afterwards) + `_FakeRunDialog` in `test_boq_dialog.py`
    gained `restart()`/`show()`/`raise_()`/`activateWindow()` and a
    `construct_calls` counter so a test can tell a reuse from a rebuild.
    81/81 across both BOQ dialog test files, full suite unaffected
    (nothing outside BOQ touches `BoqRunDialog`).

**CORRECTION, 2026-10-22, same day — the fix above was real but incomplete,
and marking it "Done" without catching that was wrong.** The owner tested
it: "Make with drawing," then a follow-up ("generate a docx of this") on
top of it still opened a fresh browser tab/chat — and the same thing
happened following up after an ordinary "Make my BOQ". What shipped above
fixed Prism's OWN small progress popup (`BoqRunDialog`) — a real, correct
fix, and still needed — but it is not what "opens a new tab" meant. The
actual new tab is the BROWSER's own tab for the writing agent's chat
(Claude.ai / ChatGPT, etc.), controlled entirely separately, inside
`prism_terminal/core/automation.py` — a layer the first pass of this item
never looked at. Caught only because the owner tested the real app end to
end rather than trusting the earlier write-up.

**What was actually wrong:** the engine already has a working mechanism
for exactly this — `resume_urls`, a `{stage: chat_url}` dict passed into
`AutomationWorker`/`automation.run()` that tells it to navigate straight
back to an existing conversation instead of opening a fresh tab
(`core/automation.py`'s `_open_agent_page` checks it before deciding
whether to open a new tab at all). `addons/step/dialog.py`'s own
follow-up handler already uses it correctly. **`addons/boq/dialog.py`
simply never called it, on any follow-up, ever** — every `_send_followup`
call built a brand-new `custom_stages` job with no `resume_urls`, so the
engine had no way to know a chat already existed to go back to, and
always opened a new one. BOQ already tracked everything needed to fix
this (`self._stage_agents_map`, `self._links`) — the pieces existed, nobody
had wired them to this specific parameter.

**The actual fix:**
  - **`addons/boq/dialog.py`**: two new fields, `self._last_agent` /
    `self._last_link` — "who answered most recently, and that exact
    chat's own URL" — updated at the end of EVERY completed stage
    (`_on_written` for the first write-up, `_on_followed_up` for every
    follow-up/recheck after it, so a third follow-up resumes the SECOND
    one's chat, not reaches back to the very first).
  - **`_fu_start_next`** now builds `resume_urls = {self._fu_stage:
    self._last_link} if tool == self._last_agent and self._last_link else
    None` before constructing the `AutomationWorker`, and passes it
    through. Guarded on the SAME agent answering again — switching
    agents (or falling back to a different one mid-chain after a
    failure) correctly resumes nothing, because there is no chat of that
    OTHER tool's to go back to; it falls through to the existing
    full-context prompt instead, exactly as before. The same check
    `addons/step/dialog.py`'s `_on_answer_followup` already makes, not a
    new pattern invented for BOQ.
  - Groq's own branch in `_send_followup` is untouched and unaffected —
    it has no browser page at all, so `self._last_link` stays empty
    whenever Groq last answered, and resume correctly never triggers for
    it, with no special-casing needed.
  - 6 new tests in `tests/test_boq_dialog.py::
    AFollowUpResumesTheSameChatInsteadOfOpeningAFreshOne`: a first
    write-up leaves its chat resumable; a same-agent follow-up actually
    gets `resume_urls`; switching agents gets `None`; a SECOND follow-up
    resumes the FIRST follow-up's chat, not the original write-up's;
    "Make with drawing" as the very first action (nothing to resume yet)
    gets `None`; a mid-chain fallback to a different tool also gets
    `None`. 136/136 across the full BOQ+BOM+site-facts sweep.
  - **Said plainly, for the record:** the first pass at item 7 was
    reported as "Done" without actually tracing where a new browser tab
    comes from in the engine — it fixed a real problem, just not the one
    that was reported, and that gap wasn't caught until the owner tested
    it directly. The fix above is now verified against the actual
    mechanism that opens a tab, not just against Prism's own popup.

## 8. "Recheck with the drawing" and "Verify and remake" are the same job — renamed and made available from the start

Noted 2026-10-22, from the owner. **Done (2026-10-22).**

**The owner's point:** "Verify and remake" (the follow-up window's quick
action) and "Recheck with the drawing" (the button next to the result box)
send the exact same thing — the drawing file itself, with explicit consent
— to do the exact same job. The button should be renamed **"Make with
drawing"** and stand next to **"Make my BOQ"** from the start, not stay
disabled until a BOQ already exists: "Make my BOQ" uses the offline
measured quantities alone; "Make with drawing" gives the drawing file to
the AI directly, after asking permission again.

What shipped:
  - **Button renamed** — `i18n.t("Recheck with the drawing")` →
    `i18n.t("Make with drawing")`. `devtools/extract_strings.py` run after:
    2 new strings, 1 retired.
  - **Enabled by a drawing alone, not by also requiring an existing
    answer.** Previously gated on `bool(self.cad_path) and bool(texts)`
    (three separate spots: construction, after a write-up, and
    `_set_busy`) — now just `bool(self.cad_path)`, and also turned on the
    moment a drawing finishes measuring (`_on_measured`), not only after
    "Make my BOQ" has already run once. This is the actual fix: before,
    the button genuinely could not be pressed until a BOQ existed, which
    is why it only ever behaved like a recheck.
  - **One new prompt, used only when there is nothing to verify yet** —
    `MAKE_WITH_DRAWING_PROMPT`, next to the existing `VERIFY_PROMPT`.
    `VERIFY_PROMPT`'s own wording ("remake... in the same format as the
    previous answer... list what changed") only makes sense once an
    answer exists; pressing "Make with drawing" before any BOQ is written
    now sends the new prompt instead, asking the agent to read the
    drawing directly and cross-check it against the locally measured
    figures.
  - **The "PREVIOUS ANSWER" section is now conditional**, not always
    appended — `_send_followup` only adds it when `self.result` actually
    has text. Before this, pressing the button with no existing answer
    would have sent `"PREVIOUS ANSWER:\n\n"`, which reads as a blank
    previous answer rather than there being none.
  - **The live-progress window's title branches the same way** —
    "Making your BOQ from the drawing" when there is nothing previous
    (checked off whether the built prompt actually contains
    `"PREVIOUS ANSWER:"`, not by re-reading `self.result`, which could in
    principle have changed by the time the window opens), "Verifying
    against the drawing" otherwise — unchanged from before this item.
  - Both call sites still reach the SAME engine stage key, `"recheck"` —
    no change needed in `prism_terminal/core/contract.py`'s
    `_WRITING_STAGES` or anywhere else engine-side; only the prompt text
    and the window title differ between the two moments.
  - 5 new tests in `tests/test_boq_dialog.py` (the button's new label; on
    even with no answer yet; the no-previous-answer prompt omits
    "PREVIOUS ANSWER" and reads as making, not verifying, with the
    matching window title; the with-previous-answer path is unchanged)
    + the one stale test from item 2's era renamed to describe what is
    actually true now instead of what used to be true. 110/110 across
    the full BOQ+BOM sweep (`test_boq_dialog.py`, `test_boq_run_dialog.py`,
    `test_boq_file_guardrail.py`, `test_boq_pricing.py`).

## 9. A sample BOQ/template as a reference — discoverable, without sending the drawing

Noted 2026-10-22, from the owner. **Done (2026-10-22).**

**What was asked:** "there should be option for the user to just give in
the sample BOQs/template for the BOQs... such that they could be given as
the reference to the AI for creation of better BOQs without actually
giving the drawing file to the AIs."

**What was actually true before this item:** the mechanism already
existed and already worked exactly as asked — `prism_terminal/core/
boq.py:classify_inputs` has always sorted an attached sample/previous BOQ
(`.docx`/`.doc`/`.xlsx`/`.xls`/`.csv`/`.ods`/`.pdf`) into its own
`templates` role, described to the writing agent as "an example BOQ
showing the firm's usual style" — and the drawing is a SEPARATE role
(`cad`) that is never folded into it. This was never built in this
session; checked directly in the engine before touching anything. The
real problem was pure discoverability: nothing on screen ever told the
user a sample/template could be attached at all, so in practice nobody
attached one on purpose.

What shipped:
  - **A standing invitation**, `self.template_hint`, under the drawing
    format note: "You can also attach a sample BOQ or your usual
    template above — Prism will match its style, logo and layout. This
    is separate from the drawing, which is only ever sent to an AI after
    you say so, in 'Make with drawing'." — naming item 8's button
    directly, so the one reassurance the owner asked for (the drawing is
    not swept up in this) sits right next to the invitation, not in a
    different part of the screen.
  - **Turns into a confirmation once one actually lands** —
    `_update_template_hint()`, called from `_absorb()` whenever
    `classify_inputs` returns at least one template: "N sample
    template(s) attached — Prism will match the style shown. [same
    drawing reassurance]", singular/plural worded correctly, the count
    rising as more are attached rather than resetting.
  - **Scope, stated plainly**: no change to `classify_inputs`, no change
    to what gets sent to the AI or how — this item is screen text only,
    making an existing, already-correct behaviour visible and trustable.
  - 4 new tests in
    `tests/test_boq_dialog.py::AttachingASampleTemplateIsDiscoverableAndConfirmed`
    (the standing invitation's wording before anything is attached;
    attaching one confirms it with a count and still names "Make with
    drawing"; a second one updates the count and pluralises; a plain
    `.txt` note — classified as "notes", not "templates" — leaves the
    hint alone). `devtools/extract_strings.py` run after: 4 new strings,
    none removed. 114/114 across the full BOQ+BOM sweep.

## 10. "Price it" sat there, static and useless, before a BOQ even existed

Noted 2026-10-22, from the owner, with a screenshot. **Done (2026-10-22)
— both parts, after the owner's own clarification resolved the tension
part two originally flagged.**

**What was reported:** the "Price it (optional)" card appeared right
after a drawing was measured — before "Make my BOQ" had even been
pressed — sitting there empty and inert. The owner's own words: "this is
now staying static and honestly this is useless, as we can decide the
pricing based on just the measured quantities, we can add this feature
once the BOQ is formed." Proposed flow: form the BOQ first; once it
exists, let the user bring a price list as a later, deliberate step, and
"use the groq-inhouse agent to fill in the details in the BOQ document
that are already made like excel and word."

**Part one — shipped.** The card's DATA has been ready since the
measurement finished all along (`price_table.set_quantities()` in
`_on_measured`); only its VISIBILITY moved. `self.price_box.setVisible
(True)` no longer fires there — it now fires once a BOQ actually has
text, in both places that can produce the first one: `_on_written` (the
ordinary "Make my BOQ" path) and `_on_followed_up` (item 8's "Make with
drawing" used as the very first action, before any BOQ exists). A
write-up that comes back with nothing leaves the card hidden, same as
before pricing could ever have existed. 2 new tests in
`tests/test_boq_pricing.py` (shown once a real write-up lands; a write-up
with nothing back leaves it hidden) + the one stale test from this
card's original build renamed and corrected (it asserted the OLD
"visible right after measuring" behaviour, which is exactly what this
item reports as the problem). 116/116 across the full BOQ+BOM sweep. One
real bug caught building the test: calling `_on_written` with real text
reaches `_offer_followup()`, which opens a real `FollowupDialog` — had to
patch it the same way every other BOQ test on this path already does, or
the test hangs forever (CLAUDE.md: never exec()/a QEventLoop in a test).

**Part two — the owner's clarification, and what it actually meant.**
Asked to resolve the tension against `boq_price.py`'s "no number of
record is ever produced by an AI, without exception" rule (option (a)/
(b)/(c) above, as originally written). The owner's answer: "basically i
want that BOQ in any format gets filled in with the number from the
pricing list the user will attach, that's it" — option (b), and simpler
than first described: no AI merge step at all. The numbers were always
going to come from the user's own attached price list (the existing
deterministic matcher, unchanged); the actual, narrower gap was that
"any format" wasn't true yet — `write_boq_xlsx`/`_csv`/`_pdf` existed in
`core/boq_price.py`, `write_boq_docx` did not, so Word was the one format
the priced numbers could never reach. No Groq, no AI, no rule change
needed — this was a missing writer, not a missing merge.

What shipped:
  - **`prism_terminal/core/boq_price.py`: `write_boq_docx(boq, path)`**,
    fourth alongside the existing three. Reuses the SAME `Boq` model and
    the SAME canonical Decimal methods the other writers call
    (`subtotal()`/`contingency_amount()`/`pre_tax_total()`/
    `gst_amount()`/`grand_total()`) — nothing here recomputes a total
    independently, so Word can never disagree with Excel/CSV/PDF by a
    paisa. The CGST/SGST split mirrors `boq_html()`'s own approach
    exactly (SGST = `gst_amount() - cgst`, not computed separately, so
    the two halves always sum to the exact total). A table per the same
    `_COLS` header `write_boq_xlsx` uses, a merged section-header row
    per section, a sub-total row per section, then the same roll-up
    (sub-total → contingency → GST/IGST → grand total) and the same
    amount-in-words line. Guarded by a new `HAVE_DOCX` flag, same
    pattern as `HAVE_XLSX` — `python-docx` is already a project
    dependency, used elsewhere in the engine. Word has no formula cells,
    so unlike the xlsx sheet this is a flat, once-computed table — the
    docstring says so plainly, and that editing a rate here does not
    re-flow the totals the way Excel's live formulas do.
  - **`addons/boq/pricing.py`**: a fourth export button, "Save as
    Word…", next to Excel/CSV/PDF, wired through the same `export(kind,
    path)` / `_export(kind)` methods every other format already uses —
    no new code path, one new dict entry in each.
  - 1 new test, `tests/test_boq_pricing.py::TheExportsWriteWhatTheGridShows
    ::test_docx_has_the_same_grid_and_totals_as_every_other_format` —
    opens the real .docx with `python-docx` and checks the matched rate,
    the computed amount and the grand total are all actually in the
    table, the same shape the existing `test_csv`/`test_xlsx_has_live
    _formulas` tests already check for their own formats. `devtools/
    extract_strings.py` run after: 2 new strings, none removed. 117/117
    across the full BOQ+BOM sweep.
  - Manually verified directly against `core/boq_price.py` before
    wiring the UI: built a real priced `Boq`, wrote it, re-opened the
    .docx with `python-docx` and confirmed the table, the matched rate,
    and the GRAND TOTAL row all round-tripped correctly.

## 11. Prism's own offline measurement was wrong — first real-client-file bug, and the process for the next one

Noted 2026-10-22, from the owner, testing a real HVAC drawing end to end
(`HVAC_BOQ_TEST`, outside this repo: `hvac_sample.dxf`). **Done
(2026-10-22) — the bug, the fix, and the process for every future one.**

**What the owner actually found:** made a BOQ the normal way (measured
figures only, no drawing sent). Separately, out of curiosity, gave the
real drawing directly to an AI and got a second BOQ. Compared the two —
the AI's version was more accurate, and by a lot. Checked myself, directly
against the real file (not by trusting either generated document): Prism's
own offline measurement said the supply duct was **78.82 m**. It is
actually **38.80 m** — confirmed independently. Opened the raw DXF entity
by entity and found the exact cause: the duct is drawn as two parallel
lines 800mm apart (completely normal, professional HVAC drafting
practice), and `core.boq.measure()` was summing every line on the layer —
both edges counted as if they were two separate ducts.

**The uncomfortable part, said plainly:** the only reason the AI-written
version was right is that the real drawing left Prism's offline, "no AI
ever sees it" path. That is exactly the gap this fix closes — teaching
the *offline* measurer the convention, so the drawing never has to leave
the machine to get a correct number.

**The owner's instruction, which sets how every future one of these gets
handled:** don't call it "a suspicious layer" and stop there — that's not
a real fix. Teach Prism's code the actual rule, write the rule down
somewhere durable, and when a client brings more test files and more bugs
turn up, work through the same loop every time: find it, understand the
real drawing convention behind it, fix the measuring code itself, write
the rule down, test it so it can't come back.

**What shipped:**
  - **`prism_terminal/core/boq.py`: `_collapse_duct_pairs()`.** Before
    summing a layer's LINE lengths, looks for pairs that are roughly
    parallel, roughly the same length, and a small constant perpendicular
    distance apart (a run's own width) — treats a matched pair as ONE
    run's two edges, not two, and drops the short stub that closes a
    paired run's open end (not route length). Anything that doesn't match
    is measured exactly as it always was — this only ever acts on a
    genuine double-line pair, never an ordinary single-line run.
  - **A visible note, not a silent correction** — `measure()`'s existing
    `notes` list gets an entry naming the layer and how many pairs were
    read this way, "verify before pricing." The inference is real and the
    fix is real, but it is still an inference, not a raw measurement, and
    the module's whole promise is that nothing here is silently trusted.
  - **A real false positive caught and fixed before shipping, not after**
    — the first version (offset < 0.6 × length) nearly read a 24 m × 14 m
    room's opposite walls as one 24 m duct (ratio 0.58, close to every
    real duct pair's own ratio). Tightened to 0.5, confirmed against both
    the real duct geometry and a synthetic room, documented as the known
    edge of the current rule, not quietly tuned away and forgotten.
  - **`prism_terminal/core/HVAC_DRAWING_RULES.md`** (new) — the rule book
    the owner asked for. Rule 1 is this bug, in full: the convention, what
    broke, exactly what the fix does, and — importantly — what it does
    NOT yet handle (LWPOLYLINE double-lines, two genuinely separate runs
    accidentally sharing one layer, a tapering reducer's true centreline).
    Above rule 1, a numbered **process** section: get the client's real
    file and an independent ground truth, compare line by line, read the
    raw DXF coordinates rather than guessing from the symptom, name the
    general drawing CONVENTION responsible (not the one file), fix the
    measuring code itself, write the rule down in this same shape, add a
    synthetic regression test built from the real geometry (never the
    client's actual file kept in the repo), and re-run every rule's tests
    together before shipping the next one. `core/boq.py`'s own module
    docstring now points here.
  - 5 new tests, `tests/test_double_line_ducts.py`: a simple two-edge
    duct; the real client geometry reconstructed synthetically (pinned to
    within 100mm of the AI's own independent 38.80 m reading, nowhere
    near the old 78.82 m); an ordinary single-line run, untouched; two
    separate same-length parallel pipes on two different layers, both
    kept at their own full length; and the room-walls false positive
    that was caught and fixed, now locked in as a permanent regression
    guard. 130/130 across the full BOQ+BOM+site-facts sweep.
  - Checked which other add-ons this core-engine change could reach
    before calling it safe: only `addons/boq/dialog.py` and `addons/boq/
    measured.py` call `core.boq` at all — Gerber, STEP and every other
    add-on measure through their own, separate engines, untouched.

## 12. Item 7's real fix, and HVAC_DRAWING_RULES.md gated to HVAC requests only

Noted 2026-10-22/23, from the owner. **Done.**

### 12a. The real "opens a fresh tab" fix (item 7 was incomplete)

The owner tested item 7 directly: "Make with drawing," then a follow-up
on top of it, still opened a fresh browser tab — and the same thing
happened following up after "Make my BOQ". Item 7's write-up had been
marked "Done" without actually tracing where a browser tab comes from;
it fixed Prism's own small progress popup, which was real, but not what
"opens a new tab" meant.

**What was actually wrong:** the engine already has a working mechanism
for this — `resume_urls`, a `{stage: chat_url}` dict passed into
`AutomationWorker`/`core.automation.run()` that makes it navigate back to
an existing conversation instead of opening a fresh tab
(`_open_agent_page` checks it before deciding whether to open a new one
at all). `addons/step/dialog.py`'s own follow-up handler already uses it.
`addons/boq/dialog.py` simply never called it on any follow-up.

What shipped:
  - **`addons/boq/dialog.py`**: `self._last_agent` / `self._last_link` —
    who answered most recently, and that exact chat's own URL — updated
    at the end of every completed stage (`_on_written` for the first
    write-up, `_on_followed_up` for every follow-up/recheck after it, so
    a third follow-up resumes the SECOND one's chat, not the very first).
  - **`_fu_start_next`** builds `resume_urls = {self._fu_stage:
    self._last_link} if tool == self._last_agent and self._last_link else
    None` before constructing the `AutomationWorker`. Guarded on the SAME
    agent answering again — a different agent, or a mid-chain fallback to
    one, correctly resumes nothing (no chat of that other tool's exists),
    the same check `addons/step/dialog.py`'s `_on_answer_followup` makes.
  - Groq's branch is untouched — no browser page, so `self._last_link`
    stays empty whenever Groq last answered, and resume never triggers
    for it, with no special-casing needed.
  - 6 new tests,
    `tests/test_boq_dialog.py::AFollowUpResumesTheSameChatInsteadOfOpeningAFreshOne`.
  - **Said plainly:** the first pass at item 7 was reported "Done" without
    tracing the actual mechanism that opens a browser tab. This one is
    verified against that real mechanism, not just against Prism's own
    popup.

### 12b. HVAC_DRAWING_RULES.md gated — only when the request says "HVAC"

The owner's instruction, once item 11's fix was shipped: these rules are
trade-specific, verified against real HVAC drawings specifically, and
must never quietly start reading an electrical, plumbing or civil
drawing's lines differently too just because the geometry happens to
look similar. Going forward, more test folders will come in, each may
surface its own bug, and each fix gets taught into the code and written
into the rule book the same way rule 1 was (see HVAC_DRAWING_RULES.md's
own process section) — but the rules only ever engage when the person's
own request actually names HVAC. Nothing here is guessed from the
drawing's layer names or file name.

What shipped:
  - **`prism_terminal/core/boq.py`**: `measure(dxf_path, hvac=False)` —
    a new parameter. `_collapse_duct_pairs` (rule 1) only runs when
    `hvac=True`; otherwise every layer is measured exactly as it was
    before rule 1 ever existed — the plain sum, double-counted duct and
    all. The module docstring and `HVAC_DRAWING_RULES.md` both say so.
  - **`workers.py`**: `MeasureWorker` takes `hvac: bool = False` and
    passes it straight through to `boq.measure`.
  - **`addons/boq/dialog.py:_measure()`** decides `hvac` by checking
    `"hvac" in self.ask.text().lower()` — the person's own request text,
    read live off the ask box (not `self.request`, which isn't set until
    "Make" is pressed, well after measuring already ran). Typing "HVAC"
    anywhere in the request turns the rules on for that run; nothing
    else does. **Known limitation, stated plainly:** if the drawing is
    attached before "HVAC" is typed into the box, measuring has already
    run without the flag — type HVAC into the request before or
    alongside attaching the drawing.
  - **The audit-trail gap from item 11 is also closed here**: rule 1's
    own note (`q["notes"]`) was being computed but never actually shown
    anywhere — `_on_measured` only ever read the DXF *converter's* notes
    (a different list, `MeasureWorker.done`'s second value), never
    `q.get("notes")`. Both are now joined into the same line the person
    already sees under "Measured from your drawing" (`self.csv_label`),
    and `write_quantities_csv` now appends each note as its own `note`
    row in the exported CSV too, so it survives being emailed or filed
    away, not only shown once in the live app.
  - 7 new tests: `tests/test_double_line_ducts.py::
    TheRuleOnlyAppliesWhenHvacIsAskedFor` (hvac=False keeps the old,
    un-collapsed reading; hvac=True applies the rule) +
    `tests/test_boq_dialog.py::TheHvacFlagComesOnlyFromTheAskBox` (the
    word "HVAC" turns it on, case-insensitively; a different trade or no
    text yet leaves it off). The existing double-line-duct tests were
    updated to pass `hvac=True` explicitly, since they test the rule
    itself and must still exercise it now that it is opt-in.
  - Full BOQ+BOM+site-facts sweep green throughout (142 at last count);
    full project suite + `PRISM_SELFTEST` run before this push.

**Where to actually check this in the Prism UI, for the owner:**
  1. Attach the drawing with "HVAC" somewhere in the request text box.
  2. Once measured, open **"Measured from your drawing"** — the table
     shows the corrected length per layer directly (e.g. the supply duct
     reading ~38.3 m, not ~78.8 m).
  3. Just below the table, the green **"Saved so you can check every
     number →"** line now also shows the audit note when a rule fired —
     "M-DUCT-SUPPLY: read N pair(s) of lines as one run's two edges... —
     verify before pricing" — directly under that line, in amber/⚠ style.
  4. The exported CSV at that same path (openable in Excel) has the same
     numbers in rows, plus a `note` row for each one a rule touched.
  5. To see the difference for yourself: leave "HVAC" out of the request
     text for the same drawing and measure again — the duct layer reads
     the old, doubled number instead, with no note — proving the gate
     itself, not just the fix.

## 13. The measured-quantities panel: a bulleted dropdown for warnings, colour-coded trust, editable, a bigger window, and a Desktop CSV

The owner's report, 23 Oct 2026, on the same real multi-building site
file: the rules/warnings box (the amber "⚠ Look-alike layers..." /
"⚠ N of N ... blocks are ... km away..." / "⚠ LAYER: read N pair(s)..."
list, one line per flag) had grown into a wall of text on a file with
this many layers — and asked, since there will be many more such rules
over time, for it to become a dropdown, bulleted, instead of an
ever-growing flat box. Separately: the "Measured from your drawing"
table itself is too small to read comfortably — "you can't see more
than half of the information" — and needs a way to open it bigger; the
owner also asked for the table to be editable, with every row coloured
by how much Prism trusts it (green = fine, yellow = the HVAC
duct-pairing rule touched it and is worth a look, red = Prism genuinely
cannot resolve it and a person must), and for a way to save the
reviewed/edited numbers straight to a CSV on the Desktop once confirmed.
The green "Saved so you can check every number →" confirmation line
(`self.csv_label` in `dialog.py`) was explicitly called out as already
working correctly and is untouched by this item.

What shipped, all in `addons/boq/measured.py`:
  - **The warnings dropdown.** The old `self.warn` `QLabel` (always
    visible, one line per flag, all flags concatenated) is replaced by
    `self.warn_btn` (a small toggle button reading "⚠ N rules &
    warnings ▾/▴") and `self.warn_list` (a `QListWidget`, each flag its
    own bulleted row, collapsed by default, max height 180px so a very
    long list scrolls instead of pushing the table off-screen). Exactly
    the same warning text as before — unit-not-confirmed, inferred
    unit, look-alike layers, remote blocks, scope filter, and rule 1's
    pairing notes — just in a collapsed, bulleted list rather than one
    ever-growing label. `warning_lines()` returns the plain list for
    anything (tests, a future caller) that wants the text itself rather
    than the widget.
  - **Trust colour per row — `severity_for(q)`.** Reads the *exact same
    signals* the warnings list already shows, so there is never a
    second, independent judgement of what Prism is or isn't sure about:
    a layer in `site["lookalikes"]` or named in `site["remote_blocks"]`
    is red (Prism found something it cannot resolve by itself); a layer
    named at the start of one of `q["notes"]` (rule 1's "LAYER: read N
    pair(s)..." audit line) is yellow (the pairing rule acted on it,
    usually right, still worth a look); everything else is green. Every
    cell in a row is tinted with `theme.qcolor(theme.OK_BG /
    WARN_BG / ERR_BG)` — the same tokens the rest of the app already
    uses for this, nothing new invented.
  - **The Value column is editable.** Item/Layer/Unit stay identifiers,
    not numbers to retype — the same split `pricing.py`'s grid already
    uses (`_EDITABLE`/`COL_VALUE`). Double-click Value, type a number,
    and the instant it parses, the *whole row* turns green — editing a
    number is read as a person confirming it by hand, so it overrides
    whatever colour it started with, lookalike/remote-block flag
    included. A bad edit (not a number) is left alone — the cell keeps
    its old value and colour, nothing crashes, nothing is silently
    corrupted.
  - **"Open in a bigger window."** `MeasuredTableWindow` is a plain
    resizable `QDialog` holding another `MeasuredTable` instance with
    its height cap removed, 900×640 to start. Clicking the button again
    reuses the same window (`raise_()` + `activateWindow()`) instead of
    opening a second one, the same "reuse in place" pattern item 7's
    real fix used for the run-dialog popup.
  - **"Save as CSV (Desktop)."** Writes exactly what is on screen right
    now — edits included — to `~/Desktop/BOQ_Quantities_<timestamp>.csv`,
    no file dialog, confirmed with the same green banner style
    `pricing.py`'s exports already use. This is a second, separate CSV
    from the automatic one `_on_measured` already saves to
    `~/.prism/runs/` (item 12b) — that one is the raw, as-measured audit
    trail; this one is the person's own reviewed, possibly hand-corrected
    copy, saved on purpose, to the Desktop, only when they ask for it.
    `desktop_dir()` is its own function for exactly one reason: so a
    test can patch it and never once touch the real Desktop — the same
    rule this repo already holds for `~/.prism`.
  - A short legend line under the table spells out the colour meaning
    and that Value is editable, so nobody has to be told in chat.

What did **not** change: `rows_for()`, the CSV columns, the prompt text
the AI receives (`core.boq.summary_text`), and `self.csv_label` in
`dialog.py` (the green confirmation box) — all untouched, as above.

Tests: `tests/test_boq_dialog.py::RowsAreTintedByConfidenceAndValueIsEditable`
(severity mapping, the three colours actually land on the right rows,
only Value is editable, editing turns a row green, a bad edit is a
no-op) + `::TheExpandedWindowAndTheDesktopCsv` (the bigger window shows
the same rows, opening it twice reuses one window, the Desktop CSV is
written to a patched temp dir — never the real Desktop — with a header
row and one row per measured item). The two pre-existing tests that
read `t.warn.text()` (`test_boq_dialog.py` and `test_site_facts.py`)
were updated in this same commit to read `t.warning_lines()` /
`t.warn_btn` / `t.warn_list` instead, since the widget they were
checking no longer exists — same content, different container, said
plainly in both tests' docstrings rather than quietly patched around.
`devtools/extract_strings.py`: +7 new strings, 0 removed.

**Where to actually check this in the Prism UI, for the owner:**
  1. Measure a drawing with more than one or two flagged layers. Under
     "Measured from your drawing," the warnings no longer sit as a wall
     of amber text — there's a small "⚠ N rules & warnings ▾" button;
     click it to open the bulleted list, click again to collapse it.
  2. Look at the table itself: rows are now tinted — green, yellow, or
     red — at a glance, before reading a single number.
  3. Double-click a Value cell, type a corrected number, press Enter —
     the whole row turns green immediately.
  4. Click "Open in a bigger window" next to "Show every layer name" —
     the same table opens full-size, resizable, in its own window.
  5. Once satisfied with the numbers (edited or not), click "Save as CSV
     (Desktop)" — check your actual Desktop for
     `BOQ_Quantities_<numbers>.csv` and open it; it has exactly what was
     on screen.

## 13b. Same day, round two: the colour coding wasn't actually visible, and values were locked to the drawing's own unit

The owner tried item 13 and reported two things still wrong: "there isn't
[colour coding] right now," and a request for the unit to be user-
changeable directly in the measured-quantities window. Checked the running
Prism process first (started 11:10, after the file was last saved at
10:44) — not a stale-code problem, a real one: the row tint alone used
`theme.OK_BG`/`WARN_BG`/`ERR_BG`, the same pale, 14%-opacity tokens the
rest of the app uses for text banners — fine on a wide label, close to
invisible on a narrow table cell next to `setAlternatingRowColors(True)`.
Confirmed by actually rendering the widget offscreen and grabbing a
screenshot (not just reading the passing unit-test assertions) before
calling it fixed.

What shipped, `addons/boq/measured.py`:
  - **A dedicated Trust column** (`COL_TRUST`), a solid "●" dot in the
    full ink colour (`theme.OK_INK` / `WARN_INK` / `ERR_INK`), with a
    tooltip spelling out why. The pale row tint stays too (consistent
    with the rest of the app), but the dot is now the primary, impossible-
    to-miss signal. Columns shifted: Trust, Item, Measured as, Layer,
    Value, Unit, then the hidden sort column — `COL_TRUST`..`COL_SORT`
    are now named constants exported from the module so nothing outside
    it hardcodes a column number again.
  - **"Show values in:" unit picker** (`unit_combo`) — As measured / mm /
    cm / m / ft / in. `convert_value(kind, value, from_unit, to_unit)` is
    a plain, pure function: Length converts by a straight factor, Area by
    its square, Count never converts. Switching units calls
    `_render_rows()` alone — no re-measuring, the underlying `q` and
    `rows_for()` output are untouched, only the display changes. The
    picker is disabled (with a tooltip saying why) when the drawing's
    unit is neither confirmed nor inferred — Prism won't guess a
    conversion it isn't sure of, same rule as everywhere else in this
    module. Switching units re-draws from the original measured figures,
    so an in-progress hand edit does not survive a unit change — stated
    plainly in the on-screen legend, not just in this file.
  - `set_quantities()` was split: warning/header computation stays there,
    the actual table fill moved into a new `_render_rows()` so the unit
    picker can call just that part.

Verified before calling it done: `t.rows()` in "As measured" mode is
byte-for-byte the same output as before this change (a dedicated test
pins this), the full targeted BOQ+site-facts sweep (217 tests) green, and
— because a passing unit test had already been wrong about this once that
same day — the widget was actually rendered offscreen with `QWidget.grab()`
and the PNG inspected by eye: the dot and row tint are now clearly red /
amber / green, not merely "a QColor that matches in a test." `extract_strings.py`:
+8 new, -1 (the old, now-replaced legend line).

**The running Prism process will not pick this up on its own** — Python/Qt
does not hot-reload; the app must be restarted to see this round.

## 14. The HVAC_BOQ_R0.xlsx review's 4 proposed fixes — 2 shipped clean, 1 shipped with a correction caught before shipping, 1 deliberately not shipped

The owner compared Prism's own HVAC BOQ output against a second,
independent AI review of the same real `hvac_sample.dxf` and asked what
Prism is still missing for a proper HVAC BOQ. I proposed 4 fixes; the
owner's instruction, verbatim: "fix all... first tell me like the rule we
made, do we now have to teach out model again?" — yes, same process as
item 11/12b, each one its own numbered rule in `HVAC_DRAWING_RULES.md`,
a real-geometry regression test, gated behind `hvac=True`, verified
against the real file's actual coordinates before any of it was called
done.

**Shipped — Rule 2, the reducer counted once, not twice.** The real
file's supply duct moved from 38,319.8 mm (rule 1 alone) to 37,809.9 mm —
closer to the independently-verified 38.80 m, not the other direction.
`_duct_runs()` in `core/boq.py` is rule 1's pairing logic refactored to
also detect a converging (non-parallel) "transition" pair and count it
once, bounded so it can never be confused with an unrelated long diagonal
line elsewhere on the layer. `_collapse_duct_pairs()` is now a thin
wrapper over it, returning `(total, pairs_found, transitions_found)` — a
3-tuple, not 2; its one caller (`measure()`) was updated in the same
change.

**Shipped — Rule 3, duct/pipe sizes read from the drawing's own TEXT.**
The gap both the owner's own question and the second AI review landed on:
a route length alone can't be priced, GI duct is billed in m² per size,
and the size ("800x400", "DN80") sits right there as TEXT, never read
before. New, additive `q["duct_sizes"]` — `lengths_by_layer` untouched.
**Caught and fixed before shipping:** the first version matched labels to
runs by proximity alone and wrongly attached A-WALL (architecture, not
HVAC) to a duct-size label that merely sat nearby; fixed by scoping rule 3
to layers that name themselves duct or pipe work. Verified against the
real file: supply duct correctly split into 800x400 (10.2 m) / 600x400
(2.3 m) / 400x250 branches (24.8 m, matching the second review's own
number exactly), return duct 600x300, both CHW pipes DN80, total duct
sheet area 100.9 m² (the second review's own figure: 104.3 m² — close,
not identical, because that review also bridged branch take-off gaps,
which this round deliberately does not; see rule 2's "what it does NOT
handle yet").

**Shipped — Rule 4, a corner in a single-line run is an elbow.** Safe by
construction: only ever looks at two segments that already share an exact
coordinate, never a proximity guess. Verified: the real return duct's one
corner at (2000, 1000) is correctly found.

**Shipped, 25 Oct 2026 — branch take-off gap bridging, done properly this
time.** This was the 4th fix originally proposed (2026-10-22), built,
tested against the real file's own geometry, and found to produce a
wrong answer: a trunk that takes branches off BOTH sides at the same
point (very common — this file does it 3 times) got read as one
continuous run straight through the trunk's own body, silently adding
the trunk's own width (400–800 mm per occurrence, ~3 m wrong on this file
alone) as if it were missing duct. Not shipped then; documented as the
one piece of "fix all" honestly left undone, needing real topology.

Revisited by reproducing the exact false-positive case: reconstructed
`hvac_tender_complex.dxf`'s M-DUCT-SUPPLY trunk directly, found the real
junction at x=13275-13725 — two branches cross the trunk from opposite
sides at that exact point, one going up from (13275, 16400), one going
down from (13725, 15600), both landing their endpoint exactly on the
trunk's own gap boundary.

**The fix — `_duct_runs()` in `core/boq.py`:** a gap between two
collinear, same-width "pair" runs is bridged into one continuous run
ONLY when no other segment on the same layer has an endpoint landing
inside the gap. An endpoint there means a branch ties in — a real tee/
cross junction, the gap is the fitting's own width, not missing duct,
left un-bridged exactly as before this rule existed. No endpoint there
means nothing explains the split — a trunk broken into two LINE entities
for no topological reason — and it IS bridged.

**A real bug caught writing the test for this, not after:** the first
version checked ALL segments on the layer for a "crossing" endpoint,
including the two gap-forming runs' OWN boundary points — which sit
exactly at the gap's edges by definition, so every gap falsely read as
"branched" and nothing ever bridged. Fixed by tracking which raw segment
indices form each pair run (`seg_idxs`) and excluding only those from the
crossing check — a real branch can legitimately land exactly on one of
those same coordinates (confirmed: the real file's own branch does
exactly this), so coordinate matching alone couldn't tell the two apart;
only excluding by segment identity could.

**Verified against the real file, both directions:** `hvac_tender_complex
.dxf`'s M-DUCT-SUPPLY — all 3 of its real gaps correctly stay un-bridged
(143,862.5mm total, unchanged from before this rule existed, `bridged: 0`).
A synthetic gap with nothing crossing it correctly bridges (confirmed via
a direct `_duct_runs()` call before writing the test).

**An existing rule-3 test's fixture needed a real fix, not just a number
update:** `TextLabelsBecomeDuctSizesAndSheetArea::_trunk_split_by_a_
branch_gap` was named for a branch gap but never actually drew one — two
trunk pieces with an unexplained gap between them. This rule correctly
started bridging it (nothing proved it was a junction), breaking two
tests expecting the old, unbridged 7,600mm total. The fixture itself was
wrong, not this rule: added the actual crossing branch the name always
claimed was there, restoring the original expectation on a fixture that
now actually demonstrates what it says it does.

Tests: `tests/test_double_line_ducts.py::
ABranchTakeOffGapIsBridgedOnlyWhenNoBranchTiesIn` (3 tests — a gap with
nothing tied in bridges; a gap with a branch tied in stays separate; the
real file's own both-sided junction, reconstructed, never bridges) + the
`_trunk_split_by_a_branch_gap` fixture fix. Full `test_double_line_ducts.py`
sweep (21 tests) + targeted BOQ suite (`test_boq_dialog.py`,
`test_boq_run_dialog.py`, `test_boq_file_guardrail.py`,
`test_boq_pricing.py`, `test_site_facts.py`) green.

Tests: `tests/test_double_line_ducts.py` gained
`ATaperingTransitionCountsOnceNotTwice` (2 tests),
`TextLabelsBecomeDuctSizesAndSheetArea` (4 tests, including the
A-WALL-never-sized regression), `ACornerInASingleLineRunIsAnElbow`
(2 tests) — 8 new, all built from the real file's own coordinates or a
minimal isolated case, not guessed numbers. The one pre-existing test that
pinned rule 1 alone's number (38,320 mm) was updated to the rule-2-correct
number (37,810 mm) in this same commit, with the reason stated in its own
docstring, per the project's rule about changing a test alongside the
behaviour it pins. Full targeted BOQ+engine sweep (166 tests) green; full
project suite running before push.

## 15. A second, more complex HVAC test file — the real errors were write-up judgement, not measurement, and the prompt is where most of them had to be fixed

The owner supplied a second, more complex real file (`hvac_tender_complex.dxf`
— two AHU halves of an office floor, ~1000 entities, duplicate legacy/
current layer naming) and its own two-way comparison (Prism's own
`not_from_drawing.xlsx` vs an independent AI-with-the-drawing
`from_drawing.docx`), then gave explicit direction: fix what prompting can
fix first, "apart from that, when there are genuine measurement quantities
errors we can set the rules and teach the model" — i.e. prompting first,
engine rules only for what prompting genuinely cannot reach.

**The real finding: the biggest error was never a measurement bug.** The
write-up AI silently decided two differently-prefixed layer sets
(`M-DUCT-SUPPLY` vs the legacy-looking `HVAC_SA_DUCT`) were "the same
system, legacy duplicate" and **dropped an entire real half of the
building's ductwork** — AHU-02's own zone, with its own sizes — from the
priced BOQ. Traced to the exact sentence in `core.boq.formatting_prompt()`
licensing it: "when two layers look like the same feature... **decide —
count it once or keep both**." That is an instruction to silently choose,
and on this file it chose wrong.

**Fixed, `core/boq.py`:**
  - **`formatting_prompt()`'s cad_note, clause (e), rewritten.** The
    licence to "decide" is gone. New rule: compare the actual FIGURES, not
    the names. Identical or near-identical (within ~2%) → likely one
    feature traced twice, pick one, say which and why. Figures that
    DIFFER by more than a small margin → likely two real, separate things
    — NEVER drop either one, price both, flag for the designer to confirm.
    When unsure, keep both. Stated plainly: dropping real ductwork because
    it looked like a duplicate is the one mistake not to make; keeping an
    actual duplicate priced twice is recoverable (the reader can net it
    out) and far less harmful. This is a general write-up-quality fix, not
    HVAC-specific — the same failure mode (two similarly-named layers, one
    silently dropped) could happen on any trade's drawing.
  - **`formatting_prompt()`'s cad_note, new clause (f).** A second gap the
    independent review caught: several terminal/damper counts were off by
    exactly 1 per type (e.g. 47 vs the true 46) because a drawing's own
    LEGEND/KEY — one reference instance of each symbol — got counted as an
    installed item. Prism's measurement cannot tell a legend instance from
    a real one (that needs geometric legend-region detection, not
    attempted here — flagged as a known limitation, not silently
    guessed around). The prompt now tells the writer to say so next to any
    count that could include one, and point the reader at a terminal
    schedule on the drawing if it has one, rather than silently trusting
    or silently adjusting the raw count.
  - **`summary_text()` now includes rule 3's `duct_sizes`.** A real,
    separate bug from the prompt wording: rule 3 (item 14) computed real
    duct/pipe sizes and sheet areas the same day, but nothing ever put
    them in front of the write-up AI — `summary_text()` (what actually
    reaches the prompt) never read `q["duct_sizes"]` at all, so every BOQ
    still said "TBC — to HVAC schedule" even once the engine knew better.
    One new block, aggregated (layer, size, kind) so a trunk split into
    many short segments by branch take-offs shows one line per real size,
    not a dozen near-duplicates — caught live: the first version listed
    "M-DUCT-SUPPLY 800x450" twice, separately, because two different
    chains happened to share that size.
  - **A real bug caught verifying the above against the complex file:**
    `_duct_sizes_for_layer()` matched a label to a run by nearest distance
    alone, with no check that a *duct*-pattern label only ever attaches to
    a *duct* layer and a *pipe*-pattern label only to a *pipe* layer. A
    "DN32" pipe label sitting closer to a duct run than any duct-pattern
    label produced a nonsensical "M-DUCT-FLEX, DN32" entry. Fixed: each
    layer now only matches labels of its own expected kind (from the
    layer's own name, same "duct"/"pipe" signal rule 3 already uses to
    decide which layers get sized at all).

**What this round deliberately did NOT do:** detect a drawing's legend
region geometrically (flagged, not solved — see clause (f) above); read
equipment TAG text (CH-01, AHU-01) — Prism only reads size patterns, not
arbitrary tags, lower priority since it affects labels, not quantities;
read a terminal SCHEDULE table's own figures to cross-check block counts
— real capability gap, bigger undertaking, not attempted this round.

Tests: `tests/test_boq_dialog.py::test_the_writer_is_told_not_to_silently_
drop_a_look_alike_layer` (the new clause (e)/(f) wording is present; the
old, dangerous "decide — count it once or keep both" phrase is gone from
the test that used to check for it). `tests/test_double_line_ducts.py`
gained the kind-mismatch regression (2 tests: a pipe label near a duct
layer, a duct label near a pipe layer — neither ever attaches) and the
summary-text aggregation test (one line per layer+size, not one per
chain). Verified end-to-end against the real `hvac_tender_complex.dxf`:
both `M-DUCT-SUPPLY` and `HVAC_SA_DUCT` now get their own full size
breakdown in the text the write-up AI reads (so the prompt fix has real
data to act on, not just permission to act on it), and no duct layer
produces a DN-labelled entry or vice versa. Full targeted BOQ+engine sweep
(205 tests) green; `extract_strings.py` — no diff (engine-only change);
selftest clean.

## 16. The colours were never actually visible — style.qss was silently overriding every one of them

The owner sent a real screenshot after restarting Prism: every Trust dot
solid black, no row tint anywhere, despite item 13b being tested and
declared fixed. Root cause, found by reproducing it (loading the real
`style.qss` the same way `main.py` does, not the bare widget every earlier
test used): `style.qss` has `QTableWidget::item { ...; color: #09090b;
...; }` with no per-item exception. Qt's style sheet engine paints every
item of that class with that fixed colour once a stylesheet declares it —
a `QTableWidgetItem`'s own `Qt.ForegroundRole` / `Qt.BackgroundRole` brush
is silently ignored at paint time, even though the item's own data still
reports it correctly (confirmed directly: `.foreground().color()` returned
the right red; the rendered pixel was `#09090b`, the stylesheet's colour,
not the item's). This is a known Qt/QSS limitation, not a bug in this
file's own code — and it is why every earlier verification this session
(including an actual offscreen screenshot) missed it: none of them loaded
the real app stylesheet before rendering.

**Fixed, `addons/boq/measured.py`:** `_TintDelegate`, a `QStyledItemDelegate`
subclass that paints each cell itself — fills the background from the
item's own `Qt.BackgroundRole`, draws the text in the item's own
`Qt.ForegroundRole` colour, with a light selection tint — entirely
bypassing `style()->drawControl()`, which is the one path style.qss
intercepts. Set once on the table (`setItemDelegate`); editing (the Value
column) is untouched, since only `paint()` is overridden, not the
editor-creation methods.

**Verified properly this time:** rendered the widget with the real
`style.qss` loaded (not a bare widget) and sampled an actual pixel — red
for a flagged row, confirmed. Then, to prove the new test itself is
trustworthy and not just passing by coincidence: temporarily disabled the
delegate, re-ran the same test, watched it fail with the pixel reading
back exactly `#09090b` (the stylesheet's own forced colour), then restored
the fix and confirmed green again. `tests/test_boq_dialog.py::
RowsAreTintedByConfidenceAndValueIsEditable::
test_the_colours_actually_render_on_screen_under_the_real_stylesheet` is
that test, kept in the suite — it loads the real stylesheet and checks an
actual rendered pixel, specifically so a regression here fails the same
way the owner's screenshot did, not just in the data model.

**The related `pricing.py` bug flagged above — confirmed and fixed,
2026-10-25.** Checked `PricingTable` directly against the real
`style.qss` rather than assuming it was fine because it uses the same
colour tokens: with the plain `QStyledItemDelegate` it had before, an
unpriced row's warning tint (`cell.setBackground(tint)`, the only tint
this table has) rendered as flat white (`#ffffff`) — the exact same
invisible-colour bug, confirmed with an actual sampled pixel, not
inferred. **Fixed:** `addons/boq/pricing.py` now imports and sets the
same `_TintDelegate` from `addons/boq/measured.py` on its own table
(`self.table.setItemDelegate(_TintDelegate(self.table))`) — an
intra-add-on import (`from addons.boq.measured import _TintDelegate`),
same pattern `addons/whatsapp/`'s own files already use for a shared
private helper, not a cross-add-on one. With the delegate set, the
same pixel renders `#f8efdd` — theme.WARN_BG composited on white, warm
and short of 255 on blue, clearly not the bug's flat white. 1 new test
in `tests/test_boq_pricing.py`
(`test_the_unpriced_tint_actually_renders_under_the_real_stylesheet`),
built the same way item 16's own test was: loads the real `style.qss`,
samples an actual rendered pixel — and, to prove the test itself
catches the regression and not just coincidentally passes, temporarily
removed the `setItemDelegate` call, re-ran it, watched it fail with
the pixel back at `#ffffff`, then restored the fix and confirmed green
again. `COL_RATE`'s editability (one of pricing's `_EDITABLE` columns)
is untouched — the delegate only overrides `paint()`, never the
editor-creation methods, the same guarantee measured.py's own Value
column already relies on.

Full targeted BOQ+engine sweep (224 tests) green; `extract_strings.py` —
no diff; selftest clean.

## 17. Item 15's write-up fix was universal — the owner caught it, correctly, before testing it

The owner's instruction, verbatim, right after being told item 15's prompt
fix was ready to test: "be very specific about when to give this prompt,
this type of prompts shall only be given when the BOQ is specifically
made for the HVAC industries... from now only i say that you basically
store the data of the HVAC sector into a place where it doesn't affect
other BOQs." Checked, and the owner was right to ask: clauses (e) and (f)
from item 15 — the "don't silently drop a look-alike layer" rule and the
legend-overcounting caution — had no gate at all. They would have shaped
every BOQ `formatting_prompt()` writes, not just HVAC ones: ELV, CCTV,
cabling, plumbing, fire hydrants all call this same function.

**Fixed, `core/boq.py` and `addons/boq/dialog.py`:**
  - `formatting_prompt()` gained an `hvac: bool = False` parameter. Clauses
    (e) and (f) were pulled out of the generic `cad_note` block entirely
    and moved into their own block, `hvac_note`, appended to the prompt
    only when `has_cad and hvac` — physically separate from the generic
    instructions, not just logically gated, so the HVAC-specific content
    stays in one place to find, audit or extend without touching what
    every other trade's BOQ reads. Labelled plainly in the prompt itself:
    "HVAC-SPECIFIC WRITE-UP RULES (this BOQ was asked for as HVAC)".
  - **`addons/boq/dialog.py`**: the `hvac` decision is no longer made only
    once, locally, inside `_measure()` — it's now remembered on the
    dialog as `self._hvac`, set the moment measuring starts, and reused
    unchanged at `_write()` time (which can run well after measuring, by
    when the ask box's text may have changed). `_write()`'s call to
    `formatting_prompt()` passes `hvac=self._hvac`. This keeps the write-
    up guidance tied to whatever the MEASUREMENT itself actually used —
    exactly consistent with item 15's `duct_sizes` wiring, which is
    already empty for a non-HVAC run by construction, so the two
    HVAC-only pieces of this round (the sizes data and the write-up
    rules) now turn on and off together, from the same one decision.
  - Rule 3's `duct_sizes` block in `summary_text()` (item 15) needed no
    change — it was already self-gating, since `q["duct_sizes"]` is only
    ever non-empty when `measure(..., hvac=True)` found something.

Verified both directions against the real `hvac_tender_complex.dxf`: a
prompt built with `hvac=True` contains "HVAC-SPECIFIC WRITE-UP RULES"; the
exact same measured summary, built with `hvac=False` (the default, what
every ELV/CCTV/cabling/plumbing/fire-hydrant run gets), does not — proven
as a real `formatting_prompt()` call, not just by reading the code.

Tests: `tests/test_boq_dialog.py::test_the_writer_is_told_not_to_
silently_drop_a_look_alike_layer` now calls `formatting_prompt(...,
hvac=True)` explicitly; new `test_the_hvac_write_up_rules_never_appear_
for_any_other_trade` proves the phrase is absent both at the default and
with `hvac=False` stated explicitly. `TheHvacFlagComesOnlyFromTheAskBox`
(the existing class guarding the measurement-side gate) gained
`test_the_flag_is_remembered_for_the_write_up_stage_too` (confirms
`d._hvac` survives from `_measure()`) and two more exercising the real
`d._write()` path end to end — a captured `AutomationWorker` call's actual
assembled prompt text, not a unit test of `formatting_prompt()` in
isolation — proving the HVAC rules reach the write-up stage when asked
for HVAC and never otherwise. Full targeted BOQ+engine sweep (230 tests)
green; `extract_strings.py` — no diff; selftest clean.

**Standing instruction for every future HVAC-sector addition, write-up or
measurement:** goes in its own clearly separate place (a dedicated block
like `hvac_note`, a dedicated function, or `HVAC_DRAWING_RULES.md` for the
measurement side), gated behind the same `hvac` flag this whole file
already threads from the ask box through to every stage, never folded
into the generic instructions every other trade's BOQ also reads.

---

## CHECKPOINT — 23 Oct 2026, end of session

**Everything below is on disk, nothing is committed or pushed.** Last
pushed commits: app `557bbdc`, engine `bd8fa50`. Items 13–17 (this whole
second half of the day — colour coding, the unit picker, the style.qss
colour bug, rules 2/3/4, the write-up prompt fix, the HVAC/ELV scoping
fix) are all uncommitted working-tree changes on top of those. `git
status --short` right now: `addons/boq/dialog.py`, `addons/boq/
measured.py`, `tests/test_boq_dialog.py`, `tests/test_double_line_
ducts.py`, `tests/test_site_facts.py`, `lang/_catalogue.json`,
`BOQ-CHANGES-TODO.md` (app repo); `core/boq.py`, `core/
HVAC_DRAWING_RULES.md` (engine submodule). (`docs/GERBER_INTRO.md` is
also untracked — a separate, unrelated one-pager from earlier the same
day, not BOQ work.)

**Don't push without being asked.** The owner's own standing rule — pull/
merge/push only when told in that message — and nothing in this session
said to push this round.

**What's done and verified** (each item above has its own "where to
check" / test section — this is just the index):
  - Item 13/13b: measured-quantities panel — collapsible warnings, Trust
    colours, editable Value, bigger window, Desktop CSV, unit picker.
  - Item 14: HVAC rules 2–4 (reducer counted once, duct/pipe sizes from
    TEXT + sheet area, elbow detection) — all gated behind `hvac=True`.
  - Item 15: the write-up prompt actually uses rule 3's sizes; the
    duplicate-layer and legend-overcounting write-up guidance.
  - Item 16: the colours' real bug (style.qss silently overriding every
    per-item colour in the whole app) and its fix (`_TintDelegate`).
  - Item 17: item 15's write-up guidance correctly scoped to `hvac=True`
    only — proven absent for every other trade, not just present for HVAC.
  - Full targeted BOQ+engine sweep (230 tests) green at every step; two
    full-project background runs were started and stopped mid-way as
    later edits made them stale — **the full suite has NOT actually
    finished clean end-to-end since item 14 landed.** Only the targeted
    sweep and the app selftest have confirmed-green runs on the final
    code. Run `QT_QPA_PLATFORM=offscreen python3 -m pytest -q
    --timeout=120` yourself (or ask for it) before pushing.

**What's left for the owner to check, when back:**
  1. **Restart Prism** — the running process predates all of today's
     engine/UI changes; Python does not hot-reload.
  2. Re-run the SAME complex file (`hvac_tender_complex.dxf` in
     `HVAC_BOQ_TEST/`) with the SAME "HVAC" prompt as before, and compare
     the new BOQ against `not_from_drawing.xlsx`/`from_drawing.docx` (the
     two files already in that folder) — specifically: does it still drop
     the east half (`HVAC_*` layers)? Does it use real duct/pipe sizes
     instead of "TBC"? Does the measured-quantities panel show visible
     red/yellow/green and a working unit picker?
  3. Try the same file with a NON-HVAC request (e.g. "ELV/CCTV BOQ") and
     confirm none of today's HVAC-only guidance shows up in that prompt —
     items 15/17's whole point.
  4. Once satisfied, say so and ask for the full suite + push — engine
     first, then the app with its gitlink bumped, per CONTRIBUTING.md.
  5. Longer-term, noted but not done: `addons/boq/pricing.py`'s
     `PricingTable` likely has the same style.qss colour bug as item 16
     (same pattern, never verified) — flagged in item 16, not fixed.

## 18. A second way into the BOQ pipeline: paste or upload measurements, no drawing needed

The owner's ask, 24 Oct 2026, new session: a tool like the PDF takeoff
extractor (`hvac_takeoff/`, a separate program outside Prism) measures a
tender PDF and produces numbers — but there was no way to get those
numbers INTO Prism's own BOQ pipeline except by faking a drawing. Asked
for a button beside the measured-quantities area that opens a window to
paste or upload already-measured figures, which then feeds "Make my BOQ"
the same way a real drawing's measurement does — and confirmed the ask
box still has to say what the BOQ is for (e.g. "Create me a BOQ for the
HVAC industry"), same as always, so HVAC gating still works correctly.

**What shipped, `addons/boq/dialog.py`:**
  - **`InputMeasurementsDialog`** — a small, self-contained dialog: paste
    text, or upload a file (any text/JSON/CSV — read as plain text, not
    parsed into a specific schema). Deliberately does not try to
    understand the other tool's JSON shape; whatever is pasted or
    uploaded is trusted as already-measured, the same way a sample BOQ or
    a legend note is handed to the writer as text and not reinterpreted
    here. "Use these measurements" is blocked (via a message box, not
    silently) until something is actually there.
  - **"Input measurements…" button**, placed directly below the sample-
    BOQ invitation, always visible (not gated on a drawing existing) —
    confirmed screenshot, not just a passing test.
  - **`_use_external_measurements(text)`** — the actual wiring: sets
    `self.q` to a small, clearly-marked dict (`{"external": True,
    "text": text}`, never a guessed structured shape) purely so
    `has_cad=bool(self.q)` and the rest of the dialog see that something
    measured now exists, and sets `self.summary = text` directly — that
    is what `_write()` actually hands the writer as the measured
    quantities, confirmed end-to-end with a captured real prompt, not
    just by reading the code. Writes the pasted text to a file in
    `RUNS_DIR` (same "a real file survives this, not only the screen"
    habit as a real measurement), and decides `self._hvac` from the ask
    box the exact same way `_measure()` does, so the HVAC-only write-up
    guidance (item 17) still only fires when the request actually says
    HVAC, regardless of which path the numbers came in by.
  - **A new "External measurements" panel**, separate from the real
    drawing's "Measured from your drawing" panel — only one is ever
    shown at a time (using external measurements hides the drawing
    panel and vice versa), so the screen can never claim two different
    things both measured the current BOQ.
  - "Make with drawing" stays correctly disabled in this path (no real
    drawing exists to re-read).
  - The drawing-never-touches-an-AI promise holds for this path by
    construction: there is no drawing here at all, only text someone
    already measured elsewhere — the same trust level `summary_text()`
    output already has.

Tests: `tests/test_boq_dialog.py::ExternalMeasurementsAreASecondWayIn`
(7 tests: q/summary set correctly, writes only to a patched RUNS_DIR
— never the real one, HVAC decided from the ask box both ways, only one
measurement panel ever visible at once, "Make with drawing" stays off,
and an end-to-end captured prompt proving the pasted text and the HVAC
rules both actually reach the writer) + `InputMeasurementsDialogTests`
(3 tests, including one that caught a real test-writing mistake of my
own: `_confirm()`'s empty-input warning is a blocking `QMessageBox` —
same trap as `.exec()`/`processEvents()` this project has hit before —
mocked, not skipped). Full targeted BOQ sweep green; `extract_strings.py`
+12 new, 0 removed; selftest clean; verified visually with the real
stylesheet loaded, same discipline as item 16.

**Still open, the owner's own next step (not started):** reverse-engineer
the PDF takeoff tool's accuracy by first generating a BOQ straight from
the PDF (ground truth), figuring out which parameters came from geometry
vs. judgement, implementing the geometry ones in `hvac_takeoff.py`
properly, and leaving the judgement-only ones for the write-up agent to
fill with a proper prompt — same process as `HVAC_DRAWING_RULES.md`'s own
8-step method, applied to the PDF side.

## 19. Reverse-engineering, item 1: Hi-Wall split units from a drawing note, not a symbol

Step 1 of the reverse-engineering pass: rendered the real ASPENTECH tender
PDF myself and looked at it directly (not just the JSON output) — same
"read the real thing yourself, don't trust a tool's own summary" discipline
as the DXF side's rule book. Confirmed visually: diffusers, flex
connectors and dampers are real, repeating, countable shapes (bigger job,
left for later); but the two small wall-mounted AC units on this drawing
aren't drawn as a distinct block at all — they're a plain text note,
"2TR HI-WALL", sometimes with the installed count given a line below as
"2NOS.". `core.boq.measure()`'s own TEXT_RE already matched the "2TR"
inside that note and silently folded it into the generic tonnage list,
indistinguishable from the real rooftop unit's "17 TR" — a quiet
under-count, not a missing feature.

**Shipped, `hvac_takeoff/hvac_takeoff.py`:**
  - `HIWALL_RE` / `NOS_RE`, and `parse_label()` now claims the "<N>TR
    HI-WALL" span before the generic `TR_RE` pass runs, so it becomes its
    own `kind: "equipment"` entry instead of a second, indistinguishable
    tonnage tag.
  - `_equipment_from_labels()` — the capacity note and its "NOS." count
    are genuinely two separate text boxes on this drawing, joined here by
    proximity (not assumed to be the same string); no "NOS." found nearby
    defaults qty to 1, not 0 or blank — a single unit's own note usually
    has none.
  - **A real bug caught verifying this, not assumed away:** a second,
    noisier OCR pass of the exact same label ("L2TR _HI-WALL", stray
    characters breaking `HIWALL_RE`) fell through to a plain `TR_RE`
    match, producing a spurious generic `tr: 2.0` entry a few inches from
    the equipment entry already captured correctly. Fixed by dropping a
    `tr` label that sits this close to an already-found equipment entry
    of the same capacity — the same note read twice, not a second tag.
  - `result["equipment"]` now holds real entries; the old "equipment is
    empty by design" warning was quietly false the moment this shipped —
    split into an honest "equipment: only Hi-Wall units are read, every
    other type (AHU, chiller, FCU...) is not" warning, kept separate from
    the still-genuinely-empty categories' own warning.
  - `summary_text()` now shows an EQUIPMENT section — this was reaching
    the JSON but never the screen or the plain-text prompt before.

**Verified against the real drawing, not just logic:** ran the actual
extraction on `FINAL LAYOUT-Model.pdf` — found both real Hi-Wall notes, at
the two positions already confirmed by eye (qty 2 correctly joined to its
"2NOS." note; qty 1 correctly defaulted where no count was nearby), and
confirmed the generic `tr_labels` list stayed clean (no stray tonnage
value leaking in from either note, including the noisy second OCR pass).

**New: `hvac_takeoff/test_hvac_takeoff.py`** — this tool had no test file
at all before today. 8 tests: the capacity/equipment split, hyphen vs.
space vs. case tolerance in the note's wording, a plain "17 TR" (no
HI-WALL suffix) correctly staying generic, the proximity join (near =
joined, far = not, two separate notes each get their own nearest count),
and the zero-NOS.-nearby fallback.

**A separate, pre-existing issue found but NOT fixed today** (outside
this item's scope): the real "17 TR" label gets read once by the real
text layer and a second time by OCR scanning the same rasterised page —
the two are never cross-deduplicated against each other (only OCR-vs-OCR
passes are), so the generic `tr_labels` list currently shows the one real
rooftop unit three times, not two. Worth its own pass later.

**Still open, reverse-engineering items 2+**: diffuser/flex-connector/
damper counting by shape (the bigger, higher-value item); the ambiguous
second duct number per room, left for the write-up agent to flag, not
measuring to resolve.

## 20. Reverse-engineering item #1's own dedup gap, and item #2 — counting diffusers, flex connectors and dampers by shape

Noted 2026-10-24, from the owner, two things at once: "do fix this" (the
real-text-vs-OCR double-count item 19 flagged but left alone) "as well as
start doing item #2" (counting the three repeating symbol types by shape,
the bigger reverse-engineering item named when this whole effort started).
Both done, `hvac_takeoff/hvac_takeoff.py`.

**The dedup fix.** The real "17 TR" rooftop-unit label was being read
once by the PDF's own real text layer and a second time by OCR scanning
the same rasterised page — `ocr_page()`'s own OCR-vs-OCR dedup only ever
compared its two passes (0°/90°) against each other, never against the
text layer, so the same physical label counted as two. Fixed by a new
`dedupe_labels(labels, pt_per_ft, radius_ft=1.0)`, run once after all
pages' labels are collected, before the equipment join: for same-kind,
same-value, same-page labels within 1ft of each other, keeps the
`source=="text"` one over any OCR source, and among OCR-only duplicates
keeps the higher-confidence one. Verified on the real file: `tr_labels`
went from `[17.0, 17.0, 17.0]` to the correct `[17.0, 17.0]` — the two
genuinely separate rooftop units, ~75ft apart, correctly NOT merged (1ft
radius is far smaller than that). `equipment` entries unaffected.

**Item #2 — symbols counted by shape, not by a named block.** A PDF
export from AutoCAD generally does not keep reusable block/XObject
references — every symbol is flattened to its own literal rectangles —
so a diffuser, flex connector or damper can only be found by its shape
signature (colour + line weight + kind + a plausible size), the same way
item #1 found the Hi-Wall note by text pattern instead of a block. Found
by rendering each colour/weight layer in isolation and visually
confirming it against the real drawing, not guessed:
  - Diffusers = `#00ffff@0.84:rect` (cyan squares in the ceiling grid).
  - Flex duct connectors = `#ffbf7f@0.48:rect` (tan rectangles at duct
    take-offs).
  - Volume control dampers = `#ff0000@1.08:rect` — but this layer also
    carried the building's own giant outline rectangle (888×1556pt, not
    a damper) and every real damper is drawn as TWO overlapping squares
    (an outer ~9×9pt, an inner ~4.4×4.4pt) at the same spot — both an
    overcount risk and a double-count risk on the same layer at once.

What shipped:
  - `ROLES` gains `"diffuser"`, `"flex_connector"`, `"volume_damper"`;
    new `SYMBOL_ROLES` set and `_SYMBOL_MAX_PT` size cap per role (20pt
    for diffuser/flex_connector, 12pt for volume_damper — tight enough to
    exclude the building outline and an unrelated 49.9×15.2pt rect found
    on the same damper layer, found by inspecting the real rect sizes
    directly, not picked blind).
  - `count_symbol_rects(page, layer_map, role)` — new. Filters
    `page.rects` to the ones mapped to `role`, drops anything over the
    size cap, then dedupes the survivors by position (<2.0pt apart =
    one symbol, not two) so a damper's paired outer/inner square is
    counted once.
  - `extract()`: symbol roles are pulled OUT of the ordinary duct-pairing
    `by_role` path (they're shapes, not line-pairs) and counted per page
    with `count_symbol_rects()` instead — diffusers land in
    `result["terminals"]`, flex connectors and dampers in
    `result["accessories"]`, each with `cfm`/`size`/`room` left blank
    (`source: "geometry"` — a shape tells you it exists and where, not
    its airflow or which room it serves). Warnings rewritten to say so
    plainly rather than claiming these categories are always empty.
  - `layer_map.json` updated: the three colour keys above, previously
    `"ignore"`, now map to their symbol roles.
  - **Verified end-to-end against the real file**, not just in isolation:
    `extract()` on `FINAL LAYOUT-Model.pdf` returns 40 diffusers, 67 flex
    connectors, 13 dampers. Checked this isn't an over-merge: the closest
    two diffusers in the final output are 36pt apart — clean grid
    spacing, nowhere near the 2pt dedup radius, so nothing genuinely
    separate got collapsed together.
  - New `CountSymbolRectsCountsShapesNotRawRects` (4 tests) in
    `hvac_takeoff/test_hvac_takeoff.py`, synthetic `_FakePage`/`_rect`
    fixtures: only rects mapped to the target role count; an oversized
    rect on the same layer is excluded; a nested outer+inner square at
    one spot counts as one symbol; two genuinely separate symbols both
    count. 15/15 across the whole file (the pre-existing 11 plus these 4),
    re-run clean after the dedup fix too.

**Still open**: `cfm`/`room`/`tag` on every terminal/accessory entry are
left blank by design (not geometry-derivable) — flagged in the warnings,
not silently guessed; the ambiguous second duct number per room is still
untouched, left for the write-up agent as before.

## 21. The ambiguous second duct number per room — detected by its ink colour, not resolved, not silently merged

Noted 2026-10-24, from the owner: item #3 of the reverse-engineering list
("flex connectors and dampers") had already shipped together with
diffusers in item 20; the only item left on that original list was #4 —
every room on the real drawing has a primary black duct size/CFM pair
(e.g. "20"x30"/4000cfm") and a second one, right below it, in orange
(e.g. "36"x8"/600cfm"), with no legend on the sheet saying what the
orange one represents (a secondary branch? a return tie-in? an older
system?). Not geometry-derivable — the owner's own original instruction
was to leave values like this unfilled rather than guess, and let the
write-up agent ask about them.

**What this item does NOT do**: it does not decide what the orange
number means. It only makes sure the tool stops silently treating it as
if it were the same kind of reading as the primary one.

**Found, verified before writing any code**: the orange text is not real
(selectable) PDF text — `page.extract_words(extra_attrs=['non_stroking_
color'])` on the real file returns only black/red/green, no orange at
all — so, like every other dimension/CFM label on this drawing, it's
SHX-stroke geometry only OCR ever reads, and OCR gives back no colour of
its own. Sampled pixel colour directly off the rendered page at each
label's own position instead: every real orange reading landed at
`(255, 163-198, 72-142)`; every real black/grey one (including ones
contaminated by a nearby coloured gridline bleeding into the sample
radius) stayed within ~30 of R==G==B — a wide, confirmed margin, not a
guessed threshold.

**Shipped, `hvac_takeoff/hvac_takeoff.py`:**
  - `_is_secondary_duct_pixel(r, g, b)` — the pure threshold check
    (`r > 200 and r - b > 80 and g > b`), pulled out on its own so it's
    testable without rendering a page.
  - `_classify_duct_label_colors(pdf_path, pi, labels, dpi=150)` — for
    every `size`/`cfm` label on a page, samples a small patch of the
    rendered page at that label's position and tags it
    `is_secondary_duct_color: bool`. Called once per page in `extract()`,
    right after OCR.
  - `result["unresolved_duct_labels"]` (new, always present) — every
    label flagged secondary, pulled out with its page/position/text.
    `cfm_label_counts` now excludes them instead of silently folding
    them in with the primary readings. A new warning fires when any are
    found, naming the count and the open question plainly, and
    `summary_text()` gets its own "UNRESOLVED — SECOND DUCT SYSTEM"
    section so it's visible without reading the raw JSON.
  - **Verified against the real drawing, not just logic**: ran the real
    extraction — 36 labels correctly pulled into `unresolved_duct_labels`
    (every room's orange "36"x8"/600cfm"-style pair), `cfm_label_counts`
    left holding only the primary black readings. Rendered an overlay
    marking every surviving primary label green and every pulled-out
    secondary label blue directly on the actual drawing — checked by eye
    across every room in the crop: zero misclassifications either way.
  - 3 new tests,
    `test_hvac_takeoff.py::TheSecondDuctSystemIsDetectedByItsInkColorNotGuessed`
    — the real orange pixel samples from this file all flag secondary;
    the real black/grey samples, including the gridline-contaminated
    ones, all stay unflagged; a pure-green outlier (one odd OCR read
    during testing) isn't mistaken for orange. 18/18 across the whole
    file.

This closes every item on the original reverse-engineering list (#1-#4).
What's left is exactly what was always meant to be left: the orange
labels' actual meaning is a question for the client, surfaced plainly in
`unresolved_duct_labels` and the warnings, never guessed.

## 22. "Make my BOQ" itself has no live progress window — only recheck/follow-up do

Noted 2026-10-24, from the owner, not yet implemented. **Not a new ask —
a gap in item 2's original scope**, caught now that a real multi-stage
run was watched end to end.

**What the owner reported:** pressing "Make my BOQ" gives no live window
at all — no "research agent, then write-up agent" status, no Skip / Use
fallback / Stop. Item 2 built exactly that window (`BoqRunDialog`) and
item 7 made it reused across jobs instead of rebuilt — but, as item 2's
own write-up said plainly at the time, "the very first 'Write' call
(`_write()`) is untouched — no live window, no fallback chain — a
deliberate boundary, not an oversight." That boundary is what the owner
is now asking to remove.

**Why it matters more today than when that boundary was drawn:** a
derived BOQ (the "allow design-stage estimates" path, item 3's
`allow_derived`) is genuinely two AI stages back to back — the
`self.researcher` standards lookup (`_pm.standards_prompt`, a plain
`AutomationWorker` with no dialog, just a `_set_busy` text) THEN
`_write()` (same: a `_set_busy` text, no dialog, no fallback chain,
no Skip/Stop). Both run completely blind compared to recheck/follow-up.

**Fixed, 25 Oct 2026, `addons/boq/dialog.py`.** Both open questions
resolved the same way item 7 already set the precedent for: ONE window,
reused everywhere.
  - `_run_stage(stage, agent, prompt, files, on_success, worker_kwargs=None)`
    — the same live-window + fallback-chain shape as `_start_followup_run`,
    its own small `_rs_*` state (never shared with `_fu_*`, so neither
    flow can read the other's token/chain/stopped/skipped flags), but
    the SAME `self._fu_dialog` instance — created once, by whichever flow
    runs first, `restart()` on every call after that, exactly like item 7.
    `on_success` is `_on_standards`/`_on_interpreted`/`_on_written`
    unchanged — each already expects exactly the `(responses, links)`
    shape a plain `AutomationWorker.done` signal gives it, so none of
    them needed to change at all.
  - **The signal-sharing problem, solved once, not per-flow:** reusing one
    `BoqRunDialog` across two independent flows means its three signals
    (`skip_requested`/`fallback_requested`/`stop_requested`) can only be
    connected ONCE, at first construction — connecting them a second time
    for the second flow would fire BOTH flows' handlers on every click.
    Fixed with a thin dispatcher (`_rundlg_on_skip`/`_fallback`/`_stop`)
    that checks `self._active_runner` ("fu" or "rs", set right before
    either flow starts a stage) and calls the matching flow's own
    handler — `_start_followup_run` and `_run_stage` both connect to the
    dispatchers now, never directly to `_fu_on_*`/`_rs_on_*`.
  - **`FALLBACK_ORDER` applies to all three initial stages** (standards,
    interpret, format) the same way it already does for recheck/followup
    — the owner's own fallback instruction was phrased generally ("when
    those errors occur"), not scoped to write-up only, and `_run_stage`
    is stage-agnostic by construction, so this needed no special-casing.
  - **A fallback answering instead of the originally-picked agent is
    tracked correctly** — `_on_standards`/`_on_interpreted`/`_on_written`
    read `self.researcher`/`self.interpreter`/`self.writer_agent` for
    `_stage_agents_map` and resume-chat tracking; `_rs_on_done` sets
    whichever of those three actually answered, the same way
    `_fu_start_next` already does via `self._followup_agent`.
  - Groq's own direct-API branch in `_write()` is untouched — no browser
    page, so no live window, exactly as already established for
    follow-ups.

Tests: `tests/test_boq_dialog.py::
TheInitialRunNowHasTheSameLiveWindowAndFallbackChain` (6 tests — a plain
run with no research shows the window on the format stage; a research
stage shows "standards" first then reuses the SAME window, restarted, for
"format"; the format stage's own wait floor (item 23, see below); a
failure falls back to the next `FALLBACK_ORDER` agent; Skip/Stop route to
`_rs_skipped`/`_rs_stopped`, never the follow-up flow's own flags; a
completed initial run followed by a real follow-up call reuses the SAME
window instance a second time, now driven by the follow-up flow). Full
BOQ suite (`test_boq_dialog.py`, `test_boq_run_dialog.py`,
`test_boq_file_guardrail.py`, `test_boq_pricing.py`,
`test_double_line_ducts.py`, `test_site_facts.py`) green.

## 23. Wait time before "stopped answering" is too short for Kimi, Grok, Gemini — tuned around Claude's speed

Noted 2026-10-24, from the owner: "the timeline for kimi, grok, gemini,
etc is very low, they take more time than claude so the time of answer
should be increased for all the agents who are writing it up." Not yet
implemented.

**What exists today**, from item 6: `AutomationWorker` takes a raw
`min_wait` floor, applied PER STAGE — BOQ's `recheck` gets a 20-minute
floor, a plain `followup` gets `automation.FOLLOWUP_MIN_WAIT` (8
minutes) — but this is the same floor regardless of WHICH agent is
answering. The very first "Make my BOQ" write-up stage has no raised
floor at all; it uses the engine's own generic, shorter default wait.

**The gap**: nothing here is PER-AGENT. Claude finishes quickly; the
owner's report is that Kimi/Grok/Gemini genuinely take longer on the
same job and the current wait logic — tuned, as far as any of this was
ever tuned, around Claude's own pace — cuts them off or reads them as
"stopped growing" before they're actually done.

**Investigated, 25 Oct 2026 — a real per-agent mechanism already exists,
and checking it changed the diagnosis.** `core/automation.py`'s
`_smart_wait()` (the "text stopped growing" wait) is given a `cap` =
`max(agent_cfg["wait_time"], min_wait)` — ALREADY per-agent, from each
tool's own registry entry (`core/agents.py`'s `_agent(..., wait, ...)`,
scaled ×2 and clamped to 300-1800s). The computed `wait_time` per writer
agent, checked directly: **Claude 600s, Kimi 2.6 1000s, DeepSeek 360s,
ChatGPT/Grok/Gemini 300s each.** So Kimi was never the problem — it
already has the HIGHEST floor of the six. Grok, Gemini and ChatGPT were
the real gap: all three sit BELOW Claude's own 600s, confirming the
owner's actual observation for those three, not the literal "Kimi" name.

**The bigger gap, found verifying this — item 22 exposed it directly:**
before today, "Make my BOQ"'s research/interpret/write stages never
passed `followup=True` or any `min_wait` at all — LESS floor than even a
plain follow-up already gets (`FOLLOWUP_MIN_WAIT`, 480s). Writing a full
BOQ is exactly the "redoes a whole deliverable" case that floor exists
for; it was simply never wired to these three stages.

**Fixed, `addons/boq/dialog.py`'s `_rs_start_next()`** (the same method
item 22 built): every initial-pipeline stage now passes `followup=True`
(480s floor, same as any follow-up) and the "format" stage gets a
900s floor on top — a full written BOQ is typically the longest of the
three. A ceiling only, per `_smart_wait()`'s own design — the wait still
ends the moment an agent's answer actually stabilises, so this costs a
fast agent (Claude) nothing; it only helps an agent that was genuinely
still working past its own shorter default.

**Not done, and deliberately not guessed at:** whether Claude's 600s /
Kimi's 1000s / DeepSeek's 360s base estimates are themselves still
accurate for a BOQ-length job specifically (as opposed to the
registry's original everyday-chat-reply estimates) — the 480s/900s
floors added here lift every agent to at least that level regardless,
which covers the owner's report either way; retuning the base per-agent
`wait` values in `core/agents.py` would affect every add-on that uses
these agents, not just BOQ, and needs its own real-run evidence before
touching shared, cross-add-on config on a guess.

Tests: `tests/test_boq_dialog.py::
TheInitialRunNowHasTheSameLiveWindowAndFallbackChain::
test_the_format_stage_gets_a_raised_wait_floor_not_just_claudes_own_pace`.

## 24. The writer dropdown still has the old, unpruned list, and the fallback chain isn't actually working

Noted 2026-10-24, from the owner: "the fallbacks are not working and
though I told you just to keep claude, grok, kimi, deepseek, gemini,
chatgpt ONLY, in the dropdown list for write it up agent." Not yet
implemented. Two separate problems, found together:

**24a. `WRITER` was never actually pruned.** Item 3 (2026-10-21)
documented the intended replacement list — "Groq-inhouse, Claude,
ChatGPT, Gemini, Kimi, Grok, DeepSeek", dropping Perplexity, LAZYCOOK,
Jasper, Copy.ai, Writesonic — and only checked off that stage-one
(Groq-inhouse producing text) already worked; the actual list edit was
never marked done, and checking `addons/boq/agents.py` directly today
confirms it: `WRITER` is still
`["Perplexity", "ChatGPT", "Claude", "Groq", "Grok", "DeepSeek", "Gemini",
"LAZYCOOK", "Jasper", "Copy.ai", "Kimi 2.6", "Writesonic"]` — the full
original twelve, untouched. Item 3's own write-up described the intended
list without anyone actually making the edit.

**The discrepancy above is resolved, 2026-10-24, same day:** asked the
owner directly rather than guessing — Groq-inhouse is OUT. The final
`WRITER` list is exactly the six named: Claude, Grok, Kimi, DeepSeek,
Gemini, ChatGPT. Item 3's original seven-agent list (which had
Groq-inhouse as entry one) is superseded by this instruction where the
two disagree.

**Done, 2026-10-25.** `addons/boq/agents.py`'s `WRITER` is now exactly
`["Claude", "Grok", "Kimi 2.6", "DeepSeek", "Gemini", "ChatGPT"]`.
Pruning it left Groq's own special-cased code in `addons/boq/dialog.py`
unreachable — a non-editable `QComboBox` silently no-ops on
`setCurrentText("Groq")` once "Groq" isn't a populated option, so none
of the Groq guards could ever fire again. Asked the owner whether to
keep that dead code (and just patch the 3 tests that exercised it via
the dropdown) or remove it outright; the owner chose full removal.
Deleted: `addons/boq/workers.py` (`BoqGroqWorker`, a direct
`core.router.groq_chat` call — nothing else imported it), every
`writer_agent == "Groq"` / `writer_combo.currentText() == "Groq"` guard
in `_run()`, `_write()`, `_ask_recheck()`, `_send_followup()` and the
"verify" quick action in `_offer_followup()`'s result handler, and the
`GroqInHouseIsADirectCallNotABrowserAgent` test class in
`tests/test_boq_dialog.py` (7 tests, all exercising code that no longer
exists). Also dropped the now-dead `groq_worker.assert_not_called()`
mock patches from the Grok/DeepSeek/Gemini "goes through
AutomationWorker" tests and the `test_a_format_request_is_never_sent_to_
groq` test, and re-ran `devtools/extract_strings.py` to retire the 5
Groq-only warning strings from `lang/_catalogue.json`. Full
`tests/test_boq_dialog.py` run green afterwards (113 tests).

**24b. The fallback chain itself is reported broken**, separately from
the list-pruning gap. The owner's own live test (2026-10-24) pinned it
down: ran DeepSeek as writer, chose "Use fallback" mid-run to Claude,
and the prompt the engine actually sent to Claude (pasted by the
owner) carried two different, disagreeing format requests in one
message — one line asking for CSV, another asking for docx — plus the
measured figures appearing twice. Not the fallback MACHINERY itself
(`_fallback_chain()`/`_start_followup_run()`, re-checked against this
transcript and found to still do exactly what its tests say: pop the
next agent, re-send the same prompt in a fresh chat). The real bug was
in what that prompt contained:

  1. **Two independent systems decide the file format, and they can
     disagree.** `addons/boq/dialog.py`'s own `_format_request_line()`
     reads `self.format_combo` — a UI dropdown that still held
     whatever was chosen on an EARLIER run (here, CSV). Separately,
     `prism_terminal/core/contract.py`'s engine-side system
     (`wants_file()`/`wanted_ext()`) independently scans the full,
     free-text prompt for a format — and the owner's own follow-up
     note that day asked for docx in plain words. Both fired into the
     same message: the picker's stale CSV line, and the engine's own
     docx instruction built from the note's own wording, side by side,
     contradicting each other. **Fixed:** `_format_request_line()` now
     takes the free text the person actually typed (the ask box's text
     for a fresh write-up, the follow-up note otherwise) and returns ""
     — skips the picker's line entirely — whenever that text already
     asks for a format or a download in its own words (checked with
     `CB.contract.wants_file()`, the exact same scan the engine itself
     uses downstream, so the two can no longer disagree: there is now
     only ever one source of the format request, whichever one the
     person's own words already triggered). The picker still drives
     the request when the person's own text says nothing about
     format — its job for every run that doesn't type one.
  2. **The previous answer was only ever pasted as text**, never
     attached as the real file produced for it (`self._deliverable_path`,
     already tracked since item 4). Asking a tool to "remake" a
     document from a paragraph of pasted text is a weaker instruction
     than handing it the actual file to open. **Fixed:** `_send_followup()`
     now attaches `self._deliverable_path` (when it exists on disk) to
     the follow-up's file list, alongside — not instead of — the pasted
     text (some agents cannot read an attached file at all, so the text
     stays as their only copy; a missing/deleted deliverable is simply
     skipped, never an error).

3 new tests in `tests/test_boq_dialog.py`'s
`AFollowUpOrVerifyActuallyProducesAndSurfacesAFile` class: the stale
picker vs. typed-format conflict is gone, the previous deliverable is
attached alongside its text, a deleted deliverable is silently skipped
rather than raising. Full `tests/test_boq_dialog.py` run green
afterwards (116 tests).

## 25. A real BOQ run compared against the PDF by a second AI — one real finding, several claims checked and most of them wrong

Noted 2026-10-24, from the owner: ran the hvac_takeoff measurements
through Prism's BOQ add-on with Grok as the writer, then had a separate
Claude session compare the result against the PDF directly and list
differences. The owner shared that session's write-up
(`HVAC_BOQ_TEST/BOQ Pipeline Fixes Instructions for Claude Code.md`) and
asked for it to be looked into carefully, not copied in as-is. It wasn't
— that session had no access to this tool's actual geometry, so its
claims were checked against the real PDF before anything below was
written down. Most did not hold up; one real, verified finding did.

**25a. The run used stale input — explains most of the complaint.** The
measurements fed to Grok that day
(`boq_external_measurements_1792836724.txt`) predate essentially every
fix in items 19-21: no dedup, no equipment parsing, diffuser/flex
_connector/volume_damper measured as fake duct lengths instead of real
shape counts. Already covered in this file's own run log — not
re-documented here, just named as the real cause behind points 1, 2 and
4 of "Why the current BOQ came out worse" in the shared doc (junk rows
copied straight in, no sanity check on the fake 628 ft/314-run flex
figure, bare TR tags never becoming equipment). A re-run with the
current, fixed measurement text is needed before judging the writer on
this again.

**25b. One real, verified finding: a genuine unmapped symbol sits where
the "second duct system" labels are** — the shared doc's claim that this
is a return-air network, checked directly against the PDF rather than
taken on its word. A layer nobody had looked at before,
`#ffbf7f@1.44:poly` (tan ink, 41 raw segments), groups into **13 small
bracket-shaped symbols** (3 segments each, one stray partial 14th),
positioned at the SAME spot as 13 of the "unresolved" orange size/CFM
labels from item 21 — each one sitting on the corridor's duct riser next
to a "TT" mark. This is a real, repeating, countable shape — the
"second duct system" is not just floating text, it has its own symbol
and its own duct connection point.

**What is NOT confirmed, said plainly rather than guessed:** what "TT"
stands for, and whether this bracket symbol is actually a return grille,
a transfer-duct tap, or something else — no legend on this sheet names
it, OCR did not catch "TT" as text (it may be drawn geometry, not a
label), and nothing here resolves that. The count is 13, not the shared
doc's "33" — that number came from a session with no access to the raw
PDF geometry, not a real count. If this bracket turns out to be worth
counting as its own symbol role (same technique as item 20's
`count_symbol_rects`), that's future work, pending someone confirming
what it actually is — not something to guess into the code now.

**25c. Checked and found wrong: "67 vs 4" flex connectors.** The shared
doc's sanity-check argument ("67 flex connectors can't exceed 40
diffusers") is not a real constraint — nothing requires a 1:1 cap — and
item 20 already verified the 67 figure by exact raw-geometry accounting
(134 raw rects, every single one a clean pair of an 18×18 outer rect and
a 5.4×18 inner rect, 134÷2 = 67 exactly, zero rects left over) plus a
direct visual check showing each one sitting beside a real diffuser on
the rendered drawing. The "4" figure in the shared doc has no such
backing. Not acted on.

**25d. Checked, not found: "6 linear diffusers."** Scanned every layer
on the page (`scan_layers()`) looking for anything matching a linear
/slot-diffuser shape beyond the three already-mapped symbols (item 20)
and the bracket in 25b — nothing else repeats at a count near 6 or looks
like a linear slot. Not acted on; flagged here only so it isn't silently
dropped if real evidence for it turns up later.

**25e. The junk "x?" DUCT SUMMARY rows — diagnosed, not just a lead
anymore.** `layer_map.json` maps THREE layers to `return`:
`#ff0000@1.08:line`, `#808080@0:poly`, `#ff00ff@0.72:poly`. Measured each
in isolation to see what each one actually contributes:

| layer | runs | length | what it actually is (rendered alone, checked by eye) |
|---|---|---|---|
| `#ff0000@1.08:line` | 28 | 287.1 ft | the real return-air riser — carries its own "RETURN AIR DUCT" text label next to it on the drawing |
| `#808080@0:poly` | 105 | 857.6 ft | **not ductwork at all** — the building's own perimeter wall rails and window/mullion marks, running the full height of both sides of the plan |
| `#ff00ff@0.72:poly` | 0 | 0.0 ft | sprinkler-head-style diamond point markers + a hatched area — contributes nothing numerically, but is still the wrong kind of geometry to have mapped here |

So roughly two-thirds of the reported 1,313.5 ft "return" total, and
most of the junk `9x?`/`4x?`/`7x?`/`8x?` rows, come from `#808080@0:poly`
being mapped to `return` when it is the building's own wall outline, not
ductwork — confirmed by rendering that one layer alone and recognising
it immediately as the perimeter, not a duct network. This is the same
shape of bug item 11 found and fixed for double-line ducts (wrong
geometry read as if it were duct, just a mapping error here rather than
a measuring-rule gap).

**Fixed, 2026-10-24, same day.** `hvac_takeoff/layer_map.json`:
`#808080@0:poly` and `#ff00ff@0.72:poly` changed from `return` to
`ignore`; `#ff0000@1.08:line` (the one genuinely labelled "RETURN AIR
DUCT" on the drawing) is the only layer left mapped to `return`.
Re-ran the real extraction to verify, not just logic:

| | before | after |
|---|---|---|
| return runs | 176 | 45 |
| return total | 1,313.5 ft | **287.1 ft** |
| supply total | 478.1 ft | 477.8 ft (unchanged, as expected) |
| label match rate | 27% | **43%** — the "few runs matched a size label" warning is now gone entirely |

Full test suite re-run clean (18/18) — none of today's tests touch
`layer_map.json` directly, so none needed changing; only the real-file
numbers moved, in the direction the evidence said they should.

**25h. Supply "?" sizes (~249 ft, 79 of 120 runs unlabeled) — checked,
not an OCR miss.** The unlabeled runs' widths (6″ through 48″) are
ordinary values this file labels plenty of elsewhere — the gap is
`split_by_labels()`'s distance match (`match_ft=8`, i.e. a label must be
within 8 ft of the run to attach), not a failure to read a label. This
drawing labels a branch duct once, near its start, the normal CAD
convention; later segments of the same run, past 8 ft from that label,
correctly show no match rather than guessing. Not a bug, a known
radius limit already implied by the tool's own `match_ft` parameter.

**25i. Hi-Wall ×1/×2 — confirmed NOT a duplicate read.** Checked the two
equipment entries' own positions: (93.79 ft, 162.46 ft) and (69.37 ft,
166.1 ft) — about 24 ft apart, matching the two physically separate
Hi-Wall notes already confirmed by eye when item 19 was built. Dedup
is working correctly here; these are two real notes, not one read twice.

**25j. 17 TR tags — confirmed, do NOT become equipment today.**
Checked `_equipment_from_labels()` directly: it only processes labels of
`kind == "equipment"`, which `parse_label()` only ever produces from an
HIWALL_RE match ("<N>TR HI-WALL"). A bare "17 TR" tag stays in
`tr_labels` only. Whether a rooftop unit's own "<N> TR" tag (no
"HI-WALL" suffix) should also become an equipment entry is a reasonable
future enhancement, not yet decided or built — noted here, not assumed.

**25k. Terminals/diffuser layer purity — checked, clean.** All 120 raw
rects on `#00ffff@0.84:rect` (the diffuser layer) group into exactly 40
clean triples of the same three sizes (13.56/9.0/4.44pt) — no outlier
sizes suggesting a different symbol (e.g. a return grille) sharing that
layer. Zero linear-slot-shaped rectangles found anywhere on the page
(same check as 25d). The 13-count bracket symbol (25b) stays
"unidentified repeating symbol," per the shared doc's own latest
position — no legend names it, and the count (13) and the orange
size/CFM labels nearby are the only evidence either of us has.

**25f. The shared doc's main recommendation — "let the writer clean junk
rows, merge reversed sizes, run consistency checks" — conflicts with
this project's own rule, not adopted.** `core/boq.py`'s whole design,
stated in its own docstring and HVAC_DRAWING_RULES.md, is that measured
figures are ground truth the writer never recalculates; cleaning bad
rows by prompt would mean an AI silently deciding which measured numbers
to trust, the opposite of that rule. The right fix for junk rows is
25e — fix the MEASURING tool so it doesn't produce them — not a prompt
instruction asking the writer to guess which ones are real. The shared
doc's OWN point 3 agrees: "the measuring tool itself... real faults a
prompt can't fix."

**25g. Context transfer from the research agent — tied to item 22, not
a separate bug.** Checked `_on_standards`/`_write()` directly:
`self._standards` IS set from the research stage's response and IS
embedded in the write-up prompt as a labelled "DESIGN STANDARDS BRIEF
from the research stage" block — the mechanism is correct in code. What
could not be confirmed from the pasted Grok prompt (cut off before that
point) is whether a DESIGN STANDARDS BRIEF block was actually present,
or whether the research stage even ran for that job — and because item
22's live window doesn't exist yet, there's no way to SEE whether
research ran, succeeded, or came back empty. Needs reproducing with item
22's window in place (or a manual check of `self._standards` mid-run)
before concluding the transfer itself is broken, rather than the
visibility into it.

## 26. The HVAC PDF-takeoff window must only appear for HVAC — BOQ is going multi-industry

Noted 2026-10-26, from the owner: BOQ is being built to serve multiple
industries, not just HVAC. The `hvac_takeoff/` PDF extractor (OCR a
duct-layout PDF into measured quantities) is HVAC-specific, so its
"upload a PDF" window must only pop up when the person's own request
names the HVAC industry — the same way `HVAC_DRAWING_RULES.md`'s
write-up guidance is already gated (item 12): `self._hvac = "hvac" in
self.ask.text().lower()` in `addons/boq/dialog.py`. Not implemented yet
— `hvac_takeoff/` today is a standalone script/CLI tool
(`hvac_takeoff/hvac_takeoff.py`), not wired into `addons/boq/dialog.py`
at all (confirmed by grep: nothing outside `hvac_takeoff/` itself
imports it). This item is to wire it in gated from the start, not to
un-gate something already shipped open to every industry.

**Three ways to do the gating, simplest first:**

1. **Reuse the existing typed-keyword gate.** Same check BOQ already
   uses for `self._hvac` — if the word "HVAC" appears in the request
   text box, show the PDF-takeoff button/window; otherwise hide it.
   Zero new UI, consistent with item 12's precedent, but it depends on
   the person typing that exact word, and a typo or a phrase like
   "ducting job" would miss it.
2. **An explicit "Industry/Trade" picker** (a small dropdown next to
   the request box: HVAC, Electrical, Plumbing, General, …) instead of
   reading free text. More reliable than guessing from wording — no
   missed matches, no false positives — and it is also where any
   FUTURE trade-specific tool (not just HVAC's) would plug in without
   inventing a new keyword each time. Costs one new control and a
   choice of what the other industries are called.
3. **Keep one generic "Input measurements" window** (it already exists
   — `InputMeasurementsDialog`, paste-or-upload, any file) **and run
   the HVAC PDF extractor only behind it**, automatically, when the
   uploaded file is a PDF and the request text says HVAC — no second,
   HVAC-only button at all. Fewer controls on screen, but the
   HVAC-specific step becomes invisible machinery behind a generic
   button, which can be confusing if it silently does nothing for a
   non-HVAC PDF.

**Decided, 2026-10-26 — option 2, the Industry dropdown, and not just
for showing/hiding a button.** Option 3 (guess the industry from the
uploaded PDF itself) was ruled out with a concrete counter-example: a
pharma-tech company uploads a PDF and the system could wrongly read it
as an HVAC duct drawing and run HVAC's OCR + rules on it anyway, since
nothing told it otherwise. The dropdown fixes this by making the
industry an explicit choice, never a guess from file content — and its
job is bigger than gating one button: **it must pick which whole
rule-set/OCR profile runs**, not only whether the HVAC one shows up.
A company doing ELV/CCTV/fibre-link work (a different example given:
Raj Infotech) needs its OWN extraction rules for its own drawings, the
same way HVAC has `hvac_takeoff/` and `HVAC_DRAWING_RULES.md` today —
so each industry on the dropdown is a separate, pluggable rule-set
(its own OCR reading rules + its own write-up guidance), selected by
the dropdown, never mixed with another industry's. Still to design:
how each industry's rule-set plugs in without `addons/boq/` having to
hardcode a growing if/elif per industry — likely one small
registry/lookup (industry key → its extractor + its guidance), mirroring
how `addons/registry.py` already keys add-ons, so adding a new
industry later is "add one entry," not "edit BOQ's core logic." Not
built yet — this is the shape to build toward, not code.

**Extended, 2026-10-26 (same conversation) — every targeted industry
gets its own rule-set, and the per-industry flow has three parts, not
one.** Confirmed: this is not just HVAC vs. everyone-else. ELV, CCTV,
fibre-link, pharma-tech, and any other industry Prism targets each
need their OWN rules — OCR/extraction AND write-up — the same way HVAC
does today, not a generic "non-HVAC" fallback bucket. Looking at
`hvac_takeoff/hvac_takeoff.py`'s own existing (standalone, Tkinter)
tool, its flow already has the right shape and should carry over into
every industry's rule-set, not just HVAC's:

1. **A calibration/preview step** (`hvac_takeoff.py`'s own "Step 1 -
   set what each line colour is (Preview to check)" — confirming what
   each drawing layer/line-colour means before extraction runs). Every
   industry's PDF-reading rules will need some version of this, since
   each trade's drawings use their own layer/colour/symbol
   conventions. In Prism's UI this must stay **compacted** — folded
   away, only shown once the person opens the industry dropdown's own
   section — never shown by default. Reason given: showing this much
   detail up front clutters Prism's main screen for the common case
   (someone who doesn't need to touch it).
2. **Extraction itself** (`hvac_takeoff.py`'s "Step 2 - Extract"),
   using whichever industry's rule-set was picked.
3. **A measurements review step**, shown after extraction, before
   "Make my BOQ" can be pressed:
   - Each measured value **colour-coded by how accurate/confident it
     is** — reusing the trust-colour pattern already built for
     `MeasuredTable` (item 13/16, green = nothing flagged it, yellow =
     a rule touched it and is worth a look) rather than inventing a
     new colour scheme per industry.
   - Every value in that table **must stay manually editable** — the
     person can correct a measured figure by hand before it ever goes
     into the BOQ prompt, same as `MeasuredTable` already allows today.

So the shape per industry is: its own rule-set (OCR + write-up) → its
own compacted calibration step → a shared, colour-coded, editable
measurements review → "Make my BOQ." Still not built — this is the
requirement, recorded for when this is implemented.

**Done, 2026-10-26.** Built to the shape above:

- `addons/boq/industries.py` (new) — the registry. `NAMES` ("General"
  first, then "HVAC"), `has_takeoff()`, and thin dispatchers
  (`scan_layers`, `extract`, `summary_text`) that call into
  `hvac_takeoff/hvac_takeoff.py` for HVAC and raise `ValueError` for any
  industry with no rule-set yet — never a silent fallback to HVAC's own
  rules for a drawing that was never one. `hvac_takeoff` itself is
  imported lazily (`_hvac()`), so opening BOQ for a non-HVAC job never
  pulls in pdfplumber/pypdfium2/rapidocr just to show the dropdown.
- `addons/boq/dialog.py` — an **Industry** dropdown next to the Write
  with/Research with/File format row (`self.industry_combo`,
  `industries.NAMES`, default "General"). `self._hvac` — read at both
  the places it already was (`_measure()`, `_use_external_measurements()`)
  — now comes from this dropdown, **not** from `"hvac" in
  self.ask.text().lower()` as it did until today: BOQ now targets more
  than one industry, and a typed phrase like "ducting job" that never
  says the word "HVAC" used to miss the old gate silently; an explicit
  choice cannot. A new **"HVAC PDF takeoff…"** button sits beside
  "Input measurements…", shown only when `industries.has_takeoff()` says
  the picked industry has one (`_on_industry_changed`).
- `addons/boq/takeoff.py` (new) — `IndustryTakeoffDialog`, the compact
  3-part flow: pick a PDF + drawing scale + OCR toggle; a **Step 1**
  layer-mapping section (colour swatch, segment/length info, a Role
  combo per layer, from `industries.roles()`) folded away behind a
  toggle button and hidden until a PDF is picked, so opening BOQ never
  shows it by default; an **Extract** button (runs
  `addons/boq/workers.py`'s new `HvacTakeoffWorker`, off the GUI thread,
  per rule 4); and a review table (`_ReviewTable`, reusing
  `measured.py`'s own `_TintDelegate` — the same real-stylesheet-safe
  paint path item 16/pricing.py's fix already established) of every
  OCR-read label (size/CFM/TR/room), green at ≥0.6 confidence and yellow
  below it — hvac_takeoff's own existing "unread" cutoff, not a new
  invented threshold. "Use these measurements" hands the plain-text
  summary back to `BoqDialog._use_external_measurements`, unchanged —
  the takeoff dialog needed zero changes there.
- **Edits actually reach the numbers, not just the screen.** A TR or CFM
  row's text is editable (a duct-run's own length is exact vector
  geometry, conf 1.0 always, nothing to second-guess, so it is not in
  this table and not editable here; a "size" label is shown but not
  editable either, since splitting it back into the duct geometry it was
  paired with would need re-running the pairing pass, not a one-line
  reparse). An edit is re-parsed through hvac_takeoff's own
  `parse_label()` (never a second, drifting regex) and
  `industries._recompute_aggregates()` mirrors `extract()`'s own
  `tr_labels`/`cfm_label_counts` one-liners exactly, so a corrected "8
  TR" misread as "3 TR" shows up in `summary_text()`'s own printed
  numbers, not only in the table.
- `requirements.txt` + `packaging/prism.spec` — added `pdfplumber` and
  `pypdfium2` (pillow and rapidocr-onnxruntime were already required for
  core/ocr.py and Reel), plus a guarded `collect_data_files("pypdfium2")`
  in the spec, the same defensive pattern already used for
  rapidocr_onnxruntime, since pypdfium2 loads its own compiled binary by
  a path read from its data files rather than something PyInstaller's
  static analysis would otherwise find on its own.
- Tests: `tests/test_boq_industries.py` (new, 16 tests — the registry's
  dispatch/error behaviour and, specifically, that an edited reading's
  correction reaches `tr_labels`/`cfm_label_counts`, not only the row
  shown). `tests/test_boq_dialog.py` — the old
  `TheHvacFlagComesOnlyFromTheAskBox` class, whose own docstring named
  the ask-box-text rule this item just replaced, is renamed
  `TheHvacFlagComesOnlyFromTheIndustryDropdown` and rewritten to match
  (per CLAUDE.md rule 8: the guard test changed in this same commit,
  with the reason stated in its own docstring, not deleted); two
  `ExternalMeasurementsAreASecondWayIn` tests updated the same way; a new
  `TheIndustryDropdownGatesThePdfTakeoffButton` class covers the button's
  own visibility and both dialog outcomes (accepted/declined). Full
  `tests/test_boq_dialog.py` + `tests/test_boq_pricing.py` +
  `tests/test_boq_industries.py` run green together, and
  `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python3 main.py` still
  reports every check green, BOQ's own line included.
- **Not done, flagged honestly rather than assumed:** a real PDF was not
  run through the embedded dialog end-to-end in this session (no sample
  file was attached to it the way `hvac_takeoff/sample_ASPENTECH/` was
  used standalone) — the wiring is tested at the unit level
  (`industries.py`, the dropdown/button, the edit-and-recompute path),
  not proven yet against a real tender PDF inside Prism's own window.
  Also unverified: whether `hvac_takeoff/`'s lack of an `__init__.py`
  (an implicit namespace package, fine running from source) survives a
  real PyInstaller freeze the way the guarded `collect_data_files` call
  above was written to help with — no packaged build was actually run
  to check. Only "HVAC" has a real rule-set; ELV/CCTV/fibre-link/
  pharma-tech etc. each still need their own entry in
  `addons/boq/industries.py` before they can appear in the dropdown at
  all — not attempted here, since none of their actual reading rules
  exist yet to encode.
- **A real gap, found 27 Oct 2026, when asked directly "will the OCR
  model actually be installed when someone pulls this": `requirements.txt`
  was missing `rapidocr` entirely.** `hvac_takeoff.py` imports
  `from rapidocr import RapidOCR` -- a genuinely separate PyPI package
  from `rapidocr-onnxruntime` (already required, for `core/ocr.py`),
  different versioning (3.x vs 1.x), neither depends on the other. The
  first write-up of this section's `requirements.txt` entry assumed the
  existing `rapidocr-onnxruntime` line covered it; it does not. Fixed
  now: `rapidocr>=3.10` added, plus a matching guarded
  `collect_data_files("rapidocr")` in `packaging/prism.spec`.
  **Still open, and NOT something a requirements.txt line can fix:** the
  `rapidocr` package does not ship its ~30MB of model weights (PP-OCRv6
  det/rec "small" + a text-angle classifier) in the wheel at all --
  `rapidocr/download_file.py` fetches them from `modelscope.cn`,
  SHA256-verified, the first time `RapidOCR()` actually runs. A fresh
  `pip install -r requirements.txt` gets the PACKAGE; the actual model
  weights only arrive on the first real OCR call, and need network
  access to do it. A frozen/offline build has no good answer here yet --
  bundling a pre-downloaded models/ directory into the build, or
  documenting the first-run network requirement, neither attempted.

## 27. A third ground-truth source for the same real file — the client's own field measurement sheet, three-way compared, root causes graded by evidence

Noted 2026-10-28: the client uploaded `clientsent_quantity_measurements.xls`
into `HVAC_BOQ_TEST/` — the same real file as items 11-25 above
(`FINAL LAYOUT-Model.pdf`), but this time the ground truth comes from the
client's own site measurement/billing sheet, not a second AI's read of the
drawing. Its `Comparison` tab is literally the earlier Claude-written BOQ
pasted back with the client's own `Actual Quantity` column filled in
against it, item by item — the first time this file's ground truth comes
from someone who actually counted the real terminals and dampers on site.

This item is the analysis step only — **27a-27e below are evidence, not
changes.** Nothing in `hvac_takeoff.py` or `industries.py` was changed yet.
The 5 numbered items under "Actual changes to make" near the end of this
section are the real to-do list this analysis produced; each one still
needs item 25's own process (real geometry, a named general convention, a
fix, a regression test) before it gets written up as a shipped rule the
way `HVAC_DRAWING_RULES.md` records one.

**27a. Three-way headline comparison (background numbers only, not a
change) — Prism's own BOQ output, my (Claude's)
independent PDF read, and the client's real counts.**

| item | Prism | Claude | client actual |
|---|---|---|---|
| 17 TR units | 2 | 2 | 2 |
| 2 TR Hi-wall units | 3 | 3 | 3 |
| Supply duct, 22G, sq.m | 38.15 | 50.87 | 55.90 |
| Supply duct, 24G, sq.m | 81.32 | 96.38 | 187.57 |
| Return duct, 22G, sq.m | 39.15 | 33.04 | 17.02 |
| Return duct, 24G, sq.m | 146.36 | 175.01 | 204.38 |
| Supply insulation, sq.m | 119.47 | 147.25 | 243.47 |
| Return insulation, sq.m | 185.51 | 208.05 | 221.40 |
| Diffusers | 40 | 40 | 53 (40 SA + 13 RA) |
| 36"×8" return grilles | not quantified (folded into "second duct system, unresolved") | 13 | 13 |
| VCDs | 13 | 13 | 8 |

Accuracy (1 − Σ\|error\| ÷ Σactual, across the measurable rows above):
Prism vs client ≈ 62%; Prism vs Claude's own independent PDF read ≈ 75%.
Prism sits closer to a second AI's read of the drawing than to what was
actually installed on site — backwards from what the add-on needs to be
useful for pricing.

**27b. Diffusers (40 vs 53) — the shape geometry is clean, so this is
very unlikely to be a shape-recognition bug.** Item 25k already confirmed,
at the raw-rect level, that the diffuser layer (`#00ffff@0.84:rect`)
groups into *exactly* 40 clean triples with zero leftover geometry and no
outlier sizes suggesting a second symbol. The 13 "RA" diffusers the
client's own `SQ. DIFFUSER` schedule counts (40 SA + 13 RA = 53, same
225×225mm neck, "with attached damper") are not sitting undetected in
this page's own geometry — there is nothing there to find. Two
possibilities, not yet told apart: (1) this one PDF page is only part of
a larger drawing set and the 13 RA units are drawn on a page this tool
was never given, or (2) the schedule total (53) includes terminals this
sheet never draws individually, relying on the schedule as the sole
record of quantity. **Not something `count_symbol_rects` can fix by
itself** — needs the full drawing set, not just "page 1", to settle which.

**27c. VCDs (13 vs 8) — plausible but unverified: collar dampers may be
getting counted as VCDs.** The client's real count (8) ties every VCD to
the two 17 TR units' own main ducts (`VCD` sheet: tags "17TR UNIT-1"/
"-2"). The same client file's `Grill` sheet separately lists 7 grille tags
(G1-G7), several marked "with attached coller damper" — a different
fitting, mounted at a grille neck, that plausibly uses a visually similar
paired-square symbol to the one item 20 already keys VCDs off
(`#ff0000@1.08:rect`, outer+inner nested squares). **This has not been
checked against the real geometry yet** — the next step, before writing
any rule, is to look at where each of the 13 counted damper rects actually
sits: on a duct trunk (a real VCD) or beside/overlapping a diffuser/grille
symbol (a collar damper). Leading theory, not a confirmed cause.

**27d. Return grilles — the count that WAS right (13, confirmed, delta 0)
still isn't the full picture.** The client's own remark on this exact line
— "what about 36×6 & 24×6? mention type of grill" — points at the same
root cause as 25b's unidentified bracket symbol: this tool reads floating
size/CFM text near a duct run, never a **legend/schedule table**
(`schedules: []` in every `hvac_takeoff` output — the tool's own flag that
this category isn't extracted yet, not a finding specific to this file).
The client's own `Grill` sheet is exactly such a schedule (7 tags, sizes
in mm, a "with/without attached collar damper" column) and nothing in the
current pipeline has ever read a table shaped like that.

**27e. Ducting area gaps (24G supply undercounted by more than half; 22G
return overcounted by more than 2×) — most likely explained by what the
tool already tells you, not a new bug.** Two causes already visible in
the tool's own output, neither newly discovered here:
  - `checks.label_match_rate = 0.43` on this file — under half of the 165
    measured runs have a readable size label at all; the rest (75.98 m
    supply, 306.22 m return) sit in the part-sized/TBC bucket and
    contribute nothing to the firm area subtotal, by this tool's own
    documented design. 24G is exactly the smaller-size band where label
    density is thinnest, so a real quantity of 24G duct plausibly never
    reaches the "fully-sized" total at all.
  - `T.01` (the write-up's own flag): scale may be wrong. Return 22G is,
    in effect, a single data point (one 20"×30" run) — a category built
    from one run is exactly where one bad OCR/scale read swings the whole
    total, which fits an overcount on a single-member category better
    than a general rule bug.
  Neither cause is confirmed against the real geometry the way 25e's
  layer-mapping bug was — graded as "likely, from the tool's own
  evidence," not verified line-by-line. Next step, before writing a rule:
  re-run with a manually confirmed scale (one known dimension on the
  drawing, measured by hand) and see how much of the gap in both
  categories closes.

**Actual changes to make — the real to-do list from this analysis (none
built yet; this is what items 27b-27e above were gathering evidence for):**

  1. **Read legend/schedule tables off the drawing**, not just floating
     size/CFM text next to a duct run. `hvac_takeoff.py` currently never
     looks for a tag→size table (`schedules: []`, always empty, by the
     tool's own admission). Build this, then match tags drawn on the
     duct layout against it. Fixes the missing 36"×6" / 24"×6" grilles
     (27d), and may also fix the missing 13 RA diffusers (27b) if the
     full drawing set has a terminal schedule.
  2. **Stop counting grille-mounted collar dampers as VCDs.** Before
     `count_symbol_rects()` counts a paired-square damper shape as a VCD,
     check whether it sits on a duct trunk (a real VCD) or right next to
     a diffuser/grille symbol (a collar damper, a different line item).
     Fixes the 13-vs-8 VCD overcount (27c) — but first needs someone to
     actually look at where those 13 rects sit on the real drawing; this
     is still a theory, not a confirmed cause.
  3. **Let VCDs be billed by area (sq.m), not just by count.** Once a
     VCD's own width×height is read, compute and show its area as an
     alternative unit — this is literally how the client said they bill
     it, not a guess.
  4. **Put the tool's own warnings where an estimator will actually see
     them.** `checks.label_match_rate` (43% on this file) and any
     category whose firm total comes from a single measured run are
     currently buried in a JSON file, not in Prism's own review screen.
     Surface both as a loud, visible warning in the BOQ add-on's UI
     before "Make my BOQ" can be pressed — this is the single biggest
     fix for catching a bad duct-area total (27e) before it reaches a
     price.
  5. **Require a manual scale check before trusting area totals.** The
     tool already prints "scale may be wrong" (T.01) but nothing stops a
     BOQ being generated anyway. Add a step where the user confirms one
     real dimension on the drawing against the assumed scale before the
     fully-sized duct areas are treated as firm.

## 28. Building item 27's rules — one real finding corrected, three built and tested, one found impossible to verify yet

Noted 2026-10-28, same day, "start building all the rules one by one."
Followed item 27's own prerequisite (the process `HVAC_DRAWING_RULES.md`
sets for every rule: real geometry first, never guess the cause from the
symptom) before writing any fix — which overturned 27c's own theory
before any code was touched.

**28a. 27c's "collar damper" theory was wrong — checked against the real
file, not assumed.** Measured the distance from each of the 13 counted
"volume_damper" rects to the nearest diffuser AND the nearest flex
connector on the real PDF (`#ff0000@1.08:rect`, `#00ffff@0.84:rect`,
`#ffbf7f@0.48:rect`). Every single one sits 5.6-8.2 ft from the nearest
diffuser but a consistent ~2.0-2.85 ft from a flex connector — not the
"mounted on a grille" pattern 27c guessed. Rendered three of the 13
positions at 300 dpi to see what is actually drawn there: a red
starburst/arrow symbol next to a "TT" text mark on a duct riser, visually
nothing like a volume damper (a plain square symbol, like the diffuser
layer right next to it in the same crop) -- and exactly the same count
(13) and the same "TT"-adjacent locations item 25b already flagged as an
**unidentified repeating symbol it could not name**. The two findings are
almost certainly the same real thing, seen through two different mapped
layers. **Real root cause: the persisted `hvac_takeoff/layer_map.json`
simply had the wrong colour mapped to `volume_damper`** on this file --
not a disambiguation problem at all.

**Fixed:** `hvac_takeoff/layer_map.json`'s `"#ff0000@1.08:rect"` changed
from `"volume_damper"` to `"ignore"`. Re-ran the real extraction:
volume_damper count goes from the wrong 13 to 0; diffuser (40) and
flex_connector (67) unaffected, confirming the fix is scoped to the one
wrong layer. **Not fixed, and now a new, separate open item:** the real 8
VCDs the client's own schedule ties to the two 17TR units are not
identified anywhere in this file's geometry yet -- 0 is honest ("not
found"), not "confirmed none on the drawing". Finding them needs its own
real-geometry pass near the 17TR equipment positions, not attempted here;
a quick look at one 17TR unit's own crop found no obvious plain damper
symbol nearby either, so this isn't a five-minute follow-up.

**28b. A correction to 27e's own claim.** 27e called the real file's
"return, 22G" category "effectively one single run" to explain why it
came out more than 2x the client's real figure. Checked directly against
`duct_summary` while building rule 4's single-run warning below: it is
**5 runs** (the 20"x30" group, 38.8 ft, 13.5% of all return length), not
one. The warning built for rule 4 (below) correctly does NOT fire on this
category, because it genuinely isn't a single-point-of-failure case --
27e overstated this one detail. The real cause of that category's gap is
still open, not re-investigated here (would need its own geometry pass,
same honesty as 28a's own "not a five-minute follow-up").

**28c. Rule 3 built — symbols now carry their own size and area, not just
a count.** `count_symbol_rects()` (`hvac_takeoff.py`) now returns
`(cx, cy, w_pt, h_pt)` instead of just a centre point, keeping the
OUTER (larger) footprint when a symbol is drawn as a nested outer/inner
pair -- the frame someone would actually cut a hole for, the thing an
area-based bill needs, regardless of which of the pair pdfplumber happens
to return first (verified both orderings in a new test). `extract()`
converts this to `width_in`/`height_in`/`area_sqft` on every
diffuser/flex_connector/volume_damper entry, so a VCD can be billed by
area (sq.m, the client's own stated convention on the real file) as well
as by count -- both numbers are just there now, the write-up picks which
one the client's convention wants. 4 new tests in
`hvac_takeoff/test_hvac_takeoff.py`; full file re-run clean (20/20).

**28d. Rule 4 built -- three real gaps in the warnings, not just a UI
pass.** All in `hvac_takeoff.py`'s own `extract()`:
  - The label-match-rate warning only fired below 30%; the real file sat
    at 43% -- over half its runs unlabeled -- and said nothing. Added a
    second tier: 30-50% now gets its own warning naming the real
    percentage, instead of silence.
  - The "no symbol layer mapped" warning was all-or-nothing: mapping ANY
    one of diffuser/flex_connector/volume_damper silenced it for all
    three. Found live testing 28a's own fix: after removing the wrong
    volume_damper mapping, the file reported "0 dampers" with zero
    warning, reading exactly like a confirmed zero. Now checked per
    role -- an unmapped role gets its own warning naming it.
  - New: a `(system, size)` group built from exactly one measured run,
    where that run is a real share (>30%, a plain middle threshold, not
    tuned against a labelled set yet) of its whole system's length, now
    gets its own warning -- the general form of the single-point-of-
    failure risk 27e described (even though, per 28b, it didn't turn out
    to be this file's actual case).
  All three verified against the real file (43% warning and the
  volume_damper gap both now fire; no test added for warning STRINGS,
  consistent with this file's existing pattern of verifying warnings
  against the real extraction rather than unit-testing wording).

**28e. Rule 5 built -- a real gate, not just advice text.**
`addons/boq/takeoff.py`: a new checkbox, "I've checked one real, known
dimension on the drawing against this scale," next to the scale dropdown.
`self.use_btn` ("Use these measurements") now stays disabled until BOTH a
result exists AND this is checked -- changing the scale afterwards
un-checks it again, so a stale confirmation can never carry forward
silently. 4 new tests in `tests/test_boq_takeoff.py`; that file's full
12/12 and the combined `test_boq_dialog.py`/`test_boq_industries.py`/
`test_boq_takeoff.py` run both clean afterwards.

**28f. Rule 1 (schedule/legend tables) -- checked against the real file,
found nothing to build against, not attempted.** Before writing any
table-parsing code, checked whether this specific real file even has
something to parse: `page.extract_tables()` (pdfplumber) found **zero**
tables on the one page in hand, and a direct scan of the real text layer
for tag-shaped tokens (`G1`, `G2`, ... the client's own grille-schedule
tag format) found **zero** matches anywhere on the page. This is a
flattened CAD-export PDF, not a typeset document -- a schedule drawn as
plain text with no ruling lines is exactly what pdfplumber's table
detector cannot see, and more likely here: the client's grille schedule
(`G1`-`G7`, sizes in mm) and the VCD schedule almost certainly live on a
**different sheet of the full drawing set**, which this one-page test
file does not include. Writing a table-parser against a file that
provably has nothing for it to find would be exactly the kind of
unverified guess this project's whole process exists to avoid -- **not
built, needs the full drawing set (not just page 1) before it can even be
attempted, let alone verified.**

**Net for this session:** 3 of 5 rules built and tested (3, 4, 5); one
(2) turned out to need a config fix instead of new logic, with a new,
correctly-scoped open item left behind it (finding the real VCDs); one
(1) is confirmed blocked on missing input, not on missing code. Full
`pytest` suite re-run on the combined changes before calling this done.

## 29. Two more accuracy changes, asked for the same day — one gap closed, one new capability; one idea deliberately NOT built

Noted 2026-10-29, from the owner: after item 28 shipped, asked directly
whether running Prism now would actually look any different -- it would
not, for two of the five pieces: rule 3's area numbers were computed but
never reached a screen, and the `layer_map.json` fix only affects the
standalone script, never the app. Then asked for "any other ways to
increase accuracy", and to build them.

**29a. Rule 3, actually finished.** It was only half built: `extract()`
computed `width_in`/`height_in`/`area_sqft` on every diffuser/flex/damper
entry (28c), but neither `summary_text()` (what reaches the BOQ writer)
nor the review dialog (what a person sees before pressing "Use these
measurements") ever read it. New `symbol_counts_and_areas(res)` in
`hvac_takeoff.py` is the one place both now read from, so they can't
drift into reporting different numbers for the same run:
  - `summary_text()`'s "SYMBOLS COUNTED BY SHAPE" section now prints each
    type's total area (sq.ft and sq.m) alongside its count.
  - `addons/boq/industries.py` gains `symbol_counts_and_areas()`, a thin
    dispatcher matching every other function in that file.
  - `addons/boq/takeoff.py`'s `_ReviewTable` gains a small summary line
    under the legend, filled by `_render_symbols()`, so this is visible
    BEFORE "Use these measurements" is ever pressed, not just in the
    final text hand-off.
  Verified against the real file (OCR off, for speed): now prints
  `Flex Duct Connector: 67 (268.00 sq.ft / 24.90 sq.m total frame area)`,
  previously just `Flex Duct Connector: 67`. 2 new tests in
  `hvac_takeoff/test_hvac_takeoff.py`, 2 more in
  `tests/test_boq_industries.py`.

**29b. A new capability: the scale check can now fix the number, not
just flag it.** Item 27 rule 5's checkbox only ever asked "did you check
it?" -- it had no way to let a person actually correct a wrong scale.
New `_ScaleMeasureDialog` (`addons/boq/takeoff.py`): renders the drawing
at a fixed 100 dpi, the person clicks two points on something they
already know the real length of (a labelled room width, a door opening),
types that real length in feet, and the dialog computes the drawing's
real points-per-foot scale directly from pixel distance -- `72 / dpi` is
the PDF-point conversion (not a guess; 72 pt/inch is the PDF unit
definition), so this needs no second calibration step. A new "Measure…"
button opens it; accepting overrides `_pt_per_ft()` (a measured reading
always wins over the dropdown's assumed standard scale) and auto-checks
the scale-confirmation box, since measuring it IS the confirmation --
nobody should have to tick a second box saying what they just did.
Changing the scale dropdown afterwards, or picking a new PDF, clears the
measured override and un-checks the box again, same reasoning as 28e's
own reset rule. Verified against the real file: 100 px at 100 dpi over a
stated 10 ft came out to exactly 7.2 pt/ft, matching the plain
arithmetic by hand. 9 new tests in `tests/test_boq_takeoff.py` (the real
PDF is never kept in the repo -- tests replace `_load_image` with a
blank pixmap and check the click/distance math, not rendering).

**29c. Considered and deliberately NOT built: a duct-run "continuity
check".** The idea -- flag any measured run that doesn't connect to the
rest of the network, since an isolated run is often a misread -- sounds
reasonable, but `HVAC_DRAWING_RULES.md` rule 2 already records a nearly
identical idea (bridging gaps between runs) being BUILT, shipped, and
then having to be walked back once a real branch tee-junction was found
reading as a false "gap". Writing a NEW connectivity heuristic today,
with no second real file to check it against, risks the exact same
mistake. Not attempted -- needs its own real-geometry verification pass
first, the same process every rule in this file and `HVAC_DRAWING_RULES.md`
already follows, not skipped just because the idea sounds safe.

**Also named, not attempted today (unchanged from item 27's own list):**
finding the real 8 VCDs in the geometry (28a's own open item), and an
automatic "second independent AI read" cross-check before a BOQ is
finalised -- a real idea, but it is a new piece of architecture (which
agent, what prompt, how a disagreement surfaces in the UI), not a
same-shape fix to an existing function, and deserves its own design
pass rather than being rushed in alongside today's other changes.

**29d. Asked which to do next: found the real VCDs.** Scanned every
rect AND curve layer on the real page for any group with a small count
(4-20) -- the kind a real VCD schedule (8 total, per the client's own
file) would produce -- instead of guessing where to look. One stood out:
`#00ffff@0.84:poly`, 8 polyline objects. Rendered 4 of the 8 positions at
300dpi: every one is a hatched rectangle with a black bowtie/blade mark,
sitting directly on a duct riser at a size-transition point -- the
textbook symbol for a manual volume-control damper (OBD), and visually
nothing like the red starburst 28a already found to be a different,
unidentified symbol. 7 of the 8 are distinct positions; one pair is an
exact duplicate (same coordinates to 0.1pt) -- plausibly one drawn
symbol standing in for a multiple-unit tag group, the same way the
client's own grille schedule notes "4NOS." next to one drawn grille
rather than drawing four.

**Fixed:** new `count_symbol_curves()` in `hvac_takeoff.py` -- same job
as `count_symbol_rects()`, for a symbol drawn as a filled polyline
instead of a rectangle (its bounding box is looser, 50pt vs 9-20pt,
because this symbol's drawn extent runs along the duct, 36-44pt on the
real file, not a small fixed icon). `extract()`'s symbol loop now checks
both per role, deduped against each other. `hvac_takeoff/layer_map.json`
gains `"#00ffff@0.84:poly": "volume_damper"`. Re-ran the real extraction:
**volume_damper count goes from the wrong 13 (28a) to 7** -- much closer
to the client's real 8, with a plausible explanation for the remaining
gap, rather than a number with no story behind it at all.

**A second honesty fix found while building this:** a curve symbol's
bounding box is the drawn MARK's own extent along the duct, not the
item's physical cross-section the way a rect icon's bbox is (rule 3,
item 29a, relies on the bbox BEING the physical size). Computing an
"area_sqft" from it would be a real-looking number that means nothing.
`width_in`/`height_in`/`area_sqft` are left `None` for curve-sourced
symbols rather than populated with a wrong figure -- checked directly:
the 7 real dampers now report `size: ""`, `area_sqft: None`, not a
plausible-looking wrong area.

6 new tests (`CountSymbolCurvesFindsThePolylineDamperSymbol`,
`ACurveSourcedSymbolsAreaIsNoneNotAWrongNumber`) in
`hvac_takeoff/test_hvac_takeoff.py`.

**Still open:** 7, not 8 -- the duplicate-position theory above is
plausible, not confirmed; needs the actual schedule (rule 1, still
blocked on the same missing drawing-set page) to settle which tag covers
3 units.

**29e. Asked to build the duct-connectivity check anyway, scoped as
report-only.** A run that connects to NOTHING else, at either end, within
its own system (supply only checked against supply, return against
return) is flagged -- a run free at only ONE end is a completely normal
dead end (a diffuser, a stub, an AHU connection) and is never flagged.
New `_isolated_runs()` in `hvac_takeoff.py`, wired into `extract()`'s
warnings only -- it never alters a run, a length or `duct_summary`,
exactly the line 29c drew before building it.

`tol_ft` checked against the real file before picking one, not chosen
blind: 1.0 ft flagged 90 of 145 runs (a flood -- ordinary CAD gaps are
often wider than that); 2.0 ft flagged 17, and every one of those matches
runs the write-up's own text had ALREADY named by hand ("very short
identical runs... may be collars, stubs or symbol edges") -- independent
confirmation this threshold finds a real, already-known anomaly rather
than noise. Shipped at 2.0 ft. 5 new tests
(`IsolatedDuctRunsAreFlaggedNeverAlteredOrMerged`), including one that
asserts the function never mutates its input.

Full `pytest` suite re-run on the combined 28+29 changes before calling
this done.

## 30. BUILT — OpenRouter write-up agents, research off by default, a per-job memory folder, two-tier models

Noted 2026-10-30, from the owner, explicitly "note this down first, we start working after." Nothing in this
item is built. Written down before any code so the next session starts from an agreed shape, not from
memory.

**30a. Research agent: default becomes "No research."** Today's BOQ flow runs a standards-research stage
before write-up by default. Change: that stage is OFF unless the user turns it on -- the common case
skips straight from measurements to write-up.

**30b. Write-up agent: default becomes an OpenRouter API key, not browser automation.** Same job, same
shape (measurements in, a document out), just reached through an API key instead of driving a browser tab.
Output format (DOCX/CSV/PDF) stays whatever the user already picks. This is the BOQ add-on's own small,
scoped version of the "Migration A" gateway idea from the 28 Oct migration doc -- OpenRouter here, not
Prism's own licence-server gateway, and only for this one add-on's write-up stage.

**30c. Two new named write-up options, both via OpenRouter:**
- **"Prism Agent Claude"** -- `anthropic/claude-sonnet-5.5` ($2 / $10 per 1M tokens, 1M context).
- **"Prism Agent Deep"** -- `deepseek/deepseek-v3.2` ($0.28 / $0.42 per 1M tokens, 163K context).

Prices and model ids pulled directly from OpenRouter's own `/api/v1/models` endpoint, 29 Oct 2026 -- not a
blog or a guess. **Quality for this specific job (faithfully writing out given measurements, never
re-deriving a number, staying in format across follow-ups) is verified for neither model yet** -- Sonnet
5.5 has a track record in this session's own BOQ write-ups; DeepSeek v3.2 does not, and was recommended on
price alone. Before this ships as a real default, run the same real-measurement write-up prompt through
both and check the output directly, the same way this session tested OCR engines before trusting any of
them -- not assumed from a spec sheet.

**30d. A basic per-job memory folder (a small RAG, not a vector database) -- and the real reason for it is
a History feature, not logging.** Every time the BOQ add-on is opened fresh for a NEW job, a new folder
under a new unique job ID is created -- closing the add-on and reopening it starts a new folder, never
reuses the last one. In it:
- the input file(s) the user attached (drawing, external measurements),
- every prompt the user gave, stored as `.txt`/`.json`,
- the document the API produced for each turn.

**Why:** someone making several BOQs a day needs to come back to any ONE of them later -- a client asks
for a change on the first BOQ from that morning, after two more have already been made since. The folder
is what makes that possible: a **History** list in the BOQ add-on, one row per job with its date and time,
lets the user pick that exact earlier job. Picking one opens ITS folder by its unique ID, Prism reads back
that job's documents and prompt history, and only then answers or makes the follow-up change -- not the
currently-open job, not a guess from the live chat alone. This is a new piece of UI (a History
list/browser), not only a storage format -- noted here since 30d's folder is the data it reads, but the
list itself still needs its own screen in `addons/boq/dialog.py` or a sibling.

Still to decide, not decided here: the folder's exact layout, how large a document gets read back in full
vs. summarised, how far back History keeps jobs (forever vs. a cap), and whether this replaces or sits
alongside the existing conversation-resend pattern `VERIFY_PROMPT`/follow-up flow already uses.

**30e. Two-tier model use inside one job.** A heavier, smarter (and more expensive) model for the actual
BOQ generation; a lighter, cheaper model for follow-up edits and small changes to an existing BOQ --
different from 30c's "Claude vs Deep" choice (that is picking WHICH provider/brand runs the write-up
stage; this is picking a DIFFERENT, cheaper model specifically for the follow-up stage of the SAME job,
regardless of which brand generated the original document). Not yet decided: which model fills the
"light" follow-up tier -- a smaller model from the same family as whichever heavy model generated the
document is the obvious starting guess, not yet checked against a real follow-up prompt.

**Still open after this item, unchanged from before:** the new open items from 28/29 (finding the real 8
VCDs in the geometry, rule 1's schedule-table parsing still blocked on a missing drawing-set page), and
everything in section 12 of the 28 Oct migration guide (credits/pricing model, which Reasoner model, data
terms) that this item's own cost questions overlap with.

## 31. Item 30, actually built — the key screen, every piece wired, and one real bug caught before it shipped

Noted 2026-10-30, same day: "now build all of this with proper UI". All five pieces of item 30 are built
and tested; nothing here is a plan any more.

**31a. `addons/boq/agents.py`** gains `PRISM_AGENTS = ["Prism Agent Claude", "Prism Agent Deep"]`
(first in `WRITER`, so a fresh install's write-up default is now an API call, not a browser tab),
`NO_RESEARCH = "No research"` (first in `RESEARCH`), `PRISM_AGENT_MODELS` (the heavy, generation-tier
OpenRouter model id per agent) and `PRISM_AGENT_FOLLOWUP_MODELS` (the cheaper same-family sibling — item
30e's two-tier choice). 9 tests in `tests/test_boq_agents.py`.

**31b. `prism_terminal/core/openrouter.py`** (new) — `openrouter_chat()` and `verify_key()`, deliberately
shaped like `router.py`'s own `groq_chat()`/`verify_key()` (same retry-on-429/5xx behaviour, same "raise
with the server's own words" rule), so the two API paths fail the same way to whatever reads their
exceptions. Exposed as `CB.openrouter` (`core_bridge.py`), same pattern as `CB.router`. 11 tests in
`tests/test_openrouter.py`, nothing touches the real OpenRouter API.

**31c. `addons/boq/openrouter_writer.py`** (new) — the half a browser agent gets for free (its own
file-export feature) and a plain API call does not. `write()` picks the right model tier and calls
`openrouter_chat`; a small markdown parser (`parse_markdown`) reads the headings/paragraphs/bullet-lists/
pipe-tables the write-up prompt has always asked every agent for; `markdown_to_docx`/`markdown_to_csv`
build the real file from that (python-docx; the CSV picks the BIGGEST table found, almost always the BOQ
item schedule, never silently empty); `markdown_to_pdf` reuses `core.boq_price.write_boq_pdf`'s own
technique (render HTML with the bundled Chromium, print it) rather than a new dependency. **Deliberately
NOT routed through `core.boq_price`'s `Boq`/`BoqItem` pipeline** — that module's own docstring states "no
number of record is ever produced by an AI", which is the PRICING stage's rule, not the write-up stage's;
conflating them would have been exactly the kind of boundary violation this project's whole architecture
exists to prevent. A real bug was caught here before it shipped: the table-separator regex
(`_is_table_sep`) scanned a whole row as one string, which fails on a real pipe-table row because the `|`
characters between cells aren't in the allowed charset — found by running a realistic sample through the
parser BEFORE writing the tests, not after. Fixed by splitting into cells first. 18 tests in
`tests/test_boq_openrouter_writer.py`.

**31d. `addons/boq/workers.py`** gains `OpenRouterWriteWorker` (one completion off the GUI thread, same
`_Worker` base every other worker in this app uses). `addons/boq/dialog.py` gains `_run_prism_agent()`,
the single interception point called from the TOP of both `_run_stage` (the first run: research/interpret/
write) and `_start_followup_run` (recheck/followup) whenever the picked agent is a Prism Agent — it never
reaches `AutomationWorker` or `BoqRunDialog`'s live window/fallback chain at all (a bad key or a down API
is reported once, directly; retrying it against five different BROWSER agents would not help an API
problem). `on_success(responses, links)` is called with the exact `{stage: [text]}` / `{}` shape a browser
run's own done signal already produces, so `_on_standards`/`_on_interpreted`/`_on_written`/
`_on_followed_up` all work completely unchanged — not one of them can tell the difference between this and
a browser agent's answer.

**A real hang, found and fixed before this shipped.** The full dialog test suite hung indefinitely after
this wiring went in. Cause: `writer_combo`'s default is now "Prism Agent Claude" (31a), and ONE existing
test class (`TheDrawingGoesToAIOnlyAfterAYes`) never set an explicit writer agent — it inherited whatever
the combo defaulted to. With no OpenRouter key configured in the test's config, `_run_prism_agent` called
`QMessageBox.warning(...)`, a real blocking modal, with nobody there to click it. Every OTHER test in this
file already set an explicit agent (`d.writer_agent = "..."` or `writer_combo.setCurrentText(...)`) — this
was the one gap. Fixed by giving that class's `setUp` the same explicit `self.d.writer_combo.setCurrentText
("Claude")` every other test already uses, since it specifically tests the browser-agent path. 7 new tests
in `APrismAgentNeverTouchesAutomationWorkerOrBoqRunDialog` check the bypass directly: no key warns and
starts no worker, a Prism Agent never constructs `AutomationWorker`, a browser agent's own path is
completely untouched, a success/failure both call the right callback with the right shape.

**31e. The OpenRouter key screen — Settings → AI tools, same page as the Groq key.** A new password field
(`widgets/settings_panel.py`, right under the existing Groq key field — "the Groq key and the agent picks
are one job" already applied here too) saves to `self.cfg["openrouter_api_key"]`, validates the `sk-or-`
prefix before saving, and checks the key against OpenRouter the moment it's saved (`OpenRouterKeyWorker` in
root `workers.py`, mirroring `GroqKeyWorker` exactly) — a wrong key is told apart from a right one on the
spot, the same promise the Groq key already makes. One key powers both Prism Agent models; every other
writer agent keeps working without one.

**31f. The per-job folder and History — built on what already existed, not a new system.** Checked first:
`core/config.py` already had a complete "one folder per run, resumable" system
(`begin_run`/`continue_run`/`current_run_dir`/`save_artifact`/`save_run`, under
`~/.prism/Artifacts/<Task>/<timestamp>/`) and `_on_written` already called `save_run()` with a JSON record
— item 30d turned out to be mostly already there, not a new thing to build.
  - `_run_prism_agent` now writes the exact prompt sent to the API into that same job's folder as both
    `.txt` (for a person to open) and `.json` (stage/agent/prompt/request/timestamp) via a new
    `_save_prompt_record()` — best-effort, never fails the BOQ if the write itself fails.
  - `_on_written`'s and `_on_followed_up`'s `save_run()` calls now tag the record `"addon": "boq"` (so
    History can find BOQ's own runs without guessing from the title text) and carry `"request"`,
    `"last_text"` and `"deliverable_path"` — everything a follow-up on a REOPENED job actually needs.
    `_on_followed_up` now calls `save_run()` too (it never did before), passing the path the FIRST call
    returned, so `save_run`'s own already-existing "update this file in place" behaviour keeps one job's
    record current across every follow-up, not stuck at the first answer.
  - `addons/boq/history.py` (new) — `list_boq_runs()` (every `"addon": "boq"` record, newest first, a file
    that fails to parse is skipped not a crash) and `BoqHistoryDialog` (date + the original request per
    row, double-click or "Open this BOQ" to pick one). A new "History" button next to the writer/research
    pickers opens it; `BoqDialog._resume_from_history()` loads the picked job's last answer, its
    deliverable path, its measured-CSV/drawing paths, and resumes its OWN artifacts folder via
    `continue_run` (so anything a follow-up produces now lands beside that job's existing files, not in a
    fresh folder) — then offers the same "anything to change?" follow-up window any run already ends with.
  13 tests in `tests/test_boq_history.py`, including the full resume path.

**What's intentionally simpler than the browser-agent path, said plainly:** a Prism Agent has no live
progress window (`BoqRunDialog`) — a plain API call has nothing comparable to watch happen, unlike a
browser agent typing in a visible tab, so a simple busy spinner was judged enough rather than building a
second live-window UI for a call that's just "waiting on a response." No retry across a fallback chain
either — FALLBACK_ORDER is a chain of BROWSER agents, and retrying an OpenRouter failure against Claude's
own browser tab would not fix an OpenRouter-side problem; a failure is reported once, directly, with the
real reason, same as the project's own "the server's own words, never a paraphrase" rule elsewhere.

**Verification:** `tests/test_boq_agents.py` (9), `tests/test_openrouter.py` (11),
`tests/test_boq_openrouter_writer.py` (18), `tests/test_boq_history.py` (13), plus the existing
`tests/test_boq_dialog.py` (131, including the 7 new Prism Agent routing tests) and the rest of the BOQ
suite (`test_boq_run_dialog.py`, `test_boq_pricing.py`, `test_boq_industries.py`, `test_boq_takeoff.py`,
`test_boq_file_guardrail.py`) all re-run together, clean. Full repo `pytest` re-run before calling this
done.

**Still open, not attempted here:** DeepSeek's real quality on this job is still unverified (item 30c's own
flag, unchanged — only the plumbing to call it exists now, not proof it writes a good BOQ); which model
fills the follow-up tier was picked as "the obvious same-family cheaper sibling", not checked against a
real follow-up prompt (item 30e's own open point, unchanged); and the per-job folder's prompt files are
written only for the Prism Agent path, not for a browser agent's own write-up (scoped to match the user's
own framing — "the document that the API key produced" — not extended further without being asked).

## 32. The drawing itself, for .pdf/.dxf/.dwg, actually reaching a Prism Agent's eyes — and the three calls this forced

Asked 2026-10-30, same day as item 30/31: BOQ's clients split into genuinely different permutations —
some will hand a drawing straight to an AI as a PDF, some have signed an NDA that the drawing never
leaves their machine at all. "we must make and solve this problem in all possible ways and people can
use it in all permutation combination." That's not one feature; it's three decisions plus the pipe that
makes any of them real. Resolved by `AskUserQuestion`, not guessed, since each one is a real
business/compliance call:

- **Key provisioning (for now, before a server-side gateway exists):** the installer/Prism-team enters
  the OpenRouter key during setup, not the client themselves.
- **Send-to-AI default:** off by default, explicit opt-in every time a drawing would actually leave the
  machine.
- **DWG scope:** build all three formats now, including the DWG→DXF conversion step, not just PDF/DXF.

**32a. `addons/boq/cad_render.py` (new)** — turns a drawing into something a vision model can actually
look at. `prepare_for_ai(path)` branches on extension: a `.pdf` is read and base64-encoded as-is (Claude
reads a real PDF natively, no rendering needed); a `.dxf` goes through `render_dxf_to_png()`
(`ezdxf.addons.drawing`'s `RenderContext`/`Frontend`/`MatplotlibBackend`, headless via `matplotlib.use
("Agg")`); a `.dwg` goes through `dwg_to_drawing()` first — `ezdxf.addons.odafc`, a wrapper around the
free, separately-installed ODA File Converter (not pip-installable; `odafc.is_installed()` confirmed
`False` in this dev machine, a real, honestly-reported constraint, not a guess) — then the same PNG
render. Anything else raises `CadRenderError` with the real reason, never a silent guess.

**A real bug, caught by actually looking at the output, not by the absence of an exception.** The first
DXF render produced a non-trivial, ~5.8 KB PNG with no errors — and was completely blank when opened.
Cause: `ax.set_axis_off()`, called before drawing to hide the plot frame, also hides ezdxf's own
background patch, which is tied to the same axes visibility — so the geometry drew onto an invisible
canvas. Found by isolating the exact line in a step-by-step repro script and comparing the saved PNG
with/without it; fixed by removing the call (and the now-pointless `facecolor="white"` savefig argument,
since ezdxf's own background patch overrides it regardless). 10 tests in `tests/test_boq_cad_render.py`,
including a regression test that checks the output PNG actually has more than one pixel colour — not just
that a file of plausible size exists.

**32b. `prism_terminal/core/openrouter.py` extended for multimodal.** `openrouter_chat()` gains an
`attachments` parameter; a new `_content_blocks()` helper returns a plain string when there's nothing
attached (every call before this item, unchanged — a payload inspector or a provider that chokes on an
array-of-one sees exactly what it always has) or OpenRouter's documented multimodal content-array shape
otherwise: an image becomes an `image_url` block with a `data:` URI; a PDF becomes a `file` block with
`file_data`, so a compatible model reads the real document rather than a picture of it. Built from
OpenRouter's own published API shape — **honestly flagged in the code as not yet verified against a live
call**, since no real key was available to test with this session. 4 new tests in
`tests/test_openrouter.py` (`AttachmentsBuildOpenroutersMultimodalContentShape`) check the shape built,
not a real call.

**32c. Vision capability checked against real data, not reputation.** `addons/boq/agents.py` gains
`PRISM_AGENT_HAS_VISION` — queried directly from OpenRouter's own `/api/v1/models`
`architecture.input_modalities`, 30 Oct 2026: `claude-sonnet-5.5`/`claude-haiku-5.5` → `['text','image',
'file']`; `deepseek-v3.2`/`deepseek-v4-flash` → `['text']` only, no vision at any tier. `openrouter_writer.
has_vision(agent)` reads this table; `write()` silently drops an attachment for an agent with no vision as
its own last line of defence, but the caller (32d) is expected to have already told the user plainly
before it gets this far.

**32d. Wired into the actual recheck flow — `addons/boq/dialog.py`.** The real drawing was already being
attached for the ONE stage that ever sends it — `"recheck"` (`_ask_recheck()` and the "Verify and remake"
quick action in `_offer_followup()`), both already gated by the pre-existing `_drawing_consent()` yes/no
("the drawing file leaves this computer. Continue?"), which turned out to already satisfy this item's
"off by default, explicit opt-in every time" decision — nothing new needed there. The gap was what
happened to the drawing AFTER that yes, for a Prism Agent: it was being flattened into
`CB.files.context_block()`'s plain TEXT (whatever `CB.files.attach()`'s own text-extraction finds — little
to nothing for a DXF/DWG, and not the actual pixels/vectors for a scanned PDF either), never the real
file/image a vision model could look at.

  - New `_prepare_drawing_attachment(stage, agent, files)`: for `stage == "recheck"` with `files[0]` being
    the drawing (always true for both call sites above — the drawing is always attached first), it is
    pulled OUT of the plain-text file list and either turned into a real attachment via `cad_render.
    prepare_for_ai()` (agent has vision — the drawing is also removed from the text context, since the
    real file now carries it) or left exactly where it was, in the text list, with a plain `QMessageBox.
    warning()` telling the user why: no vision at all ("{agent} can't look at drawings... Pick Prism Agent
    Claude for a real look at the drawing"), or the render itself failed (`CadRenderError`'s own message,
    e.g. the missing ODA converter), never silently.
  - `_run_prism_agent()` calls it first, then passes the result on to `OpenRouterWriteWorker(..., 
    attachments=[attachment] if attachment else None)`; `OpenRouterWriteWorker` and `openrouter_writer.
    write()` both already accepted `attachments` (32b/32c's own plumbing) — this is what finally calls it
    with something real instead of `None`.
  - Every other stage (`format`, `standards`, `interpret`, `followup` without a drawing) is completely
    unaffected — `_prepare_drawing_attachment` returns `(files, None)` immediately unless `stage ==
    "recheck"` and the drawing is actually there.
  5 new tests in `tests/test_boq_dialog.py` (`PrismAgentRecheckShowsTheRealDrawingNotJustTextItem32`):
  a vision agent gets a real attachment and the drawing leaves the text files; a no-vision agent warns and
  keeps everything as text; a render failure warns with the real reason and falls back to text; a
  non-recheck stage never touches the drawing at all; `_run_prism_agent` actually passes the prepared
  attachment through to the worker constructor.

**Answering the owner's own logistical question — where does the key go?** Today, only the existing
self-service field exists: Settings → AI tools → "OpenRouter key", the same screen as the Groq key,
checked against OpenRouter the moment it's saved (item 31e). That is NOT yet the "installer/Prism-team
enters it, hidden from the client" screen the owner's `AskUserQuestion` answer actually asked for — this
item built the pipe the key flows through once it exists, not a second, gated entry screen. Said
plainly, again: OS Keychain storage (how `licensing/secretstore.py` already keeps this key) is not a
security boundary against a client who controls their own machine — it only raises the cost of casual
leakage. Real secrecy needs the key to never reach the client's machine at all (a server-side gateway,
the "Migration A" idea already on record from the 28 Oct migration doc), which this item does not build.

**Still open, not attempted here:** the installer-entered, password-protected key screen itself (today's
field is self-service, not gated — see above); a real DWG file through a real, installed ODA File
Converter (the converter is confirmed absent from this dev machine — `dwg_to_drawing()` is unit-tested
against a mock only); `openrouter_chat`'s multimodal payload against a REAL OpenRouter call (32b's own
flag — the shape is built from documentation, not proven live); and the server-side gateway itself (every
key today still lives on the client's machine, by design, per the owner's own "for now" framing of the
provisioning decision).

**Verification:** `tests/test_boq_cad_render.py` (10, new), `tests/test_openrouter.py` (15, 4 new),
`tests/test_boq_openrouter_writer.py` (21, 3 new covering `has_vision`/attachment-gating),
`tests/test_boq_dialog.py` (132, 5 new), full repo `pytest` re-run before calling this done.

## 33. A "Preview this layer" button in Step 1 — and its first real use found the real client_2nd_sample file was stuck at 0 duct runs because of it

Noted 2026-10-30, same day: "i can see the preview option beside layer mapping [in a rival
PDF-takeoff tool] that is not available in the prism hvac pdf takeoff version... this was
confusing for the user to actually recognize, so add a option of preview in the prism as well."
A Layer-mapping row has only ever shown a colour swatch, a segment count and a rough length —
real information, but not an answer to "is THIS the duct network or something else" without
opening the raw PDF in another program. The fix: an eye-icon button on every row
(`addons/boq/takeoff.py`) that calls a new `hvac_takeoff.layer_preview_png()` — the exact
"render one layer alone, look at it" technique item 25e already used once as a one-off debug
script (it found `#808080@0:poly` was the building's own wall outline, not ductwork, mapped
to `return` by mistake) — now a one-click tool instead of something only reachable by someone
who can write a script. Returns PNG bytes, never a file on disk, since a person still deciding
every layer's role may click this on dozens of them in one sitting.

- `hvac_takeoff/hvac_takeoff.py`: `layer_preview_png(pdf_path, key, page_index=0, dpi=100)` --
  fades the full page (same `Image.blend` technique `overlay_png` already uses) and draws only
  that one layer's own segments (`layer_lines()`, already existed) in red on top.
- `addons/boq/industries.py`: `layer_preview()` dispatch, same shape as `scan_layers`/`extract`.
- `addons/boq/takeoff.py`: the eye-icon button, and `_LayerPreviewDialog` -- a small popup
  showing the rendered picture, or the real error if rendering failed (never a blank dialog).
- 3 new tests in `hvac_takeoff/test_hvac_takeoff.py`, 2 in `tests/test_boq_industries.py`, 6 in
  `tests/test_boq_takeoff.py` -- all mocked at the same level this project's own tests already
  use for this module (a fake page/PdfDocument, never a real PDF fixture).

**It immediately paid for itself.** The owner had just run Prism's own HVAC PDF-takeoff on
`HVAC_BOQ_TEST/client_2nd_sample/HVAC_LAYOUT_ 2ND SAMPLE-Model.pdf` (the same file item 32's
BOQ-vision-read used) and got `runs: 0, label match: 0%` -- every one of the file's 212 layers
had been left on "ignore" (confirmed directly: the owner's own screenshot showed `#808080 line
289 segs`, `#0000ff rect 760 segs` and `#000000 rect 2220 segs`, all three still "ignore" --
scanning the same file here reproduced the identical segment counts and lengths exactly, so
this is the same layer list, not a guess). The extractor's own "No duct runs found: check the
layer mapping" warning did its job correctly here -- this was never a bug, just confusing to
act on without being able to see what any of those 212 colours actually drew.

Used the new preview tool itself (not just built it) to find the real answer: rendering
`#000000@1.56:line` (1347 segments, the longest black line layer) showed the ENTIRE duct
network, both supply and return branches -- this file does not colour-code return separately
from supply the way the first sample file does (item 25's `#ff0000@1.08:line` convention).
`#000000@1.56:poly` turned out to be the SAME network's elbows/transitions, drawn as polylines
rather than straight lines. Other tall candidates checked and ruled out by eye: `#ff0000@0.84:
line` is red-highlighted annotation underlines (toilet partitions, a label box), not ductwork;
`#000000@0.72:line` is the SHX-stroke-drawn label/tag text itself (VAV tags, "T" markers), not
geometry at all -- consistent with item 8/32's own "hybrid document" finding that this
drawing's MEP annotation layer is vector strokes, not real embedded text, while its
architectural room-name layer is (1281 real `ArialMT`/`ArialUnicodeMS` words extract cleanly,
but zero contain a CFM or VAV tag).

**Mapping `#000000@1.56:line` + `#000000@1.56:poly` to `supply` DOES produce real runs** (38,
vs 0) -- confirmed by actually calling `industries.extract()` with that map, not assumed from
the preview picture alone. **Two honest caveats, not glossed over:**
- The 105.6 ft total is at a GUESSED 96 pt/ft (only to test the pairing mechanics) -- the
  resulting duct widths (16″, 13″...) read far too small next to labels actually seen on this
  drawing (550x300mm ≈ 21.7″x11.8″), a clear sign 96 is wrong. The real scale needs "Measure…"
  against a known dimension on THIS drawing before any length here is trusted -- this file's
  text isn't extractable (previous paragraph), so there is no OCR'd dimension to fall back on
  for a quick sanity check either.
- Even at the right scale, the total will likely stay well below the drawing's real duct
  footage: visually, this file's duct runs are heavily diagonal (angled VAV-box connections,
  curved elbows) compared to the first sample file's mostly-orthogonal layout, and the
  extractor's own documented limit -- "only straight horizontal/vertical ducts are measured" --
  is a real, structural gap for this drawing's own drafting style, not a mapping mistake to fix
  by picking a different layer.

**Deliberately NOT done: no change to `hvac_takeoff/layer_map.json`'s defaults.** `#000000` at
weight 1.56 means "the duct network" on THIS file and "nothing in particular" (0.72 is label
text, not ductwork) on this SAME file two rows up -- the owner's own standing caution from
earlier the same day ("are you sure \[these rules\] will be applicable for other drawings?")
applies directly: a colour-keyed global default would be guessing from one file's convention,
exactly what item 25's own per-layer reverse-engineering already refused to do. This stays a
per-file, Preview-button judgement call, the way it already was for every colour before today.

## 34. "The standalone tool measured many runs on this exact file -- BOQ measured zero" -- found why: BOQ was never wired to the standalone tool's own cross-tender memory

The owner tried the SAME `client_2nd_sample` PDF, unchanged, straight through
`hvac_takeoff.py`'s own standalone GUI (`run_gui()`, tkinter) -- the tool item 33's
investigation had already been exercising all along from the command line -- and it measured
real duct runs immediately, no manual mapping. Through BOQ's own dialog, the identical file
measured zero (item 33). Same PDF, same extraction code underneath -- so the difference had
to be in what each caller does with Step 1's roles, not in the extraction itself.

**Root cause, found by reading `hvac_takeoff.py`'s own `run_gui()`:** `MAP_FILE`
(`hvac_takeoff/layer_map.json`) is a *cross-tender memory* -- its own comment says so
("remembers colour -> role between tenders") -- and the standalone tool's `load()` always
pre-fills every combo box from it (`v = tk.StringVar(value=saved.get(L["key"], "ignore"))`),
then `start()` writes the current choices back to it before extracting. `#000000@1.56:line`
and `#000000@1.56:poly` were ALREADY saved as `"supply"` in that file -- from item 33's own
`industries.extract()` test calls earlier this same session -- so the standalone tool's Step 1
opened with those two rows already set to `supply`, and measured real runs with zero manual
work. BOQ's own `addons/boq/takeoff.py` (`_fill_mapping`) never once reads or writes that file
-- every layer, on every drawing, in every BOQ session, has always started at "ignore" and
been thrown away after Extract, regardless of what a previous tender already taught the
standalone tool about that exact colour+weight+kind key.

**Fix, built the same way as every other industry-specific capability here (item 26's own
dispatch pattern) -- never a direct import of `hvac_takeoff` from BOQ's own files:**
- `hvac_takeoff.py`: a new `save_map(updates)` wraps the load-merge-write `start()` already did
  inline; `start()` itself now just calls it (no behaviour change, one less duplicate).
- `industries.py`: two new dispatch functions, `saved_layer_roles(industry)` (read) and
  `remember_layer_roles(industry, layer_map)` (write) -- HVAC reaches `load_map()`/`save_map()`,
  any other industry gets `{}` back / is a no-op, same "empty/no-op, not an error" convention
  `roles()`/`scales()` already use for a lookup nothing is being asked to measure.
- `takeoff.py`: `_fill_mapping` now asks `saved_layer_roles` for each layer's own key and
  pre-selects that role on the combo (only if the saved value is still one of THIS industry's
  current `roles()` -- a stale value from an older role list is never forced in); `_extract`
  calls `remember_layer_roles` with the current `_layer_map()` right before starting the
  worker, same timing as the standalone tool's `start()` -- saved whether the extraction that
  follows succeeds, fails, or finds zero runs, since the mapping work itself is still real.

**This is NOT the same thing as item 33's "deliberately not done."** Item 33 refused to pick a
NEW hardcoded colour-role default and bake it into the JSON as a judgement call on the file's
behalf -- that would be guessing one file's convention onto every future one. This item wires
BOQ to a memory mechanism `hvac_takeoff.py` already had on day one, that only ever remembers
whatever role a person actually picked for an EXACT key, right or wrong -- the same convenience
default the standalone tool has always offered, now offered in BOQ's dialog too. A pre-filled
role is still only a starting point, not a verified answer: the same colour can mean something
else on a different drawing (item 33's own `#000000@1.56` vs `#000000@0.72` finding on the SAME
file is proof enough of that), so the Preview button from item 33 is exactly how a person
checks a pre-filled guess before trusting it, same as they would an unfilled one.

Tests: `hvac_takeoff/test_hvac_takeoff.py` +3 (`save_map` merges/overwrites/swallows a write
failure -- patches `H.MAP_FILE` to a temp path, never the real tracked JSON); `tests/
test_boq_industries.py` +4 (the two dispatch functions, built and unbuilt industries);
`tests/test_boq_takeoff.py` +5 (`_fill_mapping` pre-selects a saved-and-still-valid role, never
forces in a stale one; `_extract` passes the current map to `remember_layer_roles`, and skips
it entirely when the all-ignore warning is declined). A module-level patch at the top of
`test_boq_takeoff.py` guards EVERY test in that file from reaching the real
`hvac_takeoff/layer_map.json` through `_extract()`'s new call, the same "never touch real
persisted state in a test" rule the project already holds for `~/.prism`.

**Found along the way, NOT fixed here -- a separate, pre-existing bug:** running `tests/
test_boq_industries.py` together with `hvac_takeoff/test_hvac_takeoff.py` in the same pytest
process throws `ModuleNotFoundError: No module named 'hvac_takeoff.hvac_takeoff'; 'hvac_takeoff'
is not a package` on every test after the first that reaches `industries._hvac()` -- confirmed
reproducible on the unmodified `main` branch (via `git stash`), so today's change did not cause
it. Cause: `hvac_takeoff/test_hvac_takeoff.py` inserts `hvac_takeoff/` onto `sys.path` and does
`import hvac_takeoff as H`, which binds `sys.modules["hvac_takeoff"]` to the flat module
`hvac_takeoff/hvac_takeoff.py` itself; `industries._hvac()`'s later `import
hvac_takeoff.hvac_takeoff as m` then fails because that name is no longer a package. A bare
`python3 -m pytest` from the repo root -- the exact pre-push check this file's own standing
instructions require -- collects both files in one process and would hit this. Worth fixing
before the next real pre-push run, but it is unrelated to this item and left open here.
