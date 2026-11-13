"""Sample answers for the WhatsApp platform routes (templates, campaigns, segments, import).

Answers POST /v1/whatsapp/p/<route> from memory, in the shapes the real service returns
(prism-wa's ops.py), so the Templates, Campaigns and Import screens can be built, shown and
tested offline. Reached only through `demo.handle_platform`, which is switched on with
PRISM_WHATSAPP_DEMO=1 and never in a frozen build.

STDLIB ONLY.
"""
from __future__ import annotations

import csv
import io
import re
import time
from datetime import timedelta

_PAGE: dict = {}


def _body(text: str, *samples: str) -> list:
    return [{"type": "BODY", "text": text, "example": {"body_text": [list(samples)]}}]


def _state() -> dict:
    from addons.whatsapp.demo import _iso
    if not _PAGE:
        _PAGE.update({
            "templates": [
                {"id": "t1", "name": "diwali_offer", "language": "en_US", "category": "MARKETING", "status": "APPROVED",
                 "quality": "GREEN", "reject_reason": None,
                 "components": _body("Hello {{1}}, our Diwali offer on {{2}} ends on Friday so do reply soon.", "Asha", "boundary walls")},
                {"id": "t2", "name": "order_update", "language": "en_US", "category": "UTILITY", "status": "APPROVED",
                 "quality": "GREEN", "reject_reason": None,
                 "components": _body("Hello {{1}}, your order {{2}} has shipped and will reach you tomorrow morning.", "Asha", "A-1")},
                {"id": "t3", "name": "quotation_followup", "language": "en_US", "category": "MARKETING", "status": "PENDING",
                 "quality": None, "reject_reason": None,
                 "components": _body("Hello {{1}}, a quick follow-up on quotation {{2}} that we shared with you.", "Asha", "Q-2041")},
                {"id": "t4", "name": "big_sale", "language": "en_US", "category": "MARKETING", "status": "REJECTED",
                 "quality": None, "reject_reason": "INVALID_FORMAT",
                 "components": _body("{{1}} big sale today only", "Asha")},
            ],
            "campaigns": [
                {"id": "c1", "name": "Diwali offer", "status": "done", "template_name": "diwali_offer", "total": 190, "sent": 182,
                 "failed": 8, "schedule_at": None, "created_at": _iso(timedelta(days=2))},
                {"id": "c2", "name": "Site visit reminders", "status": "scheduled", "template_name": "order_update", "total": 0,
                 "sent": 0, "failed": 0, "schedule_at": _iso(-timedelta(days=1)), "created_at": _iso(timedelta(hours=3))},
            ],
        })
    return _PAGE


LIBRARY = [
    {"key": "quotation_sent", "title": "Quotation sent", "category": "UTILITY", "language": "en_US",
     "components": _body("Hello {{1}}, thank you for your enquiry. We have prepared quotation {{2}} for your project and sent it "
                         "to your email. Please reply here if you would like to go through it together.", "Asha", "Q-2041")},
    {"key": "site_visit_confirmation", "title": "Site visit confirmation", "category": "UTILITY", "language": "en_US",
     "components": _body("Hello {{1}}, your site visit is confirmed for {{2}}. Our engineer will meet you at the project "
                         "location. Please keep the drawings ready if you have them.", "Asha", "Saturday 10 AM") + [
         {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Confirm"}, {"type": "QUICK_REPLY", "text": "Reschedule"}]}]},
    {"key": "festival_greeting", "title": "Festival greeting", "category": "MARKETING", "language": "en_US",
     "components": _body("Hello {{1}}, wishing you and your family a very happy {{2}} from all of us. Thank you for being "
                         "with us this year.", "Asha", "Diwali")},
]


def lint(d: dict) -> list:
    out = []

    def issue(sev, code, msg, where=""):
        out.append({"severity": sev, "code": code, "message": msg, "where": where, "meta_code": None})

    if not re.match(r"^[a-z0-9_]{1,512}$", d.get("name") or ""):
        issue("error", "bad_name", "The name may only use lowercase letters, numbers and underscores.", "name")
    body = next((c for c in d.get("components") or [] if c.get("type") == "BODY"), None)
    text = (body or {}).get("text") or ""
    if not text.strip():
        issue("error", "empty_body", "The body cannot be empty.", "BODY")
    if len(text) > 1024:
        issue("error", "body_too_long", "The body is %d characters; the limit is 1024." % len(text), "BODY")
    variables = re.findall(r"\{\{\s*(\d+)\s*\}\}", text)
    if variables and re.match(r"^\s*\{\{", text):
        issue("error", "variable_at_start", "The body cannot start with a variable.", "BODY")
    if variables and re.search(r"\}\}\s*$", text):
        issue("error", "variable_at_end", "The body cannot end with a variable.", "BODY")
    samples = ((body or {}).get("example") or {}).get("body_text") or [[]]
    if variables and len(samples[0]) != len(variables):
        issue("error", "missing_example", "Give a sample value for each of the %d variables." % len(variables), "BODY")
    return out


def handle(route: str, data: dict) -> dict:
    from addons.whatsapp.demo import _iso, _s
    from addons.whatsapp.license_client import PlatformError
    time.sleep(0.1)
    p, s = _state(), _s()
    from addons.whatsapp import demo_book                            # the contact book answers its own routes first
    answer = demo_book.handle(route, data, p, s)
    if answer is None:
        from addons.whatsapp import demo_campaigns, demo_enterprise, demo_forms, demo_inbox, demo_media, demo_shop, demo_templates, demo_usage
        answer = demo_media.handle(route, data, p, s)
        if answer is None:
            answer = demo_templates.handle(route, data, p, s)
        if answer is None:
            answer = demo_usage.handle(route, data, p, s)
        if answer is None:
            answer = demo_inbox.handle(route, data, p, s)
        if answer is None:
            answer = demo_campaigns.handle(route, data, p, s)
        if answer is None:
            answer = demo_shop.handle(route, data, p, s)
        if answer is None:
            answer = demo_forms.handle(route, data, p, s)
        if answer is None:
            answer = demo_enterprise.handle(route, data, p, s)
    if answer is not None:
        return answer

    if route == "templates/list":
        return {"templates": [dict(t) for t in p["templates"]]}
    if route == "templates/library":
        return {"library": list(LIBRARY)}
    if route == "templates/lint":
        issues = lint(data)
        return {"issues": issues, "valid": not any(i["severity"] == "error" for i in issues)}
    if route == "templates/create":
        issues = lint(data)
        if any(i["severity"] == "error" for i in issues):
            raise PlatformError("That template has problems.", "template_invalid", {"issues": issues})
        # the same name and language is a resubmission: it replaces the old one, as at Meta
        p["templates"] = [t for t in p["templates"] if (t["name"], t["language"]) != (data["name"], data.get("language", "en_US"))]
        p["seq"] = p.get("seq", 10) + 1
        p["templates"].append({"id": "t%d" % p["seq"], "name": data["name"], "language": data.get("language", "en_US"),
                               "category": data["category"], "status": "PENDING", "quality": None, "reject_reason": None,
                               "components": data["components"]})
        return {"id": "t%d" % p["seq"], "status": "PENDING", "issues": issues}
    if route == "templates/sync":
        return {"synced": len(p["templates"])}
    if route == "templates/delete":
        t = next((x for x in p["templates"] if x["id"] == data.get("template_id")), None)
        if t is None:
            raise PlatformError("That template is not in this workspace.", "unknown_template", {})
        if any(c["template_name"] == t["name"] and c["status"] in ("scheduled", "sending", "paused") for c in p["campaigns"]):
            raise PlatformError("A campaign that is scheduled, sending or paused uses this template. Cancel that campaign first.",
                                "template_invalid", {"issues": [{"severity": "error", "code": "in_use", "where": "name", "meta_code": None,
                                                                 "message": "A campaign that is scheduled, sending or paused uses this template. Cancel that campaign first."}]})
        p["templates"].remove(t)
        return {"deleted": True}

    if route == "segments/list":
        return {"segments": [{"id": x["id"], "name": x["name"], "dynamic": True, "size": 3,
                              "filter": {"field": "tags", "op": "has_any", "value": x["filter"].get("tags", [])}} for x in s["segments"]]}

    if route == "segments/count":
        return {"count": _count(data.get("filter") or {}, s)}
    if route == "segments/save":
        flt = data.get("filter") or {}
        s["segments"].append({"id": "s%d" % (len(s["segments"]) + 1), "name": data["name"],
                              "filter": {"tags": list(flt.get("value") or []) if flt.get("field") == "tags" else []}})
        return {"segment_id": s["segments"][-1]["id"]}
    if route == "segments/delete":
        s["segments"] = [x for x in s["segments"] if x["id"] != data.get("segment_id")]
        return {"deleted": True}

    if route == "campaigns/reschedule":
        c = next((x for x in p["campaigns"] if x["id"] == data.get("campaign_id")), None)
        if c is None or c["status"] != "scheduled":
            raise PlatformError("Only a scheduled campaign can be moved.", "bad_state", {})
        c["schedule_at"] = data["schedule_at"]
        return {}
    if route == "campaigns/list":
        return {"campaigns": sorted(p["campaigns"], key=lambda c: c["created_at"], reverse=True)}
    if route in ("campaigns/create", "campaigns/preflight", "campaigns/launch"):
        return _campaign(route, data, p, s, _iso, PlatformError)
    if route in ("campaigns/pause", "campaigns/resume", "campaigns/cancel"):
        c = next((x for x in p["campaigns"] if x["id"] == data.get("campaign_id")), None)
        if c:
            c["status"] = {"campaigns/pause": "paused", "campaigns/resume": "sending", "campaigns/cancel": "cancelled"}[route]
        return {}
    if route == "campaigns/report":
        c = next((x for x in p["campaigns"] if x["id"] == data.get("campaign_id")), p["campaigns"][0])
        sent = c["sent"]
        return {"report": {
            "campaign": {"id": c["id"], "name": c["name"], "status": c["status"], "template": c["template_name"]},
            "counts": {"recipients": c["total"], "queued": 0, "skipped": 0, "sent": sent, "delivered": int(sent * .94),
                       "read": int(sent * .61), "replied": int(sent * .12), "clicked": int(sent * .09), "clicks": int(sent * .11),
                       "failed": c["failed"]},
            "rates": {"delivered": 94.0, "read": 61.0, "replied": 12.0, "clicked": 9.0},
            "billable": {"marketing": sent}, "spend_estimate": {"inr": round(sent * 0.8631 * 1.18, 2), "is_estimate": True}}}

    if route == "contacts/import":
        rows = list(csv.DictReader(io.StringIO(data.get("csv") or "")))

        def digits(r):
            return "".join(ch for ch in str(r.get("Mobile") or r.get("Phone") or "") if ch.isdigit())
        good = [r for r in rows if len(digits(r)) >= 10]
        bad = [(i + 2, r) for i, r in enumerate(rows) if r not in good]
        return {"report": {"rows": len(rows), "created": len(good), "updated": 0, "invalid": len(bad),
                           "consent_recorded": len(good) if data.get("attest_consent") else 0, "kept_opted_out": 0,
                           "errors": [{"row": n, "error": "%r is not a valid phone number" % (r.get("Mobile") or r.get("Phone") or "")} for n, r in bad][:20],
                           "warnings": []}}
    if route == "contacts/export":
        head = "Name,Mobile,Email,Tags\n"
        return {"csv": head + "\n".join("%s,%s,%s,%s" % (c["name"], c["phone"], c["email"], "|".join(c["tags"])) for c in s["contacts"])}
    if route == "numbers/list":
        return {"numbers": list(p.setdefault("numbers", [{"id": "n1", "display": "+91 98765 43210", "status": "CONNECTED", "quality": "GREEN"}]))}
    if route == "onboarding/link":
        return {"state": "demo", "path": "/onboarding?state=demo", "url": "https://example.com/onboarding?state=demo"}
    if route == "onboarding/attach":
        return {"waba_id": str(data.get("waba_id") or ""), "phone_number_id": str(data.get("phone_number_id") or ""), "registered": True, "subscribed": True, "errors": []}
    from addons.whatsapp import demo_automation, demo_flows     # the chatbot builder first, then the team inbox, stores, keys, ads, AI agents, repeats
    answer = demo_flows.handle(route, data, p, s)
    if answer is not None:
        return answer
    return demo_automation.handle(route, data, p, s)


def _tags_of(flt: dict, s: dict):
    """The tags a filter in the shapes the screens send asks for; None means everyone."""
    if flt.get("field") == "tags":
        return set(flt.get("value") or [])
    if flt.get("field") == "segment":
        seg = next((x for x in s["segments"] if x["id"] == flt.get("value")), None)
        return set(((seg or {}).get("filter") or {}).get("tags", [])) or None
    if "tags" in flt:
        return set(flt["tags"]) or None
    return None


def _count(flt: dict, s: dict) -> int:
    if flt.get("field") == "campaign" or "not" in flt:
        return 3                                             # who read / replied / clicked: a fixed sample
    tags = _tags_of(flt, s)
    return len([c for c in s["contacts"] if not c["opt_out"] and (not tags or tags & set(c["tags"]))])


def _campaign(route, data, p, s, _iso, PlatformError) -> dict:
    if route == "campaigns/create":
        cid = "c%d" % (len(p["campaigns"]) + 1)
        p["campaigns"].append({"id": cid, "name": data["name"], "status": "draft", "template_name": data["template_name"], "total": 0, "sent": 0,
                               "failed": 0, "schedule_at": data.get("schedule_at"), "created_at": _iso(timedelta(0)),
                               "variables": dict(data.get("variables") or {}), "audience": dict(data.get("audience") or {})})
        return {"campaign_id": cid}
    c = next((x for x in p["campaigns"] if x["id"] == data.get("campaign_id")), None)
    if c is None:
        raise PlatformError("That campaign is not in this workspace.", "unknown_campaign", {})
    report = _preflight(c, p, s)
    if route == "campaigns/preflight":
        return {"preflight": report}
    if not report["ok"]:
        raise PlatformError("; ".join(b["message"] for b in report["blocking"]), "preflight_failed", {"preflight": report})
    n = report["recipients"]
    scheduled = bool(c.get("schedule_at"))
    c.update(status="scheduled" if scheduled else "done", total=n, sent=0 if scheduled else n)
    return {"status": "scheduled" if scheduled else "sending", "queued": n}


def _preflight(c: dict, p: dict, s: dict) -> dict:
    tmpl = next((t for t in p["templates"] if t["name"] == c["template_name"]), None)
    audience = c.get("audience") or {}
    if audience.get("segment_id"):
        n = _count({"field": "segment", "op": "in", "value": audience["segment_id"]}, s)
    elif audience.get("filter"):
        n = _count(audience["filter"], s)
    else:
        n = _count({"tags": list(audience.get("tags") or [])}, s)
    blocking, warnings = [], []
    if tmpl is None:
        blocking.append({"code": "template_unknown", "message": "That template is not known for this account. Sync your templates first."})
    elif tmpl["status"] != "APPROVED":
        blocking.append({"code": "template_not_approved", "message": "The template is %s; only an approved template can be sent." % tmpl["status"].lower()})
    if tmpl:
        for v in sorted(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", tmpl["components"][0].get("text", "")))):
            if v not in (c.get("variables") or {}):
                blocking.append({"code": "variable_unmapped", "message": "Template variable {{%s}} has no value. Choose a field, an attribute or text." % v})
    if not n:
        blocking.append({"code": "no_recipients", "message": "Nobody in this audience can be messaged (everyone is opted out, blocked or unreachable)."})
    left_out = len([x for x in s["contacts"] if x["opt_out"]])
    if left_out:
        warnings.append({"code": "opted_out_removed", "message": "%d people were left out: opted out, blocked or without a number." % left_out})
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings, "recipients": n, "opted_out_removed": left_out,
            "cost": {"category": (tmpl or {}).get("category", "MARKETING"), "per_message": 0.8631, "gst": 0.18, "currency": "INR",
                     "recipients": n, "total": round(n * 0.8631 * 1.18, 2), "is_estimate": True,
                     "basis": "third-party per-message rates plus 18% GST; confirm against Meta's rate card"}}
