"""Builds every page of the AlphaKore reskin of Prism.

Run:  python3 _generator/build.py   (from preview/alphakore-reskin/)

Layout copies today's app screen by screen (captured offscreen from prism_gui on
2026-11-03 with a sandbox HOME); copy is verbatim from the add-on panel.py /
dialog.py files. Behaviour and mock data live in app.js + mock.js: this file only
lays out the static frame and gives every control the id app.js looks for.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARTS = os.path.join(HERE, "parts")


def part(name):
    with open(os.path.join(PARTS, name), encoding="utf-8") as f:
        return f.read()


EXTRA_ICONS = """
  <symbol id="i-mic" viewBox="0 0 24 24"><rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/></symbol>
  <symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/></symbol>
  <symbol id="i-pencil" viewBox="0 0 24 24"><path d="M15.5 4.5l4 4L9 19H5v-4z"/><path d="M13.5 6.5l4 4"/></symbol>
  <symbol id="i-eye" viewBox="0 0 24 24"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/></symbol>
  <symbol id="i-ext" viewBox="0 0 24 24"><path d="M14 4.5h5.5V10M19.5 4.5 11 13M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10"/></symbol>
  <symbol id="i-sliders" viewBox="0 0 24 24"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></symbol>
  <symbol id="i-help" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.4"/><circle cx="12" cy="16.8" r=".6"/></symbol>
  <symbol id="i-list" viewBox="0 0 24 24"><path d="M5 7h14M5 12h14M5 17h9"/></symbol>
  <symbol id="i-key" viewBox="0 0 24 24"><circle cx="8" cy="15" r="3.8"/><path d="m10.8 12.2 8.7-8.7M16 6.5l2.5 2.5M13.5 9l2 2"/></symbol>
  <symbol id="i-play" viewBox="0 0 24 24"><path d="M8 5.5v13l10-6.5z"/></symbol>
  <symbol id="i-video" viewBox="0 0 24 24"><rect x="3.5" y="6.5" width="12" height="11" rx="2"/><path d="m15.5 10.5 5-3v9l-5-3"/></symbol>
  <symbol id="i-expand" viewBox="0 0 24 24"><path d="M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5 14 10M4.5 19.5 10 14"/></symbol>
  <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></symbol>
  <symbol id="pcheck" viewBox="0 0 18 18"><g fill="#fff"><rect x="2" y="9" width="2" height="2"/><rect x="5" y="12" width="2" height="2"/><rect x="8" y="9" width="2" height="2"/><rect x="11" y="6" width="2" height="2"/><rect x="14" y="3" width="2" height="2"/></g></symbol>
"""
SPRITE = part("sprite.svg").replace("</defs></svg>", EXTRA_ICONS + "</defs></svg>")


def ic(name):
    return f'<svg class="i"><use href="#i-{name}"/></svg>'


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def light(label, icon=None, attrs="", cls=""):
    return f'<button class="btn light plain sm{" " + cls if cls else ""}" {attrs}>{ic(icon) if icon else ""}{label}</button>'


def dark(label, pixel="parrow", attrs="", sm=True, cls=""):
    return (f'<button class="btn dark{" sm" if sm else ""}{" " + cls if cls else ""}" {attrs}><span class="ic"><svg><use href="#{pixel}"/></svg></span>'
            f'{label}</button>')


def chip(label, icon=None, attrs="", cls=""):
    return f'<button class="chip{" " + cls if cls else ""}" {attrs}>{ic(icon) if icon else ""}{label}</button>'


def off(why):
    """A disabled control always says why (owner's rule, 2026-10-27). app.js re-enables it."""
    return f'disabled title="{esc(why)}" aria-label="{esc(why)}"'


def select(opts, label, attrs=""):
    return f'<select class="sel" aria-label="{esc(label)}" {attrs}>' + "".join(f"<option>{o}</option>" for o in opts) + "</select>"


# ── shell ────────────────────────────────────────────────────────────────
RAIL = [  # order and labels as the app's rail (addons/*/addon.py order); Reel and Motion are Home-only
    ("inquiry.html", "inbox", "Email Inquiries"), ("boq.html", "sheet", "BOQ"), ("gerber.html", "chip", "Gerber"),
    ("step.html", "cube", "STEP"), ("email.html", "mail", "Email Outreach"), ("leads.html", "user", "Leads &amp; Outreach"),
    ("whatsapp.html", "chat", "WhatsApp"), ("bom.html", "box", "BOM &amp; Stock"),
]


def sidebar(active):
    def item(href, icon, label, tile=False):
        on = ' on' if href == active else ''
        cur = ' aria-current="page"' if on else ''
        inner = f'<span class="tile">{ic(icon)}</span>' if tile else ic(icon)
        return f'<a class="navi{on}" href="{href}"{cur} title="{label.replace("&amp;", "&")}">{inner}<span>{label}</span></a>'
    work = "".join(item(h, i, l) for h, i, l in [("index.html", "home", "Home"), ("history.html", "clock", "History"), ("artifacts.html", "folder", "Artifacts")])
    adds = "".join(item(h, i, l, tile=True) for h, i, l in RAIL)
    return f"""<aside class="side">
    <div class="brand">
      <a href="index.html" title="Home"><img class="crystal" src="img/prism-logo.svg" alt="Prism"></a>
      <div class="txt">
        <div class="name">Prism</div>
        <div class="by">by <svg viewBox="0 0 789 480" aria-label="AlphaKore"><use href="#ak"/></svg> AlphaKore</div>
      </div>
      <button class="iconbtn collapse" title="Collapse the sidebar">{ic("left")}</button>
    </div>
    <div class="label">Work</div>
    <a class="btn dark" href="index.html#new" title="New task"><span class="ic"><svg><use href="#pplus"/></svg></span><span class="t">New task</span></a>
    <nav class="nav">{work}</nav>
    <div class="grp"><div class="label">Add-ons</div>{ic("down")}</div>
    <div class="addons"><nav class="nav">{adds}</nav></div>
    <a class="me" href="settings.html#profile" title="Your profile and settings">
      <div class="avatar">P</div>
      <div class="who"><b>Parth</b><span>complete plan</span></div>
      {ic("right")}
    </a>
  </aside>"""


def page(fname, title, active, key, body, extra="", full=False, sid=""):
    cls = "screen on full" if full else "screen on"
    sid = f' id="{sid}"' if sid else ""
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Prism by AlphaKore</title>
<link rel="stylesheet" href="style.css">
</head>
<body data-page="{key}">
<div class="canvas"></div>
{SPRITE}
<div class="app">
  {sidebar(active)}
  <main class="main">
    <section class="{cls}"{sid}>
{body}
    </section>
  </main>
</div>
{extra}
<button class="edge" title="Open Lumi, Prism's helper">{ic("left")}</button>
<div class="status"><span class="ok">Ready.</span><span class="r">Prism 1.6.13 · by AlphaKore <svg viewBox="0 0 789 480"><use href="#ak" fill="currentColor"/></svg></span></div>
<script src="mock.js"></script>
<script src="app.js"></script>
</body>
</html>
"""
    with open(os.path.join(ROOT, fname), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", fname)


def phead(title, sub="", acts=""):
    p = f"<p>{sub}</p>" if sub else ""
    return f"""      <header class="phead">
        <div><h1>{title}</h1>{p}</div>
        <div class="acts">{acts}</div>
      </header>"""


def modal(mid, icon, title, sub, body, foot, head_acts="", size=""):
    return f"""<div class="modal" id="{mid}" data-hash role="dialog" aria-modal="true" aria-labelledby="{mid}-t">
  <div class="scrim" data-close></div>
  <div class="dlg{' ' + size if size else ''}">
    <div class="dh"><span class="tile">{ic(icon)}</span><div><h2 id="{mid}-t">{title}</h2><p>{sub}</p></div>{f'<div class="acts">{head_acts}</div>' if head_acts else ''}</div>
    <div class="db">
{body}
    </div>
    <div class="df">{foot}</div>
  </div>
</div>"""


ASK_CHIPS = (f'<div class="row">{chip("Speak", "mic", cls="js-speak")}{chip("Add file", "clip", cls="js-add")}'
             f'{chip("Favourites", "folder", cls="js-fav")}</div><div class="att js-att"></div>')


def ph_attr(ph):
    return ph.replace('"', "&quot;")


# ── front pages: How it works + What you can ask for (BOQ, Gerber, BOM) ──
def front(title, sub, attach_label, steps, asks):
    st = "".join(f"""<div><div class="top"><span class="ftile">{ic(i)}</span><span class="n">0{n + 1}</span></div>
          <h3>{h}</h3><p>{p}</p></div>""" for n, (i, h, p) in enumerate(steps))
    ak = "".join(f"""<div class="r"><span class="ftile">{ic("mic")}</span><div><b>“{q}”</b><span class="d">{d}</span></div>
          {light("Try this", None, f'data-open="make" data-fill="{esc(q)}"', cls="js-try")}</div>""" for q, d in asks)
    return phead(title, sub, light(attach_label, "clip", 'data-open="make"')) + f"""
      <div class="pbody">
        <div class="ftitle"><h2>How it works</h2><p>Fast, automated workflow from drawing to finished document.</p></div>
        <div class="card steps">{st}</div>
        <div class="ftitle"><h2>What you can ask for</h2><p>Click an example or type your own prompt in the dialog.</p></div>
        <div class="card asks">{ak}</div>
      </div>"""


# ── BOQ / BOM — a four-step helper for people who have never used AI ──
# Owner, 2026-11-03: "for those people who have never used ai, so the UI UX should be so easy".
# One question per step, everyday words. Every control of Hitarth's dialog (addons/boq/dialog.py)
# is still reachable: experts' settings, the full measured table, Input measurements, PDF takeoff,
# History, Make with drawing (= "Double-check with AI"), Open in browser, file formats, follow-up.
def boq_dialog(mode):
    noun = "BOM" if mode == "bom" else "BOQ"
    doc = "Bill of Materials" if mode == "bom" else "Bill of Quantities"
    what = "parts list" if mode == "bom" else "bill of quantities"
    writers = ["Prism Agent Claude", "Prism Agent Deep", "Claude", "Grok", "Kimi 2.6", "DeepSeek", "Gemini", "ChatGPT"]
    steps = ["What you have", "Check the count", f"Make the {noun}", "Add prices"]
    stepper = "".join(f'<button class="wsn{" on" if n == 0 else ""}" data-go="{n + 1}" disabled title="Finish the step before first"><span class="num">{n + 1}</span><span>{t}</span></button>' for n, t in enumerate(steps))
    s1 = f"""      <section class="wstep" data-step="1">
        <h3 class="wq">What is this {noun} for?</h3>
        <p class="wsub">Say it in your own words — one line is enough.</p>
        <div class="askline"><textarea class="ta ask" id="w-ask" rows="2" placeholder="e.g. {esc(("Parts list for this magnetic separator" if mode == "bom" else "HVAC ductwork for Sargam Tower B"))}" aria-label="What is this {noun} for?"></textarea>
          {chip("Speak", "mic", 'title="Say it instead of typing"', cls="js-speak")}</div>
        <div class="examples" id="w-ex"><span class="muted small">Or pick one:</span></div>
        <div class="drop" id="w-drop">
          <span class="dropic">{ic("file")}</span>
          <div class="droptx"><b>Add your drawing</b><p>DXF or PDF. Prism measures it on this computer — the drawing itself is never sent to AI unless you say yes.</p></div>
          {dark("Choose drawing", "pplus", 'id="w-choose"')}
        </div>
        <div class="att js-att" id="w-files"></div>
        <div class="group" id="d-ext" hidden><div class="label">Your measurements</div><pre class="extview" id="d-extview"></pre><div class="okmsg" id="d-extmsg"></div></div>
        <ul class="wlinks">
          <li class="muted">{ic("help")}No drawing? That's fine — describe the job above and Prism lists the items.</li>
          <li class="hvacon" id="w-hvac" hidden>{ic("check")}HVAC drawing rules are on — because your request says HVAC.</li>
          <li><button id="w-sample">{ic("sheet")}Make it look like my company's {noun}</button><span class="muted small" id="w-samplename"></span></li>
          <li><button id="d-meas">{ic("clip")}I already have some measurements</button></li>
          {"" if mode == "bom" else '<li id="w-takeoff-li" hidden><button id="w-takeoff">' + ic("file") + 'My HVAC drawing is a PDF tender — measure it</button></li>'}
          <li><button id="d-hist">{ic("clock")}Open a past {noun}</button></li>
          <li><button id="w-dwg">{ic("help")}My drawing is a .dwg file</button></li>
        </ul>
        <details class="more experts"><summary>{ic("right")}Settings for experts (optional)</summary>
          <p class="muted small">Prism picks good defaults. Change these only if you know you need to.</p>
          <div class="meta"><span class="pair">Write with {select(writers, "Write with", 'id="d-writer"')}</span><span class="pair">Research with {select(["No research", "Perplexity", "ChatGPT", "Claude"], "Research with", 'id="d-research"')}</span>
            <span class="pair">File format {select(["Let the tool decide", "Word document (.docx)", "CSV", "PDF"], "File format", 'id="d-format"')}</span>
            <span class="pair">Industry {select(["General", "HVAC"], "Industry", 'id="d-industry"')}</span></div>
          <div class="meta" style="flex-direction:column;align-items:stretch">
            <input class="field2" placeholder="Drawing unit, if you know it — e.g. meters" aria-label="Drawing unit">
            <input class="field2" placeholder="Only include layers containing… (comma separated)" aria-label="Only include layers">
            <input class="field2" placeholder="What the drawing's symbols mean, if the sheet doesn't say — e.g. circles = light points" aria-label="Legend">
            <label class="opt"><input type="checkbox" class="ck" checked> Estimate items the drawing doesn't contain (marked as an estimate)</label>
          </div>
          {"" if mode == "bom" else chip("HVAC PDF takeoff…", "clip", 'id="d-takeoff" hidden')}
        </details>
      </section>"""
    body = f"""<div class="wiz">
      <nav class="wsteps" aria-label="Steps">{stepper}</nav>
{s1}
      <section class="wstep" data-step="2" id="w-s2" hidden></section>
      <section class="wstep" data-step="3" id="w-s3" hidden><div class="out js-out" hidden></div></section>
      <section class="wstep" data-step="4" id="w-s4" hidden></section>
    </div>"""
    foot = (light("Back", "left", 'id="w-back" hidden') + '<span class="sp"></span>' + light("Close", None, "data-close")
            + light("Skip prices", None, 'id="w-skip" hidden') + dark("Next: count it", attrs='id="w-next" ' + off("Add a drawing or describe the job first")))
    return modal("make", "sheet" if mode == "boq" else "box", doc,
                 f"Make a {what} from your drawing in four easy steps.", body, foot, size="wizw")


def build_boq():
    body = front("BOQ", "Quantities off a CAD drawing, or a written spec. Prism counts and measures — you price it.", "Attach a file",
                 [("clip", "Attach the drawing", "Upload a CAD drawing (DXF/PDF) or enter a written description."),
                  ("bars", "Prism measures it", "Counts, lengths, and areas are calculated automatically."),
                  ("file", "Attach a sample BOQ too", "Upload your past BOQ (Excel/Word) to match your company's format."),
                  ("grid", "Price &amp; export", "Generates itemized quantities and priced Excel sheets with live formulas.")],
                 [("BOQ for CCTV, cabling and fibre for this site", "Measures your CAD drawing and matches formatting to your past BOQs."),
                  ("Materials to build one 36x24 jaw crusher, 100 TPH", "Generates an itemized Bill of Quantities directly from your prompt.")])
    page("boq.html", "BOQ", "boq.html", "boq", body, boq_dialog("boq"))


def build_bom():
    body = front("BOM", "The parts list to fabricate it — off a CAD drawing, or a written spec. Prism counts and measures the parts; you price them.", "Attach a file",
                 [("clip", "Attach the drawing", "Upload a GA drawing (DXF/PDF) or describe the assembly."),
                  ("bars", "Prism measures the parts", "Part counts, cut lengths, and plate areas are measured locally."),
                  ("file", "Audit the take-off", "Review verified part quantities in a clean, checkable CSV."),
                  ("pencil", "Export Bill of Materials", "Outputs an organized BOM grouped by material, grade, and size.")],
                 [("Parts list to fabricate this over-band magnetic separator", "Measures your GA drawing to extract plate sizes, beam lengths, and hardware."),
                  ("BOM for one 36x24 jaw crusher, 100 TPH", "Generates a complete fabrication parts list directly from specifications.")])
    page("bom.html", "BOM", "bom.html", "bom", body, boq_dialog("bom"))


def build_gerber():
    body = front("Gerber", "PCB size, track width &amp; spacing, drill size and count — measured from the Gerber files, not guessed.", "Attach a job",
                 [("clip", "Drop the job", "Attach the customer .zip or .rar Gerber archive directly."),
                  ("bars", "Measured on this machine", "Board size, track width, spacing, and drill counts are extracted."),
                  ("lock", "The design never leaves", "Only measured numbers are processed — Gerber files stay private."),
                  ("pencil", "Quote or spec", "Generates ready-to-send fabrication notes, price breakdowns, or replies.")],
                 [("Reply with our price for 500 pieces", "Generates a priced fabrication quote from measured PCB specifications."),
                  ("Fabrication note &amp; PCB inspection summary", "Summarizes board size, track width/spacing, and drill counts for manufacturing.")])
    dbody = f"""      <h3>What is this job, and what do you want done with it?</h3>
      <textarea class="ta ask" placeholder="Drop the customer's zip or rar exactly as it arrived — a folder works too. Set the client's format below if you want it, then press Generate." aria-label="What is this job?"></textarea>
      {ASK_CHIPS}
      <div class="privacy">{ic("lock")}<span>The Gerber files never leave this machine. If you ask for a write-up below, only the measured NUMBERS are shown to an agent — never a file, never a path.</span></div>
      <div class="group"><div class="label">Client's format (optional)</div>
        <div class="split"><p>If the client wants the figures in their own Excel form — a quotation format, a checklist — choose it here. Prism fills the cells it recognises and leaves everything else exactly as they drew it.</p>
          <span class="tplbox"><span id="d-tplname" class="mono small"></span>{light("Choose template…", None, 'id="d-tpl"')}</span></div>
        <div class="meta">Measurements in {select(["mm", "mil"], "Measurements in", 'id="d-unit"')} — every size, width, spacing and drill diameter on the filled form</div></div>
      <div class="group"><div class="label">Files for the AI (optional)</div>
        <div class="split"><p>The inquiry email, price list or spec sheet (PDF, Word, Excel). These files WILL be shown to the AI — only to fill the form fields measurement cannot know. The Gerber files are never shown. <span id="d-filesname" class="mono small"></span></p>
          {light("Add files…", "clip", 'id="d-files"')}</div></div>
      <div class="out js-out">If you asked for a write-up, the agent's reply appears here.</div>"""
    foot = (light("Clean Outline", "file", 'id="d-clean" ' + off("Generate first — the outline comes from the measured board"))
            + light("Open Browser", "ext", 'id="d-ob" ' + off("Generate first"))
            + light("Answer with AI", "pencil", 'id="d-ans" ' + off("After generating: an agent writes the reply or quotation from the measured numbers — the files still never leave"))
            + light("Fill with AI", "pencil", 'id="d-fill" ' + off("After generating with a template: your attached email/pricing documents — never the Gerbers — are shown to an agent to fill the blank fields"))
            + '<span class="sp"></span>' + light("Close", None, "data-close") + dark("Generate", "pdots", 'id="d-make" ' + off("Attach a job first")))
    page("gerber.html", "Gerber", "gerber.html", "gerber", body,
         modal("make", "chip", "Gerber", "PCB size, track width, spacing, drill size and count — measured off the files themselves.", dbody, foot, size="mid"))


# ── STEP: the rail opens its workbench directly (main_window._open_step) ──
def build_step():
    body = f"""      <header class="phead stephd">
        <h1>STEP</h1><span class="trust">Measured here — never uploaded</span>
        <div class="acts">{light("Output folder", "folder", 'id="st-of" ' + off("Attach a model first"))}
          <select class="sel" id="st-mat" aria-label="Part type"><option>Sheet metal</option><option>Plastic</option></select>
          <a class="iconbtn" href="index.html" title="Close STEP" style="box-shadow:inset 0 0 0 1px var(--line2)">{ic("x")}</a></div>
      </header>
      <div class="pbody">
        <div class="ws3">
          <section class="card pane" aria-label="Models">
            <div class="ph"><span class="label">Models</span><span class="badge" id="st-count">0</span></div>
            <div id="st-models"></div>
            <div class="divider"></div>
            <div class="ph"><span class="label">History</span></div>
            <div id="st-hist"><div class="emptyline">No runs yet.</div></div>
            <div class="dropz">Drop .step / .stp files here<br><a href="#" id="st-browse">or browse</a><a href="#" id="st-fav">Favourites</a></div>
          </section>
          <section class="card pane" aria-label="Draft, ask or edit">
            <div class="tabsbar"><div class="pseg" id="st-modes"><button class="on">Draft</button><button>Ask</button><button>Edit</button></div></div>
            <div class="centerempty" id="st-empty"><div>
              <h2>Attach a 3D model</h2>
              <p>.step / .stp — several at once is fine. It is measured on this machine; no AI ever sees the file.</p>
              <p>or drop them anywhere on this window</p>
              <div class="steps3">1 Attach · 2 Pick Draft · Ask · Edit · 3 Run</div>
              {dark("Choose files…", "pplus", 'id="st-choose"', sm=False)}
            </div></div>
            <div class="stwork" id="st-work" hidden>
              <div class="render"><svg class="iso" viewBox="0 0 320 220" aria-hidden="true"><g fill="none" stroke="#111110" stroke-width="1.6" stroke-linejoin="round"><path d="M40 150 160 200 290 140 170 90z" fill="#fff"/><path d="M40 150v14l120 50 130-60v-14" fill="#E6E5E1"/><path d="M160 200v14"/><path d="M170 90V30l-40-18v58" fill="#F6F5F2"/><path d="M130 70 40 150"/><path d="M170 30l120 60v50"/><path d="M200 105l40 20 40-20-40-20z" fill="#E6E5E1"/></g><g fill="#fff" stroke="#C8161D" stroke-width="1.6"><ellipse cx="90" cy="158" rx="9" ry="5"/><ellipse cx="225" cy="160" rx="9" ry="5"/><ellipse cx="150" cy="40" rx="5" ry="8"/><ellipse cx="150" cy="62" rx="5" ry="8"/></g></svg><span class="cap">Prism's own render — the model is not shown to any AI</span></div>
              <div class="askbar"><input class="field2" id="st-ask" placeholder="Optional — anything the drawing sheet must show" aria-label="What do you want done with it?">{dark("Run", attrs='id="st-run"')}</div>
            </div>
          </section>
          <section class="card pane" aria-label="Results">
            <div class="tabsbar"><div class="pseg" id="st-rtabs"><button class="on" data-r="m">Measured</button><button data-r="c">Chat</button><button data-r="p">Plan</button><button data-r="f">Files</button></div>
              <button class="iconbtn" id="st-wide" title="Make this panel wider">{ic("expand")}</button></div>
            <div class="rbody2">
              <div data-rp="m" id="rp-m"><div class="rbody">Nothing measured yet — attach a model and press the button.</div></div>
              <div data-rp="c" id="rp-c" hidden><div class="rbody">Pick Ask, type a question about the model, and the answer appears here.</div></div>
              <div data-rp="p" id="rp-p" hidden><div class="rbody">Pick Edit and say what to change. The plan appears here — nothing is built until you press Build.</div></div>
              <div data-rp="f" id="rp-f" hidden><div class="rbody">Files go to Desktop / Prism Artifacts / Step — a folder per model.</div></div>
            </div>
          </section>
        </div>
      </div>"""
    page("step.html", "STEP", "step.html", "step", body, full=True)


# ── Email Inquiries: front door (filled register) + the pipeline screen ──
def build_inquiry():
    front_v = phead("Email inquiry automation", "Prism reads your inbox, writes every inquiry in the register, and tells you what needs you.",
                    light("Edit setup", "sliders", 'id="inq-edit"') + '<a class="btn dark sm" href="#pipeline" title="Opens the working window — check the mail, quote, chase, and record the order."><span class="ic"><svg><use href="#parrow"/></svg></span>Open Email inquiry automation</a>') + """
      <div class="pbody"><div class="inqdash" id="inq-dash"></div></div>"""
    stages = [("quote", "1 · To quote", True), ("wait", "2 · No answer yet", True), ("answered", "3 · They answered", True), ("order", "4 · Order came", True), ("all", "5 · All inquiries", False), ("mail", "6 · All mail", False)]
    st = "".join(f'<button data-s="{k}" class="{"on" if k == "quote" else ""}">{l}{chr(32) + "<span class=" + chr(34) + "n" + chr(34) + "></span>" if n else ""}</button>' for k, l, n in stages)
    acts = (light("Add inquiry", "plus", 'id="inq-add"') + '<label class="lbl-ck"><input type="checkbox" class="ck" id="inq-auto"> Check by itself</label>'
            + light("Setup", "sliders", 'id="inq-setup"') + light("Check my mail now", "inbox", 'id="inq-check"') + f'<button class="iconbtn" id="inq-more" title="More">{ic("more")}</button>')
    pipe_v = phead("Email inquiry automation", "", acts) + f"""
      <div class="pbody">
        <div class="pipe">
          <div class="center"><div class="pseg" id="inq-views"><button class="on" data-v="pipe">Pipeline</button><button data-v="client">Client file</button><button data-v="mail">All mail</button></div></div>
          <div id="inq-pipe" class="pipe2">
            <div class="stages" id="inq-stages">{st}</div>
            <div class="hint" id="inq-hint"></div>
            <div class="card">
              <div class="filters">Show: {select(["All time", "Today", "This week", "This month"], "Show", 'id="inq-show"')}
                <div class="fsearch" style="width:15rem">{ic("search")}<input class="field2" id="inq-q" placeholder="Find a customer …" aria-label="Find a customer"></div></div>
              <div class="inqt" id="inq-table"></div>
              <div id="inq-detail"></div>
            </div>
          </div>
          <div id="inq-client" class="pipe2" hidden></div>
          <div class="foot2">{light("Open the folder", "folder", 'data-toast="Opened Prism Workspace / Inquiries in your file manager"')}{light("Open the register file", "file", 'data-toast="Opened Inquiry register.xlsx"')}<span class="sp"></span>
            <a class="btn light plain sm" href="#">Back to Email inquiry automation</a></div>
        </div>
      </div>"""
    body = f'<div data-view="front">{front_v}</div>\n<div data-view="pipeline">{pipe_v}</div>'
    page("inquiry.html", "Email inquiries", "inquiry.html", "inquiry", body, full=True)


# ── Email Outreach: account + sent log + Send an email ───────────────────
def build_email():
    body = phead("Email Outreach", "Send emails from your own account. Set the account up once.",
                 light("Change account", "key", 'id="em-acct"') + light("New email", "mail", 'data-open="compose"')) + """
      <div class="pbody"><div class="emgrid" id="em-body"></div></div>"""
    dbody = f"""      <div class="form">
        <span class="k">To</span>
        <div class="line"><input class="field2" id="c-to" placeholder="rajesh@acme.in — for more than one, separate with commas" aria-label="To">{chip("Add a list (CSV)", "list", 'id="c-list"')}</div>
        <span></span><div class="line2"><span id="c-listname"></span><a class="hint" href="#" id="c-web">{ic("search")}Don't know the address? Search the web</a></div>
        <span class="k">Subject</span><input class="field2" id="c-subj" placeholder="What the email is about" aria-label="Subject">
        <span class="k">Message</span><textarea class="ta" id="c-msg" rows="9" placeholder="Type the message here, or ask Prism to write it below." aria-label="Message"></textarea>
        <span class="k">Files</span><div class="line">{chip("Attach a file", "clip", 'id="c-attach"')}<span class="att" id="c-att"></span><span class="muted" id="c-none" style="font-size:.88rem">No files attached.</span></div>
      </div>
      <div class="stripe"><b>Pace and limits</b><span class="mono" id="c-paceline">2 s apart · everyone at once · no daily limit · sends now · copy kept in Sent</span><a class="link" href="#" id="c-pace">Change</a></div>
      <div class="group"><div class="label">Want Prism to write the message for you? (optional)</div>
        <div class="line" style="display:flex;gap:.5rem"><input class="field2" id="c-draft" placeholder="Say what it should say — e.g. introduce our spring range and ask for a meeting next week" aria-label="What the draft should say">{chip("Write it for me", "pencil", 'id="c-write"')}</div>
        <p class="muted" style="font-size:.85rem">Attached files are read for the draft. The draft lands in the Message box above; change anything before you send.</p></div>"""
    foot = '<span class="sp"></span>' + light("Close", None, "data-close") + dark("Send", attrs='id="c-send" ' + off("Still needed: To, Subject, Message"))
    page("email.html", "Email Outreach", "email.html", "email", body,
         modal("compose", "mail", "Send an email", "From your account. Fill in To, Subject and Message, then press Send. Nothing goes out until you press it.",
               dbody, foot, head_acts=light("Change account", "key", 'id="c-acct"'), size="mid"))


# ── Leads & Outreach ─────────────────────────────────────────────────────
def build_leads():
    def acc(title, open_body=None):
        if open_body is None:
            return f'<div class="acc"><div class="h">{title}{ic("right")}</div><div class="b" hidden><input class="field2" placeholder="Add a {title.lower()}" aria-label="{title}"></div></div>'
        return f'<div class="acc"><div class="h">{title}{ic("down")}</div><div class="b">{open_body}</div></div>'
    acts = (f'<button class="iconbtn" id="ld-help" title="Help — ask Lumi" style="box-shadow:inset 0 0 0 1px var(--line2)">{ic("help")}</button>'
            + light("Credits", None, 'id="ld-credits" title="Your credits — every paid lookup Leads makes is charged to them. Click for the price list."')
            + light("Export sheets", "file", 'id="ld-export" ' + off("Find or import people first"))
            + dark("Send all", attrs='id="ld-send" ' + off("Pick people and press Draft emails first")))
    body = phead("Leads &amp; Outreach", "Find, qualify and reach the right people — Prism drafts, you send.", acts) + f"""
      <div class="pbody">
        <div class="card wsc">
          <div class="utabs" id="ld-tabs"><button class="on">People</button><button>Sessions</button><button>Lists</button><button>Saved searches</button><button>Sequences</button><button>Analytics</button>
            <span class="sp"></span><span class="chipm">Your credits · your inbox</span></div>
          <div id="ld-people" class="ldp">
            <div class="hd2"><h2>Find people</h2><button class="chip" id="ld-import">Import{ic("down")}</button></div>
            <div class="toolbar">
              {chip("Default view", "grid", 'id="ld-view"')}{chip("Hide filters", "list", 'id="ld-hide"')}
              <div class="fsearch">{ic("search")}<input class="field2" id="ld-q" placeholder="Search people" aria-label="Search people"></div>
              {chip("Research with AI", "spark", 'id="ld-ai"')}{chip("Save search", None, 'id="ld-savesearch" title="Keep these filters to run again later"')}
              <span class="sp"></span>{select(["Relevance", "Newest", "Company A–Z"], "Sort", 'id="ld-sort"')}{chip("Search settings", "sliders", 'id="ld-settings"')}
            </div>
            <div class="split2">
              <div class="filt">
                <div class="stats3" id="ld-stats"><div class="on" data-s="total">Total<b>0</b></div><div data-s="new">Net New<b>0</b></div><div data-s="saved">Saved<b>0</b></div></div>
                {acc("Job title", '<input class="field2" id="ld-title" placeholder="Add a job title" aria-label="Job title"><label><input type="checkbox" class="ck" id="ld-sim" checked> Include similar titles</label>')}
                {acc("Seniority")}{acc("Current company")}
                {acc("Location", '<input class="field2" id="ld-loc" placeholder="Add a country, region or city" aria-label="Location">')}
                {acc("Industry")}{acc("Contact CSV Import")}{acc("Account CSV Import")}
                <div class="fbtns">{light("More filters (12)", None, 'id="ld-more"')}{dark("Find new people", attrs='id="ld-find"')}</div>
              </div>
              <div class="res" id="ld-res"></div>
            </div>
          </div>
          <div id="ld-other" class="ldo" hidden></div>
        </div>
      </div>"""
    page("leads.html", "Leads & Outreach", "leads.html", "leads", body, full=True)


# ── WhatsApp ─────────────────────────────────────────────────────────────
def build_whatsapp():
    tabs = "".join(f'<button class="{"on" if t == "Inbox" else ""}">{t}</button>' for t in
                   ["Inbox", "Contacts", "Templates", "Campaigns", "Automations", "Ads", "Shop", "Forms", "Analytics", "Settings"])
    body = phead("WhatsApp", "Every conversation, contact and broadcast on your WhatsApp number.",
                 light("AI tools", "grid", 'id="wa-ai"') + light("New campaign", "plus", 'id="wa-camp"')) + f"""
      <div class="pbody">
        <div class="tabs-strip"><div class="utabs" id="wa-tabs" style="border:0">{tabs}<span class="sp"></span><span class="chipm wait" id="wa-status">Connecting…</span></div></div>
        <div class="wa" id="wa-inbox">
          <div class="card list">
            <div class="pseg dark sm" id="wa-live" style="align-self:flex-start"><button class="on">Live</button><button>History</button></div>
            <div class="line">{select(["All chats", "Unread"], "Which chats", 'id="wa-filter"')}{chip("Filters", "sliders", 'id="wa-filters"')}</div>
            <div class="fsearch">{ic("search")}<input class="field2" id="wa-q" placeholder="Search conversations" aria-label="Search conversations"></div>
            <div class="chatlist" id="wa-list"></div>
          </div>
          <div class="card chatpane" id="wa-pane"><div class="blank"><div><span class="ftile">{ic("chat")}</span><h2>Pick a conversation</h2>
            <p>Choose someone on the left to read the chat and reply.</p></div></div></div>
        </div>
        <div id="wa-other" class="waother" hidden></div>
      </div>"""
    page("whatsapp.html", "WhatsApp", "whatsapp.html", "whatsapp", body, full=True)


# ── Home, with Reel / Studio and Motion Graphics (Home-only add-ons) ─────
def video_dialog(mid, title, sub, q, ph, choice, utils, make):
    body = f"""      <h3>{q}</h3>
      <textarea class="ta ask" placeholder="{ph_attr(ph)}" aria-label="{esc(q)}"></textarea>
      {ASK_CHIPS}
      {choice}
      <div class="out js-out">The scenes will be listed here once written.</div>"""
    foot = "".join(light(l, i, off(w)) for l, i, w in utils) + '<span class="sp"></span>' + light("Close", None, "data-close") + dark(make, cls="js-make")
    return modal(mid, "video", title, sub, body, foot)


def build_home():
    h = part("home.html")
    tiles = [("inquiry.html", "inbox", "Email Inquiry"), ("boq.html", "sheet", "BOQ"), ("gerber.html", "chip", "Gerber"),
             ("step.html", "cube", "STEP"), ("bom.html", "box", "BOM &amp; Stock"), ("email.html", "mail", "Email"),
             ("leads.html", "user", "Leads"), ("whatsapp.html", "chat", "WhatsApp"), ("#reel", "film", "Reel / Studio"), ("#motion", "video", "Motion")]
    grid = "".join(f'<a class="ad" href="{u}"><span class="tile">{ic(i)}</span><b>{l}</b><span class="rd">Ready</span></a>' for u, i, l in tiles)
    h = re.sub(r'<div class="adgrid">.*?</div>\n          </div>', f'<div class="adgrid">{grid}</div>\n          </div>', h, flags=re.S)
    h = re.sub(r'<ul class="acts">.*?</ul>', '<ul class="acts" id="h-acts"></ul>', h, flags=re.S)
    reps = [
        ('<textarea placeholder="What can I take care of today?" aria-label="Describe a task"></textarea>',
         '<textarea id="task" placeholder="What can I take care of today?" aria-label="Describe a task"></textarea>\n            <div class="att" id="h-att"></div>'),
        ('<button class="chip"><svg class="i"><use href="#i-clip"/></svg>Attach</button>', '<button class="chip" id="h-attach"><svg class="i"><use href="#i-clip"/></svg>Attach</button>'),
        ('<button class="chip"><svg class="i"><use href="#i-cmd"/></svg>Commands</button>', '<button class="chip" id="h-commands"><svg class="i"><use href="#i-cmd"/></svg>Commands</button>'),
        ('<button class="chip"><svg class="i"><use href="#i-grid"/></svg>Tools</button>', '<button class="chip" id="h-tools"><svg class="i"><use href="#i-grid"/></svg>Tools</button>'),
        ('<button class="send" title="Make a plan">', '<button class="send" id="h-send" title="Make a plan">'),
        ('<button class="chip"><svg class="i"><use href="#i-file"/></svg>Summarize a PDF</button>', '<button class="chip" id="try-pdf"><svg class="i"><use href="#i-file"/></svg>Summarize a PDF</button>'),
        ('<button class="chip"><svg class="i"><use href="#i-film"/></svg>Create a reel</button>', f'<a class="chip" href="#reel">{ic("film")}Create a reel</a>'),
        ('<button class="chip"><svg class="i"><use href="#i-bars"/></svg>Analyze this BOQ</button>', '<button class="chip" id="try-boq"><svg class="i"><use href="#i-bars"/></svg>Analyze this BOQ</button>'),
        ('<button class="chip"><svg class="i"><use href="#i-spark"/></svg>Clean up artifacts</button>', '<button class="chip" id="try-clean"><svg class="i"><use href="#i-spark"/></svg>Clean up artifacts</button>'),
        ('<span class="pill">01:03 ›</span>', '<button class="pill" id="h-time" title="Play the 1-minute demo">01:03 ›</button>'),
        ('<button class="btn light sm">', '<button class="btn light sm" id="h-demo">'),
        ('<button class="link" data-go="history">See all <svg class="i"><use href="#i-arrow"/></svg></button>', f'<a class="link" href="history.html">See all {ic("arrow")}</a>'),
        ('<button class="btn light plain sm">Manage</button>', '<a class="btn light plain sm" href="settings.html#licence">Manage</a>'),
    ]
    for a, b in reps:
        assert a in h, a[:50]
        h = h.replace(a, b, 1)
    reel = video_dialog(
        "reel", "Make a Reel", "A finished 9:16 video, drawn frame by frame on this machine. No watermark and no daily cap.",
        "What should the reel be about?",
        'Just say it — for example:&#10;"a reel describing what we sell at Raj Infotech"&#10;&#10;Attach a logo for branding, or client .MOV/.MP4 clips to edit into one vertical reel.',
        """<div class="choice"><div class="label">How it is made</div>
        <label class="opt"><input type="radio" class="rd2" name="how" checked><span>Studio — designed for this client. A web page, filmed. Takes a few minutes.</span></label>
        <label class="opt"><input type="radio" class="rd2" name="how"><span>Quick — drawn from templates. Same look every time, ready in under a minute.</span></label>
        <label class="opt"><input type="radio" class="rd2" name="how"><span>Edit client footage — dynamic motion graphics captions, cinematic transitions, and ducked audio. The video stays local.</span></label></div>""",
        [("Edit the layout", "pencil", "Open the reel in your browser: drag anything into place, resize it, retype it or delete it, then render again. Studio reels only. Make a reel first."),
         ("Play", "play", "Make a reel first"), ("Show file", "folder", "Make a reel first")], "Make my reel")
    motion = video_dialog(
        "motion", "Make a Motion Graphic", "A scene-graph video with a real camera — charts, diagrams and UI mockups, drawn frame by frame on this machine.",
        "What should the motion graphic show?",
        'Just say it — for example:&#10;"an animated architecture diagram of our distributed crawler"&#10;&#10;Attach a logo or business card and the brand colours are taken straight from it.',
        "", [("Edit in Studio", "pencil", "Open the motion graphic in your browser: scenes, continuity threads, camera shots, glass and handoffs, with start, midpoint, settled and exit previews of every shot. Make one first."),
             ("Play", "play", "Make a motion graphic first"), ("Show file", "folder", "Make a motion graphic first")], "Make my motion graphic")
    page("index.html", "Home", "index.html", "home", h, reel + motion)


def build_core():
    hist = phead("History", "Every past run, re-rendered out of its stored record.",
                 light("Clear all", "trash", 'id="hist-clear"', cls="danger")
                 + '<a class="btn dark sm" href="index.html#new"><span class="ic"><svg><use href="#pplus"/></svg></span>New task</a>') + f"""
      <div class="pbody">
        <div class="card search">
          <div class="field">{ic("search")}<input id="hist-q" placeholder="Search a task, or a tool that ran it" aria-label="Search history"></div>
          <span class="count" id="hist-count"></span>
        </div>
        <div class="seg" role="tablist">
          <button class="on" data-f="all">All <span class="n"></span></button>
          <button data-f="ok">Completed <span class="n"></span></button>
          <button data-f="err">Failed <span class="n"></span></button>
          <button data-f="never">Never ran <span class="n"></span></button>
        </div>
        <div class="selbar" id="hist-sel" hidden><b></b><span class="sp"></span>{light("Select none", None, 'id="hist-sel-none"')}{light("Delete selected", "trash", 'id="hist-sel-del"', cls="danger")}</div>
        <div id="h-list"></div>
      </div>"""
    page("history.html", "History", "history.html", "history", hist)
    art = part("artifacts.html")
    empty = art[art.index('<div class="card empty">'):art.rindex("</div>")]
    art_body = phead("Artifacts", "Everything Prism has generated for you (reels, images, documents), kept here even after you close it.",
                     light("Open the folder", "folder", 'id="art-folder"')) + f"""
      <div class="pbody"><div id="art-list"></div><template id="art-empty">{empty}</template></div>"""
    page("artifacts.html", "Artifacts", "artifacts.html", "artifacts", art_body)
    s = re.sub(r'<button class="iconbtn" data-go="dashboard"[^>]*>(.*?)</button>',
               r'<a class="iconbtn" href="index.html" title="Close settings" style="box-shadow:inset 0 0 0 1px var(--line2);width:2.6rem;height:2.6rem">\1</a>',
               part("settings.html"), flags=re.S)
    s = s.replace('<button class="btn light plain sm">Request a meeting</button>', '<button class="btn light plain sm" id="s-meeting">Request a meeting</button>')
    page("settings.html", "Settings", "", "settings", s, full=True, sid="s-settings")


if __name__ == "__main__":
    build_home()
    build_core()
    build_inquiry()
    build_boq()
    build_gerber()
    build_step()
    build_email()
    build_leads()
    build_whatsapp()
    build_bom()
