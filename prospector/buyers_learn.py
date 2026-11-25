"""
Find my buyers — what it learns from the owner
──────────────────────────────────────────────
Every card the owner accepts or puts away is a lesson, and a hunt that ignores it makes the same mistakes twice. The
tools that do this well (Syften and F5Bot's AI accept rule, Clay's score calibration) let the owner correct the filter
in plain words and check the scores against what actually happened. This module is that loop, with three parts:

    memory       one small record per judged card: who, where, which source, the decision and the owner's reason.
    taste        the memory, said back to the model as examples ("accepted: …, put away: … (wrong size)") in the
                 search check and in the scoring, so the next hunt judges like the owner does.
    suppression  a company the owner already put away, or already accepted into People, is not shown again, and is
                 not paid to be read again.
    report       how each source is doing: how many it gave that were accepted, how many were put away, and, from
                 People, how many accepted buyers replied. A source that is nearly all put away is named, so the
                 owner can switch it off.

Qt-free and file-free: the store keeps the memory, this module only reads and rewrites a list of plain dicts.
"""
from __future__ import annotations

import re
from collections import Counter

from . import buyers as B

# What the owner can say when they put a card away. The key is stored, the label is shown (and translated).
REASONS = (("size", "Wrong size"),
           ("place", "Wrong country or place"),
           ("competitor", "They sell the same thing"),
           ("not_buying", "Not buying what I sell"),
           ("customer", "Already my customer"),
           ("other", "Something else"))
REASON_LABEL = dict(REASONS)

MEMORY_CAP = 400                # judged cards kept, newest first
TASTE_ACCEPTED = 6              # examples of what the owner wanted, said to the model
TASTE_REJECTED = 8              # ... and of what they did not
NOTE_CHARS = 70
DECIDED_FOR_ADVICE = 6          # a source needs this many judged cards before it is named as not working
POSITIVE = ("Replied", "Interested")
NEGATIVE = ("Not Interested", "Unresponsive", "Do Not Contact", "Bad Data")
_GENERIC = ("pvt", "ltd", "llp", "inc", "private", "limited", "the", "and", "company", "india")


def reason_key(reason: str) -> str:
    """The key of a reason as stored or shown: "size" for "size" or "Wrong size"; "" when it is not one of ours (the
    model's own words, such as "vendor", or nothing)."""
    text = (reason or "").strip().casefold()
    for key, label in REASONS:
        if text in (key, label.casefold()):
            return key
    return ""


def _url_key(url: str) -> str:
    u = re.sub(r"^https?://(www\.)?", "", (url or "").strip().casefold())
    return re.sub(r"[?#].*$", "", u).rstrip("/")


def _name_key(who: str) -> str:
    words = [w for w in re.split(r"\W+", (who or "").casefold()) if w and w not in _GENERIC]
    key = "".join(words)
    return key if len(key) >= 5 else ""


def entry_of(h: "B.Hit", decision: str, reason: str, at: str) -> dict:
    return {"id": h.id, "url": _url_key(h.url), "name": _name_key(h.who), "who": h.who[:120], "channel": h.channel,
            "buyer_type": h.buyer_type, "decision": decision, "reason": reason_key(reason) or (reason or "")[:40],
            "note": " ".join((h.why or h.snippet).split())[:NOTE_CHARS], "at": at}


def remember(entries: list, hits, decision: str, reason: str, at: str, cap: int = MEMORY_CAP) -> list:
    """The memory after `hits` were given `decision`. Accepted and put-away cards are kept (newest first, a card once);
    putting a card back, or skipping it, forgets it, because the owner has not judged it."""
    entries = [e for e in entries or [] if isinstance(e, dict)]
    ids = {h.id for h in hits}
    names = {_name_key(h.who) for h in hits} - {""}
    urls = {_url_key(h.url) for h in hits} - {""}
    kept = [e for e in entries if e.get("id") not in ids and not (e.get("url") in urls and e.get("url"))
            and not (e.get("name") in names and e.get("name"))]
    if decision in (B.ACCEPTED, B.NOT_A_FIT):
        kept = [entry_of(h, decision, reason, at) for h in hits] + kept
    return kept[:cap]


def matcher(entries: list):
    """`verdict(hit) -> "rejected" | "accepted" | ""`: whether the owner already judged this company or page. A card
    is the same one when its page is, or when its company's name is (at least five letters, so "Careers" is not a name)."""
    by_url, by_name = {}, {}
    for e in entries or []:
        if not isinstance(e, dict) or e.get("decision") not in (B.ACCEPTED, B.NOT_A_FIT):
            continue
        verdict = "accepted" if e["decision"] == B.ACCEPTED else "rejected"
        if e.get("url"):
            by_url.setdefault(e["url"], verdict)
        if e.get("name"):
            by_name.setdefault(e["name"], verdict)

    def verdict(h) -> str:
        return by_url.get(_url_key(h.url)) or by_name.get(_name_key(h.who)) or ""
    return verdict


def lessons(entries: list) -> str:
    """The owner's taste, as a block for the model's prompt; "" when nothing has been judged yet."""
    acc = [e for e in entries or [] if isinstance(e, dict) and e.get("decision") == B.ACCEPTED][:TASTE_ACCEPTED]
    rej = [e for e in entries or [] if isinstance(e, dict) and e.get("decision") == B.NOT_A_FIT][:TASTE_REJECTED]
    if not (acc or rej):
        return ""
    lines = ["THE OWNER HAS ALREADY JUDGED SOME COMPANIES. Judge like they do."]
    if acc:
        lines.append("ACCEPTED (they want more like these): " + "; ".join(
            f"{e.get('who', '')}" + (f" ({e['note']})" if e.get("note") else "") for e in acc))
    if rej:
        lines.append("PUT AWAY (nothing like these): " + "; ".join(
            f"{e.get('who', '')}" + (f" - {REASON_LABEL[e['reason']]}" if e.get("reason") in REASON_LABEL else "")
            for e in rej))
        why = Counter(REASON_LABEL[e["reason"]] for e in entries if isinstance(e, dict)
                      and e.get("decision") == B.NOT_A_FIT and e.get("reason") in REASON_LABEL)
        if why:
            lines.append("Why they put companies away, most often first: "
                         + ", ".join(f"{label} (x{n})" for label, n in why.most_common(3)))
    lines.append("A company like an accepted one scores higher. A company like a put-away one is fit 30 or lower.")
    return "\n".join(lines)[:1400]


def outcomes(rows) -> dict:
    """`rows` = [(source, stage)] for each accepted buyer now in People. → {source: {"saved", "replied", "lost"}}."""
    out: dict = {}
    for source, stage in rows or ():
        o = out.setdefault(source, {"saved": 0, "replied": 0, "lost": 0})
        o["saved"] += 1
        if stage in POSITIVE:
            o["replied"] += 1
        elif stage in NEGATIVE:
            o["lost"] += 1
    return out


def report(entries: list, results: dict | None = None) -> list:
    """How each source is doing, in the order of B.CHANNELS: [{"channel", "accepted", "put_away", "replied", "saved",
    "advice"}]. `advice` is True when the owner has judged enough of a source's cards and nearly none were accepted."""
    results = results or {}
    count: dict = {}
    for e in entries or []:
        if not isinstance(e, dict) or e.get("channel") not in B.CHANNELS:
            continue
        c = count.setdefault(e["channel"], {"accepted": 0, "put_away": 0})
        if e.get("decision") == B.ACCEPTED:
            c["accepted"] += 1
        elif e.get("decision") == B.NOT_A_FIT:
            c["put_away"] += 1
    out = []
    for ch in B.CHANNELS:
        if ch not in count:
            continue
        c, r = count[ch], results.get(ch, {})
        judged = c["accepted"] + c["put_away"]
        out.append({"channel": ch, "accepted": c["accepted"], "put_away": c["put_away"],
                    "replied": r.get("replied", 0), "saved": r.get("saved", 0),
                    "advice": judged >= DECIDED_FOR_ADVICE and c["accepted"] / judged <= 0.15})
    return out
