# Prism × AlphaKore — UI preview

A clickable HTML preview of the Prism desktop app restyled in AlphaKore's brand
(the same colours, fonts and controls as [alphakore.org](https://www.alphakore.org)),
so Prism reads as part of one product family.

**This is a design preview, not app code.** Nothing here is imported by the app or
packaged into a build.

## Open it

Open `index.html` in Chrome, Edge or Safari. No server is needed. Every page links to
the others through the sidebar.

| Page | What it shows |
|---|---|
| `index.html` | Home: composer, Try chips, demo, Recent activity, Add-ons. Reel / Studio and Motion Graphics open from here (`#reel`, `#motion`). |
| `history.html` | Every past run: search, filters, select and delete, open a run to see its answer. |
| `artifacts.html` | Generated files by day; open any of them. |
| `settings.html` | All eight sections: Licence, Profile, Agents, Language, Connections, Appearance, Privacy & data, Help & contact. |
| `inquiry.html` | Email inquiries front page, plus the pipeline (`#pipeline`): quote, remind, record the order. |
| `boq.html` | Drop-in BOQ: counted table, items to check, prices, changes. See the BOQ section below. |
| `boq-steps.html`, `bom.html` | Step-by-step BOQ, and BOM (same steps). |
| `gerber.html` | Front page, plus the Gerber dialog. |
| `step.html` | The STEP workspace: models, Draft / Ask / Edit, results. |
| `email.html` | Email Outreach, plus Send an email (`#compose`). |
| `leads.html` | Leads & Outreach: find, filter, draft and send. |
| `whatsapp.html` | WhatsApp inbox and its other tabs. |

## What is real and what is mock

- **Layout, labels, button names and dropdown options** are copied from today's app
  (`addons/*/panel.py`, `dialog.py`, `widgets/settings_panel.py`). Screens were compared
  against offscreen captures of the running app.
- **Data is mock** (`mock.js`): one invented customer, Kinetic Springs, Vadodara, with
  invented inquiries, people, chats and files. Every button works against this data. Things
  the browser can't do, such as opening a folder or sending a mail, show a short message
  saying what the app would do.
- **Brand assets:** the fonts (Doto, Geist, Geist Mono) are bundled in `fonts/`. The AK
  mark, the Prism crystal, the Prism painting and the two videos in `media/` come from
  alphakore.org.

## BOQ (for Hitarth and anyone checking it)

Two versions of the same BOQ, for comparison:

- **`boq.html` is the drop-in version** (the one we recommend).
  - Drop a drawing, or describe the job.
  - Prism counts it and shows a live, editable table.
  - Only the doubtful items are pinned on top ("2 left to check").
  - Prices are a column. Changes are one box at the bottom.
  - "Try a sample drawing" shows the whole thing with no file.
- **`boq-steps.html` is the step-by-step version:** What you have → Check the count → Make the BOQ → Add prices.

**Try this, in order (5 minutes):**
1. Open `boq.html`. Click **Try a sample drawing**. You'll be asked your industry once. Pick HVAC.
2. Look at "2 left to check". Press **Yes, it's right** on one and **Change the number** on the other.
3. Click **Typical prices**, then change one price in the table.
4. Type a change at the bottom ("Split it floor by floor") and press **Change it**. It's saved as version 2.
5. Click **New BOQ**. The finished one is now under "Continue where you left off". Try **Change it** and **Continue** there.
6. Click the **Industry** chip and pick **Other**. It asks for a few words and says Prism uses general rules.
7. Drop a PDF with Industry = HVAC. The two-step HVAC window opens. Compare it with `boq-steps.html`.

**Your rules, and where they show up** (item numbers from `BOQ-CHANGES-TODO.md`):

| Rule | In the preview |
|---|---|
| Industry is an explicit choice, never guessed from the file (26) | Asked once, remembered. HVAC rules and the PDF takeoff run only when Industry = HVAC. |
| Prices come after the BOQ exists (10) | The price column is empty until a BOQ exists. |
| Drawing never leaves without asking (8, 32) | "Double-check my BOQ" asks first, every time. |
| Red = must check, yellow = worth a look (13) | The pinned cards and the Check / Look tags. |
| A follow-up is a new file (4) | v2, v3… in the title and file name. |
| A sample BOQ shapes the look, not the numbers (9) | The Format chip says "the look only". |
| Layer colours remembered between tenders (34), per-layer preview (33) | In the HVAC window. |

**Three changes that need your decision.** They are in the preview but not in the real code:
1. Remember the industry for the company.
2. Let a customer add their own industry ("Other"), with no rule-set.
3. Remember a BOQ format per industry.

Open **More settings** under the table. "What Prism tells the writer" lists what would feed the prompt: industry, rules, format, drawing.

## Brand tokens

| Token | Value | Use |
|---|---|---|
| Background | `#EEEDEA` | warm stone canvas |
| Ink | `#111110` | text, primary buttons |
| Mute | `#6B6A65` | secondary text (the site's `#8C8B86` is too light for 4.5:1) |
| Accent | `#C8161D` | brand marks only: label squares, the dot on primary buttons |
| OK / Error | `#1F6B43` on `#E4EFE7` · `#A3141A` on `#F7E3E1` | status, always with a word |
| Display font | Doto | the name on Home only |
| Text font | Geist | everything else |
| Label font | Geist Mono | uppercase labels, numbers, status pills |

## Editing

Pages are generated: change `_generator/build.py` (layout), `style.css` (look),
`app.js` (behaviour) or `mock.js` (data), then run

    python3 _generator/build.py

from this folder. `_shots/` has screenshots of each screen at 1366 × 768.
