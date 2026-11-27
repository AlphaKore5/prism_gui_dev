"""What the dashboard screens show, read from the same stores the rest of the
app writes.

The design's Home and Inquiry screens are full of numbers — inquiries logged,
quotes sent, win rate, recent activity. In the design those are invented
spring-manufacturer data. Here every one of them is derived from a real store:
run records under the member's runs folder, and the inquiry register CSV the
Inquiry Automation add-on maintains.

Nothing in here fabricates a figure. Where a store is missing or empty the
caller gets `None` or an empty list and is expected to show an empty state —
a dashboard that invents plausible numbers is worse than one that admits it has
nothing yet, because the first time a customer spots an invented number they
stop believing all of them.
"""
from __future__ import annotations
import json
import os
from datetime import date, datetime, timedelta

import core_bridge as CB
import identity
import paths
import workspace


# ── runs ─────────────────────────────────────────────────────────────────────
def _run_files(cfg: dict, mid: str = "") -> list[str]:
    """Newest-first paths of the member's saved run records."""
    who = mid or identity.viewing()["mid"]
    folder = workspace.runs_dir(who, cfg)
    names = []
    if os.path.isdir(folder):
        names = sorted((n for n in os.listdir(folder)
                        if n.startswith("run_") and n.endswith(".json")),
                       reverse=True)
    if not names:
        fb = paths.user_dir("runs")
        if os.path.isdir(fb):
            names = sorted((n for n in os.listdir(fb)
                            if n.startswith("run_") and n.endswith(".json")),
                           reverse=True)
            if names:
                folder = fb
    return [os.path.join(folder, n) for n in names]


def delete_runs(cfg: dict, paths: list[str], mid: str = "") -> tuple[int, list[str]]:
    """Remove saved run records. Returns (deleted, [paths that would not go]).

    Two guards, because the caller is a widget handing back paths it was
    given, and a delete that trusts a path from a widget is one refactor
    away from removing something else:

      · the file must sit in THIS member's own runs folder, resolved fresh
        through workspace.runs_dir() rather than taken on trust, and
      · it must be named `run_*.json`.

    The second guard is not pedantry. That folder is a junk drawer: the same
    directory holds the artefacts runs produced -- reel scene specs and
    their .mp4, BOQ and Gerber CSVs -- none of them named after the run that
    made them, and `main_window` globs `reel_*.json` there to find the
    latest spec. Deleting a record must never take one of those with it.

    A file that has already gone counts as deleted. `recent_runs()` lists,
    then a person clicks; the gap between is real, and it is the same race
    that makes every getmtime in this module sit inside a try.
    """
    who = mid or identity.viewing()["mid"]
    folder = workspace.runs_dir(who, cfg)
    try:
        root = os.path.realpath(folder)
    except OSError:
        return 0, list(paths)
    deleted, refused = 0, []
    for path in paths or []:
        try:
            full = os.path.realpath(path)
        except OSError:
            refused.append(path)
            continue
        name = os.path.basename(full)
        if (os.path.dirname(full) != root
                or not (name.startswith("run_") and name.endswith(".json"))):
            refused.append(path)
            continue
        try:
            os.remove(full)
        except FileNotFoundError:
            deleted += 1            # already gone is the outcome we wanted
        except OSError:
            refused.append(path)
        else:
            deleted += 1
    return deleted, refused


def _ago(stamp: float, now: float | None = None) -> str:
    """"2 hours ago" / "yesterday" / "1 week ago" — the design's phrasing."""
    now = now if now is not None else datetime.now().timestamp()
    seconds = max(0, int(now - stamp))
    minutes, hours = seconds // 60, seconds // 3600
    days = seconds // 86400
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    return datetime.fromtimestamp(stamp).strftime("%d %b")


def recent_runs(cfg: dict, limit: int = 6) -> list[dict]:
    """The last few tasks, grouped as unified journeys: First task -> Followup 1 -> Followup 2.

    A task and its subsequent follow-ups share their artifacts workspace or
    explicit follow-up chain. They collapse into a single row showing the
    parent task, total follow-up count, tools used across the entire journey,
    and latest activity time.
    """
    groups: dict[str, list[tuple[str, dict, float]]] = {}
    order: list[str] = []

    scan_max = max(limit * 5, 30)
    for path in _run_files(cfg)[:scan_max]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f) or {}
            when_stamp = os.path.getmtime(path)
        except (OSError, Exception):
            continue

        art = (record.get("artifacts") or "").strip()
        user_art_dir = ""
        try:
            user_art_dir = os.path.normpath(paths.user_dir("artifacts"))
        except Exception:
            pass

        norm_art = os.path.normpath(art) if art else ""
        if norm_art and norm_art != user_art_dir:
            key = norm_art
        else:
            key = path

        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((path, record, when_stamp))

    out = []
    for key in order:
        if len(out) >= limit:
            break
        items = groups[key]
        # Sort chronologically so index 0 is the root / initial task
        items_chrono = sorted(items, key=lambda x: x[2])
        root_path, root_rec, root_stamp = items_chrono[0]

        # Gather any followups stored inside records + legacy separate run files
        internal_fus = list(root_rec.get("followups") or [])
        if len(items_chrono) > 1:
            # Sibling run files are legacy follow-ups
            sibling_fus = len(items_chrono) - 1
        else:
            sibling_fus = 0
        total_fu_count = max(len(internal_fus), sibling_fus)

        # De-duplicate tools across root task and all follow-ups
        tools, seen_tools = [], set()
        for _, rec, _ in items_chrono:
            agents = rec.get("agents") or {}
            for tool in agents.values():
                name = (tool or "").strip()
                if name and name.lower() not in seen_tools:
                    seen_tools.add(name.lower())
                    tools.append(name)
            for fu in (rec.get("followups") or []):
                for tool in (fu.get("agents") or {}).values():
                    name = (tool or "").strip()
                    if name and name.lower() not in seen_tools:
                        seen_tools.add(name.lower())
                        tools.append(name)

        # Latest activity timestamp
        stamps = [it[2] for it in items]
        for _, rec, _ in items:
            for fu in (rec.get("followups") or []):
                if fu.get("timestamp"):
                    stamps.append(float(fu["timestamp"]))
        latest_stamp = max(stamps) if stamps else root_stamp

        when = _ago(latest_stamp)
        if total_fu_count > 0:
            when = f"{when} · {total_fu_count} follow-up{'s' if total_fu_count != 1 else ''}"

        # Which of those tools actually worked in the person's browser, so a
        # screen can name them (a step on Prism's server reads "Prism AI").
        in_browser = []
        for _, rec, _ in items_chrono:
            for part in [rec] + list(rec.get("followups") or []):
                ran_in, named = part.get("ran_in") or {}, part.get("agents") or {}
                in_browser += [named[s] for s, w in ran_in.items()
                               if w == "browser" and named.get(s)]

        latest_rec = items_chrono[-1][1]
        err = (latest_rec.get("error") or root_rec.get("error") or "").strip()

        # Initial task title and query
        title = ((root_rec.get("title") or "").strip()
                 or (root_rec.get("query") or "").strip() or "Untitled task")
        query = (root_rec.get("query") or "").strip()

        out.append({
            "title": title,
            "query": query,
            "tools": tools,
            **({"browser_tools": sorted(set(in_browser))} if in_browser else {}),
            "when": when,
            "ok": not bool(err),
            "error": err,
            "stamp": latest_stamp,
            "path": root_path,
            "followup_count": total_fu_count,
        })
    return out


def run_counts(cfg: dict, days: int = 7) -> tuple[int, int]:
    """(finished, failed) over the last `days`, for the Home stat cards."""
    cutoff = datetime.now().timestamp() - days * 86400
    done = failed = 0
    for path in _run_files(cfg):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp < cutoff:
            break                       # newest-first, so the rest are older
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f) or {}
        except Exception:
            continue
        if record.get("error"):
            failed += 1
        else:
            done += 1
    return done, failed


def runs_per_day(cfg: dict, days: int = 7) -> list[int]:
    """A run count per day, oldest first — the Home sparklines.

    Real counts, so a quiet week draws a flat line rather than the design's
    decorative staircase. That is the honest picture and it is also the useful
    one: a flat line is itself worth seeing.
    """
    today = date.today()
    buckets = {today - timedelta(days=n): 0 for n in range(days)}
    oldest = datetime.combine(min(buckets), datetime.min.time()).timestamp()
    for path in _run_files(cfg):
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if stamp < oldest:
            break
        day = datetime.fromtimestamp(stamp).date()
        if day in buckets:
            buckets[day] += 1
    return [buckets[today - timedelta(days=n)] for n in range(days - 1, -1, -1)]


# ── the inquiry register ─────────────────────────────────────────────────────
def register_rows(cfg: dict) -> list[dict]:
    """Every row of the inquiry register, or [] if the add-on isn't set up
    (or isn't in this build).

    Swallows failure on purpose: the register is a CSV on a shared drive that
    may be open in Excel, missing, or on a disconnected mount. None of those
    should stop Home from drawing — they just mean there is nothing to show.
    """
    try:
        from addons import registry
        if registry.by_key("inquiry") is None:
            return []     # this build has no Inquiry add-on: never read its register
        from inquiry_config import settings_of
        folder = (settings_of(cfg) or {}).get("folder", "")
        if not folder:
            return []
        paths = CB.get_mailflow().Paths(folder)
        return CB.get_register().load(paths.register_csv)
    except Exception:
        return []


def needs_you(cfg: dict, rows: list[dict] | None = None) -> dict:
    """The four things the owner opens Prism for, as counts — the launcher's
    "What needs you today" card and its deep links into the working window.

        to_quote   inquiries with no quotation yet (Status New)
        waiting    quotations sent and not answered (Quoted / Following up)
        due        of those, the ones due a reminder today
        replies    customer answers not yet applied to the register
        orders     purchase orders (by mail, or a "yes" waiting for its PO)
        sent_today what Prism sent for them today

    Zeros — never an exception — when nothing is set up, the register is
    unreadable, or the worklist folder does not exist yet: this feeds a
    screen that must always draw.
    """
    rows = register_rows(cfg) if rows is None else rows
    out = {"to_quote": 0, "waiting": 0, "due": 0, "replies": 0, "orders": 0,
           "sent_today": 0}
    try:
        from inquiry_config import settings_of
        settings = settings_of(cfg) or {}
        reg = CB.get_register()
        status = lambda r: (r.get("Status") or "").strip() or reg.NEW  # noqa: E731
        out["to_quote"] = sum(1 for r in rows if status(r) == reg.NEW)
        out["waiting"] = sum(1 for r in rows
                             if status(r) in (reg.QUOTED, reg.FOLLOWING_UP))
        out["due"] = len(reg.awaiting_followup(
            rows,
            after_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3)))
        accepted = sum(1 for r in rows if status(r) == reg.ACCEPTED)
        folder = settings.get("folder", "")
        if folder:
            wl = CB.get_worklist()
            data = wl.load(folder)
            out["replies"] = len(wl.pending(data, "replies"))
            pending_orders = wl.pending(data, "orders")
            covered = {e.get("inquiry_no", "") for e in pending_orders}
            out["orders"] = len(pending_orders) + sum(
                1 for r in rows if status(r) == reg.ACCEPTED
                and r.get("Inquiry no", "") not in covered)
            today = date.today().isoformat()
            out["sent_today"] = sum(1 for e in data.get("sent", [])
                                    if e.get("date") == today)
        else:
            out["orders"] = accepted
    except Exception:
        pass
    return out


def month_summary(cfg: dict, rows: list[dict] | None = None) -> dict | None:
    """This month's figures for the launcher's plain table, straight off
    register.summarise(). None when there is no register at all."""
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return None
    reg = CB.get_register()
    today = date.today()
    try:
        month = reg.summarise(rows, since=today.replace(day=1))
    except Exception:
        return None
    return {
        "received": month.received,
        "quoted": month.quoted,
        "quoted_value": rupees(month.quoted_value),
        "converted": month.converted,
        "converted_value": rupees(month.converted_value),
        "conversion": month.conversion,
        "waiting": month.waiting,
        "reasons": dict(month.reasons or {}),
        "month": today.strftime("%B %Y"),
    }


def inquiry_stats(cfg: dict, rows: list[dict] | None = None) -> dict | None:
    """The four figures the Inquiry screen leads with, and the two Home shows.

    Returns None when the add-on has never been set up, so the caller can show
    the "attach a mailbox to begin" state rather than a wall of zeroes — zero
    open inquiries and no register at all mean very different things.
    """
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return None
    reg = CB.get_register()
    today = date.today()
    month = summary = None
    try:
        month = reg.summarise(rows, since=today.replace(day=1))
        summary = reg.summarise(rows, since=today - timedelta(days=90))
        week = reg.summarise(rows, since=today - timedelta(days=7))
        waiting = reg.awaiting_followup(rows)
    except Exception:
        return None
    open_now = sum(1 for r in rows
                   if (r.get("Status") or "").strip() in reg.OPEN_STATUSES)
    return {
        "open": open_now,
        "quoted_value": rupees(month.quoted_value, compact=True),
        "waiting": len(waiting),
        "win_rate": summary.conversion,
        "logged_week": week.received,
        "quoted_week": week.quoted,
    }


def inquiries_per_day(cfg: dict, rows: list[dict] | None = None,
                      days: int = 7) -> list[int]:
    """Inquiries received per day, oldest first — the Home sparkline.

    Off "Date received", so a row whose date will not parse is simply not
    counted rather than being bucketed to today; a mis-dated row inflating
    today's bar would be worse than a bar one short.
    """
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return []
    reg = CB.get_register()
    today = date.today()
    buckets = {today - timedelta(days=n): 0 for n in range(days)}
    for row in rows:
        when = reg.parse_date(row.get("Date received", ""))
        if when in buckets:
            buckets[when] += 1
    return [buckets[today - timedelta(days=n)] for n in range(days - 1, -1, -1)]


def register_view(cfg: dict, rows: list[dict] | None = None) -> list[dict]:
    """The register, shaped for the design's table row."""
    rows = register_rows(cfg) if rows is None else rows
    reg = CB.get_register()
    out = []
    for row in rows:
        status = (row.get("Status") or "").strip()
        out.append({
            "num": row.get("Inquiry no", ""),
            "customer": row.get("Customer", ""),
            "item": row.get("Product asked", ""),
            "qty": row.get("Quantity", ""),
            "amount": rupees(row.get("Quotation value")),
            # The figure behind the formatting, so the AMOUNT column sorts as
            # money and not as the string "₹2,10,000" — which would file
            # ₹9,000 above ₹10,00,000.
            "amount_raw": _amount_of(row.get("Quotation value")),
            "status": status or reg.NEW,
            "tone": status_tone(status),
        })
    return out


def _amount_of(value) -> float:
    """A register amount as a plain number, or 0.0 when it will not parse."""
    try:
        return float(CB.get_register().money(value))
    except Exception:                                   # noqa: BLE001
        return 0.0


def rupees(value, compact: bool = False) -> str:
    """A register amount as the reader expects to see it.

    The register stores plain digits on purpose — a currency symbol in the CSV
    turns the whole column into text for Excel (see register.money_str). So the
    symbol and the lakh grouping are put back here, at the point of display,
    using the same quoting.indian_currency() the quote documents already use.

    `compact` gives the dashboard form — ₹8.4L, ₹1.2Cr — because a headline
    figure is read at a glance and eleven digits is not a glance.
    """
    from decimal import Decimal
    try:
        amount = CB.get_register().money(value)
    except Exception:
        amount = Decimal(0)
    if not compact:
        if not amount:
            # An inquiry nobody has quoted has no amount, and "₹0.00" reads as
            # a quote for nothing rather than as an absence.
            return "—"
        text = CB.get_quoting().indian_currency(amount)
        # Whole rupees lose the paise, per the design. A register amount is
        # never priced to the paisa, and ".00" on every row is pure noise in a
        # column you scan vertically.
        return "₹" + (text[:-3] if text.endswith(".00") else text)
    number = float(amount)
    if abs(number) >= 1e7:
        return f"₹{number / 1e7:.1f}Cr"
    if abs(number) >= 1e5:
        return f"₹{number / 1e5:.1f}L"
    if abs(number) >= 1e3:
        return f"₹{number / 1e3:.0f}K"
    return f"₹{number:.0f}"


def status_tone(status: str) -> str:
    """Which Pill tone a register status wears.

    Won is green and lost is red in every role — see theme's semantic block.
    Everything mid-flight is accent, and a brand-new untouched inquiry is
    neutral, so "needs me to do something" and "already handled" are separable
    at a glance without reading a word.
    """
    reg = CB.get_register()
    status = (status or "").strip()
    if status == reg.CONVERTED:
        return "ok"
    if status == reg.NOT_CONVERTED:
        return "err"
    if status == reg.NEW:
        return "neutral"
    return "accent"


def waiting_view(cfg: dict, rows: list[dict] | None = None) -> list[dict]:
    """Quotations that have gone quiet — the "Waiting on a reply" tab."""
    rows = register_rows(cfg) if rows is None else rows
    if not rows:
        return []
    reg = CB.get_register()
    try:
        due = reg.awaiting_followup(rows)
    except Exception:
        return []
    today = date.today()
    out = []
    for row in due:
        sent = reg.parse_date(row.get("Quotation date", "")) or today
        count = str(row.get("Reminders sent") or "0").strip() or "0"
        try:
            n = int(float(count))
        except ValueError:
            n = 0
        out.append({
            "customer": row.get("Customer", ""),
            "item": row.get("Product asked", ""),
            "sent_days": max(0, (today - sent).days),
            "reminders": (f"{n} reminder{'s' if n != 1 else ''} sent"
                          if n else "Not yet due"),
            "num": row.get("Inquiry no", ""),
        })
    return out


def filter_active_artifacts(paths: list[str]) -> list[str]:
    """Given a collection of artifact files from a task directory (which may span
    multiple iterative follow-up runs), return only the active/latest deliverables
    by filtering out superseded earlier versions of reels, specs, audio, and documents.
    """
    if not paths:
        return []

    existing = [p for p in paths if p and os.path.isfile(p)]
    try:
        existing.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        pass

    active = []
    seen_roles = set()

    for p in existing:
        ext = os.path.splitext(p)[1].lower()
        name = os.path.basename(p).lower()

        # 1. Video files (reel MP4s): keep the latest cut
        if ext in (".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"):
            if "video" not in seen_roles:
                active.append(p)
                seen_roles.add("video")
            continue

        # 2. Reel JSON specs: keep the latest spec
        if ext == ".json" and "reel" in name:
            if "reel_spec" not in seen_roles:
                active.append(p)
                seen_roles.add("reel_spec")
            continue

        # 3. Audio files (voiceovers): keep the latest voiceover
        if ext in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
            if "audio" not in seen_roles:
                active.append(p)
                seen_roles.add("audio")
            continue

        # 4. Artwork / scene images: keep each distinct scene artwork
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            import re
            m = re.search(r"(artwork\s*\d*|scene\s*\d*)", name)
            key = f"image_{m.group(1)}" if m else f"image_{name}"
            if key not in seen_roles:
                active.append(p)
                seen_roles.add(key)
            continue

        # 5. Documents (.pdf, .docx, .xlsx, .csv, .pptx): keep latest of each extension
        if ext in (".pdf", ".docx", ".xlsx", ".csv", ".pptx", ".html"):
            doc_key = f"doc_{ext}"
            if doc_key not in seen_roles:
                active.append(p)
                seen_roles.add(doc_key)
            continue

        # Other distinct files
        if name not in seen_roles:
            active.append(p)
            seen_roles.add(name)

    return active

