# Prism default work (browser)

Built 27 Nov 2026, on branch `feature/prism-default-work-browser`. Not merged.

**Prism default work** = the task you type on Home (research → thinking →
writing → …) and its follow-ups.

## What runs where

| Step | Runs on | Tools you can pick (first = default) |
|---|---|---|
| Planner | Prism's server (credits) | no choice |
| Read the files | your browser | ChatGPT, Claude |
| Look things up | your browser | ChatGPT, Grok, Claude |
| Find the people | your browser | ChatGPT, Apollo |
| Think it through | your browser | Claude, ChatGPT |
| Write it up | your browser | ChatGPT, Claude, Kimi 2.6 |
| Sum it up | your browser | same as Think it through |
| Build the tool | your browser | Claude, v0.dev, emergent.sh, Kimi 2.6 |
| Build the slides | your browser | Claude, Gamma.app, Canva |
| Record the voice | your browser | ElevenLabs, Sarvam |
| Make the images | Prism's server (unchanged) | |
| Make the video, and its script and design | Prism's server (unchanged) | |
| Every add-on | Prism's server (unchanged) | |

- "Find the people" and "Record the voice" stay empty until you pick a tool.
- A saved pick that is no longer offered (Jasper, Perplexity, …) becomes the
  default. Your settings file is not rewritten until you press Save.
- All four modules (complete, sales, engineering, studio) share this code.

## Where it is in the app

- First launch: a setup walk — pick the tools, then **Open login tabs**.
- Settings → AI tools: the pickers and **Open login tabs**.
- Settings → Connections: the Chrome options.
- Plan and run screens: browser steps show the site's name; server steps show
  "Prism AI".

You create the accounts yourself on each site. Prism only opens the pages.

## Off switch

`PRISM_DEFAULT_WORK=server` puts every step back on Prism's server, with the
old screens. No new build needed to test the difference.

## Test it by hand

Needs Google Chrome and a working licence for the flavour (see
`RUN_AND_TEST_THE_MODULES.md`; the dev key issue still applies).

1. `devtools/run_flavour.sh sales` (with the exports from the run guide).
2. Finish the setup walk. Sign in on every tab, then close that Chrome window.
3. Home: `search for the latest GTU compiler design units and make a document`.
   Expect Chrome to open and work ChatGPT. Settings → Usage should show only
   small planner calls (Claude Haiku), no Sonar or Sonnet.
4. Ask a follow-up in the box under the answer. It should continue the same chat.
5. `draw a red crane poster`: no Chrome; the picture uses credits.
6. Try one step on each tool you will offer (table above).
7. Run one add-on (for example Email "Write with AI"): no Chrome.

For each tool note: did it type the prompt, did the answer come back, was the
file saved.

## Not tested

- **No real website has been run with this code.** The automated tests stop at
  "the step asked for the browser". The site-reading code is older than the move
  to the server, so some sites may have changed.
- **Sarvam is new.** It reuses the ElevenLabs steps on
  `dashboard.sarvam.ai/text-to-speech`; the page needs a sign-in, so its
  buttons were never seen.
- Packaged builds (installer, macOS, Windows) with this change.

## Known limits

- Perplexity is left out: a note in the code dated 8 Nov says its page crashed
  Prism's browser on Chrome 157.
- A task saved before this change continues on the server when you follow up.
- The new screen sentences are not translated to Hindi or Gujarati yet.
- Voice inside an add-on (Reel's voice-over tick box) is still unavailable, as
  before: the server has no voice.

## Main files

- Engine: `core/default_work.py` (the rules), `core/automation.py`,
  `core/agents.py`, `core/router.py`.
- App: `ai_server.py`, `main_window.py`, `workers.py`, `widgets/` (settings,
  setup walk, plan, run screen, sign-in tabs).
- Tests: `tests/test_default_work.py`.
