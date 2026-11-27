"""Sample answers for the Analytics tab, Plan and usage, Business profile, the number's limits, webhooks and the Inbox's live updates, in
the shapes prism-wa's ops_usage.py returns.

Reached only through demo_platform.handle (PRISM_WHATSAPP_DEMO=1, never in a frozen build). The numbers are made up, but they add up: the
days sum to the totals, the categories to the spend, the team to the replies.

STDLIB ONLY.
"""
from __future__ import annotations

import csv
import io
import time
import uuid
from datetime import datetime, timedelta, timezone

from addons.whatsapp.license_client import PlatformError

RATES = {"MARKETING": 0.8631, "UTILITY": 0.115, "AUTHENTICATION": 0.115, "SERVICE": 0.0}
GST = 0.18
EVENTS = {"message.received": "A customer sent a message", "message.status": "A message you sent was delivered, read or failed",
          "chat.handoff": "A chat needs a person", "campaign.completed": "A campaign finished sending", "contact.opt_in": "A contact opted in",
          "contact.opt_out": "A contact opted out", "template.status": "Meta approved, rejected or changed a template",
          "flow.response": "A customer finished a form or flow", "payment.status": "A payment was made, failed or refunded"}
TIER_LIMITS = {"TIER_50": 50, "TIER_250": 250, "TIER_1K": 1000, "TIER_2K": 2000, "TIER_10K": 10000, "TIER_100K": 100000, "TIER_UNLIMITED": None}
LIMITS = {"free": {"tags": 10, "attributes": 5, "segments": 0, "agents": 1, "mps": 40, "webhooks": 0, "flows": 0, "ai_messages": 0, "storage_mb": 1024},
          "basic": {"tags": 10, "attributes": 5, "segments": 2, "agents": 6, "mps": 40, "webhooks": 0, "flows": 0, "ai_messages": 0, "storage_mb": 1024},
          "pro": {"tags": 100, "attributes": 20, "segments": 10, "agents": 6, "mps": 40, "webhooks": 0, "flows": 5, "ai_messages": 0, "storage_mb": 5120},
          "premium": {"tags": 250, "attributes": 50, "segments": 50, "agents": 10, "mps": 250, "webhooks": 1, "flows": 20, "ai_messages": 1000, "storage_mb": 5120},
          "unlimited": {"tags": 500, "attributes": 100, "segments": 50, "agents": 201, "mps": 1000, "webhooks": 3, "flows": 50, "ai_messages": 5000, "storage_mb": 10240}}
ORDER = ("free", "basic", "pro", "premium", "unlimited")
LABELS = {"free": "Free", "basic": "Basic", "pro": "Pro", "premium": "Premium", "unlimited": "Unlimited"}
# The catalogue prism-wa's plans.catalogue() returns (27-Nov-2026), for the Compare plans screen in demo mode. A copy:
# demo mode is stdlib-only and never talks to prism-wa. Flows and AI replies come with the add-ons, not a tier.
_TIER_FEATURES = {
    "free": ["ads_manager", "integrations"],
    "basic": ["broadcast", "multi_agent", "transfer", "template_api", "ads_manager", "integrations"],
}
_TIER_FEATURES["pro"] = _TIER_FEATURES["basic"] + ["scheduler", "csv_scheduler", "click_tracking", "budget_analytics", "project_api",
                                                  "agent_rules", "access_control", "auto_retry", "flow_delay", "commerce", "forms"]
_TIER_FEATURES["premium"] = _TIER_FEATURES["pro"] + ["number_masking", "reports_download", "template_ttl", "webhooks", "duplicate_csv",
                                                    "multi_ad_flow", "priority_support", "turbo_onboarding"]
_TIER_FEATURES["unlimited"] = _TIER_FEATURES["premium"] + ["dedicated_manager"]
_TIER_FEATURES["enterprise"] = _TIER_FEATURES["unlimited"] + ["sso", "audit_log", "sla_support"]
_FEATURE_LABELS = (
    ("broadcast", "Broadcasting & retargeting"), ("multi_agent", "Multi-agent live chat"), ("transfer", "Agent transfer & manager monitoring"),
    ("template_api", "Template message APIs"), ("ads_manager", "Click-to-WhatsApp ads manager"),
    ("integrations", "Shopify, WooCommerce & other integrations"), ("scheduler", "Campaign scheduler"), ("csv_scheduler", "CSV campaign scheduler"),
    ("click_tracking", "Campaign click tracking"), ("budget_analytics", "Campaign budget & analytics"), ("project_api", "Project APIs"),
    ("agent_rules", "Custom agent rules"), ("access_control", "User access control"), ("auto_retry", "Automatic failed-message retry"),
    ("flow_delay", "Time delay & timeout in chatbot flows"), ("commerce", "Shop, catalog & payments"), ("forms", "WhatsApp forms"),
    ("number_masking", "Number masking"), ("reports_download", "Download reports"), ("template_ttl", "Template TTL"), ("webhooks", "Webhooks"),
    ("duplicate_csv", "Duplicate contacts in a CSV broadcast"), ("multi_ad_flow", "Several ads into one chatbot flow"),
    ("priority_support", "Priority support"), ("turbo_onboarding", "Turbo onboarding"), ("dedicated_manager", "Dedicated account manager"),
    ("sso", "Company sign-in (SSO)"), ("audit_log", "Audit log"), ("sla_support", "SLA-backed support"))
_LIMIT_LABELS = (("agents", "Agent seats (with the owner)"), ("mps", "Messages a second"), ("tags", "Tags"), ("attributes", "Custom attributes"),
                 ("segments", "Audience segments"), ("webhooks", "Webhooks"), ("storage_mb", "Media storage (MB)"))
_PRICES = {"free": 0, "basic": 1500, "pro": 3200, "premium": 9100, "unlimited": 45000, "enterprise": None}
_TAGLINES = {"free": "WhatsApp API free for life", "basic": "Get started fast", "pro": "Growth marketer", "premium": "Expert marketer",
             "unlimited": "Everything, no limits", "enterprise": "Built for your scale"}


def catalogue() -> dict:
    tiers = []
    for p in ORDER + ("enterprise",):
        lim = LIMITS.get(p) or {k: None for k, _ in _LIMIT_LABELS}
        tiers.append({"plan": p, "label": LABELS.get(p, "Enterprise"), "tagline": _TAGLINES[p], "price": _PRICES[p],
                      "limits": {k: lim.get(k) for k, _ in _LIMIT_LABELS}, "features": [f for f, _ in _FEATURE_LABELS if f in _TIER_FEATURES[p]]})
    return {"tiers": tiers, "features": [{"key": k, "label": v} for k, v in _FEATURE_LABELS],
            "limits": [{"key": k, "label": v} for k, v in _LIMIT_LABELS],
            "addons": [{"addon": "chatbot", "label": "Chatbot flows", "price": 2500, "features": ["flows"], "limits": {"flows": 5}},
                       {"addon": "ai_agent", "label": "AI agent", "price": 1350, "features": ["ai_agent"], "limits": {"ai_messages": 1000}},
                       {"addon": "seat", "label": "Extra agent seat", "price": 750, "features": [], "limits": {"agents": 1}}],
            "billing_discount": {"monthly": 0, "quarterly": 5, "yearly": 10}, "currency": "INR"}
VERTICALS = ("UNDEFINED", "OTHER", "AUTO", "BEAUTY", "APPAREL", "EDU", "ENTERTAIN", "EVENT_PLAN", "FINANCE", "GROCERY", "GOVT", "HOTEL", "HEALTH",
             "NONPROFIT", "PROF_SERVICES", "RETAIL", "TRAVEL", "RESTAURANT", "NOT_A_BIZ")
_ROUTES = ("usage/", "plan/", "reports/", "numbers/limits", "numbers/refresh", "profile/", "webhooks/", "inbox/changes")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text, default: datetime) -> datetime:
    if not text:
        return default
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise PlatformError("That date does not look right.", "bad_range", {}) from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _range(d: dict) -> tuple:
    until = _parse(d.get("until"), _now() + timedelta(seconds=1))
    since = _parse(d.get("since"), until - timedelta(days=30))
    if until <= since:
        raise PlatformError("The end of the range must be after its start.", "bad_range", {})
    if (until - since).days > 400:
        raise PlatformError("Pick a range of at most 400 days.", "range_too_long", {})
    return since, until


def _series(since: datetime, until: datetime) -> list:
    """One row per day, shaped like the real overview: the same days always give the same numbers."""
    out, day = [], since.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < until:
        k = day.toordinal()
        sent = 26 + (k * 7) % 31 + (18 if day.weekday() < 5 else 0)
        out.append({"day": day.strftime("%Y-%m-%d"), "sent": sent, "delivered": int(sent * .94), "read": int(sent * (.52 + (k % 5) / 40)),
                    "failed": max(0, (k % 4) - 1), "received": 14 + (k * 5) % 19, "new_chats": 3 + k % 6, "new_contacts": 2 + k % 5})
        day += timedelta(days=1)
    return out


def _totals(days: list) -> dict:
    t = {k: sum(r[k] for r in days) for k in ("sent", "delivered", "read", "failed", "received", "new_chats", "new_contacts")}
    pct = lambda n: round(100.0 * n / t["sent"], 1) if t["sent"] else 0.0                  # noqa: E731
    t.update(handoffs=max(1, len(days) // 3), delivered_rate=pct(t["delivered"]), read_rate=pct(t["read"]), failed_rate=pct(t["failed"]))
    return t


def _p(p: dict) -> dict:
    return p.setdefault("usage", {"rates": {}, "profile": {
        "about": "Compound walls, gates and sheds, built on time.", "address": "12 Alkapuri Society, Vadodara, Gujarat", "description":
        "Patel Constructions builds boundary walls, industrial sheds and gates for factories and homes across Gujarat.", "email": "hello@patelconstructions.in",
        "websites": ["https://patelconstructions.in"], "vertical": "PROF_SERVICES", "profile_picture_url": ""},
        "webhooks": [], "deliveries": [], "cursor": 1})


def _rates(p: dict) -> dict:
    return {**RATES, **{k: v for k, v in _p(p)["rates"].items()}}


def _usage(p: dict, since: datetime, until: datetime) -> dict:
    days = _series(since, until)
    card = _rates(p)
    split = {"MARKETING": .46, "UTILITY": .44, "SERVICE": .10}
    by, rows = {}, []
    for r in days:
        cats = {}
        for cat, share in split.items():
            n = int(r["sent"] * share)
            billable = 0 if cat == "SERVICE" else n
            cats[cat] = {"messages": n, "billable": billable, "cost": round(billable * card.get(cat, 0), 4)}
            c = by.setdefault(cat, {"category": cat, "messages": 0, "billable": 0, "cost": 0.0, "rate": card.get(cat, 0)})
            c["messages"] += n
            c["billable"] += billable
            c["cost"] = round(c["cost"] + cats[cat]["cost"], 4)
        rows.append({"day": r["day"], "messages": sum(v["messages"] for v in cats.values()), "billable": sum(v["billable"] for v in cats.values()),
                     "cost": round(sum(v["cost"] for v in cats.values()), 4), "by_category": cats})
    cost = round(sum(c["cost"] for c in by.values()), 2)
    return {"range": {"since": since.isoformat(), "until": until.isoformat()}, "days": rows, "by_category": sorted(by.values(), key=lambda c: -c["cost"]),
            "totals": {"messages": sum(c["messages"] for c in by.values()), "billable": sum(c["billable"] for c in by.values()), "cost": cost,
                       "cost_with_gst": round(cost * (1 + GST), 2)}, "rates": card, "gst": GST, "is_estimate": True}


def _agents(p: dict, days: list) -> list:
    from addons.whatsapp import demo_automation
    out = []
    for i, a in enumerate(demo_automation._auto(p)["agents"]):
        base = sum(r["sent"] for r in days) // (3 + i)
        out.append({"agent_id": a["id"], "name": a["name"], "role": a["role"], "replies": base, "chats": max(1, base // 7), "resolved": max(0, base // 9),
                    "open_now": 3 - i if i < 3 else 0, "avg_reply_seconds": 95.0 + 140 * i})
    return sorted(out, key=lambda r: -r["replies"])


def _optins(days: list) -> dict:
    rows = [{"day": r["day"], "opt_in": 2 + int(r["day"][-2:]) % 4, "opt_out": int(r["day"][-2:]) % 3} for r in days]
    return {"days": rows, "totals": {"opt_in": sum(r["opt_in"] for r in rows), "opt_out": sum(r["opt_out"] for r in rows)},
            "now": {"opted_in": 640, "opted_out": 28, "contacts": 702}, "sources": [
                {"action": "opt_in", "source": "csv_import", "count": sum(r["opt_in"] for r in rows) // 2}, {"action": "opt_in", "source": "button",
                 "count": sum(r["opt_in"] for r in rows) - sum(r["opt_in"] for r in rows) // 2}, {"action": "opt_out", "source": "keyword",
                 "count": sum(r["opt_out"] for r in rows)}]}


def _campaigns(p: dict) -> list:
    out = []
    for c in p.get("campaigns", []):
        sent = c["sent"]
        out.append({"id": c["id"], "name": c["name"], "status": c["status"], "template": c["template_name"], "recipients": c["total"], "queued": 0,
                    "skipped": 0, "sent": sent, "delivered": int(sent * .94), "read": int(sent * .6), "replied": int(sent * .12), "clicked": int(sent * .06),
                    "clicks": int(sent * .09), "failed": c["failed"], "rates": {"delivered": 94.0, "read": 60.0, "replied": 12.0, "clicked": 6.0},
                    "spend": round(sent * 0.8631 * 1.18, 2)})
    return out


def _plan(p: dict) -> str:
    """The demo workspace's plan. PRISM_WHATSAPP_DEMO_PLAN picks another (free, basic, pro...), to see a plan's locks
    without a server; demo mode itself never runs in a frozen build (demo.enabled)."""
    import os
    want = (os.environ.get("PRISM_WHATSAPP_DEMO_PLAN") or "").strip().lower()
    return p.get("plan") or (want if want in LIMITS else "") or "premium"


def _demo_addons(p: dict) -> list:
    """The demo workspace's add-ons: PRISM_WHATSAPP_DEMO_ADDONS="chatbot,ai_agent" (or "none"), else both."""
    import os
    if p.get("addons") is not None:
        return list(p["addons"])
    raw = os.environ.get("PRISM_WHATSAPP_DEMO_ADDONS")
    if raw is None:
        return ["chatbot", "ai_agent"]
    return [a for a in (x.strip() for x in raw.split(",")) if a in ("chatbot", "ai_agent")]


def _csv(header: list, rows: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def _features(p: dict) -> list:
    """The plan's features as prism-wa's plans.features_of gives them: the tier's, plus its add-ons'."""
    out = list(_TIER_FEATURES.get(_plan(p), ()))
    addons = _demo_addons(p)
    out += [f for a, f in (("chatbot", "flows"), ("ai_agent", "ai_agent")) if a in addons]
    return sorted(set(out))


def _plan_view(p: dict) -> dict:
    from addons.whatsapp import demo_media
    plan, now = _plan(p), _now()
    limits = LIMITS[plan]
    q = demo_media._quota(p)
    used = {"agents": 3, "tags": 6, "attributes": 4, "segments": 2, "flows": 3, "webhooks": len(_p(p)["webhooks"]), "ai_messages": 212, "storage_mb": q["used"] // (1024 * 1024)}
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = _usage(p, first, now + timedelta(seconds=1))
    nxt = next((x for x in ORDER[ORDER.index(plan) + 1:]), None)
    return {"plan": plan, "label": LABELS[plan], "limits": [{"key": k, "limit": limits.get(k), "used": used.get(k, 0)} for k in
                                                          ("agents", "tags", "attributes", "segments", "flows", "webhooks", "ai_messages", "storage_mb", "mps")],
            "features": _features(p), "next_plan": nxt,
            "addons": _demo_addons(p), "extra_seats": int(p.get("extra_seats") or 0), "catalogue": catalogue(),
            "month": {"label": now.strftime("%B %Y"), "totals": month["totals"], "by_category": month["by_category"]}, "storage": q,
            "ai": {"replies": 212, "limit": limits["ai_messages"], "configured": True, "month": now.strftime("%Y-%m")}, "rates": month["rates"], "gst": GST,
            "is_estimate": True}


def handle(route: str, d: dict, p: dict, s: dict):
    if not route.startswith(_ROUTES):
        return None
    u = _p(p)

    if route == "usage/summary":
        return _usage(p, *_range(d))
    if route == "usage/plan":
        return _plan_view(p)
    if route == "plan/request":                       # demo: pretend Alphakore got it
        want = d.get("want") or {}
        name = " + ".join(([LABELS.get(want.get("plan"), want.get("plan", "").title())] if want.get("plan") else [])
                          + [{"chatbot": "Chatbot flows", "ai_agent": "AI agent"}.get(a, a) for a in want.get("addons") or []])
        return {"request": {"id": 1, "offer_name": "WhatsApp " + (name or "upgrade"), "kind": "wa_plan", "status": "new"}, "created": True}
    if route in ("usage/rates", "usage/rates_save"):
        if route == "usage/rates_save":
            for k, v in (d.get("rates") or {}).items():
                if str(k).upper() not in RATES:
                    raise PlatformError("%r is not a message category." % k, "bad_rate", {})
                if v in (None, ""):
                    u["rates"].pop(str(k).upper(), None)
                elif isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1000:
                    raise PlatformError("The rate for %s must be an amount in rupees, from 0 to 1000." % str(k).title(), "bad_rate", {})
                else:
                    u["rates"][str(k).upper()] = float(v)
        return {"rates": _rates(p), "defaults": dict(RATES), "gst": GST}

    if route.startswith("reports/"):
        since, until = _range(d)
        days = _series(since, until)
        overview = {"range": {"since": since.isoformat(), "until": until.isoformat()}, "days": days, "totals": _totals(days),
                    "by_sender": [{"sender": "agent", "messages": sum(r["sent"] for r in days) // 2}, {"sender": "bot", "messages": sum(r["sent"] for r in days) // 3},
                                  {"sender": "campaign", "messages": sum(r["sent"] for r in days) // 6}]}
        agents = _agents(p, days)
        optins = _optins(days)
        if route == "reports/overview":
            return overview
        if route == "reports/agents":
            return {"range": overview["range"], "agents": agents}
        if route == "reports/optins":
            return {"range": overview["range"], **optins}
        if route == "reports/campaigns":
            return {"campaigns": _campaigns(p)}
        if route == "reports/dashboard":
            usage = _usage(p, since, until)
            return {"range": overview["range"], "overview": overview, "usage": {"totals": usage["totals"], "by_category": usage["by_category"],
                                                                                   "days": usage["days"], "is_estimate": True},
                    "agents": agents, "optins": {"totals": optins["totals"], "now": optins["now"], "days": optins["days"]}, "campaigns": _campaigns(p)[:8],
                    "open_chats": 7, "can_download": _plan(p) in ("premium", "unlimited")}
        # reports/download
        if d.get("kind") not in ("overview", "usage", "campaigns", "agents", "optins"):
            raise PlatformError("Choose one of: overview, usage, campaigns, agents, optins.", "bad_report", {})
        if _plan(p) not in ("premium", "unlimited"):
            raise PlatformError("Downloading reports is not part of the %s plan (it starts on Premium)." % LABELS[_plan(p)], "plan_feature", {"needs": "premium"})
        kind = d["kind"]
        stamp = "%s_to_%s" % (since.date(), (until - timedelta(seconds=1)).date())
        if kind == "overview":
            text = _csv(["Day", "Sent", "Delivered", "Read", "Failed", "Received", "New chats", "New contacts"],
                        [[r["day"], r["sent"], r["delivered"], r["read"], r["failed"], r["received"], r["new_chats"], r["new_contacts"]] for r in days])
        elif kind == "usage":
            text = _csv(["Day", "Messages", "Billable", "Total (Rs, estimate)"], [[r["day"], r["messages"], r["billable"], r["cost"]] for r in _usage(p, since, until)["days"]])
        elif kind == "campaigns":
            text = _csv(["Name", "Status", "Template", "Recipients", "Sent", "Delivered", "Read", "Replied", "Clicked", "Failed", "Spend (Rs, estimate)"],
                        [[c["name"], c["status"], c["template"], c["recipients"], c["sent"], c["delivered"], c["read"], c["replied"], c["clicked"], c["failed"], c["spend"]]
                         for c in _campaigns(p)])
        elif kind == "agents":
            text = _csv(["Name", "Role", "Replies", "Chats", "Resolved", "Open now", "Average reply (seconds)"],
                        [[a["name"], a["role"], a["replies"], a["chats"], a["resolved"], a["open_now"], a["avg_reply_seconds"]] for a in agents])
        else:
            text = _csv(["Day", "Opted in", "Opted out"], [[r["day"], r["opt_in"], r["opt_out"]] for r in optins["days"]])
        return {"filename": "prism-whatsapp-%s-%s.csv" % (kind, stamp), "csv": text, "rows": text.count("\n") - 1}

    if route in ("numbers/limits", "numbers/refresh"):
        row = {"id": "n1", "display": "+91 98765 43210", "status": "CONNECTED", "quality": "GREEN", "tier": "TIER_1K", "daily_limit": 1000, "unlimited": False,
               "next_limit": 10000, "name_status": "APPROVED", "verified_name": "Patel Constructions", "throughput": "STANDARD", "checked_at": _iso(_now())}
        return {"numbers": [row], "tiers": TIER_LIMITS, **({"problems": []} if route == "numbers/refresh" else {})}

    if route == "profile/get":
        return {"profile": dict(u["profile"]), "number": "+91 98765 43210", "stale": False}
    if route == "profile/save":
        prof = d.get("profile") or {}
        bad = []
        if prof.get("about") is not None and not 1 <= len((prof["about"] or "").strip()) <= 139:
            bad.append("The About line is 1 to 139 characters.")
        if len(prof.get("address") or "") > 256:
            bad.append("The address is up to 256 characters.")
        if len(prof.get("description") or "") > 512:
            bad.append("The description is up to 512 characters.")
        if prof.get("email") and "@" not in prof["email"]:
            bad.append("That email address does not look right.")
        sites = [w for w in (prof.get("websites") or []) if str(w).strip()]
        if len(sites) > 2 or any(not str(w).startswith(("http://", "https://")) for w in sites):
            bad.append("At most 2 websites, each with its full address, like https://example.com.")
        if prof.get("vertical") and str(prof["vertical"]).upper() not in VERTICALS:
            bad.append("Choose a category from the list.")
        if bad:
            raise PlatformError(" ".join(bad), "bad_profile", {})
        if prof.get("picture_asset_id"):
            from addons.whatsapp import demo_media
            found = demo_media.asset(p, prof["picture_asset_id"])
            if found["kind"] != "image" or found["mime"] not in ("image/jpeg", "image/png"):
                raise PlatformError("The profile photo must be a JPG or PNG picture.", "bad_photo", {})
            u["profile"]["profile_picture_url"] = "https://pps.whatsapp.net/demo/%s" % found["id"]
        for k in ("about", "address", "description", "email", "vertical"):
            if prof.get(k) is not None:
                u["profile"][k] = str(prof[k]).strip() if k != "vertical" else str(prof[k]).upper()
        if prof.get("websites") is not None:
            u["profile"]["websites"] = sites
        return {"profile": dict(u["profile"]), "number": "+91 98765 43210", "stale": False}

    if route == "inbox/changes":
        time.sleep(min(float(d.get("wait") or 0), 1.0))
        u["cursor"] += 0
        return {"cursor": str(u["cursor"]), "changed": False}

    # webhooks/*
    hooks = u["webhooks"]
    if route == "webhooks/events":
        return {"events": dict(EVENTS)}

    def row(h):
        return {k: v for k, v in h.items() if k != "secret"}

    if route == "webhooks/list":
        return {"endpoints": [row(h) for h in hooks], "events": dict(EVENTS)}
    if route == "webhooks/create":
        limit = LIMITS[_plan(p)]["webhooks"]
        if not limit:
            raise PlatformError("Webhooks are not part of the %s plan (it starts on Premium)." % LABELS[_plan(p)], "plan_feature", {"needs": "premium"})
        if len(hooks) >= limit:
            raise PlatformError("The %s plan allows %d webhooks." % (LABELS[_plan(p)], limit), "plan_limit", {})
        url = (d.get("url") or "").strip()
        if not url.startswith("https://"):
            raise PlatformError("The address must use https.", "insecure_url", {})
        if any(x in url for x in ("//10.", "//192.168.", "//127.", "//169.254.")):
            raise PlatformError("That address points inside a private network, which webhooks may not reach.", "private_url", {})
        events = list(dict.fromkeys(d.get("events") or []))
        if not events or any(e not in EVENTS for e in events):
            raise PlatformError("Choose at least one thing to be told about.", "no_events", {})
        secret = "whsec_" + uuid.uuid4().hex[:32]
        h = {"id": "w%d" % (len(hooks) + 1), "url": url, "description": (d.get("description") or "").strip() or None, "events": events, "enabled": True,
             "failure_count": 0, "last_status": None, "last_error": None, "last_delivery_at": None, "disabled_reason": None, "created_at": _iso(_now()), "secret": secret}
        hooks.append(h)
        return {"endpoint": row(h), "secret": secret}
    h = next((x for x in hooks if x["id"] == d.get("endpoint_id")), None)
    if route in ("webhooks/update", "webhooks/delete", "webhooks/test", "webhooks/rotate_secret") and h is None:
        raise PlatformError("That webhook is not in this workspace.", "unknown_endpoint", {})
    if route == "webhooks/update":
        ch = d.get("changes") or {}
        for k in ("url", "events", "description", "enabled"):
            if k in ch:
                h[k] = ch[k]
        if ch.get("enabled"):
            h["failure_count"], h["disabled_reason"] = 0, None
        return {"endpoint": row(h)}
    if route == "webhooks/delete":
        hooks.remove(h)
        u["deliveries"] = [x for x in u["deliveries"] if x["endpoint_id"] != h["id"]]
        return {"deleted": True}
    if route == "webhooks/rotate_secret":
        h["secret"] = "whsec_" + uuid.uuid4().hex[:32]
        return {"secret": h["secret"]}
    if route in ("webhooks/test", "webhooks/replay"):
        src = None
        if route == "webhooks/replay":
            src = next((x for x in u["deliveries"] if x["id"] == d.get("delivery_id")), None)
            if src is None:
                raise PlatformError("That delivery is not in this workspace.", "unknown_delivery", {})
            h = next(x for x in hooks if x["id"] == src["endpoint_id"])
        did = "d%d" % (len(u["deliveries"]) + 1)
        now = _now()
        u["deliveries"].insert(0, {"id": did, "endpoint_id": h["id"], "url": h["url"], "event": src["event"] if src else "ping", "state": "delivered", "attempts": 1,
                                   "response_status": 200, "error": None, "created_at": _iso(now), "delivered_at": _iso(now), "next_at": _iso(now)})
        h["last_status"], h["last_delivery_at"] = 200, _iso(now)
        return {"delivery_id": did}
    # webhooks/deliveries
    rows = [x for x in u["deliveries"] if not d.get("endpoint_id") or x["endpoint_id"] == d["endpoint_id"]]
    return {"deliveries": rows[:int(d.get("limit") or 50)]}
