# Prism Engineering: real-machine checklist (E4)

Nothing here can be proven on the Linux dev machine. Run it on a real Windows
x64 machine first, then macOS, on a build made with the Engineering flavour
(the bundle must contain boq, bom, step, gerber and NOT inquiry, leads,
whatsapp, email, reel, motion). Windows and macOS runs go through Harsh.
Use a throwaway Windows user / HOME: never an account with a real `~/.prism`.
Files: use your own drawings. Do not commit real customer files.

Record for each line: machine, OS, Prism version, PASS/FAIL, screenshot.

## 0. The build
- [ ] Launch: opens with the Engineering rail only (BOQ, Gerber, STEP; BOM is registered but switched off).
- [ ] No Leads / Inquiry / Email / WhatsApp / Reel / Motion on the rail or Home.
- [ ] Self-test (`PRISM_SELFTEST=1`) passes and lists BOQ, STEP, Gerber checks only (no Reel/Motion/FFmpeg).
- [ ] Ask Prism for "find leads": it says that tool isn't in this version and names Prism Sales.

## 1. AI with a licence key only
- [ ] Sign in with a licence key (no Groq/OpenRouter keys on the machine): a plain question gets an answer.
- [ ] Offline: a clear message, no traceback.

## 2. DXF
- [ ] Open a real DXF (units set): layers listed, units asked/confirmed, lengths/areas/blocks counted.
- [ ] A DXF with text entities, blocks and a closed polyline: counts match a manual count.

## 3. DWG (ODA auto-install stays OFF)
- [ ] Open a real DWG with no converter installed: the "install / choose / use DXF" window appears, nothing downloads by itself.
- [ ] Bundled LibreDWG path: the DWG converts and measures (Windows, then macOS).
- [ ] Choose-a-converter path works if ODA File Converter is installed manually.

## 4. BOQ end to end
- [ ] Drawing -> measured -> price from own rate list (Excel) -> export xlsx, csv, pdf (PDF needs the bundled Chromium).
- [ ] Config with no `inquiry` section: pricing still works.
- [ ] History lists the run; Resume works.

## 5. STEP
- [ ] Open a real STEP file; ask a question; produce an edit plan; the conversation shows in History.

## 6. Gerber
- [ ] Load a real Gerber zip: layers, board outline and size, clean-up, report/export.

## 7. History read-only
- [ ] Copy a saved Leads/Email run into the runs folder: it opens read-only with the "opens in Prism Sales" note and no follow-up button.

## 8. Update
- [ ] In-app update from the previous Engineering build offers and applies this one.
