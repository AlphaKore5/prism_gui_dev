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
| `boq.html`, `bom.html` | Front page, plus the Bill of Quantities / Materials dialog (`#make`). |
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

## BOQ / BOM: four easy steps for people who have never used AI

`boq.html` and `bom.html` open a step-by-step helper instead of one dense dialog:
**1 What you have → 2 Check the count → 3 Make the BOQ → 4 Add prices**.
It uses everyday words, has one main button per step, and asks only about the items that need a person.

It follows Hitarth's rules in `BOQ-CHANGES-TODO.md` (item numbers):

- **Item 10:** prices come after the BOQ exists.
- **Item 8:** "From the count" and "With the drawing" are both offered before any BOQ exists.
- **Items 12b and 26:** HVAC rules and the PDF take-off switch on only when the request says HVAC.
- **Item 13:** red means a person must check; yellow means worth a look.
- **Item 18:** pasted measurements still need the request line.
- **Items 2 and 22:** the progress window has Stop and Use another AI.
- **Item 4:** each change is saved as a new file (v2, v3…).
- **Item 32:** Prism asks permission every time the drawing would leave the computer.
- **Item 30:** research is off by default.
- **Item 9:** the sample template is kept separate from the drawing.

Every expert control is still there: Settings for experts, the full measured table, Input measurements, PDF take-off, History and file formats.

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
