/* Mock data for the preview. One fictional customer of Prism — Kinetic Springs, Vadodara —
   so the same companies show up in Inquiries, Leads, WhatsApp, History and Artifacts.
   Every name, number and address here is invented. */
var MOCK = {
  company: "Kinetic Springs Pvt Ltd",
  me: { name: "Parth", email: "sales@kineticsprings.in" },

  /* files the mock picker offers ("Desktop") */
  files: {
    drawing: [["Sargam-Tower-B-HVAC.dxf", "Drawing · 2.4 MB"], ["Magnetic-separator-GA.pdf", "Drawing · 1.1 MB"], ["Site-CCTV-layout.dxf", "Drawing · 860 KB"]],
    sample: [["Our BOQ template.xlsx", "Sample template · 38 KB"], ["Vraj Infra old BOQ.xlsx", "Sample template · 52 KB"]],
    gerber: [["controller-rev-c.zip", "Gerber archive · 1.8 MB"], ["power-board-v2.rar", "Gerber archive · 2.6 MB"]],
    step: [["mounting-bracket.step", "3D model · 640 KB"], ["pump-housing.stp", "3D model · 3.2 MB"]],
    doc: [["Kirloskar price list.pdf", "PDF · 1.3 MB"], ["Customer inquiry mail.pdf", "PDF · 220 KB"], ["Rate sheet Nov.xlsx", "Sheet · 64 KB"]],
    media: [["kinetic-logo.png", "Image · 120 KB"], ["factory-floor.mov", "Video · 48 MB"], ["visiting-card.jpg", "Image · 340 KB"]],
    csv: [["HVAC contractors Gujarat.csv", "24 people"], ["Pump OEM buyers.csv", "11 people"]]
  },

  /* History (also feeds Home's Recent activity) */
  runs: [
    { id: "r1", day: "Today", when: "10:42", title: "BOQ for HVAC ductwork, Sargam Tower B — must include size and quantity", tool: "BOQ", by: "Prism Agent Claude", status: "ok", out: "boq", icon: "sheet" },
    { id: "r2", day: "Today", when: "10:05", title: "Edit: make the holes 0.05mm larger", tool: "STEP", by: "Measured here", status: "ok", out: "step", icon: "cube" },
    { id: "r3", day: "Today", when: "09:31", title: "Reply with our price for 500 pieces — controller-rev-c", tool: "Gerber", by: "Prism Agent Claude", status: "ok", out: "gerber", icon: "chip" },
    { id: "r4", day: "Today", when: "09:02", title: "A reel describing what we sell at Raj Infotech", tool: "Reel", by: "Prism Studio", status: "ok", out: "reel", icon: "film" },
    { id: "r5", day: "Today", when: "08:40", title: "ETH Global Hackathon Research Overview", tool: "", by: "Perplexity", status: "err", out: "err", icon: "file",
      err: "Perplexity did not answer within 4 minutes, so the run stopped. Nothing was saved." },
    { id: "r6", day: "Yesterday", when: "17:20", title: "Parts list to fabricate this over-band magnetic separator", tool: "BOM", by: "Prism Agent Claude", status: "ok", out: "bom", icon: "box" },
    { id: "r7", day: "Yesterday", when: "15:02", title: "Summarize the attached supplier PDF — Kirloskar price list", tool: "", by: "ChatGPT", status: "ok", out: "text", icon: "file" },
    { id: "r8", day: "Yesterday", when: "11:15", title: "Quotation for Shree Ambica Engineering — INQ-0142", tool: "Inquiry", by: "Prism Agent Claude", status: "ok", out: "quote", icon: "inbox" },
    { id: "r9", day: "Yesterday", when: "10:00", title: "Follow-up emails to 12 HVAC contractors", tool: "Email", by: "", status: "never", out: "never", icon: "mail" }
  ],

  /* Artifacts, grouped by day as the app does */
  artifacts: [
    { day: "Today", name: "BOQ — Sargam Tower B HVAC.xlsx", kind: "sheet", size: "48 KB", out: "boq" },
    { day: "Today", name: "mounting-bracket-sheet.pdf", kind: "pdf", size: "312 KB", out: "drawing" },
    { day: "Today", name: "mounting-bracket-render.png", kind: "image", size: "186 KB", out: "render" },
    { day: "Today", name: "controller-rev-c check sheet.xlsx", kind: "sheet", size: "18 KB", out: "gerber" },
    { day: "Today", name: "Raj Infotech reel.mp4", kind: "video", size: "4.2 MB", out: "reel", thumb: "media/reel-poster.jpg" },
    { day: "Yesterday", name: "BOM — over-band magnetic separator.csv", kind: "sheet", size: "21 KB", out: "bom" },
    { day: "Yesterday", name: "Quotation INQ-0142 — Shree Ambica.pdf", kind: "pdf", size: "96 KB", out: "quote" },
    { day: "Yesterday", name: "Kirloskar price list — summary.docx", kind: "doc", size: "34 KB", out: "text" },
    { day: "Earlier this week", name: "Prism explainer.mp4", kind: "video", size: "6.8 MB", out: "motion", thumb: "media/prism-story-poster.jpg" }
  ],

  /* BOQ (Rate and Amount stay blank on purpose: Prism counts, you price) */
  boq: [["Ductwork"], ["GI rectangular duct, 0.63 mm (24 G)", "642.5", "m²"], ["GI rectangular duct, 0.80 mm (22 G)", "418.2", "m²"], ["Bends, offsets and shoes", "52", "nos"],
        ["Dampers"], ["Volume control damper, 300 × 200", "18", "nos"], ["Fire damper, 90 min, 400 × 300", "8", "nos"],
        ["Air terminals"], ["Supply grille with VCD, 450 × 150", "64", "nos"], ["Return air grille, 600 × 300", "22", "nos"],
        ["Insulation"], ["Nitrile rubber, 13 mm, on supply duct", "642.5", "m²"]],
  bom: [["Plates — IS 2062 E250"], ["Side plate, 12 mm", "2", "nos", "1,850 × 920", "321.4 kg"], ["Base plate, 16 mm", "1", "nos", "2,100 × 1,200", "316.5 kg"],
        ["Gussets, 10 mm", "8", "nos", "250 × 250", "39.3 kg"], ["Sections"], ["ISMC 150 channel", "4", "nos", "2,400 mm", "157.4 kg"],
        ["ISA 65 × 65 × 6 angle", "6", "nos", "1,100 mm", "38.9 kg"], ["Hardware"], ["Hex bolt M16 × 60, grade 8.8", "48", "nos", "—", "—"]],
  gerber: [["Copper layers", "4"], ["PCB size", [86.4, 54.2]], ["Array size", "not an array (single board)"], ["PCBs in the array", "1"],
           ["Min track width", 0.152], ["Min track spacing", 0.127, "3 places on the board are this tight"], ["Min drill size", 0.30],
           ["Number of drills", "412"], ["Min pad pitch", 0.50], ["Min SMT pad", [0.30, 0.25], "on Top copper"]],
  step: [["sec", "Part · not measured by an AI"], ["Mode", "Sheet metal"], ["Overall size", "240.0 × 120.0 × 45.0 mm"], ["Parts", "2"],
         ["sec", "Mounting bracket"], ["Size", "240.0 × 120.0 × 45.0 mm"], ["Thickness / wall", "3 mm"], ["Volume", "118.40 cm³"], ["Weight (mild steel)", "929 g"],
         ["Flat size", "240.0 × 204.6 mm"], ["Holes", "Ø8.5 ×4 · Ø6.5 ×2"], ["sec", "Gusset"], ["Size", "60.0 × 40.0 × 3.0 mm"], ["Volume", "3.60 cm³"],
         ["sec", "Bend allowance"], ["K-factor", "0.44"], ["warn", "Thickness is an estimate (2 × volume / surface area)."]],

  /* Email inquiry register */
  inquiries: [
    { no: "INQ-0147", who: "Shree Ambica Engineering", contact: "Mehul Shah", email: "mehul@shreeambica.in", asked: "RFQ: 200 nos MS brackets as per drawing", got: "Today 09:12", stage: "quote", files: ["bracket-rev2.pdf", "spec-sheet.xlsx"],
      mail: "Dear Sir, please quote for 200 nos MS brackets as per the attached drawing, 3 mm, powder coated. Delivery required within 3 weeks at our Anand plant." },
    { no: "INQ-0146", who: "Patel Fabricators", contact: "Harsh Patel", email: "purchase@patelfab.in", asked: "Enquiry for SS304 hopper, 1 no", got: "Today 08:40", stage: "quote", files: ["hopper-GA.dxf"],
      mail: "Hello, we need one SS304 hopper as per GA drawing. Kindly send your best price with GST and delivery period." },
    { no: "INQ-0145", who: "Kalpataru Pumps", contact: "Priya Nair", email: "priya.nair@kalpatarupumps.in", asked: "Quote required — impeller castings, 3 sizes", got: "Yesterday 16:05", stage: "quote", files: ["impellers.pdf"],
      mail: "Please quote for CI impeller castings in three sizes (150, 200, 250 mm). Monthly requirement 40 nos each." },
    { no: "INQ-0143", who: "Vraj Infra", contact: "Rakesh Mehta", email: "rakesh@vrajinfra.com", asked: "GI duct work — Sargam Tower B", got: "Mon 11:20", stage: "wait", value: "₹14,67,000", due: true, files: ["Sargam-Tower-B-HVAC.dxf"],
      mail: "Please quote for GI ductwork, dampers and grilles as per the HVAC layout of Sargam Tower B." },
    { no: "INQ-0141", who: "Neelkanth Polymers", contact: "Farhan Shaikh", email: "maintenance@neelkanthpoly.in", asked: "Spring set for extruder, 12 types", got: "Mon 09:05", stage: "wait", value: "₹2,85,000", files: [],
      mail: "Need compression springs for our extruder line, 12 types, list attached." },
    { no: "INQ-0137", who: "Rudra Steel Works", contact: "Vikram Rao", email: "vikram@rudrasteel.in", asked: "Leaf springs, 50 sets", got: "Last Thu", stage: "wait", value: "₹96,500", files: [],
      mail: "Please send rate for 50 sets of leaf springs as per sample." },
    { no: "INQ-0140", who: "Aarav Automation", contact: "Kavita Iyer", email: "kavita@aaravautomation.com", asked: "Torsion springs, 1,000 nos", got: "Last Wed", stage: "answered", value: "₹2,10,000", files: [],
      mail: "Thanks for the quotation.", answer: "Thanks for the quotation. Can you do ₹1,950 per hundred if we confirm 1,000 nos this week?" },
    { no: "INQ-0138", who: "Gujarat Conveyors", contact: "Anil Desai", email: "anil.desai@gujaratconveyors.com", asked: "Return idler springs, 400 nos", got: "Last Tue", stage: "order", value: "₹6,40,000", po: "PO-7781", files: ["PO-7781.pdf"],
      mail: "Please find our PO attached. Kindly confirm the delivery date." }
  ],
  quoteLines: [["MS bracket, 3 mm, powder coated, as per drawing bracket-rev2", "200", "nos", "₹186", "₹37,200"], ["Packing and forwarding", "1", "lot", "₹1,500", "₹1,500"],
               ["GST 18%", "", "", "", "₹6,966"], ["Total", "", "", "", "₹45,666"]],

  /* Leads */
  people: [
    ["Rakesh Mehta", "Purchase Manager", "Vraj Infra Pvt Ltd", "Ahmedabad", "Verified", 1],
    ["Priya Nair", "Head of Procurement", "Kalpataru Pumps", "Pune", "Verified", 1],
    ["Anil Desai", "Plant Head", "Gujarat Conveyors", "Vadodara", "Verified", 1],
    ["Sneha Joshi", "Project Engineer — HVAC", "Sargam Builders", "Surat", "Risky", 0],
    ["Vikram Rao", "Director", "Rudra Steel Works", "Rajkot", "Verified", 1],
    ["Farhan Shaikh", "Maintenance Manager", "Neelkanth Polymers", "Halol", "Verified", 0],
    ["Kavita Iyer", "Sourcing Lead", "Aarav Automation", "Bengaluru", "Verified", 0],
    ["Harsh Patel", "Purchase Executive", "Patel Fabricators", "Vadodara", "Risky", 0],
    ["Deepak Kulkarni", "VP Operations", "Sahyadri Castings", "Kolhapur", "Verified", 0],
    ["Meera Shah", "Procurement Manager", "Shree Ambica Engineering", "Anand", "Verified", 0],
    ["Rohan Gupta", "Founder", "CoolAir HVAC Solutions", "Mumbai", "Verified", 0],
    ["Nisha Verma", "Category Manager — MRO", "Indus Projects", "Hyderabad", "Risky", 0]
  ],
  morePeople: [
    ["Amit Trivedi", "Purchase Head", "Shiv Shakti Pumps", "Rajkot", "Verified", 0],
    ["Pooja Bhatt", "Buyer — Springs & Fasteners", "Atlas Auto Components", "Pune", "Verified", 0],
    ["Sanjay Menon", "Plant Manager", "Western Valves", "Vadodara", "Verified", 0],
    ["Ritu Agarwal", "Sourcing Manager", "Bharat Agro Machines", "Indore", "Risky", 0],
    ["Karan Malhotra", "Director", "Malhotra Engineering", "Ludhiana", "Verified", 0],
    ["Ishita Rao", "Procurement Lead", "Sunrise Elevators", "Chennai", "Verified", 0]
  ],

  /* WhatsApp */
  chats: [
    { name: "Mehul Shah", org: "Shree Ambica Engineering", num: "+91 98250 41xxx", time: "10:41", unread: 2, tag: "Inquiry",
      msgs: [["in", "Good morning sir", "10:38"], ["in", "Drawing bhej diya hai mail pe. Rate kab tak milega?", "10:41"]] },
    { name: "Priya Nair", org: "Kalpataru Pumps", num: "+91 99099 12xxx", time: "10:12", unread: 0, tag: "Customer",
      msgs: [["out", "Quotation for the impeller castings is on mail, ma'am.", "09:50"], ["in", "Please share the revised quotation with GST.", "10:12"]] },
    { name: "Anil Desai", org: "Gujarat Conveyors", num: "+91 97277 30xxx", time: "09:55", unread: 1, tag: "Order",
      msgs: [["in", "PO attached. Please confirm the delivery date.", "09:55"]] },
    { name: "Raj Infotech", org: "Raj Infotech", num: "+91 90990 55xxx", time: "09:20", unread: 0, tag: "Customer",
      msgs: [["out", "Here is the reel we made for you.", "09:05"], ["in", "The reel looks great. Can we get a square version too?", "09:20"]] },
    { name: "Vikram Rao", org: "Rudra Steel Works", num: "+91 98980 77xxx", time: "Yesterday", unread: 0, tag: "Customer",
      msgs: [["in", "Call me after 4, will discuss the leaf spring rate.", "Yesterday"]] },
    { name: "Farhan Shaikh", org: "Neelkanth Polymers", num: "+91 93274 18xxx", time: "Yesterday", unread: 0, tag: "Customer",
      msgs: [["out", "Quotation sent for the 12 spring types.", "Yesterday"], ["in", "Thanks, received.", "Yesterday"]] },
    { name: "Kavita Iyer", org: "Aarav Automation", num: "+91 96011 84xxx", time: "Mon", unread: 0, tag: "Negotiating",
      msgs: [["in", "Can you do ₹1,950 per hundred if we confirm this week?", "Mon"]] }
  ],

  /* Email Outreach sent log */
  sent: [
    ["rakesh@vrajinfra.com", "Reminder: quotation for GI ductwork, Sargam Tower B", "Today 10:30", "Sent"],
    ["anil.desai@gujaratconveyors.com", "Delivery date for PO-7781", "Today 10:02", "Sent"],
    ["priya.nair@kalpatarupumps.in", "Revised quotation with GST — impeller castings", "Yesterday 16:40", "Sent"],
    ["info@coolairhvac.in", "Springs and wire forms for HVAC dampers", "Yesterday 12:15", "Bounced"],
    ["kavita@aaravautomation.com", "Torsion springs — our best rate", "Mon 18:05", "Sent"]
  ],

  /* Lumi, Prism's helper: a few canned answers */
  lumi: [
    [/boq|quantit/i, "Open BOQ from the sidebar, attach the drawing and press Make my BOQ. The quantities are measured on this computer; the Rate and Amount columns stay blank for you to price."],
    [/reel|video/i, "Click Create a reel on Home. Studio makes a designed reel in a few minutes; Quick uses templates and is ready in under a minute."],
    [/licen|plan|seat/i, "Your copy is on Prism Complete with 2 seats, renewing on 01 September 2027. Settings → Licence has the details."],
    [/mail|inquir/i, "Email Inquiries reads your inbox, numbers every inquiry and keeps the register. Press Check my mail now to run it."],
    [/.*/, "I can help with BOQ, Gerber, STEP, inquiries, reels and settings. Try asking \"how do I make a BOQ?\""]
  ]
};

/* BOQ / BOM working data (shapes follow addons/boq/measured.py and pricing.py) */
MOCK.measured = {
  boq: [ // [trust, section, item, measured as, layer, value (m / m² / nos), kind]
    ["ok", "Ductwork", "Supply duct 600 × 300", "length", "M-DUCT-SUPPLY-600x300", 186.4, "len"],
    ["ok", "Ductwork", "Supply duct 450 × 250", "length", "M-DUCT-SUPPLY-450x250", 142.8, "len"],
    ["warn", "Ductwork", "Return duct 500 × 300", "length", "M-DUCT-RETURN", 98.2, "len"],
    ["ok", "Dampers", "Volume control damper, 300 × 200", "count", "M-VCD", 18, "cnt"],
    ["bad", "Dampers", "Fire damper, 90 min, 400 × 300", "count", "M-FD", 8, "cnt"],
    ["ok", "Air terminals", "Supply grille with VCD, 450 × 150", "count", "M-GRILLE-S", 64, "cnt"],
    ["ok", "Air terminals", "Return air grille, 600 × 300", "count", "M-GRILLE-R", 22, "cnt"],
    ["ok", "Insulation", "Nitrile rubber, 13 mm, on supply duct", "area", "M-INSUL", 642.5, "area"]
  ],
  bom: [
    ["ok", "Plates — IS 2062 E250", "Side plate, 12 mm", "area", "S-PLATE-12", 3.40, "area"],
    ["ok", "Plates — IS 2062 E250", "Base plate, 16 mm", "area", "S-PLATE-16", 2.52, "area"],
    ["warn", "Plates — IS 2062 E250", "Gussets, 10 mm", "count", "S-GUSSET", 8, "cnt"],
    ["ok", "Sections", "ISMC 150 channel", "length", "S-ISMC150", 9.6, "len"],
    ["ok", "Sections", "ISA 65 × 65 × 6 angle", "length", "S-ISA65", 6.6, "len"],
    ["bad", "Hardware", "Hex bolt M16 × 60, grade 8.8", "count", "S-BOLT-M16", 48, "cnt"]
  ]
};
MOCK.warnings = {
  boq: ["M-DUCT-RETURN: paired with M-DUCT-SUPPLY-600x300 by the HVAC duct-pairing rule — worth a look before pricing.",
        "M-FD: 2 of the 8 fire-damper blocks sit outside the drawing border. Prism can't resolve this by itself — a person must check it.",
        "Look-alike layers M-GRILLE-S and M-GRILLE-SUP: same block, counted once."],
  bom: ["S-GUSSET: 2 gussets overlap on the GA view — check the count.", "S-BOLT-M16: bolts are drawn as a symbol on a remote block. A person must check the count."]
};
MOCK.allLayers = { boq: ["0", "DEFPOINTS", "A-WALL", "A-DOOR", "A-GRID", "M-DUCT-SUPPLY-600x300", "M-DUCT-SUPPLY-450x250", "M-DUCT-RETURN", "M-VCD", "M-FD", "M-GRILLE-S", "M-GRILLE-SUP", "M-GRILLE-R", "M-INSUL", "M-TEXT"],
                   bom: ["0", "S-PLATE-12", "S-PLATE-16", "S-GUSSET", "S-ISMC150", "S-ISA65", "S-BOLT-M16", "S-DIM", "S-TEXT"] };
/* rates: your rate list, and Prism's indicative starter rates (₹ per unit) */
MOCK.rates = {
  mine: { "Supply duct 600 × 300": 1420, "Supply duct 450 × 250": 1180, "Return duct 500 × 300": 1260, "Volume control damper, 300 × 200": 2200, "Supply grille with VCD, 450 × 150": 950,
          "Return air grille, 600 × 300": 1100, "Nitrile rubber, 13 mm, on supply duct": 410, "Side plate, 12 mm": 7400, "Base plate, 16 mm": 9800, "ISMC 150 channel": 1650, "ISA 65 × 65 × 6 angle": 610, "Hex bolt M16 × 60, grade 8.8": 38 },
  starter: { "Supply duct 600 × 300": 1350, "Supply duct 450 × 250": 1100, "Return duct 500 × 300": 1200, "Volume control damper, 300 × 200": 2000, "Fire damper, 90 min, 400 × 300": 6400,
             "Supply grille with VCD, 450 × 150": 900, "Return air grille, 600 × 300": 1050, "Nitrile rubber, 13 mm, on supply duct": 380, "Side plate, 12 mm": 7000, "Base plate, 16 mm": 9300,
             "Gussets, 10 mm": 450, "ISMC 150 channel": 1550, "ISA 65 × 65 × 6 angle": 580, "Hex bolt M16 × 60, grade 8.8": 35 }
};
MOCK.takeoff = {
  layers: [["Supply duct", "ductwork", 41], ["Return duct", "ductwork", 18], ["Diffuser", "terminal", 64], ["Grille", "terminal", 22], ["Damper", "damper", 26], ["Room text", "text", 112]],
  warnings: ["Page 3 has no scale bar — the scale you set was used.", "6 duct labels could not be read by OCR; their runs were measured by length only."]
};

/* Plain-language reasons for items a person should look at (BOQ wizard, for first-time users) */
MOCK.plain = {
  "M-DUCT-RETURN": "Prism matched this duct to the supply duct running next to it. Please check the length is right.",
  "M-FD": "2 of the 8 fire dampers are drawn outside the sheet border. Is 8 the right number?",
  "S-GUSSET": "Two gussets overlap in the drawing, so one may be counted twice. Is 8 the right number?",
  "S-BOLT-M16": "The bolts are drawn as one symbol, not one by one. Is 48 the right number?"
};
MOCK.examples = {
  boq: ["HVAC ductwork for Sargam Tower B", "CCTV, cabling and fibre for this site", "Materials for one 36x24 jaw crusher, 100 TPH"],
  bom: ["Parts list for this magnetic separator", "BOM for one 36x24 jaw crusher, 100 TPH"]
};

/* HVAC tender PDF pipeline (hvac_takeoff/hvac_takeoff.py + addons/boq/takeoff.py).
   Layer keys follow the tool's own "colour@weight:kind"; roles are its ROLES list. */
MOCK.hvac = {
  pdf: "Sargam-Tower-B-HVAC-tender.pdf",
  roles: [["ignore", "Ignore — not ductwork"], ["supply", "Supply duct"], ["return", "Return duct"], ["fresh_air", "Fresh air duct"], ["exhaust", "Exhaust duct"],
          ["toilet_exhaust", "Toilet exhaust"], ["kitchen_exhaust", "Kitchen exhaust"], ["smoke_extract", "Smoke extract"], ["diffuser", "Diffuser (count)"],
          ["flex_connector", "Flex connector (count)"], ["volume_damper", "Volume damper (count)"]],
  // [key, colour, kind, segments, length ft, remembered role ("" = new)]
  layers: [["#000000@1.56:line", "#000000", "line", 1240, 1912, "supply"], ["#000000@1.56:poly", "#000000", "poly", 386, 604, "supply"],
           ["#ff0000@1.08:line", "#ff0000", "line", 512, 822, ""], ["#ff0000@1.08:poly", "#ff0000", "poly", 140, 231, ""],
           ["#0000ff@0.72:rect", "#0000ff", "rect", 760, 0, "diffuser"], ["#00a651@0.72:rect", "#00a651", "rect", 96, 0, ""],
           ["#808080@0.00:poly", "#808080", "poly", 289, 2440, "ignore"], ["#000000@0.25:rect", "#000000", "rect", 2220, 0, "ignore"],
           ["#ff7f00@0.50:line", "#ff7f00", "line", 66, 118, ""]],
  summary: [["Supply", "600 × 300", 412], ["Supply", "450 × 250", 318], ["Supply", "300 × 200", 226], ["Return", "500 × 300", 241], ["Return", "350 × 250", 152], ["Fresh air", "250 × 200", 64]],
  match: 78,
  unread: [["“6OO×25O”", "page 1, near grid C4", 0.41], ["“CFM 1?00”", "page 1, near grid F2", 0.38]],
  outputs: [["_takeoff.json", "Everything measured, for writing the BOQ"], ["_takeoff_summary.csv", "Length by system and size"], ["_takeoff_runs.csv", "Every run, with its position"], ["_takeoff_overlay_p1.png", "The picture to check"]],
  limits: ["Pipes drawn as a single line are not measured yet — only ducts drawn with two walls.", "Only straight ducts are measured. Bends and fittings go into the allowance.", "Vector PDFs only — a scanned drawing has no lines to measure. If you have the DWG/DXF, use that instead: it is exact."]
};
MOCK.pastBoq = [["BOQ — HVAC ductwork, Sargam Tower B.xlsx", "Today 10:42", "boq"], ["BOQ — CCTV and fibre, Vraj site.xlsx", "Mon", "boq"], ["BOQ — 36x24 jaw crusher.xlsx", "Last week", "boq"]];
/* BOQ jobs for "Continue where you left off" (a stopped one and two finished ones) */
MOCK.boqJobs = [
  { title: "CCTV, cabling and fibre — Vraj site", file: ["Site-CCTV-layout.dxf", "Drawing · 860 KB"], status: "draft", step: 2, when: "Yesterday 17:40" },
  { title: "HVAC ductwork for Sargam Tower B", file: ["Sargam-Tower-B-HVAC.dxf", "Drawing · 2.4 MB"], status: "ready", priced: true, rev: 2, when: "Today 10:42" },
  { title: "Materials for one 36x24 jaw crusher, 100 TPH", file: null, status: "ready", priced: false, rev: 1, when: "Mon" }
];
