"""Turning what went wrong into what to do about it.

The person using Prism runs a business. They have not used an AI tool before,
they did not choose Selenium, and "HTTP 429" is not a sentence. Every message
they can possibly see goes through here first and comes out as three things:

    title    what happened, in five words
    what     one or two sentences of plain English, no jargon
    steps    the numbered things to try, most likely fix first

The rule this module exists to enforce: **never show someone a problem without
showing them the next action.** A message with no action is a phone call.

How it works
────────────
A list of patterns, most specific first. Each knows one real failure — the
ones in KNOWN_ISSUES.md, because those are the ones that actually happen — and
carries the words for it. Anything unmatched still gets a useful answer: the
generic entry ends with "send us the diagnostics file", which is the honest
next step when we genuinely do not know.

Write the steps as instructions to a person, not a description of a system.
"Open Settings → Chrome and clear the version box" beats "the pinned Chrome
version is inconsistent with the detected one".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Problem:
    title: str
    what: str
    steps: tuple[str, ...] = ()
    # True when the honest next step is to contact support, which is the only
    # case where the dialog offers to save the diagnostics file.
    ask_support: bool = False
    # Something Prism can do for them, named so the dialog can offer a button:
    # "settings:chrome", "settings:key", "login", "guide", "support".
    action: str = ""
    action_label: str = ""


# Each entry is (regex over the error text, Problem). First match wins, so the
# specific ones come before the general ones.
_RULES: list[tuple[re.Pattern, Problem]] = []


def _rule(pattern: str, problem: Problem) -> None:
    _RULES.append((re.compile(pattern, re.I | re.S), problem))


# ── the internet, and our own server ──────────────────────────────────────
_rule(r"couldn't reach the licence server|licence server|unreachable",
      Problem(
          "Prism couldn't check your licence",
          "Prism asks our server for permission each time you start work, and "
          "it didn't answer. This is almost always the internet, and it "
          "usually clears on its own within a minute.",
          ("Check this computer is online — try loading any website.",
           "Wait about a minute and press Start the work again. Our server "
           "sometimes takes a moment to wake up.",
           "If you are on office wifi, a firewall may be blocking it — try a "
           "phone hotspot to check."),
          ask_support=True))

_rule(r"check your internet|connection|network is unreachable|getaddrinfo|"
      r"name or service not known|temporary failure in name resolution|"
      r"timed out",
      Problem(
          "No internet connection",
          "Prism needs the internet for everything it does — it plans your "
          "task online and drives the AI tools in a browser.",
          ("Try loading any website to confirm you're online.",
           "If you're connected but it still fails, turn wifi off and on "
           "again.",
           "On a company network, ask whoever runs IT whether the AI websites "
           "are blocked.")))

# ── Groq: the planning brain ──────────────────────────────────────────────
_rule(r"rate.?limit",
      Problem(
          "Your AI allowance is used up for now",
          "Groq — the free service Prism uses to plan your work — only allows "
          "so many requests in a short period, and you've reached it. Nothing "
          "is broken and nothing is lost.",
          ("Wait one minute, then press Make a plan again.",
           "If you're running several tasks at once, do them a few at a time.",
           "To remove the limit, upgrade your plan at console.groq.com — it "
           "is your own account, not ours.")))

_rule(r"rejected your api key|invalid api key|401",
      Problem(
          "Your Groq key isn't working",
          "The key Prism uses to plan your work was refused. Usually the key "
          "was deleted, or only part of it was pasted in.",
          ("Go to console.groq.com and sign in.",
           "Open API Keys and create a new key. It starts with gsk_.",
           "Copy the WHOLE key, then paste it into Settings → Groq API key."),
          action="settings:key", action_label="Open Settings"))

_rule(r"none of the models|model.*(not found|decommission|deprecat|no longer)",
      Problem(
          "The AI model Prism uses has changed",
          "Groq has retired the model Prism was using. Prism normally switches "
          "to another one by itself, so seeing this means all of the ones it "
          "knows about are unavailable on your key.",
          ("Press Make a plan once more — Prism will try the next model.",
           "If it keeps failing, this needs an update from us."),
          ask_support=True))

_rule(r"no groq api key|set your groq api key",
      Problem(
          "Prism needs your Groq key first",
          "Groq is the free service Prism uses to work out the steps for your "
          "task. It takes two minutes to get a key.",
          ("Go to console.groq.com and sign up — it's free.",
           "Open API Keys → Create API Key.",
           "Copy it and paste it into Settings → Groq API key."),
          action="settings:key", action_label="Open Settings"))

# prism_terminal/core/mailer.explain_error()'s own timeout message —
# workers.SendWorker/VerifyWorker route their smtplib failures through it
# now (a real bug: they used to emit the bare exception text instead), so
# this rule exists to give ITS wording a proper title/steps rather than
# also falling through to _GENERIC, same reasoning as the rate-list rule
# below. Matched on stable prose, not the embedded port numbers.
_rule(r"mail server didn't answer|blocking outbound mail",
      Problem(
          "Your mail server couldn't be reached",
          "This is very rarely the mail account itself — it almost always "
          "means something on this network is blocking outbound mail "
          "traffic entirely, which is common on ISPs and office firewalls.",
          ("Open Email → Change account and try the other port (465 ↔ "
           "587) — some networks block one but not the other.",
           "If you can, send from a different network (a phone hotspot is "
           "the fastest way to test) — if it works there, the network is "
           "the cause, not the account.",
           "On a company network, ask whoever runs IT whether outbound "
           "SMTP (ports 587/465) is blocked.")))

# Written as an already-actionable sentence at the call site
# (addons/inquiry/dialog.py's quotation flow) — without this rule it fell
# through every pattern above to _GENERIC and threw that specific, already-
# correct message away in favour of "Something went wrong", the one outcome
# this whole module exists to avoid (see the module docstring).
_rule(r"rate list or.*cost sheet",
      Problem(
          "Nothing to price from yet",
          "This inquiry needs your rate list or your cost sheet before Prism "
          "can work out a quotation.",
          ("Open Email inquiry automation → Setup → Files.",
           "Add a rate list (a price per item) or a cost sheet (your own "
           "pricing formulas) — either one is enough.",
           "Come back and press Prepare a quotation again.")))

# ── the browser ───────────────────────────────────────────────────────────
# BEFORE the "browser window was closed" rule, because it has to be: a Chrome
# that never STARTED reports "cannot connect to chrome at 127.0.0.1:53695 —
# from chrome not reachable", and "chrome not reachable" is in that rule's
# pattern. Read as a closed window, the advice became "everything you finished
# is in History, start the run again" — for a run that had not started, and
# would fail the same way every time until the leftover Chrome was closed.
#
# Which is what this actually is, nearly always: Chrome allows one browser per
# profile folder, so a second launch on the same folder hands over to the
# first and exits. See core/automation.py's _release_profile(), which now
# clears that before launching — this rule is what to say when it could not.
_rule(r"cannot connect to chrome at",
      Problem(
          "Chrome closed before Prism could use it",
          "Prism opens its own Chrome window to do the work. That window "
          "started and then closed again immediately — nearly always because "
          "another copy of Prism's Chrome was already running in the "
          "background and only one can use it at a time.",
          ("Close every Chrome window, including any Prism opened for signing "
           "in, then try again.",
           "On a Mac, closing Chrome's windows leaves it running — quit it "
           "with ⌘Q (Chrome menu → Quit Google Chrome) first.",
           "If it happens again, restart the computer — that clears it for "
           "certain.",
           "If you use antivirus or company security software, it may be "
           "stopping Prism from starting Chrome. Allow Prism through it.")))

# BEFORE the version-mismatch rule, whose pattern ("chromedriver") is in
# both of these messages. Found on a client's M2 (10 Sep 2026): the engine
# raised a careful explanation -- an Intel driver, a Mac with no Rosetta --
# and this file rewrote it into "Chrome updated itself, update Chrome", with
# the true text folded away under Technical detail. The customer did what
# the screen said and it changed nothing.
_rule(r"bad cpu type|errno 86|built for intel macs|no rosetta",
      Problem(
          "The browser driver that ran is built for Intel Macs",
          "This Mac has an Apple silicon chip and no Rosetta, so the Intel "
          "build of the browser driver cannot run. Prism fetches its own "
          "Apple silicon driver; it needs to be online once to do that.",
          ("Check this Mac is online and press Start again.",
           "If it comes back, open Terminal, paste this line, then try once "
           "more:  rm -rf ~/Library/Application\\ Support/undetected_chromedriver",
           "Still stuck? Settings → Export diagnostics and send us the file."),
          action="support", action_label="Get help"))

_rule(r"apple silicon browser driver",
      Problem(
          "Prism needs its Apple silicon browser driver",
          "This Mac has an Apple silicon chip. Prism drives Chrome through a "
          "small helper built for that chip, which it downloads once from "
          "Google's Chrome for Testing site — and this Mac could not reach it.",
          ("Check this Mac is online and press Start again. The download is "
           "about 10 MB and happens once per Chrome version.",
           "On a company network, ask IT to allow googlechromelabs.github.io "
           "and storage.googleapis.com.",
           "Still stuck? Settings → Export diagnostics and send us the file."),
          action="support", action_label="Get help"))

_rule(r"could not determine browser executable",
      Problem(
          "Google Chrome isn't installed",
          "Prism does its work inside Google Chrome, using your own logins. "
          "It can't find Chrome on this computer.",
          ("Install Google Chrome from google.com/chrome.",
           "Open it once and sign in to the AI tools you use.",
           "Come back to Prism and try again.",
           "It has to be Chrome — Prism cannot use Edge, Safari or Firefox.")))

# BEFORE the version-mismatch rule below, and the order is the whole point.
#
# A "no such window" error arrives with a Selenium stack trace, and every
# frame of that trace says "undetected_chromedriver" — which matches the
# chromedriver pattern below. So a closed tab was diagnosed as a driver
# version mismatch, and the customer was sent to update a browser that was
# working perfectly. A wrong answer given confidently is worse than the
# generic "something went wrong" it replaced.
_rule(r"no such window|target window already closed|web view not found|"
      r"invalid session id|session deleted because of page crash|"
      r"disconnected: not connected to devtools|chrome not reachable|"
      r"browser has closed",
      Problem(
          "The browser window was closed",
          "Prism was working in a Chrome window and that window went away — "
          "usually because it was closed by hand while the run was going, or "
          "because Chrome itself quit. Nothing is wrong with your computer or "
          "your setup.",
          ("Everything finished before this point was kept — check History.",
           "Start the run again, and leave Prism's Chrome window alone while "
           "it works. You can use a different Chrome window in the meantime.",
           "If you did not close it, Chrome may have run out of memory — "
           "close some other tabs and try again.")))

_rule(r"couldn't start chrome|chromedriver|session not created|"
      r"this version of chrome|webdriver",
      Problem(
          "Prism couldn't open Chrome",
          "Chrome updates itself every few weeks, and for a day or two after "
          "an update Prism's browser connection can stop matching it.",
          ("Open Chrome, click the Chrome menu → About Google Chrome, let it "
           "update, then close Chrome completely and try again.",
           "If you set a Chrome version by hand in Settings → Chrome, clear "
           "that box so Prism finds it automatically.",
           "Make sure Google Chrome is actually installed — Prism cannot use "
           "Safari or Edge."),
          action="settings:chrome", action_label="Open Chrome settings"))

_rule(r"profile appears to be in use|user data directory is already",
      Problem(
          "Prism's browser is still open somewhere",
          "A previous run left a Chrome window running in the background, and "
          "only one can use Prism's browser at a time.",
          ("Close every Chrome window, including any Prism opened.",
           "On a Mac, quit Chrome with ⌘Q — closing its windows leaves it "
           "running.",
           "If that doesn't help, restart the computer — it clears it for "
           "certain.")))

_rule(r"not signed in|sign in to this tool|signed out",
      Problem(
          "You're not signed in to one of the AI tools",
          "Prism uses your own accounts — ChatGPT, Claude and the rest — and "
          "one of them has signed you out. Signing in once is remembered from "
          "then on.",
          ("Click Login tabs in the left sidebar.",
           "Sign in to each tool in the window Prism opens.",
           "Close that window and run your task again."),
          action="login", action_label="Open Login tabs"))

_rule(r"human.?verification|are you a robot|captcha",
      Problem(
          "A tool is asking to check you're human",
          "One of the AI websites showed a 'confirm you're human' box. Prism "
          "cannot click those — they exist to stop software doing exactly "
          "that.",
          ("Click Login tabs in the sidebar.",
           "Tick the box on whichever site is asking.",
           "Run your task again. It usually only asks once."),
          action="login", action_label="Open Login tabs"))

# ── licence and add-ons ───────────────────────────────────────────────────
_rule(r"isn't in your licence|feature_not_licensed|not licensed",
      Problem(
          "That's not part of your plan",
          "This part of Prism is sold separately from the one you have. "
          "Nothing is broken — it simply isn't switched on for your licence.",
          ("Everything else keeps working as normal.",
           "If you'd like it added, get in touch and we'll send an updated "
           "key — it takes effect immediately, with nothing to reinstall.")))

_rule(r"licence has ended|expired|licence is over",
      Problem(
          "Your licence has ended",
          "New work is paused, but nothing has been taken away — your history "
          "and everything you've already produced are still here.",
          ("Open History to reach anything you made before.",
           "Contact us to renew. Entering the new key switches everything "
           "back on straight away.")))

_rule(r"clock|date and time",
      Problem(
          "This computer's date looks wrong",
          "Prism checks the date to confirm your licence, and this computer's "
          "clock has gone backwards.",
          ("Open your computer's Date & Time settings.",
           "Turn on 'Set date and time automatically'.",
           "Connect to the internet and restart Prism.")))

# ── email ─────────────────────────────────────────────────────────────────
_rule(r"app password|smtpauth|authentication failed|username and password",
      Problem(
          "Your email password was refused",
          "Gmail and most other providers no longer let apps use your normal "
          "password. They need a separate 'app password' — a one-off code you "
          "create for Prism.",
          ("Go to myaccount.google.com/apppasswords and sign in.",
           "Create an app password, name it Prism, and copy the 16 letters.",
           "Paste that into Prism's email setup instead of your real "
           "password.")))

# ── files and disk ────────────────────────────────────────────────────────
_rule(r"no space left|disk full|errno 28",
      Problem(
          "This computer has run out of space",
          "Prism couldn't save because the hard disk is full.",
          ("Empty the Trash.",
           "Delete or move some large files, then try again.",
           "In Settings you can see how much space Prism's own history is "
           "using.")))

_rule(r"permission denied|errno 13|read-only file system",
      Problem(
          "Prism isn't allowed to open that file",
          "The computer refused access. Usually the file is somewhere "
          "protected, or it's open in another program.",
          ("Close the file if it's open in Word, Excel or a PDF reader.",
           "Try copying it to your Desktop and attaching it from there.")))

_rule(r"file not found|no such file|filenotfound",
      Problem(
          "That file isn't there any more",
          "The file has been moved, renamed or deleted since it was attached.",
          ("Remove it from the attached list and add it again.",)))

# ── optional extras ───────────────────────────────────────────────────────
_rule(r"ezdxf|libredwg|\.dwg",
      Problem(
          "Save the drawing as DXF and it will work",
          "Prism measures DXF drawings directly. A .dwg is Autodesk's own "
          "closed format, and reading one needs a separate converter that "
          "isn't installed here — but the same drawing saved as DXF needs "
          "nothing at all.",
          # DXF first, and it used to be second, behind "send us this message
          # and we'll send you the one-line install". That put a wait on
          # support in front of a fix the person can do in ten seconds
          # without anybody's help — for the same drawing, with no loss of
          # accuracy, since DXF carries the identical geometry.
          ("In your CAD program: File → Save As → AutoCAD DXF. Attach that "
           "file instead.",
           "Or describe the job in words instead of attaching a drawing; the "
           "BOQ add-on works from a written spec too.",
           "If you would rather attach .dwg files directly, tell us and we'll "
           "send you the free converter to install once."),
          ask_support=True))

_rule(r"ffmpeg",
      Problem(
          "Video needs one extra program",
          "Making a reel needs FFmpeg, a free video tool that isn't part of "
          "Prism. Prism can fetch it for you.",
          # No longer "send us this message". Prism downloads and installs it
          # itself now, so telling a customer to contact support for a job the
          # software does in a minute would be an odd thing to do.
          ("Open Reel and press Get FFmpeg. It's about 30 MB and takes a "
           "minute; it only happens once.",
           "Nothing else changes on this computer, and everything else in "
           "Prism works without it.")))

# Both operating systems, not one. This offered the macOS permission screen
# and nothing else — so a Windows customer, whose commonest cause is exactly
# the same permission being off, was handed the settings path of an OS they
# are not running and left with no route of their own. Windows is most of
# the customers this is sold to. (KNOWN_ISSUES #14 names FFmpeg and the
# microphone together; the FFmpeg half was fixed long ago and only this was
# left.)
_rule(r"pyaudio|portaudio|microphone",
      Problem(
          "The microphone isn't available",
          "Prism couldn't reach the microphone, so speaking your task isn't "
          "available on this computer.",
          ("Check that no other program is using the microphone.",
           "On Windows, open Settings → Privacy & security → Microphone and "
           "make sure desktop apps are allowed to use it.",
           "On a Mac, look in System Settings → Privacy & Security → "
           "Microphone and make sure Prism is allowed.",
           "Everything else works — just type the task instead.")))

# ── the tools themselves ──────────────────────────────────────────────────
_rule(r"returned nothing|no response|couldn't read the response|empty",
      Problem(
          "One of the AI tools didn't answer",
          "The tool was asked, but nothing came back in time. This is usually "
          "the website being slow or having changed its page.",
          ("Your other steps still ran — check the results above.",
           "Click the link next to that step to open the tool and see whether "
           "the answer arrived after Prism stopped waiting.",
           "Run just that step again by unticking the others."),
          ask_support=True))

_rule(r"apollo",
      Problem(
          "Apollo didn't return any leads",
          "Three things cause this: the search was too narrow, the Apollo "
          "account is signed out, or it has run out of email credits for the "
          "month.",
          ("Click Login tabs and check you can see Apollo's People table.",
           "Look at the credit balance at the top of Apollo.",
           "Try a broader search — a wider area, or more job titles.")))

# ── the catch-all ─────────────────────────────────────────────────────────
_GENERIC = Problem(
    "Something went wrong",
    "Prism hit a problem it doesn't recognise. Nothing you have already "
    "produced has been lost.",
    ("Try the same thing once more — many problems are momentary.",
     "Ask Lumi if it happens again — she has a written answer for "
     "most things, and opens the way to us when none of them fits.",
     "Everything already finished is still in History."),
    ask_support=True,
    # The one entry where we genuinely do not know what went wrong, so it is
    # the one that most needs a route onwards rather than a shrug. Saving the
    # diagnostics file is still offered beside it; this is the faster half.
    action="support", action_label="Ask Lumi")


# The server's own customer-facing AI refusal copy (licence server errors.py).
_AI_REFUSAL = re.compile(
    r"enough (AI )?credits|needs? [0-9,.]+ credits|top up your credits"
    r"|AI isn't switched on for your account|AI is paused on your account"
    r"|AI isn't available( to your account)?|AI is (blocked|not available)"
    r"|re-check your licence before using AI", re.I)


def explain(error: object, context: str = "") -> Problem:
    """Any error → something a person can act on.

    `context` is a hint from the caller ("attach", "run", "email") used only
    when the text itself is not distinctive enough to match.
    """
    text = f"{context} {error}".strip()
    # The licence server words its own AI refusals for the customer ("needs
    # 40 credits and you have 12", "isn't switched on for your account").
    # Show that sentence itself, not a generic "something went wrong".
    if _AI_REFUSAL.search(str(error)):
        return Problem(
            "Prism AI couldn't run this",
            str(error).strip(),
            ("Nothing was charged for the step that stopped.",
             "Everything already finished is still in History."))
    for pattern, problem in _RULES:
        if pattern.search(text):
            return problem
    return _GENERIC


def as_text(problem: Problem) -> str:
    """The whole thing as plain text, for a status bar or a log line."""
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(problem.steps, 1))
    return f"{problem.title}\n\n{problem.what}\n\n{steps}".strip()
