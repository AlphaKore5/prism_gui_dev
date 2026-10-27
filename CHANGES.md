# What changed

Written for the person who has to pick this up later — each entry says what it
was, what it is now, and why the change was made, because the "why" is the
part that gets lost.

Tests: **1966 passing** (6 skipped, 8 Sep 2026 after Round 16 landed on main — see
`.claude/agents/prism-test-doctor.md`), plus 148 scenario checks
(`devtools/scenarios.py`).

---

# 1.6.13 — Dev builds keep your folders; choose where files go; Uninstall (27 Oct 2026)

- **Dev builds no longer change Windows' idea of your folders.** They used to redirect the
  whole home setting, so the file picker lost Desktop, Downloads, Documents and Pictures
  and opened in the install folder. They now keep their own data folder without touching
  Windows. In every build, dev or not, file and folder pickers now open in your real Downloads
  instead of whatever folder Prism was started from.
- **Choose where Prism saves your files** (Settings > Privacy & data): generated files,
  STEP files and Gerber reports each have a folder box; empty means the usual place.
- **Uninstall** (Settings > Privacy & data), two choices. "Uninstall Prism" removes the
  program only; settings, licence, History, logs and every file Prism made stay. "Uninstall
  Prism and everything it stored" also removes Prism's data folder (settings, licence,
  History, logs, browser logins), the licence key saved in the system's credential store,
  and the "Prism ..." folders Prism created on its own in their usual places. A folder you
  chose in Settings is never removed, whatever it is called, and neither is the shared
  workspace; both are listed as left alone. A development build removes only its own data
  folder (the made-file folders and saved key belong to the normal Prism too). If Prism is
  still running when the remover stops waiting, nothing is removed. The program folder is
  removed only if it holds nothing but Prism (a copy dropped straight onto the Desktop is
  refused, not deleted). Not yet run on a real Windows PC: try it on a spare one first.
- **Dev builds only:** a card to bring settings, the Groq key, browser logins, History and
  tools across from your normal Prism, which is only read, never changed.
- Not part of this app, listed so it is not lost: the licence server (deployed separately, not yet)
  lets the console mark one computer as Development, so an older dev build follows the dev
  version numbers without touching what customers are told.

---

# 1.6.12 — Activation says what is wrong; builds say which channel they are (27 Oct 2026)

- **The Activate button explains itself.** A key copied one character short used
  to leave the button grey with no reason. The activation window now says how
  many characters the key has, or that it does not look right, or that the two
  documents still need opening. Three new strings, not yet translated.
- **Licence requests carry the release channel** (`X-Prism-Channel`), so the
  licence server can offer a dev build its own version numbers without touching
  what production customers are told. Builds before this send nothing and count
  as production.
- **A release now waits for the tests** in CI; a red test stops it.

---

# 1.6.11 — The updater moves to the AlphaKore5 organisation (25 Oct 2026)

- **Updates are fetched from the AlphaKore5 organisation first and the old
  repository second.** Every file is checked against the signed manifest on
  whichever host served it, so a host that is down or serves a wrong file costs
  nothing more than a fallback.
- **Updates now download quietly in the background** and show a "Restart now"
  banner when ready. Nothing restarts while a task is running.
- **Signed rollout, minimum-updater and revoke fields** let a release reach 5%,
  25%, then everyone, and be withdrawn if it misbehaves. Older apps ignore them.
- **Each update reports back how it went** (installed, rolled back, why it
  failed) to the licence server, so a release can be judged by devices rather
  than by guesses.
- **Dev builds are separate**: their own signing key, their own update repository
  and their own home folder, so testing an update can never touch real data.

---

# 1.6.10 — BOQ: its own agent lists, a live follow-up window, real output files (21 Oct 2026)

- **BOQ's writer/research agent pickers no longer share the engine's CATEGORIES
  list.** They live in `addons/boq/agents.py` now, so editing which tools BOQ
  offers can never change what Leads, Content or Visual offer. Writer gains
  Groq (in-house, a direct API call with no browser tab), Grok, DeepSeek and a
  text-only Gemini (separate from the existing image-making "Google Gemini"
  entry); Research gains Claude and ChatGPT.
- **"Verify and remake" and a follow-up now show a live progress window** —
  the same Run-screen language the rest of Prism already uses — with Skip,
  Use fallback and Stop, and a Claude → Kimi 2.6 fallback chain that tries
  automatically if the chosen tool errors out (ChatGPT's memory limit, most
  often).
- **A follow-up's new file no longer gets lost.** Nothing previously tracked
  what an AI stage actually produced; the "anything to change?" window always
  showed the original measured-quantities CSV no matter what a follow-up had
  just made. It now shows the newest real file first.
- **"Verify and remake" can actually produce a file**, in a format you choose
  (a new "File format" picker: Word / CSV / PDF, or let the tool decide) —
  it used to come back with nothing to open, in any format, ever.
- **Its progress window says up front that a drawing-scan run can take up to
  20 minutes**, instead of reading like it had stalled; the run itself now
  gets that much time rather than being cut short.

# 1.6.7 — Email inquiries: newest first, no zero acknowledgements, quieter mail check (15 Oct 2026)

- **The Inquiry column shows the newest mail first.** With 15 inquiries the one that had
  just arrived sat at the bottom, below the fold, and read as "it never arrived".
- **An order Prism cannot price sends nothing.** A PO naming no rate-list code priced to
  zero lines, and the acknowledgement still went out as a quotation for ₹0.00 with a new
  quotation number. Prism now says nothing could be matched and stops.
- **The mail check no longer logs "Groq no longer offers the saved model" on every call
  or rewrites the config each time.** Calls with no model named start at the chain's
  first entry, which is not a retirement; the check now passes the owner's saved model to
  every AI call, not only the sorter.

- **The licence is far less likely to be asked for again after an update.** Prism now reads the licence
  before the background renewal starts rewriting it, retries a read that fails for a moment (Windows
  blocks reads while a file is replaced or virus-scanned, which used to look like "no licence"), finds the
  Mac machine id by its full path, and writes a line to the log whenever the licence screen is about to
  appear saying why.
- **STEP: pictures and files open when clicked, on Mac and Windows.** Clicking a picture in the Files tab (it
  now shows a thumbnail), a file row, the drawing sheet, or a built / styled file in the chat opens it in its
  own window with the computer's own viewer. Each platform's own opener is used (`open` on a Mac,
  `os.startfile` on Windows, `xdg-open` on Linux) instead of Qt's, which did nothing for local files on
  the packaged apps.
- **Settings tells you it saved, and checks your Groq key.** Settings is a window over the app, so the
  "Saved." that used to appear in the app's status bar was hidden behind it and a Save looked like nothing
  happened. A message now appears at the foot of the Settings window (green saved, amber warning, red
  problem); saving a Groq key also asks Groq whether it works and says so ("Saved — Groq accepts this key", or
  "Saved, but Groq rejected this key…"). The STEP screen now always uses the app's current settings, so a
  key saved after it was first opened is the one it uses. The default look is a plain white screen — no
  wallpaper, no logo — until a wallpaper is chosen in Settings → Appearance.
- **STEP: Ask and Edit are two different things, and every answer says who gave it.** Fixed from a
  tester's report: a follow-up no longer overwrites the first answer (two questions used to show one
  answer); choosing Groq no longer opens ChatGPT — Groq's answer is planned by Groq, in-house, with no
  browser; the chat under an Ask has one button, "Ask", and "Make a change" appears only while you are
  changing the model (the old "Build this" is gone); the main button reads "Ask" or "Make a change";
  a question typed into Edit stays on the answer instead of opening an empty Plan tab; each answer, follow-up
  and plan is labelled with the AI that wrote it (Groq, ChatGPT or Claude) and that survives a reopen;
  follow-ups and the plan are given the whole conversation, not only the last reply; and answers are no
  longer cut off at the bottom.
- **One loader everywhere.** Waiting now looks the same on every screen: a staged pipeline (STEP, Reel,
  Motion, BOQ, Gerber) shows a segmented bar with its stages (Measure · Plan · Build · Check) and a live
  clock; the mail check and other counted waits show a ring; waiting on an AI tool (the email writer) shows
  Prism's orb; the button that started the work says "Working ●●●" and is disabled until it is done; WhatsApp
  chat and contact lists show placeholder rows while they load. The main run's header is a segmented bar, one
  segment per step; Make a plan shows the orb ("Checking your licence…", then "Making a plan…"); the update and
  FFmpeg downloads, and opening the sign-in tabs, use the same ring in a small window; the Drive picker and
  Leads show the ring beside their status line. One component, `widgets/loader.py`.
- **Terms of Use and Privacy Policy read like documents.** A contents list on the left follows you as you
  scroll, the text is typeset with a readable line length and real tables, and the "draft, not yet reviewed"
  note is a visible notice above the text instead of a grey quote inside it. The wording is unchanged.
- **STEP is one screen, and one chat per part.** It opens straight into its workbench — no front door,
  no stacked windows. History on the left lists chats, not runs: everything done to a part and its edited
  copies (draft, ask, edit) is one thread. Open it a week later and both files are offered to carry on from —
  the original and the edited copy. A past STEP run opened from History or Home lands here too. A chat starts empty when a file is attached and counts what is done in it (0, 1, 1+n); a new file
  is a new chat, and old chats are reopened from History. The Chat tab is organised to scan: a count, numbered
  jump dots, runs grouped by day as one-line rows (newest open, answers rendered as Markdown). Nothing opens over
  the window any more: an Ask's answer appears in the Chat tab with a follow-up box (and Build this) under it; an
  Edit's plan appears in the Plan tab with a Build bar — nothing is built until you press it, no browser page
  opens, and a plan with nothing to build says why and what to do next; errors show in the window. The chat
  lists the newest run first. The checks before a run (no question typed, Groq without a key, Edit without a
  reasoning tool) now speak in the window too, and a styled ChatGPT copy of the sheet is named on its Draft card.
  **Delete from the left bar:** a bin on each History chat removes the chat's run records (the files stay), and
  a bin on a model removes the folder Prism made for it — only a folder directly inside your STEP folder, never
  your original STEP file, and only after you confirm.
- **STEP is a workbench.** One screen with three columns — models and options on the left, the
  drawing sheet and one action at a time (Draft / Ask / Edit) in the centre, and the results in
  tabs on the right (Measured · Answer · Files). Options and the K-factor sit away from the main
  flow; the question box shows only for Ask and Edit; the Files tab lists every file written for
  the models, with Open and Show. All the measuring, asking, planning and building code is unchanged.

---

# 1.6.6 — a removed file could still be measured and billed (15 Oct 2026)

**1.6.5 was never signed for in-app update — this release supersedes it.**
CI's own Windows test run caught a real bug before anything shipped: on
Windows, clicking a file chip's "x" in STEP or Gerber could make the chip
disappear while the file stayed in what Generate actually measures — a
path-representation mismatch between AskPanel's own abspath'd storage
and each dialog's separate, unnormalised list. Gerber had a second copy
of the same root cause that could double-count a single dropped file.
Both dialogs now store and match paths the same way AskPanel does
(abspath'd, compared by normcase), with a regression test per add-on
that reproduces the mismatch on any OS, not just Windows. See 1.6.5's
entry below for everything else carried forward unchanged.

---

# 1.6.5 — STEP Edit actually finishes, and a build's confirmation (15 Oct 2026)

A customer running Edit on the same model more than once got an
identically-named file every time, and once the build finished saw no sign of
where it landed. Both were engine/GUI pieces that had been written but never
reached a release on `prism_terminal`.

- **Every build's filename is now stamped** with when it was written
  (`stepfile.modified_name()`), so repeat Edits of the same model stop
  overwriting each other under one flat name.
- **The green "Saved — the file is at ..." confirmation** that already showed
  after a measurement now shows after a build too — a completed Edit gave no
  visible sign of where the modified file landed.
- **A reviewing agent's wordier part name** (e.g. a planner adding "— 1 NOS"
  to a measured part's real name) is now accepted as a prefix match, not
  required to match exactly — before this, a real, reviewed plan could
  silently apply nothing, or raise "Nothing in the plan could be applied"
  outright.
- **The in-app review page** no longer tells the reader to "go back to the
  terminal and answer Y" — that page is shown inside Prism's own Build/Cancel
  dialog too, where there is no terminal to go back to.
- **A model's saved conversation thread** (`names()["conversation"]`) now
  actually saves — the GUI has called this key since 1.6.2, but the engine
  pinned into that release never carried it, so every save silently failed.
- Gerber: a tool-table-looking line plus an X-looking line anywhere in an
  unrelated file (a BOM, a dimension note, a panel legend) no longer reads as
  an Excellon drill file — both checks also require the `%` every real
  Excellon file has, header or not.
- Carries 1.6.4's Email inquiries fix forward (see below) — this is the
  first release with both the STEP fixes and the pipeline-board restoration
  together.

---

# 1.6.4 — Email inquiries works again (14 Oct 2026)

1.6.2 and 1.6.3 shipped with two stale copies of `addons/inquiry/dialog.py` and
`quotation.py` (from a machine that had not pulled the pipeline-board work), so
they **overwrote** it. The Email inquiries screen crashed on open
(`enter() got an unexpected keyword argument 'view'`), and the colours, multi-delete,
PDF quotations, OCR confidence rule and the pipeline board were missing.

- **Restored** both files from the board build and re-applied the 1.6.2 additions
  on top (All-mail Mark as reminder, Delete selected, Reset everything, View
  attachments, Time received, resizable All-mail columns) — a three-way merge,
  not a copy. All-mail now picks several rows (its Delete selected needs it).
- **Engine pieces those additions called but never had**: `worklist.remove`,
  `worklist.clear`, `worklist.entry_key`, `register.remove`, `register.clock`; and a
  mail the sorter cannot place but that sits on an open inquiry's own thread now
  counts as that customer's reply.
- **Guard**: a test pins `enter()`'s keywords against what `main_window.py` passes,
  and another opens the screen the way the main window does.

---

# 1.6.3 — the 1.6.2 release, published (14 Oct 2026)

1.6.2 never reached customers: its build was too big for GitHub to host (see
below), so CI stopped before publishing. 1.6.3 is the same content and nothing
else new, plus the fix. Everything listed under 1.6.2 ships in 1.6.3.

- **Updates: a build too big for one GitHub release is now hosted across
  several.** GitHub allows 1000 files on a release and Prism hosts every file of
  an update separately. STEP's engine (cadquery, OCP, vtk) took Windows to 1466
  files and Linux/macOS to 1542, so the build failed at "Generate the (unsigned)
  update manifest" on all three. Past 900 files each file now names its part in
  the signed manifest; part 1 stays at `<tag>-assets-<platform>` where older
  builds look, and the rest continue in `-2`, `-3`. `release_all.py` creates and
  fills every part. A build under one release's worth is unchanged.
  **Consequence:** a 1.6.1 or older app cannot finish an in-app update to a
  multi-part version, so its first update to 1.6.3 falls back to the browser
  download; every update after that is in-app. See `RELEASING-UPDATES.md`.
- **STEP: Edit and the saved conversation no longer fail on the engine that is
  on GitHub.** The STEP screens were written against a newer local engine than
  the one that was ever pushed. Two things they call were missing there:
  `core.stepfile.modified_name` (every Edit failed at its first line) and the
  `"conversation"` entry of `core.stepfile.names()` (opening or saving a model's
  conversation raised `KeyError`). The GUI now builds both names itself when the
  engine cannot (`addons/step/workers.py::_modified_name`,
  `addons/step/dialog.py::_conversation_path`), in exactly the shapes the engine
  uses, so a later engine that has them changes nothing. Still engine-side and
  unpushed: the email-inquiry "delete many" / "clear" actions
  (`worklist.remove`, `worklist.clear`).

---

# 1.6.2 — release roll-up (14 Oct 2026)

What this version carries on top of 1.6.1: the full Email Inquiry pipeline
board (numbers, multi-delete, files, quotation PDF, Excel export), a
redesigned STEP addon with a split Ask/Edit flow and per-model fallback, Lumi
as a dockable edge button, Enter-to-go on Make a plan and Start the work, and
the leads bulk bar cleanup. See `docs/handover/HANDOVER-2026-10-14.md` for the
full handover and open items.

- **Email Inquiry — every inquiry gets its own number.** A second,
  fresh-subject enquiry from a customer with an open inquiry was folded into
  the first one: same number, same folder, product overwritten. `register.find_by_thread`
  now joins a mail onto an earlier inquiry only when it is clearly a reply
  (thread headers, a mail that names the inquiry or quotation number, or a
  Re:/Fwd: whose subject is that open inquiry's "Product asked" or the subject
  of a mail we sent on it). A forwarded "Fwd: Enquiry for SS lockers" from the
  same buyer is a new inquiry, and so is a mail with no reply markers at all
  even with a quotation open. The "customer wrote again" refresh of a New row
  runs only on a thread or named-number match (`register.match`).
- **A number is never handed out twice.** The next number now also sits above
  every `inquiries/INQ-*` folder, every saved `QTN-*` file and every quotation
  subject in the sent log (`mailflow.numbers_in_use`). The inquiry screen saves
  through `register.save_merged`, so its in-memory copy can no longer erase a
  row added by a check, a second Prism or Excel since it was read.
- **Imported sheets:** "Inquiry No.", "Enq No", "Email ID", "Mobile" and similar
  are read as Prism's own columns so imported rows keep their numbers.
- **Matching tightened:** a "Confident match" made of numbers alone never
  counts; a lone candidate needs two shared words (`quotation.confident_match`).
- **Delete several at once** on To quote, No answer yet and All inquiries
  (ctrl/shift-click): one question listing the rows, one "block these senders?",
  one write. On They answered / Order came, Delete only takes the mails off that
  list; the inquiries stay in the register.
- **Files:** the customer is sent the quotation as an A4 PDF on the company's
  name (₹ in lakh grouping, aligned table; drawn by Qt). All inquiries has
  "Save as Excel…" with real dates, phone numbers, money as numbers, status
  colours. Saved attachments carry their inquiry number (`INQ-26-27-0005_drawing.pdf`);
  each mail is kept in its folder as an `.eml`.
- **A mail check no longer undoes changes made on screen while it ran.** The
  check now re-reads the file and applies only what it did — new rows, and the
  fields it changed. Every register write takes `inquiries.csv.lock` with a
  5 s wait, 30 s crash takeover, and Windows retry.
- **Deleting is by the row, not the object on screen.** Rows are found by
  inquiry number (or Email + Date + Product), the timer waits while the question
  is open, and the status line counts only what actually left the register.
- **One colour per state:** yet to quote blue, quoted grey, following up amber,
  negotiating orange, won green, lost red. The hexes live in `theme.REGISTER_TONES`.
- **Inquiry pipeline board:** new `addons/inquiry/board.py`, `drawer.py`,
  `pipeline_actions.py`, `pipeline_setup.py`, `documents.py` carrying the full
  kanban-style pipeline view; `InquiryDialog` is now a plain embedded screen
  (not a modal), navigated to like Home or Settings.
- **A customer's attachment becomes a Prism attachment in one click** from inside
  the inquiry screen or the quotation window (`inquiry_work_panel.attach_to_prism`).
- **STEP addon — Ask and Edit are now separate actions** instead of a single
  multi-step flow.
  - **Ask** now delivers an immediate answer in a new `AnswerDialog` popup — no
    plan page is opened, nothing is built. The footer button says "Get the
    Answer" so the action is never ambiguous.
  - **Edit** inherited the review page: measure, get Groq's suggestions, review
    the exact change plan on a new `PlanReviewDialog`, confirm, then apply to a
    copy and re-measure. The footer button says "Make the Changes".
  - **Model picker** (Groq / ChatGPT / Claude) with a fixed fallback order
    (`FALLBACK_ORDER`) — the stash's Groq-only path is gone; Gemini is
    deliberately excluded (its `_maker_brief` wrapper refuses a plain text Q&A).
  - **`ACTION_BUTTON` dict** gives the footer button a label and icon per action
    so the single button always names the actual result.
  - **`AskPanel.file_removed` signal** emitted when a chip is removed, so Gerber
    and STEP keep their own path lists in sync. Without this, the chip vanished
    but the owner's list kept the file; Generate still ran it.
  - **History step conversation rendering** (`dialogs/history_dialog.py`):
    STEP's own response keys (`ask · <model>`, `plan · <model>`, etc.) are no
    longer listed as pipeline stages; they are rendered as a labelled
    back-and-forth (`_step_conversation`) when the conversation file exists, or
    fall back to the raw text for entries predating this change.
- **BOQ / BOM follow-up guard** (`main_window.py`): `owns_followup` flag prevents
  the main window offering the generic routed-pipeline follow-up after a BOQ or
  BOM run that already owns its own follow-up dialog — the dead-end where
  ChatGPT wrote code-looking text but no file appeared is closed. STEP
  deliberately does not offer the generic follow-up at all for the same reason.
- **Lumi as a dockable edge button.** Lumi now pins to the window's right edge
  so it is reachable on every page without covering action buttons or form
  fields. Bulk-select mode in Leads hides the pill cleanly.
- **Enter moves the task on.** "Make a plan" and "Start the work" no longer need
  the mouse; pressing Enter on the input moves to the next step.
- **Leads polish.** The bulk bar clears the Ask-Lumi pill; header and chip fit
  fixes.
- **Engine (prism_terminal):** updated submodule pin.

---

# 1.6.1 — release roll-up (9 Oct 2026)

What this version carries on top of 1.6.0. The review findings are in
`docs/handover/HANDOVER-2026-10-02.md`.

- **From the 1 Oct app review:** a partial e-mail send no longer vanishes after a
  reconnect failure; closing the app stops the Leads workers; cancelling the run
  confirmation no longer leaves auto-run armed; "Not now" on the update banner
  returns after 24 hours instead of hiding it for good (Settings keeps the card);
  Leads outreach honours the send pace and a daily limit counted across runs, and
  the suppression list is per sender.
- **Found by running the real app:** unsupported files (`.zip`, `.doc`) opened
  nothing instead of the "open externally" dialog (live in 1.6.0); Discard kept
  attached files in memory only; the Leads Removed window's Restore crashed; the
  delete-contact box read the name as markup; Home's demo video showed a raw file
  name; page subtitles and header buttons were cut off; the Appearance wallpaper
  tiles were unstyled; the AI tools card column was clipped; the Email account
  dialog's field text was clipped.
- **Lumi:** the launcher no longer covers Discard, Start the work, the Inquiry
  Back button or the last row of a page, and now also leaves the setup wizard's
  Next button clear (its pages scroll on a short window instead of clipping).
  Lumi answers the Chrome-connection and "other browsers" questions and no longer
  names Settings buttons that do not exist.
- **Look:** every role's palette is pinned, so the app stays light on any desktop
  theme.
- **Engine:** ChatGPT's new composer and reply markup, and a busy check that
  cannot return the previous answer.
- **Open login tabs** opens on a worker and always says what happened; a Chrome
  that holds a file open no longer fails the profile copy, which is why the button
  did nothing on a fresh Windows 10 install.
- **Inquiry:** a double-click on any row opens the mail in full (body and the
  names of what was attached), and every row is colour-graded (New green, Quoted
  grey).
- **Release tooling:** `devtools/release_all.py` releases Windows, then Linux, then
  macOS, and takes `--only <platform>`.

Still open: §4 of the handover.

---

# 1.6.0 — release roll-up (1 Oct 2026)

What this version carries on top of 1.5.8: Rounds 37-40 and 47-52 from the
engine (Gemini in Visual & Image, a Mac with no Chrome could not start one,
STEP flat-pattern K-factor, PNG-only rendering, Gerber rotated-board and
unit-picker fixes, NotebookLM in the audio category); automation and Reel
Studio work in `prism_terminal` (busy send buttons with attachments, run-state
reset between tasks, reel editor and Studio editor); bundled wallpaper presets
and custom wallpapers in Settings; the new Lumi welcome card and help centre;
and release-bundle trimming to stay under GitHub's 1000-assets-per-release cap.

---

# Round 52 — a rotated copy of the same board was counted as a different board, and the array undercounted a real panel by 8 boards

Reported by the manufacturing company field-testing Gerber automation:
Prism's own answer sheet against the client's real fab quotation for the
same job. Board size matched the client's figure exactly (25.50 x
11.40mm, to the fourth decimal in inches) — the single-unit outline
reading was never the problem. The array was: Prism said 28 boards in
a clean "4 x 7" grid, 110.00 x 118.59mm; the client's own quotation
form said 36 pieces, 121.6 x 133.6mm. Not noise — a real 8-board, real
~12-15mm gap, and the reviewer's own words: "the filter... doesn't work
correctly" on the newer, more complex panels they're seeing now.

**Root cause, in `panel()` (`core/gerber.py`):** candidate board-sized
faces on the outline layer are grouped into "the unit" by their own
(width, height), rounded — the assumption being that every copy of the
same board is drawn the same way round. A modern fab panel mixing
orientations to pack the frame tighter (a real, ordinary practice, not
an edge case) breaks that assumption directly: a board turned 90°
has its width and height SWAPPED, so it lands in a completely
different size bucket than its own un-rotated twin, and the code kept
only the larger bucket — silently treating the rotated copies as if
they were not there at all.

Reproduced from first principles, not guessed at: a synthetic 75 x
50mm panel — four 20 x 15mm boards in a block, two more of the exact
same board turned 90° filling the rest of the frame, six real boards —
came back "28 of 36"-shaped wrong two different ways depending on
whether a frame face happens to fully enclose the missed units:
sometimes an undercounted array (the client's own shape: some real
count, smaller than true), sometimes the whole detection rejected
outright and the entire panel reported as one giant "board" the size
of the full frame (the fill-ratio sanity check — correctly there to
catch decorative repeats — tripped by real boards it could not see).
Both are the same root cause.

**The fix:** the grouping key is now the SORTED (width, height) —
`tuple(sorted((w, h)))` — so a board and its own 90°-rotated copy land
in the same bucket, the way they are the same physical board on the
panel. The reported single-board size can no longer come from
whichever copy the group happens to start with either: it is now the
DOMINANT orientation among the real units (a plain tally, not
`units[0]`), so a mostly-one-way panel with a rotated minority still
reports its board the way most of the panel actually reads it.

Verified against the real customer sample jobs already in the suite
(`PRISM_SLOW_TESTS=1`) — unaffected, as expected: none of them mix
orientations, so sorting a key that was already symmetric changes
nothing for them. The fix only changes behaviour for exactly the case
it targets.

**What this does not do:** it does not fix every possible "complex
panel" failure mode — only the one this specific report's numbers
pointed to and that a synthetic reproduction confirmed. If the same
account hits another wrong array on a different kind of newer panel
(non-rectangular tiling, mixed board sizes on one panel, rails that
don't close as a single face), that needs its own real numbers to
diagnose the same way this one was — a guess fixed against no
reproduction is exactly the kind of change this project does not make.

Files: `prism_terminal/core/gerber.py` (`panel`'s grouping key and
board-size reporting), `tests/test_gerber.py`
(`ARotatedCopyIsStillTheSameBoard`, `PANEL_MIXED_ORIENTATION`).

---

# Round 51 — when ChatGPT's image limit ran out, the fallback chain handed a photo-composite job to a template tool, then to a page with no upload field at all

Reported from a real run: a request to composite a product hamper photo
from 6 reference images. ChatGPT hit its own free-tier image limit,
Prism failed over to Canva — which came back generic, because Canva
builds an editable template and cannot use reference photos for a
photorealistic composite at all — then failed over again to Google
Gemini, which never received a single one of the 6 attachments.

**Canva was never going to be able to do this job.** `alternatives_for()`
picks a fallback by catalogue order alone: "visual" lists Canva first,
deliberately, "because most business visual work is a post or a
brochure" — a real, reasonable default for THAT case. But this project
already has a signal for the other case: `wants_canva()` reads the
customer's own words for "canva", "editable", "template" and so on, and
already keeps the PRIMARY tool from routing an ordinary image request
through Canva (`NO_CANVA_INSTRUCTION`). It was simply never reused for
the fallback choice — so a photorealistic composite request, which
`wants_canva()` would correctly say no to, still got offered Canva the
moment the primary tool failed. Fixed by having `alternatives_for()`
(now taking the user's own task text) exclude Canva from "visual" and
"presentation" fallbacks unless that same signal says the customer
actually asked for something editable — the legitimate case keeps
working, verified with its own test.

**Google Gemini attaching zero of 6 files was a second, separate bug.**
Confirmed live, end-to-end, by driving the real gemini.google.com page:
a freshly loaded page has ZERO `<input type='file'>` elements anywhere
on it — not hidden, not slow to render, none — until the button beside
the composer, aria-label "Upload & tools", is clicked; clicking it
mounts a hidden file input, and assigning a file to that input directly
produced a real attachment chip and enabled the send button, confirming
the whole path works, not just that the button exists. The 15 Sep
registry note that verified Gemini only ever tried a TEXT prompt, no
reference photos, which is exactly why this went unnoticed: no amount
of the upload path's existing wait (Round "composer renders late" fix)
ever finds an input that the page has not created yet. `_upload_files`
now tries a short list of candidate "reveal the upload control" buttons
first when a tool declares them (`upload_trigger_selectors`, new,
currently only set for Google Gemini) — silent and best-effort, so a
tool that never needed this is untouched either way. One more real find
along the way: the revealed input's own `accept` attribute lists
document types only, no image extension in it at all — turned out to
be a picker-dialog hint only, not an enforced filter, so an image still
goes through it without issue.

**What this does not do:** it does not change why ChatGPT hit its
image limit in the first place — that is ChatGPT's own account quota,
outside Prism's control; the fix here is that the fallback Prism reaches
for next is now one that can actually do the job.

Files: `prism_terminal/core/agents.py` (`alternatives_for`'s new `query`
parameter and Canva exclusion, Google Gemini's `upload_trigger_selectors`),
`prism_terminal/core/automation.py` (`_upload_files`'s trigger-click step,
`_retry_failed_stages`' call site passing `query`),
`tests/test_failover.py` (Canva exclusion/inclusion tests),
`tests/test_cross_platform_browser.py`
(`AComposerThatMountsItsUploadInputOnlyAfterAClick`).

---

# Round 50 — a real 6-photo attachment was reported "only 2 of 6 reached ChatGPT" while it was still uploading

Reported straight from a real run's own terminal log, across several
automation attempts on the same job: "📎 verified 6 file(s) attached to
ChatGPT" the first time, then later runs on the same kind of job coming
back "⚠️ only 2 of 6 attachment(s) reached ChatGPT — the rest never
appeared on the page", and separately "⚠️ only 2 of 6 attachment(s)
reached ChatGPT" on a fresh conversation with no prior failure nearby —
not a browser crash, not a rejected file, an upload that was still
legitimately in progress.

**Root cause, in `_verify_page_attachments` (`core/automation.py`):** a
real upload of several photos lands progressively — the browser reads
and thumbnails each file in turn, so six camera photos can still be two
chips deep half a second in. The polling loop broke on the very FIRST
poll that saw ANY chip, any matched filename, or any busy indicator —
so whatever partial count happened to be on screen at that one instant
was reported as final, even though the rest of the very same upload
would have shown up within another second or two. Not caught by the
existing tests because the fake driver they use always returns `False`
from `execute_script`, which sidesteps this function's real counting
logic entirely (falls straight to the "assume everything worked"
fallback) — a gap closed here with a driver that actually returns
growing chip counts across polls, the shape of the real bug.

**The fix:** keep the BEST count any poll has seen rather than the
FIRST, and only stop once it has held steady — no growth, nothing still
marked busy — for a short grace window (1.2s), or every file is
accounted for, or the overall timeout runs out. The verification
window itself also now scales with how many files there are to wait
for (5s plus 1.5s per file beyond the first, capped at 24s) instead of
a flat 5s that was never enough room for six real photos to finish
rendering — the stability check still returns early once they are all
in, so this only matters when the upload is genuinely still working.

**What this does not fix:** the same log also showed several browser
crashes ("no such window: target window already closed", "invalid
session id") following repeated warnings that Chrome had auto-updated
mid-session (pinned v152, running v153) — a separate, real instability
this round did not touch. Worth running `/chrome` to update or clear
the pin before the next long automation run; making the pipeline
recover from a browser that closes mid-run is a bigger, different
piece of work than an undercounted upload.

Files: `prism_terminal/core/automation.py` (`_verify_page_attachments`,
`_upload_files`'s verification timeouts), `tests/test_cross_platform_browser.py`
(`ASlowBatchIsNotUndercounted`).

---

# Round 49 — overlapping red callouts on a real generated job now get a leader line instead

Checked directly against the actual PNGs a real run of this job produced
(`~/Desktop/Prism Step/Assem1 (7)/`) — not a synthetic case: on "top", a
hole's Ø, one cutout's size and a second cutout's size all landed on
the same few pixels, unreadable. On "bottom", a cutout's size label
sat on top of a completely different, nearby hole's own drawn circle.

**Root cause.** Every callout (`_draw_flat_pattern`'s cutout-size and
hole-diameter labels) was placed "beside its own shape" — a fixed small
offset from that one feature, with no idea any other feature's label,
or even another feature's own drawn shape, might already be sitting
there. Fine when features are spread out; on a real job with several
small holes and cutouts within a few mm of each other, several labels'
"beside" spots landed in the same place.

**The fix, the way it was asked for:** a leader line. New
`_place_label()` tries a label's normal spot first — nothing changes
for the common case, a label reads exactly where it always has — and
only when that spot collides with something already on the page (checked
against a shared `label_boxes` list every cutout, hole and label
registers itself into, in two passes: every shape is drawn and
registered first, every label placed second, so a cutout's label
already knows about a hole drawn later in the old single-pass order,
which is what let it miss that hole before) does it try further
positions — straight out along the same direction, then fanned out to
other compass directions — and draw a thin line from the feature back
to wherever the label ended up. Every real feature still gets its
number; a crowded one just points at it from open space instead of
printing on top of something else.

Verified by rendering the actual job at every step, the discipline this
whole feature has followed since Round 41 — not by trusting the
collision math alone. Round 47's `flats` cutting images are exactly
where this mattered most: a shop-floor image just filling the page
means labels routinely sit close together now.

Files: `prism_terminal/core/stepfile.py` (`_label_box`, `_boxes_overlap`,
`_place_label`, `_draw_flat_pattern`'s cutout/hole labelling
restructured into a draw-then-label two-pass), `tests/test_stepfile.py`
(`test_no_two_red_callouts_overlap_on_a_real_generated_job`).

---

# Round 48 — the STEP sheet is drawn straight to PNG now, no HTML, no SVG, no browser

Real feedback from a real job's output: too many files (an HTML page, a
combined SVG, and one more SVG per part for the isometric alone), and a
confusing cluster of short crossing lines at the "side" part's own
stepped corner in what a person actually looks at. Both addressed.

**File count and format.** `render_sheet()` used to write an HTML page,
a combined SVG, and `<model> - view <part>.svg` for every part's
isometric — main reason for the isometric SVGs' existence was letting
someone open one part's 3D view alone, but nobody asked for that and it
tripled the file count for no deliverable purpose. It also only ever
produced a PNG when Playwright's Chromium happened to be installed —
optional, and the exact class of fragility Round 38 already burned this
project on once (a fresh Mac with no Chromium). Now: two kinds of file,
both PNG, always produced, no browser involved —

  - `<model> - drawing sheet.png` — everything, one page (same content
    the old combined SVG had: every part's flat pattern or formed
    3-view, isometric, hole table, notes, title block);
  - `<model> - <part> - flat pattern.png` — one per part that has a
    flat pattern, that part ALONE, full page width and height (no
    isometric column sharing the page with it — a standalone cutting
    image gets to be bigger and clearer, not squeezed into the corner
    the combined sheet's layout would give it), no title block either
    since the caption at its own top already carries the job/part/size.

For this job (3 parts, all 3 flat): 4 images total, exactly what was
asked for, replacing what used to be up to 5 files (1 html + 1 svg + up
to 3 more svg) of which the png only sometimes existed at all.

**How, without a new dependency:** a second drawing backend, `_Canvas`,
implements the exact same method surface `_Sheet` (the SVG backend)
already does — `text`, `line`, `rect`, `polygon`, `circle`, `arrow`,
`view`, `dim_h`/`dim_v` (borrowed unbound from `_Sheet`, since they only
ever call `self.line`/`self.arrow`/`self.text`, which both backends
implement) — so `_draw_flat_pattern`, `_draw_part` and `_title_block`
(now called through a shared `_lay_out_sheet(sh, report)`, factored out
of `sheet_svg`) run against either backend completely unmodified.
`_Canvas` rasterises straight to a PIL image, using the same
`assets/fonts/Barlow-*.ttf` Reel's own PIL-drawn frames already use —
no new dependency, just the one this project already has. The
isometric's hidden-line-removal paths (from cadquery's own `getPaths`)
come back as SVG path `d` strings; checked directly against this file's
own real sample, every one uses only M (move) and L (line), cadquery
has already flattened every curve to short line segments before handing
them back — so a small `_svg_path_points()` reader (M/L only, no arc or
Bezier flattening needed) turns them into point lists `_Canvas.view()`
draws as plain polylines.

**A real bug this caught before it shipped:** the first rendered sheet
had every vertical dimension figure (the numbers running up the left
edge of a flat pattern) drawn as garbled, mirrored-looking text.
Traced, not guessed at — isolated the rotation, the paste, and the font
loading into separate scripts and rendered each — to `textbbox()`'s own
top-left corner not being `(0, 0)` (a font's internal ascent/leading
offsets it); drawing the glyph flush at a fixed `(4, 4)` on the tightly
sized temp layer clipped it against the layer's own edge before the
rotation ever ran, which at a glance read as mirrored rather than
clipped. Fixed by drawing at `(4 - bbox[0], 4 - bbox[1])` instead, so
the actual ink lands where the layer has room for it. Caught by
rendering the real sheet and reading it, the same discipline every
other real bug in this feature has been caught by.

**The corner the customer's reference marked as confusing:** checked
directly — it is real geometry, not a rendering bug. The "side" part's
two 276mm² flanges are narrower than the main panel (they stop at
x=87.87mm; the main panel's own stepped corner runs out to x=96.37mm),
so the flange's own edge and the panel's own step legitimately meet at
that point, and the model has a couple of ~0.45mm relief jogs right
there too — real, small, correctly-drawn cuts, not double-drawn
geometry. Whether those sub-millimetre relief jogs are worth simplifying
out of the outline for readability, at the cost of the drawing no longer
showing the exact geometry a cutter would follow, is a real trade-off
between precision and clarity — flagged to the customer rather than
decided unilaterally, since simplifying a real cut line without being
asked is exactly the kind of silent change that could send a wrong part
to the floor. The much bigger, page-filling standalone flat image this
round adds already makes that corner far easier to read than it was
sharing a quarter of a page with an isometric column.

**What this does not do:** it does not touch `sheet_svg()` or the SVG
backend at all — every existing SVG-based test still reads the same
string it always did; SVG is simply no longer written to disk. It does
not change any geometry, dimensioning, or labelling logic — same
`_draw_flat_pattern`, same `_draw_part`, same `_title_block`, called
through the same `_lay_out_sheet`, only a different backend recording
the same calls.

Files: `prism_terminal/core/stepfile.py` (`HAVE_PIL`, `_svg_path_points`,
`_Sheet.polygon`/`circle`, `_draw_flat_pattern`'s new `with_isometric`
parameter, `_lay_out_sheet` (factored out of `sheet_svg`), `_step_font_path`,
`_Canvas`, `names()` — dropped `html`/`svg` keys, `flat_image_name`
(replacing `view_name`), `render_sheet` rewritten, `_svg_of` removed
(dead code, nothing called it once its one caller was rewritten)),
`prism_terminal/prism.py` (the one `drawn['html']` fallback),
`addons/step/dialog.py` (`_on_measured` now saves the flat-pattern images
as artifacts too), `tests/test_stepfile.py`, `tests/test_step_dialog.py`.

---

# Round 47 — the "side" part's missing corner turned out not to be missing; the K-factor back-solve tool

Asked to build everything still on the table: a suspected branching-bend
gap on the "side" part (only 4 of its 28 faces reach a detected bend —
looked, on the numbers alone, like 24 faces of real geometry silently
left out, including one 68.5 x 90.15mm face nobody expects to call a
"small feature"), amboss/boss labelling, dimensioning the panel's own
outline, and the K-factor back-solve tool flagged as needed back in
Round 43 and never built.

**The suspected branching-bend gap did not hold up.** Checked directly
against `Assem1.STEP`'s real "side" part, face by face, before writing
any code for it: all 3 real bends on that part ARE correctly detected
and placed — each of the 6 raw cylindrical candidates touches exactly
one planar neighbour, none of them were ever rejected by
`_group_bends`'s single-neighbour rule. The 68.5 x 90.15mm face is not
missing at all; it is the ROOT panel `_flatten_faces` picks (the
largest reachable face), always placed. Its own outer wire already has
12 points, not 4 — the stepped corner is already IN the outline
`_draw_flat_pattern` draws. Rendered the actual page to check, the same
discipline Round 44 and 46 both leaned on: the step is there, on
screen, at the right size, before this round touched anything.

What the 24 "unplaced" faces actually are, checked one at a time: the
material's own edge-thickness walls of that same step (a sliver no
wider than the sheet is thick — its two long edges lie ON the boundary
the placed face already draws) and the untouched BACK faces of the
panel and its two flanges (same shape, one thickness away, facing the
opposite way — a solid sheet has two faces per panel, only one is ever
what a bend's cylindrical face touches). Not one of the 24 is a
distinct piece of geometry nothing else on the drawing already shows.
Confirmed the same holds on "top" (3 of 68) and "bottom" (8 of 42) —
same pattern, same conclusion: nothing real is missing on this job.

**The fix is the warning, not the geometry.** `"N of M faces unfolded —
small features off the main bend chain are not shown"` read as data
loss on every one of these three real parts, when none had actually
happened. New `_is_trivial_leftover()` in `stepfile.py` tells a genuine
gap (a real face the bend graph could not reach, e.g. a true multi-way
junction, should one show up on a future job) apart from these two
harmless categories, geometrically: a sliver by bounding-box aspect
(narrowest side no wider than 1.5x the sheet thickness), an
area too small to matter, or a same-size, opposite-facing twin of an
already-placed face one thickness away. `unfold()` now reports
`faces_hidden_meaningful` alongside the existing raw counts (kept, for
anything reading them already), and the drawing's own note only fires
on that number — silent on all three of this job's real parts, exactly
as it should be given nothing here is actually hidden.

**Amboss/boss labelling was not built.** Looked for the geometry it
would need to key off — a raised or recessed flat pad near a small
pilot hole, offset from the main panel plane — around every Ø1.2mm hole
on "side" and "bottom" (the sizes that read like amboss pilot holes on
this job). Found none: each Ø1.2 hole's only nearby non-hole faces are
its own cylindrical wall, split into two half-cylinders by the kernel,
radius and length matching the hole exactly. `Assem1.STEP` simply does
not model a real amboss feature, so there is nothing here to verify
detection against — and this file's whole discipline, every round back
to 41, has been to check a change against real geometry before trusting
it, not to write a detector on a description alone and hope. Left
undone, honestly, rather than shipped unverified; revisit if a job with
a real boss ever comes through.

**Outline/corner dimensioning: built.** Position dimensioning
(`_draw_flat_pattern`'s chain) used to read only hole positions — a
panel's own step or notch was drawn (it is part of the outline) but
never numbered, which was the actual, if misdiagnosed, thing worth
fixing here. Its own outline vertices now join the same `_cluster` +
`_chain_points` chain a hole position already used, so a step in the
edge gets a gap number on the same dimension line a hole would, not a
shape a reader has to measure by eye. Verified on the real "bottom"
panel: its 46mm window (Round 45) now splits what used to be one gap
(33.36) into two real stops either side of the window's own edge
(18.08 / 15.28) — a chain that used to only ever see holes now also
sees the panel's own geometry.

**The K-factor back-solve tool: built.** New `solve_k_factor(report,
part_name, target_mm, axis)` in `stepfile.py`. Bend allowance is
exactly linear in k (`_bend_allowance` is `angle*radius +
angle*k*thickness`), and every placed point's flat position is a
straight sum of bend-allowance terms along its own path back to the
root panel — so the whole flat size is linear in k too. Two real
`unfold()` calls (k=0.1 and k=0.9) pin that line down exactly; no
search, no iteration, and no assumption baked in about what k "should"
be. Verified by round-trip on the real job: unfolded "bottom" at a
known k=0.7, fed the resulting width back in as the "true" figure,
solved back to exactly 0.7. Wired into the dialog as a small box under
the measured view — pick the part, say width or height and the true
mm figure, Solve, then "Use this K-factor" copies it straight into the
Bend K-factor field for the next Generate.

**What this round does not do:** it does not add multi-way bend-
junction handling — investigated first, found no real job that needs
it, so nothing speculative was written against an untested case; it
does not detect amboss/boss features, for the same "verify against real
geometry first" reason. Both stay open, honestly, rather than shipped
as a guess.

Files: `prism_terminal/core/stepfile.py` (`_is_trivial_leftover`,
`unfold`'s new `faces_hidden_meaningful` field, `solve_k_factor`,
`_draw_flat_pattern`'s outline-fed chain and reworded disclosure),
`addons/step/dialog.py` (the back-solve box, `_fill_kfit_parts`,
`_kfit_solve`, `_kfit_apply`), `tests/test_stepfile.py`
(`test_nothing_is_actually_missing_on_this_real_job`,
`test_the_panels_own_outline_joins_the_dimension_chain`),
`tests/test_step_dialog.py`
(`KnowingARealFlatSizeSolvesTheKFactor`).

---

# Round 46 — Round 45's own cutout labels overlapped exactly the way Round 44's fix them for holes had already ruled out

Round 45 fixed a real cutout (a 46 x 46 mm window) being drawn as nothing
at all. The fix drew every cutout found — but a ventilation grille is
not one cutout, it is eighteen of them, each a real, individually
present slot in the actual geometry, and the new code labelled every
single one. Same class of bug Round 44 had already found and fixed for
hole positions, reintroduced by the very next round because the new
code path didn't reuse that rule.

**The fix, in `_draw_flat_pattern`:** one label per DISTINCT cutout
size, the same rule hole diameters already follow — repeated instances
of an identical size (the vent slats) get their outline drawn but no
second label. For a cutout too small to hold its own label without the
text spilling past the shape (a few-mm corner relief), the label moves
beside it instead, the same convention a small hole's diameter label
already uses — and where two differently-sized small cutouts still sit
close enough to collide even placed beside their own shapes, each
label's row is staggered, one per label placed that way.

Caught the same way Round 44's bug was: by rendering the actual page and
reading it, not by the code running without an error.

Files: `prism_terminal/core/stepfile.py` (`_draw_flat_pattern`'s cutout
loop), `tests/test_stepfile.py`
(`test_a_ventilation_grilles_cutouts_are_not_each_individually_labelled`).

---

# Round 45 — a real cutout on a real customer part was drawn as nothing at all

Checked against a fabricator's own reference drawing of this exact job
(the same `Assem1.STEP` sample every other STEP round has used) and
found a real, verified square window — 46 x 46 mm, cut into the bottom
panel — completely missing from Prism's flat pattern. Not mislabelled,
not mis-sized: absent. No outline, no gap, no note that anything had
been left out.

**The actual cause.** `unfold()` built each panel's shape from its
face's OUTER wire only. A window or slot cut into the middle of a panel
is one of that face's INNER wires, and nothing in `unfold()` ever looked
at those — the code was never wrong about where the window is, it
simply never asked whether one existed.

**Why holes were fine and this wasn't.** A round hole's boundary is
*also* an inner wire, but Prism already draws every hole correctly, from
its own cylindrical side-wall face (`_holes_detail`) — a completely
separate code path that has nothing to do with a face's inner wires.
That is exactly why this one real customer part still fell through: its
window has no cylindrical face at all (it's bounded by four straight
edges), so the one detector that *would* have caught it never had
anything to catch.

**The fix.** Every placed panel's inner wires are now walked too. A
degenerate one — collapsed to ~zero width in at least one direction,
which is what a round hole's own inner-wire boundary looks like under
this same crude vertex sampling — is skipped, because that hole is
already drawn properly elsewhere; anything with real extent in both
directions is a genuine cutout, drawn as its own outline (filled white,
so it reads as an opening rather than a second panel) and labelled with
its own width x height, the way the reference sheet marks its "46 x 46."

**A second real bug hit immediately while wiring this in**, and fixed the
same session: the new code passed 3D point arrays into a loop written
for 2D tuples (`for x, y in pts` against `[x, y, z]` values) —
`ValueError: too many values to unpack`, caught only because `unfold()`'s
own blanket exception handler was temporarily removed to see it. Fixed
by indexing (`p[0]`, `p[1]`) the same way the panel-outline code already
does, instead of unpacking.

Files: `prism_terminal/core/stepfile.py` (`unfold`'s cutout-detection
block, `_draw_flat_pattern`), `tests/test_stepfile.py`
(`test_the_bottom_panels_square_window_is_not_invisible`,
`test_the_square_window_is_drawn_and_sized_on_the_page`,
`test_a_round_holes_inner_wire_is_not_double_drawn_as_a_cutout`).

**Still open, from the same reference-drawing comparison:** the "amboss"
(boss/emboss) feature is still shown as a plain hole, with no distinction
from an ordinary punched one; the panel outline's own corner/step
geometry (as opposed to hole positions) still carries no dimensions even
where it's drawn correctly; the ~0.14mm-per-bend K-factor shortfall
(Round 43's finding) still has no back-solve tool. Next, in some order.

---

# Round 44 — the flat pattern dimensions BETWEEN holes, not just each hole's distance from an edge

Round 42's position marks answered "where is this hole" (a distance from
one edge). They did not answer "how far apart are these two holes" —
which is what the reference sheet actually shows, and what the owner
meant by "I don't see any measurements": reading the gap between two
features off Prism's sheet meant subtracting two numbers by hand first.

**What changed**, `_draw_flat_pattern` in `prism_terminal/core/stepfile.py`:
position marks are now a dimension CHAIN — edge to first feature, feature
to feature, last feature to the far edge, each its own little arrowed
span (`26.5 -> 90.5 -> 50 -> 3.5`, summing to the whole) — the same
convention the reference sheet uses, not Prism's own datum-distance
convention from Round 42.

**Two real bugs found by rendering the actual page and reading it, not
by running the code and calling it done:**

1. The first version could **drop the far edge itself** during
  thinning, when the nearest real feature sat within tolerance of it —
  the chain fell 2mm short of a real part's own measured height,
  silently. Fixed: both ends of a chain always survive; when a feature
  is too close to an edge to get its own segment, the FEATURE gives way,
  folded into the edge segment, never the edge.
2. The second version chained a dense row (eighteen vent-slot positions
  on the real job) anyway, and the labels printed as an unreadable run
  of overlapping digits. Fixed at the root rather than patched after the
  fact: the clustering tolerance is now derived directly from
  `_Sheet.NARROW` (dim_h/dim_v's own "too narrow to fit a label inside"
  threshold), so every segment that survives clears it by construction —
  no segment is ever built narrow enough to overlap its neighbour in the
  first place. When there are still too many real, well-separated
  positions to chain at all (`_chain_points` returns `None`), the sheet
  says so honestly ("too closely packed to dimension individually — shown
  to scale") instead of forcing a label onto it.

**Verified against the same real job**, `Assem1.STEP` — every chain on
every part now sums exactly to that part's own measured overall size,
and the previously-broken vent row (Round 44's own reason for
existing) turned out, on this particular job, not to need the fallback
at all: the same small scale its tall neighbour forces already collapses
it to two clean segments. Pinned as its own test rather than assumed;
the fallback path itself is proven separately, on synthetic data built
to actually trigger it.

**Still open, from the owner's own comparison against a real fabricated
reference (Round 43's conversation):** the ~0.14mm-per-bend shortfall in
Prism's bend-allowance figure is diagnosed (the K-factor), not yet fixed
with a tool — there is still no way to enter "this part's real flat size
is X" and have Prism back-solve the K-factor that reproduces it. Next.

Files: `prism_terminal/core/stepfile.py` (`_chain_points`,
`_draw_flat_pattern`; `_Sheet.tick_h`/`tick_v` removed, superseded),
`tests/test_stepfile.py` (new classes `TheDimensionChainAlwaysReachesBothEdges`,
plus new assertions on `TheFlatPatternOfTheCustomersEnclosure`).

---

# Round 43 — STEP's "Draft" no longer asks ChatGPT for a picture unless told to

Round 42 found, by actually opening the file ChatGPT drew and comparing
it beside Prism's own, that STEP's Draft action was spending a minute
asking ChatGPT to draw a "styled" copy of a sheet Prism had already drawn
correctly — and what came back was that same picture traced, with the
text garbled in the process ("t≈0.87 mm SHEET" → "t=.rr mm 5MEET"). It
was never an independent check on the numbers; it was a slower, worse
copy of a drawing that already existed. The owner's own words once that
was shown: "if there is no need for chatgpt image generation, than make
it optional."

**What changed.** The ChatGPT drawing step is now a checkbox in STEP's
"What to do" box, off by default, next to a note explaining why (the
Round 42 finding, stated plainly rather than just silently switched
off). Draft's own real deliverable — Prism's measured drawing sheet,
flat pattern and all — is unaffected either way; it is made during
measuring, before the action even runs. Checking the box is still there
for the one real reason to want ChatGPT's version anyway: a
differently-styled picture for sending to someone outside the shop, not
a verification step.

Files: `addons/step/dialog.py` (`ACTIONS`' own blurb, the new
`ai_draft_cb`, `_draft`'s early return, `cfg["step_ai_draft"]`),
`tests/test_step_dialog.py` (existing Draft tests now check the box
explicitly, since what they test only runs when it is checked; new test
`test_the_ai_draft_is_off_by_default_and_skips_chatgpt_entirely`).

---

# Round 42 — the flat pattern drawing is for the person cutting it, not the estimator

Round 41 unfolded the flat pattern correctly, but drew it the way an
estimator's software would: every part's OLD formed 3-view band still
ran first, the flat pattern squeezed underneath it as an extra, and a
hole's diameter lived only in a side table — meaning whoever cuts the
part has to hold a table and a drawing in their head at once to know
what any one hole is. The owner's own words: "this is something that
would be read by a non technical person working on a machine," and the
reference sheet they'd already shared showed why — diameters marked
right next to each hole, no table to cross-reference.

**What changed, in `_draw_flat_pattern` (`prism_terminal/core/stepfile.py`).**

- Two plainly headed sections, side by side with a rule between them —
  **FLAT PATTERN** and **ISOMETRIC** — instead of one dense band. The old
  formed 3-view (front/top/side) is now only the fallback for a part
  whose bends did not resolve to simple folds, where it is the only real
  drawing there is; every part that has a flat pattern shows the flat
  pattern first, not buried under a formed view of the same part.
- Every hole's diameter is written on the drawing itself, next to the
  hole — once per distinct size present, so a repeated size is not
  re-labelled at every instance and crowded off the page — not only in
  the side table (kept, smaller, as a quick order-quantity tally, not
  the only place a size is stated).
- Every hole's position is dimensioned from the panel's own edges,
  grouped the way a real dimension chain reads (`_cluster`) rather than
  one entry per hole.

**A real layout bug, caught by looking at the actual rendered page, not
just running the code:** the first version of the position dimensions
used two staggered rows to keep adjacent labels apart. That's enough for
a handful of mounting holes; it is nowhere near enough for a
ventilation grille, where a dozen slot positions sit within 60 mm of
each other — the labels printed on top of each other as an unreadable
run of digits. Fixed two ways: four stagger rows instead of two, and the
grouping tolerance itself is now computed in PIXEL space at the part's
actual drawn scale (`22px` / `15px` minimum separation), not a fixed
distance in millimetres — the same 1 mm of separation is three pixels on
a small part and thirty on a large one, and only the pixel figure
actually predicts whether two labels will collide.

Files: `prism_terminal/core/stepfile.py` (`_draw_flat_pattern`, `_cluster`,
`_Sheet.tick_h`/`tick_v`), `tests/test_stepfile.py` (new class
`ClusteringHolePositionsForTheDrawing`, plus three new assertions on
`TheFlatPatternOfTheCustomersEnclosure` for the section split, the
inline diameter labels, and the position dimensions).

---

# Round 41 — the STEP add-on now unfolds a formed sheet-metal part

The drawing sheet's own note used to say it out loud: "a bent sheet's
flat pattern is not shown." A client's reference drawing (a real fab's
"System Engineers" quotation sheet) made clear that flat, dimensioned,
cutting-list drawings — not the formed 3-view — are what a fabricator
actually needs. Building it needed real bend detection and real
sheet-metal unfolding math, not a guess.

**What was added, in `prism_terminal/core/stepfile.py`.** A bend is a
cylindrical face OCCT models between two flat panels — but so is the
small rounding fillet at almost every hole's edge, and the two look
identical by angular span alone. The reliable difference, found by
reading a real customer STEP file's faces directly: a bend's cylindrical
face is as long as the panel it folds (tens or hundreds of mm); a hole's
edge fillet is only ever as long as the sheet is thick. `_bend_candidates`
uses exactly that, `_group_bends` pairs up each bend's inner/outer
surfaces and finds the two flat panels it connects, and `unfold()` walks
that graph from the largest flat face, rotating each connected panel
about its own real bend axis by its own measured angle, then separating
the two panels at that seam by the real bend-allowance distance —
`angle x (radius + K x thickness)` — rather than the formed radius.
Holes carry through to their true flat position. A part whose bends
don't resolve to simple folds between flat panels is left unmeasured,
not approximated — the same rule `_project()`/`_svg_of()` already follow
for a view that cannot be drawn.

**The K-factor** — the one input this can't derive from geometry — is
now a field in the STEP dialog (blank = Prism's own default, 0.4133;
entering one uses it instead), always stated on the drawing sheet
("K-factor 0.4133 (Prism's default — confirm with the shop)" or
"...(as entered)") so a default is never mistaken for a confirmed shop
value.

**Two real bugs found only by testing the actual numbers, not just
whether the code ran.** Both looked completely fine as SVG renders —
every panel positioned, every hole inside its outline, nothing visibly
wrong — and both were still silently broken:

1. A test asserting "a bigger K-factor makes a bigger flat pattern"
  failed: raising K from 0.2 to 0.45 changed nothing. The correction
  step measured "the gap" between a bend's two seam edges and nudged it
  toward the target — except that gap is always exactly zero, by
  construction (both edges belong to the same cylindrical face at the
  same radius; rotating by the face's own angular span always lands one
  exactly on the other), so the "correction" was reliably zero too, for
  every bend, silently.
2. Fixing that by pushing outward from the bend's cylinder axis instead
  moved panels in the right amount but the wrong direction — into Z,
  off the flat plane, because that axis sits one bend-radius OFF the
  panel's own plane (a bend's cylindrical face is tangent to it, not
  centred on it), which the correction's own "stay in-plane" projection
  didn't account for. The fix measures from `other`'s own panel centre
  instead, which is never degenerate with the fold line the way a point
  chosen ON the bend geometry can be.

Caught by writing the assertion "K goes up, size goes up" as an actual
test before calling this done, not by eyeballing a rendered picture —
the picture looked right both times.

**Verified against a real customer job**, `step_file_demo/Assem1.STEP`
(the same file `TheCustomersOwnEnclosure`'s tests already witness
against) — all three real parts (top, bottom, side) unfold cleanly,
every one of their 48 real holes lands inside its own flat outline, and
a rendered SVG of the result was eyeballed panel by panel before trusting
the numbers.

Files: `prism_terminal/core/stepfile.py` (`unfold` and its helpers,
`_measure`, `analyse`, `_draw_flat_pattern`, `write_xlsx`),
`addons/step/dialog.py` (the K-factor field), `addons/step/workers.py`
(threading it through), `tests/test_stepfile.py` (new classes
`TheFlatPatternOfTheCustomersEnclosure` and
`BendAllowanceIsTheNeutralAxisNotEitherRadius`), `tests/test_step_dialog.py`.

**What this does not do.** Corner reliefs (the small notch cut where two
bend lines meet) are not modelled — the flat outline is each panel's own
real boundary at its correct unfolded position, which is exact for the
numbers but does not yet draw the relief cut a real cutting file would
have. A part whose bends are not simple folds between flat panels — most
sheet metal in these two sample jobs, in fact only the box/bracket-style
parts qualify — is reported as formed-only, same as before this round.

---

# Round 40 — a finished NotebookLM video was thrown away right after it downloaded

"There is no sign of the video" — but the automation for actually driving
NotebookLM's Studio → Video Overview → Customize → Generate now → download
flow already existed (`_nb_generate`, `_nb_wait_generated`, `_nb_download`)
and, live-checked against the real page on 18 Sep 2026, its selectors are
still exactly right: `Customize Video Overview`'s Short/Explainer choices
are `<mat-radio-button>`s each wrapped in a `<label>` starting with that
word, and `Generate now` is a plain button by that name — both match what
`_nb_generate` was already looking for.

**The actual cause.** One line after `_run_notebooklm` returns —
`_make_editable(..., made_image=bool(got))` — reads a variable, `got`,
that is only ever assigned inside the generic maker branch (the
image-wait/artwork loop, further down the same dispatch). Apollo, Canva,
ElevenLabs and NotebookLM are the other four branches of that same
dispatch, and every one of them reaches this line having never touched
`got` — `UnboundLocalError: cannot access local variable 'got'`, every
single time. It didn't matter that a Video Overview had genuinely
rendered and downloaded: the crash lands *before*
`_save_artifacts(nb_files, ...)` and before `pipeline_files[:] = ...`, so
the file that NotebookLM had already produced was never saved to
Artifacts and never reported back — indistinguishable, from the run's
outside, from nothing having happened at all.

**The fix.** `got = 0` is now set once, before the whole dispatch, so
every branch — Apollo, Canva, ElevenLabs, NotebookLM, and the generic
maker path that already reassigns it while actually counting images —
reaches `bool(got)` with a real value.

**Verified against the live page, not assumed.** Connected Playwright
over CDP to Prism's own signed-in Chrome (same technique as the 13 Sep
probe), opened the real `Video Overview → Customize` dialog on a live
notebook, and read the DOM directly: `Customize Video Overview` heading,
`Short`/`Explainer` as `<mat-radio-button><label>` pairs, `Generate now`
and `Generate later` buttons — all present exactly as `_nb_generate`
expects. Did not press Generate (that spends the account's daily
allowance) — so `_nb_download`'s selector for a *finished* item's Download
control is still unverified; the memory note from 13 Sep still calls that
one "Unseen," and this round doesn't change that.

Files: `prism_terminal/core/automation.py` (`AU.run`),
`tests/test_notebooklm.py` (new test,
`test_a_finished_video_is_not_thrown_away_right_after`).

---

# Round 39 — Gerber's "Measurements in" picker only ever reached the Excel form

Picking "inch" in Gerber's unit box and still getting mm back, everywhere
that mattered: the on-screen "THE FIVE NUMBERS" / "WORKINGS" panel, the
CSV-adjacent report text, and the brief handed to the writing AI.

**The actual cause.** `core/gerber.py`'s `answers_text()`, `summary_text()`
and `agent_brief()` — the three places a measured job's figures ever
become text a person or an AI reads — never took a unit argument at all;
every dimension was hardcoded to mm, with mil shown as a fixed secondary
reading. The dialog's `gerber_units` setting was real and correctly saved,
but `_units_changed()` only ever called `_fill_forms()` (the client's
Excel export, which already had proper mm/inch/mil support via
`gerber_form.py`'s `_in_units()`) — it never touched the on-screen text,
and `_write_up()` never passed a unit into `agent_brief()` either. Picking
a unit changed nothing a customer or an AI actually read.

**The fix.** `_fmt`, `_rule_note`, `answers_text`, `summary_text` and
`agent_brief` in `core/gerber.py` now take a `unit` parameter and format
every dimension (PCB/array size, track width, track spacing, drill size,
pad pitch, SMT pad) in it — reusing `gerber_form.py`'s existing
`_in_units()` conversion table and decimal convention (2 dp mm, 4 dp inch,
2 dp mil) rather than a second copy, so a value shown in the dialog and a
value written into a client's cell can never quietly disagree on what
0.25 mm is in inch. The chosen unit is always shown with mm alongside it,
so a figure never has to be taken on trust. `addons/gerber/dialog.py`
threads `self.cfg["gerber_units"]` into all three call sites, and
`_units_changed()` now rebuilds the on-screen report (`_render_meas_view`,
extracted from `_on_measured`) as well as the client's form, so switching
units after a job is already measured updates everything at once — no
re-measuring, since the measurement itself was never the problem.

**What this does not touch.** `write_report_csv()` — the audit-trail CSV
saved next to every job — stays mm-only, deliberately: it is a fixed
ground truth to cross-check an AI's reply against, not a display surface,
and the customer's-form export already had its own working unit support.
Two secondary readings (total trace length in metres, the X/Y position of
the tightest copper gap) were deliberately left in mm — they are
locations/aggregates, not the kind of dimension a fab quote is written
against, and converting them added risk without matching what a customer
actually complained about missing.

Files: `prism_terminal/core/gerber.py`, `addons/gerber/dialog.py`,
`tests/test_gerber.py` (new class `ChoosingAUnitActuallyChangesTheAnswer`,
5 tests).

---

# Round 38 — a brand-new Mac couldn't start Chrome, and it wasn't the driver

A client's MacBook Air M2: Prism opened, took her request, wrote a plan —
and failed the moment she pressed Start, before Chrome ever opened. Round
33's memory of "M2 + Chrome won't start" pointed at the arm64 chromedriver
work from earlier this month, but that machinery is sound and this was a
different bug, hers being the first Mac to run this build that wasn't
already a developer's own machine with its own Python history.

**The actual cause.** A frozen build's Python has its default location for
internet security certificates baked in at build time — wherever the
machine that built the app happened to keep its own. On any OTHER Mac
that folder does not exist, so every plain HTTPS request from the frozen
app finds nothing to verify a site against and refuses the connection.
There is exactly one such call in the whole engine:
`core/automation.py`'s `_http_get`, used for exactly one thing — fetching
Prism's own Apple Silicon chromedriver, the step that runs right before
Chrome opens. Every other network call in the app goes through `requests`,
which already carries its own certificate bundle and never had this
problem.

**Verified, not assumed.** Reproduced by hand: pointed Python's
certificate lookup at a path that does not exist (the same shape a
missing build-machine folder takes) and called the real
Chrome-for-Testing feed through the old code — it failed with
`[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer
certificate`, the exact class of failure a customer's own fresh Mac would
hit. Same broken environment, same real address, through the fixed code —
it succeeded.

**The fix.** `_http_get` now builds its own SSL trust from `certifi`'s
bundled certificate file — already shipped inside the app for other
reasons, just never pointed at for this one call — instead of trusting
wherever the build machine's Python happened to keep its own. Which
computer built the app, or what is or isn't installed on the customer's,
stops mattering.

**What this does not fix, said plainly.** Prism still isn't signed with
an Apple developer certificate, so a fresh install still needs the
"unknown developer" bypass by hand — and on macOS 15+, that dialog has no
*Open* button; System Settings → Privacy & Security → *Open Anyway* is
the only path, and it has to happen within a few minutes of the blocked
attempt. Full write-up, in plain language, in `KNOWN_ISSUES.md` #13 —
including what we checked and couldn't verify without a second Apple
Silicon Mac to test on by hand.

Tests: `tests/test_chrome_driver_arch.py`'s
`TheDriverFetchVerifiesAgainstCertifi` (5, new).

---

# Round 37 — Google Gemini joins Visual & Image, as ChatGPT's real fallback

The owner's ask (15 Sep 2026), tested live before it shipped: add a
Google image tool, and make it the next fallback after ChatGPT — which
on this account had already hit its own free-tier image limit twice in
one afternoon, both times seen in this session's own real end-to-end
runs.

**Read live, not guessed at.** Attached Playwright to Prism's own
signed-in Chrome (the same technique used for NotebookLM's registry
entry) and opened gemini.google.com/app for real. A plain prompt —
"Generate an image: a stainless steel shoe rack product photo, industrial
style, teal accent lighting, vertical 9:16 composition" — produced a
clean, correctly-composed 572×1024 picture in about 15 seconds, settled,
with a working "Download full size image" control once it finished.
Google's current model behind this is Nano Banana (Gemini 2.5 Flash
Image). No custom selectors were needed: the composer is a plain
`contenteditable` div the generic textarea selector already matches, and
the picture is a plain large `<img>` the generic image harvest
(`_harvest_images`) already finds by its shape — the same reason
Leonardo.ai, Adobe Firefly and Midjourney needed no special handling
either.

**Registered as a maker** (`core/agents.py`): `AGENT_REGISTRY["Google
Gemini"]`, `_MAKES["Google Gemini"] = "generated images"`,
`_PROFILES["Google Gemini"] = {"produces": ("image",), …}` — free, and
the fastest tool in the category.

**Positioned to actually be reached, not just added.** `alternatives_for()`
offers the first two untried tools in `CATEGORIES["visual"]["agents"]`'s
own order when one fails — so appended at the end it would never come up
under the category's 2-tool cap. Placed second, right after Canva, it is
now genuinely one of the two alternatives offered whenever ChatGPT is the
tool that failed, which is the whole point of adding it.

Tests: `tests/test_failover.py`'s `GoogleGeminiIsChatGPTsRealFallback`
(4, new) — offered when ChatGPT fails, a maker of images, not a local
renderer, present in both the category and the registry.

---

# Round 36 — "Email automation" is named "Email inquiry automation"

The owner's ask, plain: rename it. "Email automation" was the add-on's
label since it shipped (`addons/inquiry/addon.py`) — read the mailboxes,
register inquiries, quote, chase. The name never said what it automates,
and the app also has a separate "Email" add-on (the draft-and-send
screen), so the two sat one word apart in every list that shows both.

Only the label moved. The add-on's key (`inquiry`) and its licence feature
(`inbox`) are unchanged, per the same rule the label's own comment already
stated: "the SKU and the wiring did not move, only the name on the shelf."
61 occurrences across 20 files — the rail, Home, the working screen's own
header and dialogs, the setup wizard, the guided tour, the support
articles, `--features` mint hints, and the golden-string assertions in
`tests/test_inquiry_screen.py` and `tests/test_email_automation.py`.

`devtools/extract_strings.py` re-run: 7 phrases removed, the same 7 added
back under the new name — a clean swap, nothing else touched.

---

# Round 35 — a BOQ/BOM from an attached file is a guardrail again, not a second skills module

Round 31's own small "Prism skills" loader was dropped on the 12 Sep pull
in favour of the far more complete house-standards system a teammate
landed the same day under the same module name (`core/skills.py`,
`skills/boq-writeup/`, `skills/bom-parts/`) — the right call, and it stayed
that way. But the thing the owner had actually asked for was gone with it:
the owner's report of 11 Sep, that the same BOQ-from-a-drawing request
typed to Claude by hand got the document in a fraction of the tokens a
routed Prism run spent, because the routed run also answered with
Think-it-through and Sum-it-up. The teammate's skills answer a different
question — how a BOQ is *written* (measurement traceability, IS 1200
rounding, unit rules) — and are flagged `stages: []`, so they were never
wired to prune a plan's *stages* in the first place. Nothing there was
going to fix this.

**Rebuilt as a router guardrail instead of a second skills module**
(`apply_boq_file_guardrail`, the same deterministic, no-LLM-judgement
mechanism `apply_make_guardrail` and `apply_studio_guardrail` already use).
With an attachment present and a BOQ/BOM word in the request, it turns off
brains, leads, visual, summary, development, presentation, media, audio,
design and artwork, and turns CONTENT into the one document step —
kind `file`, briefed with the attached file's name and the requested
format (default .docx). RESEARCH is left exactly as the planner decided,
so "and research the company too" in the same breath still gets its
research. Wired into `route()` right before the skills pass, so a skill is
only ever offered a stage that is actually going to run — and on the
owner's exact request the two now compose cleanly: the guardrail prunes to
research + content, and the teammate's own skills system attaches
`research-report` and `pdf-document` to those two, unchanged and untouched.

This cannot collide the way Round 31's did: it touches no file under
`skills/`, and `core/skills.py` is byte-identical to what the teammate
shipped, verified by diff before and after this change.

Tests: `tests/test_boq_file_guardrail.py` (14, new).

---

# Round 34 — a settling entrance animation is not the same as a broken layout

The accent-colour bug in Round 33 was real and is fixed; the very next
render hit a different wall — "an image (img, 719x1937) runs off the
frame", no MP4 written, on a reel that had passed every per-scene check
clean. Loaded straight into a real browser (the saved
`~/.prism/runs/reel_*.json` — see the new memory on that), the truth
settled it in one measurement: scene 1's photo sits in
`.s1-photo{...;overflow:hidden}` at exactly `(367, 0, 713, 1920)` — dead
inside the 1080x1920 frame. The `<img>` inside it carries a slow scale-in
entrance (1.06 → 1.0 over the scene). Measured at the check's own point
(75% into the scene), the animation had not quite settled —
`transform: matrix(1.00868, …)`, 0.868% still oversized — giving the
element's own unclipped box as `(364, -8, 719, 1937)`: a few pixels past
every edge. Nothing the viewer ever actually sees leaves the frame; the
wrapper clips it. `window.__check()`'s image-boundary test measured the
image directly and never asked whether anything contained it.

**Now**: before flagging an image, the check walks from it up to the
scene root; if any ancestor clips overflow (`overflow: hidden` or `clip`,
on either axis), the ANCESTOR's own box is judged instead — the box that
actually decides what paints, and one that a moving child never changes.
An image with no such wrapper, or one whose wrapper is itself off frame,
is still caught exactly as before; `overflow: visible` or `auto` still
does not count, since neither actually hides anything.

Tests: `tests/test_offframe_clip_check.py` (8, real-browser, gated behind
`PRISM_RUN_RENDER_TESTS=1` the way `test_studio_v2.py` already is) —
reproduces the owner's exact scene geometry (copy and picture replaced by
placeholders; the client's words do not belong in this repository),
confirms the animation genuinely still overshoots at the check point
(so the passing test isn't passing by accident), and confirms a
no-wrapper or wrapper-itself-off-frame image is still caught.

---

# Round 33 — the accent-colour rule is actually checked before filming, not just after

The owner's run of 14 Sep 2026: a routed Studio reel wrote and filmed every
scene, then failed on export — "the client's accent colour #3a713a appears
nowhere in the design — use var(--accent) for the element the eye goes to
first in each scene, or the reel is not in their colours" — with no MP4
written. Minutes of writing and filming, thrown away at the last step.
It happened again the next day with a different reel and #4ab50a, which is
what turned up the second, deeper cause below.

**First cause: the per-scene correction loop never checked the rule at
all.** The design's turn-one prompt tells the model the rule and says "the
design is checked for this before it is filmed" (`brand_block`) — but
nothing ever had. `build_spec()` already catches and sends back layout
faults and missing assets one scene at a time, cheaply, while the model is
still on that scene — but its check-spec was
`{"design": design, "scenes": [sc], "_assets": …}`, with no `"brand"` key.
`brand_faults()` reads `spec.get("brand")`; with nothing there it always
saw an empty accent and returned `[]`. The rule was checked for the first
time at `render()`'s own gate, by which point every scene had already been
written and the whole reel already filmed — and that gate does not
correct, it refuses to publish a flawed MP4.

*Fixed:* `build_spec()` takes the client's measured `brand` and, once the
LAST scene is written, checks `brand_faults()` cumulatively over the shared
stylesheet and every scene written so far — cumulative, not per-scene,
because the rule only needs the colour to appear *somewhere* in the reel
(the same thing `render()`'s own gate requires), so an early scene that
legitimately carries no accent element (a full-bleed picture, a
kicker-only card) is never wrongly flagged. When it is still missing, it
goes through the exact same one-shot "send it back, keep whichever answer
is better" correction every other layout fault already gets.

**Second cause, found the next day on a different reel: the colour was not
known yet at design time at all.** `#4ab50a` was real and the fix above
was wired in — yet the same failure happened again. The saved spec proved
it: none of the five filmed scenes, and no rule in the shared stylesheet,
ever mentioned it. `studio_brand` — the value threaded into `build_spec()`
above — is seeded once, early in `run()`, from a sample of the user's own
raw attachment alone. On this run that attachment (a screenshot) sampled to
nothing usable, and the pipeline had no research step to fall back to
— so `studio_brand` stayed `{}` for the entire design conversation, and
Round 33's own new check ran the whole time against an empty brand. The
colour was only ever discovered by `_run_studio()`'s OWN render-time
fallback, which samples `attachments + pipeline_files` — and by render
time, `pipeline_files` already held the two pictures the Artwork stage had
generated (Artwork runs before Design in this pipeline shape), and one of
THOSE is what actually sampled to `#4ab50a`. The design conversation was
never told; it was never even offered the images that made the colour
found-able.

*Fixed:* the same sample `_run_studio()` already falls back to at render
time is now tried once more, earlier — right before the design prompt is
built, if nothing has supplied a brand yet — over the SAME set
(`attachments + pipeline_files`), which by then already includes whatever
the Artwork stage has made. Extracted as one shared function
(`_brand_from_images`) so both call sites — the new early one and
`_run_studio()`'s existing render-time backstop — sample the same way, and
so it doesn't just feed the check silently: it also fills `brand_block()`,
so the design conversation is told the real colour from turn one, not only
corrected against it on the last scene. Research still wins when it has an
answer — a client's own published colours over a heuristic photo-sample —
this fallback only runs when nothing else, research included, has supplied
one yet.

`render()`'s hard gate is unchanged and stays as the backstop either way: a
correction that does not take, or a colour that genuinely can't be
sampled from anything on hand, still stops a flawed MP4 from shipping.

Not fixed in either pass, and said plainly rather than left quiet: the Reel
add-on's own dialog (`addons/reel/dialog.py`) lets a person type a brand
colour by hand; that value is applied to the spec only after `build_spec()`
has already run, so a hand-typed colour with no attachment or research
behind it still is not caught until the final gate. Both routed-pipeline
runs this bug was reported from are now fully covered — one by the measured
brand reaching the check, the other by the check itself existing.

Tests: `tests/test_scene_by_scene.py` (7, `TheAccentColourIsCheckedBeforeTheReelIsFilmed`), `tests/test_studio_brand_timing.py` (8, new).

---

# Round 32 — NotebookLM makes the video from the run's own material

The owner's run of 13 Sep 2026: "summarize this all in one ideation and
generate me a google notebook lm video", nine documents attached. Prism
opened NotebookLM, created an empty notebook, typed nothing, and reported
"couldn't find the 'Add source → Copied text' option". Two causes: the
runner looked for "Copied text" without ever pressing "Add source", so it
searched a dialog that was not open; and NotebookLM was not offered for
the Video & Reels step at all, so it had been put on the Voice & Audio
step with a "voice-over" line for a request that said "video".

Read live that day by attaching Playwright to Prism's own signed-in Chrome
(the run's Chrome keeps a debugging port open): notebooklm.google.com now
redirects to notebook.google.com ("Gemini Notebook"); the Add-sources
dialog has "Upload files" (the OS picker — no `<input type=file>` exists on
the page, which is why the generic upload said "no file-upload field"),
"Websites", "Drive" and "Copied text" (a "Pasted text" box and "Insert");
the chat is `textarea[aria-label='Query box']`; each Studio card ("Video
Overview", "Audio Overview", …) carries a pencil that opens "Customize":
Video = Format {Short, Explainer} + a focus box; Audio = Format {Deep Dive,
Brief, Critique, Debate} + Length {Short, Default, Long} + a focus box;
both end in "Generate now". The full notes sit above `_run_notebooklm`.

**Now** (`core/automation.py`, `core/agents.py`):

* NotebookLM is a choice for **Video & Reels** as well as Voice & Audio,
  and a maker (`_MAKES`), so the planner briefs it to build the overview.
* The runner: a fresh notebook; every earlier step's **full** answer and
  every readable attachment pasted in as a "Copied text" source (a source
  tool wants the material, not the four-line hand-off — `_nb_sources`);
  wait for the sources to be read; then the card's Customize dialog —
  **the person's words decide video vs audio over the step** (`_nb_wants`),
  long-form is the default (an Explainer video; a Long audio when the words
  say so — `_nb_format`), the focus box gets the person's words and the
  step's line (`_nb_focus`); "Generate now"; wait up to 25 minutes
  (`generate_wait`, Stop honoured) for the render; then the item's menu →
  Download, captured through the same scratch-folder path every
  click-to-download file uses (`_capture_download`, factored out of
  `_harvest_via_download`), saved to the run's artifacts and handed to the
  next step. An ordinary step asks the notebook's chat instead.
* Attachments with no readable text (pictures) are named in the log as not
  sent; the page has no upload field to give them to.
* The registry entry says `upload_selector=""`, which `_upload_files` now
  reads as "this tool takes files another way" — no more "9 attachment(s)
  were NOT sent; it will answer blind" on every NotebookLM step.

Unverified, and said so in the code: what a finished overview looks like in
the Studio list and where its Download control sits (nothing was generated
during the probe — a Video Overview spends the account's daily allowance).
The wait ends when "generating" gives way to a listed item, or a new
menu/download control appears; if the download is not found the answer
names the notebook so the person can fetch it by hand.

Tests: `tests/test_notebooklm.py` (18).

---

# Round 31 — the tool gets the words, one line, and four lines from before

The owner's strict instruction (11 Sep 2026). The same PDF and the same
target — a BOQ for K J Pharmatech — put to Claude by hand as one line with
the file attached came back in a fraction of the tokens. Put through Prism,
the message Claude received was a banner ("WHAT THE PERSON ACTUALLY ASKED
FOR"), a paragraph on why the words above win, the extracted PDF text, the
whole Perplexity research report (up to 8,000 characters of it), a 250-word
"Act as a senior technical writer" prompt with role, deliverable spec,
quality bar and non-goals, and a hand-off rule sheet — and the chat ran out
of tokens before the document existed. "AIs now are very understanding; they
don't need complex prompts, they need simple prompts."

**The message a tool gets now** (`core/automation.py`):

* the person's own words, bare — no banner, no dashes, no paragraph about
  summaries (`_intent_block` returns the text and a blank line);
* the attachment line as before (a file that went up is pointed at, not
  pasted);
* `From the earlier step (Look things up):` and at most **four lines** —
  the lines under the earlier answer's `HANDOFF FOR <tool>` heading
  (`_handoff_of`; last heading wins; an answer with no heading falls back
  to a tail capped at 1,200 characters, down from 8,000). A tool with its
  own filter block (Apollo) keeps every line of it; the Sum-it-up step gets
  each earlier step's four lines rather than the last step's alone;
* the step's one line from the planner;
* one closing sentence: what to hand back (`contract.deliverable_line`,
  unchanged) and, for a step that is not the last, *"At the end add a
  section headed 'HANDOFF FOR X': at most 4 lines with the facts and
  decisions X needs — only those lines go forward. No questions back."*
  The last step gets *"Give me the finished result — no questions back."*
  Self-directing tools (Perplexity-style) are asked the same in two
  sentences that still invite depth.

The person still receives every step's full answer in the run's output;
only what travels to the **next tool** is cut to the hand-off.

**The planner writes one line per step** (`core/router.py`): "ONE line of
at most 25 words, in plain language, saying what this step does towards the
person's request" — on the first plan and on the rewrite for a confirmed
plan, which until now still carried the old ROLE / CONTEXT / DELIVERABLE
SPEC / QUALITY BAR / NON-GOALS, 120–250 words rule and the HAND-OFF rule.
The floor under a step nobody wrote a prompt for is one line too:
`For this step: write it up — <the request>`. The plain step names
(`STEP_NAMES`) moved to `core/agents.py` so the router can use them.

Measured on the owner's BOQ request with Perplexity's real hand-off: the
message to Claude is under 1,000 characters where it was over 9,000.

Tests: `tests/test_one_line_prompts.py` (15) pins the shape; the six tests
that pinned the old wording were changed in the same commit.

**Prism skills** (`core/skills.py`, new; `docs/PRISM_SKILLS.md`). The
owner asked for the BOQ prompt formation as a skill *for Prism* — not one
of Claude's. A skill is one Markdown file with `name:` and `when:` front
matter and a body that says which steps run and the one line each gets.
Read from `~/.prism/skills/` (yours, first) and `prism_terminal/skills/`
(shipped); a skill applies on a whole-word trigger in the person's own
request and its body goes to the planner on the first plan and on the
confirmed-plan rewrite. The first one ships:
`skills/boq-from-a-file.md` — a BOQ/BOM from any file the person drops in is one
document step (kind = file) with an optional four-line research hand-off
in front, and no brains, summary or picture step. Bodies are capped at
1,500 characters and a broken file is skipped, so a skill can neither
become a rule sheet nor stop a plan. Tests: `tests/test_prism_skills.py`.

The first run against it (owner, 11 Sep) came back with a Think-it-through
and a Sum-it-up step the skill's body had said not to run — the planner
reads advice as advice. So a skill's `steps:` line is now **binding**
(`skills.apply`, called in `router.route` after the guardrails): a stage not
listed is switched off, a stage marked `?` is left to the planner, a stage
without the mark is switched on, and `kinds:` fixes what a step must
produce. The BOQ skill says `steps: research?, content` and
`kinds: content=file`.

**Only this task's files go up** (`_clear_staged_attachments`). The same
run sent Claude the shoe-rack PDF *and* a deck outline from a reel run days
earlier. Prism never uploaded the deck — the writing step sends only the
person's own files — but claude.ai keeps an unsent draft, attachment chips
included, and shows it again on the next new chat; a run that staged a file
and stopped before sending left the chip for the next run to send. Every
stage now presses the remove control on every chip in the composer before
its own upload, and the log says how many it cleared. Generic by design
(the control's accessible name says remove/delete/dismiss; the send button
is excluded), so it does not depend on either tool's class names.

---

# 1.5.8 — skills: house standards for each kind of job, and a check on the answer

**Prism carries skills** (`core/skills.py`, `prism_terminal/skills/`). A skill
is one folder: a one-line description the planner reads, the standards for
one kind of deliverable, and, for nine of the twelve, a checker that reads
the answer. Research reports, slide decks, PDF and Word documents,
documentation, stories, storyboards and cold emails are offered to the
planner, which names the one that fits a step; where it names none, the
person's own words pick at most one. The add-ons attach theirs directly:
bill of quantities, bill of materials, negotiation and follow-up emails, the
PCB quote reply, machined-part advice and lead outreach.

**The standards go where they fit, by the step's kind.** A text step gets
the whole skill. A step that builds its deliverable — a maker, the
presentation stage, or a file, image or video step — gets the standards
without the text layout, which would tell it to write the thing out instead
of building it. A step a program reads, and a links step, get nothing.

**A text step's answer is checked**, as Prism captures it: the page as it is
displayed, not markdown. A step with faults is asked once to fix them, and
the second answer is kept only if it is cleaner. A step whose deliverable
the contract found missing has already had its one re-ask, and a reply that
is a built file is never judged as text. Checkers are tested against samples
rendered in real Chrome and against the owner's own saved replies.

**The trade rules were fact-checked** against Indian standards and
manufacturer catalogues. Six size ranges in the parts-list checker rejected
real parts and are gone. A sheet for review by someone in the trade is at
`prism+gui/artifacts/skills-trade-review-2026-09-11.html`.

**A customer can change them without a release.** `~/.prism/skills/<key>/`
replaces or adds to a shipped skill; a checker is only ever loaded from the
app itself. `/skills` in the terminal lists what applies.

**A checker's fault keeps its brackets in the log.** A fault reads
"[slide-deck] Placeholder text left in: [client name]", and rich reads both
as style tags, so `ui.literal()` escapes them — but it did so only when rich
was installed. rich is in the engine's requirements, not the app's, so every
packaged build and every CI lane runs without it, and there the fallback
stripper ate both: the log said "·  Placeholder text left in: .". The
escape now happens either way, and the fallback and the plain console take
it off. `tests/test_skills.py` pins the path without rich.

**The source-zip launcher uses Python 3.12** (`packaging/Install and Run
Prism.command`). It took any 3.11+, so on a Mac whose Homebrew Python is
3.13 or newer that one won — and rapidocr-onnxruntime will not install on
3.13 while gerbonara needs 3.12, so the whole install failed. It now takes
3.12 only, native to the chip even from a Rosetta Terminal, never runs
Apple's installer stub at `/usr/bin/python3`, and rebuilds a `.venv` that
an earlier run made on another Python.

**Updating to 1.5.8.** Nothing an installed version relies on has changed:
no settings, licence, run-record or manifest format, and no updater code.
The update adds 21 files in new folders, which the updater of every version
that can update in-app creates as it stages. Windows installs on 1.5.6 or
earlier still need the one browser download described under 1.5.7.

---

# 1.5.7 — a step is held to what it was for, and the update actually swaps

Audited against the owner's own 49 saved runs (11 Sep 2026; report at
`prism+gui/artifacts/prompt-pipeline-and-deliverables-2026-09-11.html`).
Four complaints: the prompts were "over engineered … the agent that reads
messes up", a reel asked for with research came back as research only, the
agent asked to make a document made none, and Windows made no artwork. A
fifth turned up on the way: an in-app update that downloads, restarts, and is
still the old version.

**A step has a deliverable, and is checked against it** (`core/contract.py`).
Every step now has a kind — text, file, image, video, data, links — taken
from the stage, the planner, and the person's own words ("give me a .docx"
makes the one writing step that finishes the piece a file step, whatever
the plan said; "summarise the attached PDF" and "an excellent post" do not).
One line of the
message says what to hand back. When the step ends Prism checks: a file step
that answered in chat text is asked once for the file, and if it still
answers in prose, Prism writes the document itself from that text and the
card says so. An image step with no picture shows as needing review instead
of "completed". At the end, the run says which of the things it was asked
for were not produced, rather than "All done".

**The document Claude built is collected.** Claude's card reads
"Document·DOCX" with no extension anywhere, so it was never recognised as a
file; and the download click matched the wrapper around the button, reported
success, and waited 45 seconds for a download that never started
(run of 2026-09-08 15:07). Cards are now read by their type label, and the
click takes the innermost real control.

**The planner writes briefs, not specifications** (`router.build_prompt`).
It was handed 20,695 characters of rules that contradicted each other
("Prefer ONE stage" beside rules that forced four), with the field notes
declared to outrank the rules, and it had to write every step as a role, a
deliverable spec, a quality bar and non-goals — which is where "Non-Goals: Do
NOT generate an actual .docx file" came from. 89% of the owner's saved stage
prompts opened "Your ONLY task is", and 34% of the tools' replies contained a
"HANDOFF FOR" section. Now each step gets a kind and a 40–80 word brief in
plain language: no role-play, no format rules, no hand-off rules — Prism adds
those itself, once. Field notes are sent only for the tools in the plan, and
a tool carrying several steps is described once. The engine's hand-off went
from four numbered rules to one paragraph, and "THIS OVERRIDES EVERY OTHER
FORMATTING INSTRUCTION" is gone from the reel prompts because there is no
longer anything to override. "document", "report", "proposal" and similar
now route to a writing step, and a bare "api" no longer sends "documentation
for this API" to an app builder.

**A reel gets its pictures.** A plan row the planner never turned on was
sent to the engine as "switched off", and "visual" switched off Studio's own
artwork step; only rows the person actually unticks count now. Dropping a
step that has no prompt no longer turns the pictures off either — the dialog
had promised the opposite in the same breath. Prism Motion gets an artwork
step of its own and is given the pictures earlier steps made; it used to be
offered the client's attachments only, so a Motion reel could not contain a
generated picture. The imagery guardrail sets a flag instead of forcing a
second image step, covers Motion as well as Studio, and still honours "type
only".

**The reel prompts say each rule once** (`core/reel_web.py`,
`core/motion/generate.py`). A scene is written in the same chat straight
after the design turn, yet every scene prompt restated the whole motion,
layer and shape rulebook, and the safe area was given in two different sets
of numbers inside one message. The rules now live once in the design turn
(Studio) or the storyboard turn (Motion); each scene carries its own row, its
asset names and the JSON shape. Measured on a six-scene reel with brand
colours and four pictures: Studio went from 72,023 to 30,086 characters
typed, Motion from 56,718 to 34,567, and a Studio scene prompt from about
9,600 characters to about 2,400. Essential copy has one safe area everywhere,
clear of the platform's caption and buttons at the bottom of the frame.

**Prompts are written for the tool that reads them** (`agents._PROFILES`).
Each tool carries what it can produce, how to ask it for a file, and its
known drift ("write it in the chat, not a side panel"); a step is not held
to a file its tool cannot make. The signed licence payload can replace any
profile (`licensing/payload.profiles_for`), so how Prism talks to a tool is
kept current from the admin console rather than by a release.

**The update swaps** (`apply_update.py`, `updater.py`).

* Windows: the swap helper was Prism.exe, started from inside the folder it
  then tried to rename, which Windows refuses. No Windows in-app update could
  ever have swapped. It is now a script in `~/.prism/updates` run through
  `cmd.exe`.
* The new version is recorded as accepted when it has **started**, not when
  it finished downloading, so a failed swap no longer makes the next check
  say "nothing newer" and open GitHub instead — the report from 1.5.2.
* Staging happens beside the install so the swap is a rename; across volumes
  it falls back to a copy, and what staging leaves behind is removed.
* `~/.prism/logs/update-apply.log` records what the swap did.
* A build that failed its first launch and was rolled back is not offered
  again; only a newer one is.
* The Windows script leaves the install folder before moving it, reads its
  paths as UTF-8, runs in a hidden console, and starts the old version again
  if the folder will not move.
* A rename refused because a file is in use changes nothing and is retried.
  Only a move between drives falls back to copying — copying on any error,
  as this fix first did, could empty a live install when one file was locked.

**Windows artwork.** Artwork exists only on the Studio and Motion paths, so
anything that swaps them out removes it. A failed Chromium lookup is now
retried after a minute instead of being cached as "not installed" until
restart; the frozen build's self-test now fails a bundle whose FFmpeg cannot
be resolved (Studio checks FFmpeg before the browser, and that gate only ever
proved the browser); and the "run with Prism Reel instead?" dialog says Prism
Reel makes no pictures.

**The build fits GitHub's file limit again.** The picture-reading stack
added in Round 30 took the Linux bundle to 1,053 files and the macOS bundle
to 1,028, over the 1,000 assets one release can hold, which is why 1.5.6
could not be published. Qt's own interface translations, which Prism never
loads (see i18n.py), are no longer bundled: 96 files on every platform.

**Updating from 1.5.6 or earlier on Windows.** The in-app update is run by
the version being replaced, so a Windows install on 1.5.6 or earlier still
uses the old helper, which cannot swap. If the update does not take, the
next press of Update opens the download page: download 1.5.7 there once.
Every update after 1.5.7 goes through the new helper.

**Known, not fixed here.** In the packaged macOS build the picture-reading
package fails to import, so reading text from pictures is unavailable on
Mac; it works in the Windows and Linux builds. The frozen app's OpenCV
loader looks for its native library where the .app layout does not put it,
and diagnosing that needs a macOS build.

Tests: `tests/test_task_contract.py`, `tests/test_tool_profiles.py`,
`tests/test_update_swap.py`, `tests/test_plan_deliverables.py`; changes to
`tests/test_updater_phase1.py`, `tests/test_router_json.py`,
`tests/test_canva.py`, and to `tests/test_scene_by_scene.py` and
`tests/test_asset_plan.py`, whose checks on scene-prompt wording now look in
the design turn, where those rules moved. 13 new UI strings have no Hindi or
Gujarati translation yet.

---

# 1.5.6 — a design that went into a side panel is read, and asked for in the chat

Reported from a client's Mac (11 Sep 2026): the Studio run stopped with
*No JSON found in the agent's reply. The art-direction stage has to return
the design JSON.* Studio's art-direction turn is a long, code-shaped JSON
answer — exactly the kind Claude moves into an artifact panel and ChatGPT
into a canvas on its own. Prism reads the conversation text; a side panel
is invisible to it, and nothing in the prompt had said not to use one.

**Now:**

* Every JSON-returning Studio prompt (script, art direction, each scene)
  says: put it in this chat message itself, no artifact, canvas, document
  or file — `reel_web.IN_CHAT_RULE`.
* Before the design conversation starts, `_design_turn_text()` looks for
  a reply that parses: the captures newest-first (not only the last one),
  then any code panel on the page that carries the design keys
  (`_rescue_json_from_page`: `pre`, `code`, CodeMirror, artifact and
  canvas containers, minus Prism's own prompt echo), then one re-ask that
  names the problem and asks for the JSON in the chat, then both again.
  Only when all of that fails does the run stop with the same message
  and the same saved file as before.

What the saved file on that Mac says decides whether this was the whole
story; the change covers the two likeliest causes and costs a plain-text
step nothing. `tests/test_design_in_chat.py`.

---

# 1.5.5 — the macOS in-app update produced an app that would not open

Found by the first real macOS in-app update (1.5.2 → 1.5.4, 10 Sep 2026):
the update downloaded, verified, swapped in and relaunched — and Prism.app
never opened again. No window, no log line, no rollback. The backup was
beside it as `Prism.app.old`; restoring it by hand brought 1.5.2 back.

**Was:** `update_manifest.build()` listed the tree with `os.walk()`, whose
`filenames` never include a symlink that points at a *directory* — those
are reported in `dirnames` and, with `followlinks=False`, never descended
into either. So they were never recorded. A PyInstaller macOS bundle is
built on exactly those links: every framework's `Versions/Current → A`,
and `Python.framework/Versions/Current → 3.12`. The *file* links that go
through them (`Python.framework/Python → Versions/Current/Python`, the
seventeen Qt framework binaries) WERE recorded and recreated, so the
staged bundle had every file, every file link, and nothing for the links
to point at. dyld could not load Python.framework, so the process died
before a line of Prism ran — which is also why the two-phase rollback
marker never got its second launch: it needs Python to reach `main.py`.
Linux and Windows bundles have no directory symlinks, which is why the
real frozen-Linux update test in 1.4.2 passed and this waited for a Mac.

**Now:** `build()` records directory symlinks from `dirnames` as the same
`{"path", "symlink"}` entries file symlinks already use; the client's
`stage_update()` has created those since 1.4.1, so a 1.5.2 or 1.5.4 Mac
updating to 1.5.5 gets a complete bundle. And a gate:
`update_manifest.dangling_symlinks()` resolves every link in the manifest
through every other link in it, and `packaging/manifest.py` fails the CI
build if any link points at nothing the manifest carries — run against
the shipped 1.5.4 macOS manifest it reports every broken link that build
had. `tests/test_update_manifest.py` builds a framework-shaped tree and
checks both halves.

**Stated plainly for anyone on a Mac:** a 1.5.2 or 1.5.4 Mac that takes
the in-app update to 1.5.5 is fine — the fix is in the manifest CI builds,
not in the client. A Mac that already took 1.5.4 in-app and will not open:
in Terminal, `mv /Applications/Prism.app /Applications/Prism-broken.app &&
mv /Applications/Prism.app.old /Applications/Prism.app && rm -f
/Applications/Prism.app.prism_update_pending`, then open Prism; it is 1.5.2
again and will offer 1.5.5. The 1.5.4 DMG itself was always fine.

Still open: the rollback can only act once Python runs. A launch that dies
in dyld needs a supervisor (the apply helper waiting on the relaunched PID
for a few seconds) to notice; the next hardening step.

---

# 1.5.4 — a file the tool made is a result, on every step, and it lands in Artifacts

Reported 10 Sep 2026: "the agent gives the document but Prism couldn't
read it" — the card said *Prism couldn't read the response off the page*,
the run recorded a failure, and the DOCX/XLSX the tool had plainly
produced was either never saved or saved and never mentioned. BUGS.md #3.

**Was:**

* Files were harvested on six stages only (development, presentation,
  format, content, write, audio). A tool asked on research, brains, leads
  or summary for "an Excel of this" made one and Prism walked past it.
* The candidate test for "this link is a file" was: extension in the
  href, a `download` attribute, or a `blob:` URL. ChatGPT's generated-file
  chip is none of those — a signed, extension-less URL whose only clue is
  the link text "report.docx" — so it was skipped as a navigational link.
  The click fallback then looked for a control labelled "Download"; the
  chip is labelled with the filename; nothing was found.
* Harvesting ran before the "did the tool answer?" decision but was not
  part of it: a reply that was the file alone, with no prose over fifty
  characters, fell through to `it returned nothing`.
* The saved copy was named `<task> — Content.pdf`; the tool's own filename
  was thrown away.

**Now:**

* `_harvest_stage_files()`: every non-image stage is looked at. The six
  producer stages keep their patient wait; every other stage gets one
  free probe of the page (no sleep) and waits only when a file link is
  already there or the reply's own words say one is coming
  (`_FILE_HINT_RE`). The click-and-wait fallback runs only with such a
  reason (`click_fallback`). The customer's own attachments, which come
  back as identical chips in their turn, are skipped by name.
* `_filename_in_text()`: an anchor whose visible text is a filename counts
  as a file, and that name is kept — the temp file, the attachment record
  (`_site_name`) and the Artifacts copy (`save_artifact(name=…)` →
  `<task> — Research — Product Brief.docx`).
* A step that produced a file and no text is a result: the stage's text
  becomes a short note naming the file (`_files_as_reply`), the run
  records success, the next step receives both the note and the file.
  `stage_done` carries `files`; the card prints "Saved to Prism
  Artifacts: Product Brief.docx · 0.1 MB".

Not changed: image harvesting stays on the visual/media/artwork stages
(on a text step, an `<img>` sized like a picture is as likely to be the
customer's own upload). Claude's side-panel artifact still depends on the
page exposing a download control; the click path is unchanged there.

Tests: `tests/test_cross_platform_browser.py` (+11: the ChatGPT chip, the
customer's upload, the gated click fallback, every-stage probing, the
file-only reply), `tests/test_artifacts_config.py` (+1, the kept name).

## Also in 1.5.4 — "Studio makes artwork on Linux, not on Mac or Windows"

Reported the same day. The artwork step exists only on the Studio path:
the routed run inserts it before Prism Studio's design stage, and the
Reel window inserts it only when the *Studio* renderer is chosen. On a
machine where Studio's browser is not found, the Reel window greyed the
Studio option with a tooltip and quietly ran *Quick*, which has no artwork
step — so the report is accurate and the cause is upstream of artwork.

Checked against the 1.5.2 release manifests: the macOS and Windows
bundles DO ship Playwright's Chromium and node driver (353 and 314 files
under `.local-browsers/`), so a missing browser in the build is not it.
What is left, and what this release does about each:

* **The Artifacts folder could not be written and nothing said so.**
  `~/Desktop/Prism Artifacts` needs the person's permission on macOS
  (a packaged app is asked once; "Don't Allow" made every save a
  PermissionError that `_save_artifacts` swallowed), and on Windows with
  OneDrive's Known Folder Move the Desktop is `…\OneDrive\Desktop` and
  `C:\Users\x\Desktop` may not exist, so Prism made an invisible one.
  Now: `config._desktop_dir()` asks the Windows shell where the Desktop
  is; `config.artifacts_root()` verifies the folder is writable once per
  process and otherwise falls back to `~/Prism Artifacts`, saying so; the
  Artifacts screen and Settings show the folder actually in use;
  `_save_artifacts` warns with the reason instead of `continue`.
* **Studio unavailable was invisible.** The Reel window now says on the
  page why Studio cannot run here, and Export diagnostics gains three
  lines: `Prism Studio yes/no — why`, `Studio browser <path>`, and
  `Artifacts folder <path>` with a note when the Desktop one was refused.
* **Not verifiable from here:** whether the packaged Mac's Chromium and
  node launch on a customer's machine at all. An unsigned, quarantined
  `.app` can have its nested executables refused by Gatekeeper, and the
  build gate runs on a runner that never sees quarantine. The next Mac or
  Windows report should come with Export diagnostics; the three new lines
  answer this in one look.

---

# 1.5.3 — a Mac closes its own leftover Chrome, and never runs an Intel driver without Rosetta

Found by reading the client's M2 failure end to end (10 Sep 2026) instead
of the errno alone. "Chrome opened, no profile, no ChatGPT" was four things
stacked; 1.5.2 removed one of them.

**Was:**

* `_posix_chrome_pids()` took the first whitespace-separated token of the
  `ps` line as the program. On a Mac that is `/Applications/Google` (the
  binary is `…/Google Chrome.app/Contents/MacOS/Google Chrome`), basename
  "Google", so no Mac Chrome ever matched and `_release_profile()` was a
  silent no-op on every Mac. The Chrome left running by Login tabs (closing
  a Mac app's windows does not quit it) and the browser undetected-
  chromedriver launches *before* it starts the driver were never closed;
  the next launch handed itself to them and chromedriver said "cannot
  connect to chrome". That is also why the 1.5.1/1.5.2 errno-86 retry
  could not work on a Mac: the retry's Chrome handed off to the first
  attempt's orphan.
* undetected-chromedriver 3.5.5 has no `mac-arm64` in its platform table
  (`win32`, `linux64`, `mac-x64`), so on *every* Mac it downloads the Intel
  driver. Whenever Prism's own arm64 download failed — offline, a proxy,
  Chrome for Testing not yet listing a just-updated major — the fallback
  was a certain errno 86, shown as "Chrome updated itself, update Chrome".
  The reason every Mac at Alphakore worked: Rosetta was already on them,
  pulled in long ago by some Intel app, so the Intel driver ran. macOS
  never offers to install Rosetta for a binary a program executes; that
  just fails.
* `friendly.py`'s version-mismatch rule (pattern "chromedriver") rewrote
  the engine's Intel/Rosetta explanation; the true text sat under
  Technical detail.
* uc's browser finder looks in `/Applications` only. Prism's own finder
  knows `~/Applications` (a no-admin install), but never told uc — so
  Login tabs worked and every run said Chrome was not installed.
* The source-zip hand-off (`Install and Run Prism.command`) ran a Python
  with no CA bundle; the certifi patch lived only in the PyInstaller hook.

**Now:**

* The program is everything before the first ` --`; five Mac `ps` lines in
  `tests/test_cross_platform_browser.py`, helper process included, the
  everyday Mac Chrome and a script that names the path still left alone.
* `_refuse_intel_fallback()`: on Apple silicon with no arm64 driver and no
  Rosetta (`_rosetta_installed()` — two files, then a real `arch -x86_64`
  exec), Prism stops with "needs its Apple silicon browser driver … check
  this Mac is online and press Start again" and never calls uc. With
  Rosetta, uc chooses as before. `_apple_silicon_driver()` now tries the
  exact major, then `STABLE`, then any arm64 driver already in
  `~/.prism/chromedriver/` (newest first) before giving up.
* `browser_executable_path` is passed to uc from Prism's own finder.
* `friendly.py`: rules for errno 86 / "built for Intel Macs" and for the
  missing arm64 driver, placed before the version-mismatch rule; the
  "cannot connect" and "profile in use" rules tell a Mac user to quit
  Chrome with ⌘Q. The engine's own "cannot connect" text says the same on
  Darwin.
* `main.py` `_ensure_tls_trust()`: the same certifi patch as the runtime
  hook, applied when running from source on macOS.
* Export diagnostics gains a "Browser driver" section
  (`automation.driver_report()`): CPU, Rosetta, Chrome path and version,
  every driver file with the CPU it was built for, and whether a Chrome is
  sitting on Prism's profile right now.

Tests: `tests/test_chrome_driver_arch.py` (+9, incl. `NoRosettaNoIntelDriver`
and `TheDriverReport`; `test_without_an_own_driver_uc_chooses_as_before`
is now conditional on Rosetta, and says why), `tests/test_cross_platform_browser.py`
(+5 Mac lines), `tests/test_friendly_mac.py` (new, 6). Windows and Linux
paths are untouched except that uc is now told the browser path Prism
already found. Full read-through: `artifacts/mac-chrome-driver-cases-2026-09-10.html`
in the parent folder.

---

# 1.5.2 — Prism brings its own Apple silicon driver

The client's M2 updated to 1.5.1 and still stopped with errno 86 on the
retry. The reason is inside undetected-chromedriver: it unlinks and
re-downloads the driver on every launch, and when the unlink is refused
(the migrated folder was not writable) it silently reuses the file that
is there — the Intel one. So Prism's cleanup and purge could both fail
and the same driver ran again.

**Now:** on Apple silicon Prism fetches the `mac-arm64` chromedriver
itself from Chrome for Testing into `~/.prism/chromedriver/<major>/`,
checks the Mach-O header says arm64, and hands that path to
undetected-chromedriver, which only patches it. Its own cache no longer
decides anything. A driver folder that cannot be emptied is moved aside.
The message now says: press Start again; if it comes back, the one
`rm -rf` line; then Export diagnostics. Intel Macs, Windows and Linux are
untouched, and a failed download falls back to the old behaviour.

---

# 1.5.1 — an Intel driver on an M2 is found, removed and explained

Found by the first client install of the Apple silicon DMG (10 Sep 2026):
the first run died with `[Errno 86] Bad CPU type in executable`. Chrome
was universal and fine. The cached browser driver in
`~/Library/Application Support/undetected_chromedriver` was x86_64 —
carried over from an older Intel Mac by Migration Assistant — and the M2
had no Rosetta to run it.

**Was:** the cleanup that should have removed it shelled out to `file`
and swallowed every failure, so it did nothing and said nothing, and the
raw errno reached the customer.

**Now:** the engine reads the Mach-O header itself (thin x86_64, thin
arm64, universal), removes an Intel driver on Apple silicon before Chrome
starts and says so, an errno 86 out of the launch purges the cache and
retries once with a fresh download, and a second errno 86 becomes plain
words that name the folder. Linux and Windows are untouched: the check
only decides on Darwin/arm64. Tests: `tests/test_chrome_driver_arch.py`.

Client-side, until they update: delete that folder and start Prism again.

---

# 1.5.0 — the rules and fallbacks of 9–10 Sep, in a build

1.4.3 was built on 8 Sep, before any of Rounds 17–28 existed, so every
installed copy still sends a list two seconds apart with no cap, still
has no "Use fallback" button, still hands Canva a page of prompt, and
still attaches the customer's drawing to the BOQ writer. This build is
those rounds, plus what the team landed on `main` since:

* **Email** — Pace and limits (gap, jitter, per-press and per-day caps,
  send later), the Sent-folder copy with its switch, het's multi-account
  sending (Round 17, Round 28; `docs/EMAIL_SEND.md`).
* **Running a task** — "Use fallback" beside "Skip step"; an empty
  ChatGPT answer caught in seconds and regenerated once; Canva builds the
  deck through its own AI page; short, human-sized prompts; makers are
  briefed to build; the prompts are written only for the plan you
  confirmed (Rounds 18–22).
* **BOQ** — the drawing never reaches an AI; a sample BOQ defines the
  document; the measurement is a table with the unit inferred from the
  coordinates, look-alike layers and remote blocks flagged; and now
  pricing from your own rate list to an Excel with live formulas (Rounds
  23–28).
* **Landed by the team** — Leads & Outreach add-on and the BOQ pricing
  engine (Harsh); Motion Studio, the continuity compiler, materials,
  review and the cinematic lab (Beastburner); the add-on architecture and
  its guard tests (`CONTRIBUTING.md`).
* **Hand-off without a certificate** — `devtools/make_bundle.py` and the
  double-click installer for a Mac with nothing on it.

Nine add-ons register. The update manifests for this version are signed
with the production key `u1` as before; a 1.4.1+ install updates in-app.

---

# 1.4.3 — the Windows update helper never swapped

Found by a real customer update on Windows: the 1.4.2 tree downloaded and
verified into `%USERPROFILE%\.prism\updates\1.4.2`, Prism quit for the
restart, and never came back; reopening the exe gave the old version.

**Was:** `apply_update.pid_alive()`'s Windows branch did `import ctypes`
and then used `ctypes.wintypes.DWORD()`. `ctypes.wintypes` is a submodule
that only exists as an attribute once something imports it by name. The
`--prism-apply-update` helper is a bare process — no Qt, no licensing,
no keyring — so nothing had, `wait_for_exit()` raised `AttributeError`,
`perform_apply_and_relaunch()`'s catch-all returned 3, and the swap and
relaunch never happened. Under pytest some other import had already
loaded the submodule, which is why the Windows test lane was green.

**Now:** `import ctypes.wintypes`, and a test that runs `pid_alive()` in
a fresh `python -I` interpreter with only `apply_update` imported — the
way the helper actually runs.

**Consequence, stated plainly:** the helper runs in the OLD binary, so a
Windows 1.4.1 or 1.4.2 install cannot finish any in-app update. Windows
customers make one browser download to 1.4.3; from then on they
self-update. Linux and macOS clients on 1.4.1+ update to 1.4.3 in-app.

# 1.4.2 — the in-app update finally sticks

Found by actually running one: a real frozen 1.4.0 Linux build, the signed
1.4.1 manifest, real assets, the real swap — and then the new build rolled
itself back on its first launch. Every in-app update through 1.4.1 did.

**Was:** `apply_update.mark_pending_confirm()` wrote a marker after the
swap and `check_and_rollback_if_pending()` treated ANY marker at startup as
"the previous launch never confirmed". The very first launch of the
swapped-in build is the one that finds the marker — so it restored the
backup, noted a rollback, and relaunched the old version before a single
window opened. Nothing in the tests exercised swap-then-first-launch;
`test_pending_marker_at_next_launch_triggers_rollback` codified the bug.

**Now:** the marker is two-phase. The first launch appends `launched` and
carries on; `confirm_startup_success()` removes the marker once the window
is up; only a SECOND launch that still finds it rolls back. Because the
decision runs in the NEW binary, 1.4.0 and 1.4.1 clients updating to 1.4.2
get the fix — their own code only stages and swaps.
`tests/test_apply_update.py::ConfirmAndRollback`.

**Also from that run:**

* `updater._get()` opened a fresh connection to github.com, followed its
  redirect to the asset CDN, and closed it — for every one of ~1000 files.
  GitHub throttles that pattern: 3 s per tiny file from the long-running
  process, 0.3 s from a fresh one; an 80 MB update took 25 minutes and
  looked hung. One keep-alive `requests.Session` (`updater._http()`): the
  same update now stages and verifies in 52 s.
* GitHub allows 1000 assets per release and the 1.4.1 Linux build had
  1022, so its assets release could never be complete (only the files that
  differ from 1.4.0 were published, which is all a 1.4.0 client asks for).
  `packaging/prism.spec` now trims licence texts inside `*.dist-info/` and
  `.pyi` stubs — nothing reads them at runtime — and
  `packaging/manifest.py` fails the build over 1000 rather than letting
  `release_all.py` discover it an hour later.

# Round 30 — a picture is an inquiry, and the Files step speaks plainly

The client's case (11 Sep): a customer mails a crop of a brochure — the
product photo with "SS Locker (8 Comp)  KJP 3" printed under it — and
nothing else. Until now that inquiry had no product and nothing to quote.

* **Pictures are read on the machine.** `core/ocr.py`: RapidOCR
  (`rapidocr-onnxruntime`, models inside the package, ~30 MB with its
  runtime, the same wheel on Windows, macOS and Linux, nothing to install)
  first; the OS's own reader on a Mac as a fallback from source;
  tesseract if it happens to be there. On the client's crop it reads
  "ss Locker (8 Comp)" and "KJP3" in 0.2 s. The picture never leaves the
  machine.
* **The check reads what it files.** Every picture attached to a new
  inquiry (or a reply) is read as it is saved; the text is kept beside it
  as `image_text.txt`; when the mail itself said nothing, "Product asked"
  becomes the picture's words marked *(read from the picture)*. The code
  finder reads the same file, so "KJP3" in a picture matches the
  catalogue row "KJP 3", and the quantity comes from the mail's words. A
  picture with no quantity anywhere is held, as it should be.
* **The quotation window says what it read** — *Read from their picture:
  SS Locker (8 Comp) · KJP3* — beside what they typed, so the person can
  see the code came off a screenshot.
* **The Files step, rewritten for a workshop owner.** Three things, said
  in their words: *Price list (catalogue)* — one row per product, code,
  name, unit, price, Excel/CSV/PDF/Word; *I don't have fixed prices — I
  work each price out* — the cost sheet, folded away because a catalogue
  seller never needs it (open when one is saved); *Your old inquiry sheet*
  — the Excel they kept by hand, so numbering carries on, with "This is
  NOT your price list" in the help. Selftest reports the picture reader.

Tests: `tests/test_picture_inquiry.py`.

# Round 29 — quote by product code, and send it yourself if you say so

A client's ask (11 Sep): their customers write the catalogue code and the
pieces ("chair 1128K x 40"), the code is on their price list, and they
want the quotation to go straight back. The Rate list under Email
automation → Setup → Files was already that price list; three things were
missing.

* **Any file.** The rate list reads from PDF, Word and plain text as well
  as Excel and CSV (`quoting.load_rates` → `_rows_from_document`, over the
  same text extraction attachments use). A scanned PDF is refused with a
  reason; the picker and the help text say which formats work.
* **Every code in the mail.** `quoting.find_requests(text, items)` reads
  each rate-list code the mail names, in order, with the quantity written
  beside it ("1128K x 40", "40 pcs of chair 1128K", "1129K: 12 pieces").
  A code is exact, never fuzzy. A code with no quantity comes back
  unconfident. The quotation window shows a lines table when a mail names
  more than one code, prefills the single form when it names one, and the
  quotation itself carries every line.
* **Auto-send, opt-in.** A switch in the same setup group: "Quote
  automatically when the mail names product codes from this list with
  quantities". Off by default. After every mailbox check, each new inquiry
  is planned (`addons/inquiry/autoquote.py`): if every code matched and
  every line has a quantity, the quotation is numbered, saved, and sent
  from the default account under the saved terms, and the row is marked
  Quoted like a hand-sent one; otherwise the row stays in "To quote" with
  `auto-quote held: <why>` in its Notes. Sends run one at a time.

Tests: `tests/test_autoquote.py`.

# Round 28 — Harsh's BOQ pricing and Sent-copy get their windows

Harsh's 10 Sep landing (engine `de4ed63`) brought two things the GUI could
not show: `core/boq_price.py`, which prices a measured take-off into a
tender-ready BOQ, and a Sent-folder copy of every email the mailer sends.
Both were live in the engine and invisible in the app — the pricing had no
caller at all, and the copy was on with nothing to say so or switch it off.

**BOQ — "Price it (optional)"** (`addons/boq/pricing.py`, shown under the
measured table once a drawing is measured, BOQ mode only — a BOM is a parts
list):

* one grid row per measured line, in the measurement's order; Qty is the
  measurement and Amount is arithmetic, so neither takes typing; Section,
  Description, Unit and Rate do;
* **Attach your rate list…** (CSV / XLSX, read by the same `core.quoting`
  loader Inquiry's quotations use; the price list already given to Inquiry
  is picked up automatically), or **Use starter rates**, marked indicative;
* a library rate is applied only when the match is confident AND the units
  agree — a per-cum rate never prices a wall measured in metres; the row
  stays unpriced and says why;
* contingency %, GST % and inter-state (IGST vs CGST+SGST); the totals
  line with the grand total in Indian words; unpriced lines counted and
  kept out of the total;
* **Save as Excel…** (live `=Qty*Rate` / `=SUM` formulas, Abstract of Cost
  sheet), **CSV**, **PDF** (needs the bundled Chromium).

No AI touches a number here, and the write-up prompt is unchanged: pricing
sits beside the writing stage, never inside it. `core_bridge.get_boq_price()`
is the one door. Tests: `tests/test_boq_pricing.py`.

**Email — "Keep a copy of each email in the account's Sent folder"** in
the Pace and limits card, on by default as the engine has it, named in the
folded summary ("copy kept in Sent" / "no copy in Sent"), handed to the
worker as ticked, remembered with the pace, and carried across an account
save like `folder` (`email_config.save_to_sent` / `with_save_to_sent`).
The terminal's `/email` reads the same key. Tests: `ACopyInSent` in
`tests/test_email_pacing.py`.

**Shipping to a Mac with nothing on it** (`devtools/make_bundle.py`,
`packaging/Install and Run Prism.command`): a zip of the tracked source of
both repos plus one double-click launcher that finds or fetches a
standalone Python (no admin password, no Homebrew), makes the venv,
installs the requirements, fetches Chromium, checks for Google Chrome and
starts Prism — and on the next double-click just starts it. Interim until
the Developer ID certificate lets the DMG be signed. See
`packaging/README-INSTALL.txt`.

# Round 27 — the measurement says what the coordinates say

Reading the same site survey by hand settled three things no BOQ written
from its totals had: the unit (a projected survey grid in metres, and a
7 m gate block placed at scale ~0.001), the two boundary-wall layers (one
wall on two layers — together they close the footprint), and six of seven
pump houses sitting 1 – 4 km away on a pipeline. `core.boq.measure()` now
walks the same coordinates once more and reports `site`: the inferred
unit with its evidence, look-alike layers with a verdict (one run on two
layers / drawn twice / check), the main cluster's extent, and any block
farther than a kilometre from the rest with its distances. The summary
the AI reads carries them; the measured table on screen shows the unit as
inferred and the look-alikes and remote blocks in its warning band. All
local; nothing leaves the machine.

*Files:* `prism_terminal/core/boq.py`, `addons/boq/measured.py`,
`tests/test_site_facts.py`

---

# Round 26 — the measurement is a table

The owner's screenshot: "Measured from your drawing" showed the prompt
text — "LENGTHS BY LAYER:" and a wall of "layer: 498.44 unspecified"
lines in a 120 px box. That text is written for the AI, not for a person.
The box is now a table (`addons/boq/measured.py`): one row per measured
item in the CSV's own order — Item, Measured as (Length / Area / Count),
Layer, Value right-aligned with thousands separators, Unit — sortable by
any column, ten rows on screen and the rest scrolling, a header line with
units, entity and layer counts, the warnings (unit unconfirmed, scope
filter, conversion notes) in a warning band, and the full layer list one
click away. The prompt text is untouched; it is still what the AI gets.

*Files:* `addons/boq/measured.py`, `addons/boq/dialog.py`,
`tests/test_boq_dialog.py`

---

# Round 25 — the writer keeps the estimator's habits

Comparing two BOQs of the same site — one written locally from the
numbers with the firm's sample attached, one written by Claude with the
whole DWG — showed the template did its job (the local one is the
document the firm would send) and the drawing added no measurement (the
tool said so itself). What the drawing-fed one did better was habit, not
data: a reference table of the measured figures, a stated decision on a
duplicate wall layer, storage and power sized from the counts with the
arithmetic shown, existing poles reused as mounts. Those habits are now
asked of the local writer on every drawing-based BOQ.

*Files:* `prism_terminal/core/boq.py`, `tests/test_boq_dialog.py`

---

# Round 24 — a sample BOQ tells the writer what it is making

The owner's idea, after comparing a numbers-only BOQ with one written
from the drawing: do not give the AI the drawing, give it one of the
firm's own BOQs. The plumbing already existed — a `.docx`/`.xlsx`/`.pdf`
attached to the BOQ window was classed as a template and handed to the
Interpret and Format stages — but the screen never said so, and the
writer was told to treat it as a "style guide, take inspiration". Now the
BOQ front door offers it as a step, and the writer is told the sample
defines the document: its sections, columns, numbering, level of detail,
wording, units and boilerplate, and its design decisions for comparable
items, filled with this drawing's measured numbers, never its rows.

*Files:* `prism_terminal/core/boq.py`, `addons/boq/panel.py`,
`tests/test_boq_dialog.py`

---

# Round 23 — the BOQ drawing never reaches an AI either

The owner walked the BOQ flow and found the one gap in the rule every
measuring add-on keeps: the drawing was measured here, the Standards and
Interpret stages never saw it — but the Format stage attached the CAD
file to the writing tool "so it could analyse the drawing itself".

Now no stage receives the drawing, in the window and in the terminal's
`/boq` alike; the writer is handed the measured summary (every layer,
every block and count, the lengths and areas) and told plainly that the
file is not attached, to build every line from those figures, and to
flag anything only the layout could decide rather than invent it. BOM
mode, which shares the writer, says the same. Templates and notes still
travel.

*Files:* `addons/boq/dialog.py`, `prism_terminal/prism.py`,
`prism_terminal/core/boq.py`, `prism_terminal/core/bom.py`,
`tests/test_boq_dialog.py`

---

# Round 22 — the prompts are written for the plan you confirmed

The flaw behind the Canva run, named by the owner: the router wrote every
step's prompt when it made the plan — before anyone looked at it. Drop a
step, add one, move one, or switch its tool on the Plan screen and the
prompts did not follow: the presentation step was switched from Gamma to
Canva and Canva was handed Gamma's brief.

**Now Start the work checks whether the plan changed** (`router.plan_changed`
against `router.planned_steps`: membership, order, tools, and any step with
no prompt) and, if it did, **writes the prompts again for exactly the steps
you confirmed, in that order, on those tools** — one Groq call off the
thread (`PlanBriefWorker` → `router.brief_confirmed_plan`) before the
licence check. The drafts keep their substance; the tool and the order are
the truth; makers get the maker rule; the last step is told it is last.
The rewritten prompts are put back on the rows (`AgentsPanel.apply_prompts`)
so Prompt shows what will actually be sent. An unchanged plan keeps its
prompts and starts as before. If Groq cannot be reached the drafts stand,
and a step with no prompt gets a real floor (`passthrough_prompt`).

*Files:* `prism_terminal/core/router.py`, `workers.py`, `main_window.py`,
`widgets/agents_panel.py`, `tests/test_confirmed_plan.py`

---

# Round 21 — a tool that builds the thing is briefed to build it, and every stage is briefed like a colleague

The owner's second Canva run, from the prompt Canva received: *"Produce the
final deck in plain-text slide format ready for import into Gamma.app …
Do NOT generate actual PPT files."* Canva did as it was told and typed the
outline back. The stage prompt had been written for a chat tool, and it
named the wrong tool.

**Makers.** The registry now says what each tool builds (`makes`: Canva an
editable design, Gamma and Tome a presentation, Midjourney images, Runway
a video, ElevenLabs audio, v0 an app…). The router is told, per tool, and
when a maker is in the plan it gets a rule to brief it the way a senior
person briefs a designer: build this, with this content verbatim, this
look, this count — never "plain text", never "do not generate files", and
never a different tool's name. At run time the engine opens a maker's
stage with a plain brief — *"You are Canva, and what I need from you is an
editable Canva design … build it here … if anything below asks for plain
text or says not to create files, that was written for a chat tool and
does not apply to you"* — reads the context to it the human way, and never
asks it for a handoff section.

**Every other stage, in the same voice.** The numbered "STRICT PIPELINE
RULES" block that closed each chat prompt now reads as a colleague's
note — what the answer is for, who reads it next, the one section that
has to be there (`HANDOFF FOR <NEXT>`, unchanged, because the relay parses
it) — and the final stage is told it is the last step and the answer goes
to the person. Machine-read stages (JSON specs, image batches, Apollo's
filter block) keep their strict wording on purpose.

Engine only. Tests in `tests/test_makers.py`.

---

# Round 20 — an empty ChatGPT answer is caught in seconds, and Canva builds the deck

From the owner's run log of 10 Sep, two faults.

**ChatGPT finished with nothing, and Prism waited 300 s for it.** The tab
showed a new assistant turn with no text and no Stop button — the toolbar
under a blank bubble — and `_smart_wait`, which watches text grow, ran out
the whole cap. Now a tool can say which element means "still generating"
(`busy_selector`) and which means "a reply" (`turn_selector`); when a new
turn has sat idle and empty for a short while the wait ends, the tool's
own regenerate control is pressed once (`_regenerate_once`, hover-only but
in the DOM), and if it is empty again the stage fails at once and the
fallback tool takes it. ChatGPT's selectors were read off the live page.
The user can also press **Use fallback** (Round 19) the moment they see it.

**Canva never received the prompt, then never pressed Generate.** The
registry pointed at `/magic-design/`, a marketing page with no composer.
Probed live with Playwright: Canva AI lives at `canva.com/ai`, opens under
a promo dialog whose video swallows clicks (Escape closes it), takes the
prompt in the one labelled textarea, sends with `button[aria-label='Submit']`
— and answers with an *outline* first, needing "View outline" → "Generate
design" before a deck exists. `_run_canva` makes those moves; the thread
URL is the saved link (the deck opens from its card there and lands in
Projects). Verified end to end: a 3-slide deck built through both paths.

**The prompt header is shorter.** The block that carries the customer's
own words to every tool now says its rule in one sentence — summaries lose
things, the words above win, specific facts must survive — instead of a
paragraph. The stall was not the prompt's length, but every tool reads it.

Engine only. Tests in `tests/test_empty_answer.py`.

---

# Round 19 — Use fallback: hand a stuck step to its fallback tool now

The owner's ask: Prism waits a fixed time for a tool and only then hands
the step to the next tool in its category — but the person watching can
often see the tool has errored, and does not want to sit out 600 seconds
for Prism to notice.

**Use fallback**, beside Skip this step on the run screen. Pressing it
stops the wait on the running step and runs the failover pass for that
one step immediately — the next tool in the same category, the same
`_retry_failed_stages` the end-of-run pass uses — so the stages after it
get its answer instead of running on thinner context. What the stuck tool
had on the page is not kept; the person pressed the button because they
could see it was not going to answer. Pressed again during the retry, it
abandons that tool too and moves to the next one. Not latched; the engine
clears the flag per press, like Skip.

Wiring, in the same shape as Skip: `OutputPanel.fallback_requested` →
`MainWindow._use_fallback` → `AutomationWorker.use_fallback()` →
`run(fallback_signal=)`. The engine's per-stage waits (text and image)
poll it through `stage_halt()`; a nested retry run never fails over again.

*Files:* `prism_terminal/core/automation.py`, `workers.py`,
`widgets/output_panel.py`, `main_window.py`, `tests/test_use_fallback.py`

---

# Round 18 — the Canva hand-off, verified live, and the two reasons Prism skipped it

The owner's report: ask Prism for an Instagram post *"and make it editable /
in Canva"* and ChatGPT should draw the picture and then hand it to its
Canva app — and it no longer did.

**Verified with Playwright first** (`devtools/canva_probe.py`, on a copy of
Prism's own Chrome profile). The hand-off itself works: ChatGPT drew the
post, the follow-up `@canva …` was answered by the Canva app with a card and
`CANVA LINK: https://www.canva.com/d/…`, and that link opens a real editable
1254×1254 design in the owner's Canva. ChatGPT still routes a plain
`@canva` in the message text to the app; the response selector still finds
the text turn. So the engine's plan was right and the run was failing
around it.

**Reason one — a picture has no words.** ChatGPT answers an image request
with the image and no prose: the assistant turn is an `<img>` and an
"Edit" button. `_capture()` therefore came back empty, and
`_make_editable()` read an empty capture as "nothing was made" and skipped
Canva — while the picture sat on screen. `run()` now tells the step whether
a picture rendered (`made_image=bool(got)` off `_wait_for_images`), and a
rendered image counts as something to convert.

**Reason two — a short answer was thrown away.** `_capture()` drops
anything under fifty characters, to lose buttons and chips. `CANVA LINK:
none` is sixteen; a real link can be under fifty. So the one reply the
step most needs to read was the one discarded, and "not connected" read
as "did not answer". `_capture(keep=)` keeps a reply carrying the marker a
caller is waiting for, and `_reask()` passes its `expect` through.

Engine only (`core/automation.py`); no add-on, no shell, no registry
touched. Tests in `tests/test_canva.py`.
# Round 17 — a list is not a blast: pace, limits and sending later

The owner's ask, in two lines: *limit and schedule the mails*, and *the
difference of time between the emails*. A list used to go out to everyone,
two seconds apart, the moment Send was pressed.

**Pace and limits**, a card under the letter in the Email window: the gap
between emails plus a random extra on top (so the pauses are not a
metronome), a per-press cap and a per-address daily cap (counted off the
sent log, across windows and days), and *Send later, at* a chosen time.
The note under the card and the Send button both say what will happen in
words — *Send to 88 of 120 people*, *Daily limit reached*. After a capped
send the window stays open with exactly the people who did not go, so the
next press continues. The numbers persist in `cfg["email"]["send"]`.

**Folded by default (10 Sep).** On the owner's screen the open card pushed
the Message box down to one line, the date picker drew unstyled and the
note was clipped. The card is now a title, the setting in words (*2 s
apart · everyone at once · no daily limit · sends now*) and **Change**; it
opens to a proper form and opens on its own when a saved setting is not
the default. The window scrolls; `QDateTimeEdit` joined the stepper rules
in `style.qss`.

**Engine:** `core/mailer.py:send_bulk()` grew `jitter`, `limit`, `start_at`
and `on_wait`; the scheduled wait happens before the SMTP login and a stop
during it sends nothing. `pause_after_send()` is the one place the gap is
computed. The terminal's `/email` reads the same gap, jitter and per-send
cap out of the config.

**Kept inside the Email add-on and its own data module**, per the
architecture: `addons/email/dialog.py`, `addons/email/sent_log.py` (each
entry now records `from`, and `sent_today()` counts it), root-level
stdlib-only `email_config.py` (`send_policy`, `with_send_policy`,
`plan_send`; the policy survives `account_block` and `cfg_for_sender`),
`workers.py:SendWorker` (the parameters pass through; a `waiting` signal
counts down). No other add-on touched; Email automation's own sends are
single messages and are unchanged.

*Files:* `prism_terminal/core/mailer.py`, `prism_terminal/prism.py`,
`email_config.py`, `addons/email/dialog.py`, `addons/email/sent_log.py`,
`workers.py`, `docs/EMAIL_SEND.md`, `tests/test_email_pacing.py`,
`lang/_catalogue.json`

---

# 1.4.1 — a Mac can install, update and re-seat itself; Studio V2 is whole

Three threads, one release. The first two came out of reading the macOS
install and licensing path end to end for the first time
(`prism+gui/artifacts/macos-install-and-licensing-2026-09-08.html`); the
third finishes the Studio V2 / Motion work that had been sitting
uncommitted.

## The macOS updater swapped the wrong folder

**Was:** `updater.install_dir()` returned the executable's parent —
correct for a PyInstaller onedir on Linux and Windows, but on a Mac that is
`Prism.app/Contents/MacOS`. `apply_update.perform_swap()` renamed *that*
aside and dropped a whole staged tree in its place, so the first in-app
update left a bundle with no `Info.plist`, no `Frameworks/` and a broken
signature seal. Finder then refused to open it. CI compounded it by
hashing `dist/Prism` (the COLLECT folder) for the macOS manifest, a tree no
installed Mac has.

**Now:** `updater.bundle_root()` walks up to the `.app` and the whole
bundle is the swap unit; the pending-confirm marker is written *beside* it
(a stray file inside a bundle also breaks the seal); CI hashes
`dist/Prism.app`. And because every 1.4.0 Mac still carries the old swap
code, macOS moved to a new update channel name, `macos-arm64-app`: a 1.4.0
Mac fetches `manifest.macos-arm64.signed`, gets a 404, and takes the
browser-download fallback — the only safe path for it. Never publish under
the old name again. `tests/test_apply_update.py::MacBundle`,
`tests/test_updater.py::PlatformChannel`.

## Signing is wired, waiting on an Apple account

`packaging/codesign.py` already did Developer ID + hardened runtime +
notarytool + stapler; nothing ever set `MACOS_SIGN_IDENTITY`. The workflow
now imports a `.p12` into a throwaway keychain and passes the six secrets
through — all optional, so an unset secret still builds unsigned exactly as
before. The `.dmg` itself is now signed, notarised and stapled too
(`codesign.sign_macos_archive`); before, only the bundle inside it was.
BUILD.md and the release notes gained the macOS 15 "Open Anyway" path,
which replaced right-click → Open.

## SEAT_LIMIT_REACHED is a choice, not a ticket

**Was:** the server answered "every seat is in use" *with the list of
machines*, and the client showed only the sentence. A customer whose old Mac
was reimaged, repaired or migrated (a new IOPlatformUUID) sat at the one
machine that could not activate, and the only way out was an admin release.
`device.py` had predicted this as the most common support ticket.

**Now:** the licence dialog lists the machines with when they were last
used, and one click frees the chosen seat and activates here, through a
new `POST /v1/release` that takes the licence key as proof — the same proof
activation takes to grab a seat, so it grants nothing the key did not.
`tests/test_license_seats.py`; server `tests/test_api.py` (+2).

## Smaller licensing changes

* `keyring` is on. Every build before this wrote the reusable licence key
  in the clear to `~/.prism/license.json` because the line was commented
  out "for later". On macOS an updated (re-signed) Prism gets one keychain
  prompt; Deny is survivable — the customer retypes the key once.
* Server `offline_hours` default 1 → 24, matching what `issue-key.sh`,
  `trial.sh` and `grant.py` always passed. Only a licence minted through
  the raw API differed, and it stopped authorising an hour into a train
  journey.

## Studio V2, finished

The uncommitted rewrite had the right bones — durable `data-prism-id`
layers instead of child-index paths, browser modules as real files under
`core/studio_assets/`, a `/refine` endpoint back into the design
conversation — and three things that made it unusable as it stood:

* **The canvas did not fit its column.** `editor.css` fixed `#stage`'s
  edges but never overrode the harness's 1080×1920, so the reel drew near
  full size under the right panel and below the fold; the workspace test
  timed out on a click the transport intercepted. The stage now sits in its
  own viewport and is scaled *as one unit*, the way V1 did it.
* **`fit()` wrote an inline `transform` on every scene**, which is exactly
  the property the cut library drives — so no push, squeeze or zoom ever
  showed in the preview. Scaling the stage instead leaves scene transforms
  alone; scrub across a cut and it plays.
* **The editor had lost V1's tools** while the Python still accepted every
  record: add text / picture / shape, colour, background, font, size,
  weight, align, front/back, delete/reset, scene length and background,
  palette and typeface swap. All back, inside the V2 inspector, one undo
  step per control.

Also: a reel the AI router filmed never got `_studio` (the design
conversation), so Refine was dead for every reel opened from Artifacts —
`automation._studio_conversation()` finds the nearest earlier stage with a
chat URL and `_run_studio` stores it. `build_html()` stamps ids on every
page it builds, so an edit made in the editor finds its layer on the render
page for a spec that predates stamping. The V1 `#__ed-bar`/`#__ed-side`
stubs are gone; the two browser tests that waited on them now drive the V2
ids. `tests/test_studio_v2.py` (+2), the browser lane in
`tests/test_reel_edit.py` and `tests/test_reel_editor_tools.py`.

## Motion is back, with the check its kill-switch asked for

The switch-off comment said: re-enable only after "a real attached-image
render". `tests/test_motion_assets.py::AttachedImageReachesTheFilm` films a
spec with an attached red PNG and reads the pixel out of the MP4. The
packaged self-test gained `Studio editor + Motion runtime files`, because
both are data files a bundle can lose without any import failing.
# Round 16 — STEP moves into `addons/step/`, on top of the add-ons migration

**Landed 8 Sep 2026.** Rebased onto `origin/main` after PR #8 (the
migration) and the 1.4.1 / Reel Studio round had merged; the engine commit
was rebased onto the engine's `origin/main` (Studio V2) — one conflict in
`core/automation.py`, resolved by keeping the upstream no-prompt guard and
folding the Studio hand-off into `_run_local_stage`. `workers.py` keeps
both sides' new `AutomationWorker` parameters. Engine pushed first, then
the app, per `CONTRIBUTING.md`. A `CLAUDE.md` at the root now points every
Claude session at the architecture and landing rules.

`origin/chore/addons-migration` (het-vaghela-21, ~24 commits) restructures
the app: every add-on is a folder under `addons/<key>/` declared by a
stdlib-only manifest, `addons/registry.py` is the one shared file an
add-on touches, `widgets/simple_panels.py` is gone, and eight rules are
enforced by guard tests (`CONTRIBUTING.md`, `docs/architecture/`). It is
NOT on `main` yet. Rounds 12–15 were built on the old layout, so this round
rebuilds the STEP add-on the way the new rules say, on a local branch
`step-addon` cut from the migration branch. Nothing is merged into `main`
and nothing is pushed.

**What STEP is now.** `addons/step/addon.py` (`MANIFEST`: key `step`,
feature `boq` like Gerber and BOM, order 35 so the three measuring add-ons
sit together, screen `step`, probe `core_bridge:step_available`, remedy
`cadquery`, run prefixes `"STEP — "` and `"/step"`, engine `stepfile`,
offers `names.MEASURE_MODEL`), `contract.py` (`open_with_files` — plain
paths in, the dialog shapes them), `panel.py` (`StepPanel(AddonFrontDoor)`),
`dialog.py` (the Round 13–14 dialog, unchanged apart from where its workers
come from), and `workers.py` (the three STEP workers, each a
`workers._Worker`). One import line in `addons/registry.py`; one intent in
`addons/names.py`.

**What the shell needed.** The rail, Home, History and the licence gate
now read the manifest, so `widgets/sidebar.py` and `widgets/panel_base.py`
were not touched. `main_window.py` still builds each screen by hand, so it
gained the `"step"` entry in `SCREENS` (appended last), the panel, the
`opened` wiring, the `_handle_command` branch and `_open_step` /
`_open_step_dialog`. `core_bridge.py` gained `step_available()` and
`get_stepfile()` (rule 2: only the bridge imports the engine).
`workers.py` keeps only the `AutomationWorker` additions from Round 13
(`files_out`, `image_stages`, `failover`).

**The guard tests learned about STEP in the same commit**, as
`CONTRIBUTING.md` asks: `GOLDEN_RAIL` / `GOLDEN_HOME` in
`tests/test_addon_contract.py`, `PANELS` in `tests/test_screen_registry.py`,
`ADDON_FEATURES` in `tests/test_addon_gates.py`. `tests/test_step_dialog.py`
was re-pointed at `addons.step` and its shelf/routing checks rewritten
against the registry and a real window — the old version grepped
`main_window.py`, which the new rules forbid. `lang/_catalogue.json`
regenerated (56 strings added, none removed).

**The engine is unchanged by the migration** and its pin on the branch is
the same commit `main` pins, so the Round 12–15 engine work (`stepfile.py`
naming and drawing sheets, `automation.py` skip-during-retry and deferred
local stages, `config.py`'s `step_out_dir`, `prism.py`'s `/step-folder`)
carries over as-is. It sits on a local branch `wip/step-engine` in
`prism_terminal/`.

**Local branches, none pushed.** `wip/step-old-layout` (prism_gui) holds
Rounds 12–15 exactly as they were on the old layout; `wip/step-engine`
(prism_terminal) holds the engine work; `step-addon` (prism_gui) is this
round. `main` in both repos is untouched.

*Files:* `addons/step/*`, `addons/registry.py`, `addons/names.py`,
`main_window.py`, `core_bridge.py`, `workers.py`, `tests/test_step_dialog.py`,
`tests/test_addon_contract.py`, `tests/test_screen_registry.py`,
`tests/test_addon_gates.py`, `lang/_catalogue.json`

---

# Round 15 — a reel run that failed three ways, from one screenshot

A live reel run: "Make the images" failed on ChatGPT and was being retried
with Canva; **Skip this step** did nothing; and "Make the video" already
read FAILED underneath, before the images had a second chance. Three
faults, one fix each.

**Skip works during a retry.** `_retry_failed_stages` started its nested
`run()` without the skip flag, so a press during a retry — the one place a
customer is most likely to press it — was ignored. The flag now reaches
the nested run's waits (as a stop, so it winds up and keeps what landed),
a press abandons the remaining alternatives for that stage instead of
trying the next tool anyway, and the screen gets a `stage_skipped` saying
so. A promised image stage keeps its full budget through a retry too.

**The video waits for its images.** A local renderer (Reel, Studio,
Motion) ran in its turn regardless of what came before. Now, when a stage
before it produced nothing and failover is about to retry that stage, the
renderer is held back and run after the retry pass — with the pictures if
they came, honestly without them if not, but never before the retry that
could have supplied them. Its card stays queued meanwhile instead of
turning red.

**The script example is a placeholder.** Step 2's Claude reply began "A
quick flag: the tail end of your prompt demands a JSON schema about Bombay
Super Hybrid Seeds" — the OUTPUT FORMAT block's example was a realistic
sample about a named seed company, and the model read it as a smuggled
second brief and refused. No JSON, so the video stage had nothing to
build from. The example is now `<Example Company Name>` with placeholder
figures and says so.

*Files:* `core/automation.py`, `core/reel_web.py`, `tests/test_skip_step.py`

---

# Round 14 — the drawing sheet is drawn by Prism, and the AI one waits properly

`/step-auto` asked an image model for the dimension sheet and got back a
blurred preview, because a generic `visual` stage waits 60 seconds for a
picture and gives up after 12 if none has shown — while ChatGPT's image
model takes one to three minutes and shows a progressive preview that
counted as "an image, unchanged for 20s, done".

**Two changes, the second the one that matters.**

**1. The wait.** `automation.run(image_stages=…)` lets a caller promise
that a stage's deliverable IS a picture; such a stage gets a seven-minute
cap (the loop still returns the moment the picture settles). And
`_wait_for_images` now watches each image's source and size, not just the
count — a preview replaced in place by the finished picture is a change —
and keeps waiting while the page itself says it is still creating the
image. `/step-auto` and the STEP dialog's Draft both make the promise.

**2. The sheet, without an AI.** `core.stepfile.sheet_svg()` draws the
dimension sheet itself from the geometry: for every part, front, top and
side views by OpenCascade hidden-line projection (hidden edges dashed), the
overall sizes on real dimension lines in millimetres to two decimals, the
isometric, a hole table, notes and a title block — the layout of the
hand-made sheet this whole add-on replaces. It takes about a second and
every figure on it is the measured one. `/step` writes it every time as
`<model> - drawing sheet.svg` / `.html` / `.png`; `/step-auto` and Draft are
now the optional styled extra, not the only way to get a dimensioned sheet.

**3. ChatGPT only, and the file first.** The styled sheet is ChatGPT's job:
not whichever visual tool Agents names, and no hand-off to another image
model if ChatGPT stumbles (`failover=False`) — a second, differently-wrong
sheet is not a rescue. And the STEP dialog now asks for the model before
anything else: the question box and the Draft / Ask / Edit choice only
appear once a `.step` is attached.

*Files:* `core/stepfile.py`, `core/automation.py`, `workers.py`,
`prism.py`, `dialogs/step_dialog.py`, `widgets/simple_panels.py`,
`tests/test_stepfile.py`, `tests/test_step_dialog.py`

---

# Round 13 — the STEP add-on has a screen

The terminal had `/step`, `/step-auto` and `/step-ask` for a fortnight; the
GUI had nothing. Now it is an add-on like Gerber: a rail entry, a front-door
screen and a dialog.

**How it works.** Attach one or more `.step` / `.stp` models. The first
time, Prism asks where the files for your models should live (choose a
folder, or the Desktop) and keeps the answer; a folder named after each
model is made inside it, every file carrying the model's name (Round 12).
Pick the material (metal or plastic) and one of three actions:

- **Draft** — measure, then the image tool draws a dimensioned drawing
  sheet from the numbers; the sheet it returns is saved beside the rest.
- **Ask** — measure, then Groq suggests improvements from the numbers and
  your question, and the reasoning tool reviews them into an exact change
  plan on a review page. Nothing is changed.
- **Edit** — Ask, then — after you confirm against the review page — the
  plan is applied to a COPY of the model, here, and the copy is re-measured
  so the After column is real.

**The rule.** The STEP file never leaves the machine. Every AI stage is
given the measured numbers and Prism's own plain render of the parts, and
`tests/test_step_dialog.py` intercepts the worker calls to prove it — the
same tests Gerber has, for the same reason.

**The rail.** This is the thirteenth control on a rail the header of
`widgets/sidebar.py` holds at twelve. The scroll floor carries it; the day
one measuring add-on is folded into another, this is the row to fold.

*Files:* `dialogs/step_dialog.py`, `workers.py` (three STEP workers, and
`files_out` on AutomationWorker), `core_bridge.py`, `widgets/sidebar.py`,
`widgets/simple_panels.py`, `main_window.py`, `tests/test_step_dialog.py`

---

# Round 12 — STEP files are named after the model, and go where you say

An estimator keeps ten jobs' sheets in one place, and `/step` wrote
`dimensions.xlsx`, `drawing.png` and `modified.step` for every one of them
— ten files nobody could tell apart — into a folder called
`Assem1_1757000000` on the Desktop.

**Now:** every file starts with the customer's own file name. For
`Assem1.STEP`:

    Assem1 - dimensions.xlsx
    Assem1 - drawing sheet.html / .png
    Assem1 - view top.svg, Assem1 - view side.svg …
    Assem1 - AI drawing sheet 1.png          (/step-auto)
    Assem1 - change review.html              (/step-ask)
    Assem1 - modified.step
    Assem1 - dimensions after change.xlsx
    Assem1 - drawing sheet after change.png

They live in a folder named after the model, `<root>/Assem1`, and a
second run of the same model gets `Assem1 (2)` rather than overwriting the
first. `root` is the person's choice: the new config key `step_out_dir`,
set from the terminal with `/step-folder <path>` (the GUI will ask the
same question in a dialog when its STEP screen is built) and defaulting to
`~/Desktop/Prism Step` as before.

All the names come from one place, `core.stepfile.names()`, so the
terminal, the review page and a future GUI cannot disagree about what a
file is called. Spaces in the names are URL-quoted in the HTML.

*Files:* `core/stepfile.py`, `core/config.py`, `prism.py`,
`tests/test_stepfile.py`

---

# Round 11 — the Apollo prompt lands in the box that reads prose

A live run with Apollo as the first stage ended with the pipeline prompt
sitting in Apollo's small "Search people" keyword box and a table of zero
rows. That box is a plain keyword match; a sentence in it finds nobody.

**Was:** with no `HANDOFF FOR APOLLO` block to build a URL from,
`_run_apollo()` typed six words of the brief into whatever the first
`input[placeholder*='Search']` on the page was — the toolbar keyword box.

**Now:** the brief goes into the "Use Apollo AI to find the right prospects"
field (`input[role='combobox'][placeholder^='Example:']`). Enter hands it to
Apollo's AI Assistant, which opens as a side panel, thinks for 30–60 seconds
and applies Titles / company keywords / Location to the People grid — the
same grid `_capture()` already reads. Prism waits for the **Total** tile to
move off the unfiltered count (or for rows) before capturing. The keyword
box is now the last resort, reached only when the AI box is missing or the
account shows `0 CHATS LEFT`; a filtered URL search that matches nobody also
gets one try through the AI box.

**One trap, found the expensive way:** the box only renders while no
search is applied, and a restored Prism session brings the People page back
with last run's keywords still set. The button labelled **Search with AI**
does not bring the box back — it opens an assistant chat about the current
search and spends a chat doing it. **Reset filters** does, and so does the
bare `#/people` route; `_apollo_ai_box()` tries those and never touches
the other button.

**Why these selectors:** found with Playwright on the live app, not guessed.
Apollo's `zp_*` classes are hashed per deploy; the role and the rotating
"Example: …" placeholder are stable. The box kept a 4,000-character paste
with no `maxlength`, so `ai_prompt_max_chars` is a measured figure. The
probe is kept as `devtools/apollo_probe.py` for the next time Apollo moves
things around.

**Cost to the user:** one assistant chat per prompt. The free plan allows
five a month, which is why the URL route stays first whenever a filter block
exists.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_apollo.py`,
`devtools/apollo_probe.py`, `KNOWN_ISSUES.md`

---

# Round 10 — Prism knows when a newer Prism exists (1.3.1)

The licence server has sent `latest_version` and `min_supported_version` on
every lease since the authorisation-lease round, and every client dropped
both on the floor. Customers learned about a release from an email and then
went looking for the download. This round is Phase 0 of `../update-plan.md`:
read the two values, say so, and ship that as **1.3.1** — because every later
phase of the updater needs customers on a build that can *see* an update.

## The advice reaches the state

**Was:** `_store_lease()` kept the lease and nothing else. The two version
strings beside it were never read.

**Is:** `LicenseState.latest_version` / `.min_supported_version`, persisted in
`license.json` off every lease and authorize response — and off the `detail`
of a `CLIENT_TOO_OLD` refusal, which is the only lease answer a retired build
ever gets, so it can say "update" rather than "can't reach the server". Drawn
at launch with no network. A field the server stops sending is left alone; one
it sends EMPTY is cleared, which is how a banner is withdrawn without a client
release. Neither string is signed, so neither can do more than change wording
— `updater.py`'s docstring is the trust statement.

## The banner, and where it sits

Third in the pecking order, behind a licence problem and an unreachable
shared folder: "Prism 1.4.0 is available. You have 1.3.1." with **Download**
(opens `app_meta.DOWNLOAD_URL`, a fixed address, never one from the response)
and **Not now**, remembered per version in `~/.prism/update_state.json` — so
the next release brings it back. A build below the server's floor gets "can
no longer start new work — update to continue" with no Not-now, and that one
outranks the shared-folder banner because new work is already refused.

## Settings › Diagnostics › This installation

The Version row grew **Check for updates**. `licensing.refresh()` gained
`on_done`, called on its worker thread once both round trips have landed; the
panel hands it a Signal's `emit`, Qt queues that back to the UI thread, and
both the page and the window's banner redraw. It says "You have the latest
version" only after a check — never as a standing pat on the back.

## Release runbook

`SHIPPING.md` §1.3: once the Release is up, set `LATEST_CLIENT_VERSION` in
Render. `render.yaml` now declares it `sync: false`; `MIN_CLIENT_VERSION`
stays the enforcing lever and stays unset.

Tests: `tests/test_updater.py` (version compare, state, `on_done`, Not-now)
and `tests/test_gates.py::UpdateBanner` (pecking order, dismiss, Download,
the Check-now round trip).

---

# Round 9 — the help screen learns to talk, and the way to a person is real

Round 7 shipped Help & support with tiers two and three as placeholders, on
instruction. The instruction changed after a day of real use, and so did a
verdict on the first version's feel: a chat screen that posted every menu
into the thread and left it there read as a form that kept growing.

## The transcript behaves like a conversation now

**Was:** ten full-width topic cards in the thread, then ten question rows,
then ten more topic cards when somebody went back — all of them still
pressable for ever, which is both a wall to scroll and a fork waiting to be
clicked.

**Is:** three rules. Topics are CHIPS — their names are two words, so ten of
them take three short rows and the whole opening fits above the fold
(questions stay full-width rows, because a truncated question cannot be
chosen). A menu is RETIRED the moment the conversation moves past it — the
pick already survives as the customer's own bubble, so nothing readable is
lost. And Prism's messages carry its mark, because two voices in one column
need telling apart faster than reading them. Plus a Start over button — the
screen keeps its thread across visits by design, which made "begin again"
impossible without one.

## The assistant is real — the customer's own Groq key, on a leash

The button now starts a conversation with a model, and everything about the
wiring is about keeping it honest:

* It answers **from the written help, not from its imagination**: every
  question heading (so it knows the true shape of the product), the full
  text of the answers matching this question, and the ones already read —
  marked *do not repeat these*. The first rule of its instructions is to say
  "I don't have that one, press Contact the team" rather than guess, because
  a made-up menu item costs the customer more than an admitted unknown.
* It starts knowing the four facts half of every support call is spent
  establishing: version, whether a key is saved, the platform, the licence
  state.
* Temperature 0.15 — support answers are quotations from the manual, and a
  model feeling creative about which menu an option lives in is the one
  failure this tier cannot afford. A test pins it.
* Its failures go through `friendly.explain()`, so the assistant breaking
  reads exactly like the rest of the app breaking — a sentence and steps,
  never a code. No key saved: it says so and offers the Settings button,
  because the customer least likely to have a key is the one who has not
  finished setting up.
* An animated Thinking bubble while it works, and the window's own shutdown
  now winds the assistant's thread up — a running QThread destroyed with its
  owner aborts the process, and Prism vanishing mid-question is a memorably
  bad way to end a support session.

## Contact the team hands the whole story to a person

The sheet arrives pre-filled with what a support thread spends its first
three replies asking for: version, platform, licence state, the device code
(seat problems are unanswerable without it), and the full conversation —
editable, with the promise printed on it that keys and passwords are never
included (true by construction, and tested). Three ways out, because
`mailto:` silently does nothing on a machine with no mail client: open the
email app (with the full text put on the clipboard FIRST, so a truncating
mail client cannot lose it), copy it all, or save it as a file that also
carries the redacted diagnostics report.

## Tests

52 in `tests/test_support.py` now: the retire-the-menus rules, Start over
forgetting everything including the gate, the assistant's grounding (whole
product shape, full answers for the question at hand, already-read marked),
the refuse-don't-guess instruction pinned by string, the no-key path, the
cautious temperature, failure-through-friendly, and the contact draft's
contents and its no-secrets guarantee.

---

# Round 8 — Email automation: every inbox, one register, and the order's own screen

A second firm described their whole operation in one sentence: everything —
inquiries, quotations, follow-ups, purchase orders — arrives by email, on
several addresses, and several people retype it all into one shared Excel
sheet. That is the workflow the engine has run since Round 3, asked for at
the scale of an office instead of a desk. `docs/EMAIL_AUTOMATION.md` is the
full design and the business case, with sources; this is what changed.

## The mailbox step takes a list now

**Was:** one account under `cfg["inquiry"]["account"]`, one read bookmark
beside it.

**Is:** `cfg["inquiry"]["accounts"]` — each entry with its own bookmark,
because two mailboxes sharing one last-UID would skip or re-import each
other's mail, and either failure is indistinguishable from a quiet week.
The old keys are still written, mirroring the first entry, so a config saved
by this version opens in the previous one; `accounts_of()` is the one reader
that understands both, and an existing customer's first check after updating
carries on from exactly where their last one stopped.

**The walk is one account at a time, never parallel.** The engine's own rule
— two fetches racing on one bookmark registers the same inquiry twice — is
"N fetches racing on one order book" the moment there are N accounts. One
dead mail server is skipped and named ("sales@… — the mail server didn't
answer" is a whole sentence; without the address it is half of one); one
locked register stops the walk, because the same lock would refuse every
account after it and none of their bookmarks have moved. A password being
refused three times sidelines that mailbox — the provider would throttle and
then lock it, and "Prism locked me out of my email" is the support call that
ends a deployment — while the healthy ones keep being read.

**The register says where each inquiry arrived.** One new column, `Mailbox`,
stamped when the row is born and never rewritten — a PO landing on a
different address later is not the inquiry moving. With sales@, info@ and
the owner's own address feeding one file, "who is this customer talking to"
is the first question the sheet gets asked.

**The centralised sheet was always one file; Setup now says so.** The
register lives in one folder, so the folder picker now carries the sentence
("choose a folder on your shared drive and everyone opens the same
register") and a one-click **Use the team folder** when the Prism workspace
is set up. One machine does the writing — the office PC that stays on;
everyone else reads. Several machines writing one register is deliberately
deferred, with its trigger, in `docs/DEFERRED.md`.

## The purchase order finally has its screen

`core/po.py` — read the PO, compare it to the quotation, flag every
difference — has been built and tested since Round 3, and no screen ever
called it. The runtime doc has named "the PO confirmation" as the missing
screen the whole time. Tab **5 · The order came** is that screen:

* The comparison is against the quotation **actually sent**, read back from
  the CSV written at send time — today's rate list could quote something the
  customer never saw. The reader mirrors `quoting.write_csv` and is checked
  against the file's own Total row to the paisa; a file that does not add up
  produces NO comparison rather than a wrong one.
* Accepting is a button, and it only writes the register — `Converted`, the
  PO number, the order value. The second of the two money stops, exactly
  where every doc has always promised it.
* The typed-in boxes are not a failure mode, they are the design: half of
  real POs are scans with no text in them, and the privacy switch means a PO
  — which is mail content — is never sent out to be read when *Keep
  everything on this computer* is on. Reading by machine is the convenience;
  the person holding the printed order is never blocked. (OCR: deferred,
  with a measured trigger, in `docs/DEFERRED.md`.)

## The shelf says "Email automation" now

Both prospect firms said "email", not "inquiries", when they described what
they wanted — so the shelf item, the screen and the setup say **Email
automation**. The rail key (`inquiry`), the licence feature (`inbox`), the
register format and every file on disk are unchanged: the SKU and the wiring
did not move, only the name on the shelf. The support screen's answers grew
three questions to match (several mailboxes, the shared register, what
happens when the PO arrives).

## Tests

27 new (`tests/test_email_automation.py`): per-mailbox bookmarks banked
against the right account, the dead-server skip and the locked-register
stop, learned senders chaining from one mailbox's check to the next, the
Mailbox stamp (and that it never rewrites), per-address password back-off,
the quotation round-trip to the paisa with the tampered-file refusal, the
₹4,500-on-ninety-paise comparison catch, the privacy switch keeping a PO's
text on the machine, and the review sheet refusing an empty accept. The
five-tab order test in `test_inquiry_ui.py` was updated deliberately: the
tab order is still the explanation of the feature, and the fifth tab is the
end the workflow was sold on.

---

# Round 7 — Help & support: the written answer first, then us

`friendly.py` speaks when Prism itself notices a problem. Nobody was there
for the larger half — the customer who is not looking at an error at all:
does one licence cover two computers, will the inbox add-on touch my real
mail, what do I type in the box. Nothing is broken, so no dialog ever
appears, and every one of those questions was a phone call.

## A new rail destination, and the shape of it

**Help & support** sits in the rail next to How to use Prism — they are not
the same thing: the guide is for somebody who does not yet know what Prism
does, this is for somebody who knew exactly what they wanted and did not get
it. It is a screen, not a dialog, like every other destination the rail
switches to, and it keeps its conversation for the life of the window — you
can follow an answer's button to Settings and come back to the thread.

Three tiers, in an order that is the whole design:

1. **The written answers** (`support_kb.py`) — 61 questions in 10 topics,
   the ones actually asked down a phone, phrased the way the customer says
   them. Same writing rules `friendly.py` is held to: plain English, then
   numbered steps that start with a verb, never a problem without a next
   action. Every button and menu an answer names was checked against this
   build — the redesign moved several (Login tabs sits behind More settings
   now; "Back to the plan" became "Back to the steps"; Export diagnostics
   lives on the sheet Settings' Change buttons open) and an instruction that
   names a control that is not there sends the customer hunting.
   A typed box searches them; the scoring deliberately returns NOTHING
   rather than a weak guess, because the empty result is what opens the
   route to a person.
2. **The assistant** and 3. **Contact the team** — placeholders, by
   decision, not omission. The plan is an assistant that talks the problem
   through, and a direct line that has us call the customer; both are their
   own change. The buttons are already in place so the screen's shape does
   not shift under people later, and each one, pressed today, answers
   honestly in the transcript — the contact one hands over the address that
   is read today. A placeholder may postpone the feature, never the person.

**The gate.** Tiers 2 and 3 stay shut until a written answer has actually
been tried — the pattern every government service site uses, because a
button marked contact-us gets pressed instead of the four-line answer that
was faster. But it opens on the FIRST honest miss: one answer marked "No,
still stuck", or one typed question with no match. Nobody is made to read
six irrelevant answers to earn a person, and the shut buttons carry the
sentence that says what opens them.

**The ways in.** friendly's catch-all — the one entry where we genuinely do
not know what went wrong — now carries an "Open Help & support" button, and
the guide's "when something goes wrong" topic points the same way.

## What it took elsewhere

* `devtools/extract_strings.py` had not learned the redesign's copy tables
  (`sidebar.MORE`, `settings_panel.SECTIONS`, `GuidePanel.CARDS`, …), so the
  new screens' labels were quietly untranslatable; registered them, and
  normalised catalogue paths to forward slashes so a regeneration on Windows
  stops rewriting every entry. Catalogue regenerated: 373 → 768 strings.
  Sixteen keys whose English no longer exists anywhere were pruned from the
  Hindi and Gujarati packs.
* Two transcript bugs found by measuring rather than looking: the scroll
  range ran hundreds of pixels past the last message (a word-wrapped label's
  *minimum* size is its height when wrapped at its widest word, and the
  layout sums those width-blind), and the scroll-to-newest landed one layout
  pass short every time. The column now sizes by height-for-width and rides
  the range while a message settles.
* 36 tests (`tests/test_support.py`): the jargon and verbs-first rules the
  answers are held to, every action key against the window's dispatcher,
  the search phrasings, both halves of the gate, and that the placeholders
  answer honestly and end somewhere real.

---

# Round 6 — the reels were slides, and it was arithmetic

One change, and it came from a measurement rather than an opinion.

A reel built by hand with a coding agent was compared against a reel Prism
generated. Same renderer, same CSS, same browser. The difference was not taste:

|                        | Built by hand | Prism |
| ---------------------- | ------------- | ----- |
| markup + motion per scene | **20,300 chars** | **278 chars** |
| elements per scene     | 25–77         | 3–5   |
| animations inside scenes | 150         | 0     |
| planning written first | ~50,000 chars | none  |

**278 characters is a headline and a subhead.** That is a slide. There is
nothing in it to move, so no instruction about motion could ever have fixed it
— which is exactly why the previous attempt, which added motion rules to the
prompt, made the output worse rather than better.

The cause was structural. The art director was asked for the whole reel in one
JSON object, and a model writing one JSON object budgets a few thousand
characters and divides them by seven.

## The design stage is a conversation now

**Was:** one prompt, one reply, the whole reel.

**Is:** turn one is the LOOK and a STORYBOARD — the palette, the type, the
shared stylesheet, and one row per scene giving it a distinct job, composition
and motion. Then one turn per scene, in the same tab, each with a whole reply
to spend on one scene. Each is laid out in the real browser and corrected
before the next is asked for.

Measured on the same four-scene script, rendered both ways:

```
OLD   4 scenes |   271 chars/scene |  7 elements/scene |  0 animations
NEW   4 scenes | 2,339 chars/scene | 34 elements/scene | 30 animations
```

**Why the correction loop is better too.** A layout fault used to come back as
"scene 3's headline is off the frame" against a reply the model had long since
moved past. Now it is simply "this one", while the scene is still the subject.

**Why more turns cost the customer nothing.** Prism drives the customer's own
browser on their own subscription. Ten prompts in a chat window instead of two
is slower, not more expensive — which is the opposite of the economics a
coding agent faces, and the reason this approach was available to us and not
to them. The design stage now takes minutes rather than seconds, and says
which scene it is on while it works.

## Per-scene CSS is confined to its scene

`scope_css()` in `core/reel_web.py`. A model naming things in reply four
cannot see what it called them in reply two — everybody writes `.title`,
everybody writes `@keyframes rise`. Left alone they collide and whichever
scene loses the cascade silently inherits another scene's type size and
another scene's motion.

Every selector is rewritten to that scene's layer and every `@keyframes`
renamed, with the `animation:` declarations that point at them following the
rename. Three details that took real care:

- **`.leaving` is the scene element itself**, not something inside it.
  Prefixed as a descendant, every hand-written cut would have silently
  stopped working.
- **A class may share a keyframes name.** `.rise` and `@keyframes rise` are
  both idiomatic; only the animation references are rewritten, never the
  class.
- **`url()` contents are not CSS.** A brace in a path or a data: URI used to
  be read as structure and cut the stylesheet in half.

It is worth more than the collisions it prevents: because a scene *cannot*
reach outside itself, the prompt never has to ask it to be careful. It is told
so, in as many words — a scene free to name things clearly writes better CSS
than one hedging against a collision it cannot see.

## A failed turn costs one scene, not the reel

More turns means more chances to fail. A reply that is prose rather than JSON
is asked again, more bluntly. A scene that still will not come back is
replaced by a plain one built from the script's own words — modest, legible by
construction, in the design's own colours. One dull scene ships; a hole does
not.

---

# Round 5 — a week of real runs, and what they broke

Nothing in this round came from planning. Every entry is something that went
wrong while the product was being used to make an actual reel for an actual
prospect, and several of them had been quietly wrong for a long time.

The theme, if there is one: **Prism was losing information at the seams.** Not
crashing — losing. The customer's own words on the way into a prompt, the
customer's CSS on the way out of a browser, the evidence on the way into an
error message. Every one of those failures reads as "the AI did a bad job".

## The customer's own words now reach the tool doing the work

The most expensive bug here, and the hardest to see.

Prism expands a request into a professional task brief, and the router writes
each stage prompt FROM that brief. The router is handed the raw request and
told it wins on scope — but the stage prompts it produces were only as good as
what it chose to carry across, and **the agents never saw the original at
all.**

A customer asked for a reel about *"Consiz, a mouse with a middle button that
summarises whatever you have selected and lets you ask questions about it"*.
The brief came back as *"showcase the mouse, demonstrate its features, explain
its benefits"*. The button, the selecting, the summarising, the asking — every
mechanical fact, gone. Claude then wrote a genuinely good script about a
generic productivity mouse, because a generic productivity mouse was all it
had ever been told about.

Nothing downstream can catch that. A summary that drops the one fact the whole
video is about still reads perfectly well, so every later stage compounds it
confidently — and the handoff chain means stage four works from stage three's
summary of stage two's summary.

The raw request now rides at the top of every stage prompt, verbatim, before
the attachments and before the previous stage's handoff. It is labelled as the
human speaking, and says outright that what follows is a summary, that
summaries lose things, and that specific facts above must survive even if the
brief below does not repeat them. Capped at 2500 characters and marked when
truncated — generous on purpose, because the Consiz mechanism sat in the last
third of that sentence.

*Suggested by the customer, who diagnosed it from the two briefs side by side.*

## The chat window was corrupting the design on its way out

Two bugs, one saved file, and the model was innocent of both.

A reel's art direction is a JSON document containing a full stylesheet.
Repeatedly it came back as **"No JSON found in the agent's reply"** while the
customer could see JSON sitting on the ChatGPT page. Unanswerable — until the
failed reply started being kept (below). One look at it settled both:

- **A soft-wrapped URL became a real newline inside a JSON string.** The chat
  window wrapped a very long Google Fonts `@import`, and the scrape turned that
  visual wrap into an actual line break inside the value. JSON forbids an
  unescaped control character in a string, so an entire design was thrown away
  over a line break that only ever existed on screen. `_escape_control_chars()`
  now escapes exactly those, tracking string state so ordinary
  pretty-printing between members is untouched. Run against the real saved
  failure, the design comes back whole — 6 scenes, both fonts, 3550 characters
  of CSS.

- **Markdown ate every asterisk, and that was our own instruction's fault.**
  Both prompts said "no fences". Outside a code block the reply renders as
  prose, prose is markdown, and markdown treats `*` as an emphasis marker — so
  `*{box-sizing:border-box}` arrived as ` {box-sizing:border-box}` and the
  whole CSS reset was silently dropped. The saved file contained **zero
  asterisks in 17KB**. Fences are now required, and the prompt says why so a
  model does not helpfully strip them again. The parser has always skipped
  fences — its own docstring says scrapes carry them — so forbidding them
  bought nothing and cost entire designs.

## Evidence is kept instead of discarded

The reason the above took three attempts to diagnose: the scraped text lived in
a local variable, the run moved on, and the error said only "No JSON found".

A design that will not parse is now written to
`~/.prism/logs/design-that-would-not-parse-<ts>.txt`, and the error names the
file. It answered a fortnight-old mystery on its first use.

The same failure of nerve appeared elsewhere: **a planning failure discarded
the customer's prompt entirely.** Planning is where runs fail most often — a
rate limit, a dead connection, an expired key — and it fails before anything is
written down, so their own words were the only casualty. Somebody who spent
five minutes describing a job had to remember it and type it again. Saved now,
error and all.

## A reel with no pictures is designed on purpose

Image generation fails for ordinary reasons — a quota, a content refusal, a
render that never finished. On one run ChatGPT thought for 185 seconds and
produced nothing.

Prism noticed. The design stage did not, and **silence is not neutral**: an
empty asset list produced an empty listing, so the prompt simply did not
mention pictures, and a model asked for a premium product reel assumed the
usual ones existed and wrote `src='asset:art1'`.

The renderer already strips unresolved assets, so nothing showed a broken-image
glyph. But a layout DESIGNED around pictures that never arrive is worse than
that: the holes are stripped and what remains is a composition with gaps in it,
which reads as broken rather than as spare.

`assets.manifest({})` now says there are no images, that this is not an
oversight, that nothing is coming later, and — the part that matters — what to
do instead: carry it on typography, hierarchy, negative space, rules, colour
fields and CSS shapes. A prohibition alone produces a timid design, so it also
says outright that a spare type-led reel is a legitimate and often superior
one.

## Canva: make the picture first, then make it editable

Asking for an editable Canva design and a good image in the same prompt made
the customer choose between them. Canva COMPOSES a template — stock layouts,
its own type — where DALL·E renders the scene described. For "da Vinci sipping
Wagh Bakri chai" the render is the whole job.

Now the two asks stop competing. The first prompt asks only for the best
picture the tool can draw; once it exists, a second prompt goes into the same
conversation — `@canva can you make this design editable` — pointing at the
artwork directly above it. Best picture *and* an editable file, which was not
previously on offer. *The customer's idea.*

Four failure modes have defined answers rather than surprises: nothing
generated → skip it entirely; Canva not connected → the fixed reply is dropped
rather than appended; Canva silent → keep the image; wrong kind of stage →
never asked.

That last one shipped wrong and was caught on the first real run: `artwork` and
`design` were included, and the Studio pipeline's design stage emits JSON for
Prism's own renderer — so the follow-up asked Canva to "import the image above"
when the message above was a CSS blob. The editable stages are now exactly the
registry's Canva-configured ones, with a test asserting the two lists match,
because they drifted apart once and **that drift was the bug**.

## Closing the browser no longer kills Prism

Reported as *"python stopped working and prism ended"*, with a real macOS crash
report behind it: SIGABRT, `QThread::~QThread`, `_Py_Finalize`.

Qt calls `qFatal()` when a thread object is destroyed while still running, and
PySide destroys every QThread during interpreter shutdown. So closing Prism
mid-run did not leak quietly — it killed the process. The app's own log signed
off with an ordinary "Prism closed" and no traceback, which is why it looked
like a mystery: the crash happens after the last thing anyone logs.

Every live worker is now stopped and joined on close. Stop-all before wait-all,
so three stuck workers cost ten seconds between them rather than thirty.
Inquiry Automation had the same hole and more workers than anywhere else.

Separately: **a closed browser window was diagnosed as a Chrome version
problem.** Every frame of a Selenium stack trace says
`undetected_chromedriver`, which matched the version-mismatch rule, so a closed
tab sent the customer off to update a browser that was working perfectly. A
confident wrong answer is worse than the generic one it replaced, because they
act on it. And the run kept going against the dead session — every later stage
opening it, timing out, and reporting the same error. It stops on the first one
now and says so once.

## When a tool runs out, another one finishes the job

A run is twenty to forty minutes and the heaviest stage is usually the last, so
the free tier that runs out runs out at the END — leaving a pipeline that did
nine tenths of the work and produced nothing usable.

Prism now reads the page for "you've reached your limit", "out of free
messages", "upgrade to continue" and the rest, kept deliberately apart from the
signed-out check because the two need opposite responses: an exhausted quota is
something Prism can route around by itself, whereas signing in is something
only the customer can do.

The replacement comes from the same category, so it can do the same job — a
failed image stage handed to a research tool produces an essay about pictures.
Tools the customer already configured go first, because they are probably
signed in to those. Capped at two attempts; each one is minutes of browser
time.

**Limitation, stated rather than left to be discovered:** the retry runs after
the pipeline, not inside it. A stage that failed in the middle has already
handed nothing to the stages behind it, and those are not re-run. The last
stage is fully recovered. Doing better means restructuring a 500-line loop
whose index-keyed maps all shift if the stage list changes underneath it.

## The test suite was writing into the customer's own data

Twice, found twice, and the second one was found by a customer asking a
completely different question.

- **`~/.prism/config.json`** — a test called `_checked()`, which calls
  `_remember()`, which calls `config.save()`. It wrote a bare fixture over a
  real config: Groq key, profile, agent choices, Chrome pin, gone. The only
  symptom was Prism asking to be set up again on every launch, which reads like
  a Prism bug rather than a test one.
- **`~/.prism/runs/`** — tests proving "a broken run is still recorded" were
  recording into the real History. **56 of 128 files** were fake "Chrome would
  not launch" failures. Worse than clutter: they carried no query, so they
  looked exactly like real runs whose prompt had been lost — the bug
  manufactured evidence for a bug that did not exist.

Both now refuse at module level rather than relying on the next person to
remember. The runs one needed two doors shut, not one: `config.RUNS_DIR` is
only the CLI's default, and the window passes its own folder. Verified by
counting the directory before and after the suite.

## Documentation

- **`docs/FUTURE_INDUSTRY_TARGETS.md`** — where Prism goes after springs and
  plastics. PCB fabricators (Fine Circuits / Fineline, Manjusar GIDC — the
  first real prospect, with what was proven against their actual 4-layer
  board), and EMS/assembly houses, which is the larger prize because they
  receive a Gerber AND a BOM AND a pick-and-place file. Includes the rule that
  matters: **the Gerber files never leave the machine** — Prism measures
  locally and only the measurements, the template and the company details go to
  the AI tools to be formatted. Their customers are aerospace and medical firms
  whose board geometry arrives under NDA.
- **`README.md`** — rewritten. It still said "v0" and described a July build,
  and one line in it was not merely stale but wrong: it claimed a sibling
  `../prism_terminal` checkout takes priority over the submodule. It does not,
  and never did. The same sentence had already been removed from
  `core_bridge.py`; this copy survived, and it cost an afternoon of editing a
  file that is never loaded — twice.

## Also in this round

The licence lease and secret store, macOS codesigning, and the UI pass that
lifted content onto cards and folded the seven CONFIGURE rows behind a
disclosure, all by the second developer on the project.

### Still open
The send path and the PO → BOQ hand-off remain written, unit-tested, and never
run against a real mailbox. `plans.py` feature names are still not in the
translation catalogue.

---

# Round 4 — the screens, and the rest of the loop

Round 3 built the engine and said plainly that the screens did not exist. They
do now, and the workflow runs end to end: read the mail, register it, quote it,
read the answer, chase the silence, argue with the no.

## The screen

Four tabs, in the order the work happens — **What arrived → Inquiries → What
they said back → Waiting on a reply.** The tab order is the explanation of the
feature, so it has a test of its own.

- **Colour.** Categories, statuses and reply intents are tinted so a
  hundred-row register reads at arm's length. The word is always there as well
  as the colour: roughly one man in twelve cannot tell the red from the green,
  and a register printed on the office laser comes out grey. Tests assert every
  category and every status has a colour, because an uncoloured cell in a
  coloured column reads as a rendering bug.
- **Checks on a timer.** Off by default; interval set in Setup. It only ever
  READS. A tick is skipped while a check is already running — two IMAP fetches
  racing on one bookmark is how the same inquiry gets registered twice — and
  skipped while a quotation is open on top. Failures on a tick go to the status
  line, not a dialog: a modal appearing over somebody's work every ten minutes
  because the mail server had a bad afternoon is how the feature gets switched
  off for good. For the same reason a tick never moves the tab.
- **Time as well as date** in the register. Two inquiries from one customer on
  the same morning were indistinguishable before. Converted to local time — a
  mail header carries the *sender's* offset, so a 09:00 enquiry from Germany
  was filing itself at 09:00 in a Gujarat register.
- **Editing a row by hand.** They can always edit the CSV in Excel, but a
  register that can only be corrected by closing the app is one they stop
  correcting. The bookkeeping fields are deliberately not editable — letting
  the inquiry number be retyped is how two rows end up sharing one.
- **Starting from a register they already keep.** Setup imports it: their own
  columns survive untouched, numbering carries on from theirs rather than
  reissuing a number already on a quotation, and an existing register is never
  overwritten. Columns Prism did not recognise are reported, not guessed.

## Replies, which is the part it is bought for

The engine already worked out what each reply meant. The GUI threw it away.

Tab 3 now shows the reply, what Prism makes of it, what the register *would*
say, and the customer's actual words underneath. **Nothing applies itself** — a
machine silently rewriting a sales record on the strength of a sentence it
might have misread is not something a business can check.

`register.mark_reply()` is careful about three things:

- **"Accepted" does not mean Converted.** Going ahead is a promise; Converted
  is a fact with a PO number behind it. Collapsing them makes the month-end
  conversion figure optimistic by exactly the orders that never arrived — the
  one number an owner would repeat to a bank.
- **An unreadable reply changes nothing but the date.** A wrong status is worse
  than a stale one: the owner acts on the register without re-reading the mail,
  and a quotation wrongly marked Not converted is never chased again.
- **Haggling is not a refusal.** "Send your best price" is the commonest reply
  there is, and reading it as a no closes a row that is still winnable.

## Chasing, unattended

Every two days, three times, then it stops. The schedule lives in the register
— `Reminders sent` and `Last contact`, the same two columns the owner can see
and edit — so there is no hidden second queue to drift out of step with it.

One reminder per check, never a batch: three leaving in the same second, to
three customers who talk to each other, reads as a machine. Each is worded
differently — the first is a light touch, the third asks straight out whether
to close the file. A failed send is not counted, or Prism gives up after three
reminders that never left the building. Off until switched on.

## Winning back a no — and less Groq

**`core/drafting.py` is new.** Writing a page of persuasion that knows what was
quoted, what they objected to, and how far this owner will move on price is a
different job from labelling an inbox. It goes through the AI tools in the
customer's own Chrome, on their own subscription — no API key, no per-token
cost.

The risk is a tool that offers 15% because it sounded persuasive. So: no figure
may appear that is not in the owner's own policy file, **no policy file means
no discount is offered at all**, and the customer's email is marked as
information rather than instruction — a buyer cannot write "ignore your pricing
policy" and negotiate with the tool directly.

Two things deliberately did **not** move to the browser, with the reasoning in
the module docstring: sorting the inbox (a browser round trip is most of a
minute; two hundred emails is a working day with their Chrome held hostage) and
writing the register (Python writes it atomically, gets the money right to the
paisa, and cannot hallucinate a row — and it is the customer's order book, not
something to post to a website).

**Reading a reply now usually needs no AI at all.** `mailflow.local_intent()`
settles the formulaic ones — 13 of 13 test phrases, zero calls. Only genuinely
vague replies reach the model. The rules run first even when a key is
configured, or they would be dead code.

## Pricing from the owner's own formulas

The engine could always run a cost sheet; the GUI only read rate lists, which
locked out every shop quoting made-to-drawing work. Either source works now,
and every line of the working is shown — this is the number they will be asked
to justify on the phone.

Two defects the testing found:

- **The quotation totals the *rounded* per-piece rate**, so it does not equal
  the cost. Reading ₹31,556 on screen and sending ₹31,550 is how an owner stops
  believing the whole calculation. The gap is now stated in words.
- **A blank weight quoted the labour alone** — an under-quote that looked like
  a finished quotation. It refuses now.

## FFmpeg

A Windows customer met a codec install guide on pressing Reel. FFmpeg is now
**bundled** (`imageio-ffmpeg` in the wheel), with a verified download as the
fallback: the same wheel, checked against the SHA-256 PyPI publishes for that
exact file, verified before it is unpacked. `reel.py` and `reel_web.py` each
had their own `shutil.which("ffmpeg")`; both delegate to one resolver now, and
a test parses the AST to keep it that way.

The self-test line that read "optional — needs FFmpeg on the machine" *was* the
belief that caused the bug. It names which FFmpeg is in use now.

## The licence server

- **`DEFAULT_SERVER` now ships the Render address.** `api.alphakore.in` has no
  DNS record, and a build pointed at a name that does not resolve cannot
  activate anybody. This is a temporary pin with a real cost — see
  **SHIPPING.md §3.2**, which is now the only place that says how to undo it,
  and which `tests/test_licensing_endpoint.py` fails if anyone deletes.
- **`ACTIVATE_TIMEOUT` 30s → 75s.** A cold `/health` on that host measured
  **42.6 seconds**; activation was giving up 13 seconds early against a server
  that was up and healthy. Activation is the one call a new customer cannot go
  around — no cached token, no way into the app.
- Deliberately **no retry** on activation, unlike authorize. A timeout there is
  ambiguous: the request may have counted a seat before the socket gave up, and
  burning the second seat of a two-seat licence is worse than the failure the
  retry would fix.

### Not done
`plans.py` feature names and blurbs are still not in the translation catalogue
— unchanged from Round 3, still a pre-existing gap.

The send path and the PO → BOQ hand-off are written and unit-tested but have
never run against a real mailbox. Reading is the well-covered half.

---

# Round 3 — Inbox to Order

Asked for in person by a spring manufacturer at GIDC: *let Prism read my mail,
sort it, keep my inquiries in one file, quote from my own rate list, track
whether the customer said yes or no, and when the PO comes, make the production
sheet.* They also asked for SOPs to be sent to customers automatically.

The engine for all of it is built and tested. **The screens are not** — see the
end of this section.

Two documents cover it: [`docs/EMAIL_WORKFLOW.md`](docs/EMAIL_WORKFLOW.md) is
what happens, in plain language, with the flowcharts;
[`docs/EMAIL_WORKFLOW_RUNTIME.md`](docs/EMAIL_WORKFLOW_RUNTIME.md) is how —
which AI does which job, his day hour by hour, and every point a person is
needed.

### Reading the inbox — `core/inbox.py`
The other half of `mailer.py`, which could already send. IMAP over the standard
library, no new dependency. Works with any company-domain mailbox; `discover()`
tries `imap.`, `mail.` and the bare domain so nobody has to know what their
server is called.

**Two rules it will not break.** The folder is opened read-only and every fetch
uses `BODY.PEEK`, so Prism never marks anything read, moved or deleted — the
owner still uses Outlook on the same account, and a tool that silently cleared
unread flags would make them miss a real order. And nothing in the file talks
to an AI; fetching is plumbing.

Handles the things that bite in year two: a server that renumbers the mailbox
(UIDVALIDITY), the `UID n:*` search that always returns the newest message even
when it is older than asked for, attachment filenames containing `../`, and
four customers all attaching `drawing.pdf`.

### Sorting it — `core/triage.py`
Local rules first, AI only for what is left. A newsletter is caught by its own
`List-Unsubscribe` header, an out-of-office by `Auto-Submitted`, a known
customer or supplier by a list the company already has. Only genuinely new
correspondents are ever put in a prompt, and only a 1,200-character snippet of
them.

That ordering is what makes "most of your mail never leaves this computer" a
testable claim rather than a hopeful one — and it is tested: a suite check
fails the build if locally-sorted mail ever reaches a prompt. `local_only`
turns off the AI pass entirely and the feature still works.

Corrections are learned per exact address, so a sender is never asked about
twice. They outrank every rule except machine post — one mistaken tap must not
put a robot's auto-reply in the register for ever.

### The register — `core/register.py`
One growing CSV, one row per inquiry, opens in Excel. Financial-year numbering
(`INQ/25-26/0087`, April to March, like every quotation book in the country).
Written atomically, because a crash mid-write must not truncate somebody's
order book. Columns they add by hand survive. When the file is open in Excel it
says *"close the inquiry register in Excel"* rather than failing silently.

Replies find their own row by Message-Id, falling back to an open inquiry from
the same address — which catches the customer who replies from their phone and
breaks the thread. A closed row never swallows new business.

Also here: `awaiting_followup()`, the most valuable list in the file, and the
month-end figures. Conversion is counted against quotations sent, not inquiries
received — an inquiry nobody quoted was never a chance, and counting it makes
the number flattering and useless.

### Pricing — `core/quoting.py`
Reads their rate list (CSV, or Excel via openpyxl) and finds the header row
rather than assuming row 1, because real price lists open with a letterhead.
Understands quantity slabs from `Rate @ 1000` columns. Matches free text to a
row by rare-word weighting with the digits weighted up again, because in this
trade the numbers are the specification — and returns *candidates with reasons*,
never a decision.

For made-to-drawing work there is no rate to look up, so there is a cost sheet:
their own lines, their own rates, charged per kg, per piece, per lot or as a
percentage. Plus wire and coil weight from a drawing's dimensions — geometry,
checkable against a scale.

**No AI touches a number in this file, and a test enforces it.** Every figure
is Decimal, rounded half-up the way Indian accounting does — Python's default
turns ₹0.125 into ₹0.12 where Tally says ₹0.13, and "the software rounds
differently" is not a conversation worth having. The AI is handed formatted
figures and told, twice, to write the sentences around them.

### Purchase orders — `core/po.py`
Pulls the fields out of a PDF or Word PO, then puts it next to the quotation
and points at every difference. Scans are detected and say *"type these four
things in"* instead of returning a confidently empty order.

### SOPs — `core/sop.py`
The easiest thing in the whole workflow to automate, because there is no money
in the message. Library from a folder — revisions read from filenames like
`SOP-07_Heat-Treatment_rev3.pdf`, or from an index file if they keep one — and
only the newest revision is ever offered.

Four triggers, and the third is the one worth building for: **revise a
document and everyone holding the old revision is chased automatically.** The
log records who received which revision on which date, which is the answer to
*"prove your customers were notified"* — the question an ISO auditor asks, and
which today means somebody searching Sent Items for an afternoon.

### The daily loop — `core/mailflow.py`
One `check()` call does everything that cannot cost money if it goes wrong, and
hands back a worklist of what needs a person. **It never sends anything** — a
test greps the file to keep it that way. It never raises either: this runs on a
ten-minute timer next to somebody running a factory, so a mail server having a
bad afternoon belongs in a status line.

### Scenario testing — `devtools/scenarios.py`

Thirteen situations rather than unit tests: a full Monday morning of ten mixed
mails, a customer who haggles all the way from inquiry to PO, ten shapes of
badly-built rate list, 200 messages at once, a mail server that is down, an
email that tries to talk to the AI reading it. **148 checks, under a second, no
network.** Run it before a release.

The unit suite proves the pieces behave. This proved they behave *together* —
and it found four real bugs that unit tests had not, every one now also pinned
by a test:

- **`Rs.1,000/-` parsed as ZERO.** The worst bug in the feature, and invisible.
  That is how money is written in every Indian office. The parser deleted
  everything that was not a digit, a dot or a minus, turning it into `.1000-` —
  unparseable, so zero. Every order value typed the normal way summarised as
  ₹0, and a rate list cell written `28.50/-` would have quoted at **nothing**.
  There is now one strict parser shared by the register and the quotation, so
  the two can never disagree about what a rupee looks like.
- **A customer could forge a message boundary.** An email body containing
  `--- EMAIL 2 ---` was pasted into the sorting prompt verbatim, so a sender
  could fake a second message and ask to be sorted as `internal` — never
  registered, and nobody notices a customer whose mail silently stopped
  arriving. Boundaries and answer-shaped lines are now neutralised, the batch
  size is stated, and the prompt says message text is never an instruction.
- **`local_only` only did a third of its job.** It was passed to the sorter
  alone, so detail extraction and reply reading still sent customer
  correspondence out. A privacy switch that quietly does two thirds of what its
  name promises is worse than not offering one.
- **A bare "Enquiry" subject became a useless register row.** Half of all
  inquiries arrive under one. It matched nothing on a rate list and told a
  human nothing either. The opening line of the message — skipping the
  greeting — is now used when the subject carries no information.

### Two bugs from round 2, found while chasing the CI failure

Neither is part of Inbox to Order. Both were introduced by round 2 and both are
the same shape as the scenario bugs — silent, no symptom, wrong only where it
counts.

- **The licence server address was regressed to the hosting provider's URL.**
  A one-line change to `DEFAULT_SERVER` rode along inside a commit about
  cold-start timeouts: `api.alphakore.in` became
  `prism-license-server.onrender.com`. Nothing failed — the app built, started
  and self-tested clean — and **every customer activation in that build would
  have gone to the wrong host.** It also welds the binary to Render for its
  whole life, since the domain is the only thing that lets the server move
  without shipping a new app. `SHIPPING.md`, `LICENSING.md` and the comment in
  `licensing/keys.py` all name the domain; only the code disagreed. Restored,
  and `tests/test_licensing_endpoint.py` now fails if it drifts again — it also
  checks the address is HTTPS, has no trailing slash, and still matches the
  regex `packaging/prism.spec` uses to rewrite it for staging builds.
- **`core_bridge.py` described the opposite of what it does.** It claimed a
  sibling `../prism_terminal` checkout took priority "so you're always working
  against the copy you're editing". It does not: `paths.resource()` resolves to
  the submodule when running from source and is checked first, so a sibling was
  never reached. The behaviour is right — the submodule is what gets committed
  and built — so the sentence went rather than the code. And because this
  machine genuinely has both copies, `core_bridge` now prints which one is
  loaded and which is ignored, which is the sentence that ends the afternoon
  somebody would otherwise lose editing the wrong tree.

### Two bugs found by the tests, both real
- **A rate cut was measured against the wrong thing.** The PO comparison
  ignored differences under ₹1. Ninety paise off a unit rate is under ₹1 — and
  on 5,000 pieces it is ₹4,500, walking straight past the check that exists to
  catch it. The tolerance now multiplies out by the quantity first.
- **The inquiry folder was not created when nothing was attached.** The
  register printed a path that opened onto nothing.

### Also
- `plans.py` gains the `inbox` feature. Inclusive in **Works** — it is the
  piece they use every day, and it is what makes them open Prism at all.
  An add-on for **Studio**.
- **The BOQ paywall copy was lying.** It promised "a priced BOQ"; the engine
  deliberately leaves Rate and Amount blank. Now it says the customer's rates
  go in the blank columns — Prism counts, you price. Same correction already
  made in the business documents.
- `openpyxl` added to `requirements.txt`. Optional at runtime, bundled in every
  build.

### Not done — the screens
The engine runs the whole loop. The window he clicks in does not exist yet:
mail-account setup, the worklist, the quotation review with its Hold button,
and the PO confirmation. That is the next piece of work, and it is what he will
judge the product by.

Also still English-only: `plans.py` feature names and blurbs are not in the
translation catalogue — the new `inbox` feature is in exactly the same state as
every existing one, so this is a pre-existing gap rather than a new one.

---

# Round 2 — roles, languages, cloud attach, plain-English errors

---

## Bugs fixed

### Apollo was being sent a paragraph and refusing it
A live run failed with `Value too long: 'Context from the previous pipeline
stage (RESEA…' exceeds 200 characters`. Apollo is a filter screen, not a chat
box, and its API rejects any single value over 200 characters — the pipeline
was handing it the whole inter-stage brief.

Two halves. The stage before Apollo is now told to emit a fixed filter block
(`TITLES / INDUSTRIES / LOCATIONS / HEADCOUNT / KEYWORDS`) instead of prose,
and Apollo is driven by **its own search URL** rather than by typing into the
page — Apollo mirrors its whole search state into the address bar, so this
sets the same filters without touching the left rail's class names. Values are
hard-capped in code, not just asked for in the prompt.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_apollo.py`

### Canva took over every image
With the Canva app connected to ChatGPT, every visual and presentation turn
came back as a flat template — including jobs that needed a rendered
illustration. Canva composes a stock layout; DALL·E renders the scene actually
described.

Canva is now **opt-in**: it engages only when the user's own words ask for
something editable (`canva`, `editable`, `template`, `edit later`…). And when
they have not asked, the prompt says so explicitly — silence is not enough,
because a connected Canva app gets reached for unless told otherwise.

*Files:* `core/agents.py`, `core/automation.py`, `tests/test_canva.py`

### Add file stopped working
Caused by the i18n work below. To translate a window caption, `QFileDialog`'s
**static** methods were wrapped — but those are the entry point to a *native
OS panel*, not a Qt widget, and every attachment in the app goes through them.
macOS does not even draw a title on an open panel, so the patch bought nothing
and cost the most load-bearing path in the UI.

Statics are stock again; captions are translated at the call sites instead. A
test now fails the build if they are ever wrapped again, and a second test
greps every call site for a bare literal caption.

*Files:* `i18n.py`, `main_window.py`, `widgets/*.py`, `tests/test_i18n.py`

### LAZYCOOK was being talked down to
It runs its own Generate → Analyze → Optimize → Validate loop and scrapes the
web itself — which is the entire reason to route to it over Perplexity. Prism's
house style (`Your ONLY task is:`, a fixed section list, `STRICT PIPELINE
RULES: 1. Perform ONLY the task above — nothing more`) reads to it as "stop
after the first pass", so it answered in one shot and came back weaker than
the tool it was chosen over.

Agents can now declare `prompt_style="natural"` and get asked the way a person
asks. The handoff is still requested — the pipeline cannot work without it —
but as a request at the end rather than as rule 3 of 4. The router also gets a
carve-out rule, **only when such a tool is actually in the plan**.

*Files:* `core/agents.py`, `core/automation.py`, `core/router.py`

---

## New features

### Multilingual — Hindi and Gujarati, 100%
Prism translates **by value**, not by call site: `t()` takes the English string
and returns the local one, and `install()` patches the Qt methods that put text
on screen so no widget code changed.

The safety property: a string is only swapped if it is in
`lang/_catalogue.json`. The same `setText()` also draws customer names, file
paths and whole paragraphs written by Claude — none of those are in the
catalogue, so none can be touched. Run `devtools/extract_strings.py` after
adding UI copy.

Also handles: script-appropriate font fallbacks (Barlow has no Devanagari),
right-to-left layout, and a **separate** setting for what language the AI
tools write back in — plenty of people want the app in Gujarati and the client
deliverable in English.

*Files:* `i18n.py`, `lang/`, `devtools/extract_strings.py`, `core/lang.py`

### Roles, per-member folders and a manager view
A company activates with one **company key**; each person then pastes a
**designation key** (`PRSD1.…`) that we mint. The role is Ed25519-signed, so it
cannot be forged by editing a settings file — tests cover self-promotion,
another company's key, and replay as a licence token.

Eight roles (Owner, Manager, Sales, Marketing, Operations, Engineering,
Accounts, HR), each with its own workspace folder, default tools and **accent
colour** — the hue rotates while every swatch keeps its exact lightness, so
contrast is identical in all nine (measured drift: 0.000000).

`workspace.readable_members()` is the single access rule: a working role sees
one folder, an admin sees all. Every screen goes through it.

> Enforced by Prism, not by the OS. On a shared drive a member can open Finder
> and read another folder. The signed role is the part that is solid.

*Files:* `roles.py`, `identity.py`, `workspace.py`, `plans.py`,
`licensing/designation.py`, `theme.py`

### Cloud file attach — no OAuth
Add file now lists every cloud folder mounted on the machine — Google Drive
(named by account), Shared drives, OneDrive, Dropbox, iCloud — and opens the
chooser inside it.

Google Drive for Desktop mounts Drive as an ordinary folder, so there is no
token, no consent screen, and nothing that expires. The OAuth path in
`integrations/gdrive.py` still exists for anyone without Drive for Desktop,
but it is no longer the way in.

*Files:* `cloud.py`, `integrations/`, `dialogs/drive_dialog.py`

### Plain-English errors
Every failure goes through one translator and comes out as **what happened**,
**what to do** as numbered steps, and where possible a button that does it.

`session not created: This version of ChromeDriver only supports Chrome 131`
becomes *"Prism couldn't open Chrome"* with three steps and a button to the
Chrome setting.

Tests fail the build if "webdriver", "selector", "traceback", "HTTP" or
"OAuth" reaches the screen, or if any message lacks a next action — a message
without one is a phone call.

*Files:* `friendly.py`, `dialogs/problem_dialog.py`

### A guide, and a welcome
"How to use Prism" is second in the sidebar: 13 topics in plain language with
copyable examples. Locked add-ons appear greyed with what they do — it is the
only place a customer discovers what else we sell. First-timers get a welcome
offering the tour before Setup.

*Files:* `dialogs/guide_dialog.py`, `main_window.py`

### Attachments
Folders now show as one row with their files indented, so a whole "Add folder"
can be removed in one go. Plus **Detach all**, a duplicate guard, and a status
message for every outcome — so a button that appears to do nothing is
impossible.

*Files:* `widgets/files_panel.py`, `main_window.py`

---

## Reliability

Audited the whole path a daily user walks. See `KNOWN_ISSUES.md` for the
plain-language version sorted into *fixed / code / needs money / nobody can
fix*.

| | |
|---|---|
| **Groq retires a model** | `MODEL_FALLBACKS` is a list. A dead model falls through, the working one is saved, the customer sees nothing. This one would have taken every install down on the same day. |
| **Rate limits** | Waits the `retry-after`, retries once, then says what to do. |
| **Cold-start refusals** | Authorize timeout 15s → **45s** plus one retry — transport failures only, never on a real answer, so a metered run cannot be double-counted. |
| **No way to debug** | Rolling log in `~/.prism/logs` + **Export diagnostics**. Credentials and email addresses are stripped, and that is tested. |
| **Sleeping mid-run** | Wake lock held for the run, released even if the window closes mid-run. |
| **Silent truncation** | Long attachments show "(first part only)". |
| **Workspace offline** | Banner saying today's work will not reach the manager. |

*Files:* `diagnostics.py`, `awake.py`, `core/router.py`, `licensing/client.py`

---

## Things deliberately NOT done

- **Licence server hosting.** The 45s timeout absorbs most cold starts, but a
  host that sleeps needs a paid plan. Free interim: point an uptime monitor at
  `/health` every 10 minutes.
- **Publishing the Google OAuth consent screen.** Only matters if we ever use
  the API route instead of Drive for Desktop. While it is in Testing, refresh
  tokens expire every 7 days.
- **The guide's own text is English only.** The UI is 373/373 in Hindi and
  Gujarati; the 13 guide topics are not in the catalogue yet.
- **Rate cards.** The BOQ engine leaves Rate/Amount blank on purpose. Letting
  a customer attach their own price list is the single feature that would open
  the dealer and manufacturer markets — see `docs/BUSINESS_NOTES.docx`.

---

## If something here breaks

1. `Settings → Export diagnostics` — one file, credentials stripped.
2. `~/.prism/logs/prism.log` — the rolling log.
3. `python3 -m unittest discover -s tests` — 263 tests.
4. `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python3 main.py` — proves a
   build is whole.
