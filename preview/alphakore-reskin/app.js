/* Prism × AlphaKore preview — shared behaviour + every module's mock interactions.
   Data comes from mock.js. Nothing leaves the browser: "open folder", "send" and the like
   show what would happen, in a toast or a dialog. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return [].slice.call((r || document).querySelectorAll(s)); };
  var PAGE = document.body.dataset.page || "";
  var esc = function (s) { return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); };
  var ic = function (n) { return '<svg class="i"><use href="#i-' + n + '"/></svg>'; };
  var pix = function (n) { return '<span class="ic"><svg><use href="#' + n + '"/></svg></span>'; };
  window.PRISM = { ic: ic };

  /* ───────────────────────── toast ───────────────────────── */
  var toastEl = document.createElement("div");
  toastEl.className = "toast"; toastEl.setAttribute("role", "status"); toastEl.setAttribute("aria-live", "polite");
  document.body.appendChild(toastEl);
  var toastT;
  function toast(msg) {
    toastEl.textContent = msg; toastEl.classList.add("on");
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.classList.remove("on"); }, 2800);
  }

  /* ───────────────────────── disabled with a reason ───────────────────────── */
  function setOff(btn, why) {
    if (!btn) return;
    if (why) { btn.disabled = true; btn.title = why; btn.setAttribute("aria-label", why); }
    else { btn.disabled = false; btn.removeAttribute("title"); btn.removeAttribute("aria-label"); }
  }

  /* ───────────────────────── modals ───────────────────────── */
  var zTop = 60;
  function showModal(m) { if (!m) return; m.style.zIndex = ++zTop; m.classList.add("on");
    var t = m.querySelector("[autofocus], textarea, input:not([type=checkbox]):not([type=radio]):not([type=range])");
    if (t && m.dataset.focus !== "no") setTimeout(function () { try { t.focus(); } catch (e) {} }, 40); }
  function hideModal(m) {
    if (!m) return;
    if (location.hash === "#" + m.id) { history.replaceState(null, "", location.pathname + (curView() ? "#" + curView() : "")); route(); return; }
    m.classList.remove("on");
  }
  function makeModal(id, cls) {
    var m = document.getElementById(id);
    if (m) return m;
    m = document.createElement("div"); m.className = "modal"; m.id = id;
    m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    m.innerHTML = '<div class="scrim" data-close></div><div class="dlg ' + (cls || "") + '"></div>';
    document.body.appendChild(m); return m;
  }
  function dialogShell(title, sub, icon, body, foot) {
    return '<div class="dh">' + (icon ? '<span class="tile">' + ic(icon) + '</span>' : "") + '<div><h2>' + title + '</h2>' + (sub ? '<p>' + sub + '</p>' : "") +
      '</div><div class="acts"><button class="iconbtn" data-close title="Close">' + ic("x") + '</button></div></div><div class="db">' + body + '</div>' +
      (foot ? '<div class="df">' + foot + '</div>' : "");
  }
  /* confirm: ask(title, text, okLabel, cb(ok), danger) */
  function ask(title, text, ok, cb, danger) {
    var m = makeModal("askm", "sm");
    m.querySelector(".dlg").innerHTML = dialogShell(title, "", "", '<p class="lead">' + text + '</p>',
      '<span class="sp"></span><button class="btn light plain sm" data-close>Cancel</button>' +
      (danger ? '<button class="btn danger-solid sm" id="ask-ok">' + ok + '</button>' : '<button class="btn dark sm" id="ask-ok">' + pix("parrow") + ok + '</button>'));
    var done = false;
    $("#ask-ok", m).onclick = function () { done = true; m.classList.remove("on"); cb && cb(true); };
    // Cancel, the ✕ and the backdrop all answer "no" — and say so
    [m.querySelector(".scrim"), m.querySelector("[data-close].iconbtn"), m.querySelector(".df [data-close]")].forEach(function (x) { x.onclick = function (e) { e.stopPropagation(); if (!done) { done = true; m.classList.remove("on"); cb && cb(false); } }; });
    showModal(m);
  }
  /* form: form(title, sub, icon, bodyHtml, okLabel, onOk(modal) -> false keeps it open) */
  function form(title, sub, icon, body, ok, onOk, cls, mid) {
    var m = makeModal(mid || "formm", cls || "");
    m.querySelector(".dlg").className = "dlg " + (cls || "");
    m.querySelector(".dlg").innerHTML = dialogShell(title, sub, icon, body,
      '<span class="sp"></span><button class="btn light plain sm" data-close>Cancel</button><button class="btn dark sm" id="form-ok">' + pix("parrow") + ok + '</button>');
    var okb = m.querySelector("#form-ok"); okb.removeAttribute("id"); okb.className += " form-ok";
    okb.onclick = function () { if (onOk(m) !== false) m.classList.remove("on"); };
    showModal(m); return m;
  }
  function info(title, sub, icon, body, cls) {
    var m = makeModal("infom", cls || "");
    m.querySelector(".dlg").className = "dlg " + (cls || "");
    m.querySelector(".dlg").innerHTML = dialogShell(title, sub, icon, body, "");
    showModal(m); return m;
  }
  function video(src, title, poster) {
    var m = makeModal("videom", "video");
    m.querySelector(".dlg").innerHTML = '<div class="dh"><span class="tile">' + ic("video") + '</span><div><h2>' + esc(title) + '</h2></div><div class="acts"><button class="iconbtn" data-close title="Close">' + ic("x") + '</button></div></div>' +
      '<div class="vwrap"><video src="' + src + '" ' + (poster ? 'poster="' + poster + '"' : "") + ' controls autoplay playsinline></video></div>';
    showModal(m);
  }

  /* ───────────────────────── popover menus ───────────────────────── */
  var pop = document.createElement("div"); pop.className = "pop"; pop.setAttribute("role", "menu"); document.body.appendChild(pop);
  var popFor = null;
  function menu(anchor, items, head) {
    if (popFor === anchor && pop.classList.contains("on")) { closePop(); return; }
    pop.innerHTML = (head ? '<div class="ph2">' + head + '</div>' : "") + items.map(function (it, i) {
      if (it.sep) return '<div class="sep"></div>';
      if (it.html) return '<div class="phtml">' + it.html + '</div>';
      return '<button role="menuitem" data-i="' + i + '"' + (it.off ? ' disabled title="' + esc(it.off) + '"' : "") + '>' + (it.icon ? ic(it.icon) : "") +
        '<span><b>' + it.label + '</b>' + (it.hint ? '<small>' + it.hint + '</small>' : "") + '</span>' + (it.check ? '<span class="tick">' + (it.checked ? ic("check") : "") + '</span>' : "") + '</button>';
    }).join("");
    $$("button[data-i]", pop).forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); var it = items[+b.dataset.i]; if (!it.keep) closePop(); it.on && it.on(b); }; });
    pop.classList.add("on"); popFor = anchor;
    var r = anchor.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.min(Math.max(8, r.left), innerWidth - w - 8), top = r.bottom + 6;
    if (top + h > innerHeight - 30) top = Math.max(8, r.top - h - 6);
    pop.style.left = left + "px"; pop.style.top = top + "px";
  }
  function closePop() { pop.classList.remove("on"); popFor = null; }
  document.addEventListener("click", function (e) { if (!pop.contains(e.target) && popFor && !popFor.contains(e.target)) closePop(); }, true);

  /* ───────────────────────── files, voice, favourites ───────────────────────── */
  function fileChip(f, onRemove) {
    var c = document.createElement("span"); c.className = "fchip";
    c.innerHTML = ic(f[1].indexOf("Drawing") === 0 || /dxf|step|stp|zip|rar/.test(f[0]) ? "file" : "clip") + '<span><b>' + esc(f[0]) + '</b><small>' + esc(f[1]) + '</small></span><button title="Remove ' + esc(f[0]) + '">' + ic("x") + '</button>';
    c.querySelector("button").onclick = function () { c.remove(); onRemove && onRemove(f); };
    return c;
  }
  /* attach(anchor, kinds, holder, state, after) — mock "file picker" listing Desktop files */
  function pickFile(anchor, kinds, cb, head) {
    var items = [];
    kinds.split(",").forEach(function (k) { (MOCK.files[k] || []).forEach(function (f) { items.push({ label: esc(f[0]), hint: esc(f[1]), icon: "file", on: function () { cb(f); } }); }); });
    menu(anchor, items, head || "Desktop — pick a file");
  }
  function attachTo(holder, state, f, after) {
    if (state.files.some(function (x) { return x[0] === f[0]; })) { toast(f[0] + " is already attached"); return; }
    state.files.push(f);
    holder.appendChild(fileChip(f, function () { state.files = state.files.filter(function (x) { return x !== f; }); after && after(); }));
    toast("Attached " + f[0]); after && after();
  }
  var TRANSCRIPTS = {
    boq: "BOQ for the HVAC ductwork in Sargam Tower B, with the duct sizes and quantities floor by floor",
    bom: "Parts list to fabricate the over-band magnetic separator from the GA drawing",
    gerber: "Reply with our price for 500 pieces and list anything that is tight to fabricate",
    reel: "A reel describing what we sell at Kinetic Springs, for Instagram",
    motion: "An animated diagram of how an inquiry becomes a quotation in Prism",
    task: "Compare the three spring suppliers in the attached price lists and tell me who is cheapest",
    step: "How do I make this lighter?",
    email: "Introduce our compression springs and ask for a meeting next week"
  };
  function speak(btn, target, key, after) {
    if (btn.classList.contains("rec")) { stop(); return; }
    btn.classList.add("rec"); var old = btn.innerHTML;
    btn.innerHTML = '<span class="recdot"></span>Listening… press to stop';
    var t = setTimeout(stop, 2600);
    function stop() {
      clearTimeout(t); if (!btn.classList.contains("rec")) return;
      btn.classList.remove("rec"); btn.innerHTML = old;
      target.value = (target.value ? target.value + " " : "") + (TRANSCRIPTS[key] || TRANSCRIPTS.task);
      target.dispatchEvent(new Event("input", { bubbles: true })); toast("Heard you — check the words, then go ahead");
      after && after();
    }
  }
  var FAVS = {
    boq: ["BOQ for CCTV, cabling and fibre for this site", "Materials to build one 36x24 jaw crusher, 100 TPH", "BOQ for HVAC ductwork, floor by floor"],
    bom: ["Parts list to fabricate this over-band magnetic separator", "BOM for one 36x24 jaw crusher, 100 TPH"],
    gerber: ["Reply with our price for 500 pieces", "Fabrication note & PCB inspection summary"],
    reel: ["A reel describing what we sell at Raj Infotech", "Festival offer reel — 15 seconds", "Factory tour reel from my clips"],
    motion: ["An animated architecture diagram of our distributed crawler", "How a spring is made, in 5 steps"],
    task: ["Summarize the attached PDF in 10 lines", "Find 20 HVAC contractors in Gujarat", "Write a follow-up mail for INQ-0143"]
  };
  function favourites(anchor, key, target, after) {
    var items = (FAVS[key] || FAVS.task).map(function (p) { return { label: esc(p), icon: "clock", on: function () { target.value = p; target.dispatchEvent(new Event("input", { bubbles: true })); after && after(); } }; });
    menu(anchor, items, "Favourites");
  }

  /* ───────────────────────── progress lines (the app's Loader "stages") ───────────────────────── */
  function stages(box, lines, done, ms) {
    box.className = box.className.replace(/\bfilled\b/, "") + " running";
    box.innerHTML = '<ol class="stages-run">' + lines.map(function (l) { return '<li>' + esc(l) + '</li>'; }).join("") + '</ol>';
    var lis = $$("li", box), i = 0;
    (function step() {
      if (i > 0) lis[i - 1].className = "done";
      if (i === lis.length) { setTimeout(function () { box.classList.remove("running"); done(); }, 250); return; }
      lis[i].className = "now"; i++; setTimeout(step, ms || 700);
    })();
  }

  /* ───────────────────────── result renderers ───────────────────────── */
  function prov(m, ai) { return '<span class="prov m">' + m + '</span>' + (ai ? '<span class="prov ai">' + ai + '</span>' : ""); }
  function boqHTML(file) {
    var n = 0, rows = MOCK.boq.map(function (r) {
      if (r.length === 1) return '<tr class="grp"><td></td><td colspan="5">' + esc(r[0]) + '</td></tr>';
      n++; return '<tr><td class="idx">' + n + '</td><td>' + esc(r[0]) + '</td><td class="n">' + r[1] + '</td><td class="u">' + r[2] + '</td><td class="n nil">—</td><td class="n nil">—</td></tr>';
    }).join("");
    return '<div class="oh"><b>Bill of Quantities</b>' + prov("Quantities measured here", "Written up by Prism Agent Claude") + '<span class="sp"></span><span class="mono muted">Saved to Prism Artifacts</span></div>' +
      '<div class="tscroll"><table class="tbl"><thead><tr><th class="idx">#</th><th>Item</th><th class="n">Qty</th><th>Unit</th><th class="n">Rate (₹)</th><th class="n">Amount (₹)</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      '<div class="caveat">' + ic("lock") + '<span>Measured from ' + esc(file || "Sargam-Tower-B-HVAC.dxf") + ' · 3 layers read. Rate and Amount are left blank on purpose — Prism counts, you price.</span></div>';
  }
  function bomHTML() {
    var n = 0, rows = MOCK.bom.map(function (r) {
      if (r.length === 1) return '<tr class="grp"><td></td><td colspan="5">' + esc(r[0]) + '</td></tr>';
      n++; return '<tr><td class="idx">' + n + '</td><td>' + esc(r[0]) + '</td><td class="n">' + r[1] + '</td><td class="u">' + r[2] + '</td><td class="n">' + r[3] + '</td><td class="n">' + r[4] + '</td></tr>';
    }).join("");
    return '<div class="oh"><b>Bill of Materials</b>' + prov("Parts measured here", "Written up by Prism Agent Claude") + '<span class="sp"></span><span class="mono muted">Saved to Prism Artifacts</span></div>' +
      '<div class="tscroll"><table class="tbl"><thead><tr><th class="idx">#</th><th>Part</th><th class="n">Qty</th><th>Unit</th><th class="n">Size</th><th class="n">Weight</th></tr></thead><tbody>' + rows +
      '</tbody><tfoot><tr><td></td><td>Total fabricated weight</td><td></td><td></td><td></td><td class="n">873.5 kg</td></tr></tfoot></table></div>';
  }
  function gerberHTML(unit) {
    var f = function (v) { return unit === "mil" ? (v / 0.0254).toFixed(1) + " mil" : (+v).toFixed(3).replace(/0+$/, "").replace(/\.$/, "") + " mm"; };
    var rows = MOCK.gerber.map(function (g, i) {
      var v = g[1];
      if (Array.isArray(v)) v = unit === "mil" ? (v[0] / 0.0254).toFixed(0) + " × " + (v[1] / 0.0254).toFixed(0) + " mil" : v[0] + " × " + v[1] + " mm";
      else if (typeof v === "number") v = f(v);
      return '<tr><td class="idx">' + (i + 1) + '</td><td>' + g[0] + (g[2] ? '<span class="cellnote">' + g[2] + '</span>' : "") + '</td><td class="n">' + v + '</td></tr>';
    }).join("");
    return '<div class="oh"><b>controller-rev-c.zip</b>' + prov("Measured from the Gerber files") + '<span class="sp"></span><span class="mono muted">Check sheet saved beside the job</span></div>' +
      '<div class="tscroll"><table class="tbl"><thead><tr><th class="idx">#</th><th>Figure</th><th class="n">Measured</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }
  function stepHTML() {
    return '<div class="reg">' + MOCK.step.map(function (m) {
      if (m[0] === "sec") return '<div class="sec">' + esc(m[1]) + '</div>';
      if (m[0] === "warn") return '<div class="warnline">' + esc(m[1]) + '</div>';
      return '<div class="kv2"><span>' + esc(m[0]) + '</span><b>' + esc(m[1]) + '</b></div>';
    }).join("") + '</div>';
  }
  function quoteHTML(q) {
    q = q || MOCK.inquiries[0];
    var rows = MOCK.quoteLines.map(function (r, i) { var tot = r[0] === "Total" || r[0].indexOf("GST") === 0;
      return '<tr' + (tot ? ' class="tot"' : "") + '><td class="idx">' + (tot ? "" : i + 1) + '</td><td>' + r[0] + '</td><td class="n">' + r[1] + '</td><td class="u">' + r[2] + '</td><td class="n">' + r[3] + '</td><td class="n">' + r[4] + '</td></tr>'; }).join("");
    return '<div class="doc"><div class="dochead"><div><b>' + MOCK.company + '</b><small>GIDC Makarpura, Vadodara · GSTIN 24AAxxxx1Z5</small></div><div class="r"><b>Quotation Q-2611-047</b><small>For ' + esc(q.no) + ' · 03 Nov 2026</small></div></div>' +
      '<p>To <b>' + esc(q.contact) + '</b>, ' + esc(q.who) + '<br>Sub: ' + esc(q.asked) + '</p>' +
      '<table class="tbl"><thead><tr><th class="idx">#</th><th>Description</th><th class="n">Qty</th><th>Unit</th><th class="n">Rate</th><th class="n">Amount</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<p class="muted small">Delivery: 3 weeks from PO · Payment: 30 days · Validity: 15 days · Prices from your rate sheet "Rate sheet Nov.xlsx".</p></div>';
  }
  function textHTML(kind) {
    if (kind === "err") return '<div class="errbox">' + ic("x") + '<div><b>This run failed</b><p>Perplexity did not answer within 4 minutes, so the run stopped. Nothing was saved. Try again, or pick another research tool in Settings → Agents.</p></div></div>';
    if (kind === "never") return '<div class="note">This task was planned but never started. Press Run again to start it now.</div>';
    return '<div class="doc"><h4>Kirloskar price list — summary</h4><ul class="sum">' +
      ["Prices are up 4.5% on average from the August list; motors under 5 HP are unchanged.", "Pumps in the KDS range now carry a 3-week lead time (was 2).",
       "Freight is charged extra above 200 km from Pune.", "Payment terms: 30 days for dealers, advance for new buyers.", "Three items are discontinued: KDS-0332, KDS-0525, KS-415."]
        .map(function (s) { return "<li>" + s + "</li>"; }).join("") + '</ul><p class="muted small">Written by ChatGPT from the attached PDF. The PDF was read on this computer first.</p></div>';
  }
  function reelHTML(kind) {
    var sc = kind === "motion" ? [["Title — \u201cFrom inquiry to quotation\u201d", "0:00–0:03"], ["Inbox fills; Prism numbers each mail", "0:03–0:08"], ["Register table grows, row by row", "0:08–0:13"], ["Quotation PDF folds out", "0:13–0:18"], ["End card — Prism by AlphaKore", "0:18–0:21"]]
      : [["Hook — \u201cSprings that never quit\u201d", "0:00–0:02"], ["Factory floor, coiling machine", "0:02–0:05"], ["Product line-up: compression, torsion, leaf", "0:05–0:09"], ["Customers: pumps, HVAC, conveyors", "0:09–0:12"], ["Call to action — WhatsApp us", "0:12–0:15"]];
    var poster = kind === "motion" ? "media/prism-story-poster.jpg" : "media/reel-poster.jpg";
    return '<div class="reelres"><button class="thumb ' + (kind === "motion" ? "wide" : "") + '" data-play="' + (kind === "motion" ? "media/prism-story.mp4" : "media/reel.mp4") + '" title="Play"><img src="' + poster + '" alt=""><span>' + ic("play") + '</span></button>' +
      '<ol class="scenes">' + sc.map(function (s, i) { return '<li><span class="n">' + (i + 1) + '</span><b>' + s[0] + '</b><span class="mono muted">' + s[1] + '</span></li>'; }).join("") + '</ol></div>';
  }
  var ISO = '<svg class="iso" viewBox="0 0 320 220" aria-hidden="true"><g fill="none" stroke="#111110" stroke-width="1.6" stroke-linejoin="round"><path d="M40 150 160 200 290 140 170 90z" fill="#fff"/><path d="M40 150v14l120 50 130-60v-14" fill="#E6E5E1"/><path d="M160 200v14"/><path d="M170 90V30l-40-18v58" fill="#F6F5F2"/><path d="M130 70 40 150"/><path d="M170 30l120 60v50"/><path d="M200 105l40 20 40-20-40-20z" fill="#E6E5E1"/></g><g fill="#fff" stroke="#C8161D" stroke-width="1.6"><ellipse cx="90" cy="158" rx="9" ry="5"/><ellipse cx="225" cy="160" rx="9" ry="5"/><ellipse cx="150" cy="40" rx="5" ry="8"/><ellipse cx="150" cy="62" rx="5" ry="8"/></g></svg>';
  function outFor(kind) {
    return { boq: boqHTML(), bom: bomHTML(), gerber: gerberHTML("mm"), step: stepHTML(), quote: quoteHTML(MOCK.inquiries[0]), text: textHTML("text"), err: textHTML("err"), never: textHTML("never"),
             reel: reelHTML("reel"), motion: reelHTML("motion"), render: '<div class="render big">' + ISO + '</div>', drawing: '<div class="render big">' + ISO + '<span class="cap">Drawing sheet · 3 views · A3</span></div>' }[kind] || textHTML("text");
  }
  document.addEventListener("click", function (e) { var p = e.target.closest("[data-play]"); if (p) video(p.dataset.play, "Preview", ""); });

  function statusPill(s) { return s === "ok" ? '<span class="st ok">Completed</span>' : s === "err" ? '<span class="st err">Failed</span>' : '<span class="st neutral">Never ran</span>'; }
  function runDetail(r, onDelete) {
    var m = info(esc(r.title), (r.tool ? r.tool + " · " : "") + (r.by ? r.by + " · " : "") + r.day + " " + r.when, r.icon,
      '<div class="detbar">' + statusPill(r.status) + '<span class="sp"></span><button class="btn light plain sm" id="rd-art">' + ic("folder") + 'Open in Artifacts</button>' +
      '<button class="btn light plain sm" id="rd-again">' + ic("clock") + 'Run again</button><button class="btn light plain sm danger" id="rd-del">' + ic("trash") + 'Delete</button></div>' +
      '<div class="out filled">' + outFor(r.out) + '</div>', "mid");
    $("#rd-art", m).onclick = function () { location.href = "artifacts.html"; };
    $("#rd-again", m).onclick = function () { m.classList.remove("on"); toast("Started again: " + r.title.slice(0, 48) + "…"); };
    $("#rd-del", m).onclick = function () { ask("Delete this run?", "It is removed from History. Files it saved to Prism Artifacts stay where they are.", "Delete", function (ok) { if (ok) { m.classList.remove("on"); onDelete && onDelete(r); toast("Run deleted"); } }, true); };
  }

  /* ───────────────────────── hash routing (views + hash dialogs) ───────────────────────── */
  var views = $$("[data-view]");
  function curView() { var v = views.filter(function (x) { return x.classList.contains("on"); })[0]; return v && v !== views[0] ? v.dataset.view : ""; }
  function route() {
    var h = location.hash.slice(1), m = h && document.getElementById(h);
    $$(".modal[data-hash]").forEach(function (x) { if (x !== m) x.classList.remove("on"); });
    if (m && m.classList.contains("modal")) { showModal(m); return; }
    if (!views.length) { document.dispatchEvent(new CustomEvent("route", { detail: h })); return; }
    var v = views.filter(function (x) { return x.dataset.view === h; })[0] || views[0];
    views.forEach(function (x) { x.classList.toggle("on", x === v); });
    document.dispatchEvent(new CustomEvent("route", { detail: h }));
  }
  document.addEventListener("click", function (e) {
    var o = e.target.closest("[data-open]");
    if (o && !o.disabled) {
      e.preventDefault(); var fill = o.dataset.fill;
      location.hash = o.dataset.open;
      if (fill) setTimeout(function () { var t = $("#" + o.dataset.open + " textarea"); if (t) { t.value = fill; t.dispatchEvent(new Event("input", { bubbles: true })); } }, 40);
      return;
    }
    var c = e.target.closest("[data-close]");
    if (c) { e.preventDefault(); hideModal(c.closest(".modal")); return; }
    var b = e.target.closest(".utabs button, .pseg button, .stages button, .stats3 > div");
    if (b && !b.disabled && !b.closest(".pop")) [].forEach.call(b.parentNode.children, function (x) { x.classList.toggle("on", x === b); });
    var a = e.target.closest(".acc .h");
    if (a) { var body = a.nextElementSibling, open = body && !body.hidden; if (body) body.hidden = open; var u = a.querySelector("use"); if (u) u.setAttribute("href", open ? "#i-right" : "#i-down"); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (pop.classList.contains("on")) { closePop(); return; }
    var open = $$(".modal.on").sort(function (a, b) { return (+b.style.zIndex || 0) - (+a.style.zIndex || 0); })[0];
    if (open) hideModal(open); else if (lumi.classList.contains("on")) lumi.classList.remove("on");
  });
  addEventListener("hashchange", route);

  /* ───────────────────────── shell: sidebar, Lumi, status ───────────────────────── */
  var app = $(".app");
  var col = $(".side .collapse");
  if (col) col.onclick = function () { app.classList.toggle("collapsed"); col.title = app.classList.contains("collapsed") ? "Expand the sidebar" : "Collapse the sidebar"; };
  var grp = $(".side .grp");
  if (grp) { grp.style.cursor = "pointer"; grp.title = "Show or hide the add-ons"; grp.onclick = function () { var a = $(".side .addons"); a.hidden = !a.hidden; grp.querySelector("use").setAttribute("href", a.hidden ? "#i-right" : "#i-down"); }; }

  var lumi = document.createElement("aside"); lumi.className = "lumi"; lumi.setAttribute("aria-label", "Lumi");
  lumi.innerHTML = '<div class="lh"><img src="img/lumi_avatar.png" alt=""><div><b>Lumi</b><small>Prism\'s helper · answers from the Prism guide</small></div><button class="iconbtn" title="Close Lumi">' + ic("x") + '</button></div>' +
    '<div class="lmsgs"><div class="msg them">Hi Parth! Ask me anything about Prism — how to make a BOQ, where your files went, what your licence covers.</div></div>' +
    '<div class="lsugg"><button>How do I make a BOQ?</button><button>Where are my reels?</button><button>What does my plan include?</button></div>' +
    '<form class="lin"><input class="field2" placeholder="Ask Lumi…" aria-label="Ask Lumi"><button class="send sm" title="Ask"><span><svg><use href="#parrow"/></svg></span></button></form>';
  document.body.appendChild(lumi);
  function lumiAsk(q) {
    if (!q.trim()) return; var box = $(".lmsgs", lumi);
    box.insertAdjacentHTML("beforeend", '<div class="msg me">' + esc(q) + '</div><div class="msg them typing"><i></i><i></i><i></i></div>'); box.scrollTop = 1e6;
    setTimeout(function () { var a = MOCK.lumi.filter(function (x) { return x[0].test(q); })[0][1]; $(".typing", box).outerHTML = '<div class="msg them">' + esc(a) + '</div>'; box.scrollTop = 1e6; }, 700);
  }
  $(".lh .iconbtn", lumi).onclick = function () { lumi.classList.remove("on"); };
  $$(".lsugg button", lumi).forEach(function (b) { b.onclick = function () { lumiAsk(b.textContent); }; });
  $(".lin", lumi).onsubmit = function (e) { e.preventDefault(); var i = $("input", this); if (!i.value.trim()) { toast("Type a question for Lumi first"); i.focus(); return; } lumiAsk(i.value); i.value = ""; };
  var edge = $(".edge"); if (edge) edge.onclick = function () { lumi.classList.toggle("on"); if (lumi.classList.contains("on")) setTimeout(function () { $(".lin input", lumi).focus(); }, 50); };
  window.openLumi = function () { lumi.classList.add("on"); };

  /* generic buttons that only tell you what they did */
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-toast]"); if (t && !t.disabled) toast(t.dataset.toast);
  });

  /* ═════════════════════════ HOME ═════════════════════════ */
  function renderRecent() {
    var box = $("#h-acts"); if (!box) return;
    box.innerHTML = MOCK.runs.slice(0, 4).map(function (r, i) {
      return '<li data-i="' + i + '" tabindex="0"><span class="ftile">' + ic(r.icon) + '</span><div style="min-width:0"><div class="t">' + esc(r.title) + '</div><div class="m">' + (r.tool || "Prism") + ' · ' + (r.day === "Today" ? r.when : r.day) + '</div></div>' +
        statusPill(r.status) + '<button class="iconbtn more" title="More">' + ic("more") + '</button></li>';
    }).join("");
    $$("li", box).forEach(function (li) {
      var r = MOCK.runs[+li.dataset.i];
      li.onclick = function (e) {
        if (e.target.closest(".more")) {
          menu(e.target.closest(".more"), [{ label: "Open", icon: "eye", on: function () { runDetail(r, del); } }, { label: "Run again", icon: "clock", on: function () { toast("Started again: " + r.title.slice(0, 40) + "…"); } },
            { label: "Show in History", icon: "list", on: function () { location.href = "history.html"; } }, { sep: 1 }, { label: "Delete", icon: "trash", on: function () { ask("Delete this run?", "It is removed from History. Saved files stay in Prism Artifacts.", "Delete", function (ok) { if (ok) del(r); }, true); } }]);
          return;
        }
        runDetail(r, del);
      };
      li.onkeydown = function (e) { if (e.key === "Enter") runDetail(r, del); };
    });
    function del(r) { MOCK.runs = MOCK.runs.filter(function (x) { return x !== r; }); renderRecent(); toast("Run deleted"); }
  }
  function homeInit() {
    renderRecent();
    var ta = $("#task"), send = $("#h-send"), holder = $("#h-att"), st = { files: [], tools: ["Claude", "ChatGPT", "Perplexity"] };
    function upd() { setOff(send, ta.value.trim() || st.files.length ? "" : "Type what you need, or attach a file first"); }
    ta.addEventListener("input", upd); upd();
    ta.addEventListener("keydown", function (e) { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send.click(); });
    $("#h-attach").onclick = function () { pickFile(this, "doc,drawing,media", function (f) { attachTo(holder, st, f, upd); }); };
    $("#h-commands").onclick = function () {
      menu(this, [["/boq", "Bill of Quantities from a drawing", "boq.html"], ["/bom", "Parts list to fabricate it", "bom.html"], ["/gerber", "Measure a PCB job", "gerber.html"], ["/step", "Measure a 3D model", "step.html"],
                  ["/reel", "Make a 9:16 reel", "#reel"], ["/motion", "Make a motion graphic", "#motion"], ["/email", "Send an email", "email.html#compose"], ["/leads", "Find people to sell to", "leads.html"]]
        .map(function (c) { return { label: c[0], hint: c[1], icon: "cmd", on: function () { if (c[2][0] === "#" || c[2].indexOf("html") > 0) { if (c[2][0] === "#") location.hash = c[2].slice(1); else location.href = c[2]; } } }; }), "Commands — jump straight to a tool");
    };
    $("#h-tools").onclick = function () {
      var all = [["Claude", "Writing · Paid"], ["ChatGPT", "Writing, files · Free"], ["Perplexity", "Research · Free"], ["Gemini", "Research · Free"], ["Grok", "Writing · Free"], ["DeepSeek", "Writing · Free"]];
      var b = this;
      function items() { return all.map(function (t) { return { label: t[0], hint: t[1], icon: "grid", check: 1, checked: st.tools.indexOf(t[0]) >= 0, keep: 1,
        on: function () { var k = st.tools.indexOf(t[0]); if (k >= 0) st.tools.splice(k, 1); else st.tools.push(t[0]); b.innerHTML = ic("grid") + "Tools · " + st.tools.length; menu(b, items(), "Tools Prism may use"); menu(b, items(), "Tools Prism may use"); } }; }); }
      menu(b, items(), "Tools Prism may use");
    };
    $("#h-tools").innerHTML = ic("grid") + "Tools · 3";
    $("#try-pdf").onclick = function () { ta.value = "Summarize this PDF in 10 lines and list anything that changed in prices"; attachTo(holder, st, MOCK.files.doc[0], upd); upd(); ta.focus(); };
    $("#try-boq").onclick = function () { ta.value = "Analyze this BOQ — check the quantities against the drawing and flag anything missing"; attachTo(holder, st, MOCK.files.sample[1], upd); upd(); ta.focus(); };
    $("#try-clean").onclick = function () { ta.value = "Clean up my artifacts — group last week's files by customer and delete duplicates"; upd(); ta.focus(); };
    $("#h-demo").onclick = $("#h-time").onclick = function () { video("media/prism-story.mp4", "Prism — ideas to outcomes", "media/prism-story-poster.jpg"); };
    function focusNew(h) { if (h === "new") { history.replaceState(null, "", location.pathname); ta.focus(); ta.closest(".composer").classList.add("glow"); setTimeout(function () { ta.closest(".composer").classList.remove("glow"); }, 900); } }
    document.addEventListener("route", function (e) { focusNew(e.detail); });
    send.onclick = function () { if (!send.disabled) newTask(ta.value.trim() || "Work with the attached files", st.files.slice(), function () { ta.value = ""; holder.innerHTML = ""; st.files = []; upd(); }); };
    videoDialog("reel"); videoDialog("motion");
  }
  function newTask(prompt, files, cleared) {
    if (/\breel\b|video/i.test(prompt)) { location.hash = "reel"; setTimeout(function () { var t = $("#reel textarea"); t.value = prompt; t.dispatchEvent(new Event("input", { bubbles: true })); }, 50); cleared(); return; }
    var kind = /boq|quantit|dxf|drawing/i.test(prompt) ? "boq" : /pdf|summar|price list/i.test(prompt) ? "text" : "text";
    var steps = kind === "boq" ? [["file", "Read the drawing", "Measured on this computer · no AI sees the file", "Measured here"], ["sheet", "Build the quantities", "Prism Agent Claude · about 40 s", "Prism Agent Claude"], ["grid", "Prepare the workbook", "Excel, in your sample's layout", "Prism"]]
      : [["search", "Research", "Perplexity · waits up to 4 min", "Perplexity"], ["pencil", "Write it up", "Claude · about 1 min", "Claude"], ["check", "Check the facts", "ChatGPT · about 30 s", "ChatGPT"]];
    var m = info("New task", "Prism made a plan. Switch off any step you don't want, then start.", "spark",
      '<div class="taskq"><span class="label">You asked</span><p>' + esc(prompt) + '</p>' + (files.length ? '<div class="frow">' + files.map(function (f) { return '<span class="fchip mini">' + ic("clip") + '<b>' + esc(f[0]) + '</b></span>'; }).join("") + '</div>' : "") + '</div>' +
      '<div class="plan"><div class="planh"><span class="label">Suggested workflow</span><span class="mono muted">' + steps.length + ' steps</span></div>' +
      steps.map(function (s, i) { return '<label class="pstep"><span class="n">0' + (i + 1) + '</span><span class="ftile">' + ic(s[0]) + '</span><span class="tx"><b>' + s[1] + '</b><small>' + s[2] + '</small></span><span class="switch"><input type="checkbox" checked><i></i></span></label>'; }).join("") + '</div>' +
      '<div class="out" id="task-out">The answer appears here once the steps finish.</div>' +
      '<div class="df inl"><span class="mono muted" id="task-note">Nothing has run yet.</span><span class="sp"></span><button class="btn light plain sm" data-close>Not now</button><button class="btn dark sm" id="task-go">' + pix("parrow") + 'Start work</button></div>', "mid");
    cleared();
    $("#task-go", m).onclick = function () {
      var b = this, on = $$(".pstep input", m).map(function (x, i) { return x.checked ? steps[i] : null; }).filter(Boolean);
      if (!on.length) { toast("Switch on at least one step"); return; }
      setOff(b, "Working…"); $("#task-note", m).textContent = "Working — you can close this; it keeps going.";
      stages($("#task-out", m), on.map(function (s) { return s[1] + " — " + s[3]; }), function () {
        var o = $("#task-out", m); o.classList.add("filled"); o.innerHTML = kind === "boq" ? boqHTML() : textHTML("text");
        $("#task-note", m).textContent = "Done · saved to History and Prism Artifacts"; b.innerHTML = pix("parrow") + "Open History"; setOff(b, "");
        b.onclick = function () { location.href = "history.html"; };
        MOCK.runs.unshift({ id: "n" + Date.now(), day: "Today", when: "now", title: prompt, tool: kind === "boq" ? "BOQ" : "", by: on[on.length - 1][3], status: "ok", out: kind, icon: kind === "boq" ? "sheet" : "file" });
        renderRecent(); toast("Task finished");
      }, 900);
    };
  }
  function videoDialog(key) {
    var d = $("#" + key); if (!d) return;
    var ta = $("textarea", d), st = { files: [], made: false }, out = $(".js-out", d), make = $(".js-make", d), holder = $(".js-att", d);
    var util = $$(".df .btn.light", d).filter(function (b) { return !b.hasAttribute("data-close"); });
    function upd() {
      setOff(make, ta.value.trim() || st.files.length ? "" : "Say what the " + (key === "reel" ? "reel" : "motion graphic") + " should be about first");
      util.forEach(function (b) { setOff(b, st.made ? "" : b.dataset.why); });
    }
    util.forEach(function (b) { b.dataset.why = b.title; });
    ta.addEventListener("input", upd); upd();
    $(".js-speak", d).onclick = function () { speak(this, ta, key, upd); };
    $(".js-add", d).onclick = function () { pickFile(this, "media", function (f) { attachTo(holder, st, f, upd); }); };
    $(".js-fav", d).onclick = function () { favourites(this, key, ta, upd); };
    make.onclick = function () {
      if (make.disabled) return; setOff(make, "Making it…");
      var how = $("input[name=how]:checked", d); how = how ? how.parentNode.textContent.split(" — ")[0].trim() : "Motion";
      stages(out, key === "reel" ? ["Writing the script", "Designing the scenes (" + how + ")", "Filming frame by frame", "Mixing the music"] : ["Writing the scenes", "Placing the camera", "Drawing frame by frame"], function () {
        out.classList.add("filled"); out.innerHTML = reelHTML(key); st.made = true; upd(); toast("Saved to Prism Artifacts");
      }, 750);
    };
    util.forEach(function (b) { b.onclick = function () {
      if (b.disabled) return;
      if (/Play/.test(b.textContent)) video(key === "reel" ? "media/reel.mp4" : "media/prism-story.mp4", key === "reel" ? "Your reel" : "Your motion graphic", key === "reel" ? "media/reel-poster.jpg" : "media/prism-story-poster.jpg");
      else if (/Show file/.test(b.textContent)) toast("Opened Desktop / Prism Artifacts in your file manager");
      else toast("Opened the editor in your browser");
    }; });
  }

  /* ═════════════════════════ HISTORY ═════════════════════════ */
  function historyInit() {
    var list = $("#h-list"), q = $("#hist-q"), count = $("#hist-count"), filt = "all", sel = {};
    function vis() { return MOCK.runs.filter(function (r) { return (filt === "all" || r.status === filt) && (!q.value || (r.title + " " + r.tool + " " + r.by).toLowerCase().indexOf(q.value.toLowerCase()) >= 0); }); }
    function render() {
      var v = vis(), days = [];
      v.forEach(function (r) { if (days.indexOf(r.day) < 0) days.push(r.day); });
      count.textContent = v.length + " of " + MOCK.runs.length + " runs";
      $$(".seg button").forEach(function (b) { var f = b.dataset.f; $(".n", b).textContent = MOCK.runs.filter(function (r) { return f === "all" || r.status === f; }).length; });
      if (!MOCK.runs.length) { list.innerHTML = '<div class="card blank" style="min-height:18rem"><div><span class="ftile">' + ic("clock") + '</span><h2>No runs yet</h2><p>Every task you run is kept here, with its answer, so you can open it again later.</p></div></div>'; selbar(); return; }
      if (!v.length) { list.innerHTML = '<div class="card blank" style="min-height:14rem"><div><span class="ftile">' + ic("search") + '</span><h2>Nothing matches</h2><p>Try fewer words, or pick All above.</p></div></div>'; selbar(); return; }
      list.innerHTML = days.map(function (d) {
        var rs = v.filter(function (r) { return r.day === d; });
        return '<div class="day"><h2>' + d + '</h2><span>' + rs.length + (rs.length === 1 ? " run" : " runs") + '</span></div><ul class="card runs">' + rs.map(function (r) {
          return '<li data-id="' + r.id + '" tabindex="0"><input type="checkbox" class="ck"' + (sel[r.id] ? " checked" : "") + ' aria-label="Select this run"><div style="min-width:0"><div class="t">' + esc(r.title) + '</div><div class="m">' + (r.by ? esc(r.by) : "No tool recorded") + '</div></div>' +
            (r.tool ? '<span class="tag tagc">' + r.tool + '</span>' : '<span></span>') + '<span class="when">' + (r.day === "Today" ? r.when : r.when) + '</span>' + statusPill(r.status) +
            '<button class="iconbtn del" title="Delete this run">' + ic("trash") + '</button></li>';
        }).join("") + '</ul>';
      }).join("");
      $$("li[data-id]", list).forEach(function (li) {
        var r = MOCK.runs.filter(function (x) { return x.id === li.dataset.id; })[0];
        li.onclick = function (e) {
          if (e.target.closest(".ck")) { sel[r.id] = e.target.checked; selbar(); return; }
          if (e.target.closest(".del")) { remove([r]); return; }
          runDetail(r, function () { remove([r], true); });
        };
        li.onkeydown = function (e) { if (e.key === "Enter") runDetail(r, function () { remove([r], true); }); };
      });
      selbar();
    }
    function remove(rs, quiet) {
      var keep = MOCK.runs.slice();
      MOCK.runs = MOCK.runs.filter(function (r) { return rs.indexOf(r) < 0; }); rs.forEach(function (r) { delete sel[r.id]; }); render();
      if (!quiet) undo(rs.length === 1 ? "Run deleted" : rs.length + " runs deleted", function () { MOCK.runs = keep; render(); });
    }
    function selbar() {
      var n = Object.keys(sel).filter(function (k) { return sel[k]; }).length, bar = $("#hist-sel");
      bar.hidden = !n; bar.querySelector("b").textContent = n + (n === 1 ? " run selected" : " runs selected");
    }
    $("#hist-sel-del").onclick = function () { remove(MOCK.runs.filter(function (r) { return sel[r.id]; })); };
    $("#hist-sel-none").onclick = function () { sel = {}; render(); };
    q.addEventListener("input", render);
    $$(".seg button").forEach(function (b) { b.addEventListener("click", function () { $$(".seg button").forEach(function (x) { x.classList.toggle("on", x === b); }); filt = b.dataset.f; render(); }); });
    $("#hist-clear").onclick = function () { ask("Clear all history?", "All " + MOCK.runs.length + " runs are removed from this list. Files they saved stay in Prism Artifacts.", "Clear all", function (ok) { if (ok) remove(MOCK.runs.slice()); }, true); };
    render();
  }
  function undo(msg, fn) {
    toastEl.innerHTML = esc(msg) + ' <button class="undo">Undo</button>'; toastEl.classList.add("on");
    $(".undo", toastEl).onclick = function () { fn(); toastEl.classList.remove("on"); };
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.classList.remove("on"); }, 5000);
  }

  /* ═════════════════════════ ARTIFACTS ═════════════════════════ */
  function artifactsInit() {
    var box = $("#art-list");
    var KIND = { sheet: ["sheet", "Spreadsheet"], pdf: ["file", "PDF"], image: ["eye", "Image"], video: ["video", "Video"], doc: ["file", "Document"] };
    function render() {
      if (!MOCK.artifacts.length) { box.innerHTML = $("#art-empty").innerHTML; return; }
      var days = []; MOCK.artifacts.forEach(function (a) { if (days.indexOf(a.day) < 0) days.push(a.day); });
      box.innerHTML = days.map(function (d) {
        var as = MOCK.artifacts.filter(function (a) { return a.day === d; });
        return '<div class="day"><h2>' + d + '</h2><span>' + as.length + (as.length === 1 ? " file" : " files") + '</span></div><ul class="card runs arts">' + as.map(function (a) {
          var i = MOCK.artifacts.indexOf(a), th = a.thumb ? '<img src="' + a.thumb + '" alt="">' : a.kind === "image" ? ISO : ic(KIND[a.kind][0]);
          return '<li data-i="' + i + '" tabindex="0"><span class="thumbsm ' + a.kind + '">' + th + '</span><div style="min-width:0"><div class="t">' + esc(a.name) + '</div><div class="m">' + KIND[a.kind][1] + ' · ' + a.size + '</div></div>' +
            '<button class="btn light plain sm open">' + ic("ext") + 'Open</button><button class="iconbtn more" title="More">' + ic("more") + '</button></li>';
        }).join("") + '</ul>';
      }).join("");
      $$("li[data-i]", box).forEach(function (li) {
        var a = MOCK.artifacts[+li.dataset.i];
        li.onclick = function (e) {
          if (e.target.closest(".more")) {
            menu(e.target.closest(".more"), [{ label: "Open", icon: "ext", on: function () { openA(a); } }, { label: "Show in folder", icon: "folder", on: function () { toast("Showed " + a.name + " in your file manager"); } },
              { label: "Copy the path", icon: "file", on: function () { toast("Copied: Desktop/Prism Artifacts/" + a.name); } }, { sep: 1 },
              { label: "Delete the file", icon: "trash", on: function () { ask("Delete " + a.name + "?", "The file is moved to your computer's bin. You can restore it from there.", "Delete", function (ok) { if (ok) { MOCK.artifacts.splice(MOCK.artifacts.indexOf(a), 1); render(); toast("Moved to the bin"); } }, true); } }]);
            return;
          }
          openA(a);
        };
        li.onkeydown = function (e) { if (e.key === "Enter") openA(a); };
      });
    }
    function openA(a) {
      if (a.kind === "video") { video(a.out === "motion" ? "media/prism-story.mp4" : "media/reel.mp4", a.name, a.thumb); return; }
      info(esc(a.name), KIND[a.kind][1] + " · " + a.size + " · Desktop / Prism Artifacts", KIND[a.kind][0], '<div class="out filled">' + outFor(a.out) + '</div>', "mid");
    }
    $("#art-folder").onclick = function () { toast("Opened Desktop / Prism Artifacts in your file manager"); };
    render();
  }

  /* ═════════════════════════ SETTINGS ═════════════════════════ */
  var SECTIONS = {
    licence: ["Licence", "What this copy is licensed for, which add-ons come with it, and until when."],
    profile: ["Profile", "Who this copy files its work under, and where that work is kept."],
    agents: ["Agents", "Your Groq key and one tool per kind of step — the router suggests, you decide — plus where each one signs in."],
    language: ["Language", "Prism's own words, and — separately — what the AI tools write back in."],
    status: ["Connections", "Everything else Prism has to be able to reach: your browser, your team folder."],
    appearance: ["Appearance", "Dark or light mode, background wallpaper, card glassmorphism and visual effects."],
    privacy: ["Privacy & data", "Where your work is written, who else can read it, and every folder Prism keeps."],
    more: ["Help & contact", "Get help, contact Alphakore, or read the legal terms."]
  };
  function kv(rows) { return '<div class="kv">' + rows.map(function (r) { return '<div class="r"><span class="k">' + r[0] + '</span><span class="v">' + r[1] + '</span></div>'; }).join("") + '</div>'; }
  function sec(t, p, body) { return '<div class="sec"><h2>' + t + '</h2>' + (p ? '<p>' + p + '</p>' : "") + body + '</div>'; }
  function lbtn(id, label, icon, cls) { return '<button class="btn light plain sm ' + (cls || "") + '" id="' + id + '">' + (icon ? ic(icon) : "") + label + '</button>'; }
  function dbtn(id, label) { return '<button class="btn dark sm" id="' + id + '">' + pix("parrow") + label + '</button>'; }
  var SET = { name: "Parth", what: "Spring manufacturer — sales and quotations", groq: "gsk_••••••••••••••••3f9a", or: "", members: [["Ravi Patel", "Estimator"], ["Nidhi Shah", "Sales coordinator"]], wall: "stone", effects: true,
              lang: "English", out: "Same as I asked in", agents: { "Planning": "Groq — Llama 3.3", "Research": "Perplexity", "Writing": "Claude", "Files & images": "ChatGPT", "Video": "Prism Studio", "E-mail verification and finding": "Prism Leads" } };
  var INCL = ["Attendance", "BOM", "BOQ", "Email Inquiries", "Email Outreach", "Gerber", "Leads & Outreach", "Reel & Studio", "STEP", "WhatsApp"];
  function settingsHTML(key) {
    if (key === "licence") return sec("Licence", SECTIONS.licence[1],
        kv([["Licensed to", "Parth"], ["Plan", "Prism Complete"], ["Seats", '<span class="mono">2</span>'], ["Renews", '01 September 2027<span class="mono"> · 302 days left</span>'], ["Status", '<span class="st ok">Active</span>']]) +
        '<div class="who4"><div class="label">Who this plan is for</div><p>Studio plus every add-on — the whole product</p></div>') +
      sec("What's included", "The add-ons and features your current licence plan covers.", '<ul class="inc">' + INCL.map(function (n) { return '<li><span class="ck2">' + ic("check") + '</span><b>' + n + '</b><span class="st ok">Included</span></li>'; }).join("") + '</ul>') +
      sec("Careful with these", "", '<div class="btnrow">' + lbtn("s-key", "Change licence key", "key") + lbtn("s-release", "Release this computer's seat", "x", "danger") + '</div>');
    if (key === "profile") return sec("Profile", SECTIONS.profile[1],
        '<div class="fgrid"><label>Name</label><div class="line"><input class="field2" id="s-name" value="' + esc(SET.name) + '"></div>' +
        '<label>What you do</label><input class="field2" id="s-what" placeholder="e.g. indie game dev, startup marketer…" value="' + esc(SET.what) + '">' +
        '<label>Role</label><span class="val">Personal copy</span><label>Member folder</label><span class="val mono">~/Prism Workspace/parth</span></div>' +
        '<div class="btnrow">' + dbtn("s-save-prof", "Save") + '</div>') +
      sec("Company designation key", "Paste the key your company gave you to file work under the team.", '<div class="line"><input class="field2" id="s-desig" placeholder="PRSD1.… — paste your designation key">' + lbtn("s-apply", "Apply") + '</div>') +
      sec("Team workspace", "A shared folder everyone's work is filed into.", '<div class="line"><input class="field2" id="s-ws" value="\\\\NAS\\Kinetic\\Prism" readonly>' + lbtn("s-choose", "Choose…", "folder") + '</div>') +
      sec("Team members", "Everyone this copy has a designation key for.", '<ul class="inc" id="s-members"></ul><div class="line" style="margin-top:.6rem"><input class="field2" id="s-mname" placeholder="Name, e.g. Ravi Patel"><select class="sel" id="s-mrole"><option>Estimator</option><option>Sales coordinator</option><option>Production planner</option><option>Owner</option></select>' + lbtn("s-madd", "Add a team member", "plus") + '</div>') +
      sec("Bring my settings from my normal Prism", "Copy keys, agents and favourites from the Prism you use day to day.", '<div class="ckrow"><label><input type="checkbox" class="ck" checked> AI keys</label><label><input type="checkbox" class="ck" checked> Agents</label><label><input type="checkbox" class="ck"> Favourites</label><label><input type="checkbox" class="ck"> Email inquiry settings</label></div><div class="btnrow">' + dbtn("s-copy", "Copy now") + '</div>');
    if (key === "agents") return sec("Agents", SECTIONS.agents[1],
        '<div class="fgrid"><label>Groq key</label><div class="line"><input class="field2 mono" id="s-groq" value="' + esc(SET.groq) + '">' + lbtn("s-groq-save", "Save") + '</div>' +
        '<label>OpenRouter key</label><div class="line"><input class="field2 mono" id="s-or" placeholder="sk-or-… (for Prism Agent Claude and Prism Agent Deep)">' + lbtn("s-or-save", "Save") + '</div></div><p class="muted small" id="s-keynote"></p>') +
      sec("Your specialists", "One tool per kind of step. The router suggests; you decide.", '<div class="spec">' + Object.keys(SET.agents).map(function (k) {
        var opts = { "Planning": ["Groq — Llama 3.3", "Groq — Kimi"], "Research": ["Perplexity", "ChatGPT", "Claude", "Gemini"], "Writing": ["Claude", "ChatGPT", "Grok", "Gemini", "DeepSeek"], "Files & images": ["ChatGPT", "Claude"], "Video": ["Prism Studio", "Quick templates"], "E-mail verification and finding": ["Prism Leads", "Skipped"] }[k];
        var paid = /Claude|Studio|Leads/.test(SET.agents[k]);
        return '<div class="r"><span>' + k + '</span><select class="sel">' + opts.map(function (o) { return "<option" + (o === SET.agents[k] ? " selected" : "") + ">" + o + "</option>"; }).join("") + '</select><span class="tag">' + (paid ? "Paid" : "Free") + '</span></div>';
      }).join("") + '</div><div class="btnrow">' + dbtn("s-agents-save", "Save") + lbtn("s-tools", "Open the AI tools screen", "grid") + lbtn("s-login", "Open login tabs", "ext") + '</div>');
    if (key === "language") return sec("Language", SECTIONS.language[1],
        '<div class="fgrid"><label>Prism\'s language</label><select class="sel" id="s-lang"><option>English</option><option>हिन्दी — Hindi</option><option>ગુજરાતી — Gujarati</option><option>मराठी — Marathi</option></select>' +
        '<label>AI writes back in</label><select class="sel" id="s-out"><option>Same as I asked in</option><option>English</option><option>हिन्दी — Hindi</option><option>ગુજરાતી — Gujarati</option></select></div><div class="btnrow">' + dbtn("s-lang-save", "Save") + '</div>') +
      sec("Language packs on this copy", "", '<ul class="inc">' + [["English", "Complete", "In use"], ["हिन्दी — Hindi", "96% translated", ""], ["ગુજરાતી — Gujarati", "91% translated", ""], ["मराठी — Marathi", "74% translated", ""]].map(function (l) {
        return '<li><b>' + l[0] + '</b><span class="mono muted">' + l[1] + '</span>' + (l[2] ? '<span class="st ok">' + l[2] + '</span>' : "") + '</li>'; }).join("") + '</ul>');
    if (key === "status") return sec("Connections", SECTIONS.status[1],
        kv([["Browser automation", '<span class="st ok">Ready</span>'], ["Chrome version", '<span class="mono">142.0.7444.59</span>'], ["Prism's browser profile", "Created"], ["Your logins copied in", "Yes"], ["Team folder", '<span class="st ok">Reachable</span>']]) +
        '<div class="fgrid" style="margin-top:.8rem"><label>Chrome</label><div class="line"><input class="field2 mono" id="s-chrome" placeholder="blank = auto-detect">' + lbtn("s-detect", "Detect", "search") + '</div></div>' +
        '<div class="btnrow">' + lbtn("s-copylog", "Copy my Chrome logins again", "clock") + lbtn("s-closebr", "Close Prism's browser", "x") + '</div>');
    if (key === "appearance") return sec("Dashboard wallpaper", "Choose one of the Prism wallpapers, upload your own image, or keep the clean default.",
        '<div class="walls">' + [["stone", "AlphaKore stone (default)"], ["dots", "Dot field"], ["spectrum", "Prism spectrum"], ["ink", "Warm grey"]].map(function (w) {
          return '<button class="wall ' + w[0] + (SET.wall === w[0] ? " on" : "") + '" data-w="' + w[0] + '"><i></i><span>' + w[1] + '</span></button>'; }).join("") + '</div>' +
        '<div class="btnrow">' + lbtn("s-wall-own", "Choose custom wallpaper…", "folder") + '</div>') +
      sec("Mode and effects", "", '<div class="fgrid"><label>Mode</label><div class="pseg sm"><button class="on">Light</button><button disabled title="Dark mode is not in this preview yet — AlphaKore\'s brand is light-first">Dark</button></div>' +
        '<label>Visual effects</label><label class="switch big"><input type="checkbox" id="s-fx" checked><i></i><span>Soft shadows and button motion</span></label></div>');
    if (key === "privacy") return sec("Where Prism saves your files", SECTIONS.privacy[1],
        kv([["Your work is written to", '<span class="mono">~/Prism Workspace/parth</span>'], ["This folder is", "On this computer only"], ["Filed under", "Parth · Personal copy"], ["Prism's own folder", '<span class="mono">~/.prism</span>'],
            ["Generated files (Reel, images, documents)", '<span class="mono">~/Desktop/Prism Artifacts</span>'], ["Log files on disk", '<span class="mono">212 KB of at most 5,120 KB</span>']]) +
        '<div class="btnrow">' + lbtn("s-openws", "Open the folder", "folder") + lbtn("s-logs", "Open the logs", "file") + '</div>') +
      sec("Uninstall Prism", "Removes the app. Your work folders stay unless you tick them.", '<div class="btnrow">' + lbtn("s-uninst", "Uninstall…", "trash", "danger") + '</div>');
    return sec("Updates", "", '<div class="line" id="s-upd"><span class="muted">Prism 1.6.13</span>' + lbtn("s-check", "Check for updates", "clock") + '</div>') +
      sec("Ask Lumi", "Lumi answers from the Prism guide, right inside the app.", '<div class="btnrow">' + dbtn("s-lumi", "Open Lumi") + '</div>') +
      sec("Book a meeting with AlphaKore", "Schedule a 1-on-1 session with our team", '<div class="btnrow">' + dbtn("s-meet", "Book a meeting") + '</div>') +
      sec("Contact", "", kv([["Email us", '<a class="link" href="mailto:contacts@alphakore.org">contacts@alphakore.org</a>'], ["Call us", '<span class="mono">+91 xxxxx xxxxx</span>'], ["Website", '<a class="link" href="https://www.alphakore.org" target="_blank" rel="noopener">alphakore.org</a>'], ["Version", '<span class="mono">1.6.13</span>']]) +
        '<div class="btnrow">' + lbtn("s-terms", "Terms of Use", "file") + lbtn("s-privacy", "Privacy Policy", "lock") + '</div>');
  }
  function settingsWire(key, body) {
    var on = function (id, fn) { var e = $("#" + id, body); if (e) e.onclick = fn; };
    on("s-key", function () { form("Change licence key", "Paste the new key AlphaKore sent you.", "key", '<input class="field2 mono" id="f-key" placeholder="PRISM-XXXX-XXXX-XXXX-XXXX">', "Apply", function (m) { var v = $("#f-key", m).value.trim(); if (v.length < 8) { toast("That key looks too short"); return false; } toast("Key checked with AlphaKore — your plan is unchanged"); }); });
    on("s-release", function () { ask("Release this computer's seat?", "Prism will sign out on this computer and the seat becomes free for another one. Your files stay.", "Release the seat", function (ok) { if (ok) toast("Preview only — the seat was not released"); }, true); });
    on("s-save-prof", function () { SET.name = $("#s-name", body).value; SET.what = $("#s-what", body).value; $(".me .who b").textContent = SET.name || "Parth"; $(".avatar").textContent = (SET.name || "P")[0].toUpperCase(); toast("Saved."); });
    on("s-apply", function () { var v = $("#s-desig", body).value.trim(); toast(v ? "Designation key applied — work is now filed under Kinetic Springs" : "Paste a designation key first"); });
    on("s-choose", function () { menu(this, [["\\\\NAS\\Kinetic\\Prism"], ["~/Dropbox/Kinetic Prism"], ["D:\\Shared\\Prism"]].map(function (p) { return { label: esc(p[0]), icon: "folder", on: function () { $("#s-ws", body).value = p[0]; toast("Saved."); } }; }), "Choose the team workspace folder"); });
    function members() { $("#s-members", body).innerHTML = SET.members.map(function (m, i) { return '<li><span class="avatar sm">' + m[0][0] + '</span><b>' + esc(m[0]) + '</b><span class="tag">' + esc(m[1]) + '</span><button class="iconbtn" data-rm="' + i + '" title="Remove ' + esc(m[0]) + '">' + ic("trash") + '</button></li>'; }).join("");
      $$("[data-rm]", body).forEach(function (b) { b.onclick = function () { var m = SET.members.splice(+b.dataset.rm, 1)[0]; members(); toast("Removed " + m[0]); }; }); }
    if ($("#s-members", body)) members();
    on("s-madd", function () { var n = $("#s-mname", body).value.trim(); if (!n) { toast("Enter the person's name."); return; } SET.members.push([n, $("#s-mrole", body).value]); $("#s-mname", body).value = ""; members(); toast(n + " added."); });
    on("s-copy", function () { var b = this; setOff(b, "Copying…"); setTimeout(function () { setOff(b, ""); toast("Copied: AI keys, Agents. Restart Prism so everything picks it up."); }, 900); });
    on("s-groq-save", function () { var n = $("#s-keynote", body); n.textContent = "Saved — checking the key with Groq…"; setTimeout(function () { n.textContent = "Saved — Groq accepts this key."; }, 900); });
    on("s-or-save", function () { var v = $("#s-or", body).value.trim(), n = $("#s-keynote", body); if (!v) { n.textContent = "Paste your OpenRouter key first."; return; } n.textContent = "Saved — checking the key with OpenRouter…"; setTimeout(function () { n.textContent = "Saved — OpenRouter accepts this key."; }, 900); });
    on("s-agents-save", function () { toast("Saved."); });
    on("s-tools", function () { toast("Opens the AI tools screen in the app"); });
    on("s-login", function () { toast("Opened login tabs for ChatGPT, Claude and Perplexity in Prism's browser"); });
    on("s-lang-save", function () { toast("Saved. Prism will speak " + $("#s-lang", body).value.split(" — ").pop() + " after a restart."); });
    on("s-detect", function () { var i = $("#s-chrome", body); i.value = "/usr/bin/google-chrome"; toast("Found Chrome 142 at /usr/bin/google-chrome"); });
    on("s-copylog", function () { toast("Copied your Chrome logins into Prism's browser"); });
    on("s-closebr", function () { toast("Prism's browser is closed"); });
    $$(".wall", body).forEach(function (w) { w.onclick = function () { $$(".wall", body).forEach(function (x) { x.classList.toggle("on", x === w); }); SET.wall = w.dataset.w; document.body.dataset.wall = SET.wall; try { localStorage.setItem("pk-wall", SET.wall); } catch (e) {} toast("Wallpaper changed"); }; });
    on("s-wall-own", function () { pickFile(this, "media", function (f) { toast("Wallpaper set to " + f[0]); }); });
    var fx = $("#s-fx", body); if (fx) fx.onchange = function () { document.body.classList.toggle("nofx", !fx.checked); toast(fx.checked ? "Effects on" : "Effects off — flatter, faster"); };
    on("s-openws", function () { toast("Opened ~/Prism Workspace/parth in your file manager"); });
    on("s-logs", function () { toast("Opened ~/.prism/logs"); });
    on("s-uninst", function () { ask("Uninstall Prism?", "Prism is removed from this computer. Tick nothing else and your work folders stay exactly where they are.", "Uninstall", function (ok) { if (ok) toast("Preview only — nothing was uninstalled"); }, true); });
    on("s-check", function () { var box = $("#s-upd", body); box.innerHTML = '<span class="muted">Checking…</span>'; setTimeout(function () { box.innerHTML = '<span class="st ok">Up to date</span><span class="muted">You have the latest version of Prism.</span>'; }, 1000); });
    on("s-lumi", function () { window.openLumi(); });
    on("s-meet", function () { window.open("https://calendly.com/alpha-kore25/new-meeting", "_blank", "noopener"); });
    on("s-terms", function () { window.open("https://www.alphakore.org/terms.html", "_blank", "noopener"); });
    on("s-privacy", function () { info("Privacy Policy", "Prism by AlphaKore", "lock", '<div class="doc"><p>Prism runs on your computer. Drawings, Gerber files and 3D models are measured here and never uploaded. Text you send to an AI tool goes to that tool under your own account.</p><p class="muted small">Full policy: PRIVACY_POLICY.md in the app folder.</p></div>', "sm"); });
  }
  function settingsInit() {
    var body = $("#sec-body");
    function show(key) {
      if (!SECTIONS[key]) key = "licence";
      body.innerHTML = settingsHTML(key); settingsWire(key, body); $(".scontent").scrollTop = 0;
      $$(".snav .navi").forEach(function (b) { b.classList.toggle("on", b.dataset.sec === key); });
    }
    $$(".snav .navi").forEach(function (b) { b.onclick = function () { history.replaceState(null, "", "#" + b.dataset.sec); show(b.dataset.sec); }; });
    var SEARCH = { licence: "license activate activation plan seat subscription expiry key", profile: "name company team workspace folder shared designation member", agents: "ai api key groq openrouter tools models login credentials specialist",
      language: "translation output language hindi gujarati marathi", status: "connection browser chrome drive sync login", appearance: "theme dark light wallpaper display effects", privacy: "data files storage privacy folders uninstall logs", more: "help meeting contact email phone legal support update lumi" };
    $(".snav input").addEventListener("input", function () { var q = this.value.toLowerCase().trim();
      $$(".snav .navi").forEach(function (b) { b.hidden = q && (SECTIONS[b.dataset.sec][0] + " " + SEARCH[b.dataset.sec]).toLowerCase().indexOf(q) < 0; }); });
    $("#s-meeting").onclick = function () { window.open("https://calendly.com/alpha-kore25/new-meeting", "_blank", "noopener"); };
    show(location.hash.slice(1));
  }

  /* ═════════════════════════ BOQ / BOM — four easy steps ═════════════════════════
     For people who have never used AI (owner, 2026-11-03), following Hitarth's rules in
     prism_gui/BOQ-CHANGES-TODO.md (item numbers in the comments):
       1 What you have → 2 Check the count → 3 Make the BOQ → 4 Add prices (prices only once a BOQ exists, item 10). */
  function money(v) { return "₹" + Math.round(v).toLocaleString("en-IN"); }
  function boqInit(mode) {
    var d = $("#make"), noun = mode === "bom" ? "BOM" : "BOQ", what = mode === "bom" ? "parts" : "items";
    var ta = $("#w-ask"), next = $("#w-next"), back = $("#w-back"), skip = $("#w-skip"), out = $(".js-out", d);
    var FALLBACK = ["Claude", "Kimi 2.6"];   // addons/boq/agents.py FALLBACK_ORDER (item 2, 24)
    var st = { step: 1, reached: 1, files: [], sample: "", ext: "", rows: null, fromText: false, counted: false, unit: "m", how: "count",
               priceMode: "", rates: null, rateName: "", cont: 0, gst: 18, igst: false, made: false, priced: false, verified: false, rev: 1, change: "", hvacRun: false };
    function drawing() { return st.files.filter(function (f) { return /Drawing/.test(f[1]); })[0]; }
    function isPdf() { var f = drawing(); return f && /\.pdf$/i.test(f[0]); }
    // item 12b / 26: HVAC rules and the HVAC PDF takeoff engage only when the request itself says HVAC
    function hvac() { return mode === "boq" && /hvac/i.test(ta.value); }
    function writer() { return $("#d-writer").value; }
    function unitOf(r) { return r[6] === "cnt" ? "nos" : r[6] === "area" ? "m²" : "m"; }
    function qty(r) { return r[6] === "cnt" ? r[5] : Math.round(r[5] * 10) / 10; }
    function show(r) { var q = qty(r); if (r[6] === "len" && st.unit === "ft") return [(Math.round(q * 3.28084 * 10) / 10).toLocaleString("en-IN"), "ft"];
      if (r[6] === "area" && st.unit === "ft") return [(Math.round(q * 10.7639)).toLocaleString("en-IN"), "ft²"]; return [q.toLocaleString("en-IN"), unitOf(r)]; }
    function totals() { var sub = 0; (st.rows || []).forEach(function (r) { var rate = st.rates && st.rates[r[2]]; if (rate) sub += rate * qty(r); });
      var cont = sub * st.cont / 100, gst = (sub + cont) * st.gst / 100; return { sub: sub, cont: cont, gst: gst, total: sub + cont + gst }; }
    function fname(priced) { return noun + " — " + (ta.value.trim() || (drawing() ? drawing()[0].replace(/\.\w+$/, "") : "new")).slice(0, 36) + (st.rev > 1 ? " v" + st.rev : "") + (priced ? " (priced)" : "") + ".xlsx"; }

    /* ── navigation ── */
    function go(n) {
      st.step = n; st.reached = Math.max(st.reached, n);
      $$(".wstep", d).forEach(function (s) { s.hidden = +s.dataset.step !== n; });
      $$(".wsn", d).forEach(function (b) { var k = +b.dataset.go; b.classList.toggle("on", k === n); b.classList.toggle("done", k < st.reached && k !== n);
        if (k <= st.reached) { b.disabled = false; b.removeAttribute("title"); } else { b.disabled = true; b.title = "Finish the step before first"; } });
      $(".db", d).scrollTop = 0;
      if (n === 2) step2(); if (n === 3) step3(); if (n === 4) step4();
      foot();
    }
    $$(".wsn", d).forEach(function (b) { b.onclick = function () { if (!b.disabled) go(+b.dataset.go); }; });
    function foot() {
      back.hidden = st.step === 1; skip.hidden = !(st.step === 3 && st.made);
      skip.innerHTML = "Finish without prices";
      if (st.step === 1) {
        var why = "";
        if (!ta.value.trim() && !drawing()) why = st.ext ? "Say in one line what the " + noun + " is for — e.g. \"" + MOCK.examples[mode][0] + "\"" : "Add a drawing or describe the job first";
        next.innerHTML = pix("parrow") + (drawing() || st.ext ? "Next: count it" : "Next: list the " + what); setOff(next, why);
      }
      if (st.step === 2) { next.innerHTML = pix("parrow") + "Next: make the " + noun; setOff(next, st.counted ? "" : "Prism is still counting"); }
      if (st.step === 3) { next.innerHTML = pix("parrow") + "Next: add prices"; setOff(next, st.made ? "" : "Make the " + noun + " first — prices are added to it afterwards"); }
      if (st.step === 4) { next.innerHTML = pix("pcheck") + "Done"; setOff(next, st.priceMode && st.priceMode !== "none" && !st.priced ? "Press \"Add these prices to my " + noun + "\" first, or pick No prices" : ""); }
    }
    next.onclick = function () {
      if (next.disabled) return;
      if (st.step === 1) { if (st.reached < 2 || st.dirty) { st.counted = false; st.rows = null; st.made = false; st.reached = 2; } st.dirty = false; go(2); }
      else if (st.step === 2) go(3);
      else if (st.step === 3) go(4);
      else { hideModal(d); toast("Your " + noun + " is saved in Prism Artifacts"); }
    };
    back.onclick = function () { go(Math.max(1, st.step - 1)); };
    skip.onclick = function () { hideModal(d); toast("Saved " + fname(false) + " in Prism Artifacts — you can add prices later"); };

    /* ── step 1: what you have ── */
    var ex = $("#w-ex");
    MOCK.examples[mode].forEach(function (t) { var b = document.createElement("button"); b.className = "chip sm"; b.textContent = t; b.onclick = function () { ta.value = t; ta.dispatchEvent(new Event("input")); }; ex.appendChild(b); });
    function hvacUi() { var on = hvac(); var n = $("#w-hvac"); if (n) n.hidden = !on; var li = $("#w-takeoff-li"); if (li) li.hidden = !on; var tk = $("#d-takeoff"); if (tk) tk.hidden = !on; if (on) $("#d-industry").value = "HVAC"; }
    ta.addEventListener("input", function () { st.dirty = true; hvacUi(); foot(); });
    $(".js-speak", d).onclick = function () { speak(this, ta, mode, function () { hvacUi(); foot(); }); };
    function addDrawing(f) {
      st.files = st.files.filter(function (x) { return !/Drawing/.test(x[1]); }); st.files.push(f); st.dirty = true;
      var h = $("#w-files"); h.innerHTML = "";
      h.appendChild(fileChip(f, function () { st.files = st.files.filter(function (x) { return x !== f; }); $("#w-drop").classList.remove("has"); $(".droptx b", d).textContent = "Add your drawing"; st.dirty = true; foot(); }));
      $("#w-drop").classList.add("has"); $(".droptx b", d).textContent = "Drawing added"; $(".droptx p", d).textContent = f[0] + " — Prism will measure it on this computer.";
      $("#w-choose").innerHTML = pix("pplus") + "Change drawing";
      foot(); toast("Added " + f[0]);      // no industry guessed from the file name (item 12b)
    }
    $("#w-choose").onclick = function () { pickFile(this, "drawing", addDrawing, "Choose your drawing"); };
    $("#w-drop").addEventListener("click", function (e) { if (e.target === this || e.target.closest(".droptx,.dropic")) $("#w-choose").click(); });
    // item 9: the sample is a style reference only, kept apart from the drawing; the hint turns into a confirmation
    $("#w-sample").onclick = function () { pickFile(this, "sample", function (f) { st.sample = f[0]; $("#w-samplename").textContent = "✓ " + f[0] + " — used for the look only; your drawing is not sent with it"; toast("Prism will copy the look of " + f[0]); }, "Your company's " + noun); };
    $("#w-dwg").onclick = function () { info("My drawing is a .dwg file", "Two clicks in AutoCAD and you're ready", "help", '<div class="doc"><ol class="sum"><li>Open the drawing in AutoCAD.</li><li>Choose <b>File → Save As</b>.</li><li>Pick <b>AutoCAD DXF</b> as the type and save.</li><li>Add that .dxf file here.</li></ol><p class="muted small">Most other CAD programs have the same "Save as DXF" option. Prism measures DXF directly; a .dwg needs an extra converter this computer does not have.</p></div>', "sm"); };
    // item 18: paste or upload measurements — the request still says what the BOQ is for
    $("#d-meas").onclick = function () {
      form("I already have some measurements", "Type or paste them, one per line. Prism uses them exactly as given.", "clip",
        '<textarea class="ta" id="f-meas" rows="7" placeholder="For example:&#10;Duct run, level 3 — 42.5 m&#10;Floor height — 3.2 m&#10;Number of floors — 14"></textarea><div class="row" style="margin-top:.6rem"><button class="chip" id="f-up">' + ic("clip") + 'Upload a file…</button><span class="muted small" id="f-upname"></span></div>',
        "Use these measurements", function (m) { var v = $("#f-meas", m).value.trim(); if (!v) { toast("Paste some measurements, or upload a file, first."); return false; }
          st.ext = v; st.dirty = true; $("#d-ext").hidden = false; $("#d-extview").textContent = v; $("#d-extmsg").textContent = "Loaded: " + v.split("\n").filter(Boolean).length + " measurements — Prism uses them as given."; foot();
          toast(ta.value.trim() ? "Measurements added" : "Measurements added — now say in one line what the " + noun + " is for"); if (!ta.value.trim()) ta.focus(); });
      $("#f-up").onclick = function () { pickFile(this, "doc", function (f) { $("#f-upname").textContent = "Loaded: " + f[0]; $("#f-meas").value = "Duct run, level 3 — 42.5 m\nFloor height — 3.2 m\nNumber of floors — 14\nShaft height — 46.0 m"; }, "Text, JSON or CSV"); };
    };
    $("#d-hist").onclick = function () {
      menu(this, MOCK.runs.filter(function (r) { return r.tool === noun; }).concat([{ title: noun === "BOQ" ? "BOQ for CCTV, cabling and fibre — Vraj site" : "BOM for one 36x24 jaw crusher", day: "Last week", when: "" }])
        .map(function (r) { return { label: esc(r.title.slice(0, 54)), hint: r.day + " " + r.when, icon: "clock", on: function () {
          ta.value = r.title; hvacUi(); st.rows = rowsFor(); st.counted = true; st.made = true; st.reached = 3; go(3); toast("Opened the past " + noun); } }; }), "Your past " + noun + "s");
    };
    var tk = $("#d-takeoff"); if (tk) tk.onclick = function () { takeoff(); };
    var tk2 = $("#w-takeoff"); if (tk2) tk2.onclick = function () { takeoff(); };

    /* ── step 2: check what Prism counted (item 13: red = a person must check, yellow = worth a look) ── */
    function rowsFor() {
      var rows = MOCK.measured[mode].map(function (r) { return r.slice(); });
      // without "HVAC" in the request the duct-pairing rule does not run, so it flags nothing (item 12b)
      if (mode === "boq" && !hvac()) rows.forEach(function (r) { if (r[4] === "M-DUCT-RETURN") r[0] = "ok"; });
      return rows;
    }
    var REASON_OFF = "The HVAC duct-pairing rule did not run — your request doesn't say HVAC.";
    function step2() {
      var s = $("#w-s2");
      if (!st.counted) {
        st.hvacRun = hvac();
        var src = drawing() ? "Reading " + drawing()[0] : st.ext ? "Reading your measurements" : "Working out the " + what + " from your description";
        s.innerHTML = '<h3 class="wq">Counting…</h3><p class="wsub">' + esc(src) + '. This happens on this computer.</p><div class="out"></div>';
        stages($(".out", s), drawing() ? ["Opening your drawing", "Counting and measuring every " + (mode === "bom" ? "part" : "item"), st.hvacRun ? "Applying the HVAC drawing rules (your request says HVAC)" : "Checking for anything unusual"] : ["Reading what you wrote", "Listing the " + what + " a job like this needs"], function () {
          st.rows = rowsFor(); st.fromText = !drawing() && !st.ext;
          if (st.fromText) st.rows.forEach(function (r) { r[0] = "ok"; });
          st.counted = true; step2(); foot();
        }, 650);
        foot(); return;
      }
      var must = st.rows.filter(function (r) { return r[0] === "bad"; }), worth = st.rows.filter(function (r) { return r[0] === "warn"; }), good = st.rows.filter(function (r) { return r[0] === "ok" || r[0] === "edit"; });
      var flagged = must.concat(worth);
      var card = function (r) { var i = st.rows.indexOf(r), v = show(r), m = r[0] === "bad";
        return '<div class="lookcard' + (m ? " must" : "") + '" data-i="' + i + '"><div class="lc1"><span class="st ' + (m ? "err" : "warn") + '">' + (m ? "You must check" : "Worth a look") + '</span><b>' + esc(r[2]) + '</b><span class="big3 mono">' + v[0] + ' <small>' + v[1] + '</small></span></div>' +
          '<p>' + esc(MOCK.plain[r[4]] || "Prism isn't sure about this one.") + '</p><div class="row"><button class="btn dark sm" data-ok="' + i + '">' + pix("pcheck") + 'Yes, it\'s right</button><button class="btn light plain sm" data-chg="' + i + '">' + ic("pencil") + 'Change the number</button></div></div>'; };
      s.innerHTML = '<h3 class="wq">' + (st.fromText ? "Here is what a job like this needs" : "Prism found " + st.rows.length + " " + what) + '</h3>' +
        '<p class="wsub">' + (st.fromText ? "These are estimates from your description — check the numbers, change any that are wrong." :
          (must.length ? '<b class="errc">' + must.length + ' you must check</b>' : "") + (must.length && worth.length ? " · " : "") + (worth.length ? '<b class="warnc">' + worth.length + ' worth a look</b>' : "") + (flagged.length ? ". The rest look right." : "Everything looks right.")) + '</p>' +
        (mode === "boq" && !st.fromText ? (st.hvacRun ? '<div class="hvacon">' + ic("check") + 'HVAC drawing rules were used — your request says HVAC.</div>' : '<div class="muted small">' + ic("help") + REASON_OFF + ' Add the word HVAC to your request in step 1 if this is an HVAC drawing.</div>') : "") +
        (isPdf() && st.hvacRun ? '<div class="tipcard">' + ic("help") + '<div><b>This drawing is a PDF</b><p>For duct lengths to come out right, tell Prism the drawing scale.</p></div><button class="btn light plain sm" id="w-scale">Set the scale</button></div>' : "") +
        (flagged.length ? '<div class="looklist">' + must.map(card).join("") + worth.map(card).join("") + '</div>' : "") +
        '<div class="goodlist"><div class="goodh">' + ic("check") + '<b>' + (st.fromText ? good.length + " estimated " + what : good.length + ' ' + (good.length === 1 ? "looks" : "look") + ' right') + '</b><span class="sp"></span><label class="muted small">Show lengths in <select class="sel" id="w-unit"><option value="m">metres</option><option value="ft">feet</option></select></label></div>' +
        good.map(function (r) { var i = st.rows.indexOf(r), v = show(r);
          return '<div class="goodrow"><span>' + esc(r[2]) + (r[0] === "edit" ? ' <span class="tag">checked by you</span>' : "") + '</span><button class="cellbtn" data-chg="' + i + '" title="Change this number">' + v[0] + ' <small>' + v[1] + '</small></button></div>'; }).join("") + '</div>' +
        '<div class="row"><button class="chip" id="w-full">' + ic("list") + 'See the full table</button><button class="chip" id="w-csv">' + ic("file") + 'Save the count to the Desktop (CSV)</button></div>';
      $("#w-unit").value = st.unit; $("#w-unit").onchange = function () { st.unit = this.value; step2(); };
      $$("[data-ok]", s).forEach(function (b) { b.onclick = function () { st.rows[+b.dataset.ok][0] = "edit"; st.made = false; toast("Thanks — marked as checked by you"); step2(); }; });
      $$("[data-chg]", s).forEach(function (b) { b.onclick = function () { var r = st.rows[+b.dataset.chg];
        form("Change the number", esc(r[2]), "pencil", '<div class="fgrid"><label>The right number</label><div class="line"><input class="field2 mono" id="f-num" value="' + qty(r) + '" inputmode="decimal"><span class="muted">' + unitOf(r) + '</span></div></div>', "Save", function (m) {
          var v = parseFloat($("#f-num", m).value.replace(/,/g, "")); if (!(v >= 0)) { toast("Type a number"); return false; } r[5] = v; r[0] = "edit"; st.made = false; step2(); toast("Saved — " + r[2] + ": " + v + " " + unitOf(r)); }, "sm"); }; });
      var sc = $("#w-scale"); if (sc) sc.onclick = takeoff;
      $("#w-csv").onclick = function () { toast("Saved to your Desktop → " + (drawing() ? drawing()[0].replace(/\.\w+$/, "") : noun) + "-quantities.csv"); };
      $("#w-full").onclick = function () {
        var T = { ok: ["OK", "ok"], warn: ["Look", "warn"], bad: ["Check", "err"], edit: ["Edited", "info"] };
        var ws = MOCK.warnings[mode].filter(function (w) { return st.hvacRun || !/duct-pairing/.test(w); });
        info("The full table", "Everything Prism measured" + (drawing() ? " in " + esc(drawing()[0]) : ""), "list",
          '<div class="mtools"><span class="muted small">All ' + MOCK.allLayers[mode].length + ' layers: ' + MOCK.allLayers[mode].map(esc).join(", ") + '</span></div>' +
          '<button class="warnbar" id="fw">⚠ ' + ws.length + ' rules &amp; warnings ▾</button><ul class="warnlist" id="fwl" hidden>' + ws.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + '</ul>' +
          '<div class="out filled"><div class="tscroll"><table class="tbl"><thead><tr><th>Trust</th><th>Item</th><th>Measured as</th><th>Layer</th><th class="n">Value</th><th>Unit</th></tr></thead><tbody>' +
          st.rows.map(function (r) { var t = T[r[0]]; return '<tr><td><span class="st ' + t[1] + '">' + t[0] + '</span></td><td>' + esc(r[2]) + '</td><td class="u">' + r[3] + '</td><td class="mono small">' + esc(r[4]) + '</td><td class="n">' + qty(r) + '</td><td class="u">' + unitOf(r) + '</td></tr>'; }).join("") +
          '</tbody></table></div></div><div class="row" style="margin-top:.7rem"><button class="chip" data-toast="Saved to your Desktop as CSV">' + ic("file") + 'Save as CSV (Desktop)</button></div>', "wide");
        $("#fw").onclick = function () { var l = $("#fwl"); l.hidden = !l.hidden; };
      };
    }

    /* ── step 3: make the BOQ — two ways, both from the start (item 8) ── */
    function table(priced) {
      var n = 0, sec = "", t = totals();
      return '<div class="tscroll"><table class="tbl"><thead><tr><th class="idx">#</th><th>Item</th><th class="n">Qty</th><th>Unit</th><th class="n">Rate (₹)</th><th class="n">Amount (₹)</th></tr></thead><tbody>' +
        st.rows.map(function (r) { var h = ""; if (r[1] !== sec) { sec = r[1]; h = '<tr class="grp"><td></td><td colspan="5">' + esc(sec) + '</td></tr>'; } n++; var rate = priced && st.rates && st.rates[r[2]];
          return h + '<tr><td class="idx">' + n + '</td><td>' + esc(r[2]) + '</td><td class="n">' + qty(r) + '</td><td class="u">' + unitOf(r) + '</td><td class="n' + (rate ? "" : " nil") + '">' + (rate ? rate.toLocaleString("en-IN") : "—") + '</td><td class="n' + (rate ? "" : " nil") + '">' + (rate ? Math.round(rate * qty(r)).toLocaleString("en-IN") : "—") + '</td></tr>'; }).join("") +
        '</tbody>' + (priced && st.rates ? '<tfoot><tr><td></td><td>Total with ' + (st.gst ? st.gst + '% GST' : 'no GST') + '</td><td></td><td></td><td></td><td class="n">' + Math.round(t.total).toLocaleString("en-IN") + '</td></tr></tfoot>' : '') + '</table></div>';
    }
    // items 2 and 22: a live window for every run, with Stop and "Use another AI"
    function runLive(box, title, lines, done) {
      var stopped = false, fb = 0;
      box.innerHTML = '<div class="live"><div class="liveh"><b>' + title + '</b><span class="sp"></span><span class="mono small muted" id="lv-who">' + esc(writer()) + '</span></div><div class="out" id="lv-out"></div>' +
        '<div class="row"><button class="btn light plain sm" id="lv-fb">' + ic("clock") + 'Taking too long? Use another AI</button><button class="btn light plain sm danger" id="lv-stop">' + ic("x") + 'Stop</button></div></div>';
      stages($("#lv-out", box), lines, function () { if (!stopped) done(); }, 750);
      $("#lv-stop", box).onclick = function () { stopped = true; box.innerHTML = '<div class="tipcard">' + ic("x") + '<div><b>Stopped</b><p>Nothing was changed. ' + (st.made ? "Your last " + noun + " is still there." : "") + '</p></div><button class="btn light plain sm" id="lv-again">Try again</button></div>'; $("#lv-again", box).onclick = function () { step3(); }; foot(); };
      $("#lv-fb", box).onclick = function () { var to = FALLBACK.filter(function (a) { return a !== writer(); })[fb++ % 2]; $("#d-writer").value = to; $("#lv-who", box).textContent = to; toast("Switched to " + to + " — it carries on from where it was"); };
    }
    function step3() {
      var s = $("#w-s3");
      if (!st.made && !s.querySelector(".live")) {
        var card = function (k, icon, t, p, off) { return '<button class="choice2' + (st.how === k ? " on" : "") + '" data-how="' + k + '"' + (off ? ' disabled title="' + esc(off) + '"' : "") + '><span class="ftile">' + ic(icon) + '</span><b>' + t + '</b><p>' + p + '</p></button>'; };
        s.innerHTML = '<h3 class="wq">How should Prism make your ' + noun + '?</h3><p class="wsub">Most people pick the first one.</p><div class="choices two">' +
          card("count", "list", "From the count (recommended)", "Your drawing stays on this computer. Only the checked numbers go to AI to write the " + noun + ".") +
          card("drawing", "eye", "With the drawing", "AI reads the drawing itself as well. Prism asks you first — the drawing leaves this computer only if you say yes.", drawing() ? "" : "Add a drawing in step 1 to use this") + '</div>' +
          '<div class="row"><button class="btn dark" id="w-make">' + pix("parrow") + 'Make my ' + noun + '</button>' + (st.sample ? '<span class="muted small">In the style of ' + esc(st.sample) + '</span>' : "") + '</div>';
        $$("[data-how]", s).forEach(function (b) { b.onclick = function () { if (b.disabled) return; st.how = b.dataset.how; step3(); }; });
        $("#w-make", s).onclick = function () { st.how === "drawing" ? consent(false) : make(false); };
        return;
      }
      if (!st.made) return;
      s.innerHTML = '<div class="donehd"><span class="donei">' + ic("check") + '</span><div><h3 class="wq">Your ' + noun + ' is ready</h3><p class="wsub">' + st.rows.length + ' ' + what + ' · prices are added in the next step' + (st.verified ? ' · checked against the drawing by AI' : '') + '</p></div></div>' +
        '<div class="filecard">' + ic("sheet") + '<div><b>' + esc(fname(false)) + '</b><small>Saved in Prism Artifacts' + (st.sample ? ' · in the style of ' + esc(st.sample) : '') + '</small></div><span class="sp"></span>' +
          '<button class="btn dark sm" id="w-xls">' + pix("parrow") + 'Open in Excel</button><button class="btn light plain sm" id="d-open">' + ic("ext") + 'Open in browser</button><button class="btn light plain sm" id="w-more" title="Other formats and the folder">' + ic("more") + '</button></div>' +
        (st.change ? '<div class="revnote">' + ic("pencil") + 'Version ' + st.rev + ': ' + esc(st.change) + '</div>' : "") +
        '<div class="out filled">' + table(false) + '</div>' +
        '<div class="fu"><div class="label">Want to change something? Just type it</div><div class="line"><input class="field2" id="d-fu-text" placeholder="e.g. split the ductwork floor by floor" aria-label="What should change"><button class="btn dark sm" id="d-fu-send">' + pix("parrow") + 'Change it</button></div>' +
          '<div class="row"><span class="muted small">Ideas:</span>' + ["Split it floor by floor", "Add 5% for wastage", "Group by material"].map(function (x) { return '<button class="chip sm" data-idea="' + x + '">' + x + '</button>'; }).join("") + '</div></div>' +
        (drawing() ? '<div class="tipcard ai">' + ic("eye") + '<div><b>' + (st.verified ? "Checked against the drawing" : "Check it against the drawing?") + '</b><p>' + (st.verified ? "AI read your drawing and checked every line." : "AI reads your drawing and checks every line, then remakes the " + noun + ". Prism asks you first.") + '</p></div>' +
          '<button class="btn light plain sm" id="d-mwd">' + (st.verified ? "Check again" : "Verify and remake") + '</button></div>' : "");
      $("#w-xls").onclick = function () { toast("Opened " + fname(false) + " in Excel"); };
      $("#d-open").onclick = function () { var w = window.open("", "_blank"); if (w) { w.document.write('<title>' + noun + '</title><link rel="stylesheet" href="' + location.href.replace(/[^/]*$/, "") + 'style.css"><body style="padding:2rem;overflow:auto;height:auto">' + $(".out.filled", s).innerHTML + '</body>'); w.document.close(); } else toast("Opened in your browser"); };
      $("#w-more").onclick = function () { menu(this, [["Word document (.docx)", "file"], ["PDF", "file"], ["CSV", "list"]].map(function (f) { return { label: "Save as " + f[0], icon: f[1], on: function () { toast("Saved as " + f[0] + " in Prism Artifacts"); } }; }).concat([{ sep: 1 }, { label: "Show in folder", icon: "folder", on: function () { toast("Opened Prism Artifacts in your file manager"); } }]), "More"); };
      $$("[data-idea]", s).forEach(function (b) { b.onclick = function () { $("#d-fu-text").value = b.dataset.idea; $("#d-fu-text").focus(); }; });
      function change() { var v = $("#d-fu-text").value.trim(); if (!v) { toast("Type what should change first"); $("#d-fu-text").focus(); return; }
        st.made = false; foot(); runLive(s, "Changing your " + noun + "…", ["Carrying your follow-up on — " + writer(), "Saving it as a new file"], function () { st.change = v; st.rev++; st.made = true; step3(); foot(); toast("Done — saved as " + fname(false)); }); }   // item 4: new file shown
      $("#d-fu-send").onclick = change; $("#d-fu-text").onkeydown = function (e) { if (e.key === "Enter") change(); };
      var mw = $("#d-mwd", s); if (mw) mw.onclick = function () { consent(true); };
    }
    function make(again) {
      var s = $("#w-s3"); st.made = false; foot();
      var lines = ["Putting the " + what + " in order"]; if ($("#d-research").value !== "No research") lines.push("Checking the standards that apply — " + $("#d-research").value);
      lines.push("Writing your " + noun + (st.sample ? " in your company's format" : "") + " — " + writer()); lines.push("Saving it as a spreadsheet");
      runLive(s, "Making your " + noun + "…", lines, function () { st.made = true; step3(); foot(); toast("Done. Check the numbers against the drawing and the saved file.");
        MOCK.runs.unshift({ id: "n" + Date.now(), day: "Today", when: "now", title: ta.value || noun + " from " + (drawing() || ["your measurements"])[0], tool: noun, by: writer(), status: "ok", out: mode, icon: mode === "bom" ? "box" : "sheet" }); });
    }
    // item 32: off by default, explicit permission every time the drawing would leave the computer
    function consent(verify) {
      ask("Send your drawing to AI?", "Prism will send " + drawing()[0] + " to " + writer() + " so it can read the drawing itself" + (verify ? " and check every line of your " + noun : "") + ". Until now the drawing has not left this computer. Is that OK?", "Yes, send it", function (ok) {
        if (!ok) { toast("Nothing was sent"); return; }
        var s = $("#w-s3"); st.made = false; foot();
        runLive(s, verify ? "Verifying against the drawing…" : "Making your " + noun + " from the drawing…", ["Sending your drawing to " + writer(), verify ? "Checking every line against it" : "Reading the drawing and the count together", "Writing the " + noun], function () {
          st.verified = true; if (verify) { st.rev++; st.change = "checked against the drawing"; } st.made = true; step3(); foot(); toast(verify ? "Verified against the drawing — saved as " + fname(false) : "Made with the drawing"); });
      });
    }

    /* ── step 4: add prices — only now that the BOQ exists (item 10) ── */
    function step4() {
      var s = $("#w-s4");
      var card = function (k, icon, t, p) { return '<button class="choice2' + (st.priceMode === k ? " on" : "") + '" data-pm="' + k + '"><span class="ftile">' + ic(icon) + '</span><b>' + t + '</b><p>' + p + '</p></button>'; };
      var html = '<h3 class="wq">Add prices to your ' + noun + '?</h3><p class="wsub">Optional. Prism fills them into the ' + noun + ' you just made.</p><div class="choices">' +
        card("mine", "sheet", "Use my price list", st.priceMode === "mine" && st.rateName ? "✓ " + esc(st.rateName) : "Pick your rate sheet (Excel, PDF or Word).") +
        card("starter", "spark", "Use typical prices", "Good for a first estimate. Check them before you send a quote.") +
        card("none", "x", "No prices", "Leave the price columns empty for you to fill.") + '</div>';
      if (st.rates && st.priceMode !== "none") {
        var t = totals(), miss = 0;
        html += '<div class="pricelist"><div class="goodh">' + ic("bars") + '<b>Prices</b><span class="sp"></span><span class="muted small">Click a price to change it</span></div>' + st.rows.map(function (r) {
          var rate = st.rates[r[2]]; if (!rate) miss++;
          return '<div class="prow' + (rate ? "" : " miss") + '"><span>' + esc(r[2]) + '<small>' + qty(r) + ' ' + unitOf(r) + '</small></span><label class="rateb">₹<input class="cell n rate" data-k="' + esc(r[2]) + '" value="' + (rate || "") + '" placeholder="add price" aria-label="Price for ' + esc(r[2]) + '"><small>per ' + unitOf(r) + '</small></label><b class="mono">' + (rate ? money(rate * qty(r)) : "—") + '</b></div>'; }).join("") + '</div>' +
          (miss ? '<p class="warnc small">' + miss + (miss === 1 ? " item has" : " items have") + ' no price yet — type one in, or leave it empty. Nothing is guessed.</p>' : "") +
          '<div class="bigtotal"><span>Total, including ' + (st.gst ? st.gst + "% GST" : "no GST") + (st.cont ? " and " + st.cont + "% extra" : "") + '</span><b class="mono">' + money(t.total) + '</b></div>' +
          '<details class="more"><summary>' + ic("right") + 'Tax and extras</summary><div class="ptot"><label>GST <select class="sel" id="p-gst"><option value="18">18%</option><option value="12">12%</option><option value="0">None</option></select></label>' +
          '<label class="lbl-ck"><input type="checkbox" class="ck" id="p-igst"' + (st.igst ? " checked" : "") + '> Customer is in another state (IGST)</label><label>Extra for contingency <select class="sel" id="p-cont"><option value="0">none</option><option value="3">3%</option><option value="5">5%</option><option value="10">10%</option></select></label>' +
          '<div class="sums"><span>Sub-total ' + money(t.sub) + (st.cont ? ' · contingency ' + money(t.cont) : '') + (st.gst ? (st.igst ? ' · IGST ' + money(t.gst) : ' · CGST ' + money(t.gst / 2) + ' + SGST ' + money(t.gst / 2)) : '') + '</span></div></div></details>' +
          (st.priced ? '<div class="filecard">' + ic("sheet") + '<div><b>' + esc(fname(true)) + '</b><small>Prices filled into your ' + noun + ' · saved in Prism Artifacts</small></div><span class="sp"></span><button class="btn dark sm" id="p-xls">' + pix("parrow") + 'Open in Excel</button><button class="btn light plain sm" id="p-more">' + ic("more") + '</button></div>'
            : '<div class="row"><button class="btn dark" id="p-fill">' + pix("parrow") + 'Add these prices to my ' + noun + '</button></div>');
      }
      s.innerHTML = html;
      $$("[data-pm]", s).forEach(function (b) { b.onclick = function () { var k = b.dataset.pm; st.priced = false;
        if (k === "mine") { pickFile(b, "doc", function (f) { st.priceMode = "mine"; st.rates = Object.assign({}, MOCK.rates.mine); st.rateName = f[0]; step4(); foot(); toast("Prices taken from " + f[0]); }, "Your price list"); return; }
        st.priceMode = k; st.rates = k === "starter" ? Object.assign({}, MOCK.rates.starter) : null; st.rateName = k === "starter" ? "Typical prices" : ""; step4(); foot(); }; });
      $$(".rate", s).forEach(function (inp) { inp.onchange = function () { var v = parseFloat(this.value); if (v > 0) st.rates[this.dataset.k] = v; else delete st.rates[this.dataset.k]; st.priced = false; step4(); foot(); }; });
      var g = $("#p-gst", s); if (g) { g.value = st.gst; g.onchange = function () { st.gst = +this.value; st.priced = false; step4(); foot(); $("details.more", s).open = true; }; }
      var c = $("#p-cont", s); if (c) { c.value = st.cont; c.onchange = function () { st.cont = +this.value; st.priced = false; step4(); foot(); $("details.more", s).open = true; }; }
      var ig = $("#p-igst", s); if (ig) ig.onchange = function () { st.igst = this.checked; st.priced = false; step4(); foot(); $("details.more", s).open = true; };
      var pf = $("#p-fill", s); if (pf) pf.onclick = function () { setOff(pf, "Filling in…"); var o = document.createElement("div"); o.className = "out"; pf.parentNode.replaceWith(o);
        stages(o, ["Filling the prices into your " + noun, "Adding the totals and GST", "Saving it"], function () { st.priced = true; step4(); foot(); toast("Prices added — saved as " + fname(true)); }, 550); };
      var px = $("#p-xls", s); if (px) px.onclick = function () { toast("Opened " + fname(true) + " in Excel"); };
      var pm = $("#p-more", s); if (pm) pm.onclick = function () { menu(this, ["Word document (.docx)", "PDF", "CSV"].map(function (f) { return { label: "Save as " + f, icon: "file", on: function () { toast("Saved the priced " + noun + " as " + f); } }; }), "More"); };
    }

    /* ── HVAC PDF takeoff (takeoff.py) — offered only when the request says HVAC (item 26) ── */
    function takeoff() {
      var tst = { pdf: isPdf() ? drawing()[0] : "", scale: "1 : 100", done: false };
      var m = form("Measure from a PDF drawing", "Tell Prism the scale, then it measures the ducts — on this computer.", "file",
        '<div class="fgrid"><label>PDF drawing</label><div class="line"><button class="chip" id="t-pick">' + ic("file") + (tst.pdf ? "Change PDF…" : "Pick a PDF…") + '</button><span class="mono small" id="t-name">' + esc(tst.pdf) + '</span></div>' +
        '<label>Drawing scale:</label><div class="line"><select class="sel" id="t-scale"><option>1 : 50</option><option selected>1 : 100</option><option>1 : 200</option><option>I don\'t know</option></select><button class="chip" id="t-measure">' + ic("expand") + 'Measure…</button></div>' +
        '<label>Text</label><label class="lbl-ck"><input type="checkbox" class="ck" id="t-ocr" checked> Read text labels (OCR)</label></div>' +
        '<p class="muted small" style="margin-top:.5rem">Don\'t know the scale? Press Measure… and click two points you know the real distance between.</p>' +
        '<div class="row" style="margin-top:.8rem"><button class="btn dark sm" id="t-extract"' + (tst.pdf ? "" : ' disabled title="Pick a PDF first."') + '>' + pix("parrow") + 'Extract</button></div><div id="t-out"></div>', "Use these measurements", function () {
          if (!tst.done) { toast("Press Extract first"); return false; }
          st.rows = rowsFor(); st.counted = true; st.fromText = false; st.hvacRun = true; st.made = false; if (st.step === 2) step2(); foot(); toast("Measured from the PDF");
        }, "mid");
      $("#t-pick", m).onclick = function () { pickFile(this, "drawing,doc", function (f) { tst.pdf = f[0].replace(/\.\w+$/, ".pdf"); $("#t-name", m).textContent = tst.pdf; setOff($("#t-extract", m), ""); }, "PDF drawing"); };
      $("#t-scale", m).onchange = function () { tst.scale = this.value; };
      $("#t-measure", m).onclick = function () {
        form("Measure a known dimension", "Click two points on the drawing that you know the real distance between, then type it.", "expand",
          '<div class="render small2"><svg viewBox="0 0 320 120"><rect x="20" y="20" width="280" height="80" fill="#F6F5F2" stroke="#111110"/><circle cx="40" cy="100" r="5" fill="#C8161D"/><circle cx="280" cy="100" r="5" fill="#C8161D"/><path d="M40 100H280" stroke="#C8161D" stroke-dasharray="4 4"/></svg></div>' +
          '<div class="fgrid"><label>Real distance between the two points:</label><input class="field2" id="t-dist" placeholder="feet, e.g. 6.0"></div>', "Use this scale", function (mm) {
            var v = parseFloat($("#t-dist", mm).value); if (!(v > 0)) { toast("Type the real distance first"); return false; }
            tst.scale = "1 : " + Math.round(v * 16); $("#t-scale", m).insertAdjacentHTML("beforeend", "<option selected>" + tst.scale + " (measured)</option>"); toast("Scale set: " + tst.scale); }, "sm", "formm2");
      };
      $("#t-extract", m).onclick = function () {
        var b = this; if (b.disabled) return; setOff(b, "Reading…"); var o = $("#t-out", m); o.innerHTML = '<div class="out" style="margin-top:.8rem"></div>';
        stages($(".out", o), ["Reading the drawing — a large PDF can take a minute…", $("#t-ocr", m).checked ? "Reading text labels (OCR)" : "Skipping text labels", "Finding duct runs and symbols"], function () {
          tst.done = true; setOff(b, "");
          o.innerHTML = '<div class="okline">' + ic("check") + '14 duct run(s) measured.</div><button class="warnbar" id="t-map">▸ Layer mapping (' + MOCK.takeoff.layers.length + ' found)</button><ul class="maplist" id="t-maplist" hidden>' +
            MOCK.takeoff.layers.map(function (l) { return '<li><b>' + l[0] + '</b><span class="tag">' + l[1] + '</span><span class="mono small">' + l[2] + ' found</span><button class="chip sm" data-prev="' + l[0] + '">Preview this layer on the drawing</button></li>'; }).join("") + '</ul>' +
            '<button class="warnbar" id="t-w">⚠ ' + MOCK.takeoff.warnings.length + ' warning(s) from the extraction ▾</button><ul class="warnlist" id="t-wl" hidden>' + MOCK.takeoff.warnings.map(function (w) { return "<li>" + esc(w) + "</li>"; }).join("") + '</ul>';
          $("#t-map", m).onclick = function () { var l = $("#t-maplist", m); l.hidden = !l.hidden; this.textContent = (l.hidden ? "▸" : "▾") + " Layer mapping (" + MOCK.takeoff.layers.length + " found)"; };
          $("#t-w", m).onclick = function () { var l = $("#t-wl", m); l.hidden = !l.hidden; };
          $$("[data-prev]", m).forEach(function (pb) { pb.onclick = function () { info("Layer preview — " + pb.dataset.prev, tst.pdf, "eye", '<div class="render big">' + ISO + '<span class="cap">' + esc(pb.dataset.prev) + ' highlighted in red</span></div>', "sm"); }; });
        }, 600);
      };
    }
    $$(".js-try").forEach(function (b) { b.addEventListener("click", function () { setTimeout(function () { if (b.dataset.fill) ta.value = b.dataset.fill; hvacUi(); foot(); }, 60); }); });
    hvacUi(); go(1);
  }

  /* ═════════════════════════ GERBER ═════════════════════════ */
  function gerberInit() {
    var d = $("#make"), ta = $("textarea", d), out = $(".js-out", d), holder = $(".js-att", d), st = { files: [], made: false, tpl: "" };
    var gen = $("#d-make"), unit = $("#d-unit");
    function job() { return st.files.filter(function (f) { return /Gerber/.test(f[1]); })[0]; }
    function upd() {
      setOff(gen, job() ? "" : "Attach a job first");
      setOff($("#d-clean"), st.made ? "" : "Generate first — the outline comes from the measured board");
      setOff($("#d-ob"), st.made ? "" : "Generate first");
      setOff($("#d-ans"), st.made ? "" : "After generating: an agent writes the reply or quotation from the measured numbers — the files still never leave");
      setOff($("#d-fill"), !st.made ? "Generate first" : st.tpl ? "" : "Choose the client's template first");
    }
    ta.addEventListener("input", upd); upd();
    $(".js-speak", d).onclick = function () { speak(this, ta, "gerber", upd); };
    $(".js-add", d).onclick = function () { pickFile(this, "gerber", function (f) { attachTo(holder, st, f, upd); }); };
    $(".js-fav", d).onclick = function () { favourites(this, "gerber", ta, upd); };
    $("#d-tpl").onclick = function () {
      var b = this;
      if (st.tpl) { st.tpl = ""; $("#d-tplname").textContent = ""; b.textContent = "Choose template…"; upd(); return; }
      pickFile(b, "doc", function (f) { st.tpl = f[0]; $("#d-tplname").textContent = f[0]; b.textContent = "Forget it"; upd(); toast("Template chosen — Prism fills the cells it recognises"); }, "The client's Excel form");
    };
    $("#d-files").onclick = function () { pickFile(this, "doc", function (f) { $("#d-filesname").textContent = f[0] + " — will be shown to the AI"; toast("Added " + f[0]); }); };
    unit.onchange = function () { if (st.made) { out.innerHTML = gerberHTML(unit.value); toast("Showing figures in " + unit.value); } };
    gen.onclick = function () {
      if (gen.disabled) return; setOff(gen, "Measuring…");
      stages(out, ["Unpacking " + job()[0], "Measuring the copper layers", "Counting drills"], function () { out.classList.add("filled"); out.innerHTML = gerberHTML(unit.value); st.made = true; setOff(gen, ""); upd(); toast("Measured — 10 figures"); });
    };
    $("#d-clean").onclick = function () { if (!this.disabled) toast("Clean outline saved on the Desktop, with a report of what went"); };
    $("#d-ob").onclick = function () { if (!this.disabled) toast("Opened the check sheet in your browser"); };
    $("#d-ans").onclick = function () {
      if (this.disabled) return;
      stages(out, ["Showing the measured numbers to Prism Agent Claude", "Writing the reply"], function () {
        out.classList.add("filled"); out.innerHTML = '<div class="doc"><p>Dear Mehul,</p><p>Thank you for the controller-rev-c job. For <b>500 pieces</b>, 4-layer FR-4, 86.4 × 54.2 mm, 1.6 mm, HASL, our price is <b>₹142 per board</b> (₹71,000 + GST), delivery 12 working days.</p><p>One note: the minimum track spacing is 0.127 mm in 3 places. We can build it, but if you can open those to 0.15 mm the yield improves.</p><p>Regards,<br>Parth · Kinetic Springs</p></div>' +
          '<div class="caveat">' + ic("lock") + '<span>Only the measured numbers were shown to the agent — never a file, never a path.</span></div>';
        toast("Reply written — copy it into your mail");
      });
    };
    $("#d-fill").onclick = function () { if (!this.disabled) toast("Filled copy of " + st.tpl + " saved beside the job"); };
    $$(".js-try").forEach(function (b) { b.addEventListener("click", function () { setTimeout(upd, 60); }); });
  }

  /* ═════════════════════════ STEP ═════════════════════════ */
  function stepInit() {
    var st = { model: null, mode: "Draft", runs: [] };
    var run = $("#st-run"), ask = $("#st-ask");
    function upd() {
      setOff($("#st-of"), st.model ? "" : "Attach a model first");
      setOff(run, !st.model ? "Attach a model first" : st.mode !== "Draft" && !ask.value.trim() ? "Say what you want done with it first" : "");
    }
    function attach(f) {
      st.model = f;
      $("#st-models").innerHTML = '<div class="model on">' + ic("cube") + '<div><b>' + esc(f[0]) + '</b><small>2 parts · measured</small></div></div>';
      $("#st-count").textContent = "1"; $("#st-empty").hidden = true; $("#st-work").hidden = false;
      $("#rp-m").innerHTML = stepHTML(); rtab("m"); toast("Model attached and measured. Now say what you want done with it, then press Run."); upd();
    }
    $("#st-choose").onclick = $("#st-browse").onclick = function (e) { e.preventDefault(); pickFile(this, "step", attach); };
    $("#st-fav").onclick = function (e) { e.preventDefault(); menu(this, MOCK.files.step.map(function (f) { return { label: f[0], hint: "Favourite model", icon: "cube", on: function () { attach(f); } }; }), "Favourite models"); };
    $$("#st-modes button").forEach(function (b) { b.addEventListener("click", function () {
      st.mode = b.textContent.trim();
      ask.placeholder = st.mode === "Draft" ? "Optional — anything the drawing sheet must show" : st.mode === "Ask" ? "e.g. How do I make this lighter?" : "e.g. Fit M8 bolts instead of M6";
      run.innerHTML = pix("parrow") + (st.mode === "Edit" ? "Plan the change" : "Run"); upd(); }); });
    ask.addEventListener("input", upd);
    ask.addEventListener("keydown", function (e) { if (e.key === "Enter") run.click(); });
    function rtab(k) { $$("#st-rtabs button").forEach(function (x) { x.classList.toggle("on", x.dataset.r === k); }); $$("[data-rp]").forEach(function (p) { p.hidden = p.dataset.rp !== k; }); }
    $$("#st-rtabs button").forEach(function (b) { b.addEventListener("click", function () { rtab(b.dataset.r); }); });
    run.onclick = function () {
      if (run.disabled) return; setOff(run, "Working…");
      var box = $("#rp-" + (st.mode === "Draft" ? "f" : st.mode === "Ask" ? "c" : "p")); rtab(st.mode === "Draft" ? "f" : st.mode === "Ask" ? "c" : "p");
      var lines = st.mode === "Draft" ? ["Measuring", "Drawing the sheet — 3 views", "Saving files"] : st.mode === "Ask" ? ["Measuring", "Asking from the numbers alone"] : ["Reading the change", "Writing the change plan"];
      stages(box, lines, function () {
        setOff(run, ""); upd();
        if (st.mode === "Draft") { box.innerHTML = '<div class="okline">' + ic("check") + '3 files saved to Prism Artifacts / Step / mounting-bracket</div>' + ["mounting-bracket-sheet.pdf", "mounting-bracket-measured.xlsx", "mounting-bracket-render.png"].map(function (n) { return '<button class="frow2">' + ic("file") + '<span>' + n + '</span>' + ic("ext") + '</button>'; }).join("");
          $$(".frow2", box).forEach(function (b) { b.onclick = function () { info(esc(b.textContent), "Prism Artifacts / Step", "file", '<div class="out filled">' + (/xlsx/.test(b.textContent) ? stepHTML() : '<div class="render big">' + ISO + '</div>') + '</div>', "mid"); }; }); }
        else if (st.mode === "Ask") { box.insertAdjacentHTML("afterbegin", ""); box.innerHTML = '<div class="chat"><div class="msg me">' + esc(ask.value) + '</div><div class="msg them">Thin the bracket from 3 mm to 2.5 mm: it saves about 155 g per part (929 → 774 g in mild steel). The four Ø8.5 holes keep at least 2× thickness from the bend, so nothing else changes. If you also cut a 40 mm lightening hole in the web, you save another 30 g.<small>From the measured numbers only — the model was not shown to an AI.</small></div></div>'; }
        else { box.innerHTML = '<div class="reg"><div class="sec">The change plan · on a copy</div><div class="kv2"><span>Holes Ø6.5 ×2</span><b>→ Ø8.5 ×2 (M8 clearance)</b></div><div class="kv2"><span>Edge distance after the change</span><b>7.8 mm · OK</b></div><div class="kv2"><span>Original model</span><b>untouched</b></div></div><div class="btnrow"><button class="btn dark sm" id="st-build">' + pix("parrow") + 'Build</button><button class="btn light plain sm" id="st-discard">Discard</button></div>';
          $("#st-build").onclick = function () { stages(box, ["Building a copy", "Re-measuring it"], function () { box.innerHTML = '<div class="okline">' + ic("check") + 'mounting-bracket-edited.step saved — holes are now Ø8.5</div>'; toast("Edited copy saved"); }); };
          $("#st-discard").onclick = function () { box.innerHTML = '<div class="rbody">Plan discarded. Nothing was built.</div>'; }; }
        st.runs.unshift(st.mode + (ask.value ? ": " + ask.value : ""));
        $("#st-hist").innerHTML = st.runs.map(function (r) { return '<div class="hrow">' + ic("clock") + esc(r.slice(0, 40)) + '</div>'; }).join("");
        toast(st.mode === "Draft" ? "Done. 3 files saved" : st.mode === "Ask" ? "Answered" : "Plan ready — nothing is built until you press Build");
      });
    };
    $("#st-of").onclick = function () { if (!this.disabled) toast("Opened Prism Artifacts / Step"); };
    $("#st-mat").onchange = function () { if (st.model) { $("#rp-m").innerHTML = stepHTML().replace("Sheet metal", this.value); toast("Measuring as " + this.value.toLowerCase()); } };
    $("#st-wide").onclick = function () { var w = $(".ws3").classList.toggle("wide"); this.title = w ? "Make this panel narrower" : "Make this panel wider"; };
    upd();
  }

  /* ═════════════════════════ EMAIL INQUIRIES ═════════════════════════ */
  var STAGE = { quote: "To quote", wait: "No answer yet", answered: "They answered", order: "Order came" };
  function inquiryInit() {
    var st = { stage: "quote", view: "pipe", pick: null, q: "", auto: false };
    function counts() { var c = { quote: 0, wait: 0, answered: 0, order: 0 }; MOCK.inquiries.forEach(function (i) { c[i.stage]++; }); return c; }
    function front() {
      var c = counts(), due = MOCK.inquiries.filter(function (i) { return i.due && i.stage === "wait"; }).length;
      var line = function (n, text, none, btn, stage) { return '<div class="nline"><span class="big2 mono">' + n + '</span><span class="tx">' + (n ? text : none) + '</span>' + (n ? '<a class="btn light plain sm" href="#pipeline" data-stage="' + stage + '">' + btn + '</a>' : "") + '</div>'; };
      $("#inq-dash").innerHTML =
        '<div class="card needs"><div class="label">What needs you today</div>' +
        line(c.quote, c.quote + (c.quote === 1 ? " new inquiry to quote" : " new inquiries to quote"), "Nothing new to quote", "Quote them", "quote") +
        line(c.wait, c.wait + (c.wait === 1 ? " quotation with no answer yet" : " quotations with no answer yet") + (due ? " — " + due + " needs a reminder today" : ""), "Every quotation has been answered", due ? "Send a reminder" : "See them", "wait") +
        line(c.answered, c.answered + (c.answered === 1 ? " customer answered" : " customers answered"), "No new answers", "Read the answer", "answered") +
        line(c.order, c.order + (c.order === 1 ? " order came" : " orders came"), "No new orders", "Open the order", "order") +
        '<p class="foot3">Prism sent 4 mails for you today. ' + (st.auto ? "Prism checks the mail by itself every 10 minutes." : "Prism checks the mail when you press Check my mail now. Switch on \"Check by itself\" in the working window to have it run alone.") + '</p></div>' +
        '<div class="card month"><div class="label">This month — November</div>' + kv([["Inquiries received", "23"], ["Quotations sent", "18"], ["Orders won", "6"], ["Orders won out of quotations", "33%"], ["Quotations with no answer yet", "7"], ["Lost because", "price (3), delivery time (1)"]]) +
        '<div class="label" style="margin-top:1rem">Mailboxes Prism reads</div><p class="muted small">Every one of them feeds the same register.</p>' +
        '<ul class="inc">' + [["sales@kineticsprings.in", "Ready"], ["parth@kineticsprings.in", "Ready"]].map(function (m) { return '<li>' + ic("inbox") + '<b>' + m[0] + '</b><span class="st ok">' + m[1] + '</span></li>'; }).join("") + '</ul></div>';
      $$("#inq-dash [data-stage]").forEach(function (a) { a.onclick = function () { st.stage = a.dataset.stage; st.pick = null; }; });
    }
    function rows() {
      return MOCK.inquiries.filter(function (i) { return (st.stage === "all" || i.stage === st.stage) && (!st.q || (i.who + i.contact + i.asked + i.no).toLowerCase().indexOf(st.q) >= 0); });
    }
    var HINT = { quote: "These inquiries have no quotation yet. Pick one, then press Prepare a quotation. Ones already quoted stay below them in grey until the customer answers.",
                 wait: "Quoted, and the customer has not answered. Prism reminds them on the days you set; the ones due today are marked.", answered: "The customer wrote back. Read the answer, then record the order or quote again.",
                 order: "A purchase order came. Confirm the delivery date and it moves to production.", all: "Every inquiry in the register, newest first.", mail: "Every mail Prism read, including the ones that were not inquiries." };
    function pipe() {
      var c = counts();
      $$("#inq-stages button").forEach(function (b) { var k = b.dataset.s, n = $(".n", b); if (n) n.textContent = c[k]; b.classList.toggle("on", k === st.stage); });
      $("#inq-hint").textContent = HINT[st.stage];
      var t = $("#inq-table"), rs = rows();
      if (st.stage === "mail") { mailList(t); return; }
      if (!rs.length) { t.innerHTML = '<div class="blank"><div><span class="ftile">' + ic("list") + '</span><h2>' + (st.q ? "Nothing matches" : st.stage === "quote" ? "Nothing to quote" : "Nothing here") + '</h2><p>' + (st.q ? "Try another name." : "Every inquiry has a quotation. New ones appear here as soon as Prism reads them.") + '</p></div></div>'; detail(); return; }
      t.innerHTML = '<div class="tscroll"><table class="tbl reg2"><thead><tr><th>No.</th><th>Customer</th><th>What they asked</th><th>Received</th><th class="n">Value</th><th>Status</th></tr></thead><tbody>' + rs.map(function (i) {
        return '<tr data-no="' + i.no + '" tabindex="0" class="' + (st.pick === i.no ? "on" : "") + '"><td class="mono">' + i.no + '</td><td><b>' + esc(i.who) + '</b><small>' + esc(i.contact) + '</small></td><td>' + esc(i.asked) + (i.files.length ? ' <span class="clip">' + ic("clip") + i.files.length + '</span>' : "") + '</td><td class="mono small">' + i.got + '</td><td class="n mono">' + (i.value || "—") + '</td><td>' + stPill(i) + '</td></tr>';
      }).join("") + '</tbody></table></div>';
      $$("tr[data-no]", t).forEach(function (tr) { tr.onclick = function () { st.pick = tr.dataset.no; pipe(); }; tr.onkeydown = function (e) { if (e.key === "Enter") tr.click(); }; });
      detail();
    }
    function stPill(i) { var cls = { quote: "neutral", wait: "warn", answered: "info", order: "ok" }[i.stage]; return '<span class="st ' + cls + '">' + (i.due && i.stage === "wait" ? "Remind today" : STAGE[i.stage]) + '</span>'; }
    function mailList(t) {
      var mails = MOCK.inquiries.map(function (i) { return [i.contact + " · " + i.who, i.asked, i.got, "Inquiry " + i.no]; }).concat([["IndiaMART", "Weekly buyer leads digest", "Today 07:00", "Not an inquiry"], ["HDFC Bank", "Your statement for October", "Yesterday", "Not an inquiry"], ["Kirloskar Brothers", "Revised price list — November", "Mon", "Not an inquiry"]]);
      t.innerHTML = '<ul class="runs plain">' + mails.map(function (m) { return '<li class="mail"><span class="ftile">' + ic("mail") + '</span><div style="min-width:0"><div class="t">' + esc(m[1]) + '</div><div class="m">' + esc(m[0]) + '</div></div><span class="tag">' + m[3] + '</span><span class="when">' + m[2] + '</span></li>'; }).join("") + '</ul>';
      $$("li.mail", t).forEach(function (li) { li.onclick = function () { toast("Opened the mail in Prism's mail reader"); }; });
      detail();
    }
    function detail() {
      var box = $("#inq-detail"), i = MOCK.inquiries.filter(function (x) { return x.no === st.pick; })[0];
      if (!i || st.stage === "mail") { box.innerHTML = '<div class="picked">Pick a row above.</div>'; return; }
      var acts = { quote: '<button class="btn dark sm" id="i-quote">' + pix("parrow") + 'Prepare a quotation</button><button class="btn light plain sm" id="i-notinq">Not an inquiry</button>',
                   wait: '<button class="btn dark sm" id="i-remind">' + pix("parrow") + 'Send a reminder</button><button class="btn light plain sm" id="i-lost">Mark as lost</button>',
                   answered: '<button class="btn dark sm" id="i-order">' + pix("parrow") + 'Record the order</button><button class="btn light plain sm" id="i-requote">Quote again</button>',
                   order: '<button class="btn dark sm" id="i-confirm">' + pix("parrow") + 'Confirm the delivery date</button>' }[i.stage];
      box.innerHTML = '<div class="idet"><div class="ihead"><div><span class="mono muted">' + i.no + ' · ' + i.got + '</span><h3>' + esc(i.who) + '</h3><span class="muted small">' + esc(i.contact) + ' · ' + esc(i.email) + '</span></div><div class="btnrow">' + acts + '<button class="iconbtn" id="i-x" title="Close">' + ic("x") + '</button></div></div>' +
        '<div class="mailq"><b>' + esc(i.asked) + '</b><p>' + esc(i.mail) + '</p>' + (i.answer ? '<p class="ans"><span class="label">Their answer</span>' + esc(i.answer) + '</p>' : "") +
        (i.files.length ? '<div class="frow">' + i.files.map(function (f) { return '<button class="fchip mini" data-toast="Opened ' + esc(f) + '">' + ic("clip") + '<b>' + esc(f) + '</b></button>'; }).join("") + '</div>' : "") + '</div><div class="out" id="i-out" hidden></div></div>';
      var on = function (id, fn) { var e = $("#" + id, box); if (e) e.onclick = fn; };
      on("i-x", function () { st.pick = null; pipe(); });
      on("i-quote", function () {
        var o = $("#i-out", box); o.hidden = false;
        stages(o, ["Reading the mail and " + (i.files[0] || "the request"), "Pricing from your rate sheet — Rate sheet Nov.xlsx", "Writing the quotation"], function () {
          o.classList.add("filled"); o.innerHTML = quoteHTML(i) + '<div class="btnrow"><button class="btn dark sm" id="i-send">' + pix("parrow") + 'Send the quotation</button><button class="btn light plain sm" id="i-edit">' + ic("pencil") + 'Change it</button></div>';
          $("#i-send", box).onclick = function () { ask("Send the quotation to " + i.contact + "?", "It goes from sales@kineticsprings.in to " + i.email + ", with the PDF attached. A copy is kept in Sent.", "Send", function (ok) {
            if (!ok) return; i.stage = "wait"; i.value = "₹45,666"; st.pick = null; pipe(); toast("Quotation sent — " + i.no + " moved to No answer yet"); }); };
          $("#i-edit", box).onclick = function () { $$(".doc td.n, .doc td:nth-child(2)", o).forEach(function (td) { td.contentEditable = true; }); toast("Click any line or price to change it"); };
        });
      });
      on("i-notinq", function () { MOCK.inquiries.splice(MOCK.inquiries.indexOf(i), 1); st.pick = null; pipe(); undo(i.no + " removed from the register", function () { MOCK.inquiries.push(i); pipe(); }); });
      on("i-remind", function () { ask("Send a reminder to " + i.contact + "?", "\"Dear " + i.contact.split(" ")[0] + ", following up on our quotation for " + i.asked.toLowerCase() + ". Happy to answer any questions.\"", "Send the reminder", function (ok) { if (ok) { i.due = false; pipe(); toast("Reminder sent to " + i.email); } }); });
      on("i-lost", function () { form("Mark " + i.no + " as lost", "Why did it go? It feeds \"Lost because\" on the front page.", "x", '<select class="sel" id="f-why"><option>Price</option><option>Delivery time</option><option>They bought elsewhere</option><option>Project cancelled</option></select>', "Mark as lost", function (m) {
        MOCK.inquiries.splice(MOCK.inquiries.indexOf(i), 1); st.pick = null; pipe(); toast(i.no + " marked as lost — " + $("#f-why", m).value.toLowerCase()); }); });
      on("i-order", function () { form("Record the order", i.who + " · " + i.no, "check", '<div class="fgrid"><label>PO number</label><input class="field2 mono" id="f-po" placeholder="PO-…"><label>Order value</label><input class="field2 mono" id="f-val" value="' + (i.value || "") + '"></div>', "Record the order", function (m) {
        var po = $("#f-po", m).value.trim(); if (!po) { toast("Type the PO number first"); return false; } i.stage = "order"; i.po = po; i.value = $("#f-val", m).value; st.pick = null; pipe(); toast("Order recorded — " + po); }); });
      on("i-requote", function () { i.stage = "quote"; pipe(); toast(i.no + " moved back to To quote"); });
      on("i-confirm", function () { form("Confirm the delivery date", i.who + " · " + (i.po || "PO"), "check", '<div class="fgrid"><label>Delivery date</label><input class="field2" type="date" id="f-date" value="2026-11-24"></div>', "Send confirmation", function (m) { toast("Delivery date sent to " + i.email); }); });
    }
    $$("#inq-stages button").forEach(function (b) { b.addEventListener("click", function () { st.stage = b.dataset.s; st.pick = null; pipe(); }); });
    $$("#inq-views button").forEach(function (b) { b.addEventListener("click", function () {
      var v = b.dataset.v; $("#inq-pipe").hidden = v !== "pipe"; $("#inq-client").hidden = v !== "client";
      if (v === "mail") { $("#inq-pipe").hidden = false; st.stage = "mail"; pipe(); } else if (v === "pipe" && st.stage === "mail") { st.stage = "quote"; pipe(); }
      if (v === "client") clients(); }); });
    function clients() {
      var by = {}; MOCK.inquiries.forEach(function (i) { (by[i.who] = by[i.who] || []).push(i); });
      $("#inq-client").innerHTML = '<div class="card"><ul class="runs plain">' + Object.keys(by).map(function (w) { var l = by[w];
        return '<li class="cli"><span class="avatar sm">' + w[0] + '</span><div style="min-width:0"><div class="t">' + esc(w) + '</div><div class="m">' + esc(l[0].contact) + ' · ' + esc(l[0].email) + '</div></div><span class="tag">' + l.length + (l.length === 1 ? " inquiry" : " inquiries") + '</span><span class="when">' + l.filter(function (x) { return x.stage === "order"; }).length + ' orders</span></li>'; }).join("") + '</ul></div>';
      $$("li.cli").forEach(function (li) { li.onclick = function () { var who = $(".t", li).textContent, i = MOCK.inquiries.filter(function (x) { return x.who === who; })[0];
        $("#inq-views button").click(); st.stage = i.stage; st.pick = i.no; $$("#inq-views button")[0].click(); pipe(); }; });
    }
    $("#inq-q").addEventListener("input", function () { st.q = this.value.toLowerCase(); pipe(); });
    $("#inq-show").onchange = function () { toast("Showing " + this.value.toLowerCase()); };
    $("#inq-add").onclick = function () {
      form("Add inquiry", "For one that came by phone or WhatsApp — it gets the next number.", "plus",
        '<div class="fgrid"><label>Customer</label><input class="field2" id="f-who" placeholder="Company name"><label>Contact</label><input class="field2" id="f-c" placeholder="Name, email or phone"><label>What they asked</label><textarea class="ta" id="f-a" rows="3" placeholder="e.g. 500 nos compression springs, 2 mm wire"></textarea></div>', "Add to the register", function (m) {
          var who = $("#f-who", m).value.trim(), a = $("#f-a", m).value.trim(); if (!who || !a) { toast("Fill in the customer and what they asked"); return false; }
          var no = "INQ-0" + (148 + MOCK.inquiries.length - 8);
          MOCK.inquiries.unshift({ no: no, who: who, contact: $("#f-c", m).value || who, email: $("#f-c", m).value || "—", asked: a, got: "Today, now", stage: "quote", files: [], mail: a });
          st.stage = "quote"; st.pick = no; pipe(); toast(no + " added to the register"); });
    };
    $("#inq-auto").onchange = function () { st.auto = this.checked; toast(this.checked ? "Prism checks the mail by itself every 10 minutes" : "Prism checks only when you press Check my mail now"); front(); };
    $("#inq-setup").onclick = setup;
    function setup() {
      form("Email inquiry setup", "Which mailboxes Prism reads, and what it quotes as.", "sliders",
        '<div class="fgrid"><label>Quoting as</label><input class="field2" value="' + MOCK.company + '"><label>Mailbox</label><input class="field2" value="sales@kineticsprings.in"><label>App password</label><input class="field2 mono" type="password" value="abcdabcdabcdabcd">' +
        '<label>Rate sheet</label><div class="line"><input class="field2" value="Rate sheet Nov.xlsx" readonly><button class="chip" data-toast="Pick a rate sheet from your computer">' + ic("folder") + 'Choose…</button></div>' +
        '<label>Remind after</label><select class="sel"><option>3 days</option><option>5 days</option><option>7 days</option></select><label>Register file</label><span class="val mono">~/Prism Workspace/Inquiry register.xlsx</span></div>', "Save", function () { toast("Saved — the next check uses these settings"); }, "mid");
    }
    $("#inq-check").onclick = function () {
      var b = this; setOff(b, "Checking…"); b.innerHTML = '<span class="spin"></span>Checking…';
      setTimeout(function () {
        MOCK.inquiries.unshift({ no: "INQ-0148", who: "Sahyadri Castings", contact: "Deepak Kulkarni", email: "deepak@sahyadricastings.in", asked: "Valve springs, 2,000 nos — urgent", got: "Today, now", stage: "quote", files: ["valve-spring-spec.pdf"], mail: "Please quote urgently for 2,000 valve springs as per the attached spec. Required by month end." });
        setOff(b, ""); b.innerHTML = ic("inbox") + "Check my mail now"; st.stage = "quote"; st.pick = "INQ-0148"; pipe(); front(); toast("Read 14 mails — 1 new inquiry, 13 were not inquiries");
        b.onclick = function () { var bb = this; setOff(bb, "Checking…"); setTimeout(function () { setOff(bb, ""); toast("Read 2 mails — nothing new"); }, 1000); };
      }, 1400);
    };
    $("#inq-more").onclick = function () { menu(this, [{ label: "Open the register file", icon: "file", on: function () { toast("Opened Inquiry register.xlsx"); } }, { label: "Export this month", icon: "ext", on: function () { toast("Saved November register as a PDF on the Desktop"); } },
      { label: "Edit setup", icon: "sliders", on: setup }, { label: "Read the guide", icon: "help", on: function () { window.openLumi(); } }]); };
    $("#inq-edit").onclick = setup;
    document.addEventListener("route", function (e) { if (e.detail === "pipeline") pipe(); else front(); });
    front(); pipe();
  }

  /* ═════════════════════════ EMAIL OUTREACH ═════════════════════════ */
  function emailInit() {
    function body() {
      $("#em-body").innerHTML =
        '<div class="card pad"><div class="label">Sending account</div><div class="acct"><span class="avatar sm">K</span><div><b>' + MOCK.me.email + '</b><small>through smtp.gmail.com</small></div><span class="st ok">Ready</span><span class="sp"></span><button class="btn light plain sm" id="em-acct2">' + ic("key") + 'Change account</button></div></div>' +
        '<div class="card pad"><div class="label">Send an email</div><div class="two"><div><button class="btn light plain sm" id="em-one">' + ic("user") + 'Write to one person</button><p class="muted small">Type the address, the subject and the message, then press Send. Prism can write the message for you if you ask it to.</p></div>' +
        '<div><button class="btn light plain sm" id="em-list">' + ic("list") + 'Send to a list</button><p class="muted small">Attach a CSV of addresses (name, email). Each person gets their own copy, with their own name in it.</p></div></div></div>' +
        '<div class="card pad grow"><div class="hd3"><div class="label">Sent from this computer</div><button class="btn light plain sm" id="em-folder">' + ic("folder") + 'Open the folder</button></div><ul class="runs plain">' + MOCK.sent.map(function (s, i) {
          return '<li data-i="' + i + '"><span class="ftile">' + ic("mail") + '</span><div style="min-width:0"><div class="t">' + esc(s[1]) + '</div><div class="m">' + esc(s[0]) + '</div></div><span class="when">' + s[2] + '</span><span class="st ' + (s[3] === "Sent" ? "ok" : "err") + '">' + s[3] + '</span></li>'; }).join("") + '</ul></div>';
      $("#em-acct2").onclick = account; $("#em-one").onclick = function () { location.hash = "compose"; };
      $("#em-list").onclick = function () { location.hash = "compose"; setTimeout(function () { $("#c-list").click(); }, 80); };
      $("#em-folder").onclick = function () { toast("Opened Prism Workspace / Sent mail"); };
      $$("#em-body li[data-i]").forEach(function (li) { li.onclick = function () { var s = MOCK.sent[+li.dataset.i];
        info(esc(s[1]), "To " + esc(s[0]) + " · " + s[2], "mail", '<div class="doc"><p>Dear Sir/Madam,</p><p>' + (s[3] === "Bounced" ? "This mail could not be delivered: the address does not exist. Prism took it off the list." : "Following up on our earlier mail — happy to send samples or a revised rate if it helps. Please let us know.") + '</p><p>Regards,<br>Parth · Kinetic Springs</p></div>', "sm"); }; });
    }
    function account() {
      form("Sending account", "Prism sends from your own address. Set it up once.", "key",
        '<div class="fgrid"><label>Address</label><input class="field2" id="f-addr" value="' + MOCK.me.email + '"><label>App password</label><input class="field2 mono" type="password" id="f-pw" value="abcdabcdabcdabcd"><label>Server</label><select class="sel"><option>Gmail / Google Workspace</option><option>Outlook / Microsoft 365</option><option>Zoho Mail</option><option>Other (SMTP)</option></select></div>' +
        '<p class="muted small">Use an app password, not your normal one. Prism sends a test mail to yourself to check it.</p>', "Save and test", function (m) {
          var a = $("#f-addr", m).value.trim(); if (!/@/.test(a)) { toast("That address needs an @"); return false; } MOCK.me.email = a; body(); toast("Test mail sent to " + a + " — the account works"); });
    }
    $("#em-acct").onclick = account;
    body();
    /* compose */
    var to = $("#c-to"), subj = $("#c-subj"), msg = $("#c-msg"), send = $("#c-send"), st = { files: [], list: 0, pace: "2 s apart · everyone at once · no daily limit · sends now · copy kept in Sent" };
    function upd() {
      var miss = []; if (!to.value.trim() && !st.list) miss.push("To"); if (!subj.value.trim()) miss.push("Subject"); if (!msg.value.trim()) miss.push("Message");
      setOff(send, miss.length ? "Still needed: " + miss.join(", ") : "");
      send.innerHTML = pix("parrow") + (st.list ? "Send to " + (st.list + (to.value.trim() ? to.value.split(",").length : 0)) + " people" : "Send");
    }
    [to, subj, msg].forEach(function (x) { x.addEventListener("input", upd); }); upd();
    $("#c-list").onclick = function () { pickFile(this, "csv", function (f) { st.list = parseInt(f[1], 10); $("#c-listname").innerHTML = '<span class="fchip mini">' + ic("list") + '<b>' + esc(f[0]) + '</b><small>' + f[1] + '</small></span>'; upd(); toast(f[1] + " added — each gets their own copy"); }, "A CSV of addresses"); };
    $("#c-web").onclick = function (e) { e.preventDefault(); form("Search the web for an address", "Prism looks on the company's own site and public listings.", "search", '<input class="field2" id="f-co" placeholder="Company and person, e.g. Vraj Infra purchase manager"><div id="f-res" class="mt"></div>', "Search", function (m) {
      var r = $("#f-res", m); r.innerHTML = '<span class="muted">Searching…</span>';
      setTimeout(function () { r.innerHTML = [["rakesh@vrajinfra.com", "Rakesh Mehta · Purchase Manager · found on vrajinfra.com"], ["purchase@vrajinfra.com", "General purchase desk · found on IndiaMART"]].map(function (x) { return '<button class="frow2" data-a="' + x[0] + '">' + ic("mail") + '<span><b>' + x[0] + '</b><small>' + x[1] + '</small></span>' + ic("plus") + '</button>'; }).join("");
        $$("[data-a]", r).forEach(function (b) { b.onclick = function () { to.value = (to.value ? to.value + ", " : "") + b.dataset.a; upd(); m.classList.remove("on"); toast("Added " + b.dataset.a); }; }); }, 800); return false; }); };
    $("#c-attach").onclick = function () { pickFile(this, "doc", function (f) { attachTo($("#c-att"), st, f, function () { $("#c-none").hidden = st.files.length > 0; }); }); };
    $("#c-pace").onclick = function (e) { e.preventDefault(); form("Pace and limits", "How fast Prism sends, so your address stays trusted.", "sliders",
      '<div class="fgrid"><label>Gap between mails</label><select class="sel" id="f-gap"><option>2 s apart</option><option>30 s apart</option><option>2 min apart</option></select><label>Who goes first</label><select class="sel" id="f-who"><option>everyone at once</option><option>50 per run</option></select>' +
      '<label>Daily limit</label><select class="sel" id="f-day"><option>no daily limit</option><option>100 a day</option><option>300 a day</option></select><label>When</label><select class="sel" id="f-when"><option>sends now</option><option>tomorrow 10:00</option></select>' +
      '<label>Sent folder</label><label class="switch big"><input type="checkbox" checked id="f-copy"><i></i><span>Keep a copy in Sent</span></label></div>', "Save", function (m) {
        st.pace = [$("#f-gap", m).value, $("#f-who", m).value, $("#f-day", m).value, $("#f-when", m).value, $("#f-copy", m).checked ? "copy kept in Sent" : "no copy in Sent"].join(" · "); $("#c-paceline").textContent = st.pace; toast("Saved."); }); };
    $("#c-write").onclick = function () {
      var what = $("#c-draft").value.trim(); if (!what) { toast("Say what it should say first"); $("#c-draft").focus(); return; }
      var b = this; setOff(b, "Writing…"); msg.value = ""; var text = "Dear " + (to.value.indexOf("rakesh") >= 0 ? "Rakesh" : "Sir/Madam") + ",\n\nI'm Parth from Kinetic Springs, Vadodara. We make compression, torsion and leaf springs for pumps, HVAC and conveyor makers — " +
        "most of our customers order 500 to 20,000 pieces a month, and we hold a 2-week lead time.\n\n" + (/meeting/i.test(what) ? "Could we meet for 20 minutes next week? I'll bring samples and our current rate sheet.\n\n" : "I've attached our catalogue. Happy to send samples.\n\n") + "Regards,\nParth\nKinetic Springs · +91 98xxx xxxxx";
      if (!subj.value) subj.value = /meeting/i.test(what) ? "Springs for your next project — 20 minutes next week?" : "Springs and wire forms from Kinetic Springs";
      var k = 0; (function type() { msg.value = text.slice(0, k += 6); if (k < text.length) setTimeout(type, 12); else { setOff(b, ""); upd(); toast("Draft written — change anything before you send"); } })();
    };
    $("#c-acct").onclick = account;
    send.onclick = function () {
      if (send.disabled) return; var n = st.list + (to.value.trim() ? to.value.split(",").length : 0);
      ask("Send " + (n === 1 ? "this email" : "to " + n + " people") + "?", "From " + MOCK.me.email + ". " + st.pace + ".", "Send now", function (ok) {
        if (!ok) return; setOff(send, "Sending…"); var i = 0;
        (function tick() { i++; send.innerHTML = '<span class="spin"></span>Sending ' + Math.min(i, n) + ' of ' + n; if (i < n) setTimeout(tick, n > 6 ? 90 : 400); else {
          MOCK.sent.unshift([st.list ? n + " people" : to.value.trim(), subj.value, "Today, now", "Sent"]); body();
          to.value = subj.value = msg.value = ""; st.list = 0; $("#c-listname").innerHTML = ""; upd(); hideModal($("#compose")); toast(n === 1 ? "Sent." : "Sent to " + n + " people — each got their own copy"); } })();
      });
    };
  }

  /* ═════════════════════════ LEADS ═════════════════════════ */
  function leadsInit() {
    var st = { people: MOCK.people.map(function (p) { return { n: p[0], t: p[1], c: p[2], l: p[3], e: p[4], saved: !!p[5], fresh: false }; }), show: "total", q: "", title: "", loc: "", sort: "Relevance", view: "Table", picked: {}, credits: 1240, drafted: 0 };
    function vis() {
      var v = st.people.filter(function (p) {
        if (st.show === "new" && !p.fresh) return false; if (st.show === "saved" && !p.saved) return false;
        var hay = (p.n + " " + p.t + " " + p.c + " " + p.l).toLowerCase();
        return (!st.q || hay.indexOf(st.q) >= 0) && (!st.title || p.t.toLowerCase().indexOf(st.title) >= 0 || (st.similar && /purchase|procure|sourc|buyer/.test(p.t.toLowerCase()) && /purchase|procure|sourc|buyer/.test(st.title))) && (!st.loc || p.l.toLowerCase().indexOf(st.loc) >= 0);
      });
      if (st.sort === "Company A–Z") v.sort(function (a, b) { return a.c.localeCompare(b.c); });
      if (st.sort === "Newest") v.sort(function (a, b) { return b.fresh - a.fresh; });
      return v;
    }
    function stats() { var s = $$("#ld-stats > div"); s[0].querySelector("b").textContent = st.people.length; s[1].querySelector("b").textContent = st.people.filter(function (p) { return p.fresh; }).length; s[2].querySelector("b").textContent = st.people.filter(function (p) { return p.saved; }).length; }
    function render() {
      stats(); var v = vis(), box = $("#ld-res");
      setOff($("#ld-export"), st.people.length ? "" : "Find or import people first");
      setOff($("#ld-send"), st.drafted ? "" : "Pick people and press Draft emails first");
      if (!v.length) { box.innerHTML = '<div class="blank"><div><span class="ftile">' + ic("user") + '</span><h2>' + (st.people.length ? "Nobody matches" : "No people yet") + '</h2><p>' + (st.people.length ? "Loosen a filter on the left, or clear the search." : "Import a sheet with Import at the top right, or set filters on the left and press Find new people.") + '</p></div></div>'; return; }
      var n = Object.keys(st.picked).filter(function (k) { return st.picked[k]; }).length;
      var bar = '<div class="selbar2"><label><input type="checkbox" class="ck" id="ld-all"' + (n && n === v.length ? " checked" : "") + '> ' + (n ? n + " picked" : v.length + " people") + '</label><span class="sp"></span>' +
        '<button class="btn light plain sm" id="ld-save-p"' + (n ? "" : ' disabled title="Pick people first"') + '>' + ic("plus") + 'Save to a list</button><button class="btn dark sm" id="ld-draft"' + (n ? "" : ' disabled title="Pick people first"') + '>' + pix("parrow") + 'Draft emails</button></div>';
      if (st.view === "Cards") box.innerHTML = bar + '<div class="pcards">' + v.map(function (p) { var i = st.people.indexOf(p);
        return '<div class="pcard" data-i="' + i + '"><input type="checkbox" class="ck"' + (st.picked[i] ? " checked" : "") + '><span class="avatar sm">' + p.n[0] + '</span><b>' + esc(p.n) + '</b><small>' + esc(p.t) + '</small><span class="co">' + esc(p.c) + '</span><span class="mono muted small">' + p.l + '</span>' + (p.d ? '<span class="st ok">Drafted</span>' : "") + '</div>'; }).join("") + '</div>';
      else box.innerHTML = bar + '<div class="tscroll"><table class="tbl people"><thead><tr><th></th><th>Name</th><th>Company</th><th>Location</th><th>Email</th><th></th></tr></thead><tbody>' + v.map(function (p) { var i = st.people.indexOf(p);
        return '<tr data-i="' + i + '" tabindex="0"><td><input type="checkbox" class="ck"' + (st.picked[i] ? " checked" : "") + ' aria-label="Pick ' + esc(p.n) + '"></td><td><div class="pn"><span class="avatar sm">' + p.n[0] + '</span><div><b>' + esc(p.n) + (p.fresh ? ' <span class="tag new">New</span>' : "") + '</b><small>' + esc(p.t) + '</small></div></div></td><td>' + esc(p.c) + '</td><td class="small">' + p.l + '</td><td><span class="st ' + (p.e === "Verified" ? "ok" : "warn") + '">' + p.e + '</span></td><td>' + (p.d ? '<span class="st info">Drafted</span>' : p.saved ? '<span class="tag">Saved</span>' : "") + '</td></tr>'; }).join("") + '</tbody></table></div>';
      $$("[data-i]", box).forEach(function (row) { var i = +row.dataset.i;
        row.onclick = function (e) { if (e.target.closest(".ck")) { st.picked[i] = e.target.checked; render(); return; } person(st.people[i]); }; });
      var all = $("#ld-all"); if (all) all.onchange = function () { v.forEach(function (p) { st.picked[st.people.indexOf(p)] = all.checked; }); render(); };
      var sp = $("#ld-save-p"); if (sp) sp.onclick = function () { menu(this, [["HVAC contractors — Gujarat", 24], ["Pump OEM buyers", 11], ["New list…", 0]].map(function (l) { return { label: l[0], hint: l[1] ? l[1] + " people" : "", icon: "list", on: function () {
        picked().forEach(function (p) { p.saved = true; }); st.picked = {}; render(); toast("Saved to " + l[0]); } }; }), "Save to a list"); };
      var dr = $("#ld-draft"); if (dr) dr.onclick = function () { var ps = picked(); setOff(dr, "Drafting…"); var o = document.createElement("div"); box.prepend(o); o.className = "out";
        stages(o, ["Reading each company's site", "Finding what to say to each person", "Writing " + ps.length + " emails"], function () { ps.forEach(function (p) { p.d = true; }); st.drafted += ps.length; st.credits -= ps.length; st.picked = {}; render(); toast(ps.length + " emails drafted — open a person to read theirs"); }, 600); };
    }
    function picked() { return st.people.filter(function (p, i) { return st.picked[i]; }); }
    function person(p) {
      var m = info(esc(p.n), esc(p.t) + " · " + esc(p.c), "user",
        '<div class="pgrid"><div>' + kv([["Company", esc(p.c)], ["Location", p.l], ["Email", '<span class="mono">' + p.n.split(" ")[0].toLowerCase() + "@" + p.c.toLowerCase().replace(/[^a-z]/g, "").slice(0, 14) + '.in</span>'], ["Email check", '<span class="st ' + (p.e === "Verified" ? "ok" : "warn") + '">' + p.e + '</span>'], ["Phone", '<span class="mono">+91 9xxxx xxxxx</span> <button class="chip sm" data-toast="Revealed — 5 credits used">Reveal · 5 credits</button>']]) +
        '<div class="label" style="margin:1rem 0 .4rem">Why Prism picked them</div><ul class="sum"><li>' + esc(p.t) + ' — buys springs and wire forms</li><li>' + esc(p.c) + ' posted a tender for spares last month</li><li>Within 400 km of Vadodara</li></ul></div>' +
        '<div><div class="label">The email Prism drafted</div><input class="field2" style="margin:.5rem 0" value="Springs for ' + esc(p.c) + ' — samples this week?"><textarea class="ta" rows="9">Dear ' + esc(p.n.split(" ")[0]) + ',\n\nI saw ' + esc(p.c) + ' is sourcing spares this quarter. We make compression and torsion springs for pump and conveyor makers in Gujarat, with a 2-week lead time.\n\nCould I send you samples this week?\n\nRegards,\nParth · Kinetic Springs</textarea></div></div>' +
        '<div class="df inl"><button class="btn light plain sm danger" id="pp-rm">' + ic("trash") + 'Remove from the list</button><span class="sp"></span><button class="btn light plain sm" id="pp-save">' + (p.saved ? "Saved" : "Save") + '</button><button class="btn dark sm" id="pp-send">' + pix("parrow") + 'Send this one</button></div>', "mid");
      $("#pp-rm", m).onclick = function () { var i = st.people.indexOf(p); st.people.splice(i, 1); m.classList.remove("on"); render(); undo(p.n + " removed", function () { st.people.splice(i, 0, p); render(); }); };
      $("#pp-save", m).onclick = function () { p.saved = true; this.textContent = "Saved"; render(); toast("Saved " + p.n); };
      $("#pp-send", m).onclick = function () { ask("Send to " + p.n + "?", "From " + MOCK.me.email + ". One copy, with their name in it.", "Send", function (ok) { if (ok) { m.classList.remove("on"); toast("Sent to " + p.n); } }); };
    }
    $("#ld-q").addEventListener("input", function () { st.q = this.value.toLowerCase(); render(); });
    $("#ld-title").addEventListener("input", function () { st.title = this.value.toLowerCase().trim(); render(); });
    $("#ld-loc").addEventListener("input", function () { st.loc = this.value.toLowerCase().trim(); render(); });
    $("#ld-sim").onchange = function () { st.similar = this.checked; render(); }; st.similar = true;
    $$("#ld-stats > div").forEach(function (d) { d.addEventListener("click", function () { st.show = d.dataset.s; render(); }); });
    $("#ld-sort").onchange = function () { st.sort = this.value; render(); };
    $("#ld-view").onclick = function () { menu(this, ["Table", "Cards"].map(function (v) { return { label: v, icon: v === "Table" ? "list" : "grid", check: 1, checked: st.view === v, on: function () { st.view = v; $("#ld-view").innerHTML = ic(v === "Table" ? "list" : "grid") + v + " view"; render(); } }; }), "View"); };
    $("#ld-hide").onclick = function () { var f = $(".filt"), h = f.hidden = !f.hidden; $(".split2").classList.toggle("nofilt", h); this.innerHTML = ic("list") + (h ? "Show filters" : "Hide filters"); };
    $("#ld-ai").onclick = function () { form("Research with AI", "Describe who you want. Prism turns it into filters and finds them.", "spark", '<textarea class="ta" id="f-ai" rows="3">Purchase managers at pump and HVAC companies in Gujarat with 50–500 staff</textarea>', "Research", function (m) {
      $("#ld-title").value = "purchase"; $("#ld-loc").value = ""; st.title = "purchase"; render(); toast("Filters set from your words — press Find new people for fresh ones"); }); };
    $("#ld-savesearch").onclick = function () { form("Save this search", "Keep these filters to run again later.", "plus", '<input class="field2" id="f-sn" value="Purchase managers — Gujarat">', "Save", function (m) { saved.unshift([$("#f-sn", m).value, "just now"]); toast("Saved search: " + $("#f-sn", m).value); }); };
    $("#ld-settings").onclick = function () { form("Search settings", "How Prism finds and checks people.", "sliders", '<div class="fgrid"><label>Per search</label><select class="sel"><option>25 people</option><option>50 people</option><option>100 people</option></select><label>Check emails</label><label class="switch big"><input type="checkbox" checked><i></i><span>Verify every email (1 credit each)</span></label><label>Skip</label><label class="switch big"><input type="checkbox" checked><i></i><span>People already in my lists</span></label></div>', "Save", function () { toast("Saved."); }); };
    $("#ld-import").onclick = function () { menu(this, [{ label: "A CSV or Excel sheet", icon: "file", on: function () { pickFile($("#ld-import"), "csv", function (f) { MOCK.morePeople.slice(0, 3).forEach(function (p) { st.people.unshift({ n: p[0], t: p[1], c: p[2], l: p[3], e: p[4], saved: false, fresh: true }); }); render(); toast("Imported " + f[0] + " — 3 people were new, 21 already here"); }); } },
      { label: "From LinkedIn Sales Navigator", icon: "ext", hint: "Paste a search link", on: function () { toast("Paste the Sales Navigator link into the box that opens"); } }, { label: "Contact CSV Import", icon: "user", on: function () { $$(".acc .h")[5].click(); } }], "Import"); };
    $("#ld-find").onclick = function () { var b = this; setOff(b, "Finding…"); var o = $("#ld-res"); var tmp = document.createElement("div"); tmp.className = "out"; o.prepend(tmp);
      stages(tmp, ["Searching companies that match", "Finding the right person at each", "Checking each email"], function () {
        MOCK.morePeople.forEach(function (p) { if (!st.people.some(function (x) { return x.n === p[0]; })) st.people.unshift({ n: p[0], t: p[1], c: p[2], l: p[3], e: p[4], saved: false, fresh: true }); });
        st.credits -= 12; setOff(b, ""); st.show = "new"; $$("#ld-stats > div").forEach(function (d) { d.classList.toggle("on", d.dataset.s === "new"); }); render(); toast("Found 6 new people — 12 credits used");
      }, 650); };
    $("#ld-more").onclick = function () { menu(this, ["Company size", "Revenue", "Technologies used", "Hiring now", "Funding", "Department", "Years in role", "Keywords", "Email status", "Phone available", "Country", "Exclude my customers"].map(function (f) { return { label: f, icon: "plus", on: function () { toast("Filter added: " + f); } }; }), "More filters (12)"); };
    $("#ld-help").onclick = function () { window.openLumi(); };
    $("#ld-credits").onclick = function () { menu(this, [{ html: '<div class="credit"><span class="mono big2">' + st.credits.toLocaleString("en-IN") + '</span><span>credits left · team</span></div><div class="kvmini"><span>Find a person</span><b>1</b><span>Verify an email</span><b>1</b><span>Reveal a phone</span><b>5</b><span>Draft an email</span><b>1</b></div>' },
      { label: "See credit usage", icon: "bars", on: function () { toast("Opened Credit usage — 248 used this month"); } }, { label: "Buy more credits", icon: "plus", on: function () { toast("Opened the AlphaKore credits page"); } }], "Your credits"); };
    $("#ld-export").onclick = function () { if (!this.disabled) toast("Saved " + st.people.length + " people as Leads — Nov 3.xlsx on the Desktop"); };
    $("#ld-send").onclick = function () { if (this.disabled) return; ask("Send all " + st.drafted + " drafted emails?", "From " + MOCK.me.email + ", 30 seconds apart. Each person gets their own copy.", "Send all", function (ok) { if (ok) { toast("Sending " + st.drafted + " emails — watch the Sessions tab"); st.people.forEach(function (p) { p.d = false; }); st.drafted = 0; render(); } }); };
    var saved = [["Purchase managers, Vadodara", "2 days ago"], ["HVAC project engineers — Surat", "last week"]];
    $$("#ld-tabs button").forEach(function (b) { b.addEventListener("click", function () {
      var t = b.textContent.trim(); $("#ld-people").hidden = t !== "People"; var o = $("#ld-other"); o.hidden = t === "People"; if (t === "People") return;
      var list = function (rows, cols) { return '<ul class="runs plain">' + rows.map(function (r) { return '<li data-toast="Opened ' + esc(r[0]) + '"><span class="ftile">' + ic(cols) + '</span><div style="min-width:0"><div class="t">' + esc(r[0]) + '</div><div class="m">' + esc(r[1]) + '</div></div>' + (r[2] ? '<span class="tag">' + r[2] + '</span>' : "") + '</li>'; }).join("") + '</ul>'; };
      o.innerHTML = '<div class="pad2">' + ({
        Sessions: list([["Find people — purchase managers, Gujarat", "Today 10:20 · 6 found · 12 credits", "Done"], ["Draft emails — 8 people", "Yesterday 16:05 · 8 drafted", "Done"], ["Send all — 8 emails", "Yesterday 16:12 · 7 sent, 1 bounced", "Done"]], "clock"),
        Lists: list([["HVAC contractors — Gujarat", "24 people · updated today", "24"], ["Pump OEM buyers", "11 people · updated Mon", "11"]], "list"),
        "Saved searches": list(saved.map(function (s) { return [s[0], "Saved " + s[1], "Run"]; }), "search"),
        Sequences: list([["3-step follow-up", "Day 0 email · Day 3 reminder · Day 7 last note", "Active"], ["Trade-fair invite", "Day 0 email · Day 5 reminder", "Paused"]], "mail"),
        Analytics: '<div class="kpis">' + [["Sent", "86"], ["Opened", "41%"], ["Replied", "9"], ["Meetings", "3"], ["Bounced", "2"]].map(function (k) { return '<div class="card kpi"><span class="label">' + k[0] + '</span><b class="mono">' + k[1] + '</b></div>'; }).join("") + '</div>'
      }[t]) + '</div>';
    }); });
    render();
  }

  /* ═════════════════════════ WHATSAPP ═════════════════════════ */
  function whatsappInit() {
    var st = { cur: null, q: "", filter: "All chats", hist: false };
    setTimeout(function () { var s = $("#wa-status"); s.className = "chipm live"; s.textContent = "Connected · +91 98250 xxxxx"; }, 1300);
    function list() {
      var v = MOCK.chats.filter(function (c) { return (!st.q || (c.name + c.org + c.msgs.map(function (m) { return m[1]; }).join(" ")).toLowerCase().indexOf(st.q) >= 0) && (st.filter !== "Unread" || c.unread); });
      if (st.hist) v = v.filter(function (c) { return !/^\d/.test(c.time); });
      $("#wa-list").innerHTML = v.length ? v.map(function (c) { var i = MOCK.chats.indexOf(c), last = c.msgs[c.msgs.length - 1];
        return '<button class="chatrow' + (st.cur === c ? " on" : "") + '" data-i="' + i + '"><span class="avatar sm">' + c.name[0] + '</span><span class="tx"><b>' + esc(c.name) + '</b><small>' + (last[0] === "out" ? "You: " : "") + esc(last[1]) + '</small></span><span class="meta2"><small>' + c.time + '</small>' + (c.unread ? '<i>' + c.unread + '</i>' : "") + '</span></button>'; }).join("")
        : '<p class="muted small" style="padding:1rem">No chats match.</p>';
      $$(".chatrow").forEach(function (b) { b.onclick = function () { open(MOCK.chats[+b.dataset.i]); }; });
    }
    function open(c) {
      st.cur = c; c.unread = 0; list();
      $("#wa-pane").innerHTML = '<div class="chead"><span class="avatar sm">' + c.name[0] + '</span><div><b>' + esc(c.name) + '</b><small>' + esc(c.org) + ' · ' + c.num + '</small></div><span class="tag">' + c.tag + '</span><span class="sp"></span>' +
        '<button class="iconbtn" id="wa-info" title="Contact details">' + ic("user") + '</button></div><div class="cmsgs" id="wa-msgs"></div>' +
        '<form class="cin"><button type="button" class="iconbtn" id="wa-att" title="Attach">' + ic("clip") + '</button><input class="field2" id="wa-in" placeholder="Type a reply" aria-label="Reply"><button type="button" class="chip" id="wa-sugg">' + ic("spark") + 'Suggest</button><button class="send sm" title="Send"><span><svg><use href="#parrow"/></svg></span></button></form>';
      msgs();
      $(".cin").onsubmit = function (e) { e.preventDefault(); var i = $("#wa-in"); if (!i.value.trim()) { toast("Type a reply first"); i.focus(); return; } c.msgs.push(["out", i.value.trim(), "now"]); c.time = "now"; i.value = ""; msgs(); list(); toast("Sent from your WhatsApp number"); };
      $("#wa-sugg").onclick = function () { var last = c.msgs.filter(function (m) { return m[0] === "in"; }).pop(); $("#wa-in").value = /rate|price|₹/i.test(last ? last[1] : "") ? "Sir, the quotation is ready — sending it on mail in 10 minutes. Price is ₹186 per piece + GST." : /PO|delivery/i.test(last ? last[1] : "") ? "Thank you for the PO. Delivery by 24 November, I will confirm the dispatch details." : "Thank you! Let me check and get back to you today."; $("#wa-in").focus(); };
      $("#wa-att").onclick = function () { pickFile(this, "doc,media", function (f) { c.msgs.push(["out", "📎 " + f[0], "now"]); msgs(); toast("Sent " + f[0]); }); };
      $("#wa-info").onclick = function () { info(esc(c.name), esc(c.org), "user", kv([["Number", c.num], ["Tag", c.tag], ["First message", "12 Aug 2026"], ["Inquiries", c.org === "Shree Ambica Engineering" ? "INQ-0147, INQ-0142" : "—"], ["Assigned to", "Parth"]]), "sm"); };
    }
    function msgs() { var b = $("#wa-msgs"); b.innerHTML = st.cur.msgs.map(function (m) { return '<div class="msg ' + (m[0] === "out" ? "me" : "them") + '">' + esc(m[1]) + '<small>' + m[2] + '</small></div>'; }).join(""); b.scrollTop = 1e6; }
    $("#wa-q").addEventListener("input", function () { st.q = this.value.toLowerCase(); list(); });
    $("#wa-filter").onchange = function () { st.filter = this.value; list(); };
    $$("#wa-live button").forEach(function (b) { b.addEventListener("click", function () { st.hist = b.textContent.trim() === "History"; list(); }); });
    $("#wa-filters").onclick = function () { menu(this, ["Inquiry", "Customer", "Order", "Negotiating"].map(function (t) { return { label: t, icon: "list", on: function () { $("#wa-q").value = ""; st.q = ""; var keep = MOCK.chats; MOCK.chats = keep.filter(function (c) { return c.tag === t; }); list(); MOCK.chats = keep; toast("Showing tag: " + t); } }; }), "Filter by tag"); };
    $("#wa-ai").onclick = function () { menu(this, [{ label: "Suggest a reply", icon: "spark", hint: "From the open chat", on: function () { if (st.cur) $("#wa-sugg").click(); else toast("Open a chat first"); } },
      { label: "Summarize today's chats", icon: "list", on: function () { info("Today on WhatsApp", "7 chats · 3 need you", "spark", '<ul class="sum"><li><b>Mehul Shah</b> is waiting for the bracket rate (INQ-0147).</li><li><b>Anil Desai</b> sent PO-7781 — confirm the delivery date.</li><li><b>Priya Nair</b> wants the quotation again with GST.</li></ul>', "sm"); } },
      { label: "Translate the chat", icon: "pencil", on: function () { toast(st.cur ? "Translated to English" : "Open a chat first"); } }], "AI tools"); };
    $("#wa-camp").onclick = function () { form("New campaign", "A broadcast to a list, using an approved template.", "plus", '<div class="fgrid"><label>Name</label><input class="field2" value="Diwali offer — 10% on stock springs"><label>Template</label><select class="sel"><option>festival_offer (Approved)</option><option>new_catalogue (Approved)</option><option>payment_reminder (Pending)</option></select><label>Send to</label><select class="sel"><option>All customers (142)</option><option>Pump OEMs (38)</option></select><label>When</label><select class="sel"><option>Now</option><option>Tomorrow 10:00</option></select></div>', "Create campaign", function () { toast("Campaign created — it sends to 142 people"); }); };
    $$("#wa-tabs button").forEach(function (b) { b.addEventListener("click", function () {
      var t = b.textContent.trim(); $("#wa-inbox").hidden = t !== "Inbox"; var o = $("#wa-other"); o.hidden = t === "Inbox"; if (t === "Inbox") return;
      var rows = function (r, icon) { return '<ul class="runs plain">' + r.map(function (x) { return '<li data-toast="Opened ' + esc(x[0]) + '"><span class="ftile">' + ic(icon) + '</span><div style="min-width:0"><div class="t">' + esc(x[0]) + '</div><div class="m">' + esc(x[1]) + '</div></div>' + (x[2] ? '<span class="st ' + (x[3] || "ok") + '">' + x[2] + '</span>' : "") + '</li>'; }).join("") + '</ul>'; };
      o.innerHTML = '<div class="card pad2">' + ({
        Contacts: rows(MOCK.chats.map(function (c) { return [c.name + " · " + c.org, c.num + " · last message " + c.time, c.tag, "neutral"]; }), "user"),
        Templates: rows([["festival_offer", "Marketing · English, Gujarati", "Approved"], ["new_catalogue", "Marketing · English", "Approved"], ["payment_reminder", "Utility · English", "Pending", "warn"], ["order_confirmed", "Utility · English, Hindi", "Approved"]], "file"),
        Campaigns: rows([["Navratri offer", "Sent to 142 · 131 delivered · 88 read · 14 replied", "Done"], ["New catalogue", "Sent to 38 · 37 delivered · 29 read · 6 replied", "Done"]], "mail"),
        Automations: rows([["Reply after hours", "Out of office message between 8 pm and 9 am", "On"], ["New inquiry to register", "A message with \"rate\" or \"quote\" becomes an inquiry", "On"], ["Payment reminder", "3 days after the due date", "Off", "neutral"]], "clock"),
        Ads: rows([["Click-to-WhatsApp — Compression springs", "₹500 a day · 1,240 reached · 31 chats started", "Running"]], "ext"),
        Shop: rows([["Compression spring, 2 mm wire", "₹4.20 each · MOQ 1,000", "In stock"], ["Torsion spring, 90°", "₹6.80 each · MOQ 500", "In stock"], ["Leaf spring set", "₹2,150 a set", "On order", "warn"]], "box"),
        Forms: rows([["Request a quote", "Name · company · drawing upload · quantity — 18 replies", "Live"], ["Book a factory visit", "Date · people — 4 replies", "Live"]], "list"),
        Analytics: '<div class="kpis">' + [["Chats this week", "64"], ["Replied within 1 h", "82%"], ["New inquiries", "9"], ["Orders from WhatsApp", "3"]].map(function (k) { return '<div class="card kpi"><span class="label">' + k[0] + '</span><b class="mono">' + k[1] + '</b></div>'; }).join("") + '</div>',
        Settings: kv([["Number", "+91 98250 xxxxx"], ["Display name", "Kinetic Springs"], ["Business hours", "9 am – 8 pm, Mon–Sat"], ["Connection", '<span class="st ok">Connected</span>']])
      }[t]) + '</div>';
    }); });
    list();
  }

  /* ═════════════════════════ boot ═════════════════════════ */
  try { var w = localStorage.getItem("pk-wall"); if (w) document.body.dataset.wall = w; } catch (e) {}
  ({ home: homeInit, history: historyInit, artifacts: artifactsInit, settings: settingsInit, boq: function () { boqInit("boq"); }, bom: function () { boqInit("bom"); },
     gerber: gerberInit, step: stepInit, inquiry: inquiryInit, email: emailInit, leads: leadsInit, whatsapp: whatsappInit }[PAGE] || function () {})();
  route();
})();
