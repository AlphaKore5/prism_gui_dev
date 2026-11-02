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
